package com.secondbrain.app.parser

import org.json.JSONArray
import org.json.JSONObject
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.time.temporal.TemporalAdjusters
import java.util.Locale

/**
 * Rule-based / regex parser that returns the exact same payload shape the
 * fine-tuned LLM produces. Selected at runtime via [ModelRegistry] using
 * the literal sentinel `"manual"`; when active, [ParserService] dispatches
 * here instead of calling the GGUF.
 *
 * V1 phased scope (per 2026-05-11 product decision):
 *   - Writes: expense / buy / todo / weight / ledger
 *   - Queries: total / list / latest / balance / recent / search per domain
 *   - Dates: today / yesterday / tomorrow / this week / last week /
 *            this month / last month / this year + `DD MMM` / `DD MMM YYYY`
 *            + numeric `DD-MM` / `DD/MM` / `DD-MM-YYYY`
 *   - Amounts: 500 / 5,000 / 5k / 1.5L / 1 lakh / 1 crore / Rs. 500 /
 *              ₹500 / 500/- / `USD <n>` (saved numerically, no conversion)
 *   - Multi-record via `,` `;` `|` `&` ` and ` separators
 *   - Disposition reject + reason_code `manual_unrecognized` whenever the
 *     rules can't extract a confident structure. Orchestrator's existing
 *     reject path surfaces the same message it shows for LLM rejects.
 *
 * Out of V1 scope (defer to V2): Tanglish verbs, semantic group inference,
 * follow-up context inheritance, festival-relative dates, exclusion filters,
 * compare-range intent.
 */
object ManualParser {

    /** Sentinel value stored in `runtime_state.selected_model` and listed in the picker. */
    const val SENTINEL = "manual"

    /** Public display name for the radio row in Settings. */
    const val DISPLAY_NAME = "Manual (rules, no LLM)"

    fun parse(userInput: String, today: LocalDate = LocalDate.now()): ParseResult {
        val text = userInput.trim()
        if (text.isEmpty()) return reject(lane = null, "empty_input")

        val tagged = splitTag(text) ?: return reject(lane = null, "no_tag")
        val (tag, body) = tagged
        val bodyTrim = body.trim()
        if (bodyTrim.isEmpty()) return reject(lane = tag, "incomplete_input")

        return try {
            when (tag) {
                "expense" -> parseExpenseWrite(bodyTrim, today)
                "buy"     -> parseBuyWrite(bodyTrim, today)
                "todo"    -> parseTodoWrite(bodyTrim, today)
                "weight"  -> parseWeightWrite(bodyTrim, today)
                "ledger"  -> parseLedgerWrite(bodyTrim, today)
                "ask"     -> parseQuery(bodyTrim, today)
                else      -> reject(lane = null, "no_tag")
            }
        } catch (t: Throwable) {
            reject(lane = tag, "manual_unrecognized")
        }
    }

    // ──────────────────────────────────────────────────────────────
    // Tag detection
    // ──────────────────────────────────────────────────────────────

    private val KNOWN_TAGS = setOf("expense", "buy", "todo", "weight", "ledger", "ask", "note")

    private fun splitTag(text: String): Pair<String, String>? {
        val colon = text.indexOf(':')
        if (colon <= 0) return null
        val head = text.substring(0, colon).trim().lowercase()
        if (head !in KNOWN_TAGS) return null
        return head to text.substring(colon + 1)
    }

    // ──────────────────────────────────────────────────────────────
    // Write: expense
    // ──────────────────────────────────────────────────────────────

    private fun parseExpenseWrite(body: String, today: LocalDate): ParseResult {
        val (stripped, sharedDate) = stripTrailingDate(body, today)
        val parts = splitMulti(stripped)
        val records = mutableListOf<JSONObject>()
        for (p in parts) {
            val rec = parseSingleExpense(p, sharedDate ?: today) ?: return reject("expense", "incomplete_input")
            records += rec
        }
        if (records.isEmpty()) return reject("expense", "incomplete_input")
        return acceptWrite("expense", records)
    }

    private fun parseSingleExpense(text: String, fallbackDate: LocalDate): JSONObject? {
        val (trimmed, perRecordDate) = stripTrailingDate(text, fallbackDate)
        val date = perRecordDate ?: fallbackDate
        // Try `<desc>:<amount>` first (dataset uses colon-separated rows).
        val colonMatch = COLON_AMOUNT_RE.find(trimmed)
        if (colonMatch != null) {
            val desc = colonMatch.groupValues[1].trim().trimEnd(':', ',')
            val amt = parseAmount(colonMatch.groupValues[2]) ?: return null
            if (desc.isEmpty()) return null
            return expenseRecord(desc, amt, date)
        }
        // Otherwise: find the first amount token, take everything before as desc.
        val m = AMOUNT_RE.find(trimmed) ?: return null
        val before = trimmed.substring(0, m.range.first).trim().trimEnd(':', ',')
        val after = trimmed.substring(m.range.last + 1).trim().trimEnd(':', ',')
        val amt = parseAmount(m.value) ?: return null
        val desc = when {
            before.isNotEmpty() && after.isEmpty() -> before
            before.isEmpty() && after.isNotEmpty() -> after
            before.isNotEmpty() && after.isNotEmpty() -> "$before $after"
            else -> return null
        }
        if (desc.isEmpty()) return null
        return expenseRecord(desc, amt, date)
    }

