from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import threading
from array import array
from contextlib import contextmanager
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.environ.get(
    "SECOND_BRAIN_DB_PATH",
    os.path.join(APP_DIR, "second_brain.db"),
)


def _default_qwen_gguf_path() -> str:
    override = os.environ.get("SECOND_BRAIN_QWEN_GGUF")
    if override:
        return override

    candidates = [
        os.path.join(APP_DIR, "models", "Qwen3-4B-Q4_K_M.gguf"),
        os.path.join(APP_DIR, "models", "qwen2.5-4b-instruct-q4_k_m.gguf"),
        os.path.join(APP_DIR, "models", "qwen2.5-3b-instruct-q4_k_m.gguf"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


DEFAULT_QWEN_GGUF_PATH = _default_qwen_gguf_path()
DEFAULT_QWEN_TRANSFORMERS_MODEL = os.environ.get(
    "SECOND_BRAIN_QWEN_TRANSFORMERS_MODEL",
    "Qwen/Qwen2.5-4B-Instruct",
)
DEFAULT_EMBEDDING_MODEL = os.environ.get(
    "SECOND_BRAIN_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

GAVE_KEYWORDS = r"\b(gave|give|given|lent|sent|advanced)\b"
RECEIVED_KEYWORDS = r"\b(got|received|returned|paid back)\b"
PERSON_CMD_RE = re.compile(
    r"^(ADD_PERSON|REMOVE_PERSON|MODIFY_PERSON)\s*:\s*(.+)$", re.IGNORECASE
)
QUERY_LEADS = (
    "show ",
    "list ",
    "what ",
    "who ",
    "how ",
    "did ",
    "do ",
    "does ",
    "is ",
    "are ",
    "was ",
    "were ",
    "can ",
    "could ",
    "would ",
    "should ",
    "when ",
    "where ",
    "why ",
    "which ",
    "tell ",
    "find ",
    "search ",
)
TODO_LEADS = (
    "todo:",
    "task:",
    "remind me",
)
WEIGHT_PERSONS = {"jeevi", "prani", "murugan"}
MONTH_MAP = {
    "january": "2026-01",
    "february": "2026-02",
    "march": "2026-03",
    "april": "2026-04",
    "may": "2026-05",
    "jan": "2026-01",
    "feb": "2026-02",
    "mar": "2026-03",
    "apr": "2026-04",
}
EXPENSE_LIKE_KEYWORDS = [
    "petrol",
    "diesel",
    "medicine",
    "medplus",
    "pampers",
    "electricity",
    "broadband",
    "biryani",
    "tea",
    "rice",
    "mutton",
    "food",
    "groceries",
    "repair",
]
SETTLEMENT_SIGNALS = [
    "gave back the amount",
    "gave the amount back",
    "paid back the amount",
    "paid the amount back",
    "returned the amount",
    "settled the amount",
    "settled it",
    "cleared the amount",
]
TODO_START_VERBS = {
    "call",
    "buy",
    "pay",
    "send",
    "update",
    "book",
    "renew",
    "finish",
    "complete",
    "check",
    "remind",
    "pick",
    "message",
    "schedule",
    "visit",
}
NOTE_QUERY_STOPWORDS = {
    "a",
    "about",
    "all",
    "and",
    "any",
    "did",
    "do",
    "ever",
    "find",
    "for",
    "from",
    "i",
    "in",
    "info",
    "last",
    "latest",
    "mention",
    "mentions",
    "mentioned",
    "most",
    "my",
    "note",
    "notes",
    "of",
    "on",
    "our",
    "recent",
    "recently",
    "save",
    "saved",
    "search",
    "show",
    "that",
    "the",
    "what",
    "which",
}
QWEN_ROUTE_PROMPT = """You are an intent router for a personal note-taking app. Read the user input and pick exactly ONE of: a tool call, a clarification, or unknown. Return JSON only — no prose, no markdown.

User input: "{text}"
Today's date: {today}
Known people: {persons}

Available tools:
- add_expense(amount: number, description: string) — log a new expense
- add_ledger(person: string, amount: number, direction: "gave"|"received") — log money loan
- add_weight(person: string, weight: number, note: string?) — log a weight reading
- add_todo(content: string) — log a reminder/task
- add_note(content: string, domain?: "general"|"investment"|"health") — save free-form text for later semantic search
- query_ledger(query_type: "balance"|"who_owes"|"you_owe", person?: string)
- query_expense(month?: "YYYY-MM"|"current"|null, description_like?: string, list_mode?: bool) — list_mode=true when user asks for "list", "one by one", "individually"
- query_todos(status: "pending"|"done")
- query_weight(person: string, limit: int)
- query_notes(query: string, domain?: string, recent?: bool, limit?: int) — semantic search of saved notes; set recent=true with no query for "show recent notes"
- manage_person(operation: "ADD_PERSON"|"REMOVE_PERSON"|"MODIFY_PERSON", name?, old_name?, new_name?)
- prepare_settlement() — user wants to settle a debt without specifying who
- clarify_with_user(question, options) — ambiguous; ask user
- unknown — fall through to heuristic clarify menu

Return ONE of:
{{"tool": "<name>", "args": {{...}}, "confidence": 0.0-1.0}}
{{"clarify": true, "question": "...", "options": [{{"label": "...", "tool": "...", "args": {{...}}}}]}}
{{"unknown": true}}

Use confidence >=0.7 when you are sure; <0.7 means clarify is safer.

Examples:
Input: "petrol 500" -> {{"tool": "add_expense", "args": {{"amount": 500, "description": "petrol"}}, "confidence": 0.95}}
Input: "Maddy balance" -> {{"tool": "query_ledger", "args": {{"query_type": "balance", "person": "maddy"}}, "confidence": 0.95}}
Input: "this month expense" -> {{"tool": "query_expense", "args": {{"month": "current"}}, "confidence": 0.9}}
Input: "list the expense one by one" -> {{"tool": "query_expense", "args": {{"month": "current", "list_mode": true}}, "confidence": 0.9}}
Input: "vivekananda notes" -> {{"tool": "query_notes", "args": {{"query": "vivekananda"}}, "confidence": 0.9}}
Input: "march month" -> {{"clarify": true, "question": "What about March?", "options": [{{"label": "Show March 2026 expenses", "tool": "query_expense", "args": {{"month": "2026-03"}}}}, {{"label": "Save as a note", "tool": "add_note", "args": {{"content": "march month"}}}}]}}

Now route:"""

MOCK_ROUTE_RESPONSES: dict[str, dict[str, Any]] = {
    # Failure cases from logs.txt that the mock must handle deterministically.
    "march month": {
        "clarify": True,
        "question": "What about March?",
        "options": [
            {"label": "Show March 2026 expenses", "tool": "query_expense", "args": {"month": "2026-03"}},
            {"label": "Save 'march month' as a note", "tool": "add_note", "args": {"content": "march month"}},
        ],
    },
    "who all owe me money": {"tool": "query_ledger", "args": {"query_type": "who_owes"}, "confidence": 0.95},
    "who all owe me money and how much. list individually": {"tool": "query_ledger", "args": {"query_type": "who_owes"}, "confidence": 0.95},
    "list the expense one by one": {"tool": "query_expense", "args": {"month": "current", "list_mode": True}, "confidence": 0.9},
    "show me this month expense list": {"tool": "query_expense", "args": {"month": "current", "list_mode": True}, "confidence": 0.9},
    "analyse this month expense": {"tool": "query_expense", "args": {"month": "current", "list_mode": True}, "confidence": 0.75},
    "vivekananda notes": {"tool": "query_notes", "args": {"query": "vivekananda"}, "confidence": 0.9},
    "any info of vivekananda in our notes": {"tool": "query_notes", "args": {"query": "vivekananda"}, "confidence": 0.9},
    "show me last 5 notes": {"tool": "query_notes", "args": {"query": "", "recent": True, "limit": 5}, "confidence": 0.85},
    "show me saved notes": {"tool": "query_notes", "args": {"query": "", "recent": True, "limit": 10}, "confidence": 0.85},
    "show me motivation quotes saved": {"tool": "query_notes", "args": {"query": "motivation"}, "confidence": 0.85},
    "show todo list": {"tool": "query_todos", "args": {"status": "pending"}, "confidence": 0.95},
    "show me todo list": {"tool": "query_todos", "args": {"status": "pending"}, "confidence": 0.95},
    "todo list pls": {"tool": "query_todos", "args": {"status": "pending"}, "confidence": 0.9},
    "cleared todo list": {"tool": "query_todos", "args": {"status": "done"}, "confidence": 0.85},
    "monthly expense": {"tool": "query_expense", "args": {"month": "current"}, "confidence": 0.95},
    "this month expense": {"tool": "query_expense", "args": {"month": "current"}, "confidence": 0.95},
}


QWEN_PLAN_PROMPT = """You plan how to answer a query against a personal note app on SQLite.
Today: {today}.  Current month: {current_month}.
Known persons (lowercase): {persons}.

You can do ONE of these:

1. sql_query — read-only SQL against these tables and views ONLY:
     expenses(id, amount, description, date, month, raw_note, created_at)
     ledger(id, person, amount, direction['gave'|'received'], note, date, created_at)
     ledger_balance(person, balance)         -- view; balance>0 means they owe you
     weights(id, person, weight, date, note, created_at)
     todos(id, content, status['pending'|'done'], date, created_at)
     persons(id, name)
   Rules:
     - SELECT only. No INSERT/UPDATE/DELETE/PRAGMA/ATTACH/DROP/CREATE/ALTER.
     - One statement, no internal semicolons.
     - Use ? placeholders for literals, supply values in "params".
     - Use the precomputed `month` column for month filters (format YYYY-MM).
     - Cap with LIMIT 100 unless the user clearly asks for fewer.

2. note_query — semantic search across the user's saved notes.
   Use this when the user asks about content of saved notes.

3. clarify — when the input is genuinely ambiguous, ask a numbered question.

4. unknown — when no plan fits.

User input: "{text}"

Return JSON only — no prose, no markdown. Exactly one of:
  {{"action":"sql_query","sql":"...","params":[...],"intent":"<short label>","confidence":0.0-1.0}}
  {{"action":"note_query","query":"...","recent":false,"limit":5,"confidence":0.0-1.0}}
  {{"action":"clarify","question":"...","options":[{{"label":"...","action":"sql_query","sql":"...","params":[...]}}],"confidence":0.0-1.0}}
  {{"action":"unknown"}}

Examples:
Input: "expenses apart from petrol last month"
-> {{"action":"sql_query","sql":"SELECT id,amount,description,date FROM expenses WHERE month=? AND description NOT LIKE ? ORDER BY date DESC LIMIT 100","params":["2026-04","%petrol%"],"intent":"last month expenses except petrol","confidence":0.9}}

Input: "last 3 expense"
-> {{"action":"sql_query","sql":"SELECT date,amount,description FROM expenses ORDER BY date DESC, id DESC LIMIT 3","params":[],"intent":"last 3 expenses","confidence":0.9}}

Input: "weight status"
-> {{"action":"sql_query","sql":"SELECT person, weight, date FROM weights w WHERE date=(SELECT MAX(date) FROM weights WHERE person=w.person) ORDER BY person","params":[],"intent":"latest weight per person","confidence":0.85}}

Input: "how much money i owe"
-> {{"action":"sql_query","sql":"SELECT person, ABS(balance) AS amount FROM ledger_balance WHERE balance < 0 ORDER BY amount DESC","params":[],"intent":"money you owe","confidence":0.9}}

Input: "vivekananda note"
-> {{"action":"note_query","query":"vivekananda","recent":false,"limit":5,"confidence":0.9}}

Input: "show all notes"
-> {{"action":"note_query","query":"","recent":true,"limit":50,"confidence":0.85}}

Now plan:"""


MOCK_PLAN_RESPONSES: dict[str, dict[str, Any]] = {
    # Each entry is the canonical response for one normalized phrasing from the
    # activity log. Substring fallback applies when no exact match is found.
    "latest note": {"action": "note_query", "query": "", "recent": True, "limit": 1, "confidence": 0.9},
    "last note": {"action": "note_query", "query": "", "recent": True, "limit": 1, "confidence": 0.9},
    "show all notes": {"action": "note_query", "query": "", "recent": True, "limit": 50, "confidence": 0.85},
    "all notes": {"action": "note_query", "query": "", "recent": True, "limit": 50, "confidence": 0.85},
    "vivekananda note": {"action": "note_query", "query": "vivekananda", "recent": False, "limit": 5, "confidence": 0.9},
    "weight status": {
        "action": "sql_query",
        "sql": "SELECT person, weight, date FROM weights w WHERE date=(SELECT MAX(date) FROM weights WHERE person=w.person) ORDER BY person",
        "params": [],
        "intent": "latest weight per person",
        "confidence": 0.85,
    },
    "expense status": {
        "action": "sql_query",
        "sql": "SELECT month, SUM(amount) AS total FROM expenses GROUP BY month ORDER BY month DESC LIMIT 3",
        "params": [],
        "intent": "spend by recent months",
        "confidence": 0.85,
    },
    "all ledger": {
        "action": "sql_query",
        "sql": "SELECT person, balance FROM ledger_balance ORDER BY ABS(balance) DESC",
        "params": [],
        "intent": "all ledger balances",
        "confidence": 0.85,
    },
    "maddy ledger": {
        "action": "sql_query",
        "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC",
        "params": ["maddy"],
        "intent": "maddy ledger entries",
        "confidence": 0.9,
    },
    "ravi ledger": {
        "action": "sql_query",
        "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC",
        "params": ["ravi"],
        "intent": "ravi ledger entries",
        "confidence": 0.9,
    },
    "how much money i owe": {
        "action": "sql_query",
        "sql": "SELECT person, ABS(balance) AS amount FROM ledger_balance WHERE balance < 0 ORDER BY amount DESC",
        "params": [],
        "intent": "money you owe",
        "confidence": 0.9,
    },
    "last 3 expense": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses ORDER BY date DESC, id DESC LIMIT 3",
        "params": [],
        "intent": "last 3 expenses",
        "confidence": 0.9,
    },
    "last 5 expense": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses ORDER BY date DESC, id DESC LIMIT 5",
        "params": [],
        "intent": "last 5 expenses",
        "confidence": 0.9,
    },
    "last 4 expenses": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses ORDER BY date DESC, id DESC LIMIT 4",
        "params": [],
        "intent": "last 4 expenses",
        "confidence": 0.9,
    },
    "last 3 bills": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses ORDER BY date DESC, id DESC LIMIT 3",
        "params": [],
        "intent": "last 3 expenses",
        "confidence": 0.8,
    },
    "bills this month": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses WHERE month=? ORDER BY date DESC, id DESC LIMIT 100",
        "params": ["__CURRENT_MONTH__"],
        "intent": "current month expenses",
        "confidence": 0.8,
    },
    "show ledger for maddy": {
        "action": "sql_query",
        "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC LIMIT 100",
        "params": ["maddy"],
        "intent": "maddy ledger entries",
        "confidence": 0.9,
    },
    "show ledger for ravi": {
        "action": "sql_query",
        "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC LIMIT 100",
        "params": ["ravi"],
        "intent": "ravi ledger entries",
        "confidence": 0.9,
    },
    "ledger history for maddy": {
        "action": "sql_query",
        "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC LIMIT 100",
        "params": ["maddy"],
        "intent": "maddy ledger entries",
        "confidence": 0.9,
    },
    "ledger history for ravi": {
        "action": "sql_query",
        "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC LIMIT 100",
        "params": ["ravi"],
        "intent": "ravi ledger entries",
        "confidence": 0.9,
    },
    "expenses apart from petrol last month": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses WHERE month=? AND description NOT LIKE ? ORDER BY date DESC LIMIT 100",
        "params": ["__LAST_MONTH__", "%petrol%"],
        "intent": "last month expenses except petrol",
        "confidence": 0.85,
    },
    "groceries last month": {
        "action": "sql_query",
        "sql": "SELECT date, amount, description FROM expenses WHERE month=? AND description LIKE ? ORDER BY date DESC LIMIT 100",
        "params": ["__LAST_MONTH__", "%groceries%"],
        "intent": "groceries last month",
        "confidence": 0.85,
    },
}


