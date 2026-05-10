package com.secondbrain.app.parser

import com.secondbrain.app.ChatTemplate
import com.secondbrain.app.LlamaCpp

/**
 * Wraps the LLM call with prompt construction + schema validation.
 *
 * The orchestrator only ever calls `parse()`. Returns the chat-template
 * prompt (for logging), the raw model output (for logging), and the
 * structured payload (for dispatch).
 */
data class ParseAttempt(
    val prompt: String,
    val rawOutput: String,
    val result: ParseResult,
    val promptMs: Long,
    val generateMs: Long,
    /** JNI-side per-stage timings + tok/s + abort flag, as JSON. */
    val nativeStats: String,
)

object ParserService {

    /**
     * @param maxTokens cap on generated tokens. 512 default (2026-05-09).
     *   The dataset now trains buy/expense lists up to 12 items. Each
     *   canonical record JSON (`{"item_text":"X","quantity_text":null,
     *   "unit_text":null,"date":"YYYY-MM-DD"}`) is ~25 tokens, so a
     *   12-item buy output is ~300 tokens of records + ~30-token wrapper
     *   ≈ 330 tokens. Keeping 200 here would silently truncate every
     *   long-list output the new fine-tune is trained for, producing
     *   broken JSON that falls through to note-save (same failure mode
     *   as build-#27 dogfood log #78). 512 leaves headroom for 15-item
     *   lists with longer item names without letting the model ramble.
     *   Previous history: 200 default chosen after build #21 dogfooding
     *   when records-per-row was capped at 3.
     */
    suspend fun parse(userInput: String, maxTokens: Int = 512): ParseAttempt {
        val tStart = System.nanoTime()
        val prompt = ChatTemplate.buildPrompt(userInput)
        val tAfterPrompt = System.nanoTime()
        val raw = LlamaCpp.generate(prompt, maxTokens = maxTokens)
        val tAfterGen = System.nanoTime()
        val nativeStats = runCatching { LlamaCpp.getLastStats() }.getOrDefault("{}")
        val cleaned = stripChatTrailers(raw).trim()
        // Try parsing the JSON ourselves so we can hand it to the
        // ShapeAdapter before validation. If it isn't valid JSON we fall
        // through to ParserValidator.parse(text) for its detailed error.
        val coercedJson = runCatching {
            val obj = org.json.JSONObject(cleaned)
            // Pass userInput so the adapter can disambiguate things the
            // model gets wrong on its own — e.g. ledger direction from
            // "owes me" vs "i owe", or dropping bogus person filters
            // from who/all-style queries.
            ShapeAdapter.coerce(obj, userInput)
        }.getOrNull() ?: runCatching {
            // Repair attempt: model sometimes emits multi-record bodies
            // as a flat sequence of objects with a stray ] but missing [.
            // Example from build #24:
            //   "data":{"text":"a","date":"X"},{"text":"b","date":"Y"}]}
            // We rewrite to "data":[{...},{...}]} and retry parse.
            val repaired = repairMultiRecordData(cleaned) ?: return@runCatching null
            val obj = org.json.JSONObject(repaired)
            com.secondbrain.app.diag.EventLog.info(
                com.secondbrain.app.diag.EventLog.Category.ORCHESTRATOR,
                "ParserService: repaired malformed multi-record data:{} into data:[]",
                null,
            )
            ShapeAdapter.coerce(obj, userInput)
        }.getOrNull()
        val result = if (coercedJson != null) {
            ParserValidator.parse(coercedJson, coercedJson.toString())
        } else {
            ParserValidator.parse(cleaned)
        }
        return ParseAttempt(
            prompt = prompt,
            rawOutput = raw,
            result = result,
            promptMs = (tAfterPrompt - tStart) / 1_000_000,
            generateMs = (tAfterGen - tAfterPrompt) / 1_000_000,
            nativeStats = nativeStats,
        )
    }

    /**
     * Strip wrappers/trailers the model may emit around the JSON payload:
     *   - leading `<think>...</think>` (Qwen3 thinking mode)
     *   - trailing `<|im_end|>` / `<|endoftext|>` / stray `<|im_start|>`
     *   - leading whitespace + accidental code fences
     *
     * Robust enough to handle a partially-warm model that still wraps
     * its output even with the enable_thinking=False priming.
     */
    private fun stripChatTrailers(text: String): String {
        var t = text
        // 1. Drop any <think>...</think> block (greedy across newlines).
        //    Multiple think blocks are rare but we'd remove all of them.
        t = THINK_BLOCK_RE.replace(t, "")
        // 2. Drop chat-template tail tokens.
        for (marker in listOf("<|im_end|>", "<|endoftext|>", "<|im_start|>")) {
            val idx = t.indexOf(marker)
            if (idx >= 0) t = t.substring(0, idx)
        }
        // 3. Strip any leading code-fence the model decided to add.
        t = t.trimStart()
        if (t.startsWith("```")) {
            val firstNl = t.indexOf('\n')
            if (firstNl >= 0) t = t.substring(firstNl + 1)
            val fenceEnd = t.lastIndexOf("```")
            if (fenceEnd >= 0) t = t.substring(0, fenceEnd)
        }
        return t.trim()
    }

    private val THINK_BLOCK_RE = Regex("<think>[\\s\\S]*?</think>", RegexOption.IGNORE_CASE)

    /**
     * Try to repair a known model failure mode: multi-record write
     * where the array brackets are missing. Pattern looks like:
     *
     *     ..."data":{"text":"a"...},{"text":"b"...}]}
     *                                            ^^^ stray closing
     *
     * Convert to:
     *
     *     ..."data":[{"text":"a"...},{"text":"b"...}]}
     *
     * Returns null if no plausible repair found (caller falls back to
     * "save as plain note").
     */
    private fun repairMultiRecordData(text: String): String? {
        // Quick sniff: must contain `"data":{` followed somewhere by
        // `},{` and end with `]}`.
        if (!text.contains("\"data\":{") && !text.contains("\"data\": {")) return null
        if (!text.contains("},{") && !text.contains("}, {")) return null
        if (!text.trimEnd().endsWith("]}")) return null
        // Replace the FIRST `"data":{` (or with whitespace) with `"data":[{`.
        val regex = Regex("\"data\"\\s*:\\s*\\{")
        val repaired = regex.replaceFirst(text, "\"data\":[{")
        // The trailing `]}` from the model already closes the array
        // and the outer object. Sanity-check by counting braces.
        return repaired
    }
}
