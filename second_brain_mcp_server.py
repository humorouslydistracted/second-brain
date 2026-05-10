from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from second_brain_core import (
    APP_DIR,
    DEFAULT_DB_PATH,
    EmbeddingService,
    LLMService,
    add_entry_result,
    capture_note_result,
    db_connection,
    ensure_activity_log_schema,
    handle_input_result,
    get_todos_result,
    get_weight_result,
    load_known_persons,
    manage_persons_result,
    prepare_ledger_settlement_result,
    query_expense_result,
    query_ledger_result,
    query_sql_result,
    resolve_pending_action_result,
    route_input_plan,
    search_notes_result,
)

mcp = FastMCP(
    name="Second Brain MCP",
    instructions=(
        "SQLite-backed note-taking server with real tools for parsing, writes, "
        "structured queries, person management, and RAG-backed note search."
    ),
    log_level="ERROR",
    host=os.environ.get("SECOND_BRAIN_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("SECOND_BRAIN_MCP_PORT", "8765")),
)

_llm_service = LLMService()
_embedding_service = EmbeddingService()


def _open_db():
    ensure_activity_log_schema(DEFAULT_DB_PATH)
    return db_connection(DEFAULT_DB_PATH)


@mcp.resource("project://development")
def project_development_resource() -> str:
    """Read the project development tracker."""
    return Path(APP_DIR, "project_development.md").read_text(encoding="utf-8")


@mcp.resource("people://known")
def known_people_resource() -> str:
    """Read the known persons whitelist."""
    with _open_db() as conn:
        people = sorted(load_known_persons(conn))
    return json.dumps({"persons": people}, ensure_ascii=False, indent=2)


@mcp.resource("sqlite://schema")
def sqlite_schema_resource() -> str:
    """Read the SQLite schema."""
    with _open_db() as conn:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY type, name"
        ).fetchall()
    payload = [{"type": row["type"], "name": row["name"], "sql": row["sql"]} for row in rows]
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def route_input(text: str) -> dict[str, Any]:
    """Route a user note or question to the right Second Brain tool plan."""
    with _open_db() as conn:
        return route_input_plan(text, conn, _llm_service)


@mcp.tool()
def handle_input(text: str) -> dict[str, Any]:
    """Handle one bottom-bar input end to end through notes, SQL tools, and RAG."""
    try:
        with _open_db() as conn:
            result = handle_input_result(conn, _llm_service, _embedding_service, text)
            conn.commit()
            return result
    except Exception as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def capture_note(text: str) -> dict[str, Any]:
    """Save a raw note, extract structured facts, and embed note-like content."""
    try:
        with _open_db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes (content, input_kind) VALUES (?, 'note')",
                (text.strip(),),
            ).lastrowid
            result = capture_note_result(conn, _llm_service, _embedding_service, text, int(note_id))
            conn.commit()
            return result
    except Exception as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def prepare_ledger_settlement(text: str) -> dict[str, Any]:
    """Create a numbered selection when a settlement note is ambiguous."""
    try:
        with _open_db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes (content, input_kind) VALUES (?, 'note')",
                (text.strip(),),
            ).lastrowid
            result = prepare_ledger_settlement_result(conn, int(note_id))
            conn.commit()
            return result
    except Exception as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def resolve_pending_action(selection_text: str) -> dict[str, Any]:
    """Resolve the latest pending numbered action using the user's reply."""
    try:
        with _open_db() as conn:
            note_id = conn.execute(
                "INSERT INTO notes (content, input_kind) VALUES (?, 'resolution_reply')",
                (selection_text.strip(),),
            ).lastrowid
            result = resolve_pending_action_result(conn, selection_text, int(note_id))
            if result is None:
                result = {"kind": "unknown", "response_text": "No matching pending action."}
            conn.commit()
            return result
    except Exception as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def add_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Insert a parsed note into expenses, ledger, weights, or todos."""
    try:
        with _open_db() as conn:
            result = add_entry_result(conn, entry)
            conn.commit()
            return result
    except Exception as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def manage_persons(
    operation: str,
    name: str | None = None,
    old_name: str | None = None,
    new_name: str | None = None,
) -> dict[str, Any]:
    """Add, remove, or rename a person in the whitelist."""
    with _open_db() as conn:
        result = manage_persons_result(conn, operation, name=name, old_name=old_name, new_name=new_name)
        conn.commit()
        return result


@mcp.tool()
def query_ledger(query_type: str = "balance", person: str | None = None) -> dict[str, Any]:
    """Query balances or list who owes money."""
    with _open_db() as conn:
        return query_ledger_result(conn, query_type=query_type, person=person)


@mcp.tool()
def query_expense(
    month: str | None = None,
    description_like: str | None = None,
    list_mode: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    """Query expense totals or return an expense list."""
    with _open_db() as conn:
        return query_expense_result(
            conn,
            month=month,
            description_like=description_like,
            list_mode=list_mode,
            limit=limit,
        )


@mcp.tool()
def get_todos(status: str = "pending", limit: int = 20) -> dict[str, Any]:
    """List pending or done todos."""
    with _open_db() as conn:
        return get_todos_result(conn, status=status, limit=limit)


@mcp.tool()
def get_weight(person: str, limit: int = 1) -> dict[str, Any]:
    """Get the latest weight or weight trend for a known person."""
    with _open_db() as conn:
        return get_weight_result(conn, person=person, limit=limit)


@mcp.tool()
def search_notes(query: str, domain: str, top_k: int = 3) -> dict[str, Any]:
    """Run RAG over investment or health notes and summarize the hits."""
    with _open_db() as conn:
        return search_notes_result(
            conn,
            llm_service=_llm_service,
            embedding_service=_embedding_service,
            query=query,
            domain=domain,
            top_k=top_k,
        )


@mcp.tool()
def query_sql(sql: str, params: list[Any] | None = None, intent: str | None = None) -> dict[str, Any]:
    """Run an LLM-generated read-only SQL query through the safety gate.

    Only SELECT statements against the structured-data tables (expenses,
    ledger, ledger_balance, weights, todos, persons) are allowed. Any
    statement that fails validation returns a rejection response rather
    than executing.
    """
    with _open_db() as conn:
        return query_sql_result(conn, sql=sql, params=params or [], intent=intent)


@mcp.tool()
def server_status() -> dict[str, Any]:
    """Return backend status for DB, LLM, and embeddings."""
    return {
        "db_path": DEFAULT_DB_PATH,
        "llm": _llm_service.status(),
        "embeddings": _embedding_service.status(),
    }


if __name__ == "__main__":
    transport = os.environ.get("SECOND_BRAIN_MCP_TRANSPORT", "streamable-http")
    if len(sys.argv) > 1:
        transport = sys.argv[1]
    mcp.run(transport=transport)
