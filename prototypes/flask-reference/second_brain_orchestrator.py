"""Two-tier intent orchestrator for Second Brain.

Routes every user input through:
  0. Pending-action pre-check  — numbered replies to a clarify menu
  1. Tier 0 deterministic grammar
  2. user_routing_memory lookup (memoized clarify resolutions)
  3. Tier 1 Qwen function-calling (LLM picks a tool / clarify / unknown)
  4. Heuristic clarify fallback (if LLM JSON keeps failing)

The orchestrator is the only place routing decisions are made. MCP tools
stay atomic; tools never call other tools; UI surfaces never route.

Design invariant: never lose user input. Every input ends as a saved row,
a saved-as-note, or a pending clarify — never an error.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from second_brain_finetuned_parser import (
    detect_tagged_lane,
    finetuned_parser_enabled,
    get_finetuned_parser_service,
    should_use_followup_context,
    warm_finetuned_parser,
)
from second_brain_core import (
    DEFAULT_DB_PATH,
    EmbeddingService,
    LLMService,
    TODO_START_VERBS,
    add_entry_result,
    build_query_or_command_plan,
    clear_runtime_state,
    create_capture_record,
    create_note_record,
    create_pending_action,
    db_connection,
    extract_explicit_note_body,
    extract_note_query_args,
    extract_explicit_todo_body,
    extract_weight_query_args,
    format_rupees,
    get_month,
    get_todos_result,
    get_weight_result,
    infer_note_domain,
    latest_pending_action,
    load_runtime_state,
    load_known_persons,
    load_weight_persons,
    lookup_routing_memory,
    looks_like_settlement_followup,
    manage_persons_result,
    parse_note_for_write,
    parse_person_command,
    perf_timer,
    prepare_ledger_settlement_result,
    query_expense_result,
    query_ledger_result,
    query_notes_result,
    query_sql_result,
    resolve_pending_action_result,
    resolve_plan_relative_dates,
    search_notes_result,
    split_todo_items,
    store_runtime_state,
    store_note_embedding,
    update_note_record,
    upsert_routing_memory,
)
from synthetic_dataset_assets import GLOBAL_EXPENSE, INDIA_EXPENSE


# ---------------------------------------------------------------------------
# Tier 0 patterns (unchanged from step 1)
# ---------------------------------------------------------------------------

TODO_COLON_RE = re.compile(r"^\s*(?:todo|task)\s*:\s*(.+)$", re.IGNORECASE)
TODO_VERB_RE = re.compile(r"^\s*todo\s+([a-zA-Z]+)(.*)$", re.IGNORECASE)
REMIND_ME_RE = re.compile(r"^\s*remind\s+me\s+(?:to\s+)?(.+)$", re.IGNORECASE)
WEIGHT_WRITE_RE = re.compile(
    r"^\s*([a-zA-Z]+)\s+(?:weight\s+)?(\d+\.?\d*)\s*(?:kg)?\s*(.*)$",
    re.IGNORECASE,
)
SETTLEMENT_TIER0_PATTERNS = [
    re.compile(r"\bclear(?:ed)?\s+([a-zA-Z]+)\s+ledger\b", re.IGNORECASE),
    re.compile(r"\bsettle(?:d)?\s+([a-zA-Z]+)\s+(?:amount|balance|ledger)\b", re.IGNORECASE),
    re.compile(r"\b([a-zA-Z]+)\s+settle(?:d)?\s+(?:amount|balance|ledger)\b", re.IGNORECASE),
    re.compile(r"\bwrote?\s+off\s+([a-zA-Z]+)\b", re.IGNORECASE),
]
NUMBERED_REPLY_RE = re.compile(r"^#?\s*\d+$")
CANCEL_REPLIES = {"cancel", "none", "skip"}
CONFIDENCE_FLOOR = 0.7
FINETUNED_LAST_QUERY_KEY = "finetuned_last_query_context"
EXPENSE_GROUP_MATCH_TERMS = {
    group: sorted(
        {group.lower(), *(item.lower() for item in INDIA_EXPENSE.get(group, [])), *(item.lower() for item in GLOBAL_EXPENSE.get(group, []))},
        key=len,
        reverse=True,
    )
    for group in sorted(set(INDIA_EXPENSE) | set(GLOBAL_EXPENSE))
}


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorResponse:
    kind: str
    response_text: str
    tier: str = "tier0"
    parsed: dict[str, Any] | None = None
    confidence: float = 1.0
    note_id: int | None = None
    capture_id: int | None = None
    timings_ms: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "response_text": self.response_text,
            "tier": self.tier,
            "parsed": self.parsed,
            "confidence": self.confidence,
            "note_id": self.note_id,
            "capture_id": self.capture_id,
            "timings_ms": self.timings_ms,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_input(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _attach_timings(
    response: OrchestratorResponse,
    perf: dict[str, float] | None,
) -> OrchestratorResponse:
    if perf:
        response.timings_ms = dict(sorted(perf.items()))
    return response


def _sql_date_expr(column_name: str, fallback_column: str = "created_at") -> str:
    return f"COALESCE(substr({column_name}, 1, 10), substr({fallback_column}, 1, 10))"


def _append_range_filters(
    clauses: list[str],
    params: list[Any],
    date_expr: str,
    date_start: str | None,
    date_end: str | None,
) -> None:
    if date_start:
        clauses.append(f"{date_expr} >= ?")
        params.append(date_start)
    if date_end:
        clauses.append(f"{date_expr} <= ?")
        params.append(date_end)


def _grouped_date_lines(
    rows: list[sqlite3.Row],
    *,
    date_key: str = "date",
    created_key: str = "created_at",
    render: Callable[[sqlite3.Row], str],
) -> str:
    ordered_days: list[str] = []
    grouped: dict[str, list[str]] = {}
    for row in rows:
        raw_day = row[date_key] if date_key in row.keys() else None
        created_day = row[created_key] if created_key in row.keys() else None
        day = str(raw_day or created_day or "unknown")[:10]
        if day not in grouped:
            grouped[day] = []
            ordered_days.append(day)
        grouped[day].append(render(row))
    return "\n".join(f"{day}: " + " · ".join(grouped[day]) for day in ordered_days)


def _expense_group_clause(group_name: str) -> tuple[str, list[Any]]:
    normalized = (group_name or "").strip().lower()
    terms = EXPENSE_GROUP_MATCH_TERMS.get(normalized) or [normalized]
    clauses = ["lower(COALESCE(group_name, '')) = ?"]
    params: list[Any] = [normalized]
    for term in terms:
        clauses.append("lower(description) LIKE ?")
        params.append(f"%{term}%")
    return "(" + " OR ".join(clauses) + ")", params


def _resolve_self_weight_person(conn: sqlite3.Connection) -> str:
    override = (os.environ.get("SECOND_BRAIN_SELF_PERSON") or "").strip().lower()
    if override:
        return override
    row = conn.execute(
        f"""
        SELECT person
        FROM weights
        WHERE person IS NOT NULL AND person <> ''
        ORDER BY {_sql_date_expr('date')} DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row and row["person"]:
        return str(row["person"]).strip().lower()
    known = sorted(load_weight_persons(conn))
    if len(known) == 1:
        return known[0]
    return "self"


def _normalize_query_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "parse_query",
        "domain": payload.get("domain"),
        "intent": payload.get("intent"),
        "date_start": payload.get("date_start"),
        "date_end": payload.get("date_end"),
        "compare_date_start": payload.get("compare_date_start"),
        "compare_date_end": payload.get("compare_date_end"),
        "filters": dict(payload.get("filters") or {}),
        "limit": payload.get("limit"),
        "query_text": payload.get("query_text"),
    }


