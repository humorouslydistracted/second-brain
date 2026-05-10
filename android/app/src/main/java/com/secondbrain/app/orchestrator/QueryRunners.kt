package com.secondbrain.app.orchestrator

import android.database.sqlite.SQLiteDatabase
import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.embedding.EmbeddingsDao
import com.secondbrain.app.embedding.MiniLmEncoder
import com.secondbrain.app.parser.ParserPayload
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import kotlin.math.abs

/**
 * Executes a parser query payload against SQLite. One runner per domain,
 * each ported from the matching Python `_run_finetuned_<domain>_query`.
 *
 * Phase 3a scope: lexical/SQL retrieval only. Hybrid lexical+semantic note
 * search lands in Phase 3b alongside the ONNX MiniLM embedding port.
 */
object QueryRunner {

    suspend fun run(
        db: AppDatabase,
        payload: ParserPayload.Query,
        log: RequestLogBuilder,
        userText: String = "",
    ): String {
        if (payload.disposition == "reject") {
            return "Query not supported (${payload.reasonCode ?: "unsupported"})."
        }
        if (payload.disposition == "clarify") {
            val labels = payload.clarifyOptions.takeIf { it.isNotEmpty() }
                ?: listOf("Try a more specific phrasing")
            // Persist as a pending action so the user can reply with a number.
            // Each option becomes a "save_note" fallback (Phase 3b minimum
            // viable resolution); future versions can add domain-specific
            // re-execution via different `kind` values.
            val opts = org.json.JSONArray()
            labels.forEach { lbl ->
                opts.put(org.json.JSONObject().apply {
                    put("label", lbl); put("kind", "save_note")
                    put("args", org.json.JSONObject().apply { put("content", lbl) })
                })
            }
            opts.put(org.json.JSONObject().apply {
                put("label", "Save raw input as note instead")
                put("kind", "save_note")
                put("args", org.json.JSONObject().apply { put("content", payload.queryText ?: "") })
            })
            PendingActions.create(
                db = db, actionType = "query_clarify",
                prompt = payload.clarifyReason ?: "Query is ambiguous",
                options = opts,
            )
            return "Query is ambiguous (${payload.clarifyReason ?: "unclear"}). Pick one:\n" +
                (0 until opts.length()).joinToString("\n") { i -> "${i + 1}. ${opts.optJSONObject(i).optString("label")}" } +
                "\nReply with a number, or 'cancel'."
        }
        return when (payload.domain) {
            "expense" -> runExpense(db, payload, log)
            "buy"     -> runBuy(db, payload, log)
            "todo"    -> runTodo(db, payload, log)
            "weight"  -> runWeight(db, payload, log, userText)
            "ledger"  -> runLedger(db, payload, log)
            "note"    -> runNote(db, payload, log)
            else      -> "Unsupported domain: ${payload.domain}"
        }
    }

    // ============================================================
    // Expense
    // ============================================================
    private fun runExpense(db: AppDatabase, p: ParserPayload.Query, log: RequestLogBuilder): String {
        val r = db.readableDatabase
        val f = p.filters
        val where = mutableListOf<String>()
        val args  = mutableListOf<Any?>()
        f?.optStringSafe("description_text")?.let {
            where += "lower(description) LIKE ?"; args += "%${it.lowercase()}%"
        }
        f?.optStringSafe("exclude_description_text")?.let {
            where += "lower(description) NOT LIKE ?"; args += "%${it.lowercase()}%"
        }
        f?.optStringSafe("group")?.let {
            where += "lower(group_name) = ?"; args += it.lowercase()
        }
        f?.optStringSafe("exclude_group")?.let {
            where += "(group_name IS NULL OR lower(group_name) <> ?)"; args += it.lowercase()
        }
        when (p.intent) {
            "compare" -> {
                if (p.compareDateStart == null || p.compareDateEnd == null)
                    return "Compare range missing in parser output."
                val primary = sumExpenses(r, where, args, p.dateStart, p.dateEnd, log, "expense.compare.primary")
                val compare = sumExpenses(r, where, args, p.compareDateStart, p.compareDateEnd, log, "expense.compare.previous")
                return "Compare: ${p.dateStart}–${p.dateEnd} ${formatRupees(primary)} vs " +
                    "${p.compareDateStart}–${p.compareDateEnd} ${formatRupees(compare)}"
            }
            "list" -> {
                appendDate(where, args, p.dateStart, p.dateEnd)
                val whereSql = if (where.isEmpty()) "" else " WHERE " + where.joinToString(" AND ")
                val limit = (p.limit ?: 10).coerceIn(1, 100)
                val sql = "SELECT amount, description, date, group_name FROM expenses$whereSql " +
                    "ORDER BY COALESCE(date, created_at) DESC, id DESC LIMIT ?"
                return log.runSql("expense.list", r, sql, args + limit) { c ->
                    val rows = mutableListOf<Triple<String, String, String?>>()
                    while (c.moveToNext()) rows += Triple(
                        formatRupees(c.getDouble(0)),
                        c.getString(1),
                        c.getString(2),
                    )
                    if (rows.isEmpty()) "No expenses match." else
                        "Expenses:\n" + rows.joinToString("\n") { "${it.third ?: ""}  ${it.first} ${it.second}" }
                }
            }
            else -> {
                appendDate(where, args, p.dateStart, p.dateEnd)
                val total = sumExpenses(r, where, args, null, null, log, "expense.total")
                return "Total spend: ${formatRupees(total)}"
            }
        }
    }

