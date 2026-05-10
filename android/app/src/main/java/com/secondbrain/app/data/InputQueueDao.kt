package com.secondbrain.app.data

import android.content.ContentValues
import com.secondbrain.app.orchestrator.Tag

/**
 * Durable input queue — persists every submission to SQLite BEFORE the LLM
 * runs, so a GrapheneOS process-kill during a long inference (e.g. 30-second
 * 7-item buy list) doesn't lose the user's input.
 *
 * Lifecycle:
 *   pending    → enqueue() on Send tap
 *   processing → markProcessing() when the worker picks it up
 *   done       → markDone() after Orchestrator.handle() returns successfully
 *   failed     → markFailed() on error
 *
 * On next app launch, rows with status IN ('pending','processing') are
 * recovered and re-enqueued in HomeViewModel.recoverPendingQueue().
 * 'processing' is treated the same as 'pending' on recovery because the
 * app was killed before processing could complete.
 */
object InputQueueDao {

    data class QueueRow(val id: Long, val rawInput: String, val chips: String)

    fun enqueue(db: AppDatabase, rawInput: String, chips: Set<Tag>): Long {
        val cv = ContentValues().apply {
            put("raw_input", rawInput)
            put("chips", chips.joinToString(",") { it.raw })
        }
        return db.writableDatabase.insert("input_queue", null, cv)
    }

    fun markProcessing(db: AppDatabase, id: Long) {
        db.writableDatabase.execSQL(
            "UPDATE input_queue SET status='processing' WHERE id=?", arrayOf(id)
        )
    }

    fun markDone(db: AppDatabase, id: Long) {
        db.writableDatabase.execSQL(
            "UPDATE input_queue SET status='done', processed_at=datetime('now','localtime') WHERE id=?",
            arrayOf(id)
        )
    }

    fun markFailed(db: AppDatabase, id: Long) {
        db.writableDatabase.execSQL(
            "UPDATE input_queue SET status='failed', processed_at=datetime('now','localtime') WHERE id=?",
            arrayOf(id)
        )
    }

    /** Returns rows that survived a process kill (pending or stuck mid-processing). */
    fun unprocessed(db: AppDatabase): List<QueueRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, raw_input, chips FROM input_queue " +
                "WHERE status IN ('pending','processing') ORDER BY id ASC",
            null,
        ).consume { c ->
            QueueRow(
                id = c.getLong(c.getColumnIndexOrThrow("id")),
                rawInput = c.string("raw_input"),
                chips = c.stringOrNull("chips") ?: "",
            )
        }

    /** Keep last 50 done/failed rows for debugging; silently drop the rest. */
    fun pruneOld(db: AppDatabase) {
        db.writableDatabase.execSQL(
            "DELETE FROM input_queue WHERE status IN ('done','failed') " +
                "AND id NOT IN (" +
                "  SELECT id FROM input_queue WHERE status IN ('done','failed') " +
                "  ORDER BY id DESC LIMIT 50" +
                ")"
        )
    }
}
