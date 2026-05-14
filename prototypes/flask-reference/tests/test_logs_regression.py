"""Regression test against the actual failure cases from logs.txt.

Each input that misrouted in the user's dogfooding session is exercised
through the new orchestrator stack and the resulting DB state + response
are asserted. Uses a temp DB copy + mock LLM (driven by the dict in
second_brain_core) + a deterministic toy embedding so it doesn't depend
on real Qwen / sentence-transformers being loaded.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))


class _MockLLM:
    """Pure-Python mock that mirrors LLMService.route_input's mock-mode path."""

    def __init__(self):
        self._load_error = None

    def status(self):
        return {"backend": "mock"}

    def route_input(self, text, today, persons, perf=None):
        from second_brain_core import MOCK_ROUTE_RESPONSES

        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if normalized in MOCK_ROUTE_RESPONSES:
            return dict(MOCK_ROUTE_RESPONSES[normalized])
        for key, value in MOCK_ROUTE_RESPONSES.items():
            if key in normalized:
                return dict(value)
        return {"unknown": True}

    def plan_query(self, text, today, persons, perf=None):
        from second_brain_core import MOCK_PLAN_RESPONSES

        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        if normalized in MOCK_PLAN_RESPONSES:
            return dict(MOCK_PLAN_RESPONSES[normalized])
        for key, value in MOCK_PLAN_RESPONSES.items():
            if key in normalized:
                return dict(value)
        return {"action": "unknown"}

    def parse_note(self, text, today):
        return {"type": "unknown"}

    def summarize_rag(self, q, d, hits, perf=None):
        if not hits:
            return ("No notes found.", "mock")
        best = hits[0]
        label = best.get("source") or best.get("domain") or "note"
        return (f"From {label}: {best['content']}", "mock")

    def synthesize_notes(self, q, hits, perf=None):
        if not hits:
            return ("The notes do not contain enough to answer.", "mock")
        return ((hits[0].get("content") or "")[:200], "mock")


class _FakeEmbed:
    """Deterministic 26-dim letter-frequency vector — enough for cosine
    similarity to actually order matching notes. Avoids the
    sentence-transformers download in tests."""

    def status(self):
        return {"available": True, "load_error": None}

    def encode(self, text, perf=None, label="embedding"):
        if not text:
            return None
        vec = [0.0] * 26
        for ch in text.lower():
            if "a" <= ch <= "z":
                vec[ord(ch) - ord("a")] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return None
        return [v / norm for v in vec]


