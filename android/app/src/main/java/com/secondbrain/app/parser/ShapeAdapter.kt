package com.secondbrain.app.parser

import com.secondbrain.app.diag.EventLog
import org.json.JSONArray
import org.json.JSONObject

/**
 * Forward-compat shim that coerces the fine-tuned model's actual output
 * shape into the v2-trained schema the validator expects.
 *
 * **Why this exists**
 *
 * Build #19 device dogfooding showed the model emits, e.g.:
 *
 *     {"task":"parse_write","lane":"weight","disposition":"accept",
 *      "data":{"person_text":"Murugan","weight":65,"date":"2026-05-08"}}
 *
 * but `ParserSchema.kt` validates the v2 schema:
 *
 *     {"task":"parse_write","lane":"weight","disposition":"accept",
 *      "records":[{"person_text":"murugan","value":65,"unit":"kg",
 *                  "date":"2026-05-08","note":null}]}
 *
 * Same data, different shape. Either we re-finetune or we translate.
 * This file is the translator. Keep it even after a clean re-finetune
 * — the cost is tiny (one regex per lane) and it shields the runtime
 * from future model drift.
 *
 * **Scope:** parse_write only. Query payloads aren't observed to drift
 * yet; if they do, add the corresponding coercers here.
 */
object ShapeAdapter {

    /**
     * If [payload] already has `records:[]`, return it untouched. Otherwise
     * detect a `data:{...}` legacy shape and rewrite it. Returns the
     * payload after coercion (or the original if nothing to do).
     */
    fun coerce(payload: JSONObject, userText: String? = null): JSONObject {
        val task = payload.optString("task")
        if (task == "parse_query" || task == "parse_followup_query") {
            return coerceQuery(payload, userText)
        }
        if (task != "parse_write") return payload
        if (payload.has("records") && !payload.isNull("records")) return payload

        // After ParserService.repairMultiRecordData, `data:` may be a
        // JSONArray of records. Coerce each element through the per-lane
        // path and concat the results.
        val dataArray = payload.optJSONArray("data")
        if (dataArray != null) {
            val lane = payload.optString("lane")
            val merged = JSONArray()
            for (i in 0 until dataArray.length()) {
                val obj = dataArray.optJSONObject(i) ?: continue
                val per = when (lane) {
                    "weight"  -> coerceWeight(obj)
                    "expense" -> coerceExpense(obj)
                    "todo"    -> coerceTodo(obj)
                    "buy"     -> coerceBuy(obj)
                    "ledger"  -> coerceLedger(obj, userText)
                    else -> JSONArray()
                }
                for (j in 0 until per.length()) merged.put(per.opt(j))
            }
            if (merged.length() > 0) {
                val out = JSONObject(payload.toString())
                out.remove("data")
                out.put("records", merged)
                EventLog.info(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: coerced data:[] -> records:[${merged.length()}]",
                    mapOf("lane" to lane))
                return out
            }
        }

        val data = payload.optJSONObject("data") ?: return payload
        val lane = payload.optString("lane")

        val records = when (lane) {
            "weight"  -> coerceWeight(data)
            "expense" -> coerceExpense(data)
            "todo"    -> coerceTodo(data)
            "buy"     -> coerceBuy(data)
            "ledger"  -> coerceLedger(data, userText)
            else -> {
                EventLog.warn(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: unknown lane in legacy data shape",
                    mapOf("lane" to lane))
                return payload
            }
        }

        if (records.length() == 0) {
            EventLog.warn(EventLog.Category.ORCHESTRATOR,
                "ShapeAdapter: produced empty records[]",
                mapOf("lane" to lane, "data" to data.toString()))
            return payload  // let validator reject naturally
        }

        // Build a new JSONObject so we don't mutate the original.
        val out = JSONObject(payload.toString())
        out.remove("data")
        out.put("records", records)
        EventLog.info(EventLog.Category.ORCHESTRATOR,
            "ShapeAdapter: coerced data:{} -> records:[${records.length()}]",
            mapOf("lane" to lane))
        return out
    }