    private fun expenseRecord(description: String, amount: Double, date: LocalDate) = JSONObject().apply {
        put("description", description)
        put("amount", normalizeAmountNumber(amount))
        put("date", date.toString())
        put("group", JSONObject.NULL)   // V1: no group inference
    }

    // ──────────────────────────────────────────────────────────────
    // Write: buy
    // ──────────────────────────────────────────────────────────────

    private fun parseBuyWrite(body: String, today: LocalDate): ParseResult {
        val (stripped, sharedDate) = stripTrailingDate(body, today)
        val parts = splitMulti(stripped)
        val records = mutableListOf<JSONObject>()
        for (p in parts) {
            val rec = parseSingleBuy(p, sharedDate ?: today) ?: return reject("buy", "incomplete_input")
            records += rec
        }
        if (records.isEmpty()) return reject("buy", "incomplete_input")
        return acceptWrite("buy", records)
    }

    private fun parseSingleBuy(text: String, fallbackDate: LocalDate): JSONObject? {
        val (trimmed, perRecordDate) = stripTrailingDate(text, fallbackDate)
        val date = perRecordDate ?: fallbackDate
        val raw = trimmed.trim()
        if (raw.isEmpty()) return null
        // Look for a trailing quantity + optional unit:
        //   `1509 basmati 1`        → qty 1
        //   `Tide drain cleaner 500ml` → qty 500, unit ml
        //   `Babool toothpaste 2 pack` → qty 2, unit pack
        //   `Parle moong dal 2kg`   → qty 2, unit kg
        val qtyMatch = QTY_UNIT_TRAILING_RE.find(raw)
        if (qtyMatch != null) {
            val item = raw.substring(0, qtyMatch.range.first).trim()
            val qty = qtyMatch.groupValues[1].trim().ifEmpty { null }
            val unit = qtyMatch.groupValues[2].trim().ifEmpty { null }
            if (item.isEmpty()) return null
            return buyRecord(item, qty, unit, date)
        }
        // No quantity → item only.
        return buyRecord(raw, null, null, date)
    }

    private fun buyRecord(item: String, qty: String?, unit: String?, date: LocalDate) = JSONObject().apply {
        put("item_text", item)
        put("quantity_text", qty ?: JSONObject.NULL)
        put("unit_text", unit ?: JSONObject.NULL)
        put("date", date.toString())
    }

    // Recognized units after a numeric quantity at the END of the item text.
    private val QTY_UNIT_TRAILING_RE = Regex(
        """\s+(\d+(?:\.\d+)?)\s*(kg|g|ml|l|pack|packet|dozen|box|bottle|piece|pieces|nos|no)?\s*$""",
        RegexOption.IGNORE_CASE,
    )

    // ──────────────────────────────────────────────────────────────
    // Write: todo
    // ──────────────────────────────────────────────────────────────

    private fun parseTodoWrite(body: String, today: LocalDate): ParseResult {
        // For todos we intentionally DON'T comma-split aggressively — many
        // tasks contain commas naturally ("call doctor, ask about meds").
        // Only split on explicit newlines or `;` to keep accuracy high.
        val parts = body.split("\n", ";").map { it.trim() }.filter { it.isNotEmpty() }
        val records = mutableListOf<JSONObject>()
        for (p in parts) {
            val (text, date) = stripTrailingDate(p, today)
            val cleaned = text.trim()
            if (cleaned.isEmpty()) return reject("todo", "incomplete_input")
            records += JSONObject().apply {
                put("text", cleaned)
                put("date", (date ?: today).toString())
            }
        }
        if (records.isEmpty()) return reject("todo", "incomplete_input")
        return acceptWrite("todo", records)
    }

    // ──────────────────────────────────────────────────────────────
    // Write: weight
    // ──────────────────────────────────────────────────────────────

