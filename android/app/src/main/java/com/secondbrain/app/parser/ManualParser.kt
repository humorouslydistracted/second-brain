package com.secondbrain.app.parser

import android.content.Context
import com.secondbrain.app.SecondBrainApp
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
 * fine-tuned LLM produces. Selected at runtime via [com.secondbrain.app.data.ModelRegistry]
 * using the literal sentinel `"manual"`; when active, [ParserService]
 * dispatches here instead of calling the GGUF.
 *
 * V1.1 (2026-05-11): improved coverage based on offline eval against
 * `synthetic_finetune_dataset_v4_v2_schema/` (55,000 golden rows).
 * V1 → V1.1 lifted overall exact-match from 30.8% → 41.4% (+10.6 pp).
 *
 * Stays in lockstep with `manual_parser.py` (the Python mirror used by
 * `evaluate_manual_parser.py`). When you change one side, change the
 * other or eval numbers will diverge from real device behavior.
 *
 * V1.1 changes vs V1:
 *   - Expense group inference via `assets/expense_groups.json` (sourced
 *     from synthetic_dataset_assets.py: ~2400 item→group + ~520
 *     word→group entries).
 *   - Newline split on buy + bullet stripping on buy/todo.
 *   - Multi-person weight comma-split.
 *   - Date phrase expansion: `next/last <day>`, `weekend`/`wknd`,
 *     `<month> <ordinal> week`, `first/second half of <month>`,
 *     `<n> days ago`, bare `<month>`, `week close`.
 *   - Domain detection: chip-prefix-aware, frequency-tuned ledger
 *     signals (`entries`/`activity`/`borrow`/`lend`/`stand`/etc. with
 *     `history` deliberately excluded — too ambiguous).
 *   - Intent classifiers: data-driven priorities for expense (cost ~
 *     100% total, expense-singular ~75% total), todo (search via
 *     anchor patterns), ledger (balance vs summary vs list).
 *   - Buy search with generic-noun guard so `things to buy` / `what
 *     to buy` stay as `list` intent.
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
    // Expense group inference (V1.1)
    // ──────────────────────────────────────────────────────────────

    /**
     * Lazy load of the asset JSON. Two-pass lookup (item-text exact /
     * substring → word-vote). Identical to manual_parser.py.
     */
    @Volatile private var groupsLoaded = false
    private val itemToGroup = HashMap<String, String>()
    private val wordToGroup = HashMap<String, String>()

    private fun ensureGroupsLoaded() {
        if (groupsLoaded) return
        synchronized(this) {
            if (groupsLoaded) return
            try {
                val context: Context = SecondBrainApp.appContext
                val raw = context.assets.open("expense_groups.json").use { stream ->
                    stream.bufferedReader().readText()
                }
                val obj = JSONObject(raw)
                val items = obj.optJSONObject("items") ?: JSONObject()
                val itemKeys = items.keys()
                while (itemKeys.hasNext()) {
                    val k = itemKeys.next()
                    itemToGroup[k] = items.optString(k)
                }
                val words = obj.optJSONObject("words") ?: JSONObject()
                val wordKeys = words.keys()
                while (wordKeys.hasNext()) {
                    val k = wordKeys.next()
                    wordToGroup[k] = words.optString(k)
                }
            } catch (_: Throwable) {
                // Asset absent → group inference disabled, returns null.
            }
            groupsLoaded = true
        }
    }

    private fun inferGroup(description: String): String? {
        if (description.isBlank()) return null
        ensureGroupsLoaded()
        val norm = description.trim().lowercase()
        itemToGroup[norm]?.let { return it }
        // Substring containment for verbose user-typed entries.
        for ((k, v) in itemToGroup) {
            if (norm.contains(k)) return v
        }
        // Word-level vote.
        val votes = HashMap<String, Int>()
        for (w in norm.split(Regex("[^a-z0-9]+"))) {
            if (w.length >= 4) {
                wordToGroup[w]?.let { g ->
                    votes[g] = (votes[g] ?: 0) + 1
                }
            }
        }
        return votes.maxByOrNull { it.value }?.key
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
        val colonMatch = COLON_AMOUNT_RE.find(trimmed)
        if (colonMatch != null) {
            val desc = stripCurrencyWords(colonMatch.groupValues[1])
            val amt = parseAmount(colonMatch.groupValues[2]) ?: return null
            if (desc.isEmpty()) return null
            return expenseRecord(desc, amt, date)
        }
        val m = AMOUNT_RE.find(trimmed) ?: return null
        val before = stripCurrencyWords(trimmed.substring(0, m.range.first))
        val after = stripCurrencyWords(trimmed.substring(m.range.last + 1))
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
        val grp = inferGroup(description)
        put("group", grp ?: JSONObject.NULL)
    }

    // ──────────────────────────────────────────────────────────────
    // Write: buy
    // ──────────────────────────────────────────────────────────────

    private fun parseBuyWrite(body: String, today: LocalDate): ParseResult {
        val (stripped, sharedDate) = stripTrailingDate(body, today)
        val parts = splitMultiNl(stripped)
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
        // Strip leading bullets and filler verbs (`pick up` / `get` / `grab`).
        var raw = trimmed.trim().replace(Regex("""^[\-\*•\d]+[\.\)]?\s+"""), "")
        raw = raw.replace(Regex("""^(?:pick\s+up|get|grab|buy)\s+""", RegexOption.IGNORE_CASE), "").trim()
        if (raw.isEmpty()) return null
        val qtyMatch = QTY_UNIT_TRAILING_RE.find(raw)
        if (qtyMatch != null) {
            val item = raw.substring(0, qtyMatch.range.first).trim()
            val qty = qtyMatch.groupValues[1].trim().ifEmpty { null }
            val unit = qtyMatch.groupValues[2].trim().ifEmpty { null }
            if (item.isEmpty()) return null
            return buyRecord(item, qty, unit, date)
        }
        return buyRecord(raw, null, null, date)
    }

    private fun buyRecord(item: String, qty: String?, unit: String?, date: LocalDate) = JSONObject().apply {
        put("item_text", item)
        put("quantity_text", qty ?: JSONObject.NULL)
        put("unit_text", unit ?: JSONObject.NULL)
        put("date", date.toString())
    }

    private val QTY_UNIT_TRAILING_RE = Regex(
        """\s+(\d+(?:\.\d+)?)\s*(kg|g|ml|l|pack|packet|dozen|box|bottle|piece|pieces|nos|no)?\s*$""",
        RegexOption.IGNORE_CASE,
    )

    // ──────────────────────────────────────────────────────────────
    // Write: todo
    // ──────────────────────────────────────────────────────────────

    private fun parseTodoWrite(body: String, today: LocalDate): ParseResult {
        var parts = body.split("\n", ";").map { it.trim() }.filter { it.isNotEmpty() }
        if (parts.size == 1) {
            val sole = parts.first()
            val commaParts = sole.split(",").map { it.trim() }.filter { it.isNotEmpty() }
            if (commaParts.size >= 2 && commaParts.all { it.length >= 3 }) {
                parts = commaParts
            }
        }
        val records = mutableListOf<JSONObject>()
        for (p in parts) {
            val cleanP = p.replace(Regex("""^[\-\*•\d]+[\.\)]?\s+"""), "")
            val (text, date) = stripTrailingDate(cleanP, today)
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
        val (stripped, sharedDate) = stripTrailingDate(body, today)
        val parts = splitMulti(stripped)
        if (parts.size > 1) {
            val records = mutableListOf<JSONObject>()
            for (p in parts) {
                val rec = parseSingleWeight(p, sharedDate ?: today) ?: return reject("weight", "incomplete_input")
                records += rec
            }
            return acceptWrite("weight", records)
        }
        val rec = parseSingleWeight(stripped, sharedDate ?: today) ?: return reject("weight", "incomplete_input")
        return acceptWrite("weight", listOf(rec))
    }

    private fun parseSingleWeight(text: String, fallbackDate: LocalDate): JSONObject? {
        val (innerStripped, perRecordDate) = stripTrailingDate(text, fallbackDate)
        val recDate = perRecordDate ?: fallbackDate
        val s = innerStripped.trim()
        val m = NUMBER_RE.find(s) ?: return null
        val value = m.value.toDoubleOrNull() ?: return null
        if (value <= 0.0 || value >= 200.0) return null
        val before = s.substring(0, m.range.first).trim()
        val after = s.substring(m.range.last + 1)
            .replace(Regex("""\bkg\b""", RegexOption.IGNORE_CASE), "")
            .trim()
            .trimStart(',', '-', ':')
            .trim()
        val (personHint, residual) = extractWeightPersonHint(before)
        val person = personHint ?: "self"
        val note = after.takeIf { it.isNotEmpty() && it.lowercase() != "kg" }
        val noteFinal = listOfNotNull(residual.takeIf { it.isNotEmpty() }, note).joinToString(" ")
            .ifEmpty { null }
        return JSONObject().apply {
            put("person_text", person)
            put("value", normalizeAmountNumber(value))
            put("unit", "kg")
            put("date", recDate.toString())
            put("note", noteFinal ?: JSONObject.NULL)
        }
    }

    private fun extractWeightPersonHint(before: String): Pair<String?, String> {
        val cleaned = before.lowercase()
            .replace(Regex("""\bweight\b"""), "")
            .trim()
        return when {
            cleaned.isEmpty() -> "self" to ""
            cleaned == "my" || cleaned == "i" || cleaned == "me" || cleaned == "myself" -> "self" to ""
            else -> {
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

        Regex("""(\S+)\s+owes?\s+me\s+(.+)""", RegexOption.IGNORE_CASE).find(cleaned)?.let { m ->
            val person = m.groupValues[1].titleish()
            val amt = parseAmount(m.groupValues[2]) ?: return LedgerParse.Fail
            return LedgerParse.Ok(ledgerRecord(person, "add_credit", amt, date))
        }
        Regex("""i\s+owe\s+(\S+)\s+(.+)""", RegexOption.IGNORE_CASE).find(cleaned)?.let { m ->
            val person = m.groupValues[1].titleish()
            val amt = parseAmount(m.groupValues[2]) ?: return LedgerParse.Fail
            return LedgerParse.Ok(ledgerRecord(person, "add_debt", amt, date))
        }

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

        for (kw in LEDGER_REPAY_DEBT) {
            if (lower.contains(kw)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "repay_debt", amt, date))
            }
        }
        for (kw in LEDGER_COLLECT_CRED) {
            if (lower.contains(kw)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "collect_credit", amt, date))
            }
        }
        for (kw in LEDGER_ADD_CREDIT) {
            if (Regex("""\b$kw\b""", RegexOption.IGNORE_CASE).containsMatchIn(cleaned)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "add_credit", amt, date))
            }
        }
        for (kw in LEDGER_ADD_DEBT) {
            if (lower.contains(kw)) {
                val (person, amt) = extractPersonAndAmount(cleaned, kw) ?: return LedgerParse.Fail
                return LedgerParse.Ok(ledgerRecord(person, "add_debt", amt, date))
            }
        }

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

    private fun extractPersonAndAmount(text: String, keyword: String): Pair<String, Double>? {
        val amt = AMOUNT_RE.find(text)?.value?.let { parseAmount(it) } ?: return null
        val tokens = text.split(Regex("""[\s,]+"""))
            .filter { it.isNotBlank() }
        val stopWords = setOf("i", "me", "to", "from", "the", "a", "an") +
            keyword.split(' ').map { it.lowercase() } +
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
        val (dateRange, residual) = extractDateRangePhrase(lower, today)
        val domain = detectDomain(residual.ifEmpty { lower }) ?: return rejectQuery("manual_unrecognized")
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

    /**
     * V1.1.1 priority order. See manual_parser.py for the rationale.
     */
    private fun detectDomain(text: String): String? {
        val t = text.lowercase()

        // 1. Embedded chip prefix ("ask: todo: pending tasks").
        Regex("""\b(todo|task|tasks|expense|buy|weight|ledger|note)\s*:""").find(t)?.let { m ->
            return when (val word = m.groupValues[1]) {
                "todo", "task", "tasks" -> "todo"
                else -> word
            }
        }

        // 2a. Strong domain nouns.
        if (Regex("""\b(weight|weighing)\b""").containsMatchIn(t)) return "weight"
        if (Regex("""\b(todos?|tasks?|to\s*do|reminders?)\b""").containsMatchIn(t)) return "todo"
        if ("on my list" in t || "in my list" in t || "to-do" in t) return "todo"
        if (Regex("""\b(done|finished|completed)\s+(today|this\s+week|yesterday|last\s+week)\b""").containsMatchIn(t)) return "todo"
        if (Regex("""\b(what|which)\s+did\s+i\s+(finish|complete|do)\b""").containsMatchIn(t)) return "todo"
        if (Regex("""\b(shopping(\s+list)?|buy(\s+list)?|to\s+buy)\b""").containsMatchIn(t)) return "buy"
        if (Regex("""\b(expenses?|spend|spent|spending|spendings?|costs?)\b""").containsMatchIn(t)) return "expense"

        // 3. Ledger-shape signals.
        val ledgerSignals = Regex(
            """\b(ledger|balance|balances|owe|owes|owed|borrowed|borrow|borrows|""" +
                """lent|lend|lends|outstanding|dues|entries|activity|activities)\b"""
        )
        if (ledgerSignals.containsMatchIn(t)) return "ledger"
        if (Regex("""\bpending\b""").containsMatchIn(t)) return "ledger"
        if (Regex("""\b(clear|wrote off|cleared|settled\s+with|settle|close\s+out)\b""").containsMatchIn(t)) return "ledger"
        if (Regex("""\b(where\s+do\s+i\s+stand|stand\s+with)\b""").containsMatchIn(t)) return "ledger"
        if (Regex("""\bwho\s+(?:still\s+)?(?:all\s+)?(?:owes?|i\s+owe|do\s+i\s+owe)\b""").containsMatchIn(t)) return "ledger"
        if (Regex("""\b(transactions?|account)\b""").containsMatchIn(t)) return "ledger"

        // 4. Note / bucket as catch-all.
        if (Regex("""\b(notes?|bucket)\b""").containsMatchIn(t)) return "note"
        return null
    }

    // ── expense queries ──
    private fun queryExpense(residual: String, dateRange: DateRange?, today: LocalDate): ParseResult {
        val t = residual.lowercase()
        val strongTotal = Regex("""\b(total|summary|tally|how\s+much|how\s+many|sum)\b""").containsMatchIn(t)
        val strongList = Regex("""\b(list|breakdown|top\s+\d+|biggest|highest|last\s+\d+|recent|latest|show\s+(?:all|me)\s+(?:all|the))\b""").containsMatchIn(t)
        val weakTotal = Regex("""\b(costs?|expense|spending|spend\s+on|spent\s+on)\b""").containsMatchIn(t)
        val hasExpensesPlural = Regex("""\bexpenses\b""").containsMatchIn(t)

        val intent = when {
            strongTotal -> "total"
            strongList -> "list"
            weakTotal && !hasExpensesPlural -> "total"
            else -> "list"
        }
        var limit: Int? = null
        Regex("""\b(?:last|top)\s+(\d+)\b""").find(t)?.let { m -> limit = m.groupValues[1].toInt() }
        if (limit == null && Regex("""\b(recent|latest)\b""").containsMatchIn(t)) limit = 10
        val rng = dateRange ?: if (intent == "total") thisMonth(today) else null
        val filters = JSONObject().apply {
            put("group", JSONObject.NULL)
            put("description_text", JSONObject.NULL)
            put("exclude_group", JSONObject.NULL)
            put("exclude_description_text", JSONObject.NULL)
        }
        return acceptQuery(
            domain = "expense", intent = intent,
            dateStart = rng?.start?.toString(), dateEnd = rng?.end?.toString(),
            filters = filters, limit = limit, queryText = null,
        )
    }

    // ── buy queries ──
    private val GENERIC_BUY_NOUNS = setOf(
        "what", "what's", "whats", "things", "items", "stuff", "anything",
        "something", "everything", "nothing", "show items", "show what",
        "what do i need", "what i need",
    )

    private fun queryBuy(residual: String): ParseResult {
        val t = residual.lowercase()
        val patterns = listOf(
            Regex("""\bis\s+(.+?)\s+(?:on|in)\s+(?:my\s+)?(?:buy|shopping)\s*(?:list)?\s*$"""),
            Regex("""\bdid\s+i\s+add\s+(.+?)\s+to\s+(?:the\s+|my\s+)?(?:buy|shopping)\s*(?:list)?\s*$"""),
            Regex("""\badd\s+(.+?)\s+to\s+(?:the\s+|my\s+)?(?:buy|shopping)\s*(?:list)?\s*$"""),
            Regex("""\bshow\s+(.+?)\s+(?:in|on)\s+(?:my\s+)?(?:buy|shopping)\s*(?:list)?\s*$"""),
            Regex("""\b(?:find|look\s+up)\s+(.+?)$"""),
            Regex("""\bhave\s+i\s+(?:added|bought)\s+(.+?)\s+(?:to|on|in|$)"""),
            Regex("""\bany\s+(.+?)\s+(?:in|on)\s+(?:my\s+)?(?:buy|shopping)\s*(?:list)?\s*$"""),
            Regex("""^(.+?)\s+(?:in|on)\s+(?:my\s+)?(?:buy|shopping)\s+list\s*$"""),
        )
        var itemText: String? = null
        for (pat in patterns) {
            val m = pat.find(t) ?: continue
            val cand = m.groupValues[1].trim().trimEnd(',', '.', ':')
                .replace(Regex("""^(?:buy|shopping)\s*:?\s*""", RegexOption.IGNORE_CASE), "")
            if (cand.isNotEmpty() && cand.lowercase() !in GENERIC_BUY_NOUNS) {
                itemText = cand
                break
            }
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
        val searchPatterns = listOf(
            Regex("""^(.+?)\s+on\s+my\s+list\s*$"""),
            Regex("""\b(?:find|look\s+up|locate)\s+(.+?)(?:\s+on\s+my\s+list)?\s*$"""),
            Regex("""\bsearch\s+my\s+todos?\s+for\s+(.+?)\s*$"""),
            Regex("""^remind\s+(.+?)\s+on\s+my\s+list\s*$"""),
            Regex("""\bdo\s+i\s+have\s+(.+?)\s+(?:pending|todo|task)\s*$"""),
        )
        var textMatch: String? = null
        for (pat in searchPatterns) {
            val m = pat.find(t) ?: continue
            val cand = m.groupValues[1].trim().trimEnd(',', '.', ':')
                .replace(Regex("""^(?:todo|tasks?|to\s*do)\s*:?\s*""", RegexOption.IGNORE_CASE), "")
            if (cand.isNotEmpty()) {
                textMatch = cand
                break
            }
        }
        val isDoneQuery = Regex("""\b(done|finished|completed)\b""").containsMatchIn(t)
        val isHistory = Regex("""\bhistory\b""").containsMatchIn(t) && textMatch == null

        val intent: String
        val status: String?
        when {
            textMatch != null -> { intent = "search"; status = null }
            isHistory -> { intent = "history"; status = null }
            else -> { intent = "list"; status = if (isDoneQuery) "done" else "open" }
        }

        val rng = dateRange ?: if (Regex("""\btoday\b""").containsMatchIn(t)) thisDay(today) else null
        val filters = JSONObject().apply {
            put("status", status ?: JSONObject.NULL)
            put("text_match", textMatch ?: JSONObject.NULL)
        }
        return acceptQuery(
            domain = "todo", intent = intent,
            dateStart = rng?.start?.toString(), dateEnd = rng?.end?.toString(),
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
        val personHint = extractPersonFromQuery(originalText)
        val hasRecentMarker = Regex("""\b(recent|latest|recent\s+entries|recent\s+transactions|last\s+\d+)\b""").containsMatchIn(t)
        val hasHistoryMarker = Regex("""\b(history|transactions|entries)\b""").containsMatchIn(t)
        val hasBalanceMarker = Regex("""\bbalance(s)?\b""").containsMatchIn(t)
        val hasSummaryMarker = Regex("""\b(summary|outstanding|pending|dues|open\s+balances?|where\s+do\s+my)\b""").containsMatchIn(t)
        val hasWhoMarker = Regex("""\bwho\s+(?:still\s+)?(?:all\s+)?(?:owes?|i\s+owe|do\s+i\s+owe)\b""").containsMatchIn(t)

        val intent: String
        var limit: Int? = null
        when {
            hasRecentMarker -> {
                intent = "list"
                limit = 10
                Regex("""\blast\s+(\d+)\b""").find(t)?.let { m -> limit = m.groupValues[1].toInt() }
            }
            hasHistoryMarker && personHint != null -> intent = "list"
            personHint != null && hasBalanceMarker -> intent = "balance"
            personHint != null && !hasSummaryMarker -> intent = "balance"
            hasWhoMarker || hasSummaryMarker -> intent = "summary"
            hasBalanceMarker -> intent = "summary"
            else -> intent = "summary"
        }

        val perspective = when {
            Regex("""who\s+(?:still\s+)?(?:all\s+)?owes?\s+me""").containsMatchIn(t) -> "i_owe_them"
            Regex("""who\s+do\s+i\s+owe|how\s+much\s+do\s+i\s+owe|^i\s+owe\b""").containsMatchIn(t) -> "they_owe_me"
            else -> null
        }
        val filters = JSONObject().apply {
            put("person_text", personHint ?: JSONObject.NULL)
            put("perspective", perspective ?: JSONObject.NULL)
            put("status", "open")
        }
        return acceptQuery(
            domain = "ledger", intent = intent,
            dateStart = null, dateEnd = null,
            filters = filters, limit = limit, queryText = null,
        )
    }

    // ── note queries ──
    private fun queryNote(residual: String, dateRange: DateRange?, originalText: String): ParseResult {
        val t = residual.lowercase()
        val intent = when {
            Regex("""\b(latest|most recent)\b""").containsMatchIn(t) -> "latest"
            dateRange != null -> "list"
            else -> "search"
        }
        val searchText: String? = if (intent == "search") {
            var cleaned = originalText
                .replace(Regex("""^\s*ask\s*:\s*""", RegexOption.IGNORE_CASE), "")
                .replace(Regex("""^\s*note\s*:\s*""", RegexOption.IGNORE_CASE), "")
            cleaned = cleaned.replace(
                Regex(
                    """\b(any\s+mention\s+of|any\s+notes?\s+about|find|look\s+up|""" +
                        """search\s+(?:my\s+)?notes?\s+for|did\s+i\s+note\s+anything\s+about|""" +
                        """have\s+i\s+noted\s+anything\s+about|in\s+my\s+notes?|notes?|about|saved|""" +
                        """the|of|pathi\s+notes?\s+irukka|notes?\s+la|irukka)\b""",
                    RegexOption.IGNORE_CASE,
                ),
                "",
            )
            cleaned.replace(Regex("""\s+"""), " ").trim().ifEmpty { null }
        } else null

        return acceptQuery(
            domain = "note",
            intent = intent,
            dateStart = dateRange?.start?.toString(),
            dateEnd = dateRange?.end?.toString(),
            filters = JSONObject(),
            limit = null,
            queryText = searchText,
        )
    }

    private fun extractPersonFromQuery(text: String): String? {
        val cleaned = text.removePrefix("ask:").trim()
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

    private val AMOUNT_RE = Regex(
        """(?:rs\.?\s*|₹\s*|usd\s+|\$\s*)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:/-|k|l|crore|crores|lakh|lakhs|thousand|rs\.?|rupees?|₹)?""",
        RegexOption.IGNORE_CASE,
    )

    private val NUMBER_RE = Regex("""\d+(?:\.\d+)?""")

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
        val asLong = v.toLong()
        return if (kotlin.math.abs(v - asLong) < 1e-9) asLong else v
    }

    private fun stripCurrencyWords(s: String): String {
        return s
            .replace(CURRENCY_WORD_RE, " ")
            .replace(Regex("""\s+"""), " ")
            .trim()
            .trim(',', ':', ';', '.', '-')
            .trim()
    }

    private val CURRENCY_WORD_RE = Regex(
        """(?<!\w)(rs\.?|rupees?|₹|inr|usd)(?!\w)""",
        RegexOption.IGNORE_CASE,
    )

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

    private fun weekend(today: LocalDate): DateRange {
        val sat = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SATURDAY))
        return DateRange(sat, sat.plusDays(1))
    }

    private val DAYS_OF_WEEK = mapOf(
        "monday" to DayOfWeek.MONDAY, "tuesday" to DayOfWeek.TUESDAY,
        "wednesday" to DayOfWeek.WEDNESDAY, "thursday" to DayOfWeek.THURSDAY,
        "friday" to DayOfWeek.FRIDAY, "saturday" to DayOfWeek.SATURDAY,
        "sunday" to DayOfWeek.SUNDAY,
    )

    private fun nextDay(today: LocalDate, dow: DayOfWeek): DateRange {
        var delta = ((dow.value - today.dayOfWeek.value) + 7) % 7
        if (delta == 0) delta = 7
        val d = today.plusDays(delta.toLong())
        return DateRange(d, d)
    }

    private fun lastDay(today: LocalDate, dow: DayOfWeek): DateRange {
        var delta = ((today.dayOfWeek.value - dow.value) + 7) % 7
        if (delta == 0) delta = 7
        val d = today.minusDays(delta.toLong())
        return DateRange(d, d)
    }

    private fun nDaysAgo(today: LocalDate, n: Int) = today.minusDays(n.toLong()).let { DateRange(it, it) }

    private val MONTH_NAMES_LIST = listOf(
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    )
    private val MONTH_NAMES_ABBR = listOf(
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    )
    private val ORDINALS = mapOf(
        "first" to 1, "1st" to 1,
        "second" to 2, "2nd" to 2,
        "third" to 3, "3rd" to 3,
        "fourth" to 4, "4th" to 4,
        "last" to 5,
    )

    private fun monthWeek(month: Int, ordinal: Int, year: Int): DateRange {
        return if (ordinal == 5) {
            val start = LocalDate.of(year, month, 22)
            val end = start.with(TemporalAdjusters.lastDayOfMonth())
            DateRange(start, end)
        } else {
            val start = LocalDate.of(year, month, 1 + (ordinal - 1) * 7)
            val end = LocalDate.of(year, month, ordinal * 7)
            DateRange(start, end)
        }
    }

    private fun firstHalfMonth(month: Int, year: Int) = DateRange(
        LocalDate.of(year, month, 1),
        LocalDate.of(year, month, 15),
    )

    private fun secondHalfMonth(month: Int, year: Int): DateRange {
        val start = LocalDate.of(year, month, 16)
        val end = start.with(TemporalAdjusters.lastDayOfMonth())
        return DateRange(start, end)
    }

    private fun resolveMonth(name: String): Int? {
        val lower = name.lowercase()
        return MONTH_NAMES_LIST.indexOfFirst { it.startsWith(lower) || lower.startsWith(it.take(3)) }
            .let { if (it < 0) null else it + 1 }
    }

    private val DATE_RANGE_PHRASES: List<Pair<String, (LocalDate) -> DateRange>> = listOf(
        "last month"    to { t -> lastMonth(t) },
        "this month"    to { t -> thisMonth(t) },
        "current month" to { t -> thisMonth(t) },
        "last week"     to { t -> lastWeek(t) },
        "this week"     to { t -> thisWeek(t) },
        "current week"  to { t -> thisWeek(t) },
        "last year"     to { t -> lastYear(t) },
        "this year"     to { t -> thisYear(t) },
        "current year"  to { t -> thisYear(t) },
        "today"         to { t -> thisDay(t) },
        "yesterday"     to { t -> thisDay(t.minusDays(1)) },
        "tomorrow"      to { t -> thisDay(t.plusDays(1)) },
    )

    private fun extractDateRangePhrase(lower: String, today: LocalDate): Pair<DateRange?, String> {
        for ((phrase, fn) in DATE_RANGE_PHRASES) {
            val idx = lower.indexOf(phrase)
            if (idx >= 0) {
                val residual = (lower.substring(0, idx) + lower.substring(idx + phrase.length)).trim()
                return fn(today) to residual
            }
        }

        Regex("""\b(weekend|wknd)\b""").find(lower)?.let { m ->
            val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
            return weekend(today) to residual
        }

        Regex("""\b(next|last|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b""").find(lower)?.let { m ->
            val kind = m.groupValues[1]
            val day = DAYS_OF_WEEK.getValue(m.groupValues[2])
            val rng = when (kind) {
                "next" -> nextDay(today, day)
                "last" -> lastDay(today, day)
                else -> {
                    var delta = ((day.value - today.dayOfWeek.value) + 7) % 7
                    val d = today.plusDays(delta.toLong())
                    DateRange(d, d)
                }
            }
            val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
            return rng to residual
        }

        Regex("""\b(\d+|two|three|four|five|six|seven)\s+days?\s+ago\b""").find(lower)?.let { m ->
            val token = m.groupValues[1]
            val n = token.toIntOrNull() ?: when (token) {
                "two" -> 2; "three" -> 3; "four" -> 4; "five" -> 5; "six" -> 6; "seven" -> 7; else -> 1
            }
            val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
            return nDaysAgo(today, n) to residual
        }

        val monthsPattern = (MONTH_NAMES_LIST + MONTH_NAMES_ABBR).joinToString("|")
        val ordinalsPattern = ORDINALS.keys.joinToString("|")
        Regex("""\b($monthsPattern)\s+($ordinalsPattern)\s+week\b""").find(lower)?.let { m ->
            val month = resolveMonth(m.groupValues[1])
            if (month != null) {
                val ord = ORDINALS.getValue(m.groupValues[2])
                val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
                return monthWeek(month, ord, today.year) to residual
            }
        }

        Regex("""\b($ordinalsPattern)\s+week\b""").find(lower)?.let { m ->
            val ord = ORDINALS.getValue(m.groupValues[1])
            val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
            return monthWeek(today.monthValue, ord, today.year) to residual
        }

        Regex("""\b(first|second)\s+half\s+of\s+($monthsPattern)\b""").find(lower)?.let { m ->
            val month = resolveMonth(m.groupValues[2])
            if (month != null) {
                val rng = if (m.groupValues[1] == "first") firstHalfMonth(month, today.year)
                else secondHalfMonth(month, today.year)
                val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
                return rng to residual
            }
        }

        Regex("""\b($monthsPattern)\b""").find(lower)?.let { m ->
            val month = resolveMonth(m.groupValues[1])
            if (month != null) {
                val start = LocalDate.of(today.year, month, 1)
                val end = start.with(TemporalAdjusters.lastDayOfMonth())
                val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
                return DateRange(start, end) to residual
            }
        }

        Regex("""\bweek\s+(?:close|end|ending)\b""").find(lower)?.let { m ->
            val sunday = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
            val residual = (lower.substring(0, m.range.first) + lower.substring(m.range.last + 1)).trim()
            return DateRange(sunday, sunday) to residual
        }

        return null to lower
    }

    private fun stripTrailingDate(text: String, today: LocalDate): Pair<String, LocalDate?> {
        val lower = text.lowercase()
        val phrases = listOf(
            "yesterday" to today.minusDays(1),
            "tomorrow" to today.plusDays(1),
            "today" to today,
        )
        for ((phrase, date) in phrases) {
            if (lower.endsWith(phrase)) {
                val stripped = text.substring(0, text.length - phrase.length).trim().trimEnd(',', ';')
                return stripped to date
            }
        }
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

    private val TRAILING_ABSOLUTE_DATE_RE = Regex(
        """\s+(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|july|aug|sep|sept|oct|nov|dec)\w*(?:\s+\d{4})?|""" +
            """(?:jan|feb|mar|apr|may|jun|jul|july|aug|sep|sept|oct|nov|dec)\w*\s+\d{1,2}(?:\s+\d{4})?|""" +
            """\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?)\s*$""",
        RegexOption.IGNORE_CASE,
    )

    private fun parseAbsoluteDate(raw: String, today: LocalDate): LocalDate? {
        val t = raw.trim().lowercase()
        Regex("""^(\d{1,2})[-/](\d{1,2})(?:[-/](\d{2,4}))?$""").matchEntire(t)?.let { m ->
            val d = m.groupValues[1].toInt()
            val mo = m.groupValues[2].toInt()
            val y = m.groupValues[3].ifEmpty { today.year.toString() }
                .let { if (it.length == 2) "20$it" else it }.toInt()
            return runCatching { LocalDate.of(y, mo, d) }.getOrNull()
        }
        for (fmt in MONTH_NAME_FORMATTERS) {
            runCatching { LocalDate.parse(t, fmt) }.getOrNull()?.let { return it }
            runCatching {
                LocalDate.parse("$t ${today.year}", DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH))
            }.getOrNull()?.let { return it }
            runCatching {
                LocalDate.parse("$t ${today.year}", DateTimeFormatter.ofPattern("MMM d yyyy", Locale.ENGLISH))
            }.getOrNull()?.let { return it }
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

    private fun splitMulti(body: String): List<String> {
        return body.split(Regex("""\s*(?:,|;|\||&|\sand\s)\s*"""))
            .map { it.trim() }
            .filter { it.isNotEmpty() }
    }

    private fun splitMultiNl(body: String): List<String> {
        return body.split(Regex("""\s*(?:\r?\n|,|;|\||&|\sand\s)\s*"""))
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
            put("domain", "note")
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

    private fun String.titleish(): String =
        if (isEmpty()) this
        else this[0].uppercaseChar() + substring(1).lowercase()
}
