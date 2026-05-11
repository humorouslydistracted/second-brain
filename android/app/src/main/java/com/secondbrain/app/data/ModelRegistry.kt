package com.secondbrain.app.data

import android.content.ContentValues
import org.json.JSONObject
import java.io.File

/**
 * Discovers parser GGUF files under the app's `models/` folder and
 * remembers which one the user picked. Lets us A/B between Qwen3-1.7B
 * (production) and Qwen3-0.6B (smaller, faster, less reliable) without
 * re-pushing files for every comparison.
 *
 * Filename convention: every parser GGUF must match
 * `qwen3-<size>-parser-q4_k_m.gguf` (e.g. `qwen3-1.7b-parser-q4_k_m.gguf`,
 * `qwen3-0.6b-parser-q4_k_m.gguf`). The Colab/Kaggle convert notebooks
 * already produce names that fit this pattern.
 *
 * Selection is persisted to `runtime_state` (key = "selected_model").
 * Falls back to the first discovered file if nothing is persisted, or
 * if the persisted choice was deleted.
 */
object ModelRegistry {

    /** Matches `qwen3-1.7b-parser-q4_k_m.gguf`, `qwen3-0.6b-parser-q4_k_m.gguf`, etc. */
    private val GGUF_PATTERN = Regex("""qwen3-[0-9]+\.[0-9]+b-parser-q4_k_m\.gguf""", RegexOption.IGNORE_CASE)

    private const val KEY = "selected_model"

    /** All parser GGUF files present in [modelDir], sorted by filename. */
    fun discover(modelDir: File): List<File> {
        if (!modelDir.exists() || !modelDir.isDirectory) return emptyList()
        return modelDir.listFiles { f -> f.isFile && GGUF_PATTERN.matches(f.name) }
            ?.sortedBy { it.name }
            ?: emptyList()
    }

    /**
     * Returns the file the user picked (via [setSelected]) if it still
     * exists, otherwise the first discovered file, otherwise null.
     */
    fun resolveSelected(db: AppDatabase, modelDir: File): File? {
        val available = discover(modelDir)
        if (available.isEmpty()) return null
        val saved = getSelectedFilename(db)
        if (saved != null) {
            available.firstOrNull { it.name == saved }?.let { return it }
            // Persisted file no longer present — clear the stale pointer.
            clear(db)
        }
        return available.firstOrNull()
    }

    fun getSelectedFilename(db: AppDatabase): String? {
        return db.readableDatabase.rawQuery(
            "SELECT value_json FROM runtime_state WHERE key = ?",
            arrayOf(KEY),
        ).use { c ->
            if (!c.moveToFirst()) return null
            val raw = c.getString(0) ?: return null
            runCatching { JSONObject(raw).optString("filename").trim().ifBlank { null } }
                .getOrNull()
        }
    }

    fun setSelected(db: AppDatabase, filename: String) {
        val cleaned = filename.trim()
        if (cleaned.isEmpty()) return
        val json = JSONObject().put("filename", cleaned).toString()
        val w = db.writableDatabase
        val updated = w.update(
            "runtime_state",
            ContentValues().apply { put("value_json", json) },
            "key = ?",
            arrayOf(KEY),
        )
        if (updated == 0) {
            w.insert("runtime_state", null, ContentValues().apply {
                put("key", KEY)
                put("value_json", json)
            })
        }
    }

    fun clear(db: AppDatabase) {
        db.writableDatabase.delete("runtime_state", "key = ?", arrayOf(KEY))
    }
}
