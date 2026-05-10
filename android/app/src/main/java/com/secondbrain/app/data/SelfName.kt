package com.secondbrain.app.data

import android.content.ContentValues
import org.json.JSONObject

/**
 * Persisted user-name for resolving "self / me / I" pronouns into a
 * concrete person_text downstream. Backed by the `runtime_state` table.
 * Lowercased on store; null/empty means "not set" → onboarding modal
 * fires on next Home composition.
 */
object SelfName {

    private const val KEY = "self_name"

    fun get(db: AppDatabase): String? {
        return db.readableDatabase.rawQuery(
            "SELECT value_json FROM runtime_state WHERE key = ?",
            arrayOf(KEY),
        ).use { c ->
            if (!c.moveToFirst()) return null
            val raw = c.getString(0) ?: return null
            runCatching { JSONObject(raw).optString("name").trim().ifBlank { null } }
                .getOrNull()
        }
    }

    fun set(db: AppDatabase, name: String) {
        val cleaned = name.trim().lowercase()
        if (cleaned.isEmpty()) return
        val json = JSONObject().put("name", cleaned).toString()
        val w = db.writableDatabase
        // Upsert: try update, fall back to insert.
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