    private fun sumExpenses(
        r: SQLiteDatabase, baseWhere: List<String>, baseArgs: List<Any?>,
        ds: String?, de: String?, log: RequestLogBuilder, label: String,
    ): Double {
        val where = baseWhere.toMutableList(); val args = baseArgs.toMutableList()
        appendDate(where, args, ds, de)
        val whereSql = if (where.isEmpty()) "" else " WHERE " + where.joinToString(" AND ")
        val sql = "SELECT COALESCE(SUM(amount),0) FROM expenses$whereSql"
        return log.runSql(label, r, sql, args) { c -> if (c.moveToFirst()) c.getDouble(0) else 0.0 }
    }

    // ============================================================
    // Buy
    // ============================================================
    private fun runBuy(db: AppDatabase, p: ParserPayload.Query, log: RequestLogBuilder): String {
        val r = db.readableDatabase
        val f = p.filters
        val where = mutableListOf<String>()
        val args  = mutableListOf<Any?>()
        appendDate(where, args, p.dateStart, p.dateEnd)
        val status = f?.optStringSafe("status") ?: if (p.intent == "list") "open" else null
        if (status != null) { where += "status = ?"; args += status }
        f?.optStringSafe("item_text")?.let {
            where += "lower(item_text) LIKE ?"; args += "%${it.lowercase()}%"
        }
        val whereSql = if (where.isEmpty()) "" else " WHERE " + where.joinToString(" AND ")
        val limit = (p.limit ?: 25).coerceIn(1, 100)
        val sql = "SELECT item_text, quantity_text, unit_text, status, date " +
            "FROM buy_items$whereSql ORDER BY COALESCE(date, created_at) DESC, id DESC LIMIT ?"
        return log.runSql("buy.list", r, sql, args + limit) { c ->
            val rows = mutableListOf<String>()
            while (c.moveToNext()) {
                val item = c.getString(0); val qty = c.getString(1); val unit = c.getString(2)
                val st = c.getString(3); val date = c.getString(4) ?: ""
                val q = if (!qty.isNullOrBlank()) " ($qty${unit?.let { " $it" } ?: ""})" else ""
                rows += "[$st] $date $item$q"
            }
            if (rows.isEmpty()) "No buy items match." else "Buy list:\n" + rows.joinToString("\n")
        }
    }

    // ============================================================
    // Todo
    // ============================================================
    private fun runTodo(db: AppDatabase, p: ParserPayload.Query, log: RequestLogBuilder): String {
        val r = db.readableDatabase
        val f = p.filters
        val where = mutableListOf<String>()
        val args  = mutableListOf<Any?>()
        appendDate(where, args, p.dateStart, p.dateEnd)
        // Trust the LLM's status filter. "todo list" → LLM returns "open";
        // "all todo list" / "done todos" → LLM returns null or "done".
        // We no longer force "open" as a fallback so "all todo list" works correctly.
        val status = f?.optStringSafe("status")
        if (status != null) {
            val mapped = if (status == "open") "pending" else "done"
            where += "status = ?"; args += mapped
        }
        f?.optStringSafe("text_match")?.let {
            where += "lower(content) LIKE ?"; args += "%${it.lowercase()}%"
        }
        val whereSql = if (where.isEmpty()) "" else " WHERE " + where.joinToString(" AND ")
        val limit = (p.limit ?: if (p.intent == "history") 10 else 20).coerceIn(1, 100)
        val sql = "SELECT content, status, date FROM todos$whereSql " +
            "ORDER BY (CASE WHEN status='pending' THEN 0 ELSE 1 END), COALESCE(date, created_at) DESC LIMIT ?"
        return log.runSql("todo.list", r, sql, args + limit) { c ->
            val rows = mutableListOf<String>()
            while (c.moveToNext()) {
                val st = if (c.getString(1) == "pending") "open" else "done"
                rows += "[$st] ${c.getString(2) ?: ""} ${c.getString(0)}"
            }
            if (rows.isEmpty()) "No todos match." else "Todos:\n" + rows.joinToString("\n")
        }
    }