QWEN_PARSE_PROMPT = """You are a note parser. Extract structured data from the following note.

Note: "{raw_note}"
Today's date: "{today}"

Extract and return JSON only. No explanation. No markdown.

For money/ledger: {{"type": "ledger", "person": "", "amount": 0, "direction": "gave|received", "note": ""}}
For weight: {{"type": "weight", "person": "", "weight": 0.0, "note": ""}}
For expense: {{"type": "expense", "amount": 0, "description": ""}}
For todo: {{"type": "todo", "content": ""}}
For a normal note: {{"type": "note", "domain": "general|investment|health"}}
If unclear: {{"type": "unknown", "content": ""}}

Rules:
- gave/give/given/lent/sent + person = ledger, direction: gave (user gave money to them)
- got/received/returned/paid back + person = ledger, direction: received (they gave money to user)
- gift keyword = expense, not ledger
- weight is a number associated with a person's name, usually below 150kg
- ledger amounts are usually 100 or more
- amount in k means thousands (5k = 5000), L means lakhs (1.5L = 150000)
- expense description is the item name verbatim, do not invent categories
- use type "note" for narrative, reflective, informational, or reference text that is not a todo
"""
QWEN_RAG_PROMPT = """You answer only from the retrieved notes below.

Question: "{question}"
Domain: "{domain}"

Retrieved notes:
{context}

Instructions:
- Answer directly and briefly.
- If the notes do not support an answer, say that the notes do not contain it.
- Do not invent facts beyond the notes.
"""

QWEN_NOTE_SYNTH_PROMPT = """You answer the user's question using ONLY the saved notes below.

User question: "{question}"

Saved notes (each numbered with its source id):
{context}

Rules:
- Use only the wording in the notes. Light paraphrase is allowed; aggressive rewrite is not.
- If the notes do not contain enough to answer, say "The notes do not contain enough to answer."
- Do not invent facts.
- Keep your answer to 1-3 short sentences.
- Do not list the snippets back — they will be shown separately."""
MOCK_LLM_RESPONSES = {
    "moni sent 10k for groceries": {
        "type": "ledger",
        "person": "moni",
        "amount": 10000,
        "direction": "received",
        "note": "for groceries",
    },
    "mani 500": {"type": "expense", "amount": 500, "description": "mani"},
    "iniyan iyar ku money 500": {
        "type": "ledger",
        "person": "iniyan",
        "amount": 500,
        "direction": "gave",
        "note": None,
    },
    "got seetu money 23000": {
        "type": "ledger",
        "person": "self",
        "amount": 23000,
        "direction": "received",
        "note": "seetu chit fund",
    },
    "paid electricity 3560": {
        "type": "expense",
        "amount": 3560,
        "description": "electricity",
    },
    "advanced 1000 for mutton biryani": {
        "type": "expense",
        "amount": 1000,
        "description": "mutton biryani advance",
    },
    "amma gave 6k for moni saree": {
        "type": "ledger",
        "person": "amma",
        "amount": 6000,
        "direction": "received",
        "note": "for moni saree",
    },
}


def db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _perf_add(perf: dict[str, float] | None, key: str, elapsed_seconds: float) -> None:
    if perf is None:
        return
    perf[key] = round(float(perf.get(key, 0.0)) + (elapsed_seconds * 1000.0), 3)


