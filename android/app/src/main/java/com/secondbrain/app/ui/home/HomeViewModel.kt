package com.secondbrain.app.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.LlamaCpp
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.InputQueueDao
import com.secondbrain.app.diag.EventLog
import com.secondbrain.app.orchestrator.ActivityEntry
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.orchestrator.Orchestrator
import com.secondbrain.app.orchestrator.PendingActions
import com.secondbrain.app.orchestrator.Tag
import com.secondbrain.app.orchestrator.Tags
import com.secondbrain.app.orchestrator.UndoToken
import com.secondbrain.app.orchestrator.Undoer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.util.UUID

/** A user submission moving through the worker queue. */
data class PendingItem(
    val id: String,
    val composed: String,
    val chips: Set<Tag>,
    val status: PendingStatus,
    val response: String? = null,
    val startedAtMs: Long? = null,
    val finishedAtMs: Long? = null,
    /** Row ID in input_queue. Null only for items added before this feature shipped. */
    val queueId: Long? = null,
)
enum class PendingStatus { QUEUED, PROCESSING, DONE, FAILED }

data class HomeState(
    val input: String = "",
    val chips: Set<Tag> = emptySet(),
    val notices: List<String> = emptyList(),
    val recent: List<ActivityEntry> = emptyList(),
    val pending: List<PendingItem> = emptyList(),
    val pendingPrompt: String? = null,
    /** Live native-stats line shown under the input while a queue item processes. */
    val sendProgress: String = "",
    /** Live one-line counts for each Home tile. Populated by [refreshTiles]. */
    val tileSummary: TileSummary = TileSummary(),
    /** Most-recent undoable result, surfaced as a chip for ~5s. */
    val undo: UndoBanner? = null,
    /** Pool of natural-language one-liners merged into the greeting card. */
    val ambientFacts: List<String> = emptyList(),
    /** Currently-displayed ambient fact shown in the greeting card. */
    val ambientCurrent: String? = null,
    /** Time-slot-aware greeting line, e.g. "Good morning, Yuva!". */
    val greeting: String = "",
)

/** Token + label + expiry for the home Undo chip (build #27). */
data class UndoBanner(
    val token: UndoToken,
    val label: String,
    val expiresAtMs: Long,
)

/** Concise count strings rendered under each tile on Home page 1. */
data class TileSummary(
    val todo: String = "—",
    val expense: String = "—",
    val buy: String = "—",
    val weight: String = "—",
    val notes: String = "—",
    val ledger: String = "—",
)

class HomeViewModel : ViewModel() {

    private val _state = MutableStateFlow(HomeState())
    val state: StateFlow<HomeState> = _state.asStateFlow()

    private var workerJob: Job? = null
    private var progressJob: Job? = null

    init {
        viewModelScope.launch { refreshRecent() }
        viewModelScope.launch { refreshTiles() }
        viewModelScope.launch { refreshAmbientFacts() }
        viewModelScope.launch { refreshGreeting() }
        viewModelScope.launch { recoverPendingQueue() }
        // Refresh on any AppStatusBus message — covers Cleared logs,
        // person added, model loaded, etc. Cheap to re-query the
        // counts; user always sees current state.
        viewModelScope.launch {
            AppStatusBus.messages.collect {
                refreshTiles()
                refreshRecent()
                refreshAmbientFacts()
                refreshGreeting()
            }
        }
        // Silent refresh — same data update without popping a toast.
        // Domain screens use AppStatusBus.refresh() for high-frequency ops
        // (checkbox toggles, etc.) so the home feed stays current.
        viewModelScope.launch {
            AppStatusBus.refreshes.collect {
                refreshTiles()
                refreshRecent()
                refreshAmbientFacts()
            }
        }
        // Refresh greeting + contextual summary every 15 min so they update
        // naturally as the day progresses (morning → afternoon → evening).
        viewModelScope.launch {
            while (true) {
                delay(15 * 60 * 1_000L)
                refreshGreeting()
                refreshAmbientFacts()
            }
        }
    }

    fun refreshGreeting() = viewModelScope.launch {
        val name = withContext(Dispatchers.IO) {
            com.secondbrain.app.data.SelfName.get(DatabaseHolder.get())
        }
        _state.update { it.copy(greeting = buildGreeting(name)) }
    }

    /** Recompute ambient facts pool + time-aware contextual summary. */
    fun refreshAmbientFacts() = viewModelScope.launch {
        val (facts, summary) = withContext(Dispatchers.IO) {
            AmbientFacts.compute() to AmbientFacts.buildContextualSummary()
        }
        _state.update { it.copy(ambientFacts = facts, ambientCurrent = summary.ifBlank { null }) }
    }

