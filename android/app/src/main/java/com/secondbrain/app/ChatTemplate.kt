package com.secondbrain.app

import java.time.LocalDate

/**
 * Builds the prompt string that the fine-tuned Qwen3-1.7B parser expects.
 *
 * Mirrors `second_brain_finetuned_parser.py` exactly:
 *   - Same SYSTEM_PROMPT text
 *   - Same `Today: <YYYY-MM-DD>` injection (the v2 training contract)
 *   - Qwen3 chat template with `enable_thinking=False`
 *
 * If you change anything here, change it in the Python wrapper too — they
 * must stay byte-identical or eval results stop being comparable.
 */
object ChatTemplate {

    private const val SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""

    fun buildPrompt(userInput: String, today: LocalDate = LocalDate.now()): String {
        val systemFull = "$SYSTEM_PROMPT\n\nToday: $today"
        // Qwen3 chat template, enable_thinking=False form. Without the
        // empty <think></think> priming, Qwen3 wraps every reply in
        // a thinking block by default, which breaks our JSON parser.
        // Python's `tokenizer.apply_chat_template(..., enable_thinking=False)`
        // emits exactly this priming; we replicate it byte-for-byte
        // here so the v1 fine-tuned adapter sees the same context it
        // saw during training.
        return buildString {
            append("<|im_start|>system\n")
            append(systemFull)
            append("<|im_end|>\n")
            append("<|im_start|>user\n")
            append(userInput)
            append("<|im_end|>\n")
            append("<|im_start|>assistant\n")
            append("<think>\n\n</think>\n\n")
        }
    }
}
