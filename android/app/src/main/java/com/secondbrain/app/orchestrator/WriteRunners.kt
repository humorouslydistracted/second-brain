package com.secondbrain.app.orchestrator

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.parser.ParserPayload
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Executes a parser write payload against SQLite. Mirrors the Python
 * orchestrator's `_build_finetuned_entries` + `_execute_write_entries`,
 * collapsed into one place because the Android port doesn't keep the
 * legacy multi-tier dispatch.
 *
 * Each successful insert writes:
 *   - a `captures` row with the raw text + lane (immutable origin)
 *   - one or more rows in the lane-specific table, linked via source_capture_id
 */
object WriteRunner {

    fun run(
        db: AppDatabase,
        payload: ParserPayload.Write,
        rawUserText: String,
        log: RequestLogBuilder,
        undo: UndoBuilder = UndoBuilder(),
    ): String {
        return when (payload.disposition) {
            "reject"  -> rejectMessage(payload)
            "confirm" -> persistConfirm(db, payload, rawUserText)
            "accept"  -> insert(db, payload, rawUserText, log, undo)
            else      -> "Unsupported write disposition: ${payload.disposition}"
        }
    }

    /**
     * Ledger ambiguous-direction is the canonical confirm case. We surface
     * a numbered menu and persist a pending_actions row keyed to it; the
     * user replies "1" or "2" and Orchestrator.handle resolves it via
     * PendingActions.tryResolve.
     */
    private fun persistConfirm(db: AppDatabase, p: ParserPayload.Write, rawUserText: String): String {
        if (p.lane == "ledger" && p.records.size == 1) {
            val r = p.records[0]
            val person = r.optString("person_text").lowercase().trim()
            val amount = r.optDouble("amount", 0.0)
            val note = r.optString("note", null)
            if (person.isNotEmpty() && amount > 0.0) {
                val opts = org.json.JSONArray()
                opts.put(org.json.JSONObject().apply {
                    put("label", "I lent ${person.replaceFirstChar { it.uppercase() }} ${formatRupees(amount)}")
                    put("kind", "exec_ledger")
                    put("args", org.json.JSONObject().apply {
                        put("person", person); put("amount", amount); put("direction", "gave"); put("note", note)
                    })
                })
                opts.put(org.json.JSONObject().apply {
                    put("label", "I borrowed ${formatRupees(amount)} from ${person.replaceFirstChar { it.uppercase() }}")
                    put("kind", "exec_ledger")
                    put("args", org.json.JSONObject().apply {
                        put("person", person); put("amount", amount); put("direction", "received"); put("note", note)
                    })
                })
                opts.put(org.json.JSONObject().apply {
                    put("label", "Save as raw note (don't categorize)")
                    put("kind", "save_note")
                    put("args", org.json.JSONObject().apply { put("content", rawUserText) })
                })
                PendingActions.create(
                    db = db, actionType = "ledger_direction",
                    prompt = "Did you give or receive money?", options = opts,
                )
                return "Did you give or receive money?\n" +
                    (0 until opts.length()).joinToString("\n") { i -> "${i + 1}. ${opts.optJSONObject(i).optString("label")}" } +
                    "\nReply with a number, or 'cancel'."
            }
        }
        return "Confirmation needed (${p.reasonCode ?: "ambiguous"}): ${recordsSummary(p)}"
    }

    private fun rejectMessage(payload: ParserPayload.Write): String {
        val why = payload.reasonCode ?: "incomplete_input"
        return "Couldn't save ${payload.lane} ($why). Try again with more detail, or save it as a plain note instead."
    }

    private fun recordsSummary(p: ParserPayload.Write): String =
        p.records.joinToString(" / ") { it.toString() }.take(200)

    private fun insert(
        db: AppDatabase,
        p: ParserPayload.Write,
        rawUserText: String,
        log: RequestLogBuilder,
        undo: UndoBuilder,
    ): String {
        val w = db.writableDatabase
        val capId = insertCapture(w, rawUserText, p.lane, log)
        val parts = mutableListOf<String>()
        for (record in p.records) {
            val text = when (p.lane) {
                "expense" -> insertExpense(w, record, capId, rawUserText, log, undo)
                "buy"     -> insertBuy(w, record, capId, rawUserText, log, undo)
                "todo"    -> insertTodo(w, record, capId, log, undo)
                "weight"  -> insertWeight(w, record, capId, log, undo)
                "ledger"  -> insertLedger(w, record, capId, log, undo)
                else      -> "Unsupported lane: ${p.lane}"
            }
            parts += text
        }
        undo.summary = "Undo ${p.lane} (${p.records.size})"
        return parts.joinToString("; ")
    }

    private fun insertCapture(w: SQLiteDatabase, raw: String, lane: String, log: RequestLogBuilder): Long {
        val cv = ContentValues().apply {
            put("raw_text", raw); put("lane", lane); put("chip_set", null as String?)
        }
        val id = w.insert("captures", null, cv)
        log.sql("insert.captures", "INSERT INTO captures (raw_text,lane) VALUES (?,?)",
            listOf(raw, lane), 1, listOf(mapOf("id" to id)))
        return id
    }