    // ============================================================
    // Weight
    // ============================================================

    /**
     * 2026-05-09: when the parser drops `person_text` (model emitted null
     * filters or `search_text:null`), DON'T silently fall back to the
     * most-recent person — that produces confident wrong answers. E.g. user
     * types `ask: what is jeevi weight`, model emits null person, runner
     * returns the most recent insert (Amma) as "Jeevi's weight". The
     * fallback was originally for bare `weight` queries (no person in
     * input) defaulting to the user's own.
     *
     * New logic: if filter is null/self, look at the original input text
     * and find any token matching a known person (from `persons` table or
     * `weights.person`). If exactly one match → use it. If none → fall
     * back to "self" (genuine bare query). If multiple → take the first
     * lexicographically.
     */
    private fun resolvePersonForWeight(
        r: SQLiteDatabase,
        filterPerson: String?,
        userText: String,
        log: RequestLogBuilder,
    ): String {
        val selfPronouns = setOf("self", "my", "mine", "me", "myself", "i")
        // If the LLM returned a concrete person name (not a pronoun), use it directly.
        if (!filterPerson.isNullOrBlank() && filterPerson !in selfPronouns) {
            return filterPerson
        }
        // filterPerson is null, "self", or a self-referential pronoun ("my" etc.)
        // Also scan the raw input text for the same pronoun set.
        val tokens = userText.lowercase()
            .split(Regex("[\\s,.;:!?'\"()\\[\\]{}]+"))
            .filter { it.isNotEmpty() }
            .toSet()
        val nameTokens = tokens.filter { it.length >= 2 }.toSet()
        val hasSelfRef = (filterPerson != null && filterPerson in selfPronouns) || tokens.any { it in selfPronouns }
        if (hasSelfRef) {
            val selfName = r.rawQuery(
                "SELECT value_json FROM runtime_state WHERE key='self_name'", null,
            ).use { c ->
                if (!c.moveToFirst()) null
                else runCatching {
                    org.json.JSONObject(c.getString(0)).optString("name").trim().ifBlank { null }
                }.getOrNull()
            }
            if (!selfName.isNullOrBlank()) {
                log.sql(
                    label = "weight.person.self_pronoun",
                    statement = "resolved self-pronoun to self_name",
                    args = listOf(userText),
                    rowCount = 1,
                    sampleRows = listOf(mapOf("resolved" to selfName, "pronoun_tokens" to tokens.intersect(selfPronouns).joinToString(","))),
                )
                return selfName
            }
        }
        // Try to extract a name from the input text against known persons/weights.
        val candidates = mutableSetOf<String>()
        r.rawQuery("SELECT DISTINCT lower(name) FROM persons", null).use { c ->
            while (c.moveToNext()) c.getString(0)?.let { candidates += it }
        }
        r.rawQuery("SELECT DISTINCT lower(person) FROM weights", null).use { c ->
            while (c.moveToNext()) c.getString(0)?.let { candidates += it }
        }
        candidates.remove("self")
        candidates.remove("")
        val matches = candidates.filter { it in nameTokens }
        if (matches.size == 1) {
            log.sql(
                label = "weight.person.reextract",
                statement = "(in-memory match against persons + weights tables)",
                args = listOf(userText),
                rowCount = 1,
                sampleRows = listOf(mapOf(
                    "matched" to matches.first(),
                    "reason" to "parser dropped person_text; recovered from input text",
                )),
            )
            return matches.first()
        }
        if (matches.size > 1) {
            val pick = matches.sorted().first()
            log.sql(
                label = "weight.person.reextract.multi",
                statement = "(in-memory match against persons + weights tables)",
                args = listOf(userText),
                rowCount = matches.size,
                sampleRows = listOf(mapOf(
                    "matches" to matches.joinToString(","),
                    "picked" to pick,
                    "reason" to "ambiguous; picked lexicographically first",
                )),
            )
            return pick
        }
        // No name in input AND parser dropped filter → genuine bare query.
        // Default to "self". Note we deliberately do NOT fall back to the
        // most-recent insert any more — that masked parser failures as
        // confident wrong-person answers (#105 dogfood log, 2026-05-09).
        return "self"
    }

