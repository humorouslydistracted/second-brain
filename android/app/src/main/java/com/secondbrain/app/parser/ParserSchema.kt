package com.secondbrain.app.parser

import org.json.JSONArray
import org.json.JSONObject

/**
 * Frozen v2 parser schema (mirrors `generate_large_schema_frozen_dataset_v2.py`
 * and `second_brain_finetuned_parser.py::validate_parser_payload`).
 *
 * Two payload families:
 *   - WRITE  → task = "parse_write",  lane = expense | buy | todo | weight | ledger
 *   - QUERY  → task = "parse_query" or "parse_followup_query",
 *              domain = note | expense | buy | todo | weight | ledger
 *
 * All payloads carry `disposition`. Accept rows fill intent + filters + dates;
 * clarify rows fill clarify_reason + clarify_options; reject rows fill
 * reason_code.
 */

object ParserConst {
    val WRITE_LANES        = setOf("expense", "buy", "todo", "weight", "ledger")
    val WRITE_DISPOSITIONS = setOf("accept", "confirm", "reject")
    val QUERY_DOMAINS      = setOf("note", "expense", "buy", "todo", "weight", "ledger")
    val QUERY_DISPOSITIONS = setOf("accept", "clarify", "reject")
    val LEDGER_ACTIONS     = setOf("add_debt", "add_credit", "repay_debt", "collect_credit", "settle")

    /**
     * Per-domain canonical intents. We intentionally accept a SUPERSET of
     * what the v2 dataset emits so the model can hallucinate slightly without
     * crashing the dispatch path. Any "extra" intent here just falls through
     * to a sensible default in the runner.
     */
    val QUERY_INTENTS: Map<String, Set<String>> = mapOf(
        "note"    to setOf("search", "list", "latest", "recent", "latest_bucket", "day_bucket"),
        "expense" to setOf("total", "list", "compare"),
        "buy"     to setOf("list", "search"),
        "todo"    to setOf("list", "search", "history"),
        "weight"  to setOf("latest", "history", "trend", "change", "latest_all"),
        "ledger"  to setOf("balance", "list", "summary", "search"),
    )

    /** Filter shapes per v2. Missing keys are coerced to null in the runner. */
    val QUERY_FILTER_KEYS: Map<String, Set<String>> = mapOf(
        "note"    to emptySet(),
        "expense" to setOf("group", "description_text", "exclude_group", "exclude_description_text"),
        "buy"     to setOf("status", "item_text"),
        "todo"    to setOf("status", "text_match"),
        "weight"  to setOf("person_text"),
        "ledger"  to setOf("person_text", "perspective", "status"),
    )
}

/**
 * Parsed payload — sealed hierarchy so the orchestrator switches on type
 * once and the rest of the code is type-safe.
 */
sealed interface ParserPayload {
    val raw: JSONObject

    data class Write(
        override val raw: JSONObject,
        val lane: String,
        val disposition: String,         // accept | confirm | reject
        val reasonCode: String?,
        val records: List<JSONObject>,
    ) : ParserPayload

    data class Query(
        override val raw: JSONObject,
        val isFollowup: Boolean,
        val domain: String,
        val disposition: String,         // accept | clarify | reject
        val intent: String?,
        val dateStart: String?,
        val dateEnd: String?,
        val compareDateStart: String?,
        val compareDateEnd: String?,
        val filters: JSONObject?,        // null when disposition != accept
        val limit: Int?,
        val queryText: String?,
        val reasonCode: String?,
        val clarifyReason: String?,
        val clarifyOptions: List<String>,
    ) : ParserPayload
}

/** Validator result. */
sealed interface ParseResult {
    data class Ok(val payload: ParserPayload) : ParseResult
    data class Fail(val reason: String, val rawText: String) : ParseResult
}

object ParserValidator {

    fun parse(rawJsonText: String): ParseResult {
        val obj = try { JSONObject(rawJsonText) }
        catch (t: Throwable) { return ParseResult.Fail("not valid JSON: ${t.message}", rawJsonText) }
        return parse(obj, rawJsonText)
    }

