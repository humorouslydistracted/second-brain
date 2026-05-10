package com.secondbrain.app.diag

import android.content.ContentValues
import android.content.Context
import android.util.Log
import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.consume
import com.secondbrain.app.data.string
import com.secondbrain.app.data.stringOrNull
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger

/**
 * Comprehensive diagnostic feed.
 *
 * Distinct from the other two log surfaces:
 *   - `activity_log` (table) — user-facing rows shown on Home + Activity log
 *   - `request_log`  (table) — one row per orchestrator dispatch
 *   - `event_log`    (table) — EVERYTHING ELSE: app start/stop, model loads,
 *                              file imports, every settings tap, latencies,
 *                              SQL traces, raw LLM IO, crashes
 *
 * Capped at [DEFAULT_CAP] rows by default. When the cap is exceeded the
 * oldest [ARCHIVE_BATCH] rows are exported to a dated `.jsonl` file under
 * the app's external `logs/` dir and deleted from the table. Archive
 * files are kept forever; user can delete them manually if needed.
 *
 * Cap is tunable from Settings; default is set in [DEFAULT_CAP] below.
 */
object EventLog {

    const val DEFAULT_CAP = 2000
    const val ARCHIVE_BATCH = 500
    private const val TAG = "EventLog"

    enum class Severity(val raw: String) {
        DEBUG("debug"), INFO("info"), WARN("warn"), ERROR("error")
    }

    enum class Category(val raw: String) {
        APP("app"),                  // app lifecycle (start, stop, foreground)
        MODEL("model"),              // LLM load/unload/abort
        EMBEDDER("embedder"),        // ONNX MiniLM load/encode
        IMPORT("import"),            // SAF model file imports
        ORCHESTRATOR("orchestrator"),// per-stage in handle()
        SQL("sql"),                  // every SQLite call
        USER("user"),                // user actions: chip taps, sends, deletes
        CRASH("crash"),              // UncaughtExceptionHandler
        SETTINGS("settings"),        // toggles, clears
        AUTOSTART("autostart")       // AppStartup
    }

    /** Async write to event_log. Never blocks the caller. */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val pending = AtomicInteger(0)

    /** Tunable from Settings. */
    @Volatile var cap: Int = DEFAULT_CAP
        @Synchronized set

    fun debug(category: Category, message: String, metadata: Map<String, Any?>? = null) =
        write(Severity.DEBUG, category, message, metadata)

    fun info(category: Category, message: String, metadata: Map<String, Any?>? = null) =
        write(Severity.INFO, category, message, metadata)

    fun warn(category: Category, message: String, metadata: Map<String, Any?>? = null) =
        write(Severity.WARN, category, message, metadata)

    fun error(category: Category, message: String, metadata: Map<String, Any?>? = null) =
        write(Severity.ERROR, category, message, metadata)

    /**
     * Convenience for logging a Throwable. Captures class + message +
     * stack-trace (truncated to 4000 chars).
     */
    fun throwable(category: Category, message: String, t: Throwable) {
        write(
            Severity.ERROR, category, message,
            mapOf(
                "exception_class" to t.javaClass.name,
                "exception_message" to (t.message ?: ""),
                "stack" to t.stackTraceToString().take(4000),
            )
        )
    }

    private fun write(
        severity: Severity, category: Category,
        message: String, metadata: Map<String, Any?>?
    ) {
        // Always mirror to logcat too — useful when debugging via adb logcat
        // and free of our DB rotation logic.
        when (severity) {
            Severity.DEBUG -> Log.d(TAG, "[${category.raw}] $message")
            Severity.INFO  -> Log.i(TAG, "[${category.raw}] $message")
            Severity.WARN  -> Log.w(TAG, "[${category.raw}] $message")
            Severity.ERROR -> Log.e(TAG, "[${category.raw}] $message")
        }
        pending.incrementAndGet()
        scope.launch {
            try {
                val db = runCatching { DatabaseHolder.get() }.getOrNull() ?: return@launch
                writeRow(db, severity, category, message, metadata)
                // Cheap check — only every 50th write
                if (pending.get() % 50 == 0) {
                    rotateIfNeeded(db)
                }
            } finally {
                pending.decrementAndGet()
            }
        }
    }

    private fun writeRow(
        db: AppDatabase, severity: Severity, category: Category,
        message: String, metadata: Map<String, Any?>?
    ) {
        val cv = ContentValues().apply {
            put("category", category.raw)
            put("severity", severity.raw)
            put("message", message.take(4000))
            put("metadata_json", metadata?.let { JSONObject(it).toString() })
        }
        db.writableDatabase.insert("event_log", null, cv)
    }

