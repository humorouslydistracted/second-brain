package com.secondbrain.app.orchestrator

import android.content.ContentValues
import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.data.consume
import com.secondbrain.app.data.string
import com.secondbrain.app.data.stringOrNull
import org.json.JSONArray
import org.json.JSONObject

/**
 * Pending-action persistence + numbered-clarify resolution.
 *
 * The orchestrator creates a pending row whenever:
 *   - the parser returns disposition=clarify (query lane)
 *   - the parser returns disposition=confirm (write lane, e.g. ambiguous
 *     ledger direction)
 *
 * The Home screen detects when the last activity was a pending clarify
 * and lets the user reply with a number. That reply hits
 * [PendingActions.tryResolve] which executes the chosen option.
 *
 * Each option has shape:
 *   { "label": "...", "kind": "<kind>", "args": { ... } }
 * where `kind` ∈ { "exec_payload", "save_note" }. The orchestrator can
 * extend the kinds without breaking older rows because resolution is
 * forward-compat: unknown kinds fall back to "save as note".
 */

data class PendingAction(
    val id: Long,
    val actionType: String,
    val prompt: String,
    val options: JSONArray,
    val payload: JSONObject?,
    val status: String,
    val createdAt: String,
)

object PendingActions {

    fun latestPending(db: AppDatabase): PendingAction? {
        return db.readableDatabase.rawQuery(
            "SELECT id, action_type, prompt, options_json, payload_json, status, created_at " +
                "FROM pending_actions WHERE status='pending' " +
                "ORDER BY id DESC LIMIT 1", null,
        ).consume { c ->
            PendingAction(
                id = c.getLong(0),
                actionType = c.string("action_type"),
                prompt = c.string("prompt"),
                options = JSONArray(c.string("options_json")),
                payload = c.stringOrNull("payload_json")?.let { JSONObject(it) },
                status = c.string("status"),
                createdAt = c.string("created_at"),
            )
        }.firstOrNull()
    }

    fun create(
        db: AppDatabase,
        actionType: String,
        prompt: String,
        options: JSONArray,
        payload: JSONObject? = null,
    ): Long {
        return db.writableDatabase.insert("pending_actions", null, ContentValues().apply {
            put("action_type", actionType)
            put("prompt", prompt)
            put("options_json", options.toString())
            put("payload_json", payload?.toString())
            put("status", "pending")
        })
    }

    fun markResolved(db: AppDatabase, id: Long) {
        db.writableDatabase.execSQL(
            "UPDATE pending_actions SET status='resolved', resolved_at=datetime('now') WHERE id=?",
            arrayOf<Any>(id),
        )
    }

    fun markDismissed(db: AppDatabase, id: Long) {
        db.writableDatabase.execSQL(
            "UPDATE pending_actions SET status='dismissed', resolved_at=datetime('now') WHERE id=?",
            arrayOf<Any>(id),
        )
    }

    /**
     * Returns null when [reply] doesn't look like a numbered/cancel reply
     * to the latest pending action. Otherwise returns the result text and
     * marks the pending action resolved.
     */
    fun tryResolve(db: AppDatabase, reply: String, log: RequestLogBuilder): String? {
        val pending = latestPending(db) ?: return null
        val trimmed = reply.trim().lowercase()
        if (trimmed in setOf("cancel", "none", "skip")) {
            markDismissed(db, pending.id)
            log.tier("clarify_dismissed")
            return "Cancelled."
        }
        val n = trimmed.toIntOrNull() ?: return null
        if (n < 1 || n > pending.options.length()) return "Reply with a number 1-${pending.options.length()} or 'cancel'."
        val chosen = pending.options.optJSONObject(n - 1)
            ?: return "Internal error: option $n missing."

        log.tier("clarify_resolved")
        val kind = chosen.optString("kind")
        val resolvedText = when (kind) {
            "exec_ledger" -> {
                val person = chosen.getJSONObject("args").getString("person")
                val amount = chosen.getJSONObject("args").getDouble("amount")
                val direction = chosen.getJSONObject("args").getString("direction")
                val note = chosen.getJSONObject("args").optString("note", null)
                com.secondbrain.app.data.LedgerDao.add(db, person, amount, direction, note)
                val verb = if (direction == "gave") "you owe" else "owes you"
                "${person.replaceFirstChar { it.uppercase() }} $verb ${formatRupees(amount)}"
            }
            "save_note" -> {
                val text = chosen.getJSONObject("args").getString("content")
                db.writableDatabase.insert("notes", null, ContentValues().apply {
                    put("content", text); put("input_kind", "note"); put("structured_type", "note")
                })
                "Saved as note."
            }
            else -> "Saved as note (unknown option kind: $kind)."
        }
        markResolved(db, pending.id)
        return resolvedText
    }
}
