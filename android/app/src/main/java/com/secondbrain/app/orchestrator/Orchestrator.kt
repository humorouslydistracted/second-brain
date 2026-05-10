package com.secondbrain.app.orchestrator

import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.embedding.EmbeddingsDao
import com.secondbrain.app.embedding.MiniLmEncoder
import com.secondbrain.app.parser.ParseResult
import com.secondbrain.app.parser.ParserPayload
import com.secondbrain.app.parser.ParserService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Single entry-point for every Home submission.
 *
 * Phase 3a flow (deliberately simple — no Tier 0 / fastpath / memo yet):
 *   1. Normalize the input through Tags (chips already enforced in UI, but
 *      we re-run for safety).
 *   2. If the user typed plain text with no `note:` chip and no other tag,
 *      fall back to "save as plain note" without ever calling the LLM —
 *      this matches the Python `note:` hard-bypass.
 *   3. Otherwise call the fine-tuned parser, validate, dispatch.
 *   4. Always insert into activity_log + request_log.
 */
data class OrchestratorResult(
    val activityId: Long,
    val responseText: String,
    val kind: String,    // 'write' | 'query' | 'note' | 'unknown'
    val undo: UndoToken? = null,
)

object Orchestrator {

    suspend fun handle(text: String, activeChips: Set<Tag>): OrchestratorResult = withContext(Dispatchers.Default) {
        // Run the entire request off Main so synchronous SQL + the
        // QueryRunner's runBlocking-on-encoder call cannot ANR. The
        // ParserService and LlamaCpp internally pin themselves to their
        // own single-thread dispatchers, so this just affects the
        // SQL/scoring/fan-out surface.
        val db = com.secondbrain.app.data.DatabaseHolder.get()
        val tStart = System.nanoTime()
        val tagged = Tags.normalize(text, activeChips)
        val log = RequestLogBuilder(userInput = tagged.composed, activeChips = tagged.activeChips)
        log.timing("normalize_ms", (System.nanoTime() - tStart) / 1_000_000)

        var responseText = ""
        var kind = "unknown"
        val undo = UndoBuilder()
        try {
            // ----- numbered-clarify resolution: highest priority -----
            // If the previous turn left a pending_actions row and this input
            // is just a number / cancel, resolve it without touching the LLM.
            if (tagged.activeChips.isEmpty()) {
                val resolved = PendingActions.tryResolve(db, tagged.composed, log)
                if (resolved != null) {
                    return@withContext finalizeAndPersist(
                        db, log, tStart, tagged, resolved, "clarify_resolution",
                    )
                }
            }

            // Hard bypass: explicit note save, no LLM. Fires only when chips
            // are EXACTLY empty or exactly {NOTE}. {ASK, NOTE} is a note
            // query and must go through the parser.
            val noteOnlyBypass = tagged.activeChips.isEmpty() ||
                (tagged.activeChips.size == 1 && Tag.NOTE in tagged.activeChips)
            if (noteOnlyBypass) {
                val body = tagged.composed.removePrefix("note:").trimStart()
                val noteText = if (body.isBlank()) "" else body
                if (noteText.isNotBlank()) {
                    val id = saveNote(db, noteText, undo)
                    log.tier("note_bypass")
                    log.sql("insert.note", "INSERT INTO notes (...)", listOf(noteText), 1, listOf(mapOf("id" to id)))
                    responseText = "Note saved."
                    kind = "note"
                } else {
                    log.tier("empty_note_bypass")
                    responseText = "Empty note ignored."
                    kind = "unknown"
                }
            } else {
                log.tier("finetuned")
                val attempt = ParserService.parse(tagged.composed)
                log.timing("parser.prompt_build_ms", attempt.promptMs)
                log.timing("parser.generate_ms", attempt.generateMs)
                log.llm(attempt.prompt, attempt.rawOutput)
                // Per-stage native stats (tokenize/prefill/decode/tok-rate
                // in microseconds, plus aborted flag and prompt size).
                // Surfaced in Copy logs so we can diagnose any "stuck"
                // or "slow" report from a single paste.
                log.sql(
                    label = "llama.native_stats",
                    statement = "(JNI getLastStats)",
                    args = emptyList(),
                    rowCount = 1,
                    sampleRows = listOf(
                        mapOf("stats_json" to attempt.nativeStats)
                    ),
                )
                when (val pr = attempt.result) {
                    is ParseResult.Fail -> {
                        log.error("parser failed: ${pr.reason}")
                        responseText = "Parser produced unusable output (${pr.reason}). Saved as plain note."
                        kind = "note"
                        saveNote(db, tagged.composed, undo)
                    }
                    is ParseResult.Ok -> {
                        responseText = when (val payload = pr.payload) {
                            is ParserPayload.Write -> {
                                kind = "write"
                                WriteRunner.run(db, payload, tagged.composed, log, undo)
                            }
                            is ParserPayload.Query -> {
                                kind = "query"
                                QueryRunner.run(db, payload, log, userText = tagged.composed)
                            }
                        }
                    }
                }
            }
        } catch (t: Throwable) {
            log.error(t.toString())
            responseText = "Error: ${t.message ?: t.javaClass.simpleName}"
            kind = "unknown"
        }
        // Lambda's final expression — withContext returns this. No bare
        // `return` here: suspend-inline lambdas reject non-local returns.
        finalizeAndPersist(db, log, tStart, tagged, responseText, kind, undo.build())
    }

    private fun finalizeAndPersist(
        db: AppDatabase,
        log: RequestLogBuilder,
        tStart: Long,
        tagged: TaggedInput,
        responseText: String,
        kind: String,
        undo: UndoToken? = null,
    ): OrchestratorResult {
        log.timing("total_ms", (System.nanoTime() - tStart) / 1_000_000)
        log.final(responseText)
        val activityId = ActivityLogDao.insert(
            db = db, input = tagged.composed, response = responseText, kind = kind,
            metadataJson = JSONObject(mapOf(
                "tier" to kind,
                "chips" to tagged.activeChips.joinToString(",") { it.raw },
            )).toString(),
        )
        log.activityId = activityId
        log.persist(db)
        return OrchestratorResult(
            activityId = activityId,
            responseText = responseText,
            kind = kind,
            undo = undo,
        )
    }

    private fun saveNote(db: AppDatabase, content: String, undo: UndoBuilder = UndoBuilder()): Long {
        // Per-day grouping + `[HH:MM:SS]` prefix lives in NotesDao so the
        // Notes-page Add button uses the exact same logic.
        val saved = com.secondbrain.app.data.NotesDao.addForToday(db, content)
        if (saved.wasInsert) {
            undo.noteRestore = NoteUndo(noteId = saved.id, previousContent = null, wasInsert = true)
            undo.embeddingNoteIds += saved.id
            undo.summary = "Undo note save"
        } else {
            undo.noteRestore = NoteUndo(
                noteId = saved.id,
                previousContent = saved.previousContent,
                wasInsert = false,
            )
            undo.summary = "Undo note append"
        }
        // Async fire-and-forget embedding. Re-embeds the WHOLE day's note
        // (replaces any previous embedding for this row).
        embeddingScope.launch {
            try {
                val vec = MiniLmEncoder.encode(saved.finalContent) ?: return@launch
                EmbeddingsDao.put(db, saved.id, saved.finalContent, vec)
            } catch (_: Throwable) {
                // Silent — embeddings are best-effort. Surfaced in Settings.
            }
        }
        return saved.id
    }

    private val embeddingScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
}
