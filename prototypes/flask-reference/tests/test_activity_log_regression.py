"""Regression suite covering every misroute in the user's activity log.

Builds a small temp DB seeded with the same shape of data the live app has,
runs each failing input through the orchestrator, and asserts the new
LLM-planner path now returns the right `kind` / `tier` / response_text shape.

Uses an in-process mock LLM (driven by `MOCK_PLAN_RESPONSES`) so no GGUF or
sentence-transformers download is required.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
from typing import Any


APP_DIR = os.path.dirname(os.path.abspath(__file__))


class _MockLLM:
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
        return (f"From {best.get('source') or 'note'}: {best.get('content','')}", "mock")

    def synthesize_notes(self, q, hits, perf=None):
        if not hits:
            return ("The notes do not contain enough to answer.", "mock")
        return ((hits[0].get("content") or "")[:200], "mock")


class _FakeEmbed:
    """26-dim letter-frequency vector — enough for cosine to order matches."""

    def status(self):
        return {"available": True, "load_error": None}

    def encode(self, text, perf=None, label="embedding"):
        if not text:
            return None
        vec = [0.0] * 26
        for ch in text.lower():
            if "a" <= ch <= "z":
                vec[ord(ch) - 97] += 1.0
        # normalize
        n = sum(v * v for v in vec) ** 0.5
        if n == 0:
            return None
        return [v / n for v in vec]


def _build_temp_db() -> str:
    fd, path = tempfile.mkstemp(prefix="actlog_", suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        DROP TABLE IF EXISTS expenses;
        DROP TABLE IF EXISTS ledger;
        DROP TABLE IF EXISTS weights;
        DROP TABLE IF EXISTS todos;
        DROP TABLE IF EXISTS persons;
        DROP TABLE IF EXISTS notes;
        DROP TABLE IF EXISTS embeddings;
        DROP TABLE IF EXISTS pending_actions;
        DROP TABLE IF EXISTS user_routing_memory;
        DROP TABLE IF EXISTS activity_log;
        DROP VIEW IF EXISTS ledger_balance;

        CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT UNIQUE, created_at TEXT);
        CREATE TABLE notes (
          id INTEGER PRIMARY KEY,
          content TEXT NOT NULL,
          input_kind TEXT DEFAULT 'note',
          structured_type TEXT,
          note_domain TEXT,
          metadata_json TEXT,
          created_at TEXT,
          processed_at TEXT
        );
        CREATE TABLE expenses (
          id INTEGER PRIMARY KEY,
          amount REAL,
          description TEXT,
          date TEXT,
          month TEXT,
          raw_note TEXT,
          source_note_id INTEGER,
          created_at TEXT
        );
        CREATE TABLE ledger (
          id INTEGER PRIMARY KEY,
          person TEXT,
          amount REAL,
          direction TEXT,
          note TEXT,
          date TEXT,
          source_note_id INTEGER,
          created_at TEXT
        );
        CREATE VIEW ledger_balance AS
          SELECT person, SUM(CASE WHEN direction='gave' THEN amount ELSE -amount END) AS balance
          FROM ledger GROUP BY person;
        CREATE TABLE weights (
          id INTEGER PRIMARY KEY, person TEXT, weight REAL, date TEXT,
          note TEXT, source_note_id INTEGER, created_at TEXT);
        CREATE TABLE todos (
          id INTEGER PRIMARY KEY, content TEXT, status TEXT DEFAULT 'pending',
          date TEXT, source_note_id INTEGER, created_at TEXT);
        CREATE TABLE embeddings (
          id INTEGER PRIMARY KEY, domain TEXT, content TEXT, embedding BLOB,
          source TEXT, date TEXT, source_note_id INTEGER, created_at TEXT);

        INSERT INTO persons(name, created_at) VALUES
          ('jeevi', datetime('now')), ('prani', datetime('now')),
          ('murugan', datetime('now')), ('maddy', datetime('now')),
          ('ravi', datetime('now')), ('thenna', datetime('now'));

        INSERT INTO ledger(person, amount, direction, date, created_at) VALUES
          ('maddy', 7000, 'received', '2026-04-01', datetime('now')),
          ('maddy', 3000, 'gave',     '2026-04-15', datetime('now')),
          ('ravi',  10000,'received', '2026-04-05', datetime('now')),
          ('thenna',20000,'gave',     '2026-03-20', datetime('now'));

        INSERT INTO expenses(amount, description, date, month, created_at) VALUES
          (500,  'petrol',    '2026-04-15', '2026-04', '2026-04-15 09:00:00'),
          (300,  'milk',      '2026-05-01', '2026-05', '2026-05-01 09:00:00'),
          (1200, 'groceries', '2026-04-22', '2026-04', '2026-04-22 09:00:00'),
          (60,   'tea',       '2026-05-02', '2026-05', '2026-05-02 09:00:00'),
          (250,  'electricity','2026-05-03','2026-05', '2026-05-03 09:00:00');

        INSERT INTO weights(person, weight, date, created_at) VALUES
          ('jeevi',   60.1, '2026-04-24', datetime('now')),
          ('prani',   11.5, '2026-05-03', datetime('now')),
          ('murugan', 72.0, '2026-05-01', datetime('now'));

        INSERT INTO todos(content, status, created_at) VALUES
          ('renew license', 'pending', datetime('now')),
          ('haircut', 'done', datetime('now'));

        INSERT INTO notes(content, input_kind, structured_type, note_domain, created_at) VALUES
          ('vivekananda died of exhaustion not meditation', 'note', 'note', 'general', datetime('now')),
          ('avoid nightshade veggies', 'note', 'note', 'general', datetime('now')),
          ('peter lynch favours low pe stock', 'note', 'note', 'general', datetime('now')),
          ('cipla needs more study before making a decision', 'note', 'note', 'general', datetime('now')),
          ('film theory note on montage, framing, and gaze', 'note', 'note', 'general', datetime('now')),
          ('philosophy note on stoic focus and practical limits', 'note', 'note', 'general', datetime('now'));
        """
    )
    conn.commit()
    conn.close()
    return path


