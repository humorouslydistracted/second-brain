package com.secondbrain.app.orchestrator

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.data.consume
import com.secondbrain.app.data.string
import com.secondbrain.app.data.stringOrNull
import org.json.JSONArray
import org.json.JSONObject

/**
 * Per-request diagnostic capture. The user explicitly asked for "everything"
 * to be logged so we can troubleshoot by copy-pasting back here.
 *
 * Builder pattern: orchestrator constructs one of these per request, fills
 * fields as it progresses through stages, and finally calls [persist] which
 * writes a row to `request_log`. If anything throws midway, [persistError]
 * still flushes whatever we collected.
 */
class RequestLogBuilder(
    val userInput: String,
    val activeChips: Set<Tag>,
) {
    private val timings = LinkedHashMap<String, Long>()
    private val sqlTrace = JSONArray()
    private var tier: String? = null
    private var llmPrompt: String? = null
    private var llmRawJson: String? = null
    private var finalText: String? = null
    private var error: String? = null
    var activityId: Long? = null

    fun tier(value: String) { tier = value }
    fun llm(prompt: String, raw: String) { llmPrompt = prompt; llmRawJson = raw }
    fun final(text: String) { finalText = text }
    fun error(text: String) { error = text }

    fun timing(stage: String, ms: Long) { timings[stage] = ms }

    fun sql(label: String, statement: String, args: List<Any?>, rowCount: Int, sampleRows: List<Map<String, Any?>>) {
        val obj = JSONObject().apply {
            put("label", label)
            put("sql", statement.trim())
            put("args", JSONArray(args))
            put("row_count", rowCount)
            put("sample", JSONArray(sampleRows.map { JSONObject(it) }))
        }
        sqlTrace.put(obj)
    }

    fun persist(db: AppDatabase) {
        val cv = ContentValues().apply {
            put("activity_id", activityId)
            put("user_input", userInput)
            put("active_chips", activeChips.joinToString(",") { it.raw })
            put("tier", tier)
            put("llm_prompt", llmPrompt)
            put("llm_raw_json", llmRawJson)
            put("sql_trace", if (sqlTrace.length() == 0) null else sqlTrace.toString(2))
            put("final_text", finalText)
            put("timings_json", JSONObject(timings).toString())
            put("error_text", error)
        }
        db.writableDatabase.insert("request_log", null, cv)
    }
}

/**
 * Wraps a SQLite call so the SQL string + args + result are captured in the
 * RequestLogBuilder automatically. Use everywhere the orchestrator hits the
 * DB so the diagnostic log is complete.
 */
inline fun <T> RequestLogBuilder.runSql(
    label: String,
    db: SQLiteDatabase,
    sql: String,
    args: List<Any?> = emptyList(),
    block: (android.database.Cursor) -> T,
): T {
    val started = System.nanoTime()
    val rows = mutableListOf<Map<String, Any?>>()
    var t: T
    db.rawQuery(sql, args.map { it?.toString() ?: "" }.toTypedArray()).use { c ->
        // Capture up to first 5 rows for the sample
        var i = 0
        while (c.moveToNext() && i < 5) {
            val row = LinkedHashMap<String, Any?>()
            for (col in 0 until c.columnCount) row[c.getColumnName(col)] = c.getString(col)
            rows += row
            i++
        }
        // Reset and let the caller iterate normally
        c.moveToPosition(-1)
        t = block(c)
    }
    val ms = (System.nanoTime() - started) / 1_000_000
    timing("sql.$label", ms)
    sql(label, sql, args, rows.size, rows)
    return t
}

/**
 * Plain-text dump of a request_log row. Format: blocks separated by `---`,
 * labeled lines, matching the locked clipboard format from round 4.
 */