    fun refreshTiles() = viewModelScope.launch {
        val s = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            val today = java.time.LocalDate.now().toString()
            val month = today.take(7)
            val todoToday = db.readableDatabase.rawQuery(
                "SELECT COUNT(*) FROM todos WHERE status='pending' AND COALESCE(date, substr(created_at,1,10)) = ?",
                arrayOf(today)
            ).use { if (it.moveToFirst()) it.getLong(0) else 0L }
            val todoTotalPending = com.secondbrain.app.data.TodosDao.pendingCount(db)
            val expenseMonth = com.secondbrain.app.data.ExpensesDao.monthTotal(db, month)
            val buyOpen = db.readableDatabase.rawQuery(
                "SELECT COUNT(*) FROM buy_items WHERE status='open'", null
            ).use { if (it.moveToFirst()) it.getLong(0) else 0L }
            val weightPeople = db.readableDatabase.rawQuery(
                "SELECT COUNT(DISTINCT person) FROM weights", null
            ).use { if (it.moveToFirst()) it.getLong(0) else 0L }
            val notesCount = com.secondbrain.app.data.NotesDao.count(db)
            val balances = com.secondbrain.app.data.LedgerDao.balances(db)
            val owedToYou = balances.filter { it.balance > 0 }.sumOf { it.balance }
            val youOwe = balances.filter { it.balance < 0 }.sumOf { -it.balance }
            TileSummary(
                todo = "$todoToday today / $todoTotalPending total",
                expense = "₹${formatRupees(expenseMonth)} this month",
                buy = "$buyOpen to buy",
                weight = "$weightPeople people tracked",
                notes = "$notesCount notes",
                ledger = "+₹${formatRupees(owedToYou)} owed to you  ·  -₹${formatRupees(youOwe)} you owe",
            )
        }
        _state.update { it.copy(tileSummary = s) }
    }

    private fun formatRupees(v: Double): String {
        val whole = v.toLong()
        return if (kotlin.math.abs(v - whole) < 0.01) "%,d".format(whole)
               else "%,.2f".format(v)
    }

    fun onInputChanged(newText: String) {
        val reaction = Tags.reactToTyping(newText, _state.value.chips)
        _state.update {
            it.copy(
                input = reaction.newText,
                chips = reaction.activeChips,
                notices = it.notices + reaction.notices,
            )
        }
    }

    fun onChipTap(tag: Tag) {
        _state.update { it.copy(chips = Tags.toggleChip(tag, it.chips)) }
    }

    fun consumeNotices(): List<String> {
        val cur = _state.value.notices
        if (cur.isEmpty()) return emptyList()
        _state.update { it.copy(notices = emptyList()) }
        return cur
    }

    /**
     * Queue a submission. UI returns control immediately:
     *   - input text and chips are cleared
     *   - raw input is persisted to input_queue (SQLite) BEFORE the LLM runs,
     *     so a GrapheneOS process-kill during long inference doesn't lose input
     *   - a PendingItem with QUEUED status is appended to state.pending
     *   - the worker (single coroutine) starts if not already running
     */
    fun onSend() {
        val s = _state.value
        if (s.input.isBlank()) return
        val tagged = Tags.normalize(s.input.trim(), s.chips)
        val needsLlm = tagged.activeChips.isNotEmpty() &&
                !(tagged.activeChips.size == 1 && Tag.NOTE in tagged.activeChips)
        if (needsLlm && !LlamaCpp.isLoaded()) {
            AppStatusBus.emit("Model not loaded yet — waiting for auto-load.")
            return
        }

        // Clear input immediately so the user can type the next thing.
        _state.update { it.copy(input = "", chips = emptySet()) }

        viewModelScope.launch(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            // Persist FIRST — this is what survives a process kill.
            val queueId = InputQueueDao.enqueue(db, tagged.composed, tagged.activeChips)
            val item = PendingItem(
                id = UUID.randomUUID().toString(),
                composed = tagged.composed,
                chips = tagged.activeChips,
                status = PendingStatus.QUEUED,
                queueId = queueId,
            )
            _state.update { it.copy(pending = it.pending + item) }
            EventLog.info(EventLog.Category.USER, "queued submission",
                mapOf("composed" to tagged.composed,
                      "chips" to tagged.activeChips.joinToString(",") { it.raw },
                      "queue_id" to queueId))
            ensureWorker()
        }
    }

    /** Start the worker if not already running. Single instance ever. */
    private fun ensureWorker() {
        if (workerJob?.isActive == true) return
        workerJob = viewModelScope.launch { runWorker() }
    }

    private suspend fun runWorker() {
        while (true) {
            val next = _state.value.pending.firstOrNull { it.status == PendingStatus.QUEUED }
                ?: break

            // On recovery after a process kill, the model may not be loaded yet.
            // Wait up to 60 s for it before proceeding. Notes bypass the LLM
            // entirely so they don't need to wait.
            val needsLlm = next.chips.isNotEmpty() &&
                    !(next.chips.size == 1 && Tag.NOTE in next.chips)
            if (needsLlm && !LlamaCpp.isLoaded()) {
                AppStatusBus.emit("Resuming: waiting for model to load…")
                var waited = 0
                while (!LlamaCpp.isLoaded() && waited++ < 60) delay(1_000)
            }

            val db = withContext(Dispatchers.IO) { DatabaseHolder.get() }

            // Mark processing in DB so a second kill still sees this row
            // as unprocessed on the NEXT recovery pass.
            next.queueId?.let { withContext(Dispatchers.IO) { InputQueueDao.markProcessing(db, it) } }

            // Mark processing in memory
            _state.update {
                it.copy(pending = it.pending.map { p ->
                    if (p.id == next.id) p.copy(status = PendingStatus.PROCESSING, startedAtMs = System.currentTimeMillis()) else p
                })
            }
            // Spin progress poller
            progressJob?.cancel()
            progressJob = viewModelScope.launch { pollNativeStats() }

            var lastUndo: UndoToken? = null
            var succeeded = false
            val resultText = try {
                EventLog.info(EventLog.Category.ORCHESTRATOR, "submit start",
                    mapOf("composed" to next.composed))
                val r = Orchestrator.handle(next.composed, next.chips)
                EventLog.info(EventLog.Category.ORCHESTRATOR, "submit done",
                    mapOf("kind" to r.kind, "len" to r.responseText.length))
                lastUndo = r.undo
                succeeded = true
                r.responseText
            } catch (t: Throwable) {
                EventLog.throwable(EventLog.Category.ORCHESTRATOR, "submit failed", t)
                "Error: ${t.message ?: t.javaClass.simpleName}"
            }
            progressJob?.cancel()

            val finalOk = succeeded && !resultText.startsWith("Error:")
            next.queueId?.let {
                withContext(Dispatchers.IO) {
                    if (finalOk) InputQueueDao.markDone(db, it)
                    else InputQueueDao.markFailed(db, it)
                }
            }

            // Mark done in memory
            _state.update {
                it.copy(
                    pending = it.pending.map { p ->
                        if (p.id == next.id) p.copy(
                            status = if (finalOk) PendingStatus.DONE else PendingStatus.FAILED,
                            response = resultText,
                            finishedAtMs = System.currentTimeMillis(),
                        ) else p
                    },
                    sendProgress = "",
                )
            }
            refreshRecent()
            refreshAmbientFacts()

            // Surface the undo chip if the request was reversible.
            val undoSnapshot = lastUndo
            if (undoSnapshot != null) {
                val expires = System.currentTimeMillis() + 5_000
                val label = undoSnapshot.summary.ifBlank { "Undo last action" }
                _state.update { it.copy(undo = UndoBanner(undoSnapshot, label, expires)) }
                viewModelScope.launch {
                    delay(5_000)
                    _state.update { s ->
                        if (s.undo?.expiresAtMs == expires) s.copy(undo = null) else s
                    }
                }
            }

            // Slide done items off the pending list after a short pause
            // so they get absorbed into the recent feed cleanly.
            delay(300)
            _state.update { it.copy(pending = it.pending.filter { p -> p.status != PendingStatus.DONE && p.status != PendingStatus.FAILED }) }
        }
    }

    /** Reverse the most-recent reversible request. No-op if none active. */
    fun undoLast() {
        val banner = _state.value.undo ?: return
        // Optimistically clear the chip so the user gets immediate feedback.
        _state.update { it.copy(undo = null) }
        viewModelScope.launch {
            val msg = withContext(Dispatchers.IO) {
                Undoer.execute(DatabaseHolder.get(), banner.token)
            }
            AppStatusBus.emit(msg)
            refreshRecent()
            refreshTiles()
            refreshAmbientFacts()
        }
    }

    private suspend fun pollNativeStats() {
        while (_state.value.pending.any { it.status == PendingStatus.PROCESSING }) {
            val statsLine = readStatsLine()
            _state.update { it.copy(sendProgress = statsLine) }
            delay(500)
        }
    }

    private fun readStatsLine(): String {
        return try {
            val o = JSONObject(LlamaCpp.getLastStats())
            val tokensOut = o.optInt("tokens_out")
            val decodeUs = o.optLong("decode_us_total").coerceAtLeast(1)
            val tps = if (tokensOut > 0) tokensOut * 1_000_000.0 / decodeUs else 0.0
            val prefillMs = o.optLong("prefill_us") / 1000
            val promptN = o.optInt("prompt_tokens")
            buildString {
                append("prompt=$promptN  prefill=${prefillMs}ms  ")
                append("decoded=${tokensOut}  ")
                append(if (tps > 0) "@${"%.2f".format(tps)} tok/s" else "decoding…")
            }
        } catch (_: Throwable) {
            "stats unavailable"
        }
    }

    /** Cancel the currently-processing item (if any). */
    fun cancelCurrent() {
        val processing = _state.value.pending.firstOrNull { it.status == PendingStatus.PROCESSING } ?: return
        viewModelScope.launch {
            LlamaCpp.abort()
            val softOk = withTimeoutOrNull(5_000) {
                while (_state.value.pending.any { it.id == processing.id && it.status == PendingStatus.PROCESSING }) delay(100)
                true
            } != null
            if (!softOk) {
                LlamaCpp.forceUnload()
                AppStatusBus.emit("Force-unloaded the model (soft cancel didn't take).")
                _state.update {
                    it.copy(pending = it.pending.map { p ->
                        if (p.id == processing.id) p.copy(status = PendingStatus.FAILED, response = "Cancelled (force).")
                        else p
                    })
                }
            } else {
                AppStatusBus.emit("Cancelled.")
            }
        }
    }

    /**
     * On launch, find any input_queue rows that survived a process kill
     * (status = pending or processing) and re-enqueue them for processing.
     * Also prunes old done/failed rows so the table stays small.
     */
    private suspend fun recoverPendingQueue() {
        val rows = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            InputQueueDao.pruneOld(db)
            InputQueueDao.unprocessed(db)
        }
        if (rows.isEmpty()) return

        val count = rows.size
        AppStatusBus.emit("Resuming $count pending submission${if (count > 1) "s" else ""}…")
        EventLog.info(EventLog.Category.APP, "recovering input_queue",
            mapOf("count" to count))

        val items = rows.map { row ->
            val chipSet = row.chips.split(",")
                .mapNotNull { Tag.fromRaw(it.trim()) }
                .toSet()
            PendingItem(
                id = UUID.randomUUID().toString(),
                composed = row.rawInput,
                chips = chipSet,
                status = PendingStatus.QUEUED,
                queueId = row.id,
            )
        }
        _state.update { it.copy(pending = it.pending + items) }
        ensureWorker()
    }

    private fun buildGreeting(name: String?): String {
        val hour = java.time.LocalTime.now().hour
        val dow = java.time.LocalDate.now().dayOfWeek
        val base = when {
            dow == java.time.DayOfWeek.MONDAY && hour in 5..11 -> "Happy Monday"
            dow == java.time.DayOfWeek.FRIDAY && hour >= 14 -> "Happy Friday"
            (dow == java.time.DayOfWeek.SATURDAY || dow == java.time.DayOfWeek.SUNDAY) && hour in 5..10 -> "Weekend morning"
            (dow == java.time.DayOfWeek.SATURDAY || dow == java.time.DayOfWeek.SUNDAY) && hour >= 11 -> "Enjoy the weekend"
            hour in 5..11  -> "Good morning"
            hour in 12..14 -> "Good afternoon"
            hour in 15..20 -> "Good evening"
            hour in 21..22 -> "Evening"
            else            -> "Still up?"
        }
        val suffix = if (!name.isNullOrBlank())
            ", ${name.trim().replaceFirstChar { it.uppercase() }}!" else "!"
        return "$base$suffix"
    }

    private suspend fun refreshRecent() {
        val (items, pending) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            ActivityLogDao.list(db, limit = 30) to PendingActions.latestPending(db)
        }
        _state.update {
            it.copy(
                recent = items,
                pendingPrompt = pending?.let { p ->
                    "Pending: ${p.prompt} — reply with 1–${p.options.length()} or 'cancel'."
                },
            )
        }
    }
}
