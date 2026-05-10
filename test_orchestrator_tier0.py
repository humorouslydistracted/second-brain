"""Smoke test for orchestrator Tier 0 grammar.

Each input from logs.txt is exercised through the orchestrator with a stub
LLM (always returns "unknown") + a stub embedding service. Tier 0 hits are
asserted to route directly; non-Tier-0 inputs go through Tier 1 → legacy
rules → heuristic clarify. Uses a temp DB copy to avoid polluting prod.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Any

APP_DIR = os.path.dirname(os.path.abspath(__file__))


class _StubLLM:
    def status(self) -> dict[str, Any]:
        return {"backend": "stub"}

    def route_input(self, text: str, today: str, persons: list[str], perf=None) -> dict[str, Any]:
        return {"unknown": True}

    def plan_query(self, text: str, today: str, persons: list[str], perf=None) -> dict[str, Any]:
        return {"action": "unknown"}

    def parse_note(self, text: str, today: str) -> dict[str, Any]:
        return {"type": "unknown"}

    def summarize_rag(self, q: str, d: str, h: list[dict[str, Any]], perf=None):
        return ("stub", "stub")

    def synthesize_notes(self, q: str, h: list[dict[str, Any]], perf=None):
        if not h:
            return ("The notes do not contain enough to answer.", "stub")
        return ((h[0].get("content") or "stub")[:200], "stub")


class _ExplodingRouteLLM(_StubLLM):
    def route_input(self, text: str, today: str, persons: list[str], perf=None) -> dict[str, Any]:
        raise AssertionError(f"LLM route_input should not be called for fast-path query: {text!r}")

    def plan_query(self, text: str, today: str, persons: list[str], perf=None) -> dict[str, Any]:
        raise AssertionError(f"LLM plan_query should not be called for fast-path query: {text!r}")


class _StubEmbed:
    def status(self) -> dict[str, Any]:
        return {"available": False, "load_error": "stub"}

    def encode(self, text: str, perf=None, label: str = "embedding"):
        return None


def main() -> int:
    src_db = os.path.join(APP_DIR, "second_brain.db")
    if not os.path.exists(src_db):
        print(f"FAIL: {src_db} not found.")
        return 1

    tmp_dir = os.path.join(APP_DIR, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_db = os.path.join(tmp_dir, "test_orchestrator_tier0.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    shutil.copy2(src_db, tmp_db)

    os.environ["SECOND_BRAIN_DB_PATH"] = tmp_db

    for mod in ("second_brain_core", "second_brain_orchestrator"):
        if mod in sys.modules:
            del sys.modules[mod]

    from second_brain_core import ensure_runtime_schema
    from second_brain_orchestrator import handle

    ensure_runtime_schema(tmp_db)
    llm = _StubLLM()
    embed = _StubEmbed()

    # (input, expected_tier_prefix, expected_rule)
    cases: list[tuple[str, str, str]] = [
        # Tier 0 — must catch these even with stub LLM
        ("jeevi weight 65.3", "tier0", "weight_write"),
        ("jeevi 65.3", "tier0", "weight_write"),
        ("murugan weight 65.3", "tier0", "weight_write"),
        ("prani weight 11", "tier0", "weight_write"),
        ("note: avoid nightshade veggies", "tier0", "explicit_note"),
        ("TODO: update maddy to explore about datascience in iit chennai", "tier0", "explicit_todo"),
        ("todo: update maddy to explore about datascience", "tier0", "explicit_todo"),
        ("todo update maddy to explore about datascience", "tier0", "explicit_todo"),
        ("clear maddy ledger", "tier0", "settlement_phrase"),
        ("settled maddy amount", "tier0", "settlement_phrase"),
        ("maddy settled amount", "tier0", "settlement_phrase"),
        ("ADD_PERSON: ravi", "tier0", "person_command"),
        ("REMOVE_PERSON: ravi", "tier0", "person_command"),
        ("remind me to call ravi tomorrow", "tier0", "explicit_todo"),
        # Legacy rules — pre-orchestrator behavior preserved by Tier 1.5
        ("petrol 500", "tier1_legacy", "legacy_write_expense"),
        ("Maddy balance", "fastpath", "fast_query_plan"),
        ("monthly expense", "fastpath", "fast_query_plan"),
        ("ravi gave me 5k this month", "tier1_legacy", "legacy_write_ledger"),
        ("food 300, water bottle 20, tea & snacks 30", "tier1_legacy", "legacy_write_multi"),
        ("show todo list", "fastpath", "fast_query_plan"),
        ("show me todo list", "fastpath", "fast_query_plan"),
        ("todo list pls", "fastpath", "fast_query_plan"),
        ("last 3 jeevi weight", "fastpath", "fast_query_plan"),
        # Edge: weight rejection (unknown name / >150) falls through; legacy
        # write parser (now run first for number-bearing inputs) treats them
        # as expenses, which is what the spec wants.
        ("biscuit 20", "tier1_legacy", "legacy_write_expense"),
        ("milk 60", "tier1_legacy", "legacy_write_expense"),
        ("jeevi 200", "tier1_legacy", "legacy_write_expense"),
        # No-number inputs go to query plan first; cross-domain override
        # ensures 'vivekananda notes' searches saved general-domain notes
        # instead of being misrouted to 'investment' by the substring of
        # 'anand' inside 'vivekananda'.
        ("march month", "tier1_legacy", "legacy_write_note"),
        ("vivekananda notes", "fastpath", "fast_query_plan"),
        ("any mention of mcp in the notes", "fastpath", "fast_query_plan"),
        ("show me last 5 notes", "fastpath", "fast_query_plan"),
        # Stub LLM can't catch this; legacy plan also doesn't match —
        # heuristic clarify is the safety-net (real Qwen + mock dict
        # both have an entry for this phrase).
        ("who all owe me money", "fastpath", "fast_query_plan"),
    ]

    failures: list[str] = []
    for raw, expected_tier, expected_rule in cases:
        response = handle(raw, db_path=tmp_db, llm_service=llm, embedding_service=embed)
        actual_tier = response.tier
        actual_rule = (response.parsed or {}).get("rule", "<no_rule>")
        ok = (actual_tier == expected_tier) and (actual_rule == expected_rule)
        marker = "PASS" if ok else "FAIL"
        print(
            f"[{marker}] {raw!r:60s} "
            f"tier={actual_tier} rule={actual_rule} kind={response.kind}"
        )
        if not ok:
            failures.append(
                f"  {raw!r}: expected tier={expected_tier} rule={expected_rule}, "
                f"got tier={actual_tier} rule={actual_rule}"
            )

    fast_llm = _ExplodingRouteLLM()
    for raw in (
        "vivekananda notes",
        "show me last 5 notes",
        "last 3 jeevi weight",
        "monthly expense",
        "who all owe me money",
    ):
        try:
            response = handle(raw, db_path=tmp_db, llm_service=fast_llm, embedding_service=embed)
            ok = response.tier == "fastpath"
            marker = "PASS" if ok else "FAIL"
            print(f"[{marker}] {raw!r:60s} fastpath bypasses LLM route_input")
            if not ok:
                failures.append(
                    f"  {raw!r}: expected fastpath LLM bypass, got tier={response.tier} rule={(response.parsed or {}).get('rule')}"
                )
        except AssertionError as exc:
            print(f"[FAIL] {raw!r:60s} fastpath bypasses LLM route_input")
            failures.append(f"  {raw!r}: {exc}")

    print()
    print("-" * 70)
    if failures:
        print(f"FAILED: {len(failures)} of {len(cases)}")
        for line in failures:
            print(line)
        return 1
    print(f"PASSED: {len(cases)}/{len(cases)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