def _load_query_context(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return load_runtime_state(conn, FINETUNED_LAST_QUERY_KEY)


def _save_query_context(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    store_runtime_state(conn, FINETUNED_LAST_QUERY_KEY, _normalize_query_context(payload))


def _clear_query_context(conn: sqlite3.Connection) -> None:
    clear_runtime_state(conn, FINETUNED_LAST_QUERY_KEY)


def _run_finetuned_expense_query(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    filters = dict(payload.get("filters") or {})
    date_expr = _sql_date_expr("date")
    where: list[str] = []
    params: list[Any] = []
    if filters.get("description_text"):
        where.append("lower(description) LIKE ?")
        params.append(f"%{str(filters['description_text']).strip().lower()}%")
    if filters.get("exclude_description_text"):
        where.append("lower(description) NOT LIKE ?")
        params.append(f"%{str(filters['exclude_description_text']).strip().lower()}%")
    if filters.get("group"):
        clause, clause_params = _expense_group_clause(str(filters["group"]))
        where.append(clause)
        params.extend(clause_params)
    if filters.get("exclude_group"):
        clause, clause_params = _expense_group_clause(str(filters["exclude_group"]))
        where.append(f"NOT {clause}")
        params.extend(clause_params)
    intent = str(payload.get("intent") or "total")

    if intent == "compare":
        if not (payload.get("compare_date_start") and payload.get("compare_date_end")):
            return {"response_text": "Compare range was missing from the parser output.", "rows": []}
        compare_where = list(where)
        compare_params = list(params)
        primary_where = list(where)
        primary_params = list(params)
        _append_range_filters(
            primary_where,
            primary_params,
            date_expr,
            payload.get("date_start"),
            payload.get("date_end"),
        )
        _append_range_filters(
            compare_where,
            compare_params,
            date_expr,
            payload.get("compare_date_start"),
            payload.get("compare_date_end"),
        )
        primary_sql = f" WHERE {' AND '.join(primary_where)}" if primary_where else ""
        compare_sql = f" WHERE {' AND '.join(compare_where)}" if compare_where else ""
        primary = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS total FROM expenses{primary_sql}",
            primary_params,
        ).fetchone()
        compare = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS total FROM expenses{compare_sql}",
            compare_params,
        ).fetchone()
        primary_total = float(primary["total"] or 0)
        compare_total = float(compare["total"] or 0)
        return {
            "response_text": (
                f"Expense compare: {payload.get('date_start')} to {payload.get('date_end')} "
                f"{format_rupees(primary_total)} vs {payload.get('compare_date_start')} to "
                f"{payload.get('compare_date_end')} {format_rupees(compare_total)}"
            ),
            "totals": {"primary": primary_total, "compare": compare_total},
        }

    _append_range_filters(where, params, date_expr, payload.get("date_start"), payload.get("date_end"))
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    if intent == "list":
        limit = max(1, min(int(payload.get("limit") or 10), 100))
        rows = conn.execute(
            f"""
            SELECT amount, description, date, group_name, created_at
            FROM expenses{where_sql}
            ORDER BY {date_expr} DESC, id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        if not rows:
            return {"response_text": "No expense entries matched that filter.", "rows": []}
        text = _grouped_date_lines(
            rows,
            render=lambda row: f"{format_rupees(row['amount'])} {row['description']}"
            + (f" [{row['group_name']}]" if row["group_name"] else ""),
        )
        return {"response_text": "Expense list:\n" + text, "rows": [dict(row) for row in rows]}

    row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) AS total FROM expenses{where_sql}",
        params,
    ).fetchone()
    total = float(row["total"] or 0)
    return {"response_text": f"Total spend: {format_rupees(total)}", "total": total}


def _run_finetuned_buy_query(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    filters = dict(payload.get("filters") or {})
    date_expr = _sql_date_expr("date")
    where: list[str] = []
    params: list[Any] = []
    _append_range_filters(where, params, date_expr, payload.get("date_start"), payload.get("date_end"))
    status = filters.get("status")
    if status is None and payload.get("intent") in {"list", "latest_day"}:
        status = "open"
    if status:
        where.append("status = ?")
        params.append(status)
    if filters.get("item_text"):
        where.append("lower(item_text) LIKE ?")
        params.append(f"%{str(filters['item_text']).strip().lower()}%")

    if payload.get("intent") == "latest_day" and not (payload.get("date_start") or payload.get("date_end")):
        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        latest = conn.execute(
            f"""
            SELECT {date_expr} AS day
            FROM buy_items{where_sql}
            ORDER BY day DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if not latest or not latest["day"]:
            return {"response_text": "No buy items matched that filter.", "rows": []}
        where.append(f"{date_expr} = ?")
        params.append(latest["day"])

    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(payload.get("limit") or 25), 100))
    rows = conn.execute(
        f"""
        SELECT item_text, quantity_text, unit_text, status, date, created_at
        FROM buy_items{where_sql}
        ORDER BY {date_expr} DESC, id DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    if not rows:
        return {"response_text": "No buy items matched that filter.", "rows": []}
    text = _grouped_date_lines(
        rows,
        render=lambda row: (
            f"[{row['status']}] {row['item_text']}"
            + (f" ({row['quantity_text']} {row['unit_text']})" if row["quantity_text"] and row["unit_text"] else "")
            + (f" ({row['quantity_text']})" if row["quantity_text"] and not row["unit_text"] else "")
        ),
    )
    return {"response_text": "Buy list:\n" + text, "rows": [dict(row) for row in rows]}


def _run_finetuned_todo_query(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    filters = dict(payload.get("filters") or {})
    date_expr = _sql_date_expr("date")
    where: list[str] = []
    params: list[Any] = []
    _append_range_filters(where, params, date_expr, payload.get("date_start"), payload.get("date_end"))
    status = filters.get("status")
    if status is None and payload.get("intent") in {"list", "search"}:
        status = "open"
    status_map = {"open": "pending", "done": "done"}
    if status:
        where.append("status = ?")
        params.append(status_map[status])
    if filters.get("text_match"):
        where.append("lower(content) LIKE ?")
        params.append(f"%{str(filters['text_match']).strip().lower()}%")
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    limit_default = 10 if payload.get("intent") == "history" else 20
    limit = max(1, min(int(payload.get("limit") or limit_default), 100))
    order_sql = (
        f"ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, {date_expr} DESC, id DESC"
        if status is None
        else f"ORDER BY {date_expr} DESC, id DESC"
    )
    rows = conn.execute(
        f"""
        SELECT content, status, date, created_at
        FROM todos{where_sql}
        {order_sql}
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    if not rows:
        return {"response_text": "No todo entries matched that filter.", "rows": []}
    text = _grouped_date_lines(
        rows,
        render=lambda row: f"[{'open' if row['status'] == 'pending' else 'done'}] {row['content']}",
    )
    return {"response_text": "Todo list:\n" + text, "rows": [dict(row) for row in rows]}


def _run_finetuned_weight_query(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    filters = dict(payload.get("filters") or {})
    person = str(filters.get("person_text") or "self").strip().lower()
    if person == "self":
        person = _resolve_self_weight_person(conn)
    date_expr = _sql_date_expr("date")
    if payload.get("intent") == "latest_all":
        rows = conn.execute(
            f"""
            SELECT w1.person, w1.weight, w1.date, w1.note
            FROM weights w1
            WHERE w1.id = (
                SELECT w2.id
                FROM weights w2
                WHERE w2.person = w1.person
                ORDER BY COALESCE(substr(w2.date, 1, 10), substr(w2.created_at, 1, 10)) DESC, w2.id DESC
                LIMIT 1
            )
            ORDER BY w1.person
            """
        ).fetchall()
        if not rows:
            return {"response_text": "No weight data found.", "rows": []}
        response = " · ".join(
            f"{row['person'].title()}: {row['weight']}kg on {str(row['date'])[:10]}"
            for row in rows
        )
        return {"response_text": response, "rows": [dict(row) for row in rows]}

    where = ["person = ?"]
    params: list[Any] = [person]
    _append_range_filters(where, params, date_expr, payload.get("date_start"), payload.get("date_end"))
    limit_default = 5 if payload.get("intent") in {"history", "trend"} else 10
    limit = max(1, min(int(payload.get("limit") or limit_default), 100))
    rows = conn.execute(
        f"""
        SELECT person, weight, date, note, created_at
        FROM weights
        WHERE {' AND '.join(where)}
        ORDER BY {date_expr} DESC, id DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    if not rows:
        return {"response_text": f"No weight data for {person.title()}", "rows": []}
    if payload.get("intent") == "latest":
        row = rows[0]
        note = f" ({row['note']})" if row["note"] else ""
        return {
            "response_text": f"{person.title()} weight: {row['weight']}kg on {str(row['date'])[:10]}{note}",
            "rows": [dict(row)],
        }
    if payload.get("intent") == "change":
        ordered = list(reversed(rows))
        earliest = ordered[0]
        latest = rows[0]
        delta = float(latest["weight"]) - float(earliest["weight"])
        return {
            "response_text": (
                f"{person.title()} changed {delta:+.1f}kg "
                f"({earliest['weight']}kg -> {latest['weight']}kg)"
            ),
            "rows": [dict(row) for row in rows],
        }
    history_text = " · ".join(
        f"{str(row['date'])[:10]} {row['weight']}kg" + (f" ({row['note']})" if row["note"] else "")
        for row in rows
    )
    if payload.get("intent") == "trend" and len(rows) >= 2:
        latest = rows[0]
        earliest = rows[-1]
        delta = float(latest["weight"]) - float(earliest["weight"])
        return {
            "response_text": f"{person.title()} trend: {history_text} · net {delta:+.1f}kg",
            "rows": [dict(row) for row in rows],
        }
    return {"response_text": history_text, "rows": [dict(row) for row in rows]}


def _ledger_summary_rows(
    conn: sqlite3.Connection,
    *,
    person_text: str | None,
    perspective: str | None,
    status: str | None,
    date_start: str | None,
    date_end: str | None,
) -> list[sqlite3.Row]:
    if date_start or date_end:
        date_expr = _sql_date_expr("date")
        where: list[str] = []
        params: list[Any] = []
        _append_range_filters(where, params, date_expr, date_start, date_end)
        if person_text:
            where.append("person = ?")
            params.append(person_text)
        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        rows = conn.execute(
            f"""
            SELECT person, SUM(CASE WHEN direction = 'gave' THEN amount ELSE -amount END) AS balance
            FROM ledger{where_sql}
            GROUP BY person
            ORDER BY ABS(balance) DESC, person
            """,
            params,
        ).fetchall()
    else:
        params = [person_text] if person_text else []
        person_sql = " WHERE person = ?" if person_text else ""
        rows = conn.execute(
            f"SELECT person, balance FROM ledger_balance{person_sql} ORDER BY ABS(balance) DESC, person",
            params,
        ).fetchall()
    filtered: list[sqlite3.Row] = []
    for row in rows:
        balance = float(row["balance"] or 0)
        if perspective == "i_owe_them" and balance >= 0:
            continue
        if perspective == "they_owe_me" and balance <= 0:
            continue
        if status == "open" and balance == 0:
            continue
        if status == "settled" and balance != 0:
            continue
        filtered.append(row)
    return filtered


def _run_finetuned_ledger_query(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    filters = dict(payload.get("filters") or {})
    person_text = str(filters.get("person_text") or "").strip().lower() or None
    perspective = filters.get("perspective")
    status = filters.get("status")
    intent = str(payload.get("intent") or "summary")
    summary_rows = _ledger_summary_rows(
        conn,
        person_text=person_text,
        perspective=perspective,
        status=status,
        date_start=payload.get("date_start"),
        date_end=payload.get("date_end"),
    )
    # "summary" is the v2 name for "open_summary"; keep both for backward compat
    if intent in {"open_summary", "settled_list", "summary"}:
        if not summary_rows:
            if intent == "settled_list":
                return {"response_text": "No settled ledger found for that filter.", "rows": []}
            return {"response_text": "No open ledger found for that filter.", "rows": []}
        response = ", ".join(
            (
                f"{row['person'].title()} owes you {format_rupees(row['balance'])}"
                if float(row["balance"]) > 0
                else (
                    f"You owe {row['person'].title()} {format_rupees(abs(float(row['balance'])))}"
                    if float(row["balance"]) < 0
                    else f"{row['person'].title()} - settled"
                )
            )
            for row in summary_rows
        )
        return {"response_text": response, "rows": [dict(row) for row in summary_rows]}
    if intent == "latest_balance":
        latest = conn.execute(
            f"""
            SELECT person
            FROM ledger
            ORDER BY {_sql_date_expr('date')} DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if not latest:
            return {"response_text": "No ledger entries yet.", "rows": []}
        summary_rows = _ledger_summary_rows(
            conn,
            person_text=str(latest["person"]).lower(),
            perspective=None,
            status=None,
            date_start=None,
            date_end=None,
        )
        if not summary_rows:
            return {"response_text": "No ledger entries yet.", "rows": []}
        row = summary_rows[0]
        balance = float(row["balance"] or 0)
        if balance > 0:
            return {"response_text": f"{row['person'].title()} owes you {format_rupees(balance)}", "rows": [dict(row)]}
        if balance < 0:
            return {"response_text": f"You owe {row['person'].title()} {format_rupees(abs(balance))}", "rows": [dict(row)]}
        return {"response_text": f"{row['person'].title()} - settled", "rows": [dict(row)]}
    if intent == "balance":
        if person_text:
            if not summary_rows:
                return {"response_text": f"No ledger entries for {person_text.title()}", "rows": []}
            row = summary_rows[0]
            balance = float(row["balance"] or 0)
            if balance > 0:
                return {"response_text": f"{person_text.title()} owes you {format_rupees(balance)}", "rows": [dict(row)]}
            if balance < 0:
                return {"response_text": f"You owe {person_text.title()} {format_rupees(abs(balance))}", "rows": [dict(row)]}
            return {"response_text": f"{person_text.title()} - settled", "rows": [dict(row)]}
        if not summary_rows:
            return {"response_text": "No ledger entries matched that filter.", "rows": []}
        response = ", ".join(
            (
                f"{row['person'].title()}: {format_rupees(abs(float(row['balance'])))}"
                for row in summary_rows
            )
        )
        return {"response_text": response, "rows": [dict(row) for row in summary_rows]}

    people_filter = [row["person"] for row in summary_rows] if (status or perspective) else []
    where: list[str] = []
    params: list[Any] = []
    date_expr = _sql_date_expr("date")
    _append_range_filters(where, params, date_expr, payload.get("date_start"), payload.get("date_end"))
    if person_text:
        where.append("person = ?")
        params.append(person_text)
    elif people_filter:
        placeholders = ",".join("?" for _ in people_filter)
        where.append(f"person IN ({placeholders})")
        params.extend(people_filter)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"""
        SELECT person, direction, amount, note, date, created_at
        FROM ledger{where_sql}
        ORDER BY {date_expr} DESC, id DESC
        LIMIT ?
        """,
        [*params, max(1, min(int(payload.get("limit") or 20), 100))],
    ).fetchall()
    if not rows:
        return {"response_text": "No ledger entries matched that filter.", "rows": []}
    text = _grouped_date_lines(
        rows,
        render=lambda row: (
            f"{row['person'].title()} "
            f"{'gave' if row['direction'] == 'gave' else 'received'} "
            f"{format_rupees(row['amount'])}"
            + (f" ({row['note']})" if row["note"] else "")
        ),
    )
    return {"response_text": "Ledger entries:\n" + text, "rows": [dict(row) for row in rows]}


def _build_finetuned_error_response(
    text: str,
    lane: str | None,
    message: str,
) -> OrchestratorResponse:
    return OrchestratorResponse(
        kind="unknown",
        response_text=f"Fine-tuned parser error: {message}",
        tier="finetuned",
        parsed={"rule": "finetuned_parser_error", "lane": lane, "input": text},
        confidence=0.0,
    )


def _build_ledger_entry_from_parser_record(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    text: str,
    persons: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    person = str(record.get("person_text") or "").strip().lower()
    action = str(record.get("action") or "").strip()
    note = record.get("note")
    date = str(record.get("date") or _now()[:10])
    direction_map = {
        "add_debt": "received",
        "add_credit": "gave",
        "repay_debt": "gave",
        "collect_credit": "received",
    }
    if action == "settle":
        row = conn.execute(
            "SELECT balance FROM ledger_balance WHERE person = ?",
            (person,),
        ).fetchone()
        if not row:
            return None, f"No open ledger found for {person.title()}"
        balance = float(row["balance"] or 0)
        if balance == 0:
            return None, f"{person.title()} is already settled"
        amount = abs(balance)
        direction = "received" if balance > 0 else "gave"
        note = note or "settled"
    else:
        amount = float(record.get("amount") or 0)
        direction = direction_map.get(action)
        if not direction or amount <= 0:
            return None, "Ledger parser returned an invalid action payload."
    return {
        "type": "ledger",
        "person": person,
        "amount": amount,
        "direction": direction,
        "date": date,
        "note": note,
        "raw": text,
        "unknown_person": person not in persons,
    }, None


def _build_finetuned_entries(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    text: str,
    persons: set[str],
) -> tuple[list[dict[str, Any]], str | None]:
    lane = str(payload.get("lane") or "")
    entries: list[dict[str, Any]] = []
    for record in list(payload.get("records") or []):
        if lane == "expense":
            date = str(record.get("date") or _now()[:10])
            entries.append(
                {
                    "type": "expense",
                    "amount": float(record["amount"]),
                    "description": str(record.get("description") or "").strip(),
                    "date": date,
                    "month": get_month(date),
                    "group_name": str(record.get("group") or "").strip().lower() or None,
                    "raw": text,
                }
            )
            continue
        if lane == "buy":
            entries.append(
                {
                    "type": "buy",
                    "item_text": str(record.get("item_text") or "").strip(),
                    "quantity_text": str(record.get("quantity_text") or "").strip() or None,
                    "unit_text": str(record.get("unit_text") or "").strip() or None,
                    "date": str(record.get("date") or _now()[:10]),
                    "status": "open",
                    "raw": text,
                }
            )
            continue
        if lane == "todo":
            entries.append(
                {
                    "type": "todo",
                    "content": str(record.get("text") or "").strip(),
                    "date": str(record.get("date") or _now()[:10]),
                    "raw": text,
                }
            )
            continue
        if lane == "weight":
            person = str(record.get("person_text") or "").strip().lower()
            if person == "self":
                person = _resolve_self_weight_person(conn)
            entries.append(
                {
                    "type": "weight",
                    "person": person,
                    "weight": float(record["value"]),
                    "date": str(record.get("date") or _now()[:10]),
                    "note": record.get("note"),
                    "raw": text,
                }
            )
            continue
        if lane == "ledger":
            entry, error = _build_ledger_entry_from_parser_record(conn, record, text, persons)
            if error:
                return [], error
            entries.append(entry)
            continue
        return [], f"Unsupported parser write lane: {lane}"
    return entries, None


def _persist_finetuned_confirm(
    conn: sqlite3.Connection,
    text: str,
    payload: dict[str, Any],
) -> OrchestratorResponse:
    lane = str(payload.get("lane") or "")
    records = list(payload.get("records") or [])
    if lane == "ledger" and len(records) == 1:
        record = records[0]
        person = str(record.get("person_text") or "").strip().lower()
        amount = float(record.get("amount") or 0)
        note = record.get("note")
        if person and amount > 0:
            options = [
                {
                    "label": f"I lent {person.title()} {format_rupees(amount)}",
                    "tool": "add_ledger",
                    "args": {"person": person, "amount": amount, "direction": "gave", "note": note},
                },
                {
                    "label": f"I borrowed {format_rupees(amount)} from {person.title()}",
                    "tool": "add_ledger",
                    "args": {"person": person, "amount": amount, "direction": "received", "note": note},
                },
                {
                    "label": "Save as raw note (don't categorize)",
                    "tool": "add_note",
                    "args": {"content": text},
                },
            ]
            response = _persist_clarify(
                conn,
                text,
                None,
                "Did you give them money, or did they give you money?",
                options,
                source="finetuned_confirm",
            )
            response.tier = "finetuned"
            return response
    response = _persist_clarify(
        conn,
        text,
        None,
        "The parser needs confirmation. Pick one:",
        [
            {"label": "Save as a todo", "tool": "add_todo", "args": {"content": text}},
            {"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}},
        ],
        source="finetuned_confirm_fallback",
    )
    response.tier = "finetuned"
    return response


def _execute_finetuned_write(
    conn: sqlite3.Connection,
    text: str,
    payload: dict[str, Any],
    persons: set[str],
    embedding_service: EmbeddingService,
    parser_summary: dict[str, Any],
) -> OrchestratorResponse:
    disposition = str(payload.get("disposition") or "")
    lane = str(payload.get("lane") or "")
    if disposition == "reject":
        response = _persist_clarify(
            conn,
            text,
            None,
            f"That {lane} entry looks incomplete ({payload.get('reason_code') or 'needs more detail'}). Pick one:",
            [
                {"label": "Save as a todo", "tool": "add_todo", "args": {"content": text}},
                {"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}},
            ],
            source="finetuned_reject",
        )
        response.tier = "finetuned"
        return response
    if disposition == "confirm":
        return _persist_finetuned_confirm(conn, text, payload)
    entries, error = _build_finetuned_entries(conn, payload, text, persons)
    if error:
        return OrchestratorResponse(
            kind="unknown",
            response_text=error,
            tier="finetuned",
            parsed={"rule": "finetuned_parser_write_error", "summary": parser_summary},
            confidence=0.0,
        )
    _clear_query_context(conn)
    if len(entries) == 1:
        response_text, capture_id, _ = _execute_write_entry(conn, embedding_service, entries[0], text)
    else:
        response_text, capture_id = _execute_write_entries(conn, entries, text, "finetuned")
    return OrchestratorResponse(
        kind="write",
        response_text=response_text,
        tier="finetuned",
        parsed={"rule": "finetuned_parser", "summary": parser_summary, "entries": entries},
        capture_id=capture_id,
    )


def _execute_finetuned_query(
    conn: sqlite3.Connection,
    text: str,
    payload: dict[str, Any],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    parser_summary: dict[str, Any],
    used_context: bool,
) -> OrchestratorResponse:
    if payload.get("task") == "parse_followup_query" and not used_context:
        return OrchestratorResponse(
            kind="unknown",
            response_text="No earlier tagged query context was available for that follow-up.",
            tier="finetuned",
            parsed={"rule": "finetuned_missing_followup_context", "summary": parser_summary},
            confidence=0.0,
        )
    # Handle v2 query dispositions: clarify and reject carry null intent/filters
    disposition = str(payload.get("disposition") or "accept")
    if disposition == "reject":
        reason = str(payload.get("reason_code") or "unsupported query")
        response = _persist_clarify(
            conn,
            text,
            None,
            f"That query isn't supported ({reason}). What would you like to do?",
            [
                {"label": "Save as a note instead", "tool": "add_note", "args": {"content": text}},
                {"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}},
            ],
            source="finetuned_query_reject",
        )
        response.tier = "finetuned"
        return response
    if disposition == "clarify":
        clarify_reason = str(payload.get("clarify_reason") or "ambiguous query")
        raw_options: list[str] = list(payload.get("clarify_options") or [])
        options = [
            {"label": opt, "tool": "add_note", "args": {"content": text}}
            for opt in raw_options
        ]
        options.append({"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}})
        response = _persist_clarify(
            conn,
            text,
            None,
            f"Query is ambiguous ({clarify_reason}). Pick one:",
            options,
            source="finetuned_query_clarify",
        )
        response.tier = "finetuned"
        return response
    note_id = create_note_record(
        conn,
        text,
        input_kind="query",
        structured_type="query",
        metadata={"orchestrator": "finetuned", "parser_summary": parser_summary},
    )
    domain = str(payload.get("domain") or "")
    if domain == "note":
        intent = str(payload.get("intent") or "")
        query_text = str(payload.get("query_text") or "")
        result = query_notes_result(
            conn,
            llm_service,
            embedding_service,
            query=query_text,
            recent=intent in {"recent", "latest_bucket", "day_bucket", "latest"} and not query_text,
            limit=int(payload.get("limit") or 10),
            date_start=payload.get("date_start"),
            date_end=payload.get("date_end"),
        )
    elif domain == "expense":
        result = _run_finetuned_expense_query(conn, payload)
    elif domain == "buy":
        result = _run_finetuned_buy_query(conn, payload)
    elif domain == "todo":
        result = _run_finetuned_todo_query(conn, payload)
    elif domain == "weight":
        result = _run_finetuned_weight_query(conn, payload)
    elif domain == "ledger":
        result = _run_finetuned_ledger_query(conn, payload)
    else:
        return OrchestratorResponse(
            kind="unknown",
            response_text=f"Unsupported parser query domain: {domain}",
            tier="finetuned",
            parsed={"rule": "finetuned_parser_query_error", "summary": parser_summary},
            note_id=note_id,
            confidence=0.0,
        )
    _save_query_context(conn, payload)
    return OrchestratorResponse(
        kind="query",
        response_text=result["response_text"],
        tier="finetuned",
        parsed={"rule": "finetuned_parser", "summary": parser_summary, "query": _normalize_query_context(payload)},
        note_id=note_id,
    )


def _try_finetuned_route(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse | None:
    if not finetuned_parser_enabled():
        return None
    lane = detect_tagged_lane(text)
    if lane not in {"expense", "buy", "todo", "weight", "ledger", "ask"}:
        return None
    parser_service = get_finetuned_parser_service()
    context = _load_query_context(conn) if should_use_followup_context(text) else None
    try:
        parser_result = parser_service.parse(text, context=context, perf=perf)
    except Exception as exc:
        return _build_finetuned_error_response(text, lane, str(exc))
    payload = dict(parser_result["parsed"])
    task = str(payload.get("task") or "")
    if lane == "ask" and task not in {"parse_query", "parse_followup_query"}:
        return _build_finetuned_error_response(text, lane, f"expected a query task, got {task}")
    if lane != "ask" and task != "parse_write":
        return _build_finetuned_error_response(text, lane, f"expected parse_write, got {task}")
    if lane != "ask" and payload.get("lane") != lane:
        return _build_finetuned_error_response(
            text,
            lane,
            f"tagged lane {lane} did not match parser lane {payload.get('lane')}",
        )
    if task == "parse_write":
        return _execute_finetuned_write(
            conn,
            text,
            payload,
            persons,
            embedding_service,
            parser_result["summary"],
        )
    return _execute_finetuned_query(
        conn,
        text,
        payload,
        llm_service,
        embedding_service,
        parser_result["summary"],
        bool(parser_result.get("used_context")),
    )


# ---------------------------------------------------------------------------
# Tier 0 rule predicates
# ---------------------------------------------------------------------------


def _try_explicit_todo(text: str) -> dict[str, Any] | None:
    match = TODO_COLON_RE.match(text)
    if match:
        content = match.group(1).strip()
        if content:
            return {"type": "todo", "content": content, "raw": text, "form": "colon"}

    match = TODO_VERB_RE.match(text)
    if match and match.group(1).lower() in TODO_START_VERBS:
        content = (match.group(1) + match.group(2)).strip()
        if content:
            return {"type": "todo", "content": content, "raw": text, "form": "verb"}

    match = REMIND_ME_RE.match(text)
    if match:
        content = match.group(1).strip()
        # Skip query-shaped remainders: "remind me what i said about X" is a
        # retrieval, not a todo.
        leading_word = content.split(" ", 1)[0].lower() if content else ""
        if leading_word in {"what", "why", "how", "when", "where", "who", "which", "whether", "if"}:
            return None
        if content:
            return {"type": "todo", "content": content, "raw": text, "form": "remind_me"}

    return None


def _try_weight_write(text: str, weight_people: set[str], today: str) -> dict[str, Any] | None:
    match = WEIGHT_WRITE_RE.match(text.strip())
    if not match:
        return None
    name = match.group(1).lower()
    if name not in weight_people:
        return None
    try:
        weight = float(match.group(2))
    except ValueError:
        return None
    if weight <= 0 or weight >= 150:
        return None
    note = match.group(3).strip() or None
    return {
        "type": "weight",
        "person": name,
        "weight": weight,
        "note": note,
        "date": today,
        "raw": text,
    }


def _try_settlement(text: str) -> dict[str, Any] | None:
    if looks_like_settlement_followup(text):
        return {"matched_pattern": "legacy_settlement_phrase", "person_hint": None}
    for pattern in SETTLEMENT_TIER0_PATTERNS:
        match = pattern.search(text)
        if match:
            return {"matched_pattern": pattern.pattern, "person_hint": match.group(1).lower()}
    return None


# ---------------------------------------------------------------------------
# Tier 0 executors
# ---------------------------------------------------------------------------


def _execute_write_entry(
    conn: sqlite3.Connection,
    embedding_service: EmbeddingService | None,
    entry: dict[str, Any],
    text: str,
) -> tuple[str, int, dict[str, Any] | None]:
    capture_id = create_capture_record(
        conn,
        text,
        entry["type"],
        metadata={"orchestrator": "tier0", "entry": entry},
    )
    entry["source_capture_id"] = capture_id
    result = add_entry_result(conn, entry)
    return result["response_text"], capture_id, None


def _save_plain_note(
    conn: sqlite3.Connection,
    embedding_service: EmbeddingService | None,
    note_text: str,
    raw_input: str,
    source: str,
    perf: dict[str, float] | None = None,
) -> tuple[str, int, dict[str, Any] | None]:
    note_text = (note_text or "").strip()
    note_id = create_note_record(
        conn,
        note_text,
        input_kind="note",
        structured_type="note",
        metadata={"raw_input": raw_input} if note_text != raw_input else None,
    )
    embedding_status = None
    if embedding_service is not None:
        embedding_status = store_note_embedding(
            conn,
            embedding_service,
            note_id,
            note_text,
            infer_note_domain(note_text),
            perf=perf,
        )
    update_note_record(
        conn,
        note_id,
        structured_type="note",
        note_domain=infer_note_domain(note_text),
        metadata={
            "orchestrator": source,
            "raw_input": raw_input if note_text != raw_input else None,
            "embedding_status": embedding_status,
        },
    )
    suffix = ""
    if embedding_status and not embedding_status.get("embedded"):
        suffix = " (search index not available)"
    return f"Note saved{suffix}", note_id, embedding_status


def _execute_write_entries(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    text: str,
    source: str,
) -> tuple[str, int]:
    entry_types = [str(e.get("type") or "unknown") for e in entries]
    capture_type = entry_types[0] if len(set(entry_types)) == 1 else "multi"
    capture_id = create_capture_record(
        conn,
        text,
        capture_type,
        metadata={"orchestrator": source, "entries": entries},
    )
    responses: list[str] = []
    for entry in entries:
        normalized = dict(entry)
        normalized["source_capture_id"] = capture_id
        result = add_entry_result(conn, normalized)
        responses.append(result["response_text"])
    return " · ".join(dict.fromkeys(responses)) or "Saved", capture_id


def _execute_person_command(
    conn: sqlite3.Connection,
    command: dict[str, Any],
    text: str,
) -> tuple[str, int, bool]:
    note_id = create_note_record(
        conn, text, input_kind="person_command", structured_type="person_command",
    )
    op = command["op"]
    if op == "ADD_PERSON":
        result = manage_persons_result(conn, "ADD_PERSON", name=command.get("name"))
    elif op == "REMOVE_PERSON":
        result = manage_persons_result(conn, "REMOVE_PERSON", name=command.get("name"))
    elif op == "MODIFY_PERSON":
        result = manage_persons_result(
            conn, "MODIFY_PERSON",
            old_name=command.get("old_name"),
            new_name=command.get("new_name"),
        )
    else:
        result = {"response_text": f"Unknown person op: {op}", "is_error": True}
    update_note_record(
        conn, note_id,
        metadata={"orchestrator": "tier0", "command": command, "result": result},
    )
    return result["response_text"], note_id, bool(result.get("is_error"))


def _execute_settlement(
    conn: sqlite3.Connection, text: str, settlement_meta: dict[str, Any],
) -> tuple[str, int, str]:
    note_id = create_note_record(
        conn, text, input_kind="note", structured_type="ledger",
        metadata={"orchestrator": "tier0", "trigger": "settlement_phrase", "settlement": settlement_meta},
    )
    result = prepare_ledger_settlement_result(conn, note_id)
    return result["response_text"], note_id, result.get("kind", "clarification")


# ---------------------------------------------------------------------------
# Tier 1: tool dispatcher
# ---------------------------------------------------------------------------


def _normalize_month(month: Any) -> str | None:
    if month in (None, "", "all", "all time"):
        return None
    if month == "current":
        return _current_month()
    if isinstance(month, str) and re.match(r"^\d{4}-\d{2}$", month):
        return month
    return None


def _dispatch_tool(
    conn: sqlite3.Connection,
    tool: str,
    args: dict[str, Any],
    text: str,
    persons: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> tuple[OrchestratorResponse, dict[str, Any]]:
    """Run a Tier 1 tool call. Returns (response, debug_metadata).

    Structured-fact writes (expense/ledger/weight/todo) link to a `captures`
    row, never to `notes`. Real user notes (`add_note`) get a real notes row.
    Audit/clarify/query branches still create a transient notes row for
    pending_actions linkage and activity-log debug metadata.
    """
    with perf_timer(perf, "dispatch.total_ms"):
        today = _now()
        debug: dict[str, Any] = {"tool": tool, "args": args}

        def _audit_note(input_kind: str = "query", structured_type: str | None = None) -> int:
            return create_note_record(
                conn,
                text,
                input_kind=input_kind,
                structured_type=structured_type,
                metadata={"orchestrator": "tier1", "tool": tool, "args": args},
            )

        if tool == "add_expense":
            amount = float(args.get("amount") or 0)
            description = str(args.get("description") or "").strip() or "misc"
            if amount <= 0:
                return _build_heuristic_clarify(conn, text, None), debug
            with perf_timer(perf, "dispatch.add_expense_ms"):
                capture_id = create_capture_record(
                    conn, text, "expense",
                    metadata={"orchestrator": "tier1", "args": args},
                )
                entry = {
                    "type": "expense",
                    "amount": amount,
                    "description": description,
                    "date": today,
                    "month": get_month(today),
                    "raw": text,
                    "source_capture_id": capture_id,
                }
                result = add_entry_result(conn, entry)
            debug["capture_id"] = capture_id
            return OrchestratorResponse(
                kind="write",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "write_expense", "tool": tool, "args": args},
                capture_id=capture_id,
            ), debug

        if tool == "add_ledger":
            person = str(args.get("person") or "").strip().lower()
            amount = float(args.get("amount") or 0)
            direction = args.get("direction")
            if not person or amount <= 0 or direction not in {"gave", "received"}:
                return _build_heuristic_clarify(conn, text, None), debug
            with perf_timer(perf, "dispatch.add_ledger_ms"):
                capture_id = create_capture_record(
                    conn, text, "ledger",
                    metadata={"orchestrator": "tier1", "args": args},
                )
                entry = {
                    "type": "ledger",
                    "person": person,
                    "amount": amount,
                    "direction": direction,
                    "date": today,
                    "note": args.get("note"),
                    "raw": text,
                    "source_capture_id": capture_id,
                    "unknown_person": person not in persons,
                }
                result = add_entry_result(conn, entry)
            debug["capture_id"] = capture_id
            return OrchestratorResponse(
                kind="write",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "write_ledger", "tool": tool, "args": args},
                capture_id=capture_id,
            ), debug

        if tool == "add_weight":
            person = str(args.get("person") or "").strip().lower()
            weight = float(args.get("weight") or 0)
            if not person or weight <= 0 or weight >= 150:
                return _build_heuristic_clarify(conn, text, None), debug
            with perf_timer(perf, "dispatch.add_weight_ms"):
                capture_id = create_capture_record(
                    conn, text, "weight",
                    metadata={"orchestrator": "tier1", "args": args},
                )
                entry = {
                    "type": "weight",
                    "person": person,
                    "weight": weight,
                    "date": today,
                    "note": args.get("note"),
                    "raw": text,
                    "source_capture_id": capture_id,
                }
                result = add_entry_result(conn, entry)
            debug["capture_id"] = capture_id
            return OrchestratorResponse(
                kind="write",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "write_weight", "tool": tool, "args": args},
                capture_id=capture_id,
            ), debug

        if tool == "add_todo":
            content = str(args.get("content") or "").strip()
            if not content:
                return _build_heuristic_clarify(conn, text, None), debug
            with perf_timer(perf, "dispatch.add_todo_ms"):
                capture_id = create_capture_record(
                    conn, text, "todo",
                    metadata={"orchestrator": "tier1", "args": args},
                )
                entry = {
                    "type": "todo",
                    "content": content,
                    "raw": text,
                    "source_capture_id": capture_id,
                }
                result = add_entry_result(conn, entry)
            debug["capture_id"] = capture_id
            return OrchestratorResponse(
                kind="write",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "write_todo", "tool": tool, "args": args},
                capture_id=capture_id,
            ), debug

        if tool == "add_note":
            note_content = str(args.get("content") or text).strip() or text
            domain = "general"
            note_id = create_note_record(
                conn,
                note_content,
                input_kind="note",
                structured_type="note",
                note_domain=domain,
                metadata={
                    "orchestrator": "tier1",
                    "raw_input": text if note_content != text else None,
                },
            )
            with perf_timer(perf, "dispatch.add_note_ms"):
                embedding_status = store_note_embedding(
                    conn, embedding_service, note_id, note_content, domain, perf=perf,
                )
            update_note_record(
                conn, note_id,
                metadata={
                    "orchestrator": "tier1",
                    "entry": {"content": note_content, "domain": domain},
                    "embedding_status": embedding_status,
                },
            )
            suffix = ""
            if embedding_status and not embedding_status.get("embedded"):
                suffix = " (search index not available)"
            label = "Note" if domain == "general" else f"{domain.title()} note"
            debug["note_id"] = note_id
            debug["embedding_status"] = embedding_status
            return OrchestratorResponse(
                kind="write",
                response_text=f"{label} saved{suffix}",
                tier="tier1",
                parsed={"rule": "write_note", "tool": tool, "args": args},
                note_id=note_id,
            ), debug

        if tool == "manage_person":
            note_id = _audit_note(input_kind="person_command", structured_type="person_command")
            op = args.get("operation") or args.get("op")
            with perf_timer(perf, "dispatch.manage_person_ms"):
                result = manage_persons_result(
                    conn, op,
                    name=args.get("name"),
                    old_name=args.get("old_name"),
                    new_name=args.get("new_name"),
                )
            debug["note_id"] = note_id
            return OrchestratorResponse(
                kind="person_command",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "manage_person", "tool": tool, "args": args},
                note_id=note_id,
            ), debug

        if tool == "query_ledger":
            with perf_timer(perf, "dispatch.query_ledger_ms"):
                result = query_ledger_result(
                    conn,
                    query_type=args.get("query_type", "balance"),
                    person=args.get("person"),
                )
            return OrchestratorResponse(
                kind="query",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "query_ledger", "tool": tool, "args": args},
            ), debug

        if tool == "query_expense":
            with perf_timer(perf, "dispatch.query_expense_ms"):
                result = query_expense_result(
                    conn,
                    month=_normalize_month(args.get("month")),
                    description_like=args.get("description_like"),
                    list_mode=bool(args.get("list_mode")),
                    limit=int(args.get("limit") or 12),
                )
            return OrchestratorResponse(
                kind="query",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "query_expense", "tool": tool, "args": args},
            ), debug

        if tool == "query_todos":
            with perf_timer(perf, "dispatch.query_todos_ms"):
                result = get_todos_result(conn, status=args.get("status", "pending"), limit=int(args.get("limit") or 20))
            return OrchestratorResponse(
                kind="query",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "query_todos", "tool": tool, "args": args},
            ), debug

        if tool == "query_weight":
            person = args.get("person")
            if not person:
                return _build_heuristic_clarify(conn, text, None), debug
            with perf_timer(perf, "dispatch.query_weight_ms"):
                result = get_weight_result(conn, person=person, limit=int(args.get("limit") or 1))
            return OrchestratorResponse(
                kind="query",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "query_weight", "tool": tool, "args": args},
            ), debug

        if tool == "query_notes":
            with perf_timer(perf, "dispatch.query_notes_ms"):
                result = query_notes_result(
                    conn, llm_service, embedding_service,
                    query=str(args.get("query") or ""),
                    domain=args.get("domain"),
                    recent=bool(args.get("recent")),
                    limit=int(args.get("limit") or 5),
                    perf=perf,
                )
            return OrchestratorResponse(
                kind="query",
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "query_notes", "tool": tool, "args": args},
            ), debug

        if tool == "prepare_settlement":
            note_id = _audit_note(input_kind="note", structured_type="ledger")
            with perf_timer(perf, "dispatch.prepare_settlement_ms"):
                result = prepare_ledger_settlement_result(conn, note_id)
            debug["note_id"] = note_id
            return OrchestratorResponse(
                kind=result.get("kind", "clarification"),
                response_text=result["response_text"],
                tier="tier1",
                parsed={"rule": "prepare_settlement", "tool": tool},
                note_id=note_id,
            ), debug

        # Unknown tool — never crash; build a clarify menu.
        return _build_heuristic_clarify(conn, text, None), debug


