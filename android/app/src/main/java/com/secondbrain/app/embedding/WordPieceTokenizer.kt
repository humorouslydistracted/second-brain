package com.secondbrain.app.embedding

import org.json.JSONObject
import java.io.File
import java.text.Normalizer

/**
 * Minimal pure-Kotlin BERT WordPiece tokenizer.
 *
 * Reads HF's `vocab.txt` (one token per line, line number is token id) and
 * a small companion JSON written by the export notebook with config flags
 * (do_lower_case, special tokens, max_seq_len).
 *
 * Steps (matches the canonical BertTokenizer):
 *   1. Unicode NFD normalization → strip combining marks (accent fold).
 *      Skipped if `do_lower_case=false`. With `do_lower_case=true` we
 *      additionally lowercase.
 *   2. Whitespace + punctuation pre-tokenization.
 *   3. Greedy longest-match WordPiece against `vocab`. Unknown tokens map
 *      to `unk_token_id`.
 *   4. Wrap with `[CLS]` ... `[SEP]`. Pad to `maxSeqLen` with `[PAD]`.
 *
 * NOT implemented (deliberate scope cuts):
 *   - never_split / wholeword / chinese-char rules — fine for v1 English.
 *   - subword_prefix override — assumes the standard "##" prefix.
 *   - true Unicode-category punctuation classifier — uses a fast ASCII +
 *     `Char.isLetterOrDigit` check that matches BERT for common inputs.
 */
class WordPieceTokenizer private constructor(
    private val vocab: Map<String, Int>,
    private val doLowerCase: Boolean,
    val maxSeqLen: Int,
    val unkTokenId: Int,
    val padTokenId: Int,
    val clsTokenId: Int,
    val sepTokenId: Int,
) {

    /** Tokenize and return id sequence + attention mask, both length [maxSeqLen]. */
    fun encode(text: String): Encoded {
        val tokens = mutableListOf<Int>()
        tokens += clsTokenId
        for (word in basicTokenize(text)) {
            tokens += wordpiece(word)
            if (tokens.size >= maxSeqLen - 1) break
        }
        if (tokens.size > maxSeqLen - 1) {
            // truncate, keep room for [SEP]
            while (tokens.size > maxSeqLen - 1) tokens.removeAt(tokens.size - 1)
        }
        tokens += sepTokenId

        val ids = LongArray(maxSeqLen)
        val mask = LongArray(maxSeqLen)
        for (i in 0 until maxSeqLen) {
            if (i < tokens.size) {
                ids[i] = tokens[i].toLong(); mask[i] = 1L
            } else {
                ids[i] = padTokenId.toLong(); mask[i] = 0L
            }
        }
        return Encoded(ids, mask)
    }

    private fun basicTokenize(text: String): List<String> {
        val normalized = if (doLowerCase) {
            stripAccents(text.lowercase())
        } else {
            text
        }
        val out = mutableListOf<String>()
        val sb = StringBuilder()
        for (ch in normalized) {
            when {
                ch.isWhitespace() -> {
                    if (sb.isNotEmpty()) { out += sb.toString(); sb.clear() }
                }
                isPunctuation(ch) -> {
                    if (sb.isNotEmpty()) { out += sb.toString(); sb.clear() }
                    out += ch.toString()
                }
                else -> sb.append(ch)
            }
        }
        if (sb.isNotEmpty()) out += sb.toString()
        return out
    }

    private fun wordpiece(word: String): List<Int> {
        if (word.length > 100) return listOf(unkTokenId)  // BERT default
        val out = mutableListOf<Int>()
        var start = 0
        val n = word.length
        while (start < n) {
            var end = n
            var match: String? = null
            while (end > start) {
                val piece = if (start == 0) word.substring(start, end)
                            else "##" + word.substring(start, end)
                if (piece in vocab) { match = piece; break }
                end -= 1
            }
            if (match == null) {
                // No piece matched at this position → whole word is UNK
                return listOf(unkTokenId)
            }
            out += vocab[match]!!
            start = end
        }
        return out
    }

    private fun stripAccents(s: String): String {
        val nfd = Normalizer.normalize(s, Normalizer.Form.NFD)
        val sb = StringBuilder(nfd.length)
        for (ch in nfd) {
            val type = Character.getType(ch).toByte()
            if (type != Character.NON_SPACING_MARK) sb.append(ch)
        }
        return sb.toString()
    }

    private fun isPunctuation(ch: Char): Boolean {
        val code = ch.code
        // BERT's punctuation rule: ASCII punct + any Unicode "P" class char.
        return (code in 33..47) || (code in 58..64) ||
               (code in 91..96) || (code in 123..126) ||
               Character.getType(ch).let { t ->
                   t == Character.CONNECTOR_PUNCTUATION.toInt() ||
                   t == Character.DASH_PUNCTUATION.toInt() ||
                   t == Character.START_PUNCTUATION.toInt() ||
                   t == Character.END_PUNCTUATION.toInt() ||
                   t == Character.INITIAL_QUOTE_PUNCTUATION.toInt() ||
                   t == Character.FINAL_QUOTE_PUNCTUATION.toInt() ||
                   t == Character.OTHER_PUNCTUATION.toInt()
               }
    }

    data class Encoded(val ids: LongArray, val attentionMask: LongArray)

    companion object {
        fun load(vocabFile: File, configFile: File): WordPieceTokenizer {
            val cfg = JSONObject(configFile.readText())
            val doLower = cfg.optBoolean("do_lower_case", true)
            val maxSeqLen = cfg.optInt("max_seq_len", 256)

            val vocab = HashMap<String, Int>(40_000)
            vocabFile.useLines { lines ->
                lines.forEachIndexed { i, line -> vocab[line] = i }
            }
            return WordPieceTokenizer(
                vocab = vocab,
                doLowerCase = doLower,
                maxSeqLen = maxSeqLen,
                unkTokenId = vocab[cfg.optString("unk_token", "[UNK]")] ?: 100,
                padTokenId = vocab[cfg.optString("pad_token", "[PAD]")] ?: 0,
                clsTokenId = vocab[cfg.optString("cls_token", "[CLS]")] ?: 101,
                sepTokenId = vocab[cfg.optString("sep_token", "[SEP]")] ?: 102,
            )
        }
    }
}