    private fun parseWeightWrite(body: String, today: LocalDate): ParseResult {
        val (stripped, date) = stripTrailingDate(body, today)
        val text = stripped.trim()
        // First number in the body is the value. Anything before it is the
        // person (or "my"); anything after is the note.
        val m = NUMBER_RE.find(text) ?: return reject("weight", "incomplete_input")
        val value = m.value.toDoubleOrNull() ?: return reject("weight", "incomplete_input")
        if (value <= 0.0 || value >= 200.0) return reject("weight", "value_out_of_range")
        val before = text.substring(0, m.range.first).trim()
        val after = text.substring(m.range.last + 1)
            .replace(Regex("""\bkg\b""", RegexOption.IGNORE_CASE), "")
            .trim()
            .trimStart(',', '-', ':')
            .trim()
        // Pull `my` / `my weight` / `weight` prefix as "self" indicator.
        val (personHint, residual) = extractWeightPersonHint(before)
        val person = personHint ?: "self"
        val note = after.takeIf { it.isNotEmpty() && it.lowercase() != "kg" }
        // residual after pulling the person hint should be empty; if not,
        // there's leftover noise — best to surface it as the note tail.
        val noteFinal = listOfNotNull(residual.takeIf { it.isNotEmpty() }, note).joinToString(" ")
            .ifEmpty { null }
        val rec = JSONObject().apply {
            put("person_text", person)
            put("value", normalizeAmountNumber(value))
            put("unit", "kg")
            put("date", (date ?: today).toString())
            put("note", noteFinal ?: JSONObject.NULL)
        }
        return acceptWrite("weight", listOf(rec))
    }

    /**
     * Returns (canonical person, residual). `my` / `my weight` / `weight` /
     * empty → "self"; otherwise the trimmed leading person token.
     */
    private fun extractWeightPersonHint(before: String): Pair<String?, String> {
        val cleaned = before.lowercase()
            .replace(Regex("""\bweight\b"""), "")
            .trim()
        return when {
            cleaned.isEmpty() -> "self" to ""
            cleaned == "my" || cleaned == "i" || cleaned == "me" || cleaned == "myself" -> "self" to ""
            else -> {
                // Strip leading "my" if present (e.g. "my Jeevi" is unusual,
                // but be safe). Use the original casing for the person name.
                val original = before.replace(Regex("""\bweight\b""", RegexOption.IGNORE_CASE), "").trim()
                val parts = original.split(Regex("""\s+"""))
                val first = parts.first()
                if (first.equals("my", true)) "self" to parts.drop(1).joinToString(" ")
                else first to parts.drop(1).joinToString(" ")
            }
        }
    }

    // ──────────────────────────────────────────────────────────────
    // Write: ledger
    // ──────────────────────────────────────────────────────────────

    /**
     * Direction keyword tables. Order matters: longer phrases come first
     * so `paid back` doesn't get swallowed by `paid`.
     */
    private val LEDGER_REPAY_DEBT  = listOf("paid back", "repaid", "repay", "settled with")
    private val LEDGER_COLLECT_CRED = listOf("returned", "paid me back", "gave back")
    private val LEDGER_ADD_CREDIT   = listOf("gave", "lent", "sent", "advanced", "lent to")
    private val LEDGER_ADD_DEBT     = listOf("borrowed from", "got from", "received from", "owe", "i owe", "took from")
    private val LEDGER_SETTLE       = listOf("settled", "cleared", "closed", "wrote off")

    private fun parseLedgerWrite(body: String, today: LocalDate): ParseResult {
        val (stripped, sharedDate) = stripTrailingDate(body, today)
        val parts = splitMulti(stripped)
        val records = mutableListOf<JSONObject>()
        var anyAmbiguous = false
        for (p in parts) {
            val rec = parseSingleLedger(p, sharedDate ?: today)
            when (rec) {
                is LedgerParse.Ok -> records += rec.obj
                is LedgerParse.Ambiguous -> {
                    anyAmbiguous = true
                    records += rec.obj
                }
                is LedgerParse.Fail -> return reject("ledger", "incomplete_input")
            }
        }
        if (records.isEmpty()) return reject("ledger", "incomplete_input")
        return if (anyAmbiguous && records.size == 1)
            confirmWrite("ledger", records, "ambiguous_direction")
        else
            acceptWrite("ledger", records)
    }

    private sealed interface LedgerParse {
        data class Ok(val obj: JSONObject) : LedgerParse
        data class Ambiguous(val obj: JSONObject) : LedgerParse
        object Fail : LedgerParse
    }