    private fun runWeight(db: AppDatabase, p: ParserPayload.Query, log: RequestLogBuilder, userText: String = ""): String {
        val r = db.readableDatabase
        val f = p.filters
        val person = f?.optStringSafe("person_text")?.lowercase()
        if (p.intent == "latest_all") {
            val sql = """
                SELECT w1.person, w1.weight, w1.date FROM weights w1
                WHERE w1.id = (SELECT w2.id FROM weights w2 WHERE w2.person=w1.person
                               ORDER BY COALESCE(date, created_at) DESC, id DESC LIMIT 1)
                ORDER BY w1.person
            """.trimIndent()
            return log.runSql("weight.latest_all", r, sql) { c ->
                val rows = mutableListOf<String>()
                while (c.moveToNext()) rows += "${c.getString(0).cap()} ${c.getDouble(1)}kg on ${c.getString(2)}"
                if (rows.isEmpty()) "No weight data yet." else rows.joinToString(" · ")
            }
        }
        val effectivePerson = resolvePersonForWeight(r, person, userText, log)
        val where = mutableListOf("person = ?")
        val args  = mutableListOf<Any?>(effectivePerson)
        appendDate(where, args, p.dateStart, p.dateEnd)
        val limit = (p.limit ?: if (p.intent in setOf("history", "trend")) 5 else 10).coerceIn(1, 100)
        val sql = "SELECT weight, date, note FROM weights WHERE ${where.joinToString(" AND ")} " +
            "ORDER BY COALESCE(date, created_at) DESC LIMIT ?"
        return log.runSql("weight.${p.intent ?: "latest"}", r, sql, args + limit) { c ->
            val rows = mutableListOf<Pair<Double, String>>()
            while (c.moveToNext()) rows += c.getDouble(0) to (c.getString(1) ?: "")
            when {
                rows.isEmpty() -> "No weight data for ${effectivePerson.cap()}."
                p.intent == "latest" -> "${effectivePerson.cap()} weight: ${rows[0].first}kg on ${rows[0].second}"
                p.intent == "change" && rows.size >= 2 -> {
                    val delta = rows.first().first - rows.last().first
                    "${effectivePerson.cap()} changed ${"%+.1f".format(delta)}kg " +
                        "(${rows.last().first}kg → ${rows.first().first}kg)"
                }
                p.intent == "trend" -> {
                    val net = rows.first().first - rows.last().first
                    val joined = rows.joinToString(" · ") { "${it.second} ${it.first}kg" }
                    "${effectivePerson.cap()} trend: $joined · net ${"%+.1f".format(net)}kg"
                }
                else -> rows.joinToString(" · ") { "${it.second} ${it.first}kg" }
            }
        }
    }

    // ============================================================
    // Ledger
    // ============================================================
    private fun runLedger(db: AppDatabase, p: ParserPayload.Query, log: RequestLogBuilder): String {
        val r = db.readableDatabase
        val f = p.filters
        val person = f?.optStringSafe("person_text")?.lowercase()
        val perspective = f?.optStringSafe("perspective")
        val status = f?.optStringSafe("status")

        val balanceSql = if (person != null)
            "SELECT person, balance FROM ledger_balance WHERE person=? ORDER BY ABS(balance) DESC, person"
        else
            "SELECT person, balance FROM ledger_balance ORDER BY ABS(balance) DESC, person"
        val balanceArgs = if (person != null) listOf<Any?>(person) else emptyList<Any?>()
        val balances = log.runSql("ledger.balance", r, balanceSql, balanceArgs) { c ->
            val out = mutableListOf<Pair<String, Double>>()
            while (c.moveToNext()) {
                val p2 = c.getString(0); val b = c.getDouble(1)
                if (perspective == "i_owe_them" && b >= 0) continue
                if (perspective == "they_owe_me" && b <= 0) continue
                if (status == "open" && b == 0.0) continue
                if (status == "settled" && b != 0.0) continue
                out += p2 to b
            }
            out
        }
        if (p.intent in setOf("summary", "balance") || balances.isNotEmpty() && p.intent == null) {
            if (balances.isEmpty()) return "No ledger entries match."
            return balances.joinToString(", ") { (n, b) ->
                when {
                    b > 0.0 -> "${n.cap()} owes you ${formatRupees(b)}"
                    b < 0.0 -> "You owe ${n.cap()} ${formatRupees(abs(b))}"
                    else    -> "${n.cap()} - settled"
                }
            }
        }

        // intent = list / search → return individual entries
        val where = mutableListOf<String>(); val args = mutableListOf<Any?>()
        appendDate(where, args, p.dateStart, p.dateEnd)
        if (person != null) { where += "person = ?"; args += person }
        val whereSql = if (where.isEmpty()) "" else " WHERE " + where.joinToString(" AND ")
        val limit = (p.limit ?: 20).coerceIn(1, 100)
        val sql = "SELECT person, direction, amount, note, date FROM ledger$whereSql " +
            "ORDER BY COALESCE(date, created_at) DESC LIMIT ?"
        return log.runSql("ledger.list", r, sql, args + limit) { c ->
            val rows = mutableListOf<String>()
            while (c.moveToNext()) {
                val n = c.getString(0); val d = c.getString(1); val a = c.getDouble(2)
                val date = c.getString(4) ?: ""; val note = c.getString(3)
                val entry = if (d == "gave") "You gave ${formatRupees(a)} to ${n.cap()}"
                            else "You received ${formatRupees(a)} from ${n.cap()}"
                rows += "$date  $entry${note?.let { " ($it)" } ?: ""}"
            }
            if (rows.isEmpty()) "No ledger entries match." else "Ledger:\n" + rows.joinToString("\n")
        }
    }

