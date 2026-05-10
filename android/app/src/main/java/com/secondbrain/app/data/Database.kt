package com.secondbrain.app.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicReference

/**
 * Single SQLiteOpenHelper for the whole app.
 *
 * Schemas mirror the Python side as faithfully as the v1-on-Android scope
 * needs — see `seed.sql` and `second_brain_core.py::ensure_runtime_schema`.
 *
 * v2 (2026-05-08) changes vs v1:
 *   - All `created_at` defaults switched from UTC `datetime('now')` to
 *     device-local `datetime('now','localtime')` so timestamps match what
 *     the user sees on their phone notification bar.
 *   - New `event_log` table — comprehensive diagnostic feed (separate from
 *     the user-facing `activity_log` and the per-orchestrator
 *     `request_log`). Capped at ~2000 rows by default; oldest rows are
 *     periodically rotated to dated `.jsonl` archive files in the app's
 *     external files dir.
 */
class AppDatabase(context: Context) :
    SQLiteOpenHelper(context.applicationContext, "second_brain.db", null, DB_VERSION) {

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onCreate(db: SQLiteDatabase) {
        DDL.forEach { db.execSQL(it) }
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Pre-1.0 policy: rebuild on schema bump. Acceptable because the
        // user does manual `Clear all logs` / fresh install regularly.
        DROP_ALL.forEach { db.execSQL(it) }
        onCreate(db)
    }

    companion object {
        private const val DB_VERSION = 3
    }
}

object DatabaseHolder {
    private val ref = AtomicReference<AppDatabase?>(null)
    fun init(context: Context) { ref.compareAndSet(null, AppDatabase(context)) }
    fun get(): AppDatabase = ref.get() ?: error("DatabaseHolder.init() not called")
}

// ---------------------------------------------------------------------------
// DDL — kept verbose so a future migration script can diff per table.
// ---------------------------------------------------------------------------

private val DDL = listOf(
    """CREATE TABLE persons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        input_kind TEXT NOT NULL DEFAULT 'note',
        structured_type TEXT,
        note_domain TEXT,
        metadata_json TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        processed_at TEXT
    )""",
    """CREATE TABLE captures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_text TEXT NOT NULL,
        lane TEXT,
        chip_set TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL NOT NULL,
        description TEXT NOT NULL,
        date TEXT,
        month TEXT,
        group_name TEXT,
        raw_note TEXT,
        source_capture_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person TEXT NOT NULL,
        amount REAL NOT NULL,
        direction TEXT NOT NULL,
        note TEXT,
        date TEXT,
        source_capture_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE VIEW ledger_balance AS
        SELECT person,
               SUM(CASE WHEN direction='gave' THEN amount ELSE -amount END) AS balance
        FROM ledger GROUP BY person""",
    """CREATE TABLE weights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person TEXT NOT NULL,
        weight REAL NOT NULL,
        date TEXT NOT NULL,
        note TEXT,
        source_capture_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        date TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        source_capture_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE buy_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_text TEXT NOT NULL,
        quantity_text TEXT,
        unit_text TEXT,
        date TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
        raw_note TEXT,
        source_capture_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        embedding BLOB NOT NULL,
        source_note_id INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE pending_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        prompt TEXT NOT NULL,
        options_json TEXT NOT NULL,
        payload_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        resolved_at TEXT
    )""",
    """CREATE TABLE runtime_state (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        input_text TEXT NOT NULL,
        response_text TEXT NOT NULL,
        kind TEXT,
        metadata_json TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    """CREATE TABLE request_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER,
        user_input TEXT,
        active_chips TEXT,
        tier TEXT,
        llm_prompt TEXT,
        llm_raw_json TEXT,
        sql_trace TEXT,
        final_text TEXT,
        timings_json TEXT,
        error_text TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )""",
    // Comprehensive diagnostic feed. Distinct from `activity_log`
    // (user-facing) and `request_log` (per-orchestrator-dispatch). Captures
    // everything from app start/stop to every SQL call. Capped at
    // EVENT_LOG_DEFAULT_CAP rows; oldest rows are exported to dated
    // `.jsonl` files when the cap is exceeded.
    """CREATE TABLE event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        metadata_json TEXT
    )""",
    """CREATE TABLE input_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_input TEXT NOT NULL,
        chips TEXT,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','done','failed')),
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        processed_at TEXT
    )""",
    "CREATE INDEX idx_activity_log_created ON activity_log(created_at DESC)",
    "CREATE INDEX idx_request_log_created  ON request_log(created_at DESC)",
    "CREATE INDEX idx_event_log_occurred   ON event_log(occurred_at DESC)",
    "CREATE INDEX idx_expenses_month       ON expenses(month)",
    "CREATE INDEX idx_expenses_date        ON expenses(date)",
    "CREATE INDEX idx_ledger_person        ON ledger(person)",
    "CREATE INDEX idx_weights_person       ON weights(person)",
    "CREATE INDEX idx_todos_status         ON todos(status)",
    "CREATE INDEX idx_buy_items_status     ON buy_items(status)",
)

private val DROP_ALL = listOf(
    "DROP TABLE IF EXISTS input_queue",
    "DROP VIEW IF EXISTS ledger_balance",
    "DROP TABLE IF EXISTS event_log",
    "DROP TABLE IF EXISTS request_log",
    "DROP TABLE IF EXISTS activity_log",
    "DROP TABLE IF EXISTS runtime_state",
    "DROP TABLE IF EXISTS pending_actions",
    "DROP TABLE IF EXISTS embeddings",
    "DROP TABLE IF EXISTS buy_items",
    "DROP TABLE IF EXISTS todos",
    "DROP TABLE IF EXISTS weights",
    "DROP TABLE IF EXISTS ledger",
    "DROP TABLE IF EXISTS expenses",
    "DROP TABLE IF EXISTS captures",
    "DROP TABLE IF EXISTS notes",
    "DROP TABLE IF EXISTS persons",
)

// ---------------------------------------------------------------------------
// Convenience extensions for cursor → primitive
// ---------------------------------------------------------------------------

fun Cursor.stringOrNull(name: String): String? {
    val idx = getColumnIndex(name); if (idx < 0 || isNull(idx)) return null
    return getString(idx)
}
fun Cursor.longOrNull(name: String): Long? {
    val idx = getColumnIndex(name); if (idx < 0 || isNull(idx)) return null
    return getLong(idx)
}
fun Cursor.doubleOrNull(name: String): Double? {
    val idx = getColumnIndex(name); if (idx < 0 || isNull(idx)) return null
    return getDouble(idx)
}
fun Cursor.string(name: String): String =
    stringOrNull(name) ?: error("missing column $name")

inline fun <T> Cursor.consume(block: (Cursor) -> T): List<T> =
    use { c -> buildList { while (c.moveToNext()) add(block(c)) } }

fun ContentValues.putNullable(key: String, value: Any?) {
    when (value) {
        null         -> putNull(key)
        is String    -> put(key, value)
        is Int       -> put(key, value)
        is Long      -> put(key, value)
        is Double    -> put(key, value)
        is Float     -> put(key, value)
        is Boolean   -> put(key, if (value) 1 else 0)
        is JSONObject -> put(key, value.toString())
        else         -> put(key, value.toString())
    }
}
