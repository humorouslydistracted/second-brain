"""Tests for user_routing_memory: schema, lookup, upsert, prune, orchestrator wiring."""
from __future__ import annotations

import os
import shutil
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _stub_fallthrough(text: str) -> dict[str, object]:
    return {"kind": "fallthrough_stub", "response_text": "stub"}


class _StubLLM:
    def status(self):
        return {"backend": "stub"}

    def route_input(self, text, today, persons, perf=None):
        return {"unknown": True}

    def plan_query(self, text, today, persons, perf=None):
        return {"action": "unknown"}

    def parse_note(self, text, today):
        return {"type": "unknown"}

    def summarize_rag(self, q, d, h, perf=None):
        return ("stub", "stub")


class _StubEmbed:
    def status(self):
        return {"available": False, "load_error": "stub"}

    def encode(self, text, perf=None, label="embedding"):
        return None


def main() -> int:
    src_db = os.path.join(APP_DIR, "second_brain.db")
    if not os.path.exists(src_db):
        print(f"FAIL: {src_db} not found.")
        return 1

    tmp_dir = os.path.join(APP_DIR, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_db = os.path.join(tmp_dir, "test_routing_memory.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    shutil.copy2(src_db, tmp_db)

    os.environ["SECOND_BRAIN_DB_PATH"] = tmp_db

    for mod in ("second_brain_core", "second_brain_orchestrator"):
        if mod in sys.modules:
            del sys.modules[mod]

    from second_brain_core import (
        db_connection,
        ensure_runtime_schema,
        lookup_routing_memory,
        prune_routing_memory,
        upsert_routing_memory,
    )
    from second_brain_orchestrator import handle, normalize_input

    ensure_runtime_schema(tmp_db)
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        marker = "PASS" if ok else "FAIL"
        line = f"[{marker}] {label}"
        if detail:
            line += f" — {detail}"
        print(line)
        if not ok:
            failures.append(label)

    with db_connection(tmp_db) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(user_routing_memory)")}
    expected = {"id", "input_pattern", "resolved_tool", "resolved_args_json", "hit_count", "last_used", "created_at"}
    check("schema columns present", expected.issubset(cols), f"got {sorted(cols)}")

    with db_connection(tmp_db) as conn:
        miss = lookup_routing_memory(conn, "anything new")
        conn.commit()
    check("empty table -> miss", miss is None)

    with db_connection(tmp_db) as conn:
        upsert_routing_memory(conn, "march month", "query_expense", {"month": "2026-03"})
        conn.commit()

    with db_connection(tmp_db) as conn:
        hit = lookup_routing_memory(conn, "march month")
        conn.commit()
    check(
        "upsert + lookup roundtrip",
        hit is not None and hit["tool"] == "query_expense" and hit["args"]["month"] == "2026-03",
        f"got {hit}",
    )

    with db_connection(tmp_db) as conn:
        h2 = lookup_routing_memory(conn, "march month")
        conn.commit()
    check("hit_count bumps on subsequent lookup", h2 is not None and h2["hit_count"] >= 3, f"got {h2}")

    with db_connection(tmp_db) as conn:
        upsert_routing_memory(conn, "march month", "query_expense", {"month": "2026-04"})
        conn.commit()

    with db_connection(tmp_db) as conn:
        h3 = lookup_routing_memory(conn, "march month")
        conn.commit()
    check(
        "upsert overwrites args on duplicate key",
        h3 is not None and h3["args"]["month"] == "2026-04",
        f"got {h3}",
    )

    norm_a = normalize_input("  Show ME  the   List ")
    norm_b = normalize_input("show me the list")
    check("normalize_input collapses + lowercases", norm_a == norm_b == "show me the list", f"a={norm_a!r} b={norm_b!r}")

    with db_connection(tmp_db) as conn:
        conn.execute("DELETE FROM user_routing_memory")
        conn.execute(
            """
            INSERT INTO user_routing_memory
                (input_pattern, resolved_tool, resolved_args_json, last_used)
            VALUES (?, ?, ?, datetime('now', '-100 days'))
            """,
            ("old entry", "query_expense", "{}"),
        )
        conn.execute(
            """
            INSERT INTO user_routing_memory
                (input_pattern, resolved_tool, resolved_args_json, last_used)
            VALUES (?, ?, ?, datetime('now', '-30 days'))
            """,
            ("recent entry", "query_expense", "{}"),
        )
        conn.commit()

    with db_connection(tmp_db) as conn:
        pruned = prune_routing_memory(conn, days=90)
        conn.commit()
    check("prune drops only old entries", pruned == 1, f"pruned={pruned}")

    with db_connection(tmp_db) as conn:
        rows = conn.execute("SELECT input_pattern FROM user_routing_memory").fetchall()
        remaining = {r["input_pattern"] for r in rows}
    check("recent entry survived prune", remaining == {"recent entry"}, f"remaining={remaining}")

    with db_connection(tmp_db) as conn:
        upsert_routing_memory(conn, "march month", "query_expense", {"month": "2026-03"})
        conn.commit()

    llm = _StubLLM()
    embed = _StubEmbed()

    response = handle("march month", db_path=tmp_db, llm_service=llm, embedding_service=embed)
    check(
        "orchestrator returns tier=memo for memoized input",
        response.tier == "memo" and (response.parsed or {}).get("rule") == "user_routing_memory",
        f"got tier={response.tier} rule={(response.parsed or {}).get('rule')}",
    )

    response2 = handle(
        "totally unseen input xyz",
        db_path=tmp_db,
        llm_service=llm,
        embedding_service=embed,
    )
    check(
        "non-memoized non-tier0 input continues past memo (tier1 or tier1_legacy)",
        response2.tier in {"tier1", "tier1_legacy"},
        f"got tier={response2.tier}",
    )

    print()
    print("-" * 70)
    if failures:
        print(f"FAILED: {len(failures)}")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("PASSED: all routing-memory checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
