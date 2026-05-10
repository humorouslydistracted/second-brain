package com.secondbrain.app.orchestrator

import android.content.ContentValues
import com.secondbrain.app.data.AppDatabase

/**
 * Build #27 (#1 in the change list): per-request undo. The orchestrator
 * collects every row-level mutation through an [UndoBuilder] and hands
 * it back as an immutable [UndoToken]. The Home VM keeps the most
 * recent token alive for 5s so the user can rewind a misclassification
 * without manually editing the lane screens.
 *
 * What we track:
 *   - rowDeletes:        straightforward `DELETE FROM ? WHERE id=?` pairs
 *   - noteRestore:       notes are append-or-insert per day; we either
 *                        restore the previous content blob or delete
 *                        the inserted row outright
 *   - autoAddedPersons:  persons added by ensurePersonExists; we
 *                        delete only if no other table still references
 *                        the name (so editing later doesn't orphan
 *                        existing rows)
 *   - embeddingNoteIds:  best-effort cleanup of MiniLM rows tied to a
 *                        note we are deleting/restoring
 *
 * What we do NOT undo:
 *   - activity_log + request_log entries (audit trail; the undo itself
 *     is also logged so the user can see the round-trip)
 *   - pending_actions rows (these resolve themselves in subsequent turns)
 *   - captures rows (kept for raw-text origin even after undo)
 */
data class UndoToken(
    val rowDeletes: List<Pair<String, Long>>,
    val noteRestore: NoteUndo? = null,
    val autoAddedPersons: List<String> = emptyList(),
    val embeddingNoteIds: List<Long> = emptyList(),
    val summary: String = "",
)

data class NoteUndo(
    val noteId: Long,
    val previousContent: String?,
    val wasInsert: Boolean,
)

class UndoBuilder {
    val rowDeletes = mutableListOf<Pair<String, Long>>()
    var noteRestore: NoteUndo? = null
    val autoAddedPersons = mutableListOf<String>()
    val embeddingNoteIds = mutableListOf<Long>()
    var summary: String = ""

    fun addRow(table: String, id: Long) {
        if (id > 0) rowDeletes += table to id
    }

    fun build(): UndoToken? {
        val anything = rowDeletes.isNotEmpty() ||
            noteRestore != null ||
            autoAddedPersons.isNotEmpty()
        if (!anything) return null
        return UndoToken(
            rowDeletes = rowDeletes.toList(),
            noteRestore = noteRestore,
            autoAddedPersons = autoAddedPersons.toList(),
            embeddingNoteIds = embeddingNoteIds.toList(),
            summary = summary,
        )
    }
}

object Undoer {

    /**
     * Reverse the mutations in [token]. Returns a short status string
     * for the toast bus.
     */
    fun execute(db: AppDatabase, token: UndoToken): String {
        val w = db.writableDatabase
        var rowsDeleted = 0
        w.beginTransaction()
        try {
            // 1) Note restore / delete
            token.noteRestore?.let { nr ->
                if (nr.wasInsert) {
                    rowsDeleted += w.delete("notes", "id=?", arrayOf(nr.noteId.toString()))
                } else if (nr.previousContent != null) {
                    w.update(
                        "notes",
                        ContentValues().apply { put("content", nr.previousContent) },
                        "id=?",
                        arrayOf(nr.noteId.toString()),
                    )
                }
            }
            // 2) Direct row deletes (expense/buy/todo/weight/ledger)
            for ((table, id) in token.rowDeletes) {
                rowsDeleted += w.delete(table, "id=?", arrayOf(id.toString()))
            }
            // 3) Auto-added persons — only if nothing references them.
            for (name in token.autoAddedPersons) {
                if (!hasOtherRefs(db, name)) {
                    w.delete("persons", "name=?", arrayOf(name))
                }
            }
            // 4) Embeddings — best-effort.
            for (noteId in token.embeddingNoteIds) {
                w.delete("embeddings", "source_note_id=?", arrayOf(noteId.toString()))
            }
            w.setTransactionSuccessful()
        } finally {
            w.endTransaction()
        }
        return if (rowsDeleted > 0 || token.noteRestore != null) "Undone." else "Nothing to undo."
    }

    private fun hasOtherRefs(db: AppDatabase, name: String): Boolean {
        val r = db.readableDatabase
        val tables = listOf("weights", "ledger")
        for (t in tables) {
            val n = r.rawQuery("SELECT 1 FROM $t WHERE person=? LIMIT 1", arrayOf(name))
                .use { it.moveToFirst() }
            if (n) return true
        }
        return false
    }
}
