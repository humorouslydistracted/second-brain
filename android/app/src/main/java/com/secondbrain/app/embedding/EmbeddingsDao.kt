package com.secondbrain.app.embedding

import android.content.ContentValues
import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.data.consume
import com.secondbrain.app.data.string
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Storage helpers for the `embeddings` table.
 *
 * Layout: each row links to a `notes.id` via `source_note_id` and stores
 * the 384-float vector as a 1536-byte little-endian Float32 BLOB. Indexed
 * search is in-memory for v1 — works fine up to a few thousand notes; we
 * can swap in HNSW or sqlite-vss later.
 */
object EmbeddingsDao {

    fun put(db: AppDatabase, noteId: Long, content: String, vec: FloatArray) {
        val w = db.writableDatabase
        // Replace existing embedding for this note (re-embed paths)
        w.delete("embeddings", "source_note_id=?", arrayOf(noteId.toString()))
        w.insert("embeddings", null, ContentValues().apply {
            put("content", content)
            put("embedding", vec.toBlob())
            put("source_note_id", noteId)
        })
    }

    /**
     * Loads ALL embeddings into memory. For v1 we accept the O(N) cosine
     * scan; the embedding count tracks note count, which for a personal
     * note app stays in the low thousands.
     */
    fun loadAll(db: AppDatabase): List<Entry> {
        return db.readableDatabase.rawQuery(
            "SELECT id, source_note_id, content, embedding FROM embeddings", null,
        ).consume { c ->
            Entry(
                id = c.getLong(0),
                noteId = c.getLong(1),
                content = c.string("content"),
                vec = c.getBlob(c.getColumnIndexOrThrow("embedding")).toFloatArray(),
            )
        }
    }

    fun deleteForNote(db: AppDatabase, noteId: Long): Int =
        db.writableDatabase.delete("embeddings", "source_note_id=?", arrayOf(noteId.toString()))

    fun count(db: AppDatabase): Long =
        db.readableDatabase.rawQuery("SELECT COUNT(*) FROM embeddings", null).use {
            if (it.moveToFirst()) it.getLong(0) else 0L
        }

    /** Notes that don't yet have an embedding row (used by Re-embed All). */
    fun unembeddedNoteIds(db: AppDatabase): List<Long> =
        db.readableDatabase.rawQuery(
            """SELECT n.id FROM notes n
               LEFT JOIN embeddings e ON e.source_note_id = n.id
               WHERE n.input_kind='note' AND n.structured_type='note' AND e.id IS NULL""",
            null,
        ).consume { c -> c.getLong(0) }

    data class Entry(val id: Long, val noteId: Long, val content: String, val vec: FloatArray)
}

private fun FloatArray.toBlob(): ByteArray {
    val buf = ByteBuffer.allocate(size * 4).order(ByteOrder.LITTLE_ENDIAN)
    for (f in this) buf.putFloat(f)
    return buf.array()
}

private fun ByteArray.toFloatArray(): FloatArray {
    val buf = ByteBuffer.wrap(this).order(ByteOrder.LITTLE_ENDIAN)
    val n = size / 4
    val out = FloatArray(n)
    for (i in 0 until n) out[i] = buf.float
    return out
}