data class RequestLogEntry(
    val id: Long,
    val createdAt: String,
    val userInput: String?,
    val activeChips: String?,
    val tier: String?,
    val llmPrompt: String?,
    val llmRawJson: String?,
    val sqlTrace: String?,
    val finalText: String?,
    val timingsJson: String?,
    val errorText: String?,
) {
    fun toClipboardBlock(): String = buildString {
        appendLine("REQUEST #$id @ $createdAt")
        appendLine("USER INPUT: ${userInput ?: ""}")
        appendLine("CHIPS:      ${activeChips ?: ""}")
        appendLine("TIER:       ${tier ?: ""}")
        appendLine()
        appendLine("LLM PROMPT:")
        appendLine(llmPrompt ?: "")
        appendLine()
        appendLine("LLM RAW JSON:")
        appendLine(llmRawJson ?: "")
        appendLine()
        appendLine("SQL TRACE:")
        appendLine(sqlTrace ?: "(none)")
        appendLine()
        appendLine("FINAL TEXT:")
        appendLine(finalText ?: "")
        appendLine()
        appendLine("TIMINGS:    ${timingsJson ?: ""}")
        if (!errorText.isNullOrBlank()) {
            appendLine()
            appendLine("ERROR: $errorText")
        }
    }
}

object RequestLogDao {

    fun list(db: AppDatabase, limit: Int = 200, offset: Int = 0): List<RequestLogEntry> {
        return db.readableDatabase.rawQuery(
            "SELECT id, created_at, user_input, active_chips, tier, llm_prompt, llm_raw_json, " +
                "sql_trace, final_text, timings_json, error_text " +
                "FROM request_log ORDER BY id DESC LIMIT ? OFFSET ?",
            arrayOf(limit.toString(), offset.toString()),
        ).consume { c ->
            RequestLogEntry(
                id = c.getLong(0),
                createdAt = c.getString(1) ?: "",
                userInput = c.stringOrNull("user_input"),
                activeChips = c.stringOrNull("active_chips"),
                tier = c.stringOrNull("tier"),
                llmPrompt = c.stringOrNull("llm_prompt"),
                llmRawJson = c.stringOrNull("llm_raw_json"),
                sqlTrace = c.stringOrNull("sql_trace"),
                finalText = c.stringOrNull("final_text"),
                timingsJson = c.stringOrNull("timings_json"),
                errorText = c.stringOrNull("error_text"),
            )
        }
    }

    fun clear(db: AppDatabase) {
        db.writableDatabase.execSQL("DELETE FROM request_log")
        db.writableDatabase.execSQL("DELETE FROM activity_log")
        com.secondbrain.app.diag.EventLog.clearAll(db)
    }
}

/** Same shape used by the home feed and Activity log screen. */
data class ActivityEntry(
    val id: Long,
    val createdAt: String,
    val inputText: String,
    val responseText: String,
    val kind: String?,
    val metadataJson: String?,
)

object ActivityLogDao {

    fun insert(
        db: AppDatabase,
        input: String,
        response: String,
        kind: String?,
        metadataJson: String?,
    ): Long {
        return db.writableDatabase.insert("activity_log", null, ContentValues().apply {
            put("input_text", input)
            put("response_text", response)
            put("kind", kind)
            put("metadata_json", metadataJson)
        })
    }

    fun list(db: AppDatabase, limit: Int = 50, offset: Int = 0): List<ActivityEntry> =
        db.readableDatabase.rawQuery(
            "SELECT id, created_at, input_text, response_text, kind, metadata_json " +
                "FROM activity_log ORDER BY id DESC LIMIT ? OFFSET ?",
            arrayOf(limit.toString(), offset.toString()),
        ).consume { c ->
            ActivityEntry(
                id = c.getLong(0),
                createdAt = c.getString(1),
                inputText = c.string("input_text"),
                responseText = c.string("response_text"),
                kind = c.stringOrNull("kind"),
                metadataJson = c.stringOrNull("metadata_json"),
            )
        }

    fun count(db: AppDatabase): Long {
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM activity_log", null).use {
            return if (it.moveToFirst()) it.getLong(0) else 0L
        }
    }
}