# ---------------------------------------------------------------------------
# Tier 1: clarify / heuristic fallback
# ---------------------------------------------------------------------------


def _build_heuristic_clarify(
    conn: sqlite3.Connection,
    text: str,
    note_id: int | None,
) -> OrchestratorResponse:
    """Last-resort clarify menu built from input features. Always offers
    'Save as raw note' as the safety-net option.
    """
    lowered = text.lower()
    has_number = bool(re.search(r"\d", text))
    is_question_shape = bool(re.search(r"\?\s*$", text)) or any(
        lowered.startswith(prefix) for prefix in ("what ", "who ", "how ", "when ", "where ", "show ", "list ")
    )
    is_long = len(text.split()) >= 8

    options: list[dict[str, Any]] = []
    if has_number:
        options.append({"label": "Save as expense", "tool": "add_expense", "args": {"amount": 0, "description": text}})
    if is_question_shape:
        options.append({"label": "Search saved notes", "tool": "query_notes", "args": {"query": text}})
    if is_long:
        options.append({"label": "Save as a note (searchable)", "tool": "add_note", "args": {"content": text}})
    options.append({"label": "Save as a todo", "tool": "add_todo", "args": {"content": text}})
    options.append({"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}})

    return _persist_clarify(conn, text, note_id, "I'm not sure what you meant. Pick one:", options, source="heuristic")


def _persist_clarify(
    conn: sqlite3.Connection,
    text: str,
    note_id: int | None,
    question: str,
    options: list[dict[str, Any]],
    source: str,
) -> OrchestratorResponse:
    numbered = []
    for index, option in enumerate(options, start=1):
        numbered.append({"number": index, **option})

    lines = [question]
    for option in numbered:
        lines.append(f"{option['number']}. {option['label']}")
    lines.append("Reply with the number.")
    prompt = "\n".join(lines)

    action_id = create_pending_action(
        conn,
        action_type="clarify_intent",
        note_id=note_id,
        prompt=prompt,
        options=numbered,
        payload={"original_input": text, "normalized": normalize_input(text), "source": source},
    )
    if note_id is not None:
        update_note_record(
            conn, note_id, structured_type="clarify",
            metadata={"orchestrator": "tier1", "clarify_source": source, "options": numbered, "pending_action_id": action_id},
        )
    return OrchestratorResponse(
        kind="clarification",
        response_text=prompt,
        tier="tier1",
        parsed={"rule": "clarify_with_user", "source": source, "options": numbered, "pending_action_id": action_id},
        note_id=note_id,
        confidence=0.0,
    )


# ---------------------------------------------------------------------------
# Pending-action resolution (clarify_intent)
# ---------------------------------------------------------------------------


def _resolve_pending(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse | None:
    pending = latest_pending_action(conn)
    if not pending:
        return None

    lowered = text.strip().lower()
    is_numbered = bool(NUMBERED_REPLY_RE.match(lowered))
    is_cancel = lowered in CANCEL_REPLIES
    if not (is_numbered or is_cancel):
        return None

    resolution_note_id = create_note_record(
        conn, text, input_kind="resolution_reply",
        metadata={"pending_action_id": pending["id"]},
    )

    if pending["action_type"] == "ledger_settlement":
        result = resolve_pending_action_result(conn, text, resolution_note_id)
        if not result:
            return None
        return OrchestratorResponse(
            kind=result.get("kind", "write"),
            response_text=result.get("response_text", ""),
            tier="resolution",
            parsed={"rule": "settlement_resolve"},
            note_id=resolution_note_id,
        )

    if pending["action_type"] == "clarify_intent":
        if is_cancel:
            conn.execute(
                "UPDATE pending_actions SET status='dismissed', resolved_at=? WHERE id=?",
                (_now(), pending["id"]),
            )
            update_note_record(
                conn, resolution_note_id, structured_type="resolution",
                metadata={"pending_action_id": pending["id"], "status": "dismissed"},
            )
            return OrchestratorResponse(
                kind="unknown",
                response_text="Okay, I dropped that.",
                tier="resolution",
                parsed={"rule": "clarify_dismissed"},
                note_id=resolution_note_id,
            )

        match = NUMBERED_REPLY_RE.match(lowered)
        index = int(match.group(0).lstrip("#").strip()) - 1
        options = json.loads(pending["options_json"])
        if index < 0 or index >= len(options):
            return OrchestratorResponse(
                kind="clarification",
                response_text=f"Pick a number between 1 and {len(options)}.",
                tier="resolution",
                parsed={"rule": "clarify_out_of_range"},
                note_id=resolution_note_id,
                confidence=0.0,
            )

        choice = options[index]
        conn.execute(
            "UPDATE pending_actions SET status='resolved', resolved_at=? WHERE id=?",
            (_now(), pending["id"]),
        )

        payload = json.loads(pending["payload_json"] or "{}")
        normalized = payload.get("normalized") or normalize_input(payload.get("original_input", ""))
        original_text = payload.get("original_input", text)
        if normalized:
            upsert_routing_memory(conn, normalized, choice["tool"], choice.get("args") or {})

        update_note_record(
            conn, resolution_note_id, structured_type="resolution",
            metadata={
                "pending_action_id": pending["id"],
                "selected_option": choice,
                "memoized": bool(normalized),
                "normalized_pattern": normalized,
            },
        )

        response, debug = _dispatch_tool(
            conn, choice["tool"], choice.get("args") or {},
            original_text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "resolution"
        response.parsed = {
            "rule": "clarify_resolve",
            "selected_option": choice,
            "dispatch": debug,
            "memoized_as": normalized,
        }
        return response

    return None


# ---------------------------------------------------------------------------
# Tier 1 entry point + legacy-rule bridge
# ---------------------------------------------------------------------------


_LEGACY_TOOL_MAP = {
    "manage_persons": "manage_person",
    "query_ledger": "query_ledger",
    "query_expense": "query_expense",
    "get_todos": "query_todos",
    "get_weight": "query_weight",
    "query_notes": "query_notes",
    "search_notes": "query_notes",
}
_READ_ONLY_TOOLS = {
    "query_ledger",
    "query_expense",
    "query_todos",
    "query_weight",
    "query_notes",
}
_READ_QUERY_LEADS = (
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


def _looks_query_shaped(text: str) -> bool:
    lowered = text.lower().strip()
    leads = _READ_QUERY_LEADS
    return lowered.startswith(leads) or lowered.endswith("?")


_RETRIEVAL_VERB_PATTERNS = [
    # Past-tense self-reference: "anything i wrote / saved / jotted / mentioned"
    re.compile(r"\b(i\s+)?(wrote|jotted|saved|noted|mentioned|said|captured|logged|recorded)\b", re.IGNORECASE),
    # "the note about X", "the X note"
    re.compile(r"\bthe\s+(\w+\s+){0,4}note\b", re.IGNORECASE),
    re.compile(r"\bthe\s+note\s+(about|where|that|on|where|from)\b", re.IGNORECASE),
    # "anything about X", "anything saved on X"
    re.compile(r"\banything\s+(about|on|saved|i\s+wrote|i\s+jotted|i\s+saved)\b", re.IGNORECASE),
    # "everything X has said", "everything anand told"
    re.compile(r"\beverything\s+(\w+\s+){0,3}(has\s+said|told|said|wrote|noted)\b", re.IGNORECASE),
    # "look up X", "tell me about X", "remind me what", "give me my X"
    re.compile(r"^\s*(look\s+up|tell\s+me\s+about|remind\s+me\s+(what|of)|give\s+me\s+my|hand\s+me\s+my|i\s+need\s+my|share\s+my|paste\s+my|recall\s+my|recite\s+my|read\s+out\s+my|dump\s+my|display\s+my|surface\s+my|expose\s+my|excavate\s+my|dredge\s+up\s+my|bring\s+up\s+my|get\s+me\s+my|yield\s+my|walk\s+me\s+through\s+my)\b", re.IGNORECASE),
    # "X stuff", "X related entries", "things X told me", "conversations with X"
    re.compile(r"\b\w+\s+stuff\s*$", re.IGNORECASE),
    re.compile(r"\b\w+\s+related\s+entries\b", re.IGNORECASE),
    re.compile(r"\bthings\s+(\w+\s+){1,3}(told|said|mentioned)\b", re.IGNORECASE),
    re.compile(r"\bconversations?\s+with\s+\w+", re.IGNORECASE),
    # "anand's view on X", "X's view on Y", "X's take on Y"
    re.compile(r"\b\w+'s\s+(view|take|opinion|thoughts?)\s+(on|about)\b", re.IGNORECASE),
    # "X position sizing rule", "X advice", "X recommendation" — treat as retrieval
    re.compile(r"\b\w+\s+(advice|recommendation|opinion|view)\s*$", re.IGNORECASE),
    # Existence checks: "did i ever", "have i mentioned", "do i have", "is there a note"
    re.compile(r"\b(did\s+i\s+(ever|never)|have\s+i\s+(ever|never)?\s*(mentioned|jotted|written|saved|noted)|do\s+i\s+have|is\s+there\s+(a\s+note|anything|nothing)|haven't\s+i|nothing\s+(about|on))\b", re.IGNORECASE),
    # Comparison/aggregation phrasings
    re.compile(r"\b(biggest|smallest|highest|lowest|average|median|cumulative|running\s+total|growth|compare|top\s+\d+)\b", re.IGNORECASE),
]


def _looks_like_protected_read_intent(text: str, weight_people: set[str]) -> bool:
    lowered = text.lower().strip()
    word_count = len(lowered.split())

    if extract_note_query_args(text) is not None:
        return True
    if extract_weight_query_args(text, weight_people) is not None:
        return True
    if lowered.endswith("?") or lowered.startswith(_READ_QUERY_LEADS):
        return True
    if re.fullmatch(r"\w+\s+ledger", lowered):
        return True
    if word_count <= 8 and re.search(r"\bledger\b", lowered) and re.search(r"\b(history|summary|show|list|recent|last|involving|for)\b", lowered):
        return True
    if word_count <= 8 and re.search(r"\b(expense|expenses|bill|bills)\b", lowered) and re.search(
        r"\b(last|latest|recent|this month|current month|monthly|show|list|between|more\s+than|less\s+than)\b",
        lowered,
    ):
        return True
    if word_count <= 8 and re.search(r"\b(todo|todos|task|tasks)\b", lowered) and re.search(
        r"\b(show|list|pending|done|status|what)\b",
        lowered,
    ):
        return True
    if re.search(r"\bwho\s+owes\b", lowered) or "owes me" in lowered or "who do i owe" in lowered or "whom do i owe" in lowered:
        return True
    # Natural-language note-retrieval phrasings the LLM/fastpath miss.
    # Only consult these on short-ish inputs so we don't mis-classify long
    # prose that happens to contain a matched substring like "average".
    if word_count <= 12:
        for pattern in _RETRIEVAL_VERB_PATTERNS:
            if pattern.search(lowered):
                return True
    return False


_JOURNAL_QUESTION_LEAD_RE = re.compile(
    r"^\s*(why|how|should|is|are|am|was|were|do|does|did|can|could|would|will|what)\b",
    re.IGNORECASE,
)
_JOURNAL_FIRST_PERSON_RE = re.compile(r"\b(i|i'm|me|my|mine|myself)\b", re.IGNORECASE)
_JOURNAL_RETRIEVAL_TOKEN_RE = re.compile(
    r"\b(notes?|saved|search|find|show|list|tell\s+me\s+about|look\s+up|recall|paste|dump)\b",
    re.IGNORECASE,
)


def _looks_like_journal_question(text: str) -> bool:
    """First-person reflective question without an explicit retrieval token.

    Matches: "why does cipla keep going up?", "should i sell idfc?",
    "is meditation worth the time cost on busy weeks?".

    Doesn't match: "show me cipla notes", "what i wrote about cipla",
    "how much do i owe ravi" (latter is structured query).
    """
    lowered = text.strip().lower()
    if not lowered.endswith("?"):
        return False
    if not _JOURNAL_QUESTION_LEAD_RE.match(lowered):
        return False
    if not _JOURNAL_FIRST_PERSON_RE.search(lowered):
        return False
    if _JOURNAL_RETRIEVAL_TOKEN_RE.search(lowered):
        return False
    if re.search(r"\bhow\s+much\b", lowered) or "owes" in lowered or "balance" in lowered:
        return False
    return len(lowered.split()) >= 4


def _build_read_barrier_response(
    conn: sqlite3.Connection,
    text: str,
    reason: str,
    attempted_tool: str | None = None,
) -> OrchestratorResponse:
    if _looks_like_journal_question(text):
        options = [
            {"label": "Save as a journal note (reflection)", "tool": "add_note", "args": {"content": text}},
            {"label": "Search saved notes for this", "tool": "query_notes", "args": {"query": text}},
        ]
        return _persist_clarify(
            conn, text, None,
            "That sounds like a journal-style question. What should I do? (or reply 'skip')",
            options, source="journal_question",
        )
    return OrchestratorResponse(
        kind="clarification",
        response_text=(
            "That looks like a query, so I won't save it as new data automatically. "
            "Rephrase the query, or use note:/todo: if you intended a write."
        ),
        tier="tier1",
        parsed={"rule": "read_write_membrane", "reason": reason, "attempted_tool": attempted_tool},
        confidence=0.0,
    )


# Inputs that the deterministic fastpath got wrong in dogfooding. These
# always defer to the LLM planner so it can emit explicit SQL/note plans.
# Patterns are intentionally narrow — `last 3 jeevi weight` and
# `show me last 5 notes` should still fall through to the existing fastpath.
_FASTPATH_DEFER_PATTERNS = [
    # `last 3 expense`, `last 5 bills`, `last 3 transactions` — fastpath
    # mis-routed these to a SUM or to the write parser.
    re.compile(r"\blast\s+\d+\s+(expense|expenses|bill|bills|tx|transaction|transactions)\b", re.IGNORECASE),
    re.compile(r"\b(latest|recent)\s+(expense|expenses|bill|bills)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+much\b", re.IGNORECASE),         # "how much money i owe"
    re.compile(r"\b(weight|expense|ledger)\s+status\b", re.IGNORECASE),
    re.compile(r"\b(all|every)\s+(ledger|expense)s?\b", re.IGNORECASE),
    re.compile(r"^\s*(show\s+(me\s+)?)?(all|every)\s+notes?\b", re.IGNORECASE),
    re.compile(r"^\s*\w+\s+ledger\s*$", re.IGNORECASE),   # "maddy ledger" / "ravi ledger"
    re.compile(r"\bapart\s+from\b", re.IGNORECASE),       # exclusion semantics
    re.compile(r"\b(except|excluding|not\s+including)\b", re.IGNORECASE),
    # Singular `latest note` / `last note` (without count, without 's').
    re.compile(r"^\s*(latest|last)\s+note\s*$", re.IGNORECASE),
    re.compile(r"^\s*\w+\s+note\s*$", re.IGNORECASE),     # `vivekananda note` (singular)
]


def _should_defer_to_planner(text: str) -> bool:
    return any(pat.search(text) for pat in _FASTPATH_DEFER_PATTERNS)


def _try_fast_query_plan(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    weight_people: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse | None:
    if _should_defer_to_planner(text):
        return None

    # Long-form prose ("kerala trip retrospective. five days was the right
    # length...") sometimes contains a topic keyword that the legacy plan
    # treats as a search target. Skip the fastpath for long inputs and let
    # the legacy bridge save them as notes.
    if len(text.split()) > 12:
        return None

    plan = build_query_or_command_plan(text, conn)
    if not plan or plan.get("kind") != "query" or not plan.get("calls"):
        return None

    lowered = text.lower().strip()
    call = plan["calls"][0]
    tool_name = call.get("name")
    safe_query = False

    if tool_name == "query_notes":
        safe_query = extract_note_query_args(text) is not None
    elif tool_name == "query_expense":
        safe_query = any(word in lowered for word in ["spend", "spent", "expense", "spending"])
    elif tool_name == "query_ledger":
        # `<person> balance`, `who owes`, `who do i owe` only — bare "owe"
        # without a matched person is sent to the planner instead.
        safe_query = (
            "balance" in lowered
            or "who owes" in lowered or "owes me" in lowered
            or "who do i owe" in lowered or "whom do i owe" in lowered
        )
    elif tool_name == "get_todos":
        safe_query = any(
            word in lowered
            for word in ["todo", "task", "pending", "tasks", "done", "cleared", "completed", "finished"]
        )
    elif tool_name == "get_weight":
        safe_query = extract_weight_query_args(text, weight_people) is not None

    if not safe_query:
        return None

    response = _dispatch_legacy_plan(conn, text, persons, llm_service, embedding_service, perf=perf)
    if response:
        response.tier = "fastpath"
        parsed = dict(response.parsed or {})
        parsed["rule"] = "fast_query_plan"
        response.parsed = parsed
    return response


# ---------------------------------------------------------------------------
# LLM-driven planner: SQL-gen + note search
# ---------------------------------------------------------------------------


def _try_plan_query(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse | None:
    """Ask the LLM for a plan: read-only SQL, note search, clarify, or unknown.

    Always safe: SQL is run through `query_sql_result` which goes through the
    sql_safety gate (allowlisted tables, SELECT-only, row cap, timeout).
    """
    today = _now()
    with perf_timer(perf, "planner.total_ms"):
        with perf_timer(perf, "planner.llm_plan_ms"):
            plan = llm_service.plan_query(text, today, sorted(persons), perf=perf)
        plan = resolve_plan_relative_dates(plan, today)

    action = plan.get("action") if isinstance(plan, dict) else None

    if action == "sql_query":
        sql = str(plan.get("sql") or "").strip()
        params = list(plan.get("params") or [])
        intent = plan.get("intent")
        confidence = float(plan.get("confidence") or 0.0)
        if not sql:
            return None

        with perf_timer(perf, "planner.execute_sql_ms"):
            result = query_sql_result(conn, sql=sql, params=params, intent=intent, perf=perf)
        if result.get("is_error"):
            return _build_heuristic_clarify(conn, text, None)
        return OrchestratorResponse(
            kind="query",
            response_text=result["response_text"],
            tier="planner",
            parsed={
                "rule": "llm_sql",
                "intent": intent,
                "sql": sql,
                "params": params,
                "tables": result.get("tables"),
            },
            confidence=confidence,
        )

    if action == "note_query":
        query = str(plan.get("query") or "").strip()
        recent = bool(plan.get("recent"))
        limit = int(plan.get("limit") or 5)
        with perf_timer(perf, "planner.note_query_ms"):
            result = query_notes_result(
                conn, llm_service, embedding_service,
                query=query, recent=recent, limit=limit, perf=perf,
            )
        return OrchestratorResponse(
            kind="query",
            response_text=result["response_text"],
            tier="planner",
            parsed={"rule": "llm_note_query", "query": query, "recent": recent, "limit": limit},
            confidence=float(plan.get("confidence") or 0.0),
        )

    if action == "clarify":
        question = str(plan.get("question") or "Please clarify:")
        options = list(plan.get("options") or [])
        if not options:
            return None
        return _persist_clarify(conn, text, None, question, options, source="planner")

    return None


def _dispatch_legacy_plan(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse | None:
    plan = build_query_or_command_plan(text, conn)
    if not plan or not plan.get("calls"):
        return None
    call = plan["calls"][0]
    legacy_name = call.get("name")
    tool_name = _LEGACY_TOOL_MAP.get(legacy_name)
    if not tool_name:
        return None
    args = dict(call.get("arguments") or {})
    # Cross-domain override for note search — user-saved notes go to
    # 'general' but the legacy query plan often guesses 'investment' /
    # 'health' from substrings (e.g. "vivekananda" contains "anand").
    if tool_name == "query_notes":
        args.pop("domain", None)
        args.pop("top_k", None)
    response, debug = _dispatch_tool(
        conn, tool_name, args, text, persons, llm_service, embedding_service, perf=perf,
    )
    response.tier = "tier1_legacy"
    response.parsed = {"rule": "legacy_query_plan", "legacy_call": call, "dispatch": debug}
    return response


def _try_legacy_rules(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    weight_people: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse | None:
    """Bridge to existing rule-based query plan + write parser.

    Ordering is intent-driven: inputs with numbers that aren't query-shaped
    try the write parser FIRST (so 'milk 60' becomes an expense instead of a
    health-domain search). Inputs without numbers (or with query leads) try
    the query plan first.
    """
    has_number = bool(re.search(r"\d", text))
    query_shaped = _looks_query_shaped(text)
    word_count = len(text.split())
    # Prefer write-parser over query-plan when:
    #   - input has a number and isn't a question (e.g. "petrol 500", "milk 60"), OR
    #   - input is prose (>=6 words) with no query lead (e.g. a long note)
    # This stops the legacy plan from misrouting long-form notes to a
    # health/investment search just because of an unfortunate substring.
    prefer_write = (not query_shaped) and (has_number or word_count >= 6)

    if not prefer_write:
        response = _dispatch_legacy_plan(conn, text, persons, llm_service, embedding_service, perf=perf)
        if response:
            return response

    today = _now()
    rule_entries = parse_note_for_write(text, today=today, persons=persons | weight_people)

    # Multi-entry collapse: if comma-split produced any 'note' entries,
    # the comma was punctuation, not a record separator. Save the whole
    # input as a single free-form note.
    if rule_entries and len(rule_entries) > 1 and any(e.get("type") == "note" for e in rule_entries):
        response, debug = _dispatch_tool(
            conn, "add_note",
            {"content": text, "domain": "general"},
            text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "tier1_legacy"
        response.parsed = {"rule": "legacy_write_note", "merged_from": rule_entries, "dispatch": debug}
        return response

    if rule_entries and len(rule_entries) > 1 and all(
        e.get("type") in {"expense", "ledger", "weight", "todo"} for e in rule_entries
    ):
        response_text, capture_id = _execute_write_entries(conn, rule_entries, text, "tier1_legacy")
        return OrchestratorResponse(
            kind="write",
            response_text=response_text,
            tier="tier1_legacy",
            parsed={"rule": "legacy_write_multi", "entries": rule_entries},
            capture_id=capture_id,
        )

    entry = rule_entries[0] if rule_entries and len(rule_entries) == 1 else None
    parsed_type = entry.get("type") if entry else None

    if parsed_type == "expense":
        # Guard: prose with a stray number ("milk delivery was 30 mins late
        # today") gets parsed as expense=Rs.30 with description "milk
        # delivery was mins late today" — clearly wrong. Require either a
        # currency-style token OR a short input (<=4 words) to accept the
        # expense classification; otherwise treat as a free-form note.
        currency_token_re = re.compile(
            r"(?:\brs\.?|₹|\$|€|£|inr\b|usd\b|\b\d+(?:\.\d+)?\s*(?:k|l|lakh|cr)\b|\b\d+(?:\.\d+)?\s*rs\.?\b|\b\d{1,3}(?:,\d{2,3})+\b)",
            re.IGNORECASE,
        )
        has_currency_token = bool(currency_token_re.search(text))
        word_count_full = len(text.split())
        if not has_currency_token and word_count_full > 4:
            response, debug = _dispatch_tool(
                conn, "add_note",
                {"content": text, "domain": "general"},
                text, persons, llm_service, embedding_service, perf=perf,
            )
            response.tier = "tier1_legacy"
            response.parsed = {
                "rule": "legacy_write_note",
                "downgraded_from": "expense",
                "reason": "prose_no_currency",
                "dispatch": debug,
            }
            return response
        response, debug = _dispatch_tool(
            conn, "add_expense",
            {"amount": entry["amount"], "description": entry["description"]},
            text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "tier1_legacy"
        response.parsed = {"rule": "legacy_write_expense", "entry": entry, "dispatch": debug}
        return response

    if parsed_type == "ledger":
        response, debug = _dispatch_tool(
            conn, "add_ledger",
            {
                "person": entry["person"],
                "amount": entry["amount"],
                "direction": entry["direction"],
                "note": entry.get("note"),
            },
            text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "tier1_legacy"
        response.parsed = {"rule": "legacy_write_ledger", "entry": entry, "dispatch": debug}
        return response

    if parsed_type == "weight":
        response, debug = _dispatch_tool(
            conn, "add_weight",
            {"person": entry["person"], "weight": entry["weight"], "note": entry.get("note")},
            text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "tier1_legacy"
        response.parsed = {"rule": "legacy_write_weight", "entry": entry, "dispatch": debug}
        return response

    if parsed_type == "todo":
        response, debug = _dispatch_tool(
            conn, "add_todo", {"content": entry.get("content", text)},
            text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "tier1_legacy"
        response.parsed = {"rule": "legacy_write_todo", "entry": entry, "dispatch": debug}
        return response

    if parsed_type == "note":
        response, debug = _dispatch_tool(
            conn, "add_note",
            {"content": entry.get("content", text), "domain": entry.get("domain")},
            text, persons, llm_service, embedding_service, perf=perf,
        )
        response.tier = "tier1_legacy"
        response.parsed = {"rule": "legacy_write_note", "entry": entry, "dispatch": debug}
        return response

    if prefer_write:
        # Long prose that the rule parser couldn't categorize: save it as
        # a free-form note rather than letting the legacy query plan
        # interpret a stray topic word ("philosophy book chapter notes ...")
        # as a search request and lose the user's writing.
        if word_count >= 12:
            response, debug = _dispatch_tool(
                conn, "add_note",
                {"content": text, "domain": "general"},
                text, persons, llm_service, embedding_service, perf=perf,
            )
            response.tier = "tier1_legacy"
            response.parsed = {
                "rule": "legacy_write_note",
                "reason": "long_prose_default_note",
                "dispatch": debug,
            }
            return response
        # Number-bearing short input that didn't parse as a structured
        # write — fall back to the query plan as a last resort.
        response = _dispatch_legacy_plan(conn, text, persons, llm_service, embedding_service, perf=perf)
        if response:
            return response

    return None


def _tier1_route(
    conn: sqlite3.Connection,
    text: str,
    persons: set[str],
    llm_service: LLMService,
    embedding_service: EmbeddingService,
    perf: dict[str, float] | None = None,
) -> OrchestratorResponse:
    today = _now()
    protected_read = _looks_like_protected_read_intent(text, load_weight_persons(conn))
    with perf_timer(perf, "tier1.total_ms"):
        decision = llm_service.route_input(text, today, sorted(persons), perf=perf)

        if decision.get("unknown") is True:
            if protected_read:
                with perf_timer(perf, "tier1.legacy_fallback_ms"):
                    legacy = _dispatch_legacy_plan(conn, text, persons, llm_service, embedding_service, perf=perf)
                if legacy:
                    return legacy
                return _build_read_barrier_response(conn, text, reason="unknown_route")
            with perf_timer(perf, "tier1.legacy_fallback_ms"):
                legacy = _try_legacy_rules(
                    conn,
                    text,
                    persons,
                    load_weight_persons(conn),
                    llm_service,
                    embedding_service,
                    perf=perf,
                )
            if legacy:
                return legacy
            return _build_heuristic_clarify(conn, text, None)

        if decision.get("clarify") is True:
            question = str(decision.get("question") or "Please clarify:")
            options = list(decision.get("options") or [])
            if not any((opt.get("tool") == "add_note") for opt in options):
                options.append({"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}})
            return _persist_clarify(conn, text, None, question, options, source="llm")

        confidence = float(decision.get("confidence", 0) or 0)
        tool = decision.get("tool")
        args = decision.get("args") or {}

        if protected_read and tool and tool not in _READ_ONLY_TOOLS:
            with perf_timer(perf, "tier1.legacy_fallback_ms"):
                legacy = _dispatch_legacy_plan(conn, text, persons, llm_service, embedding_service, perf=perf)
            if legacy:
                return legacy
            return _build_read_barrier_response(conn, text, reason="blocked_write_tool", attempted_tool=str(tool))

        if not tool or confidence < CONFIDENCE_FLOOR:
            if protected_read:
                with perf_timer(perf, "tier1.legacy_fallback_ms"):
                    legacy = _dispatch_legacy_plan(conn, text, persons, llm_service, embedding_service, perf=perf)
                if legacy:
                    return legacy
                return _build_read_barrier_response(conn, text, reason="low_confidence", attempted_tool=str(tool) if tool else None)
            question = "I'm not fully sure. Pick one:"
            options = []
            if tool:
                options.append({"label": f"Yes — {tool} with {args}", "tool": tool, "args": args})
            options.append({"label": "Save as a note (searchable)", "tool": "add_note", "args": {"content": text}})
            options.append({"label": "Save as a todo", "tool": "add_todo", "args": {"content": text}})
            options.append({"label": "Save as raw note (don't categorize)", "tool": "add_note", "args": {"content": text}})
            return _persist_clarify(conn, text, None, question, options, source="low_confidence")

        response, _ = _dispatch_tool(conn, tool, args, text, persons, llm_service, embedding_service, perf=perf)
        response.confidence = confidence
        return response


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


_default_llm: LLMService | None = None
_default_embed: EmbeddingService | None = None


def _services() -> tuple[LLMService, EmbeddingService]:
    global _default_llm, _default_embed
    if _default_llm is None:
        _default_llm = LLMService()
    if _default_embed is None:
        _default_embed = EmbeddingService()
    return _default_llm, _default_embed


def get_runtime_services() -> tuple[LLMService, EmbeddingService]:
    return _services()


def warm_runtime_services() -> dict[str, Any]:
    perf: dict[str, float] = {}
    llm_service, embedding_service = _services()
    parser_status = {"enabled": finetuned_parser_enabled(), "loaded": False}
    with perf_timer(perf, "startup_warm.total_ms"):
        with perf_timer(perf, "startup_warm.llm_backend_ms"):
            llm_status = llm_service.status()
        embedding_ready = embedding_service.encode("startup warmup", perf=perf, label="startup_warm.embedding") is not None
        summary_warmed = False
        if llm_status.get("backend") not in {None, "mock"}:
            with perf_timer(perf, "startup_warm.summary_ms"):
                llm_service.summarize_rag(
                    "startup warmup",
                    "general",
                    [{"content": "startup warmup note", "source": "warmup"}],
                    perf=perf,
                )
            summary_warmed = True
        if finetuned_parser_enabled():
            with perf_timer(perf, "startup_warm.finetuned_parser_ms"):
                parser_status = warm_finetuned_parser(perf=perf)
    return {
        "llm_backend": llm_status.get("backend"),
        "embedding_ready": embedding_ready,
        "summary_warmed": summary_warmed,
        "finetuned_parser": parser_status,
        "timings_ms": perf,
    }


def handle(
    text: str,
    db_path: str = DEFAULT_DB_PATH,
    fallthrough: Callable[[str], dict[str, Any]] | None = None,  # legacy hook, unused post step 4
    llm_service: LLMService | None = None,
    embedding_service: EmbeddingService | None = None,
) -> OrchestratorResponse:
    perf: dict[str, float] = {}
    response: OrchestratorResponse

    with perf_timer(perf, "orchestrator.total_ms"):
        text = (text or "").strip()
        if not text:
            response = OrchestratorResponse(
                kind="unknown",
                response_text="No input provided.",
                tier="tier0",
                parsed={"reason": "empty_input"},
            )
        else:
            with perf_timer(perf, "orchestrator.service_bind_ms"):
                if llm_service is None or embedding_service is None:
                    d_llm, d_embed = _services()
                    llm_service = llm_service or d_llm
                    embedding_service = embedding_service or d_embed

            today = _now()

            with perf_timer(perf, "orchestrator.db_connect_ms"):
                conn = db_connection(db_path)
            try:
                with perf_timer(perf, "orchestrator.pending_check_ms"):
                    pending_persons = load_known_persons(conn)
                    resolution = _resolve_pending(
                        conn,
                        text,
                        pending_persons,
                        llm_service,
                        embedding_service,
                        perf=perf,
                    )
                if resolution:
                    with perf_timer(perf, "orchestrator.commit_ms"):
                        conn.commit()
                    response = resolution
                else:
                    with perf_timer(perf, "orchestrator.load_persons_ms"):
                        persons = load_known_persons(conn)
                        weight_people = load_weight_persons(conn)

                    with perf_timer(perf, "tier0.person_command_ms"):
                        cmd = parse_person_command(text)
                    if cmd:
                        with perf_timer(perf, "tier0.person_command_execute_ms"):
                            response_text, note_id, is_error = _execute_person_command(conn, cmd, text)
                        with perf_timer(perf, "orchestrator.commit_ms"):
                            conn.commit()
                        response = OrchestratorResponse(
                            kind="person_command",
                            response_text=response_text,
                            tier="tier0",
                            parsed={"rule": "person_command", "command": cmd, "is_error": is_error},
                            note_id=note_id,
                        )
                    else:
                        with perf_timer(perf, "tier0.explicit_note_ms"):
                            note_body = extract_explicit_note_body(text)
                        if note_body:
                            with perf_timer(perf, "tier0.explicit_note_execute_ms"):
                                response_text, note_id, _ = _save_plain_note(
                                    conn,
                                    embedding_service,
                                    note_body,
                                    text,
                                    "tier0",
                                    perf=perf,
                                )
                            with perf_timer(perf, "orchestrator.commit_ms"):
                                conn.commit()
                            response = OrchestratorResponse(
                                kind="write",
                                response_text=response_text,
                                tier="tier0",
                                parsed={"rule": "explicit_note"},
                                note_id=note_id,
                            )
                        else:
                            with perf_timer(perf, "finetuned.try_ms"):
                                finetuned = _try_finetuned_route(
                                    conn,
                                    text,
                                    persons,
                                    llm_service,
                                    embedding_service,
                                    perf=perf,
                                )
                            if finetuned:
                                with perf_timer(perf, "orchestrator.commit_ms"):
                                    conn.commit()
                                response = finetuned
                            else:
                                explicit_todo_body = extract_explicit_todo_body(text)
                                if explicit_todo_body:
                                    with perf_timer(perf, "tier0.explicit_todo_ms"):
                                        todo_items = split_todo_items(explicit_todo_body)
                                    todo_entries = [
                                        {"type": "todo", "content": item, "raw": item}
                                        for item in todo_items
                                    ]
                                    with perf_timer(perf, "tier0.explicit_todo_execute_ms"):
                                        if len(todo_entries) == 1:
                                            response_text, capture_id, _ = _execute_write_entry(
                                                conn,
                                                embedding_service,
                                                todo_entries[0],
                                                text,
                                            )
                                        else:
                                            response_text, capture_id = _execute_write_entries(conn, todo_entries, text, "tier0")
                                    with perf_timer(perf, "orchestrator.commit_ms"):
                                        conn.commit()
                                    response = OrchestratorResponse(
                                        kind="write",
                                        response_text=response_text,
                                        tier="tier0",
                                        parsed={"rule": "explicit_todo", "entries": todo_entries},
                                        capture_id=capture_id,
                                    )
                                else:
                                    with perf_timer(perf, "tier0.explicit_todo_ms"):
                                        todo_entry = _try_explicit_todo(text)
                                    if todo_entry:
                                        with perf_timer(perf, "tier0.explicit_todo_execute_ms"):
                                            response_text, capture_id, _ = _execute_write_entry(conn, embedding_service, todo_entry, text)
                                        with perf_timer(perf, "orchestrator.commit_ms"):
                                            conn.commit()
                                        response = OrchestratorResponse(
                                            kind="write",
                                            response_text=response_text,
                                            tier="tier0",
                                            parsed={"rule": "explicit_todo", "entry": todo_entry},
                                            capture_id=capture_id,
                                        )
                                    else:
                                        with perf_timer(perf, "tier0.weight_write_ms"):
                                            weight_entry = _try_weight_write(text, weight_people, today)
                                        if weight_entry:
                                            with perf_timer(perf, "tier0.weight_write_execute_ms"):
                                                response_text, capture_id, _ = _execute_write_entry(conn, embedding_service, weight_entry, text)
                                            with perf_timer(perf, "orchestrator.commit_ms"):
                                                conn.commit()
                                            response = OrchestratorResponse(
                                                kind="write",
                                                response_text=response_text,
                                                tier="tier0",
                                                parsed={"rule": "weight_write", "entry": weight_entry},
                                                capture_id=capture_id,
                                            )
                                        else:
                                            with perf_timer(perf, "tier0.settlement_ms"):
                                                settlement_meta = _try_settlement(text)
                                            if settlement_meta:
                                                with perf_timer(perf, "tier0.settlement_execute_ms"):
                                                    response_text, note_id, kind = _execute_settlement(conn, text, settlement_meta)
                                                with perf_timer(perf, "orchestrator.commit_ms"):
                                                    conn.commit()
                                                response = OrchestratorResponse(
                                                    kind=kind,
                                                    response_text=response_text,
                                                    tier="tier0",
                                                    parsed={"rule": "settlement_phrase", "match": settlement_meta},
                                                    note_id=note_id,
                                                )
                                            else:
                                                with perf_timer(perf, "routing_memory.lookup_ms"):
                                                    memo = lookup_routing_memory(conn, normalize_input(text))
                                                if memo:
                                                    if _looks_like_protected_read_intent(text, weight_people) and memo["tool"] not in _READ_ONLY_TOOLS:
                                                        response = _build_read_barrier_response(
                                                            conn,
                                                            text,
                                                            reason="blocked_memo_write_tool",
                                                            attempted_tool=str(memo["tool"]),
                                                        )
                                                        with perf_timer(perf, "orchestrator.commit_ms"):
                                                            conn.commit()
                                                        return _attach_timings(response, perf)
                                                    with perf_timer(perf, "routing_memory.dispatch_ms"):
                                                        response, debug = _dispatch_tool(
                                                            conn,
                                                            memo["tool"],
                                                            memo["args"],
                                                            text,
                                                            persons,
                                                            llm_service,
                                                            embedding_service,
                                                            perf=perf,
                                                        )
                                                    response.tier = "memo"
                                                    response.parsed = {"rule": "user_routing_memory", "memo": memo, "dispatch": debug}
                                                    response.confidence = 1.0
                                                    with perf_timer(perf, "orchestrator.commit_ms"):
                                                        conn.commit()
                                                else:
                                                    with perf_timer(perf, "fastpath.query_plan_ms"):
                                                        fast_query = _try_fast_query_plan(
                                                            conn,
                                                            text,
                                                            persons,
                                                            weight_people,
                                                            llm_service,
                                                            embedding_service,
                                                            perf=perf,
                                                        )
                                                    if fast_query:
                                                        response = fast_query
                                                    else:
                                                        with perf_timer(perf, "planner.try_ms"):
                                                            planned = _try_plan_query(
                                                                conn,
                                                                text,
                                                                persons,
                                                                llm_service,
                                                                embedding_service,
                                                                perf=perf,
                                                            )
                                                        if planned:
                                                            response = planned
                                                        else:
                                                            response = _tier1_route(
                                                                conn,
                                                                text,
                                                                persons,
                                                                llm_service,
                                                                embedding_service,
                                                                perf=perf,
                                                            )
                                                    with perf_timer(perf, "orchestrator.commit_ms"):
                                                        conn.commit()
            finally:
                conn.close()

    return _attach_timings(response, perf)