    // ============================================================
    // Note — hybrid lexical (LIKE / trigram) + semantic (cosine) search
    // ============================================================
    private suspend fun runNote(db: AppDatabase, p: ParserPayload.Query, log: RequestLogBuilder): String {
        val r = db.readableDatabase
        val limit = (p.limit ?: when (p.intent) { "latest" -> 1; "list" -> 10; else -> 20 }).coerceIn(1, 100)

        // No query text → date-bucket / latest list (no scoring needed)
        val q = p.queryText?.takeIf { it.isNotBlank() }
        if (q == null) {
            val where = mutableListOf("input_kind='note' AND structured_type='note'")
            val args  = mutableListOf<Any?>()
            appendDateAsCreated(where, args, p.dateStart, p.dateEnd)
            val whereSql = " WHERE " + where.joinToString(" AND ")
            val sql = "SELECT content, created_at FROM notes$whereSql ORDER BY id DESC LIMIT ?"
            return log.runSql("note.recent", r, sql, args + limit) { c ->
                val rows = mutableListOf<String>()
                while (c.moveToNext()) rows += "${c.getString(1)?.take(10)}  ${c.getString(0)}"
                if (rows.isEmpty()) "No notes match." else rows.joinToString("\n\n")
            }
        }

        // ---- Hybrid scoring path ----
        // 1. Lexical signal: substring + token overlap. Scores 0..1.
        // 2. Semantic signal: encode q, cosine vs every stored embedding.
        //    Scores 0..1 (we add 1 then halve to map [-1,1] -> [0,1] but
        //    L2-normalized embeddings on the same model are bounded ~[0,1]
        //    in practice; treat <0 as 0).
        // Final score = 0.55 * lex + 0.45 * sem — biased slightly toward
        // lexical so exact-token queries don't drift to vague-but-similar
        // notes, matching the Python `query_notes_result` philosophy.

        val noteRows = log.runSql(
            "note.candidates", r,
            """SELECT id, content, created_at FROM notes
               WHERE input_kind='note' AND structured_type='note' ORDER BY id DESC""",
            emptyList(),
        ) { c ->
            val out = mutableListOf<NoteCandidate>()
            while (c.moveToNext())
                out += NoteCandidate(c.getLong(0), c.getString(1), c.getString(2))
            out
        }
        if (noteRows.isEmpty()) return "No notes match."

        val qLower = q.lowercase()
        val qTokens = qLower.split(Regex("[\\s,.;:!?'\"()\\[\\]{}]+"))
            .filter { it.isNotEmpty() }
            .toSet()

        val embeddingsByNote: Map<Long, FloatArray> = runCatching {
            EmbeddingsDao.loadAll(db).associate { it.noteId to it.vec }
        }.getOrElse { emptyMap() }

        val qVec: FloatArray? = if (embeddingsByNote.isNotEmpty())
            runCatching { runBlocking { MiniLmEncoder.encode(q) } }.getOrNull()
        else null

        val scored = noteRows.map { row ->
            val cLower = row.content.lowercase()
            val cTokens = cLower.split(Regex("[\\s,.;:!?'\"()\\[\\]{}]+"))
                .filter { it.isNotEmpty() }.toSet()
            val substring = if (qLower in cLower) 1.0f else 0.0f
            val overlap = if (qTokens.isEmpty()) 0f
                          else qTokens.intersect(cTokens).size.toFloat() / qTokens.size
            val lex = (substring * 0.6f + overlap * 0.4f).coerceIn(0f, 1f)
            val sem = if (qVec != null && embeddingsByNote.containsKey(row.id))
                MiniLmEncoder.cosine(qVec, embeddingsByNote[row.id]!!).coerceIn(0f, 1f)
            else 0f
            val final = 0.55f * lex + 0.45f * sem
            ScoredNote(row, lex, sem, final)
        }
        log.timing("note.hybrid.scored_count_ms", 0L)  // shape: counts only
        log.sql("note.hybrid.summary",
            "SELECT (hybrid scoring in-memory)", emptyList(),
            scored.size,
            scored.take(5).map { mapOf(
                "id" to it.row.id, "lex" to it.lex, "sem" to it.sem, "final" to it.final
            ) },
        )

        // Abstain: if even the best score is too weak, return "no match"
        // rather than a confident lie.
        val ranked = scored.sortedByDescending { it.final }.take(limit)
        if (ranked.isEmpty() || ranked[0].final < 0.20f) return "No notes match."

        val snippetsBlock = ranked.joinToString("\n\n") {
            "${it.row.createdAt.take(10)}  ${it.row.content}"
        }

        // Optional RAG synthesis (build #27 #8). When the toggle is OFF
        // (default) we just return the raw snippets — fast, safe. When
        // ON, we ask the parser model for a 1-2 sentence synthesis and
        // prepend it; on any failure we silently fall through to
        // snippets so the user always gets *something* back.
        if (!com.secondbrain.app.parser.NoteSynthSetting.isEnabled(db)) {
            return snippetsBlock
        }
        val question = p.queryText ?: ""
        val synthPrompt = buildString {
            append("<|im_start|>system\n")
            append("You are a concise assistant. Given the user's question and a few short notes, ")
            append("answer in 1-2 sentences using ONLY information present in the notes. ")
            append("If the notes don't answer the question, say so.<|im_end|>\n")
            append("<|im_start|>user\n")
            append("Question: ").append(question).append("\n\n")
            append("Notes:\n").append(snippetsBlock).append("<|im_end|>\n")
            append("<|im_start|>assistant\n<think></think>\n")
        }
        val tSynth = System.nanoTime()
        val synth = try {
            com.secondbrain.app.LlamaCpp.generate(synthPrompt, maxTokens = 96)
        } catch (t: Throwable) {
            log.error("note.synth.failed: ${t.message}")
            return snippetsBlock
        }
        log.timing("note.synth.generate_ms", (System.nanoTime() - tSynth) / 1_000_000)
        val cleaned = synth
            .replace(Regex("(?s)<think>.*?</think>"), "")
            .replace(Regex("<\\|im_end\\|>.*", RegexOption.DOT_MATCHES_ALL), "")
            .trim()
        return if (cleaned.isBlank()) snippetsBlock else "$cleaned\n\n---\n$snippetsBlock"
    }

    private data class NoteCandidate(val id: Long, val content: String, val createdAt: String)
    private data class ScoredNote(val row: NoteCandidate, val lex: Float, val sem: Float, val final: Float)

    // ============================================================
    // helpers
    // ============================================================
    private fun appendDate(where: MutableList<String>, args: MutableList<Any?>, ds: String?, de: String?) {
        // SQLite: dates are stored as ISO 'YYYY-MM-DD'. Falls back to created_at when null.
        if (ds != null) { where += "COALESCE(date, substr(created_at,1,10)) >= ?"; args += ds }
        if (de != null) { where += "COALESCE(date, substr(created_at,1,10)) <= ?"; args += de }
    }
    private fun appendDateAsCreated(where: MutableList<String>, args: MutableList<Any?>, ds: String?, de: String?) {
        if (ds != null) { where += "substr(created_at,1,10) >= ?"; args += ds }
        if (de != null) { where += "substr(created_at,1,10) <= ?"; args += de }
    }
    private fun String.cap(): String = replaceFirstChar { it.uppercase() }
}

private fun JSONObject.optStringSafe(key: String): String? {
    if (!has(key) || isNull(key)) return null
    val s = optString(key, "")
    return if (s.isEmpty() || s == "null") null else s
}