    private fun parseSingleLedger(text: String, fallbackDate: LocalDate): LedgerParse {
        val (cleaned, perRecordDate) = stripTrailingDate(text, fallbackDate)
        val date = perRecordDate ?: fallbackDate
        val lower = cleaned.lowercase()

        // Pattern: "X owes me <amt>" → add_credit (X)
        Regex("""(\S+)\s+owes?\s+me\s+(.+)""", RegexOption.IGNORE_CASE).find(cleaned)?.let { m ->
            val person = m.groupValues[1].titleish()
            val amt = parseAmount(m.groupValues[2]) ?: return LedgerParse.Fail
            return LedgerParse.Ok(ledgerRecord(person, "add_credit", amt, date))
        }
        // Pattern: "I owe X <amt>" → add_debt (X)
        Regex("""i\s+owe\s+(\S+)\s+(.+)""", RegexOption.IGNORE_CASE).find(cleaned)?.let { m ->
            val person = m.groupValues[1].titleish()
            val amt = parseAmount(m.groupValues[2]) ?: return LedgerParse.Fail
            return LedgerParse.Ok(ledgerRecord(person, "add_debt", amt, date))
        }

        // settle / close / wrote off: amount may be missing.
        for (kw in LEDGER_SETTLE) {
            val idx = lower.indexOf(kw)
            if (idx >= 0) {
                val rest = cleaned.substring(idx + kw.length).trim()
                val person = rest.split(Regex("""\s+""")).firstOrNull()?.titleish()
                    ?: cleaned.substring(0, idx).trim().split(Regex("""\s+""")).firstOrNull()?.titleish()
                    ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "settle", null, date))
            }
        }

        // Repay (we paid back THEM) — phrase usually has "I" subject.
        for (kw in LEDGER_REPAY_DEBT) {
            if (lower.contains(kw)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "repay_debt", amt, date))
            }
        }
        // Collect credit (they paid us back)
        for (kw in LEDGER_COLLECT_CRED) {
            if (lower.contains(kw)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "collect_credit", amt, date))
            }
        }
        // Add credit (we gave them money)
        for (kw in LEDGER_ADD_CREDIT) {
            if (Regex("""\b$kw\b""", RegexOption.IGNORE_CASE).containsMatchIn(cleaned)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "add_credit", amt, date))
            }
        }
        // Add debt (we received money)
        for (kw in LEDGER_ADD_DEBT) {
            if (lower.contains(kw)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "add_debt", amt, date))
            }
        }

        // No direction keyword. If we can extract `<person> <amt>` →
        // ambiguous; route through confirm flow.
        val parts = cleaned.split(Regex("""\s+"""))
        if (parts.size >= 2) {
            val person = parts.first().titleish()
            val amt = AMOUNT_RE.find(cleaned)?.value?.let { parseAmount(it) }
            if (amt != null) {
                return LedgerParse.Ambiguous(ledgerRecord(person, "add_credit", amt, date))
            }
        }
        return LedgerParse.Fail
    }

    /**
     * Pull the first proper-noun-ish token (not the keyword, not a number,
     * not a stop word) and the first amount in the sentence. Returns null
     * if either is missing.
     */
    private fun extractPersonAndAmount(text: String, keyword: String): Pair<String, Double>? {
        val amt = AMOUNT_RE.find(text)?.value?.let { parseAmount(it) } ?: return null
        val tokens = text.split(Regex("""[\s,]+"""))
            .filter { it.isNotBlank() }
        val stopWords = setOf("i", "me", "to", "from", "the", "a", "an") +
            keyword.split(' ').map { it.lowercase() } +
            // common amount-modifier words we don't want as a person:
            setOf("rs", "rs.", "rupees", "rupee", "thousand", "lakh", "lakhs", "crore", "crores", "k", "l")
        val person = tokens.firstOrNull { tok ->
            val low = tok.lowercase().trimEnd(',', '.', ':')
            low !in stopWords &&
                NUMBER_RE.matchEntire(low) == null &&
                AMOUNT_RE.matchEntire(low) == null &&
                low.any { it.isLetter() }
        }?.trimEnd(',', '.', ':')?.titleish() ?: return null
        return person to amt
    }

    private fun ledgerRecord(person: String, action: String, amount: Double?, date: LocalDate) = JSONObject().apply {
        put("person_text", person)
        put("action", action)
        put("amount", amount?.let { normalizeAmountNumber(it) } ?: JSONObject.NULL)
        put("date", date.toString())
        put("note", JSONObject.NULL)
    }

    // ──────────────────────────────────────────────────────────────
    // Query
    // ──────────────────────────────────────────────────────────────

    private fun parseQuery(body: String, today: LocalDate): ParseResult {
        val text = body.trim()
        val lower = text.lowercase()

        // Pull the "this month" / "last week" / etc. range out FIRST so the
        // remaining phrase determines intent/domain cleanly.
        val (dateRange, residual) = extractDateRangePhrase(lower, today)

        // Domain detection.
        val domain = detectDomain(residual.ifEmpty { lower }) ?: return rejectQuery("manual_unrecognized")

        // Intent + filter detection.
        return when (domain) {
            "expense" -> queryExpense(residual, dateRange, today)
            "buy"     -> queryBuy(residual)
            "todo"    -> queryTodo(residual, dateRange, today)
            "weight"  -> queryWeight(residual, text)
            "ledger"  -> queryLedger(residual, text)
            "note"    -> queryNote(residual, dateRange, text)
            else      -> rejectQuery("manual_unrecognized")
        }
    }

    private fun detectDomain(text: String): String? {
        val t = text.lowercase()
        // ledger first — "balance" / "owe" / "owes" beats anything else.
        if (Regex("""\b(ledger|balance|owe|owes|borrowed|lent)\b""").containsMatchIn(t)) return "ledger"
        if (Regex("""\b(expense|expenses|spend|spent|spending|cost)\b""").containsMatchIn(t)) return "expense"
        if (Regex("""\b(buy|buy list|shopping list|to buy)\b""").containsMatchIn(t)) return "buy"
        if (Regex("""\b(todo|task|tasks|to do)\b""").containsMatchIn(t)) return "todo"
        if (Regex("""\bweight\b""").containsMatchIn(t)) return "weight"
        if (Regex("""\b(note|notes)\b""").containsMatchIn(t)) return "note"
        return null
    }

    // ── expense queries ──
    private fun queryExpense(residual: String, dateRange: DateRange?, today: LocalDate): ParseResult {
        val t = residual.lowercase()
        val intent = when {
            Regex("""\b(total|how much|how many|sum)\b""").containsMatchIn(t) -> "total"
            Regex("""\b(recent|latest)\b""").containsMatchIn(t) -> "list"
            else -> "list"
        }
        val limit = if (Regex("""\b(recent|latest)\b""").containsMatchIn(t)) 10 else null
        // Default range when query mentions expense without a date: this month.
        val range = dateRange ?: if (intent == "total") thisMonth(today) else null
        val filters = JSONObject().apply {
            put("group", JSONObject.NULL)
            put("description_text", JSONObject.NULL)
            put("exclude_group", JSONObject.NULL)
            put("exclude_description_text", JSONObject.NULL)
        }
        return acceptQuery(
            domain = "expense", intent = intent,
            dateStart = range?.start?.toString(), dateEnd = range?.end?.toString(),
            filters = filters, limit = limit, queryText = null,
        )
    }

    // ── buy queries ──
    private fun queryBuy(residual: String): ParseResult {
        val t = residual.lowercase()
        val itemMatch = Regex("""\b(have i added|is\s+\S+\s+on|on (?:shopping|buy)|added)\s+(.+?)\s+(?:to|on|in)\b""")
            .find(t)
        val itemText = when {
            itemMatch != null -> itemMatch.groupValues[2].trim()
            else -> null
        }
        val intent = if (itemText != null) "search" else "list"
        val filters = JSONObject().apply {
            put("status", if (intent == "list") "open" else JSONObject.NULL)
            put("item_text", itemText ?: JSONObject.NULL)
        }
        return acceptQuery(
            domain = "buy", intent = intent,
            dateStart = null, dateEnd = null,
            filters = filters, limit = null, queryText = null,
        )
    }

    // ── todo queries ──
    private fun queryTodo(residual: String, dateRange: DateRange?, today: LocalDate): ParseResult {
        val t = residual.lowercase()
        val intent = when {
            Regex("""\b(history|done|completed|finished)\b""").containsMatchIn(t) -> "history"
            else -> "list"
        }
        val status = when {
            Regex("""\bdone\b""").containsMatchIn(t) -> "done"
            intent == "list" -> "open"
            else -> null
        }
        val range = dateRange ?: if (Regex("""\btoday\b""").containsMatchIn(t)) thisDay(today) else null
        val filters = JSONObject().apply {
            put("status", status ?: JSONObject.NULL)
            put("text_match", JSONObject.NULL)
        }
        return acceptQuery(
            domain = "todo", intent = intent,
            dateStart = range?.start?.toString(), dateEnd = range?.end?.toString(),
            filters = filters, limit = null, queryText = null,
        )
    }

    // ── weight queries ──
    private fun queryWeight(residual: String, originalText: String): ParseResult {
        val t = residual.lowercase()
        val intent = when {
            Regex("""\b(everyone|all|family)\b""").containsMatchIn(t) -> "latest_all"
            Regex("""\bhistory\b""").containsMatchIn(t) -> "history"
            Regex("""\btrend\b""").containsMatchIn(t) -> "trend"
            Regex("""\bchange\b""").containsMatchIn(t) -> "change"
            else -> "latest"
        }
        val personHint = extractPersonFromQuery(originalText)
        val filters = JSONObject().apply {
            put("person_text", personHint ?: when {
                Regex("""\b(my|me|i)\b""").containsMatchIn(t) -> "self"
                intent == "latest_all" -> JSONObject.NULL
                else -> "self"
            })
        }
        return acceptQuery(
            domain = "weight", intent = intent,
            dateStart = null, dateEnd = null,
            filters = filters, limit = null, queryText = null,
        )
    }

    // ── ledger queries ──
    private fun queryLedger(residual: String, originalText: String): ParseResult {
        val t = residual.lowercase()
        val intent = when {
            Regex("""\b(summary)\b""").containsMatchIn(t) -> "summary"
            Regex("""\bbalance\b""").containsMatchIn(t) -> "balance"
            Regex("""\b(recent|latest|list)\b""").containsMatchIn(t) -> "list"
            else -> "summary"
        }
        val perspective = when {
            Regex("""who owes me|who still owes|who all owes me""").containsMatchIn(t) -> "i_owe_them"
            Regex("""who do i owe|i owe""").containsMatchIn(t) -> "they_owe_me"
            else -> null
        }
        val personHint = extractPersonFromQuery(originalText)
        val filters = JSONObject().apply {
            put("person_text", personHint ?: JSONObject.NULL)
            put("perspective", perspective ?: JSONObject.NULL)
            put("status", "open")
        }
        return acceptQuery(
            domain = "ledger", intent = intent,
            dateStart = null, dateEnd = null,
            filters = filters, limit = null, queryText = null,
        )
    }

    // ── note queries ──
    private fun queryNote(residual: String, dateRange: DateRange?, originalText: String): ParseResult {
        val t = residual.lowercase()
        val intent = when {
            Regex("""\b(list|bucket|week|month|day)\b""").containsMatchIn(t) && dateRange != null -> "list"
            Regex("""\b(latest|most recent)\b""").containsMatchIn(t) -> "latest"
            else -> "search"
        }
        // For search intent, query_text = the residual stripped of obvious framing words.
        val searchText = if (intent == "search") {
            originalText.replace(Regex("""\b(note|notes|about|on|the|of|saved)\b""", RegexOption.IGNORE_CASE), "")
                .trim().ifEmpty { null }
        } else null
        return acceptQuery(
            domain = "note",
            intent = intent,
            dateStart = dateRange?.start?.toString(),
            dateEnd = dateRange?.end?.toString(),
            filters = JSONObject(),  // note filters are always empty per schema
            limit = null,
            queryText = searchText,
        )
    }

    /**
     * Pull a Capitalised-Word person hint from a query like
     * `ask: Kishore latest weight` or `ask: Maddy balance`. Returns null
     * if the text has no obvious proper-noun person token.
     */
    private fun extractPersonFromQuery(text: String): String? {
        // Strip leading "ask: " framing.
        val cleaned = text.removePrefix("ask:").trim()
        // First token that starts with an uppercase letter and isn't a
        // stop word.
        val tokens = cleaned.split(Regex("""\s+"""))
        val stop = setOf("ask", "show", "list", "latest", "my", "his", "her", "their", "weight",
            "balance", "expense", "buy", "todo", "note", "ledger", "summary", "recent")
        return tokens.firstOrNull { tok ->
            tok.isNotEmpty() && tok[0].isUpperCase() && tok.lowercase() !in stop
        }?.trimEnd(',', '.', ':')
    }

    // ──────────────────────────────────────────────────────────────
    // Amounts
    // ──────────────────────────────────────────────────────────────

    /** Match any plausible amount-looking token (used to find positions). */
    private val AMOUNT_RE = Regex(
        """(?:rs\.?\s*|₹\s*|usd\s+|\$\s*)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:/-|k|l|crore|crores|lakh|lakhs|thousand)?""",
        RegexOption.IGNORE_CASE,
    )

    /** Just digits + optional decimal. Used for value-shaped fields like weight. */
    private val NUMBER_RE = Regex("""\d+(?:\.\d+)?""")

    /** `<desc>:<amount>` — used by the expense dataset's colon-separator rows. */
    private val COLON_AMOUNT_RE = Regex(
        """([A-Za-z][\w\s'\-]*?)\s*:\s*((?:rs\.?\s*|₹\s*|\$\s*)?\d+(?:[\.,]\d+)?\s*(?:k|l|crore|crores|lakh|lakhs|thousand)?)""",
        RegexOption.IGNORE_CASE,
    )

    private fun parseAmount(raw: String): Double? {
        val t = raw.trim().lowercase()
            .removePrefix("rs.")
            .removePrefix("rs")
            .removePrefix("₹")
            .removePrefix("usd")
            .removePrefix("$")
            .trim()
            .removeSuffix("/-")
            .trim()
        val numMatch = NUMBER_RE.find(t) ?: return null
        val base = numMatch.value.replace(",", "").toDoubleOrNull() ?: return null
        val tail = t.substring(numMatch.range.last + 1).trim()
        return when {
            tail == "k" || tail == "thousand" -> base * 1000.0
            tail == "l" || tail == "lakh" || tail == "lakhs" -> base * 100000.0
            tail == "crore" || tail == "crores" -> base * 10000000.0
            else -> base
        }
    }

    private fun normalizeAmountNumber(v: Double): Any {
        // Keep integers as integers in JSON for cleaner round-trips
        // (the LLM emits 5000, not 5000.0).
        val asLong = v.toLong()
        return if (kotlin.math.abs(v - asLong) < 1e-9) asLong else v
    }

    // ──────────────────────────────────────────────────────────────
    // Dates
    // ──────────────────────────────────────────────────────────────

    private data class DateRange(val start: LocalDate, val end: LocalDate)

    private fun thisDay(today: LocalDate) = DateRange(today, today)
    private fun thisMonth(today: LocalDate) = DateRange(
        today.withDayOfMonth(1),
        today.with(TemporalAdjusters.lastDayOfMonth()),
    )
    private fun lastMonth(today: LocalDate): DateRange {
        val anchor = today.minusMonths(1)
        return DateRange(
            anchor.withDayOfMonth(1),
            anchor.with(TemporalAdjusters.lastDayOfMonth()),
        )
    }
    private fun thisWeek(today: LocalDate) = DateRange(
        today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)),
        today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY)),
    )
    private fun lastWeek(today: LocalDate): DateRange {
        val mon = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)).minusWeeks(1)
        return DateRange(mon, mon.plusDays(6))
    }
    private fun thisYear(today: LocalDate) = DateRange(
        LocalDate.of(today.year, 1, 1),
        LocalDate.of(today.year, 12, 31),
    )
    private fun lastYear(today: LocalDate) = DateRange(
        LocalDate.of(today.year - 1, 1, 1),
        LocalDate.of(today.year - 1, 12, 31),
    )

    /**
     * If the (lowercased) text mentions a canonical date range phrase,
     * return the resolved range AND the same text with the phrase stripped
     * so downstream intent/domain detection isn't confused by it.
     */
    private fun extractDateRangePhrase(lower: String, today: LocalDate): Pair<DateRange?, String> {
        // Order matters: longer phrases first.
        val phrases = listOf(
            "last month"  to lastMonth(today),
            "this month"  to thisMonth(today),
            "current month" to thisMonth(today),
            "last week"   to lastWeek(today),
            "this week"   to thisWeek(today),
            "current week" to thisWeek(today),
            "last year"   to lastYear(today),
            "this year"   to thisYear(today),
            "current year" to thisYear(today),
            "today"       to thisDay(today),
            "yesterday"   to thisDay(today.minusDays(1)),
            "tomorrow"    to thisDay(today.plusDays(1)),
        )
        for ((phrase, range) in phrases) {
            val idx = lower.indexOf(phrase)
            if (idx >= 0) {
                val residual = (lower.substring(0, idx) + lower.substring(idx + phrase.length)).trim()
                return range to residual
            }
        }
        return null to lower
    }

    /**
     * If the input ends with a canonical date phrase, return (stripped, date).
     * Used by write parsers so multi-record lines like `petrol 500, milk 60
     * yesterday` apply the date to BOTH records.
     */
    private fun stripTrailingDate(text: String, today: LocalDate): Pair<String, LocalDate?> {
        val lower = text.lowercase()
        val phrases = listOf(
            "yesterday"   to today.minusDays(1),
            "tomorrow"    to today.plusDays(1),
            "today"       to today,
        )
        for ((phrase, date) in phrases) {
            if (lower.endsWith(phrase)) {
                val stripped = text.substring(0, text.length - phrase.length).trim().trimEnd(',', ';')
                return stripped to date
            }
            // Also accept when followed by punctuation
            val withComma = "$phrase"
            val idx = lower.lastIndexOf(withComma)
            if (idx >= 0 && idx == lower.length - withComma.length) {
                val stripped = text.substring(0, idx).trim().trimEnd(',', ';')
                return stripped to date
            }
        }
        // `DD MMM YYYY` / `DD MMM` / `MMM DD` at the end
        val absoluteMatch = TRAILING_ABSOLUTE_DATE_RE.find(text)
        if (absoluteMatch != null) {
            val parsed = parseAbsoluteDate(absoluteMatch.value.trim(), today)
            if (parsed != null) {
                val stripped = text.substring(0, absoluteMatch.range.first).trim().trimEnd(',', ';')
                return stripped to parsed
            }
        }
        return text to null
    }

    /** Matches `15 jan`, `15 jan 2026`, `Jan 15`, `Jan 15 2026`, `15-01`, `15-01-2026`, `15/01/2026`. */
    private val TRAILING_ABSOLUTE_DATE_RE = Regex(
        """\s+(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|july|aug|sep|sept|oct|nov|dec)\w*(?:\s+\d{4})?|""" +
            """(?:jan|feb|mar|apr|may|jun|jul|july|aug|sep|sept|oct|nov|dec)\w*\s+\d{1,2}(?:\s+\d{4})?|""" +
            """\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?)\s*$""",
        RegexOption.IGNORE_CASE,
    )

    private fun parseAbsoluteDate(raw: String, today: LocalDate): LocalDate? {
        val t = raw.trim().lowercase()
        // Try numeric DD-MM-YYYY / DD/MM/YYYY / DD-MM / DD/MM.
        val numMatch = Regex("""^(\d{1,2})[-/](\d{1,2})(?:[-/](\d{2,4}))?$""").matchEntire(t)
        if (numMatch != null) {
            val d = numMatch.groupValues[1].toInt()
            val m = numMatch.groupValues[2].toInt()
            val y = numMatch.groupValues[3].ifEmpty { today.year.toString() }
                .let { if (it.length == 2) "20$it" else it }.toInt()
            return runCatching { LocalDate.of(y, m, d) }.getOrNull()
        }
        // Month-name forms.
        for (fmt in MONTH_NAME_FORMATTERS) {
            val parsed = runCatching { LocalDate.parse(t, fmt) }.getOrNull()
            if (parsed != null) return parsed
            // Without year — infer current year.
            val withYear = runCatching {
                LocalDate.parse("$t ${today.year}", DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH))
            }.getOrNull()
            if (withYear != null) return withYear
            val withYearReversed = runCatching {
                LocalDate.parse("$t ${today.year}", DateTimeFormatter.ofPattern("MMM d yyyy", Locale.ENGLISH))
            }.getOrNull()
            if (withYearReversed != null) return withYearReversed
        }
        return null
    }

    private val MONTH_NAME_FORMATTERS = listOf(
        DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH),
        DateTimeFormatter.ofPattern("d MMMM yyyy", Locale.ENGLISH),
        DateTimeFormatter.ofPattern("MMM d yyyy", Locale.ENGLISH),
        DateTimeFormatter.ofPattern("MMMM d yyyy", Locale.ENGLISH),
    )

    // ──────────────────────────────────────────────────────────────
    // Multi-record split
    // ──────────────────────────────────────────────────────────────

    /**
     * Split a multi-record write body on `,` `;` `|` `&` ` and `. The split
     * is unaware of context — fine for expense / buy / ledger writes whose
     * records don't naturally contain commas. Todos use a more conservative
     * split (only `\n` and `;`).
     */
    private fun splitMulti(body: String): List<String> {
        return body.split(Regex("""\s*(?:,|;|\||&|\sand\s)\s*"""))
            .map { it.trim() }
            .filter { it.isNotEmpty() }
    }

    // ──────────────────────────────────────────────────────────────
    // Output builders
    // ──────────────────────────────────────────────────────────────

    private fun acceptWrite(lane: String, records: List<JSONObject>): ParseResult {
        val obj = JSONObject().apply {
            put("task", "parse_write")
            put("lane", lane)
            put("disposition", "accept")
            put("reason_code", JSONObject.NULL)
            put("records", JSONArray(records))
        }
        return ParserValidator.parse(obj, obj.toString())
    }

    private fun confirmWrite(lane: String, records: List<JSONObject>, reasonCode: String): ParseResult {
        val obj = JSONObject().apply {
            put("task", "parse_write")
            put("lane", lane)
            put("disposition", "confirm")
            put("reason_code", reasonCode)
            put("records", JSONArray(records))
        }
        return ParserValidator.parse(obj, obj.toString())
    }

    private fun acceptQuery(
        domain: String,
        intent: String,
        dateStart: String?,
        dateEnd: String?,
        filters: JSONObject,
        limit: Int?,
        queryText: String?,
    ): ParseResult {
        val obj = JSONObject().apply {
            put("task", "parse_query")
            put("domain", domain)
            put("disposition", "accept")
            put("intent", intent)
            put("date_start", dateStart ?: JSONObject.NULL)
            put("date_end", dateEnd ?: JSONObject.NULL)
            put("compare_date_start", JSONObject.NULL)
            put("compare_date_end", JSONObject.NULL)
            put("filters", filters)
            put("limit", limit ?: JSONObject.NULL)
            put("query_text", queryText ?: JSONObject.NULL)
            put("reason_code", JSONObject.NULL)
            put("clarify_reason", JSONObject.NULL)
            put("clarify_options", JSONObject.NULL)
        }
        return ParserValidator.parse(obj, obj.toString())
    }

    private fun reject(lane: String?, reasonCode: String): ParseResult {
        // Lane is required by the validator for parse_write. Pick a
        // best-guess lane; if we truly don't know, route to expense (the
        // most common lane) — the reject disposition means no record is
        // written so the choice is cosmetic.
        val obj = JSONObject().apply {
            put("task", "parse_write")
            put("lane", lane ?: "expense")
            put("disposition", "reject")
            put("reason_code", reasonCode)
            put("records", JSONArray())
        }
        return ParserValidator.parse(obj, obj.toString())
    }

    private fun rejectQuery(reasonCode: String): ParseResult {
        val obj = JSONObject().apply {
            put("task", "parse_query")
            put("domain", "note")    // domain required; placeholder for reject
            put("disposition", "reject")
            put("intent", JSONObject.NULL)
            put("date_start", JSONObject.NULL)
            put("date_end", JSONObject.NULL)
            put("compare_date_start", JSONObject.NULL)
            put("compare_date_end", JSONObject.NULL)
            put("filters", JSONObject())
            put("limit", JSONObject.NULL)
            put("query_text", JSONObject.NULL)
            put("reason_code", reasonCode)
            put("clarify_reason", JSONObject.NULL)
            put("clarify_options", JSONObject.NULL)
        }
        return ParserValidator.parse(obj, obj.toString())
    }

    // ──────────────────────────────────────────────────────────────
    // String helpers
    // ──────────────────────────────────────────────────────────────

    /** Capitalize first letter, lowercase the rest. Used for person names. */
    private fun String.titleish(): String =
        if (isEmpty()) this
        else this[0].uppercaseChar() + substring(1).lowercase()
}