    // ---------------- expense ----------------
    private fun insertExpense(w: SQLiteDatabase, r: JSONObject, capId: Long, raw: String, log: RequestLogBuilder, undo: UndoBuilder): String {
        val amount = r.optDouble("amount")
        val description = r.optString("description").trim()
        val date = nullable(r, "date") ?: today()
        val month = date.substring(0, 7)
        val group = nullable(r, "group")
        val cv = ContentValues().apply {
            put("amount", amount); put("description", description)
            put("date", date); put("month", month)
            put("group_name", group); put("raw_note", raw)
            put("source_capture_id", capId)
        }
        val id = w.insert("expenses", null, cv)
        undo.addRow("expenses", id)
        log.sql("insert.expense", "INSERT INTO expenses (...) VALUES (...)",
            listOf(amount, description, date, group), 1, listOf(mapOf("id" to id)))
        return "${formatRupees(amount)} $description logged"
    }

    // ---------------- buy ----------------
    private fun insertBuy(w: SQLiteDatabase, r: JSONObject, capId: Long, raw: String, log: RequestLogBuilder, undo: UndoBuilder): String {
        val item = r.optString("item_text").trim()
        val qty = nullable(r, "quantity_text")
        val unit = nullable(r, "unit_text")
        val date = nullable(r, "date") ?: today()
        val cv = ContentValues().apply {
            put("item_text", item); put("quantity_text", qty); put("unit_text", unit)
            put("date", date); put("status", "open"); put("raw_note", raw)
            put("source_capture_id", capId)
        }
        val id = w.insert("buy_items", null, cv)
        undo.addRow("buy_items", id)
        log.sql("insert.buy", "INSERT INTO buy_items (...) VALUES (...)",
            listOf(item, qty, unit, date), 1, listOf(mapOf("id" to id)))
        val qtyStr = if (!qty.isNullOrBlank()) " ($qty${unit?.let { " $it" } ?: ""})" else ""
        return "Added to buy list: $item$qtyStr"
    }

    // ---------------- todo ----------------
    private fun insertTodo(w: SQLiteDatabase, r: JSONObject, capId: Long, log: RequestLogBuilder, undo: UndoBuilder): String {
        val text = r.optString("text").trim()
        val date = nullable(r, "date")
        val cv = ContentValues().apply {
            put("content", text); put("date", date); put("status", "pending")
            put("source_capture_id", capId)
        }
        val id = w.insert("todos", null, cv)
        undo.addRow("todos", id)
        log.sql("insert.todo", "INSERT INTO todos (...) VALUES (...)",
            listOf(text, date), 1, listOf(mapOf("id" to id)))
        return "Todo added: $text"
    }

    // ---------------- weight ----------------
    private fun insertWeight(w: SQLiteDatabase, r: JSONObject, capId: Long, log: RequestLogBuilder, undo: UndoBuilder): String {
        val person = resolveSelf((nullable(r, "person_text") ?: "self").lowercase())
        val value = r.optDouble("value")
        val date = nullable(r, "date") ?: today()
        val note = nullable(r, "note")
        ensurePersonExists(w, person, log, undo)
        val cv = ContentValues().apply {
            put("person", person); put("weight", value); put("date", date)
            put("note", note); put("source_capture_id", capId)
        }
        val id = w.insert("weights", null, cv)
        undo.addRow("weights", id)
        log.sql("insert.weight", "INSERT INTO weights (...) VALUES (...)",
            listOf(person, value, date), 1, listOf(mapOf("id" to id)))
        return "${person.replaceFirstChar { it.uppercase() }} weight: ${value}kg logged"
    }

    /**
     * If [person] is not already in the persons table, insert it and
     * fire a toast. Called from weight + ledger inserts.
     *
     * Lowercase + trimmed by convention. "self" is the placeholder
     * default — don't auto-add that as a person.
     */
    private fun ensurePersonExists(w: SQLiteDatabase, person: String, log: RequestLogBuilder, undo: UndoBuilder) {
        val name = person.trim().lowercase()
        if (name.isEmpty() || name == "self") return
        val exists = w.rawQuery(
            "SELECT 1 FROM persons WHERE name = ? LIMIT 1",
            arrayOf(name),
        ).use { c -> c.moveToFirst() }
        if (exists) return
        val id = w.insert("persons", null, ContentValues().apply {
            put("name", name)
        })
        if (id > 0) {
            undo.autoAddedPersons += name
            log.sql("insert.person.auto", "INSERT INTO persons (...) VALUES (...)",
                listOf(name), 1, listOf(mapOf("id" to id)))
            com.secondbrain.app.AppStatusBus.emit(
                "Added new person: ${name.replaceFirstChar { it.uppercase() }}"
            )
        }
    }

