package com.secondbrain.app.parser

import android.content.ContentValues
import com.secondbrain.app.data.AppDatabase
import org.json.JSONObject

/**
 * Settings flag: when ON, note queries (e.g. "what did I write about
 * X?") run an extra LLM round-trip to synthesize a 1-2 sentence answer
 * over the retrieved snippets. When OFF (default), only the snippet
 * list is returned. Trades latency (~10s) for synthesized output.
 *
 * Backed by the runtime_state table.
 */
object NoteSynthSetting {

    private const val KEY = "note_synth_enabled"

    fun isEnabled(db: AppDatabase): Boolean {
        return db.readableDatabase.rawQuery(
            "SELECT value_json FROM runtime_state WHERE key = ?",
            arrayOf(KEY),
        ).use { c ->
            if (!c.moveToFirst()) return false
            val raw = c.getString(0) ?: return false
            runCatching { JSONObject(raw).optBoolean("enabled", false) }.getOrDefault(false)
        }
    }

    fun setEnabled(db: AppDatabase, enabled: Boolean) {
        val json = JSONObject().put("enabled", enabled).toString()
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
}