def main() -> int:
    src_db = os.path.join(APP_DIR, "second_brain.db")
    if not os.path.exists(src_db):
        print(f"FAIL: {src_db} not found.")
        return 1

    tmp_dir = os.path.join(APP_DIR, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_db = os.path.join(tmp_dir, "test_logs_regression.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    shutil.copy2(src_db, tmp_db)

    os.environ["SECOND_BRAIN_DB_PATH"] = tmp_db
    for mod in ("second_brain_core", "second_brain_orchestrator"):
        if mod in sys.modules:
            del sys.modules[mod]

    from second_brain_core import db_connection, ensure_runtime_schema
    from second_brain_orchestrator import handle

    ensure_runtime_schema(tmp_db)
    llm = _MockLLM()
    embed = _FakeEmbed()

    failures: list[str] = []

    def run(text):
        return handle(text, db_path=tmp_db, llm_service=llm, embedding_service=embed)

    def check(label, ok, detail=""):
        marker = "PASS" if ok else "FAIL"
        line = f"[{marker}] {label}"
        if detail:
            line += f" -- {detail}"
        # Windows cp1252 console can't render Rs. or em-dash; sanitize.
        line = line.replace("₹", "Rs.").replace("—", "--").replace("→", "->")
        print(line)
        if not ok:
            failures.append(label)

    # ------------------------------------------------------------------
    # logs.txt failure 1: 'jeevi weight 65.3' silently returned old reading
    # ------------------------------------------------------------------
    response = run("jeevi weight 65.3")
    with db_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT weight FROM weights WHERE person='jeevi' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    check(
        "jeevi weight 65.3 inserts new weight row at 65.3",
        bool(row) and abs(float(row["weight"]) - 65.3) < 1e-6,
        f"latest_weight={row['weight'] if row else None}, response={response.response_text!r}",
    )
    check("jeevi weight 65.3 routed via Tier 0", response.tier == "tier0")

    # ------------------------------------------------------------------
    # logs.txt failure 2: 'TODO: ...' (with colon) was treated as query
    # ------------------------------------------------------------------
    response = run("TODO: update maddy to explore datascience in iit chennai")
    with db_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT content FROM todos ORDER BY id DESC LIMIT 1"
        ).fetchone()
    check(
        "TODO: prefix creates todo row",
        bool(row) and "datascience" in row["content"].lower(),
        f"latest_todo={row['content'] if row else None}",
    )
    check("TODO: prefix routed via Tier 0", response.tier == "tier0")

    response = run("todo: buy milk\n- call amit")
    with db_connection(tmp_db) as conn:
        rows = conn.execute(
            "SELECT content FROM todos ORDER BY id DESC LIMIT 2"
        ).fetchall()
    todo_items = [row["content"].lower() for row in rows]
    check(
        "todo: multiline input splits into multiple todos",
        len(rows) == 2 and "call amit" in todo_items[0] and "buy milk" in todo_items[1],
        f"latest_todos={todo_items}",
    )

    # 'todo update maddy ...' (no colon) — also Tier 0 via verb branch
    response = run("todo update maddy with mcp progress")
    check(
        "todo <verb> ... (no colon) also writes a todo (Tier 0)",
        response.tier == "tier0" and response.kind == "write",
        f"tier={response.tier} kind={response.kind}",
    )

    response = run("note: avoid nightshade veggies")
    with db_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT content, structured_type FROM notes ORDER BY id DESC LIMIT 1"
        ).fetchone()
    check(
        "note: prefix saves a plain note body",
        bool(row)
        and row["content"] == "avoid nightshade veggies"
        and row["structured_type"] in {None, "note"},
        f"latest_note={dict(row) if row else None}",
    )

    # ------------------------------------------------------------------
    # logs.txt failure 3: 'clear maddy ledger' was creating a todo
    # ------------------------------------------------------------------
    response = run("clear maddy ledger")
    check(
        "clear maddy ledger triggers settlement clarification",
        response.kind == "clarification" and response.tier == "tier0",
        f"kind={response.kind} tier={response.tier}",
    )

    # ------------------------------------------------------------------
    # logs.txt failure 4: free-form note saved but never embedded
    # ------------------------------------------------------------------
    note_text = "vivekananda died of exhaustion not meditation, important lesson on self-care"
    response = run(note_text)
    with db_connection(tmp_db) as conn:
        emb_row = conn.execute(
            "SELECT id, source, domain FROM embeddings WHERE source LIKE 'note:%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    check(
        "free-form note auto-embeds at write time",
        emb_row is not None,
        f"latest_embedding={dict(emb_row) if emb_row else None}",
    )

    # ------------------------------------------------------------------
    # logs.txt failure 5: 'vivekananda notes' returned 'no investment notes'
    # ------------------------------------------------------------------
    response = run("vivekananda notes")
    check(
        "vivekananda notes finds the saved note (cross-domain search)",
        "vivekananda" in response.response_text.lower(),
        f"response={response.response_text!r}",
    )
    check(
        "timing metadata is attached to note query responses",
        bool(response.timings_ms) and "orchestrator.total_ms" in response.timings_ms and "query_notes.total_ms" in response.timings_ms,
        f"timings={response.timings_ms}",
    )

    with db_connection(tmp_db) as conn:
        before_plain_notes = conn.execute(
            "SELECT COUNT(*) c FROM notes WHERE structured_type='note'"
        ).fetchone()["c"]
        before_total_notes = conn.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]
    response = run("did i ever save a note on vivekananda")
    with db_connection(tmp_db) as conn:
        after_plain_notes = conn.execute(
            "SELECT COUNT(*) c FROM notes WHERE structured_type='note'"
        ).fetchone()["c"]
        after_total_notes = conn.execute("SELECT COUNT(*) c FROM notes").fetchone()["c"]
    check(
        "did i ever save a note on vivekananda stays a query and does not create a plain note",
        response.kind == "query"
        and before_plain_notes == after_plain_notes
        and before_total_notes == after_total_notes,
        f"kind={response.kind} plain_notes={before_plain_notes}->{after_plain_notes} total_notes={before_total_notes}->{after_total_notes}",
    )

    response = run("show notes about no such topic protocol")
    check(
        "weak note retrieval abstains instead of returning an unrelated note",
        response.kind == "query" and "no notes matched" in response.response_text.lower(),
        f"response={response.response_text!r}",
    )

    with db_connection(tmp_db) as conn:
        before_weight_count = conn.execute(
            "SELECT COUNT(*) c FROM weights WHERE person='jeevi'"
        ).fetchone()["c"]
    response = run("last 3 jeevi weight")
    with db_connection(tmp_db) as conn:
        after_weight_count = conn.execute(
            "SELECT COUNT(*) c FROM weights WHERE person='jeevi'"
        ).fetchone()["c"]
    check(
        "last 3 jeevi weight queries history without inserting a new weight",
        response.kind == "query"
        and before_weight_count == after_weight_count,
        f"kind={response.kind} weight_count={before_weight_count}->{after_weight_count}",
    )

    response = run("any mention of mcp in the notes")
    check(
        "any mention of mcp in the notes routes as a note query",
        response.kind == "query",
        f"kind={response.kind} response={response.response_text!r}",
    )

    # ------------------------------------------------------------------
    # logs.txt failure 6: 'list the expense one by one' returned a SUM
    # ------------------------------------------------------------------
    response = run("list the expense one by one")
    check(
        "list expense one by one returns a row list (not just sum)",
        response.kind == "query"
        and "expense list" in response.response_text.lower(),
        f"response={response.response_text[:200]!r}",
    )

    with db_connection(tmp_db) as conn:
        before_count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    response = run("last 4 expenses")
    with db_connection(tmp_db) as conn:
        after_count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    check(
        "last 4 expenses stays a query and does not log a new expense",
        response.kind == "query" and before_count == after_count,
        f"kind={response.kind} expense_count={before_count}->{after_count} response={response.response_text!r}",
    )

    with db_connection(tmp_db) as conn:
        before_count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    response = run("food 300, water bottle 20, tea & snacks 30")
    with db_connection(tmp_db) as conn:
        after_count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
        rows = conn.execute(
            "SELECT description, amount FROM expenses ORDER BY id DESC LIMIT 3"
        ).fetchall()
    latest_expenses = {(row["description"].lower(), float(row["amount"])) for row in rows}
    check(
        "comma-separated numeric input writes multiple expenses",
        response.kind == "write"
        and after_count - before_count == 3
        and ("food", 300.0) in latest_expenses
        and ("water bottle", 20.0) in latest_expenses
        and ("tea & snacks", 30.0) in latest_expenses,
        f"expense_count={before_count}->{after_count} latest={latest_expenses}",
    )

    # ------------------------------------------------------------------
    # logs.txt failure 7: 'who all owe me money' was saved as a note
    # ------------------------------------------------------------------
    response = run("who all owe me money")
    check(
        "who all owe me money returns query result, not a note save",
        response.kind == "query",
        f"kind={response.kind} response={response.response_text!r}",
    )

    with db_connection(tmp_db) as conn:
        before_plain_notes = conn.execute(
            "SELECT COUNT(*) c FROM notes WHERE structured_type='note'"
        ).fetchone()["c"]
    response = run("ledger history for maddy")
    with db_connection(tmp_db) as conn:
        after_plain_notes = conn.execute(
            "SELECT COUNT(*) c FROM notes WHERE structured_type='note'"
        ).fetchone()["c"]
    check(
        "ledger history for maddy stays read-only and does not create a plain note",
        response.kind == "query" and before_plain_notes == after_plain_notes,
        f"kind={response.kind} plain_notes={before_plain_notes}->{after_plain_notes} response={response.response_text!r}",
    )

    # ------------------------------------------------------------------
    # logs.txt failure 8: 'march month' was saved as a note
    # ------------------------------------------------------------------
    response = run("march month")
    check(
        "march month asks for clarification (not a silent note save)",
        response.kind == "clarification",
        f"kind={response.kind}",
    )

    # ------------------------------------------------------------------
    # Bonus: 'monthly expense' should query, not write
    # ------------------------------------------------------------------
    response = run("monthly expense")
    check(
        "monthly expense returns expense query",
        response.kind == "query" and "spend" in response.response_text.lower(),
        f"response={response.response_text!r}",
    )

    # ------------------------------------------------------------------
    # Bonus: clarify resolution writes to user_routing_memory
    # ------------------------------------------------------------------
    # Run something that triggers clarify (mock has 'march month'),
    # then reply with '1' and verify routing memory grows.
    run("march month")
    pre_count = 0
    with db_connection(tmp_db) as conn:
        pre = conn.execute("SELECT COUNT(*) c FROM user_routing_memory WHERE input_pattern='march month'").fetchone()
        pre_count = pre["c"] if pre else 0
    response = run("1")
    with db_connection(tmp_db) as conn:
        post = conn.execute(
            "SELECT resolved_tool, resolved_args_json FROM user_routing_memory WHERE input_pattern='march month'"
        ).fetchone()
    check(
        "clarify resolution writes to user_routing_memory",
        post is not None and post["resolved_tool"] == "query_expense",
        f"pre_count={pre_count} post={dict(post) if post else None}",
    )

    # Subsequent identical input hits memo path
    response = run("march month")
    check(
        "memoized input now routes via tier=memo (no LLM)",
        response.tier == "memo",
        f"tier={response.tier}",
    )

    print()
    print("-" * 70)
    if failures:
        print(f"FAILED: {len(failures)} of checks above")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("PASSED: all regression checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