    // ---------------- ledger ----------------
    private fun insertLedger(w: SQLiteDatabase, r: JSONObject, capId: Long, log: RequestLogBuilder, undo: UndoBuilder): String {
        val person = resolveSelf(nullable(r, "person_text")?.lowercase()?.trim() ?: return "Ledger entry needs a person")
        ensurePersonExists(w, person, log, undo)
        val action = nullable(r, "action") ?: "add_credit"
        val amount = r.opt("amount").let { if (it is Number) it.toDouble() else 0.0 }
        val date = nullable(r, "date") ?: today()
        val note = nullable(r, "note")
        // Action → direction mapping. Ledger balance formula is
        // `SUM(gave) - SUM(received)`, so:
        //   - balance > 0 means "they owe us" (we gave more than received)
        //   - balance < 0 means "we owe them"
        //
        // Correct mapping:
        //   add_credit  (they take a debt, we hold a receivable)  → balance ↑ → 'gave'
        //   collect_credit (they pay us back)                     → balance ↓ → 'received'
        //   add_debt    (we incur a debt, owe them)               → balance ↓ → 'received'
        //   repay_debt  (we pay them back what we owed)           → balance ↑ → 'gave'
        //
        // Build #21 had this inverted, causing "Maddy owes me 5k" to register
        // as "I owe Maddy 5k". Fixed in build #22.
        val direction = when (action) {
            "add_credit", "repay_debt"     -> "gave"
            "add_debt",   "collect_credit" -> "received"
            "settle" -> {
                // Settle wipes their balance. Phase 3a: insert opposite-direction
                // closing entry equal to outstanding balance.
                val balance = currentBalance(w, person)
                if (balance == 0.0) return "${person.replaceFirstChar { it.uppercase() }} - already settled"
                val closeDir = if (balance > 0) "received" else "gave"
                val closeAmt = kotlin.math.abs(balance)
                val id = w.insert("ledger", null, ContentValues().apply {
                    put("person", person); put("amount", closeAmt); put("direction", closeDir)
                    put("note", note ?: "settle"); put("date", date); put("source_capture_id", capId)
                })
                undo.addRow("ledger", id)
                log.sql("insert.ledger.settle",
                    "INSERT INTO ledger (...) VALUES (...) -- settle",
                    listOf(person, closeAmt, closeDir, date), 1, listOf(mapOf("id" to id)))
                return "${person.replaceFirstChar { it.uppercase() }} - settled"
            }
            else -> "received"
        }
        val cv = ContentValues().apply {
            put("person", person); put("amount", amount); put("direction", direction)
            put("note", note); put("date", date); put("source_capture_id", capId)
        }
        val id = w.insert("ledger", null, cv)
        undo.addRow("ledger", id)
        log.sql("insert.ledger", "INSERT INTO ledger (...) VALUES (...)",
            listOf(person, amount, direction, date), 1, listOf(mapOf("id" to id)))
        // direction='gave' = we lent / they took = THEY owe us  → "X owes you"
        // direction='received' = we borrowed / we took = WE owe them → "you owe X"
        // (Build #22-23 fix: this was inverted alongside the action→direction
        // mapping. The two inversions canceled out for the immediate display
        // string but produced wrong stored balances. Both fixed now so the
        // write display agrees with future query lookups.)
        val verb = when (direction) { "gave" -> "owes you"; else -> "" }
        val text = if (direction == "gave") {
            "${person.replaceFirstChar { it.uppercase() }} $verb ${formatRupees(amount)}"
        } else {
            "You owe ${person.replaceFirstChar { it.uppercase() }} ${formatRupees(amount)}"
        }
        return text
    }

    private fun currentBalance(w: SQLiteDatabase, person: String): Double {
        w.rawQuery(
            "SELECT SUM(CASE WHEN direction='gave' THEN amount ELSE -amount END) FROM ledger WHERE person=?",
            arrayOf(person),
        ).use { c -> return if (c.moveToFirst() && !c.isNull(0)) c.getDouble(0) else 0.0 }
    }

    /**
     * Replace pronoun-style person values ("self", "me", "i", "myself")
     * with the saved self_name from runtime_state. If the user skipped
     * onboarding (saved name == "self"), we leave the placeholder in
     * place — Weight runner already handles "self" → most-recent
     * person fallback in the query path.
     */
    private fun resolveSelf(person: String): String {
        val p = person.trim().lowercase()
        if (p !in PRONOUNS) return p
        val saved = com.secondbrain.app.data.SelfName.get(
            com.secondbrain.app.data.DatabaseHolder.get()
        )
        return saved?.takeIf { it.isNotBlank() && it != "self" } ?: "self"
    }

    private val PRONOUNS = setOf("self", "me", "i", "myself", "myne", "mine")

    private fun nullable(o: JSONObject, key: String): String? {
        if (!o.has(key) || o.isNull(key)) return null
        val s = o.optString(key, "")
        return s.ifEmpty { null }
    }

    private fun today(): String = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
}

internal fun formatRupees(v: Double): String {
    val whole = v.toLong()
    return if (kotlin.math.abs(v - whole) < 0.01) "₹$whole" else "₹%.2f".format(v)
}