CASES: list[dict[str, Any]] = [
    {
        "input": "latest note",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "philosophy",  # most recently inserted
    },
    {
        "input": "last note",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "philosophy",
    },
    {
        "input": "vivekananda note",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "vivekananda",
    },
    {
        "input": "weight status",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "jeevi",  # latest weight per person includes jeevi
    },
    {
        "input": "expense status",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "2026-05",
    },
    {
        "input": "all ledger",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "thenna",
    },
    {
        "input": "maddy ledger",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "maddy ledger entries",
    },
    {
        "input": "ravi ledger",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "ravi ledger entries",
    },
    {
        "input": "ledger history for maddy",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "maddy ledger entries",
    },
    {
        "input": "how much money i owe",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "ravi",  # we owe ravi 10000
    },
    {
        "input": "show all notes",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "vivekananda",  # recent notes include vivekananda
    },
    {
        "input": "show notes about cipla",
        "expect_kind": "query",
        "expect_tier": "fastpath",
        "expect_in_response": "cipla",
    },
    {
        "input": "did i ever save a note on vivekananda",
        "expect_kind": "query",
        "expect_tier": "fastpath",
        "expect_in_response": "vivekananda",
    },
    {
        "input": "any mention of flim theory in the notes",
        "expect_kind": "query",
        "expect_tier": "fastpath",
        "expect_in_response": "film theory",
    },
    {
        "input": "show notes about nothingness protocol",
        "expect_kind": "query",
        "expect_tier": "fastpath",
        "expect_in_response": "No notes matched",
    },
    {
        "input": "last 3 expense",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "last 3 expenses",
    },
    {
        "input": "last 5 expense",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "last 5 expenses",
    },
    {
        "input": "last 4 expenses",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "last 4 expenses",
    },
    {
        "input": "last 3 bills",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "last 3 expenses",
    },
    # Sanity: the working cases should still work and NOT route through planner.
    {
        "input": "maddy balance",
        "expect_kind": "query",
        "expect_tier": "fastpath",
        "expect_in_response": "Maddy",
    },
    {
        "input": "this month expense",
        "expect_kind": "query",
        "expect_tier": "fastpath",
        "expect_in_response": "Total spend",
    },
    {
        "input": "prani weight 11.5",
        "expect_kind": "write",
        "expect_tier": "tier0",
        "expect_in_response": "Prani weight",
    },
    {
        "input": "note: is fundera park really good?",
        "expect_kind": "write",
        "expect_tier": "tier0",
        "expect_in_response": "saved",
    },
    {
        "input": "todo: go for biryani festival",
        "expect_kind": "write",
        "expect_tier": "tier0",
        "expect_in_response": "Todo added",
    },
    # Hardest: relative-date + exclusion.
    {
        "input": "expenses apart from petrol last month",
        "expect_kind": "query",
        "expect_tier": "planner",
        "expect_in_response": "groceries",  # last month had petrol+groceries
    },
]


def main() -> int:
    tmp_db = _build_temp_db()
    os.environ["SECOND_BRAIN_DB_PATH"] = tmp_db

    for mod in ("second_brain_core", "second_brain_orchestrator"):
        if mod in sys.modules:
            del sys.modules[mod]

    from second_brain_core import (
        db_connection,
        ensure_runtime_schema,
        store_note_embedding,
    )
    ensure_runtime_schema(tmp_db)

    from second_brain_orchestrator import handle

    llm = _MockLLM()
    embed = _FakeEmbed()

    # Seed embeddings for the seeded notes so semantic search has corpus.
    seed_conn = db_connection(tmp_db)
    try:
        rows = seed_conn.execute(
            "SELECT id, content, note_domain FROM notes WHERE structured_type='note'"
        ).fetchall()
        for row in rows:
            store_note_embedding(
                seed_conn, embed, int(row["id"]),
                row["content"], row["note_domain"] or "general",
            )
        seed_conn.commit()
    finally:
        seed_conn.close()

    passed = 0
    failed = 0
    for case in CASES:
        try:
            response = handle(
                case["input"],
                db_path=tmp_db,
                llm_service=llm,
                embedding_service=embed,
            )
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {case['input']!r:50s} raised {type(exc).__name__}: {exc}")
            continue

        ok_kind = response.kind == case["expect_kind"]
        ok_tier = response.tier == case["expect_tier"]
        ok_text = case["expect_in_response"].lower() in response.response_text.lower()
        if ok_kind and ok_tier and ok_text:
            passed += 1
            print(f"[PASS] {case['input']!r:50s} tier={response.tier} kind={response.kind}")
        else:
            failed += 1
            print(
                f"[FAIL] {case['input']!r:50s}\n"
                f"       expected kind={case['expect_kind']} tier={case['expect_tier']} "
                f"contains={case['expect_in_response']!r}\n"
                f"       got      kind={response.kind} tier={response.tier}\n"
                f"       response={response.response_text[:200]!r}"
            )

    try:
        os.unlink(tmp_db)
    except OSError:
        pass

    print(f"\n{passed}/{passed + failed} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