    /**
     * If the table has more than [cap] rows, export the oldest
     * [ARCHIVE_BATCH] to a dated `.jsonl` file and delete them.
     */
    private fun rotateIfNeeded(db: AppDatabase) {
        val r = db.readableDatabase
        val count = r.rawQuery("SELECT COUNT(*) FROM event_log", null).use {
            if (it.moveToFirst()) it.getLong(0) else 0L
        }
        if (count <= cap) return
        val toArchive = ARCHIVE_BATCH.toLong().coerceAtLeast(count - cap)
        val rows = r.rawQuery(
            "SELECT id, occurred_at, category, severity, message, metadata_json " +
                "FROM event_log ORDER BY id ASC LIMIT ?",
            arrayOf(toArchive.toString()),
        ).consume { c ->
            mapOf(
                "id" to c.getLong(0),
                "occurred_at" to c.string("occurred_at"),
                "category" to c.string("category"),
                "severity" to c.string("severity"),
                "message" to c.string("message"),
                "metadata_json" to c.stringOrNull("metadata_json"),
            )
        }
        if (rows.isEmpty()) return

        val archiveFile = archiveFileFor(rows[0]["occurred_at"] as String)
        archiveFile?.let { f ->
            f.parentFile?.mkdirs()
            f.appendText(rows.joinToString("\n") { JSONObject(it).toString() } + "\n")
        }
        val maxId = rows.maxOf { it["id"] as Long }
        db.writableDatabase.execSQL(
            "DELETE FROM event_log WHERE id <= ?",
            arrayOf<Any>(maxId)
        )
    }

    /** Archive directory: `<external files>/logs/event_log_YYYYMMDD.jsonl`. */
    @Volatile private var externalLogsDir: File? = null
    fun bindExternalDir(context: Context) {
        externalLogsDir = File(context.getExternalFilesDir(null), "logs")
    }

    private fun archiveFileFor(timestamp: String): File? {
        val dir = externalLogsDir ?: return null
        // timestamp looks like "2026-05-08 20:15:31"; take the date part.
        val date = timestamp.take(10).replace("-", "")
        return File(dir, "event_log_$date.jsonl")
    }

    fun listArchives(): List<File> {
        val dir = externalLogsDir ?: return emptyList()
        if (!dir.exists()) return emptyList()
        return dir.listFiles { f -> f.name.startsWith("event_log_") && f.name.endsWith(".jsonl") }
            ?.sortedByDescending { it.lastModified() }
            ?: emptyList()
    }

    /** Clear table + delete all archive files. Called by Settings 'Clear all logs'. */
    fun clearAll(db: AppDatabase) {
        db.writableDatabase.execSQL("DELETE FROM event_log")
        externalLogsDir?.let { dir ->
            dir.listFiles()?.forEach { runCatching { it.delete() } }
        }
    }

    fun count(db: AppDatabase): Long =
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM event_log", null).use {
            if (it.moveToFirst()) it.getLong(0) else 0L
        }

    /** Last [limit] events for the Settings 'Copy event log' button. */
    fun recentAsText(db: AppDatabase, limit: Int = 500): String {
        val rows = db.readableDatabase.rawQuery(
            "SELECT occurred_at, category, severity, message, metadata_json " +
                "FROM event_log ORDER BY id DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).consume { c ->
            EventEntry(
                occurredAt = c.string("occurred_at"),
                category = c.string("category"),
                severity = c.string("severity"),
                message = c.string("message"),
                metadataJson = c.stringOrNull("metadata_json"),
            )
        }
        if (rows.isEmpty()) return "(event log empty)"
        return buildString {
            appendLine("=== event_log (newest $limit, total ${count(db)}) ===")
            rows.forEach { e ->
                appendLine("${e.occurredAt}  [${e.severity}/${e.category}]  ${e.message}")
                if (!e.metadataJson.isNullOrBlank()) appendLine("  meta: ${e.metadataJson}")
            }
        }
    }

    data class EventEntry(
        val occurredAt: String, val category: String, val severity: String,
        val message: String, val metadataJson: String?,
    )
}

// ---------------------------------------------------------------------------
// Time formatting helpers
// ---------------------------------------------------------------------------

private val DISPLAY_FMT = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).apply {
    timeZone = java.util.TimeZone.getDefault()
}
private val DB_PARSE_FMT = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)

/**
 * SQLite's `datetime('now','localtime')` writes a string like
 * `2026-05-08 20:15:31` — already in device-local time. Pre-v2 rows are
 * UTC; we don't try to detect/convert. After a Clear all logs, all rows
 * are local.
 */
fun formatTimestampForDisplay(raw: String?): String {
    if (raw.isNullOrBlank()) return ""
    return raw.replace('T', ' ').take(19)
}