    /**
     * Query-payload coercer. Several normalizations:
     *   1. lane:→domain: rename (older shape).
     *   2. If `domain` looks like an intent name (e.g. "balance",
     *      "total", "latest"), remap to a sensible domain + intent.
     *   3. Default disposition + intent + filters when missing.
     *   4. Drop a clearly-bogus `person_text` filter for who/all-style
     *      questions (model occasionally hallucinates 1-3 char
     *      person names from words inside the question).
     */
    private fun coerceQuery(payload: JSONObject, userText: String?): JSONObject {
        val out = JSONObject(payload.toString())

        // 1. lane → domain rename
        if ((!out.has("domain") || out.isNull("domain"))) {
            val lane = out.optString("lane").ifBlank { "" }
            if (lane.isNotEmpty()) {
                out.put("domain", lane)
                out.remove("lane")
                EventLog.info(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: query lane='$lane' -> domain", null)
            }
        }

        // 2. If domain is actually an intent name, remap.
        val INTENT_TO_DOMAIN = mapOf(
            "balance" to ("ledger" to "balance"),
            "summary" to ("ledger" to "summary"),
            "open_summary" to ("ledger" to "summary"),
            "settled_list" to ("ledger" to "search"),
            "total" to ("expense" to "total"),
            "latest" to ("weight" to "latest"),
            "trend" to ("weight" to "trend"),
            "history" to ("weight" to "history"),
        )
        val rawDomain = out.optString("domain")
        INTENT_TO_DOMAIN[rawDomain]?.let { (newDomain, newIntent) ->
            out.put("domain", newDomain)
            out.put("intent", newIntent)
            EventLog.info(EventLog.Category.ORCHESTRATOR,
                "ShapeAdapter: query domain='$rawDomain' remapped to domain=$newDomain intent=$newIntent", null)
        }

        // 3. Defaults
        if (!out.has("disposition") || out.optString("disposition").isBlank()) {
            out.put("disposition", "accept")
        }
        if (!out.has("intent") || out.optString("intent").isBlank()) {
            out.put("intent", when (out.optString("domain")) {
                "expense" -> "total"
                "weight" -> "latest"
                "ledger" -> "summary"
                else -> "list"
            })
        }
        if (!out.has("filters") || out.isNull("filters")) {
            out.put("filters", JSONObject())
        }

        // 3.5. Model occasionally puts the search target in `search_text`
        //      at the top level instead of inside filters. Copy it to
        //      the right slot per domain:
        //        weight → filters.person_text
        //        note   → query_text
        //        others → filters.text_match / filters.item_text where
        //                 those exist
        val rootSearch = out.optString("search_text").orNullIfBlank()
        if (rootSearch is String && rootSearch.isNotEmpty()) {
            val domain = out.optString("domain")
            val f = (out.optJSONObject("filters") ?: JSONObject().also { out.put("filters", it) })
            when (domain) {
                "weight" -> if (f.optString("person_text").isBlank()) f.put("person_text", rootSearch)
                "ledger" -> if (f.optString("person_text").isBlank()) f.put("person_text", rootSearch)
                "note"   -> if (out.optString("query_text").isBlank()) out.put("query_text", rootSearch)
                "todo"   -> if (f.optString("text_match").isBlank()) f.put("text_match", rootSearch)
                "buy"    -> if (f.optString("item_text").isBlank()) f.put("item_text", rootSearch)
                "expense" -> if (f.optString("description_text").isBlank()) f.put("description_text", rootSearch)
            }
            EventLog.info(EventLog.Category.ORCHESTRATOR,
                "ShapeAdapter: search_text='$rootSearch' moved into $domain filter", null)
        }

        // 3.6. For note queries, the model sometimes drops the search
        //      term into filters.person_text (since notes don't have a
        //      person filter that's meaningless). Copy it to query_text.
        if (out.optString("domain") == "note") {
            val f = out.optJSONObject("filters")
            val miscPerson = f?.optString("person_text")?.orNullIfBlank()
            if (miscPerson is String && miscPerson.isNotEmpty()
                && out.optString("query_text").isBlank()
            ) {
                out.put("query_text", miscPerson)
                f.put("person_text", JSONObject.NULL)
                EventLog.info(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: note filters.person_text -> query_text='$miscPerson'", null)
            }
        }

        // 4. Drop bogus person_text filter for who/all-style questions.
        //    "ask: who owe me money" — model emitted person_text="iow"
        //    (hallucinated from "I OWe"). Symptom: filter for nonexistent
        //    person → 0 rows.
        val filters = out.optJSONObject("filters")
        if (filters != null && userText != null) {
            val personText = filters.optString("person_text").trim()
            if (personText.isNotEmpty() && looksLikeBogusPerson(personText, userText)) {
                filters.put("person_text", JSONObject.NULL)
                EventLog.info(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: dropped bogus person_text='$personText' from who/all-style query", null)
            }
        }

        // 5. Status hint from user text — "completed / done / finished /
        //    checked" pulls done items; "open / pending / remaining /
        //    todo / left" pulls open items. Only applied to todo/buy
        //    domains where the filter actually exists.
        if (filters != null && userText != null) {
            val domain = out.optString("domain")
            if (domain == "todo" || domain == "buy") {
                val statusHint = inferStatusHint(userText, domain)
                if (statusHint != null && filters.optString("status").isBlank()) {
                    filters.put("status", statusHint)
                    EventLog.info(EventLog.Category.ORCHESTRATOR,
                        "ShapeAdapter: status hint '$statusHint' from user text", null)
                }
            }
        }

        // 6. Relative-date hint: model occasionally fails to resolve
        //    "tomorrow" or "weekend" into date_start/date_end. Compute
        //    them ourselves when missing. (Only on accept-disposition
        //    queries — clarify/reject leave dates null deliberately.)
        if (out.optString("disposition") == "accept" && userText != null) {
            val (rs, re) = inferDateRange(userText)
            if (rs != null && (out.optString("date_start").isBlank() ||
                               out.isNull("date_start"))) {
                out.put("date_start", rs)
                EventLog.info(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: inferred date_start=$rs from user text", null)
            }
            if (re != null && (out.optString("date_end").isBlank() ||
                               out.isNull("date_end"))) {
                out.put("date_end", re)
                EventLog.info(EventLog.Category.ORCHESTRATOR,
                    "ShapeAdapter: inferred date_end=$re from user text", null)
            }
        }

        return out
    }

    private fun inferStatusHint(userText: String, domain: String): String? {
        val t = userText.lowercase()
        // "completed / done / finished / checked / closed" → done
        if (Regex("\\b(completed|finished|checked|closed)\\b").containsMatchIn(t)) {
            return if (domain == "buy") "done" else "done"
        }
        // "done" by itself is risky in queries — could mean "todos that
        // are done" OR just be a stop-word. Require it follow a domain word.
        if (Regex("\\b(done)\\s+(todo|task|item|list|buy)\\b").containsMatchIn(t)) return "done"
        if (Regex("\\b(todo|task|item|list|buy)s?\\s+(done|completed|finished)\\b").containsMatchIn(t)) return "done"
        // "pending / remaining / open / left / unfinished / outstanding" → open
        if (Regex("\\b(pending|remaining|open|left|unfinished|outstanding)\\b").containsMatchIn(t)) {
            return if (domain == "buy") "open" else "open"
        }
        return null
    }

    /** Returns (date_start, date_end) inferred from user text, both null if no signal. */
    private fun inferDateRange(userText: String): Pair<String?, String?> {
        val t = userText.lowercase()
        val today = java.time.LocalDate.now()
        // "today"
        if (Regex("\\btoday\\b").containsMatchIn(t)) {
            val s = today.toString(); return s to s
        }
        // "tomorrow" / "tmrw" / "tmrrw"
        if (Regex("\\b(tomorrow|tmrw|tmrrw|tom)\\b").containsMatchIn(t)) {
            val s = today.plusDays(1).toString(); return s to s
        }
        // "yesterday"
        if (Regex("\\byesterday\\b").containsMatchIn(t)) {
            val s = today.minusDays(1).toString(); return s to s
        }
        // "this weekend" / "weekend" — upcoming Saturday and Sunday
        if (Regex("\\b(this\\s+)?weekend\\b").containsMatchIn(t)) {
            val sat = nextOrSame(today, java.time.DayOfWeek.SATURDAY)
            val sun = sat.plusDays(1)
            return sat.toString() to sun.toString()
        }
        // "next weekend"
        if (Regex("\\bnext\\s+weekend\\b").containsMatchIn(t)) {
            val sat = nextOrSame(today.plusDays(1), java.time.DayOfWeek.SATURDAY).plusWeeks(0)
            val sun = sat.plusDays(1)
            return sat.toString() to sun.toString()
        }
        // "this monday" / "next friday" / "monday" — pick the next
        // occurrence including today.
        val DAYS = mapOf(
            "monday" to java.time.DayOfWeek.MONDAY, "mon" to java.time.DayOfWeek.MONDAY,
            "tuesday" to java.time.DayOfWeek.TUESDAY, "tue" to java.time.DayOfWeek.TUESDAY,
            "wednesday" to java.time.DayOfWeek.WEDNESDAY, "wed" to java.time.DayOfWeek.WEDNESDAY,
            "thursday" to java.time.DayOfWeek.THURSDAY, "thu" to java.time.DayOfWeek.THURSDAY,
            "friday" to java.time.DayOfWeek.FRIDAY, "fri" to java.time.DayOfWeek.FRIDAY,
            "saturday" to java.time.DayOfWeek.SATURDAY, "sat" to java.time.DayOfWeek.SATURDAY,
            "sunday" to java.time.DayOfWeek.SUNDAY, "sun" to java.time.DayOfWeek.SUNDAY,
        )
        for ((word, day) in DAYS) {
            if (Regex("\\b(this\\s+|next\\s+)?$word\\b").containsMatchIn(t)) {
                val isNext = Regex("\\bnext\\s+$word\\b").containsMatchIn(t)
                val base = if (isNext) today.plusDays(1) else today
                val d = nextOrSame(base, day)
                val s = d.toString()
                return s to s
            }
        }
        // "this week" / "next week"
        if (Regex("\\bnext\\s+week\\b").containsMatchIn(t)) {
            val mon = nextOrSame(today.plusDays(1), java.time.DayOfWeek.MONDAY)
            return mon.toString() to mon.plusDays(6).toString()
        }
        if (Regex("\\bthis\\s+week\\b").containsMatchIn(t)) {
            val weekStart = today.minusDays((today.dayOfWeek.value - 1).toLong())
            return weekStart.toString() to weekStart.plusDays(6).toString()
        }
        return null to null
    }

    private fun nextOrSame(from: java.time.LocalDate, day: java.time.DayOfWeek): java.time.LocalDate {
        var d = from
        while (d.dayOfWeek != day) d = d.plusDays(1)
        return d
    }

    /**
     * Heuristic: a person_text is probably hallucinated if it's very
     * short (≤3 chars), AND the user's question has "who" or "all"
     * shape (no specific person named). The proper fix is also to
     * cross-check against the persons table — caller can do that —
     * but the cheap heuristic catches the common "i ow…" → "iow" case.
     */
    private fun looksLikeBogusPerson(name: String, userText: String): Boolean {
        if (name.length > 3) return false
        val t = userText.lowercase()
        if (Regex("\\bwho\\b").containsMatchIn(t)) return true
        if (Regex("\\b(all|every)\\b").containsMatchIn(t)) return true
        // 1-2 char name with no "with X" pattern is suspicious
        if (name.length <= 2) return true
        return false
    }

    // -----------------------------------------------------------------
    // Per-lane coercers
    // -----------------------------------------------------------------

    private fun coerceWeight(data: JSONObject): JSONArray {
        val arr = JSONArray()
        val person = data.optString("person_text", "self").ifBlank { "self" }
        val value = parseNumeric(data.opt("weight") ?: data.opt("value")) ?: return arr
        val date = data.optString("date").orNullIfBlank()
        val note = data.optString("note").orNullIfBlank()
        arr.put(JSONObject().apply {
            put("person_text", person.lowercase())
            put("value", value)
            put("unit", "kg")
            put("date", date)
            put("note", note)
        })
        return arr
    }

    private fun coerceExpense(data: JSONObject): JSONArray {
        val arr = JSONArray()
        val date = data.optString("date").orNullIfBlank()
        val details = data.optJSONObject("details")
        when {
            details != null -> {
                // Multi-item map: {"details": {"books": "250", "chalk": 30, ...}}
                val keys = details.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    val amount = parseNumeric(details.opt(key)) ?: continue
                    arr.put(JSONObject().apply {
                        put("description", key)
                        put("amount", amount)
                        put("date", date)
                        put("group", JSONObject.NULL)
                    })
                }
            }
            data.has("description") && data.has("amount") -> {
                // Single-record fallback (canonical): {"description":"...", "amount": 100}
                val amount = parseNumeric(data.opt("amount")) ?: return arr
                arr.put(JSONObject().apply {
                    put("description", data.optString("description"))
                    put("amount", amount)
                    put("date", date)
                    put("group", JSONObject.NULL)
                })
            }
            data.has("expense_item") && data.has("amount") -> {
                // Single-record alternate (model emits this):
                //   {"expense_item":"mothe","amount":50,"group":"other","note":null}
                val amount = parseNumeric(data.opt("amount")) ?: return arr
                arr.put(JSONObject().apply {
                    put("description", data.optString("expense_item"))
                    put("amount", amount)
                    put("date", date)
                    val grp = data.optString("group").orNullIfBlank()
                    put("group", grp)
                })
            }
            else -> {
                // Last-resort flat-map shape (build #24 logs):
                //   {"data": {"rent":"25000","car_service":8287,
                //             "youtuber_subscription":299, ...}}
                // The model dropped the `details:{}` wrapper and pushed
                // item:amount pairs directly under `data:`. Detect this
                // by counting numeric-valued keys after stripping known
                // metadata fields.
                val META = setOf("date", "person_text", "note", "diff", "followup_text",
                    "inherit_task", "reason_code", "group")
                val keys = mutableListOf<String>()
                val it = data.keys()
                while (it.hasNext()) keys += it.next()
                val itemKeys = keys.filter { it !in META }
                val anyNumeric = itemKeys.any { parseNumeric(data.opt(it)) != null }
                if (anyNumeric) {
                    for (k in itemKeys) {
                        val amount = parseNumeric(data.opt(k)) ?: continue
                        arr.put(JSONObject().apply {
                            put("description", k.replace('_', ' '))
                            put("amount", amount)
                            put("date", date)
                            put("group", JSONObject.NULL)
                        })
                    }
                }
            }
        }
        return arr
    }

    private fun coerceTodo(data: JSONObject): JSONArray {
        val arr = JSONArray()
        val date = data.optString("date").orNullIfBlank()
        val details = data.optJSONObject("details")
        if (details != null) {
            // {"details":{"call ravi":null, "buy milk":null}}
            val keys = details.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                arr.put(JSONObject().apply {
                    put("text", key)
                    put("date", date)
                })
            }
        } else if (data.has("text")) {
            arr.put(JSONObject().apply {
                put("text", data.optString("text"))
                put("date", date)
            })
        } else if (data.has("content")) {
            arr.put(JSONObject().apply {
                put("text", data.optString("content"))
                put("date", date)
            })
        }
        return arr
    }

    private fun coerceBuy(data: JSONObject): JSONArray {
        val arr = JSONArray()
        val date = data.optString("date").orNullIfBlank()
        // Shapes observed across builds:
        //   1) {"details": {"item": "qty"}}                    — older
        //   2) {"items": ["mutton", "saree", ...]}             — common
        //   3) {"item_list": [{"text":"...","unit":...}, ...]} — multi-record
        //   4) {"item_text": "...", "quantity_text": ...}      — single-record
        val details = data.optJSONObject("details")
        val items = data.optJSONArray("items")
        val itemList = data.optJSONArray("item_list")
        when {
            details != null -> {
                val keys = details.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    val rawQty = details.opt(key)
                    arr.put(JSONObject().apply {
                        put("item_text", key)
                        put("quantity_text", rawQty?.toString().orNullIfBlank())
                        put("unit_text", JSONObject.NULL)
                        put("date", date)
                    })
                }
            }
            items != null -> {
                for (i in 0 until items.length()) {
                    val v = items.opt(i) ?: continue
                    arr.put(JSONObject().apply {
                        put("item_text", v.toString())
                        put("quantity_text", JSONObject.NULL)
                        put("unit_text", JSONObject.NULL)
                        put("date", date)
                    })
                }
            }
            itemList != null -> {
                for (i in 0 until itemList.length()) {
                    val obj = itemList.optJSONObject(i) ?: continue
                    val itemText = obj.optString("text")
                        .ifBlank { obj.optString("item_text") }
                        .ifBlank { obj.optString("name") }
                    if (itemText.isBlank()) continue
                    arr.put(JSONObject().apply {
                        put("item_text", itemText)
                        // Some emissions put a stray number in `unit`; keep
                        // it as quantity_text since that's where qty lives.
                        val unit = obj.optString("unit").orNullIfBlank()
                        put("quantity_text", obj.optString("quantity_text").orNullIfBlank()
                            ?.takeUnless { it == JSONObject.NULL }
                            ?: unit)
                        put("unit_text", JSONObject.NULL)
                        put("date", obj.optString("date").orNullIfBlank() ?: date)
                    })
                }
            }
            data.has("item_text") -> {
                arr.put(JSONObject().apply {
                    put("item_text", data.optString("item_text"))
                    put("quantity_text", data.optString("quantity_text").orNullIfBlank())
                    put("unit_text", data.optString("unit_text").orNullIfBlank())
                    put("date", date)
                })
            }
        }
        return arr
    }

    private fun coerceLedger(data: JSONObject, userText: String?): JSONArray {
        val arr = JSONArray()
        val person = data.optString("person_text").ifBlank { return arr }
        val amount = parseNumeric(data.opt("amount")) ?: return arr
        val date = data.optString("date").orNullIfBlank()
        val note = data.optString("note").orNullIfBlank()

        // Resolve the action with priority:
        //   1. User-text inference (most reliable — directly reflects intent)
        //   2. Model's `direction` field (older shape)
        //   3. Model's `action` field (newer shape, but model often gets
        //      this wrong — observed in build #22 logs:
        //      "thanna owes 20k" → action="add_debt" but the user means
        //      thanna is the debtor i.e. add_credit)
        //   4. Default add_credit (creditor case is the more common
        //      first-person ledger entry)
        val inferred = inferLedgerAction(userText)
        val direction = data.optString("direction")
        val modelAction = data.optString("action")
        val action = inferred
            ?: when (direction) {
                "gave"     -> "add_credit"
                "received" -> "add_debt"
                else       -> modelAction.takeIf {
                    it in setOf("add_credit", "add_debt", "repay_debt", "collect_credit", "settle")
                } ?: "add_credit"
            }

        if (inferred != null && modelAction.isNotEmpty() && inferred != modelAction) {
            EventLog.warn(
                EventLog.Category.ORCHESTRATOR,
                "ShapeAdapter: ledger action overridden from '$modelAction' to '$inferred' based on user text",
                mapOf("user_text" to (userText ?: "")),
            )
        }

        arr.put(JSONObject().apply {
            put("person_text", person.lowercase())
            put("action", action)
            put("amount", amount)
            put("date", date)
            put("note", note)
        })
        return arr
    }

    /**
     * Read English cues out of the user input to figure out which side
     * of the ledger this entry belongs on. Returns null if no
     * unambiguous signal — caller falls back to the model.
     */
    private fun inferLedgerAction(userText: String?): String? {
        if (userText.isNullOrBlank()) return null
        val t = userText.lowercase()

        // "X owes me" / "X owe me" / "X owed me" — they owe us → add_credit
        if (Regex("\\bowe[sd]?\\s+me\\b").containsMatchIn(t)) return "add_credit"
        // "owes" alone with first-person implied (just "X owes 5k")
        // — common conversational shorthand for "owes me"
        if (Regex("\\bowe[sd]?\\b(?!\\s+to\\b)").containsMatchIn(t)
            && !Regex("\\bi\\s+owe").containsMatchIn(t)) return "add_credit"
        // "I lent X" / "lent to X" / "loaned X" — we lent → add_credit
        if (Regex("\\b(lent|loaned)\\b").containsMatchIn(t)) return "add_credit"
        // "gave X" — we gave money → they owe us → add_credit
        if (Regex("\\bgave\\s+\\S").containsMatchIn(t)
            && !Regex("\\bgave\\s+me\\b").containsMatchIn(t)) return "add_credit"

        // "I owe X" / "i owe to X" — we owe them → add_debt
        if (Regex("\\bi\\s+owe\\b").containsMatchIn(t)) return "add_debt"
        // "borrowed from X" / "took from X" — we borrowed → add_debt
        if (Regex("\\b(borrowed|took)\\s+from\\b").containsMatchIn(t)) return "add_debt"
        // "X gave me" / "received from X" — money came to us → add_debt
        if (Regex("\\b(gave\\s+me|received\\s+from|got\\s+from|paid\\s+by)\\b")
                .containsMatchIn(t)) return "add_debt"

        // Settlement language
        if (Regex("\\b(settled|cleared|paid\\s+back)\\b").containsMatchIn(t)) return "settle"

        return null
    }

    // -----------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------

    /**
     * Pull a Double from a JSON value that might be Number or String,
     * tolerating units like "250rs" / "1.5k" / "₹30".
     */
    private fun parseNumeric(v: Any?): Double? {
        if (v == null || v == JSONObject.NULL) return null
        return when (v) {
            is Number -> v.toDouble()
            is String -> {
                val s = v.trim().lowercase()
                if (s.isEmpty()) return null
                // "1.5k" / "2k" / "1l" / "1.5L" multipliers
                val m = Regex("^([0-9]+(?:\\.[0-9]+)?)\\s*([kKlL]?)").find(s) ?: return null
                val base = m.groupValues[1].toDoubleOrNull() ?: return null
                val mult = when (m.groupValues[2].lowercase()) {
                    "k" -> 1_000.0
                    "l" -> 100_000.0
                    else -> 1.0
                }
                base * mult
            }
            else -> null
        }
    }

    private fun String?.orNullIfBlank(): Any =
        if (this.isNullOrBlank() || this == "null") JSONObject.NULL else this
}