    fun parse(obj: JSONObject, rawJsonText: String = obj.toString()): ParseResult {
        return when (val task = obj.optString("task")) {
            "parse_write"           -> parseWrite(obj, rawJsonText)
            "parse_query",
            "parse_followup_query"  -> parseQuery(obj, rawJsonText, task == "parse_followup_query")
            else -> ParseResult.Fail("unsupported task: $task", rawJsonText)
        }
    }

    private fun parseWrite(o: JSONObject, raw: String): ParseResult {
        val lane = o.optString("lane")
        if (lane !in ParserConst.WRITE_LANES) return ParseResult.Fail("unsupported lane: $lane", raw)
        val disp = o.optString("disposition")
        if (disp !in ParserConst.WRITE_DISPOSITIONS) return ParseResult.Fail("unsupported disposition: $disp", raw)
        val records = mutableListOf<JSONObject>()
        if (!o.isNull("records")) {
            val arr = o.optJSONArray("records") ?: JSONArray()
            for (i in 0 until arr.length()) {
                val r = arr.optJSONObject(i) ?: return ParseResult.Fail("record $i not an object", raw)
                records += r
            }
        }
        if (disp == "reject" && records.isNotEmpty())
            return ParseResult.Fail("reject must have empty records", raw)
        if (disp != "reject" && records.isEmpty())
            return ParseResult.Fail("$disp must have at least one record", raw)
        return ParseResult.Ok(
            ParserPayload.Write(
                raw = o,
                lane = lane,
                disposition = disp,
                reasonCode = o.optString("reason_code", null),
                records = records,
            )
        )
    }

    private fun parseQuery(o: JSONObject, raw: String, followup: Boolean): ParseResult {
        val domain = o.optString("domain")
        if (domain !in ParserConst.QUERY_DOMAINS) return ParseResult.Fail("unsupported domain: $domain", raw)
        val disp = o.optString("disposition", "accept").ifEmpty { "accept" }
        if (disp !in ParserConst.QUERY_DISPOSITIONS) return ParseResult.Fail("unsupported query disposition: $disp", raw)

        val opts = mutableListOf<String>()
        if (!o.isNull("clarify_options")) {
            val arr = o.optJSONArray("clarify_options")
            if (arr != null) for (i in 0 until arr.length()) opts += arr.optString(i)
        }

        val intent = if (disp == "accept") o.optString("intent", null) else null
        if (disp == "accept") {
            val allowed = ParserConst.QUERY_INTENTS[domain] ?: emptySet()
            if (intent.isNullOrEmpty() || intent !in allowed) {
                // Lenient: don't hard-fail. The orchestrator will fall back to
                // a domain-default intent and log a warning to request_log.
                // This prevents a model hallucination from killing the user
                // request entirely.
            }
        }

        return ParseResult.Ok(
            ParserPayload.Query(
                raw = o,
                isFollowup = followup,
                domain = domain,
                disposition = disp,
                intent = intent,
                dateStart = o.optString("date_start", null).orNullIfEmpty(),
                dateEnd = o.optString("date_end", null).orNullIfEmpty(),
                compareDateStart = o.optString("compare_date_start", null).orNullIfEmpty(),
                compareDateEnd = o.optString("compare_date_end", null).orNullIfEmpty(),
                filters = o.optJSONObject("filters"),
                limit = if (o.has("limit") && !o.isNull("limit")) o.optInt("limit") else null,
                queryText = o.optString("query_text", null).orNullIfEmpty(),
                reasonCode = o.optString("reason_code", null).orNullIfEmpty(),
                clarifyReason = o.optString("clarify_reason", null).orNullIfEmpty(),
                clarifyOptions = opts,
            )
        )
    }
}

private fun String?.orNullIfEmpty(): String? = if (this.isNullOrEmpty() || this == "null") null else this
