package com.secondbrain.app.orchestrator

/**
 * The 7 chip tags. Locked decisions (round 3):
 *   - chips: ask, expense, ledger, weight, todo, note, buy
 *   - combo rule: ask + at most one domain tag, OR a single write tag, OR none
 *   - chip-wins: when user types `<tag>:` and the chip is already active,
 *     the typed text is stripped from the input and a toast 'Tag already
 *     active: <tag>:' is shown
 *   - auto-convert: when user types a recognized `<tag>:` prefix and that
 *     chip is NOT active, the literal is stripped and the chip becomes active
 */
enum class Tag(val raw: String) {
    // Order is significant — drives the chip-row left-to-right ordering on
    // Home. Locked sequence per 2026-05-08 user feedback.
    ASK("ask"),
    TODO("todo"),
    EXPENSE("expense"),
    NOTE("note"),
    WEIGHT("weight"),
    BUY("buy"),
    LEDGER("ledger");

    val tagWithColon: String get() = "$raw:"
    val isWrite: Boolean get() = this != ASK
    val isQuery: Boolean get() = this == ASK

    companion object {
        fun fromRaw(raw: String): Tag? =
            entries.firstOrNull { it.raw.equals(raw, ignoreCase = true) }
    }
}

/** Result of normalizing typed input + active chips into a single submittable form. */
data class TaggedInput(
    /** Final body sent to the parser, e.g. `ask: latest buy list` */
    val composed: String,
    /** Ordered set of chips that are active after normalization. */
    val activeChips: Set<Tag>,
    /** Toasts the UI should show as a result of normalization. */
    val notices: List<String>,
)

object Tags {

    /**
     * The single canonical normalizer. Pure function — no side effects, no
     * platform deps, fully unit-testable.
     *
     * Implements every locked rule:
     *   1. If the typed text starts with a recognized `<tag>:`:
     *        - if that chip is already active → strip the literal,
     *          notice("Tag already active: <tag>:")
     *        - else → strip the literal, add the chip
     *      Repeat until no recognized prefix remains.
     *   2. Combo rule: prune the chip set down to a legal combination
     *      (ask + at most one domain, OR exactly one write tag, OR empty).
     *   3. Compose final string by prepending active chips in canonical
     *      order: `ask: <domain>: <body>` / `<write>: <body>` / `<body>`.
     */
    fun normalize(typed: String, activeChips: Set<Tag>): TaggedInput {
        val notices = mutableListOf<String>()
        var body = typed.trimStart()
        val chips = activeChips.toMutableSet()

        // ---- Step 1: peel off recognized `<tag>:` prefixes ----
        while (true) {
            val (tag, rest) = peelTagPrefix(body) ?: break
            body = rest
            if (tag in chips) {
                notices += "Tag already active: ${tag.tagWithColon}"
            } else {
                chips += tag
            }
        }

        // ---- Step 2: combo rule ----
        val (legalChips, comboNotices) = enforceCombo(chips)
        notices += comboNotices

        // ---- Step 3: compose final string ----
        val composed = buildString {
            if (Tag.ASK in legalChips) append("ask: ")
            legalChips.firstOrNull { it != Tag.ASK }?.let { append("${it.raw}: ") }
            append(body.trimStart())
        }.trimEnd()

        return TaggedInput(composed = composed, activeChips = legalChips, notices = notices)
    }

    /**
     * Inverse of normalize for live typing: returns the canonical "what
     * should the input field show now?" given the new keystrokes and
     * currently active chips. Used by the Compose TextField onValueChange.
     */
    fun reactToTyping(rawText: String, activeChips: Set<Tag>): TypingReaction {
        val notices = mutableListOf<String>()
        var text = rawText
        val chips = activeChips.toMutableSet()

        while (true) {
            val (tag, rest) = peelTagPrefix(text.trimStart()) ?: break
            text = rest
            if (tag in chips) {
                notices += "Tag already active: ${tag.tagWithColon}"
            } else {
                chips += tag
                notices += "Tag added: ${tag.tagWithColon}"
            }
        }
        // Ensure combo rule even during typing.
        val (legalChips, comboNotices) = enforceCombo(chips)
        notices += comboNotices

        return TypingReaction(text, legalChips, notices)
    }

    /**
     * What happens when the user taps a chip. If a write chip is tapped
     * while another write chip is active, the old one is replaced (write
     * tags are mutually exclusive).
     */
    fun toggleChip(tap: Tag, current: Set<Tag>): Set<Tag> {
        if (tap in current) return current - tap
        val next = current.toMutableSet()
        if (tap.isWrite) {
            // Mutually exclusive among writes
            next.removeAll { it.isWrite }
        }
        next += tap
        return enforceCombo(next).first
    }

    // ---------------------------------------------------------------

    private val PREFIX_RE = Regex("""^\s*([A-Za-z]+)\s*:\s*""")

    private fun peelTagPrefix(text: String): Pair<Tag, String>? {
        val m = PREFIX_RE.find(text) ?: return null
        val tag = Tag.fromRaw(m.groupValues[1]) ?: return null
        return tag to text.removeRange(0, m.range.last + 1)
    }

    /** Locked rule: ask + at most one domain, OR exactly one write, OR empty. */
    private fun enforceCombo(chips: Set<Tag>): Pair<Set<Tag>, List<String>> {
        val notices = mutableListOf<String>()
        val hasAsk = Tag.ASK in chips
        val writes = chips.filter { it.isWrite }
        return when {
            hasAsk -> {
                // Ask + at most one domain (the most-recently added wins;
                // since Set has no order we keep the first encountered).
                val keep = writes.firstOrNull()
                val pruned = mutableSetOf<Tag>(Tag.ASK)
                if (keep != null) pruned += keep
                if (writes.size > 1) {
                    val dropped = writes.drop(1).joinToString(", ") { it.tagWithColon }
                    notices += "Removed extra tag(s): $dropped (only ask + one domain allowed)"
                }
                pruned to notices
            }
            writes.size > 1 -> {
                val keep = writes.first()
                val dropped = writes.drop(1).joinToString(", ") { it.tagWithColon }
                notices += "Removed extra tag(s): $dropped (only one write tag allowed)"
                setOf(keep) to notices
            }
            else -> chips to notices
        }
    }
}

data class TypingReaction(
    val newText: String,
    val activeChips: Set<Tag>,
    val notices: List<String>,
)