@contextmanager
def perf_timer(perf: dict[str, float] | None, key: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        _perf_add(perf, key, time.perf_counter() - started)


def llm_backend_name(llm_service: Any) -> str:
    getter = getattr(llm_service, "backend_name", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return "error"
    status = getattr(llm_service, "status", None)
    if callable(status):
        try:
            payload = status() or {}
            return str(payload.get("backend") or "unknown")
        except Exception:
            return "error"
    return "unknown"


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    ddl: str,
) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


def ensure_runtime_schema(db_path: str = DEFAULT_DB_PATH) -> None:
    with db_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input_text TEXT NOT NULL,
                response_text TEXT NOT NULL,
                kind TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        _ensure_column(conn, "activity_log", "metadata_json", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_input TEXT NOT NULL,
                capture_type TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                input_kind TEXT NOT NULL DEFAULT 'note',
                structured_type TEXT,
                note_domain TEXT,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                processed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buy_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_text TEXT NOT NULL,
                quantity_text TEXT,
                unit_text TEXT,
                date TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
                raw_note TEXT,
                source_note_id INTEGER,
                source_capture_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                note_id INTEGER,
                prompt TEXT NOT NULL,
                options_json TEXT NOT NULL,
                payload_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved','dismissed')),
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                resolved_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_routing_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input_pattern TEXT NOT NULL UNIQUE,
                resolved_tool TEXT NOT NULL,
                resolved_args_json TEXT,
                hit_count INTEGER DEFAULT 1,
                last_used TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_routing_pattern ON user_routing_memory(input_pattern)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_state (
                state_key TEXT PRIMARY KEY,
                value_json TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        for table_name in ("expenses", "ledger", "weights", "todos", "buy_items", "embeddings"):
            _ensure_column(conn, table_name, "source_note_id", "INTEGER")
        for table_name in ("expenses", "ledger", "weights", "todos", "buy_items"):
            _ensure_column(conn, table_name, "source_capture_id", "INTEGER")
        _ensure_column(conn, "expenses", "group_name", "TEXT")
        _migrate_structured_notes_to_captures(conn)
        _purge_audit_notes(conn)
        conn.commit()


def _purge_audit_notes(conn: sqlite3.Connection) -> dict[str, int]:
    """Drop legacy audit-trail rows from `notes` left over before the
    fix-3 cleanup. These rows were created by the orchestrator for
    query/clarify/planner traces; they're never user-visible (filtered
    from /notes by structured_type='note'), and `activity_log` already
    captures the same metadata.

    Only deletes rows whose structured_type is NOT 'note' AND that are
    not referenced by any pending_actions row, any structured-fact row,
    or any embedding. Idempotent.
    """
    deleted = 0
    rows = conn.execute(
        """
        SELECT id FROM notes
        WHERE structured_type IN ('query', 'clarify')
        """
    ).fetchall()
    for row in rows:
        nid = row["id"]
        # Skip if anything still references this note row.
        still_referenced = False
        for table in ("expenses", "ledger", "weights", "todos", "buy_items"):
            if conn.execute(
                f"SELECT 1 FROM {table} WHERE source_note_id = ? LIMIT 1",
                (nid,),
            ).fetchone():
                still_referenced = True
                break
        if still_referenced:
            continue
        if conn.execute(
            "SELECT 1 FROM pending_actions WHERE note_id = ? LIMIT 1", (nid,),
        ).fetchone():
            continue
        if conn.execute(
            "SELECT 1 FROM embeddings WHERE source_note_id = ? LIMIT 1", (nid,),
        ).fetchone():
            continue
        conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
        deleted += 1
    return {"audit_notes_deleted": deleted}


def _migrate_structured_notes_to_captures(conn: sqlite3.Connection) -> dict[str, int]:
    """Move legacy structured-origin notes into the captures layer.

    For each structured row (expenses/ledger/weights/todos) that still links
    to a notes row instead of a capture row, create the matching capture and
    repoint the structured row. Then drop notes rows that:
      - have a non-'note' structured_type (or NULL),
      - have no remaining structured-row references, and
      - are not real user notes.

    Idempotent: rows already on source_capture_id are skipped; rows without
    source_note_id are skipped.
    """
    table_capture_types = {
        "expenses": "expense",
        "ledger": "ledger",
        "weights": "weight",
        "todos": "todo",
        "buy_items": "buy",
    }
    counters = {"captures_created": 0, "rows_repointed": 0, "notes_deleted": 0}
    touched_note_ids: set[int] = set()

    for table, capture_type in table_capture_types.items():
        rows = conn.execute(
            f"""
            SELECT id, source_note_id
            FROM {table}
            WHERE source_note_id IS NOT NULL
              AND (source_capture_id IS NULL OR source_capture_id = 0)
            """
        ).fetchall()
        for row in rows:
            note_id = row["source_note_id"]
            note_row = conn.execute(
                "SELECT content, structured_type, metadata_json FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            raw_input = note_row["content"] if note_row else ""
            metadata_json = note_row["metadata_json"] if note_row else None
            metadata = {"migrated_from_note_id": note_id}
            if metadata_json:
                try:
                    legacy_meta = json.loads(metadata_json)
                    if isinstance(legacy_meta, dict):
                        metadata["legacy_metadata"] = legacy_meta
                except (TypeError, json.JSONDecodeError):
                    pass
            cursor = conn.execute(
                "INSERT INTO captures (raw_input, capture_type, metadata_json) VALUES (?,?,?)",
                (raw_input, capture_type, _json_dump(metadata)),
            )
            capture_id = int(cursor.lastrowid)
            conn.execute(
                f"UPDATE {table} SET source_capture_id = ?, source_note_id = NULL WHERE id = ?",
                (capture_id, row["id"]),
            )
            counters["captures_created"] += 1
            counters["rows_repointed"] += 1
            if note_id is not None:
                touched_note_ids.add(int(note_id))

    # Drop only structured-origin notes rows that no structured table still
    # references AND that are not real user notes.
    for note_id in touched_note_ids:
        still_linked = False
        for table in table_capture_types:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE source_note_id = ? LIMIT 1",
                (note_id,),
            ).fetchone()
            if row:
                still_linked = True
                break
        if still_linked:
            continue
        note_row = conn.execute(
            "SELECT structured_type FROM notes WHERE id = ?", (note_id,),
        ).fetchone()
        if not note_row:
            continue
        if note_row["structured_type"] == "note":
            # Real user note — leave it.
            continue
        conn.execute("DELETE FROM embeddings WHERE source_note_id = ?", (note_id,))
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        counters["notes_deleted"] += 1

    return counters


def ensure_activity_log_schema(db_path: str = DEFAULT_DB_PATH) -> None:
    ensure_runtime_schema(db_path)


def lookup_routing_memory(
    conn: sqlite3.Connection,
    normalized_pattern: str,
) -> dict[str, Any] | None:
    """Return the memoized routing decision for an input, or None.

    Side effect: bumps hit_count and last_used on hit. Caller should commit.
    """
    row = conn.execute(
        """
        SELECT id, resolved_tool, resolved_args_json, hit_count
        FROM user_routing_memory
        WHERE input_pattern = ?
        """,
        (normalized_pattern,),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        """
        UPDATE user_routing_memory
        SET hit_count = hit_count + 1, last_used = datetime('now')
        WHERE id = ?
        """,
        (row["id"],),
    )
    args: dict[str, Any] = {}
    if row["resolved_args_json"]:
        try:
            args = json.loads(row["resolved_args_json"])
        except json.JSONDecodeError:
            args = {}
    return {
        "tool": row["resolved_tool"],
        "args": args,
        "hit_count": row["hit_count"] + 1,
    }


def upsert_routing_memory(
    conn: sqlite3.Connection,
    normalized_pattern: str,
    tool: str,
    args: dict[str, Any] | None = None,
) -> None:
    """Record (or refresh) a routing decision keyed by normalized input.

    Called when a clarify_with_user resolution lands. Caller should commit.
    """
    payload = json.dumps(args or {}, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO user_routing_memory (input_pattern, resolved_tool, resolved_args_json)
        VALUES (?, ?, ?)
        ON CONFLICT(input_pattern) DO UPDATE SET
            resolved_tool = excluded.resolved_tool,
            resolved_args_json = excluded.resolved_args_json,
            hit_count = user_routing_memory.hit_count + 1,
            last_used = datetime('now')
        """,
        (normalized_pattern, tool, payload),
    )


def prune_routing_memory(
    conn: sqlite3.Connection,
    days: int = 90,
) -> int:
    """Drop entries unused for >`days` days. Returns count pruned. Caller commits."""
    cursor = conn.execute(
        "DELETE FROM user_routing_memory WHERE last_used < datetime('now', ?)",
        (f"-{int(days)} days",),
    )
    return int(cursor.rowcount or 0)


def load_known_persons(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("SELECT name FROM persons")}


def load_weight_persons(conn: sqlite3.Connection) -> set[str]:
    return {
        row["person"]
        for row in conn.execute(
            "SELECT DISTINCT person FROM weights WHERE person IS NOT NULL AND person <> ''"
        ).fetchall()
    }


def load_runtime_state(conn: sqlite3.Connection, state_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value_json FROM runtime_state WHERE state_key = ?",
        (state_key,),
    ).fetchone()
    if not row or not row["value_json"]:
        return None
    try:
        payload = json.loads(row["value_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def store_runtime_state(
    conn: sqlite3.Connection,
    state_key: str,
    payload: dict[str, Any] | None,
) -> None:
    conn.execute(
        """
        INSERT INTO runtime_state (state_key, value_json, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(state_key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        (state_key, _json_dump(payload)),
    )


def clear_runtime_state(conn: sqlite3.Connection, state_key: str) -> None:
    conn.execute("DELETE FROM runtime_state WHERE state_key = ?", (state_key,))


def parse_amount(text: str) -> float | None:
    text = text.strip().replace(",", "")
    match = re.match(r"^(\d+\.?\d*)\s*[kK]$", text)
    if match:
        return float(match.group(1)) * 1000
    match = re.match(r"^(\d+\.?\d*)\s*[lL]$", text)
    if match:
        return float(match.group(1)) * 100000
    match = re.match(r"^(\d+\.?\d*)$", text)
    if match:
        return float(match.group(1))
    return None


def find_amount_in_tokens(tokens: list[str]) -> tuple[float | None, int]:
    for index, token in enumerate(tokens):
        amount = parse_amount(token)
        if amount is not None:
            return amount, index
    return None, -1


def get_month(value: str) -> str:
    return value[:7]


def format_rupees(amount: float) -> str:
    return f"₹{amount:,.0f}"


def infer_note_domain(text: str) -> str:
    return "general"


def extract_explicit_note_body(text: str) -> str | None:
    match = re.match(r"^\s*note\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    body = match.group(1).strip()
    return body or None


def extract_explicit_todo_body(text: str) -> str | None:
    match = re.match(r"^\s*(?:todo|task)\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    body = match.group(1).strip()
    return body or None


def split_todo_items(body: str) -> list[str]:
    body = (body or "").strip()
    if not body:
        return []

    items: list[str] = []

    def _clean_item(value: str) -> str:
        return re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", value.strip())

    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) > 1:
        for line in lines:
            cleaned = _clean_item(line)
            if cleaned:
                items.append(cleaned)
        if items:
            return items

    separator_parts = [
        _clean_item(part)
        for part in re.split(r"\s*(?:;\s*|\.\-\s*|\|\s*)", body)
        if part.strip()
    ]
    if len(separator_parts) > 1:
        return [part for part in separator_parts if part]

    cleaned = _clean_item(body)
    return [cleaned] if cleaned else []


def extract_weight_query_args(text: str, persons: set[str]) -> dict[str, Any] | None:
    lowered = text.lower().strip()
    if "balance" in lowered:
        return None

    person = next(
        (
            name
            for name in sorted(persons, key=len, reverse=True)
            if re.search(rf"\b{re.escape(name)}\b", lowered)
        ),
        None,
    )
    if not person:
        return None

    query_markers = {"last", "latest", "show", "list", "trend", "history", "recent", "date", "dates"}
    if not any(marker in lowered for marker in query_markers) and not (
        "weight" in lowered and parse_amount(lowered.split()[-1]) is None
    ):
        return None

    limit = 1
    count_match = re.search(r"\b(?:last|show(?:\s+me)?|list)\s+(\d+)\b", lowered)
    if count_match:
        limit = max(1, min(int(count_match.group(1)), 20))
    elif any(marker in lowered for marker in {"trend", "history", "recent"}):
        limit = 5

    return {"person": person, "limit": limit}


def extract_note_query_args(text: str) -> dict[str, Any] | None:
    lowered = text.lower().strip()
    if not lowered or lowered.startswith("note:"):
        return None

    recent_match = re.fullmatch(r"(?:show\s+(?:me\s+)?)?last\s+(\d+)\s+notes?", lowered)
    if recent_match:
        return {"query": "", "recent": True, "limit": max(1, min(int(recent_match.group(1)), 50))}
    if re.fullmatch(r"(?:show\s+(?:me\s+)?)?(?:saved|recent)\s+notes?", lowered):
        return {"query": "", "recent": True, "limit": 10}
    if re.fullmatch(r"(?:show\s+(?:me\s+)?)?(?:all|every)\s+notes?", lowered):
        return {"query": "", "recent": True, "limit": 50}

    existence_match = re.fullmatch(
        r"(?:did|do|have)\s+i\s+(?:ever\s+)?save(?:d)?\s+(?:a\s+)?note\s+(?:about|on)\s+(.+)",
        lowered,
    )
    if existence_match:
        query = existence_match.group(1).strip(" ?.!")
        return {"query": query} if query else {"query": "", "recent": True, "limit": 10}

    short_singular_note_match = re.fullmatch(r"(.+?)\s+note", lowered)
    note_context = (
        "notes" in lowered
        or "saved note" in lowered
        or "saved notes" in lowered
        or "in my notes" in lowered
        or "in our notes" in lowered
        or "in the notes" in lowered
        or lowered.startswith(("what note", "which note"))
        or re.search(r"\b(?:did|do|have)\s+i\s+(?:ever\s+)?save(?:d)?\s+(?:a\s+)?note\b", lowered) is not None
        or re.search(r"^\s*(?:show\s+(?:me\s+)?)?(?:all|every)\s+note(?:s)?\b", lowered) is not None
        or (
            short_singular_note_match is not None
            and len(short_singular_note_match.group(1).split()) <= 4
        )
    )
    queryish = looks_like_query_text(text) or lowered.startswith(
        (
            "any info ",
            "any mention ",
            "find ",
            "search ",
            "did i ",
            "do i ",
            "have i ",
            "what note",
            "which note",
        )
    )
    if not (note_context or queryish):
        return None

    query = lowered
    query = re.sub(r"^(?:did|do|have)\s+i\s+(?:ever\s+)?save(?:d)?\s+(?:a\s+)?note\s+(?:about|on)\s+", "", query)
    query = re.sub(
        r"^(?:what|which)\s+note(?:s)?\s+(?:did i save\s+)?(?:that\s+)?(?:mentions?|mentioned|says|said|talks?\s+about|about|on)\s+",
        "",
        query,
    )
    query = re.sub(
        r"^(?:show\s+(?:me\s+)?)?(?:every|all)\s+note(?:s)?\s+(?:that\s+)?(?:mentions?|mentioned|about|on)\s+",
        "",
        query,
    )
    query = re.sub(r"\b(?:in|from)\s+(?:my|our|the)\s+notes?\b", "", query)
    query = re.sub(r"\bnotes?\b", "", query)
    query = re.sub(r"\bsaved\b", "", query)
    query = re.sub(r"^(?:any\s+(?:info|mention)\s+(?:of|on)\s+)", "", query)
    query = re.sub(r"^(?:find|search)\s+", "", query)
    query = re.sub(r"^(?:show\s+(?:me\s+)?)", "", query)
    query = re.sub(r"^(?:notes?\s+(?:about|on)\s+)", "", query)
    query = re.sub(r"^(?:about|on)\s+", "", query)
    query = re.sub(r"\b(?:most\s+recently|recently|ever)\b", "", query)
    query = re.sub(r"\s+", " ", query).strip(" ?.!")
    if not query:
        return {"query": "", "recent": True, "limit": 10}
    return {"query": query}


def looks_like_settlement_followup(text: str) -> bool:
    lowered = text.lower().strip()
    return any(signal in lowered for signal in SETTLEMENT_SIGNALS)


def looks_like_todo_text(text: str) -> bool:
    lowered = text.lower().strip()
    if any(lowered.startswith(prefix) for prefix in TODO_LEADS):
        return True
    tokens = [token for token in re.split(r"\s+", lowered) if token]
    if not tokens:
        return False
    if len(tokens) <= 5 and tokens[0] in TODO_START_VERBS:
        return True
    if len(tokens) <= 7 and any(
        token in {"today", "tomorrow", "tonight", "thursday", "friday"} for token in tokens
    ):
        return tokens[0] in TODO_START_VERBS
    return False


def parse_person_command(text: str) -> dict[str, Any] | None:
    match = PERSON_CMD_RE.match(text.strip())
    if not match:
        return None
    op = match.group(1).upper()
    payload = match.group(2).strip().lower()
    if op == "MODIFY_PERSON":
        parts = payload.split()
        if len(parts) != 2:
            return {
                "type": "person_command",
                "op": op,
                "error": "Expected: MODIFY_PERSON: oldname newname",
            }
        return {
            "type": "person_command",
            "op": op,
            "old_name": parts[0],
            "new_name": parts[1],
        }
    return {"type": "person_command", "op": op, "name": payload}


def looks_like_query_text(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered.startswith(QUERY_LEADS) or lowered.endswith("?")


def _parse_rule_entry(text: str, today: str, persons: set[str]) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None

    lowered = text.lower()
    tokens = text.split()
    raw_tokens = text.split()
    cmd = parse_person_command(text)
    if cmd:
        return cmd

    if extract_note_query_args(text):
        return {
            "type": "unknown",
            "content": text,
            "raw": text,
            "reason": "note_query_like",
        }

    if extract_weight_query_args(text, persons):
        return {
            "type": "unknown",
            "content": text,
            "raw": text,
            "reason": "weight_query_like",
        }

    if re.search(r"\bgift\b", lowered):
        amount, _ = find_amount_in_tokens(tokens)
        if amount:
            description = re.sub(r"\b\d+[kKlL]?\b|gift", "", text).strip()
            return {
                "type": "expense",
                "amount": amount,
                "description": description or "gift",
                "date": today,
                "month": get_month(today),
                "raw": text,
            }

    amount, amount_index = find_amount_in_tokens(tokens)

    if re.search(RECEIVED_KEYWORDS, lowered):
        person_match = re.search(r"from\s+([a-zA-Z]+)", lowered) or re.search(
            r"^([a-zA-Z]+)\s+(?:returned|paid)", lowered
        )
        if amount and person_match:
            person = person_match.group(1).lower()
            return {
                "type": "ledger",
                "person": person,
                "amount": amount,
                "direction": "received",
                "date": today,
                "raw": text,
                "unknown_person": person not in persons,
            }

    if re.search(GAVE_KEYWORDS, lowered):
        gave_match = re.search(
            r"(?:gave|give|given|lent|sent|advanced)\s+([a-zA-Z]+)", lowered
        )
        person_first_match = re.search(r"^([a-zA-Z]+)\s+(?:gave|give|sent)\b", lowered)
        if amount:
            if person_first_match:
                person = person_first_match.group(1).lower()
                return {
                    "type": "ledger",
                    "person": person,
                    "amount": amount,
                    "direction": "received",
                    "date": today,
                    "raw": text,
                    "unknown_person": person not in persons,
                }
            if gave_match:
                person = gave_match.group(1).lower()
                return {
                    "type": "ledger",
                    "person": person,
                    "amount": amount,
                    "direction": "gave",
                    "date": today,
                    "raw": text,
                    "unknown_person": person not in persons,
                }

    for name in persons:
        match = re.search(rf"\b{name}\b\s+(\d+\.?\d*)|(\d+\.?\d*)\s+\b{name}\b", lowered)
        if match:
            number = float(match.group(1) or match.group(2))
            if number < 150:
                note_match = re.search(rf"\b{name}\b\s+\d+\.?\d*\s*(.*)", lowered)
                note = note_match.group(1).strip() if note_match and note_match.group(1).strip() else None
                return {
                    "type": "weight",
                    "person": name,
                    "weight": number,
                    "note": note,
                    "date": today,
                    "raw": text,
                }

    if amount is not None:
        if re.search(GAVE_KEYWORDS, lowered) or re.search(RECEIVED_KEYWORDS, lowered) or "money" in lowered:
            return {
                "type": "unknown",
                "content": text,
                "raw": text,
                "reason": "ledger_like_but_unresolved",
            }
        if (
            150 <= amount <= 999
            and raw_tokens
            and raw_tokens[0][:1].isupper()
            and raw_tokens[0].lower() not in persons
        ):
            return {
                "type": "unknown",
                "content": text,
                "raw": text,
                "reason": "ambiguous_person_like_amount",
            }
        description = " ".join(
            token for index, token in enumerate(tokens) if index != amount_index
        ).strip(" -+") or "misc"
        return {
            "type": "expense",
            "amount": amount,
            "description": description,
            "date": today,
            "month": get_month(today),
            "raw": text,
        }

    if looks_like_query_text(text):
        return {
            "type": "unknown",
            "content": text,
            "raw": text,
            "reason": "query_like_text",
        }

    if looks_like_todo_text(text):
        return {"type": "todo", "content": text, "raw": text}

    return {
        "type": "note",
        "content": text,
        "domain": "general",
        "raw": text,
    }


def parse_note_for_write(
    raw: str,
    today: str | None = None,
    persons: set[str] | None = None,
) -> list[dict[str, Any]]:
    if today is None:
        today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    raw = raw.strip()
    cmd = parse_person_command(raw)
    if cmd:
        return [cmd]
    if persons is None:
        with db_connection() as conn:
            persons = load_known_persons(conn) | load_weight_persons(conn)
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return [
        result
        for part in parts
        for result in [_parse_rule_entry(part, today, persons)]
        if result
    ]


def extract_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


def _validate_route_response(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("unknown") is True:
        return True
    if result.get("clarify") is True:
        opts = result.get("options")
        return isinstance(opts, list) and len(opts) > 0
    if "tool" in result:
        if not isinstance(result["tool"], str) or not result["tool"]:
            return False
        args = result.get("args", {})
        return isinstance(args, dict)
    return False


def _validate_plan_response(result: dict[str, Any]) -> bool:
    """Validate the JSON shape returned by `LLMService.plan_query`.

    The semantic safety check (allowed tables, no DDL) lives in `sql_safety`;
    this validator only checks structure so the orchestrator can branch.
    """
    if not isinstance(result, dict):
        return False
    action = result.get("action")
    if action == "unknown":
        return True
    if action == "sql_query":
        sql = result.get("sql")
        params = result.get("params", [])
        return (
            isinstance(sql, str) and bool(sql.strip())
            and isinstance(params, list)
        )
    if action == "note_query":
        query = result.get("query", "")
        return isinstance(query, str)
    if action == "clarify":
        options = result.get("options")
        question = result.get("question")
        return (
            isinstance(question, str) and bool(question.strip())
            and isinstance(options, list) and len(options) > 0
        )
    return False


def resolve_plan_relative_dates(plan: dict[str, Any], today: str) -> dict[str, Any]:
    """Replace `__LAST_MONTH__` / `__CURRENT_MONTH__` sentinels in plan params.

    The planner LLM may emit relative tokens so a memoized plan stays
    correct regardless of when it was first saved. This function expands
    them at execution time. Returns a (possibly modified) copy of `plan`.
    """
    if not isinstance(plan, dict) or plan.get("action") != "sql_query":
        return plan
    params = plan.get("params") or []
    if not any(isinstance(p, str) and p.startswith("__") and p.endswith("__") for p in params):
        return plan

    try:
        anchor = datetime.strptime(today[:10], "%Y-%m-%d")
    except Exception:
        anchor = datetime.now()
    current_ym = anchor.strftime("%Y-%m")
    if anchor.month == 1:
        last_ym = f"{anchor.year - 1}-12"
    else:
        last_ym = f"{anchor.year:04d}-{anchor.month - 1:02d}"

    expanded = []
    for value in params:
        if value == "__CURRENT_MONTH__":
            expanded.append(current_ym)
        elif value == "__LAST_MONTH__":
            expanded.append(last_ym)
        else:
            expanded.append(value)
    out = dict(plan)
    out["params"] = expanded
    return out


def validate_llm_parse(result: dict[str, Any]) -> bool:
    parsed_type = result.get("type")
    if parsed_type == "ledger":
        return (
            result.get("amount", 0) > 0
            and result.get("direction") in {"gave", "received"}
            and bool(result.get("person", "").strip())
        )
    if parsed_type == "expense":
        return result.get("amount", 0) > 0
    if parsed_type == "weight":
        return result.get("weight", 0) > 0 and bool(result.get("person", "").strip())
    if parsed_type == "note":
        return result.get("domain", "general") in {"general", "investment", "health"}
    if parsed_type in {"todo", "unknown"}:
        return True
    return False


class LLMService:
    def __init__(
        self,
        model_path: str = DEFAULT_QWEN_GGUF_PATH,
        transformers_model: str = DEFAULT_QWEN_TRANSFORMERS_MODEL,
    ) -> None:
        self.model_path = model_path
        self.transformers_model = transformers_model
        self._backend: str | None = None
        self._load_error: str | None = None
        self._llama = None
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._backend_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        self._ensure_backend_selected()
        load_error = self._load_error if self._backend == "mock" else None
        return {
            "backend": self._backend,
            "model_path": self.model_path,
            "transformers_model": self.transformers_model,
            "load_error": load_error,
        }

    def backend_name(self) -> str:
        return self._backend or "uninitialized"

    def parse_note(self, raw_note: str, today: str) -> dict[str, Any]:
        prompt = QWEN_PARSE_PROMPT.format(raw_note=raw_note, today=today)
        if self._ensure_backend_selected() == "mock":
            self._load_error = None
            return self._mock_parse(raw_note)

        try:
            output = self._generate(prompt, max_tokens=180)
            result = json.loads(extract_json(output))
            if validate_llm_parse(result):
                self._load_error = None
                return result
        except Exception as exc:  # pragma: no cover - defensive path
            self._load_error = str(exc)

        return {"type": "unknown", "content": raw_note}

    def route_input(
        self,
        text: str,
        today: str,
        persons: list[str],
        perf: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Tier 1 router: pick a tool, request clarification, or return unknown.

        Strategy: real backend first; on JSON failure, retry once with stricter
        prompt; on persistent failure, fall back to mock dict; finally,
        signal unknown so the orchestrator builds a heuristic clarify menu.
        """
        with perf_timer(perf, "llm_route.total_ms"):
            normalized = re.sub(r"\s+", " ", text.strip().lower())
            prompt = QWEN_ROUTE_PROMPT.format(
                text=text,
                today=today,
                persons=", ".join(sorted(persons)) or "(none)",
            )

            with perf_timer(perf, "llm_route.backend_select_ms"):
                backend = self._ensure_backend_selected()
            if backend == "mock":
                return self._mock_route(normalized)

            for attempt in range(2):
                try:
                    effective = prompt if attempt == 0 else prompt + "\n\nRespond with JSON only. No prose. No markdown fences."
                    with perf_timer(perf, f"llm_route.generate_attempt_{attempt + 1}_ms"):
                        output = self._generate(effective, max_tokens=240)
                    result = json.loads(extract_json(output))
                    if _validate_route_response(result):
                        self._load_error = None
                        return result
                except Exception as exc:  # pragma: no cover - defensive
                    self._load_error = str(exc)

            mocked = self._mock_route(normalized)
            if mocked.get("unknown"):
                return mocked
            return mocked

    def _mock_route(self, normalized: str) -> dict[str, Any]:
        if normalized in MOCK_ROUTE_RESPONSES:
            return dict(MOCK_ROUTE_RESPONSES[normalized])
        for key, value in MOCK_ROUTE_RESPONSES.items():
            if key in normalized:
                return dict(value)
        return {"unknown": True}

    def plan_query(
        self,
        text: str,
        today: str,
        persons: list[str],
        perf: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """LLM-driven query planner.

        Returns one of: sql_query | note_query | clarify | unknown.
        Real backend is tried with a one-shot retry on JSON failure; on
        persistent failure we fall through to the mock dictionary so
        the orchestrator still has something deterministic to dispatch.
        """
        with perf_timer(perf, "llm_plan.total_ms"):
            normalized = re.sub(r"\s+", " ", text.strip().lower())
            try:
                anchor = datetime.strptime(today[:10], "%Y-%m-%d")
            except Exception:
                anchor = datetime.now()
            current_month = anchor.strftime("%Y-%m")
            prompt = QWEN_PLAN_PROMPT.format(
                text=text,
                today=today,
                current_month=current_month,
                persons=", ".join(sorted(persons)) or "(none)",
            )

            with perf_timer(perf, "llm_plan.backend_select_ms"):
                backend = self._ensure_backend_selected()
            if backend == "mock":
                return self._mock_plan(normalized)

            for attempt in range(2):
                try:
                    effective = (
                        prompt
                        if attempt == 0
                        else prompt + "\n\nReturn JSON only. No prose. No markdown."
                    )
                    with perf_timer(perf, f"llm_plan.generate_attempt_{attempt + 1}_ms"):
                        output = self._generate(effective, max_tokens=320)
                    result = json.loads(extract_json(output))
                    if _validate_plan_response(result):
                        self._load_error = None
                        return result
                except Exception as exc:  # pragma: no cover - defensive path
                    self._load_error = str(exc)

            return self._mock_plan(normalized)

    def _mock_plan(self, normalized: str) -> dict[str, Any]:
        if normalized in MOCK_PLAN_RESPONSES:
            return dict(MOCK_PLAN_RESPONSES[normalized])
        for key, value in MOCK_PLAN_RESPONSES.items():
            if key in normalized:
                return dict(value)
        note_query = extract_note_query_args(normalized)
        if note_query is not None:
            return {
                "action": "note_query",
                "query": str(note_query.get("query") or ""),
                "recent": bool(note_query.get("recent")),
                "limit": int(note_query.get("limit") or 5),
                "confidence": 0.9 if note_query.get("query") else 0.85,
            }
        last_expense_match = re.fullmatch(r"last\s+(\d+)\s+(?:expense|expenses|bill|bills)", normalized)
        if last_expense_match:
            limit = max(1, min(int(last_expense_match.group(1)), 100))
            return {
                "action": "sql_query",
                "sql": f"SELECT date, amount, description FROM expenses ORDER BY date DESC, id DESC LIMIT {limit}",
                "params": [],
                "intent": f"last {limit} expenses",
                "confidence": 0.9,
            }
        ledger_history_match = re.fullmatch(
            r"(?:show\s+ledger\s+for|ledger\s+history\s+for)\s+([a-zA-Z]+)",
            normalized,
        )
        if ledger_history_match:
            person = ledger_history_match.group(1).lower()
            return {
                "action": "sql_query",
                "sql": "SELECT date, direction, amount, note FROM ledger WHERE person=? ORDER BY date DESC, id DESC LIMIT 100",
                "params": [person],
                "intent": f"{person} ledger entries",
                "confidence": 0.9,
            }
        return {"action": "unknown"}

    def synthesize_notes(
        self,
        question: str,
        hits: list[dict[str, Any]],
        perf: dict[str, float] | None = None,
    ) -> tuple[str, str]:
        """Generate a faithful synthesized answer from retrieved note hits.

        On mock backend, returns a brief paraphrase-style header with the
        first hit; the orchestrator separately renders the full snippet
        list, so synthesis stays additive.
        """
        with perf_timer(perf, "llm_synth.total_ms"):
            with perf_timer(perf, "llm_synth.backend_select_ms"):
                backend = self._ensure_backend_selected()
            if not hits:
                return ("The notes do not contain enough to answer.", backend)

            if backend == "mock":
                best = hits[0]
                content = (best.get("content") or "").strip()
                snippet = content[:200]
                return (snippet, backend)

            context_lines = []
            for hit in hits:
                src = hit.get("source") or hit.get("domain") or "note"
                context_lines.append(f"[{src}] {hit.get('content', '')}")
            context = "\n".join(context_lines)
            prompt = QWEN_NOTE_SYNTH_PROMPT.format(
                question=question,
                context=context,
            )
            try:
                with perf_timer(perf, "llm_synth.generate_ms"):
                    response = self._generate(prompt, max_tokens=120).strip()
                self._load_error = None
                return (response, backend)
            except Exception as exc:  # pragma: no cover - defensive path
                self._load_error = str(exc)
                best = hits[0]
                return (
                    f"LLM unavailable. Best match: {(best.get('content') or '').strip()[:200]}",
                    "mock",
                )

    def summarize_rag(
        self,
        question: str,
        domain: str,
        hits: list[dict[str, Any]],
        perf: dict[str, float] | None = None,
    ) -> tuple[str, str]:
        with perf_timer(perf, "llm_summary.total_ms"):
            if not hits:
                with perf_timer(perf, "llm_summary.backend_select_ms"):
                    backend = self._ensure_backend_selected()
                return "No notes found in this domain.", backend

            with perf_timer(perf, "llm_summary.backend_select_ms"):
                backend = self._ensure_backend_selected()
            if backend == "mock":
                best = hits[0]
                lines = [f"Best match from {best['source'] or domain}: {best['content']}"]
                if len(hits) > 1:
                    extra = hits[1]
                    lines.append(f"Also relevant from {extra['source'] or domain}: {extra['content']}")
                return "\n\n".join(lines), backend

            context = "\n\n".join(
                f"[{hit['source'] or domain}] {hit['content']}" for hit in hits
            )
            prompt = QWEN_RAG_PROMPT.format(question=question, domain=domain, context=context)
            try:
                with perf_timer(perf, "llm_summary.generate_ms"):
                    response = self._generate(prompt, max_tokens=96).strip()
                self._load_error = None
                return response, backend
            except Exception as exc:  # pragma: no cover - defensive path
                self._load_error = str(exc)
                best = hits[0]
                return f"LLM unavailable. Best match from {best['source'] or domain}: {best['content']}", "mock"

    def _mock_parse(self, raw_note: str) -> dict[str, Any]:
        lowered = raw_note.lower()
        for key, response in MOCK_LLM_RESPONSES.items():
            if key in lowered:
                return dict(response)
        return {"type": "unknown", "content": raw_note}

    def _ensure_backend_selected(self) -> str:
        if self._backend:
            return self._backend
        with self._backend_lock:
            if self._backend:
                return self._backend

            # v1 default: skip real Qwen backends because 4B-Q4 inference on
            # CPU takes 30-60s per call, blowing the 5s response-time budget.
            # The mock dict + orchestrator legacy bridge cover all known
            # input patterns from dogfooding without LLM. Set
            # SECOND_BRAIN_USE_REAL_LLM=1 to opt in (e.g. for note
            # summarization once latency is acceptable on target hardware).
            if os.environ.get("SECOND_BRAIN_USE_REAL_LLM", "0").lower() not in {"1", "true", "yes"}:
                self._backend = "mock"
                self._load_error = "skipped_per_env_default"
                return self._backend

            try:
                from llama_cpp import Llama  # type: ignore

                if os.path.exists(self.model_path):
                    self._llama = Llama(
                        model_path=self.model_path,
                        n_ctx=2048,
                        n_threads=4,
                        verbose=False,
                    )
                    self._backend = "llama_cpp"
                    return self._backend
                self._load_error = f"Model file not found: {self.model_path}"
            except Exception as exc:
                self._load_error = str(exc)

            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
                import torch  # type: ignore

                self._tokenizer = AutoTokenizer.from_pretrained(self.transformers_model)
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.transformers_model,
                    torch_dtype="auto",
                    device_map="auto",
                )
                self._torch = torch
                self._backend = "transformers"
                return self._backend
            except Exception as exc:
                self._load_error = str(exc)

            self._backend = "mock"
            return self._backend

    def _generate(self, prompt: str, max_tokens: int) -> str:
        backend = self._ensure_backend_selected()
        if backend == "llama_cpp":
            output = self._llama(prompt, max_tokens=max_tokens, temperature=0.0, stop=["\n\n"])
            return output["choices"][0]["text"]
        if backend == "transformers":
            inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
            with self._torch.no_grad():
                output = self._model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=0.01,
                    do_sample=False,
                )
            return self._tokenizer.decode(
                output[0][inputs["input_ids"].shape[1] :],
                skip_special_tokens=True,
            )
        raise RuntimeError("No live LLM backend is available.")


class EmbeddingService:
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.model_name = model_name
        self.repo_id = (
            model_name
            if "/" in model_name
            else f"sentence-transformers/{model_name}"
        )
        self.cache_dir = os.path.join(APP_DIR, "models", "embedding_cache")
        self.model_dir = os.path.join(
            self.cache_dir,
            self.repo_id.replace("/", "--"),
        )
        self._model = None
        self._load_error: str | None = None
        self._model_lock = threading.Lock()

    def _has_local_weights(self) -> bool:
        return any(
            os.path.exists(os.path.join(self.model_dir, filename))
            for filename in ("model.safetensors", "pytorch_model.bin", "tf_model.h5")
        )

    def status(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "repo_id": self.repo_id,
            "cache_dir": self.cache_dir,
            "model_dir": self.model_dir,
            "available": self._model is not None or self._can_import(),
            "load_error": self._load_error,
        }

    def encode(
        self,
        text: str,
        perf: dict[str, float] | None = None,
        label: str = "embedding",
    ) -> list[float] | None:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    try:
                        with perf_timer(perf, f"{label}.model_load_ms"):
                            from sentence_transformers import SentenceTransformer  # type: ignore
                            from huggingface_hub import snapshot_download  # type: ignore

                            os.makedirs(self.cache_dir, exist_ok=True)
                            os.environ.setdefault("HF_HOME", self.cache_dir)
                            os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", self.cache_dir)
                            os.environ.setdefault("TRANSFORMERS_CACHE", self.cache_dir)
                            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                            if not self._has_local_weights():
                                snapshot_download(
                                    repo_id=self.repo_id,
                                    cache_dir=self.cache_dir,
                                    local_dir=self.model_dir,
                                    local_dir_use_symlinks=False,
                                )
                            self._model = SentenceTransformer(self.model_dir, local_files_only=True)
                    except Exception as exc:
                        self._load_error = str(exc)
                        return None
        with perf_timer(perf, f"{label}.encode_ms"):
            embedding = self._model.encode(text)
        return [float(value) for value in embedding]

    def _can_import(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401

            return True
        except Exception:
            return False


def _vector_to_blob(values: list[float]) -> bytes:
    packed = array("f", values)
    return packed.tobytes()


def _blob_to_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return [float(value) for value in values]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _json_dump(payload: dict[str, Any] | list[Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False)


def create_note_record(
    conn: sqlite3.Connection,
    content: str,
    input_kind: str,
    structured_type: str | None = None,
    note_domain: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO notes (content, input_kind, structured_type, note_domain, metadata_json, processed_at)
        VALUES (?,?,?,?,?,?)
        """,
        (
            content,
            input_kind,
            structured_type,
            note_domain,
            _json_dump(metadata),
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    )
    return int(cursor.lastrowid)


def create_capture_record(
    conn: sqlite3.Connection,
    raw_input: str,
    capture_type: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO captures (raw_input, capture_type, metadata_json)
        VALUES (?,?,?)
        """,
        (
            raw_input,
            capture_type,
            _json_dump(metadata),
        ),
    )
    return int(cursor.lastrowid)


def update_note_record(
    conn: sqlite3.Connection,
    note_id: int,
    *,
    structured_type: str | None = None,
    note_domain: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE notes
        SET structured_type = COALESCE(?, structured_type),
            note_domain = COALESCE(?, note_domain),
            metadata_json = COALESCE(?, metadata_json),
            processed_at = ?
        WHERE id = ?
        """,
        (
            structured_type,
            note_domain,
            _json_dump(metadata),
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            note_id,
        ),
    )


def create_pending_action(
    conn: sqlite3.Connection,
    action_type: str,
    note_id: int | None,
    prompt: str,
    options: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
) -> int:
    conn.execute("UPDATE pending_actions SET status = 'dismissed', resolved_at = ? WHERE status = 'pending'", (datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),))
    cursor = conn.execute(
        """
        INSERT INTO pending_actions (action_type, note_id, prompt, options_json, payload_json)
        VALUES (?,?,?,?,?)
        """,
        (
            action_type,
            note_id,
            prompt,
            _json_dump(options) or "[]",
            _json_dump(payload),
        ),
    )
    return int(cursor.lastrowid)


def latest_pending_action(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, action_type, note_id, prompt, options_json, payload_json, status, created_at
        FROM pending_actions
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()


def _normalize_entry(
    entry: dict[str, Any],
    raw_text: str,
    today: str,
    persons: set[str],
) -> dict[str, Any]:
    normalized = dict(entry)
    parsed_type = normalized.get("type", "unknown")
    normalized["raw"] = raw_text

    if parsed_type == "ledger":
        person = str(normalized.get("person", "")).strip().lower()
        normalized["person"] = person
        normalized["date"] = today
        normalized["unknown_person"] = person not in persons
        normalized["note"] = normalized.get("note")
    elif parsed_type == "expense":
        normalized["date"] = today
        normalized["month"] = get_month(today)
        normalized["description"] = str(normalized.get("description", "")).strip() or "misc"
    elif parsed_type == "weight":
        normalized["person"] = str(normalized.get("person", "")).strip().lower()
        normalized["date"] = today
        normalized["note"] = normalized.get("note")
    elif parsed_type == "todo":
        normalized["content"] = str(normalized.get("content", "")).strip() or raw_text
    elif parsed_type == "note":
        normalized["content"] = raw_text
        normalized["domain"] = normalized.get("domain") or infer_note_domain(raw_text)
    else:
        normalized["content"] = str(normalized.get("content", "")).strip() or raw_text
    return normalized


def _choose_final_entry(rule_entry: dict[str, Any], llm_entry: dict[str, Any]) -> dict[str, Any]:
    rule_type = rule_entry.get("type", "unknown")
    llm_type = llm_entry.get("type", "unknown")

    if llm_type == "unknown":
        return rule_entry
    if rule_type == "person_command":
        return rule_entry
    if rule_type in {"expense", "ledger", "weight"} and llm_type in {"todo", "note"}:
        return rule_entry
    if rule_type == "todo" and llm_type == "note":
        return llm_entry
    if rule_type == "note" and llm_type == "todo":
        return rule_entry
    if rule_type == "unknown":
        return llm_entry
    return llm_entry


def derive_note_entries(
    text: str,
    conn: sqlite3.Connection,
    llm_service: LLMService,
) -> tuple[list[dict[str, Any]], bool, dict[str, Any]]:
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    persons = load_known_persons(conn)
    recognized_people = persons | load_weight_persons(conn)
    rule_entries = parse_note_for_write(text, today=today, persons=recognized_people)
    if not rule_entries:
        return [], False, {}

    llm_used = False
    metadata: dict[str, Any] = {"rule_entries": rule_entries}

    if len(rule_entries) == 1 and rule_entries[0]["type"] != "person_command":
        rule_entry = _normalize_entry(rule_entries[0], text, today, recognized_people)
        llm_raw = llm_service.parse_note(text, today)
        llm_entry = _normalize_entry(llm_raw, text, today, recognized_people)
        llm_used = True
        metadata["llm_entry"] = llm_entry
        return [_choose_final_entry(rule_entry, llm_entry)], llm_used, metadata

    final_entries: list[dict[str, Any]] = []
    llm_entries: list[dict[str, Any]] = []
    for entry in rule_entries:
        normalized_rule = _normalize_entry(entry, entry.get("raw", text), today, recognized_people)
        if normalized_rule["type"] == "unknown":
            llm_used = True
            llm_raw = llm_service.parse_note(
                normalized_rule.get("content", normalized_rule["raw"]),
                today,
            )
            normalized_llm = _normalize_entry(
                llm_raw,
                normalized_rule["raw"],
                today,
                recognized_people,
            )
            llm_entries.append(normalized_llm)
            final_entries.append(_choose_final_entry(normalized_rule, normalized_llm))
        else:
            final_entries.append(normalized_rule)
    if llm_entries:
        metadata["llm_entries"] = llm_entries
    return final_entries, llm_used, metadata


def store_note_embedding(
    conn: sqlite3.Connection,
    embedding_service: EmbeddingService,
    note_id: int,
    content: str,
    domain: str,
    perf: dict[str, float] | None = None,
) -> dict[str, Any]:
    with perf_timer(perf, "note_index.total_ms"):
        if domain not in {"general", "investment", "health"}:
            return {"embedded": False, "reason": "unsupported_domain"}

        vector = embedding_service.encode(content, perf=perf, label="note_index")
        if vector is None:
            return {
                "embedded": False,
                "reason": embedding_service.status().get("load_error") or "embedding_unavailable",
            }

        with perf_timer(perf, "note_index.db_write_ms"):
            conn.execute("DELETE FROM embeddings WHERE source_note_id = ?", (note_id,))
            conn.execute(
                """
                INSERT INTO embeddings (domain, content, embedding, source, date, source_note_id)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    domain,
                    content,
                    _vector_to_blob(vector),
                    f"note:{note_id}",
                    datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    note_id,
                ),
            )
        return {"embedded": True, "domain": domain}


def build_query_or_command_plan(text: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    current_month = datetime.now().strftime("%Y-%m")
    lowered = text.lower().strip()
    persons = load_known_persons(conn)
    weight_people = load_weight_persons(conn)
    recognized_weight_people = persons | weight_people

    command = parse_person_command(text)
    if command:
        return {
            "kind": "person_command",
            "calls": [
                {
                    "name": "manage_persons",
                    "arguments": {
                        "operation": command["op"],
                        "name": command.get("name"),
                        "old_name": command.get("old_name"),
                        "new_name": command.get("new_name"),
                    },
                }
            ],
        }

    if "who owes" in lowered or "owes me" in lowered:
        return {
            "kind": "query",
            "calls": [{"name": "query_ledger", "arguments": {"query_type": "who_owes"}}],
        }

    if "who do i owe" in lowered or "whom do i owe" in lowered:
        return {
            "kind": "query",
            "calls": [{"name": "query_ledger", "arguments": {"query_type": "you_owe"}}],
        }

    ledger_names = {
        row["person"]
        for row in conn.execute("SELECT DISTINCT person FROM ledger_balance").fetchall()
    }
    if any(word in lowered for word in ["balance", "owe", "owes"]):
        for name in persons | ledger_names:
            if name in lowered:
                return {
                    "kind": "query",
                    "calls": [
                        {
                            "name": "query_ledger",
                            "arguments": {"query_type": "balance", "person": name},
                        }
                    ],
                }

    weight_query = extract_weight_query_args(text, recognized_weight_people)
    if weight_query:
        return {
            "kind": "query",
            "calls": [{"name": "get_weight", "arguments": weight_query}],
        }
    for name in recognized_weight_people:
        if name in lowered and "balance" not in lowered and len(text.split()) <= 3:
            return {
                "kind": "query",
                "calls": [{"name": "get_weight", "arguments": {"person": name, "limit": 1}}],
            }

    if any(word in lowered for word in ["spend", "spent", "expense", "spending"]):
        month = None
        for word, month_value in MONTH_MAP.items():
            if word in lowered:
                month = month_value
                break
        if not month and any(word in lowered for word in ["this month", "monthly", "current month"]):
            month = current_month

        description_like = None
        for keyword in EXPENSE_LIKE_KEYWORDS:
            if keyword in lowered:
                description_like = keyword
                break

        list_mode = "list" in lowered or "one by one" in lowered or (
            lowered.startswith(("show ", "list ")) and "expense" in lowered
        )
        return {
            "kind": "query",
            "calls": [
                {
                    "name": "query_expense",
                    "arguments": {
                        "month": month,
                        "description_like": description_like,
                        "list_mode": list_mode,
                        "limit": 12,
                    },
                }
            ],
        }

    if any(
        word in lowered
        for word in ["todo", "task", "pending", "tasks", "done", "cleared", "completed", "finished"]
    ):
        status = "done" if any(
            word in lowered for word in ["done", "cleared", "completed", "finished"]
        ) else "pending"
        return {
            "kind": "query",
            "calls": [{"name": "get_todos", "arguments": {"status": status, "limit": 20}}],
        }

    note_query = extract_note_query_args(text)
    if note_query:
        return {
            "kind": "query",
            "calls": [{"name": "query_notes", "arguments": {"limit": int(note_query.get("limit") or 10), **note_query}}],
        }

    return None


def prepare_ledger_settlement_result(
    conn: sqlite3.Connection,
    note_id: int | None,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT person, ABS(balance) AS amount
        FROM ledger_balance
        WHERE balance < 0
        ORDER BY ABS(balance) DESC, person
        """
    ).fetchall()
    if not rows:
        return {
            "kind": "unknown",
            "response_text": "I couldn't find anyone you currently owe money to.",
            "options": [],
        }

    options = [
        {
            "number": index,
            "person": row["person"],
            "amount": float(row["amount"]),
        }
        for index, row in enumerate(rows, start=1)
    ]
    lines = ["Which balance did you settle? Reply with the number:"]
    for option in options:
        lines.append(
            f"{option['number']}. {option['person'].title()} - {format_rupees(option['amount'])}"
        )
    prompt = "\n".join(lines)
    action_id = create_pending_action(
        conn,
        "ledger_settlement",
        note_id,
        prompt,
        options,
        {"mode": "you_owe"},
    )
    return {
        "kind": "clarification",
        "response_text": prompt,
        "pending_action_id": action_id,
        "options": options,
    }


def resolve_pending_action_result(
    conn: sqlite3.Connection,
    selection_text: str,
    note_id: int,
) -> dict[str, Any] | None:
    pending = latest_pending_action(conn)
    if not pending:
        return None

    lowered = selection_text.lower().strip()
    if lowered in {"cancel", "none", "skip"}:
        conn.execute(
            "UPDATE pending_actions SET status = 'dismissed', resolved_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), pending["id"]),
        )
        update_note_record(
            conn,
            note_id,
            structured_type="resolution",
            metadata={"pending_action_id": pending["id"], "status": "dismissed"},
        )
        return {
            "kind": "unknown",
            "response_text": "Okay, I left that unresolved.",
        }

    match = re.fullmatch(r"#?\s*(\d+)", lowered)
    if not match:
        return None

    options = json.loads(pending["options_json"])
    index = int(match.group(1)) - 1
    if index < 0 or index >= len(options):
        return {
            "kind": "clarification",
            "response_text": f"Choose a number between 1 and {len(options)}.",
            "pending_action_id": pending["id"],
            "options": options,
        }

    choice = options[index]
    if pending["action_type"] != "ledger_settlement":
        return {
            "kind": "unknown",
            "response_text": f"Unsupported pending action: {pending['action_type']}",
        }

    result = add_entry_result(
        conn,
        {
            "type": "ledger",
            "person": choice["person"],
            "amount": choice["amount"],
            "direction": "gave",
            "date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "settled from pending selection",
            "raw": selection_text,
            "source_note_id": note_id,
            "unknown_person": False,
        },
    )
    conn.execute(
        "UPDATE pending_actions SET status = 'resolved', resolved_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), pending["id"]),
    )
    update_note_record(
        conn,
        note_id,
        structured_type="ledger",
        metadata={
            "pending_action_id": pending["id"],
            "selected_option": choice,
            "resolved": True,
        },
    )
    return {
        "kind": "write",
        "response_text": result["response_text"],
        "resolved_option": choice,
    }


def capture_note_result(
    conn: sqlite3.Connection,
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    text: str,
    note_id: int,
) -> dict[str, Any]:
    if looks_like_settlement_followup(text):
        result = prepare_ledger_settlement_result(conn, note_id)
        update_note_record(
            conn,
            note_id,
            structured_type="ledger",
            metadata={"status": "awaiting_resolution", "text": text},
        )
        return result

    entries, llm_used, parse_metadata = derive_note_entries(text, conn, llm_service)
    if not entries:
        update_note_record(
            conn,
            note_id,
            structured_type="unknown",
            metadata={"llm_used": llm_used, "parse_metadata": parse_metadata},
        )
        return {"kind": "unknown", "response_text": "I saved the note, but couldn't process it yet."}

    responses: list[str] = []
    entry_types: list[str] = []
    note_domain: str | None = None
    embedding_status: dict[str, Any] | None = None

    for entry in entries:
        entry["source_note_id"] = note_id
        parsed_type = entry["type"]
        entry_types.append(parsed_type)

        if parsed_type == "unknown":
            note_domain = infer_note_domain(text)
            embedding_status = store_note_embedding(conn, embedding_service, note_id, text, note_domain)
            responses.append("Note saved")
            continue

        if parsed_type == "note":
            note_domain = entry.get("domain") or infer_note_domain(text)
            embedding_status = store_note_embedding(conn, embedding_service, note_id, text, note_domain)
            if note_domain == "general":
                responses.append("Note saved")
            else:
                responses.append(f"{note_domain.title()} note saved")
            continue

        result = add_entry_result(conn, entry)
        responses.append(result["response_text"])

    structured_type = entry_types[0] if len(set(entry_types)) == 1 else "multi"
    update_note_record(
        conn,
        note_id,
        structured_type=structured_type,
        note_domain=note_domain,
        metadata={
            "llm_used": llm_used,
            "parse_metadata": parse_metadata,
            "entries": entries,
            "embedding_status": embedding_status,
        },
    )
    response_text = " · ".join(dict.fromkeys(responses)) or "Note saved"
    return {
        "kind": "write",
        "response_text": response_text,
        "note_id": note_id,
        "entries": entries,
        "llm_used": llm_used,
    }


def _run_planned_call(
    conn: sqlite3.Connection,
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    call: dict[str, Any],
) -> dict[str, Any]:
    name = call["name"]
    arguments = call.get("arguments", {})
    if name == "manage_persons":
        return manage_persons_result(conn, **arguments)
    if name == "query_ledger":
        return query_ledger_result(conn, **arguments)
    if name == "query_expense":
        return query_expense_result(conn, **arguments)
    if name == "get_todos":
        return get_todos_result(conn, **arguments)
    if name == "get_weight":
        return get_weight_result(conn, **arguments)
    if name == "query_notes":
        return query_notes_result(conn, llm_service, embedding_service, **arguments)
    if name == "search_notes":
        return search_notes_result(conn, llm_service, embedding_service, **arguments)
    raise ValueError(f"Unsupported planned tool call: {name}")


def handle_input_result(
    conn: sqlite3.Connection,
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    text: str,
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {"kind": "unknown", "response_text": "No input provided."}

    pending = latest_pending_action(conn)
    lowered = text.lower()
    if pending and (re.fullmatch(r"#?\s*\d+", lowered) or lowered in {"cancel", "none", "skip"}):
        resolution_note_id = create_note_record(
            conn,
            text,
            input_kind="resolution_reply",
            metadata={"pending_action_id": pending["id"]},
        )
        resolution = resolve_pending_action_result(conn, text, resolution_note_id)
        if resolution is not None:
            resolution["note_id"] = resolution_note_id
            return resolution

    plan = build_query_or_command_plan(text, conn)
    if plan:
        note_id = create_note_record(
            conn,
            text,
            input_kind=plan["kind"],
            structured_type=plan["kind"],
            metadata={"plan": plan},
        )
        results = [
            _run_planned_call(conn, llm_service, embedding_service, call)
            for call in plan["calls"]
        ]
        response_text = " · ".join(
            result.get("response_text", "") for result in results if result.get("response_text")
        ) or "No response"
        update_note_record(
            conn,
            note_id,
            structured_type=plan["kind"],
            metadata={"plan": plan, "results": results},
        )
        return {
            "kind": plan["kind"],
            "response_text": response_text,
            "note_id": note_id,
            "results": results,
        }

    note_id = create_note_record(conn, text, input_kind="note")
    return capture_note_result(conn, llm_service, embedding_service, text, note_id)


def route_input_plan(
    text: str,
    conn: sqlite3.Connection,
    llm_service: LLMService,
) -> dict[str, Any]:
    pending = latest_pending_action(conn)
    stripped = text.strip()
    if pending and (
        re.fullmatch(r"#?\s*\d+", stripped.lower())
        or stripped.lower() in {"cancel", "none", "skip"}
    ):
        return {
            "kind": "write",
            "calls": [{"name": "resolve_pending_action", "arguments": {"selection_text": text}}],
            "response_text": None,
        }

    plan = build_query_or_command_plan(text, conn)
    if plan:
        plan["response_text"] = None
        return plan

    if looks_like_settlement_followup(text):
        return {
            "kind": "write",
            "calls": [{"name": "prepare_ledger_settlement", "arguments": {"text": text}}],
            "response_text": None,
        }

    return {
        "kind": "write",
        "calls": [{"name": "capture_note", "arguments": {"text": text}}],
        "response_text": None,
    }


def add_entry_result(conn: sqlite3.Connection, entry: dict[str, Any]) -> dict[str, Any]:
    parsed_type = entry["type"]
    cursor = conn.cursor()

    if parsed_type == "expense":
        cursor.execute(
            """
            INSERT INTO expenses (amount, description, date, month, raw_note, source_note_id, source_capture_id, group_name)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                entry["amount"],
                entry["description"],
                entry["date"],
                entry["month"],
                entry["raw"],
                entry.get("source_note_id"),
                entry.get("source_capture_id"),
                entry.get("group_name"),
            ),
        )
        return {
            "entry_type": "expense",
            "response_text": f"{format_rupees(entry['amount'])} {entry['description']} logged",
        }

    if parsed_type == "ledger":
        cursor.execute(
            "INSERT INTO ledger (person, amount, direction, date, note, source_note_id, source_capture_id) VALUES (?,?,?,?,?,?,?)",
            (
                entry["person"],
                entry["amount"],
                entry["direction"],
                entry["date"],
                entry.get("note"),
                entry.get("source_note_id"),
                entry.get("source_capture_id"),
            ),
        )
        verb = "Gave" if entry["direction"] == "gave" else "Received from"
        response = f"{verb} {entry['person'].title()} {format_rupees(entry['amount'])} logged"
        if entry.get("unknown_person"):
            response += f" - tip: add {entry['person'].title()} via the People screen"
        return {"entry_type": "ledger", "response_text": response}

    if parsed_type == "weight":
        conn.execute("INSERT OR IGNORE INTO persons (name) VALUES (?)", (entry["person"],))
        cursor.execute(
            "INSERT INTO weights (person, weight, date, note, source_note_id, source_capture_id) VALUES (?,?,?,?,?,?)",
            (
                entry["person"],
                entry["weight"],
                entry["date"],
                entry.get("note"),
                entry.get("source_note_id"),
                entry.get("source_capture_id"),
            ),
        )
        return {
            "entry_type": "weight",
            "response_text": f"{entry['person'].title()} weight: {entry['weight']}kg logged",
        }

    if parsed_type == "todo":
        cursor.execute(
            "INSERT INTO todos (content, date, source_note_id, source_capture_id) VALUES (?,?,?,?)",
            (
                entry["content"],
                entry.get("date"),
                entry.get("source_note_id"),
                entry.get("source_capture_id"),
            ),
        )
        return {
            "entry_type": "todo",
            "response_text": f"Todo added: {entry['content']}",
        }

    if parsed_type == "buy":
        cursor.execute(
            """
            INSERT INTO buy_items (
                item_text, quantity_text, unit_text, date, status, raw_note, source_note_id, source_capture_id
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                entry["item_text"],
                entry.get("quantity_text"),
                entry.get("unit_text"),
                entry.get("date"),
                entry.get("status") or "open",
                entry.get("raw"),
                entry.get("source_note_id"),
                entry.get("source_capture_id"),
            ),
        )
        quantity_text = str(entry.get("quantity_text") or "").strip()
        unit_text = str(entry.get("unit_text") or "").strip()
        suffix = ""
        if quantity_text and unit_text:
            suffix = f" ({quantity_text} {unit_text})"
        elif quantity_text:
            suffix = f" ({quantity_text})"
        return {
            "entry_type": "buy",
            "response_text": f"Buy item added: {entry['item_text']}{suffix}",
        }

    raise ValueError(f"Unsupported entry type: {parsed_type}")


def manage_persons_result(
    conn: sqlite3.Connection,
    operation: str,
    name: str | None = None,
    old_name: str | None = None,
    new_name: str | None = None,
) -> dict[str, Any]:
    cursor = conn.cursor()

    if operation == "ADD_PERSON":
        if not name:
            return {"response_text": "ADD_PERSON requires a name", "is_error": True}
        try:
            cursor.execute("INSERT INTO persons (name) VALUES (?)", (name,))
            return {"response_text": f"Added '{name}' to people"}
        except sqlite3.IntegrityError as exc:
            return {"response_text": f"Unable to add '{name}': {exc}", "is_error": True}

    if operation == "REMOVE_PERSON":
        if not name:
            return {"response_text": "REMOVE_PERSON requires a name", "is_error": True}
        cursor.execute("DELETE FROM persons WHERE name = ?", (name,))
        if cursor.rowcount:
            return {"response_text": f"Removed '{name}'"}
        return {"response_text": f"'{name}' not found", "is_error": True}

    if operation == "MODIFY_PERSON":
        if not old_name or not new_name:
            return {"response_text": "MODIFY_PERSON requires old_name and new_name", "is_error": True}
        try:
            cursor.execute("UPDATE persons SET name = ? WHERE name = ?", (new_name, old_name))
            if not cursor.rowcount:
                return {"response_text": f"'{old_name}' not found", "is_error": True}
            cursor.execute("UPDATE ledger SET person = ? WHERE person = ?", (new_name, old_name))
            cursor.execute("UPDATE weights SET person = ? WHERE person = ?", (new_name, old_name))
            return {"response_text": f"Renamed '{old_name}' -> '{new_name}' (ledger + weights updated)"}
        except sqlite3.IntegrityError as exc:
            return {"response_text": f"Unable to rename '{old_name}': {exc}", "is_error": True}

    return {"response_text": f"Unknown operation: {operation}", "is_error": True}


def query_ledger_result(
    conn: sqlite3.Connection,
    query_type: str = "balance",
    person: str | None = None,
) -> dict[str, Any]:
    cursor = conn.cursor()
    if query_type == "who_owes":
        rows = cursor.execute(
            "SELECT person, balance FROM ledger_balance WHERE balance > 0 ORDER BY balance DESC"
        ).fetchall()
        if not rows:
            return {"response_text": "Nobody owes you money", "rows": []}
        response = ", ".join(
            f"{row['person'].title()}: {format_rupees(row['balance'])}" for row in rows
        )
        return {"response_text": response, "rows": [dict(row) for row in rows]}

    if query_type == "you_owe":
        rows = cursor.execute(
            """
            SELECT person, ABS(balance) AS balance
            FROM ledger_balance
            WHERE balance < 0
            ORDER BY ABS(balance) DESC
            """
        ).fetchall()
        if not rows:
            return {"response_text": "You do not currently owe anyone money", "rows": []}
        response = ", ".join(
            f"{row['person'].title()}: {format_rupees(row['balance'])}" for row in rows
        )
        return {"response_text": response, "rows": [dict(row) for row in rows]}

    if query_type == "balance" and person:
        row = cursor.execute(
            "SELECT balance FROM ledger_balance WHERE person = ?",
            (person.lower(),),
        ).fetchone()
        if not row:
            return {"response_text": f"No ledger entries for {person.title()}"}
        balance = row["balance"]
        if balance > 0:
            response = f"{person.title()} owes you {format_rupees(balance)}"
        elif balance < 0:
            response = f"You owe {person.title()} {format_rupees(abs(balance))}"
        else:
            response = f"{person.title()} - settled"
        return {"response_text": response, "balance": balance}

    return {"response_text": f"Unsupported ledger query type: {query_type}", "is_error": True}


def query_expense_result(
    conn: sqlite3.Connection,
    month: str | None = None,
    description_like: str | None = None,
    list_mode: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if month:
        where.append("month = ?")
        params.append(month)
    if description_like:
        where.append("description LIKE ?")
        params.append(f"%{description_like}%")

    where_sql = f" WHERE {' AND '.join(where)}" if where else ""

    if list_mode:
        rows = conn.execute(
            f"SELECT amount, description, date FROM expenses{where_sql} ORDER BY date DESC, id DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
        if not rows:
            return {"response_text": "No expense entries matched that filter.", "rows": []}
        lines = [
            f"{row['date'][:10]} - {format_rupees(row['amount'])} - {row['description']}"
            for row in rows
        ]
        total = sum(row["amount"] for row in rows)
        header_parts = []
        if month:
            header_parts.append(month)
        if description_like:
            header_parts.append(description_like)
        header = " / ".join(header_parts) or "all time"
        response = f"Expense list ({header}):\n" + "\n".join(lines) + f"\nTotal shown: {format_rupees(total)}"
        return {"response_text": response, "rows": [dict(row) for row in rows], "total_shown": total}

    row = conn.execute(
        f"SELECT SUM(amount) AS total FROM expenses{where_sql}",
        params,
    ).fetchone()
    total = row["total"] if row and row["total"] else 0
    labels = []
    if month:
        labels.append(month)
    if description_like:
        labels.append(f"~{description_like}")
    label = " · ".join(labels) or "all time"
    return {"response_text": f"Total spend ({label}): {format_rupees(total)}", "total": total}


def get_todos_result(
    conn: sqlite3.Connection,
    status: str = "pending",
    limit: int = 20,
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT content, status, created_at FROM todos WHERE status = ? ORDER BY id DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    if not rows:
        return {"response_text": f"No {status} todos", "rows": []}
    label = "Done" if status == "done" else "Pending"
    response = f"{label} todos: " + " · ".join(f"• {row['content']}" for row in rows)
    return {"response_text": response, "rows": [dict(row) for row in rows]}


def get_weight_result(
    conn: sqlite3.Connection,
    person: str,
    limit: int = 1,
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT weight, date, note FROM weights WHERE person = ? ORDER BY date DESC LIMIT ?",
        (person.lower(), limit),
    ).fetchall()
    if not rows:
        return {"response_text": f"No weight data for {person.title()}", "rows": []}
    if limit == 1:
        row = rows[0]
        note = f" ({row['note']})" if row["note"] else ""
        response = f"{person.title()} weight: {row['weight']}kg on {row['date'][:10]}{note}"
        return {"response_text": response, "rows": [dict(row)]}
    response = " · ".join(f"{row['date'][:10]}: {row['weight']}kg" for row in rows)
    return {"response_text": response, "rows": [dict(row) for row in rows]}


def _normalize_note_search_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


def _note_search_tokens(text: str) -> list[str]:
    normalized = _normalize_note_search_text(text)
    if not normalized:
        return []
    return [
        token
        for token in normalized.split()
        if token not in NOTE_QUERY_STOPWORDS and (len(token) >= 3 or any(ch.isdigit() for ch in token))
    ]


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    normalized = _normalize_note_search_text(text)
    if not normalized:
        return set()
    if len(normalized) <= n:
        return {normalized}
    return {normalized[index:index + n] for index in range(len(normalized) - n + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _best_fuzzy_token_ratio(query_token: str, content_tokens: list[str]) -> float:
    best = 0.0
    for candidate in content_tokens:
        if query_token == candidate:
            return 1.0
        if abs(len(query_token) - len(candidate)) > 4:
            continue
        ratio = SequenceMatcher(None, query_token, candidate).ratio()
        if ratio > best:
            best = ratio
    return best


def _note_lexical_metrics(query: str, content: str) -> dict[str, Any]:
    normalized_query = _normalize_note_search_text(query)
    normalized_content = _normalize_note_search_text(content)
    query_tokens = _note_search_tokens(query)
    content_tokens = _note_search_tokens(content)
    content_token_set = set(content_tokens)

    phrase_hit = bool(normalized_query and normalized_query in normalized_content)
    exact_hits = sum(1 for token in query_tokens if token in content_token_set)
    exact_recall = (exact_hits / len(query_tokens)) if query_tokens else 0.0

    fuzzy_scores = []
    for token in query_tokens:
        fuzzy_scores.append(_best_fuzzy_token_ratio(token, content_tokens))
    fuzzy_recall = (sum(fuzzy_scores) / len(fuzzy_scores)) if fuzzy_scores else 0.0

    trigram_overlap = _jaccard(_char_ngrams(normalized_query), _char_ngrams(normalized_content))

    lexical_score = 0.0
    if phrase_hit:
        lexical_score += 0.55
    lexical_score += 0.20 * exact_recall
    lexical_score += 0.20 * fuzzy_recall
    lexical_score += 0.05 * trigram_overlap
    lexical_score = min(1.0, lexical_score)

    return {
        "normalized_query": normalized_query,
        "normalized_content": normalized_content,
        "query_tokens": query_tokens,
        "content_tokens": content_tokens,
        "phrase_hit": phrase_hit,
        "exact_hits": exact_hits,
        "exact_recall": exact_recall,
        "fuzzy_recall": fuzzy_recall,
        "trigram_overlap": trigram_overlap,
        "lexical_score": lexical_score,
    }


def _combine_note_scores(lexical_score: float, semantic_score: float) -> float:
    if lexical_score >= 0.45:
        return min(1.0, (0.78 * lexical_score) + (0.22 * max(0.0, semantic_score)))
    if lexical_score >= 0.20:
        return min(1.0, (0.65 * lexical_score) + (0.35 * max(0.0, semantic_score)))
    return min(1.0, (0.15 * lexical_score) + (0.85 * max(0.0, semantic_score)))


def _is_confident_note_match(hit: dict[str, Any]) -> bool:
    lexical_score = float(hit.get("lexical_score") or 0.0)
    semantic_score = float(hit.get("semantic_score") or 0.0)
    combined_score = float(hit.get("score") or 0.0)
    phrase_hit = bool(hit.get("phrase_hit"))
    exact_hits = int(hit.get("exact_hits") or 0)
    fuzzy_recall = float(hit.get("fuzzy_recall") or 0.0)
    query_tokens = list(hit.get("query_tokens") or [])
    anchor_tokens = [token for token in query_tokens if len(token) >= 4]

    if phrase_hit and (exact_hits > 0 or len(query_tokens) <= 3):
        return True
    if anchor_tokens and exact_hits > 0 and combined_score >= 0.24:
        return True
    if anchor_tokens and fuzzy_recall >= 0.90 and combined_score >= 0.28:
        return True
    if lexical_score >= 0.30 and combined_score >= 0.34:
        return True
    if lexical_score >= 0.12 and semantic_score >= 0.82 and combined_score >= 0.50:
        return True
    return False


def query_notes_result(
    conn: sqlite3.Connection,
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    query: str = "",
    domain: str | None = None,
    recent: bool = False,
    limit: int = 5,
    date_start: str | None = None,
    date_end: str | None = None,
    perf: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Cross-domain note search wrapper.

    When `recent=True` (or `query` is empty) returns the latest user-saved
    notes by created_at, no embedding required.
    Otherwise it runs a hybrid lexical + semantic ranking across real user
    notes and abstains when evidence is weak instead of forcing a best match.
    """
    with perf_timer(perf, "query_notes.total_ms"):
        date_filters = []
        date_params: list[Any] = []
        date_expr = "COALESCE(substr(n.processed_at, 1, 10), substr(n.created_at, 1, 10))"
        recent_date_expr = "COALESCE(substr(processed_at, 1, 10), substr(created_at, 1, 10))"
        if date_start:
            date_filters.append(f"{recent_date_expr} >= ?")
            date_params.append(date_start)
        if date_end:
            date_filters.append(f"{recent_date_expr} <= ?")
            date_params.append(date_end)
        date_sql = f" AND {' AND '.join(date_filters)}" if date_filters else ""
        if recent or not (query or "").strip():
            with perf_timer(perf, "query_notes.recent_sql_ms"):
                rows = conn.execute(
                    """
                    SELECT id, content, structured_type, note_domain, created_at
                    FROM notes
                    WHERE structured_type = 'note'
                      AND content IS NOT NULL
                      AND content <> ''
                    """ + date_sql + """
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (*date_params, max(1, int(limit or 5))),
                ).fetchall()
            if not rows:
                return {"response_text": "No saved notes yet.", "rows": []}
            lines = [f"note:{row['id']}: {row['content']}" for row in rows]
            return {
                "response_text": " · ".join(lines),
                "rows": [dict(row) for row in rows],
            }

        where = ["n.structured_type = 'note'", "n.content IS NOT NULL", "n.content <> ''"]
        params: list[Any] = []
        if domain:
            where.append("COALESCE(n.note_domain, e.domain, 'general') = ?")
            params.append(domain)
        if date_start:
            where.append(f"{date_expr} >= ?")
            params.append(date_start)
        if date_end:
            where.append(f"{date_expr} <= ?")
            params.append(date_end)
        with perf_timer(perf, "query_notes.embeddings_sql_ms"):
            rows = conn.execute(
                f"""
                SELECT
                    n.id,
                    n.content,
                    n.note_domain,
                    n.created_at,
                    e.embedding,
                    e.source,
                    e.domain AS embedding_domain
                FROM notes n
                LEFT JOIN embeddings e ON e.source_note_id = n.id
                WHERE {' AND '.join(where)}
                ORDER BY n.id DESC
                """,
                params,
            ).fetchall()
        if not rows:
            return {
                "response_text": "No saved notes yet.",
                "hits": [],
                "llm_backend": llm_backend_name(llm_service),
            }

        query_vector = embedding_service.encode(query, perf=perf, label="query_notes.query_embedding")

        hits = []
        with perf_timer(perf, "query_notes.cosine_ms"):
            for row in rows:
                lexical = _note_lexical_metrics(query, row["content"])
                semantic_score = 0.0
                if query_vector is not None and row["embedding"]:
                    try:
                        stored_vector = _blob_to_vector(row["embedding"])
                        semantic_score = cosine_similarity(query_vector, stored_vector)
                    except Exception:
                        semantic_score = 0.0
                combined_score = _combine_note_scores(lexical["lexical_score"], semantic_score)
                hits.append(
                    {
                        "score": combined_score,
                        "semantic_score": semantic_score,
                        "lexical_score": lexical["lexical_score"],
                        "phrase_hit": lexical["phrase_hit"],
                        "exact_hits": lexical["exact_hits"],
                        "exact_recall": lexical["exact_recall"],
                        "fuzzy_recall": lexical["fuzzy_recall"],
                        "trigram_overlap": lexical["trigram_overlap"],
                        "query_tokens": lexical["query_tokens"],
                        "content": row["content"],
                        "source": row["source"] or f"note:{row['id']}",
                        "domain": row["note_domain"] or row["embedding_domain"] or "general",
                        "note_id": row["id"],
                        "created_at": row["created_at"],
                    }
                )
        hits.sort(
            key=lambda item: (
                item["score"],
                item["lexical_score"],
                item["semantic_score"],
                item["note_id"],
            ),
            reverse=True,
        )
        top_hits = hits[: max(1, int(limit or 3))]

        confident_hits = [hit for hit in top_hits if _is_confident_note_match(hit)]
        if not confident_hits:
            return {
                "response_text": f"No notes matched '{query}'.",
                "hits": top_hits,
                "llm_backend": llm_backend_name(llm_service),
            }

        display_hits = confident_hits[: max(1, int(limit or 3))]

        if any(hit["domain"] in {"investment", "health"} for hit in display_hits):
            with perf_timer(perf, "query_notes.summarize_ms"):
                summary, backend = llm_service.summarize_rag(query, display_hits[0]["domain"], display_hits, perf=perf)
            return {"response_text": summary, "hits": display_hits, "llm_backend": backend}

        # Faithful synthesis path for the general note pool.
        # Threshold gates synthesis so we don't fabricate when nothing matched.
        snippet_lines = []
        for hit in display_hits:
            label = hit["source"] or hit["domain"] or "note"
            snippet_lines.append(f"{label}: {hit['content']}")
        snippets_block = "\n".join(snippet_lines)

        with perf_timer(perf, "query_notes.synth_ms"):
            synth, backend = llm_service.synthesize_notes(query, display_hits, perf=perf)
        response_text = synth.strip()
        if snippets_block and snippets_block not in response_text:
            response_text = f"{response_text}\n\nSources:\n{snippets_block}"
        return {
            "response_text": response_text,
            "hits": display_hits,
            "synth_used": True,
            "llm_backend": backend,
        }


def search_notes_result(
    conn: sqlite3.Connection,
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    query: str,
    domain: str,
    top_k: int = 3,
    perf: dict[str, float] | None = None,
) -> dict[str, Any]:
    with perf_timer(perf, "search_notes.total_ms"):
        with perf_timer(perf, "search_notes.embeddings_sql_ms"):
            rows = conn.execute(
                "SELECT content, embedding, source FROM embeddings WHERE domain = ?",
                (domain,),
            ).fetchall()
        if not rows:
            return {
                "response_text": f"No indexed {domain} notes yet.",
                "hits": [],
                "llm_backend": llm_backend_name(llm_service),
            }

        query_vector = embedding_service.encode(query, perf=perf, label="search_notes.query_embedding")
        if query_vector is None:
            return {
                "response_text": f"RAG unavailable: {embedding_service.status()['load_error']}",
                "hits": [],
                "llm_backend": llm_backend_name(llm_service),
            }

        hits = []
        with perf_timer(perf, "search_notes.cosine_ms"):
            for row in rows:
                stored_vector = _blob_to_vector(row["embedding"])
                hits.append(
                    {
                        "score": cosine_similarity(query_vector, stored_vector),
                        "content": row["content"],
                        "source": row["source"],
                    }
                )
        hits.sort(key=lambda item: item["score"], reverse=True)
        top_hits = hits[:top_k]
        if domain == "general":
            lines = []
            for hit in top_hits:
                label = hit["source"] or "note"
                lines.append(f"{label}: {hit['content']}")
            return {
                "response_text": "\n".join(lines),
                "hits": top_hits,
                "llm_backend": llm_backend_name(llm_service),
            }
        with perf_timer(perf, "search_notes.summarize_ms"):
            summary, backend = llm_service.summarize_rag(query, domain, top_hits, perf=perf)
        return {
            "response_text": summary,
            "hits": top_hits,
            "llm_backend": backend,
        }


def query_sql_result(
    conn: sqlite3.Connection,
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    intent: str | None = None,
    perf: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run LLM-generated SQL through the safety gate against a read-only conn.

    `conn` is provided so we share the existing handle for tests, but the
    safety layer also opens its own ro connection when given a db_path.
    """
    from sql_safety import (  # local import to keep top-level deps minimal
        SqlSafetyError,
        execute_safe,
        format_rows,
    )

    with perf_timer(perf, "query_sql.total_ms"):
        try:
            with perf_timer(perf, "query_sql.execute_ms"):
                result = execute_safe(sql, params=params, conn=conn)
        except SqlSafetyError as exc:
            return {
                "response_text": f"Query rejected: {exc}",
                "is_error": True,
                "rows": [],
                "sql": sql,
                "params": list(params or []),
                "intent": intent,
            }

        text = format_rows(result)
        prefix = ""
        if intent:
            prefix = f"{intent}\n"
        return {
            "response_text": prefix + text,
            "rows": [dict(row) for row in result.rows],
            "column_names": result.column_names,
            "truncated": result.truncated,
            "tables": sorted(result.tables),
            "sql": sql,
            "params": list(params or []),
            "intent": intent,
        }
