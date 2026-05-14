"""SQL safety gate for LLM-generated read-only queries.

The orchestrator lets the planner LLM emit SQL when natural-language queries
get too combinatorial for deterministic rules (e.g. "expenses apart from
petrol last month"). That SQL is treated as untrusted: it goes through this
gate before it ever reaches the database.

Rules enforced:
  - SELECT only (or a WITH whose body is SELECT, plus UNION of SELECTs)
  - One statement per call
  - Every Table reference must be in ALLOWED_TABLES
  - No PRAGMA / ATTACH / DETACH / DROP / CREATE / ALTER / Transaction / Command
  - Read-only sqlite connection (mode=ro) for execution
  - Hard row cap and statement timeout
  - Param values must be primitives (str / int / float / bool / None)

Use:
    from sql_safety import validate_sql, execute_safe, SqlSafetyError
    rows = execute_safe(sql, params, db_path=DB_PATH)
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import expressions as exp


ALLOWED_TABLES = frozenset({
    "expenses",
    "ledger",
    "ledger_balance",
    "weights",
    "todos",
    "persons",
})

DEFAULT_ROW_CAP = 100
DEFAULT_TIMEOUT_MS = 2000


def _banned_types() -> tuple[type, ...]:
    names = (
        "Insert", "Update", "Delete", "Merge",
        "Drop", "Create", "Alter", "AlterColumn", "TruncateTable",
        "Pragma", "Attach", "Detach", "Command", "Transaction",
    )
    found: list[type] = []
    for name in names:
        node_type = getattr(exp, name, None)
        if node_type is not None:
            found.append(node_type)
    return tuple(found)


_BANNED_TYPES = _banned_types()


class SqlSafetyError(Exception):
    """Raised when a candidate SQL statement fails the safety gate."""


@dataclass
class SafetyResult:
    ok: bool
    reason: str | None = None
    tables: frozenset[str] = field(default_factory=frozenset)


def validate_sql(sql: str) -> SafetyResult:
    """Inspect a candidate SQL string and decide if it may be executed.

    The expression is parsed with sqlglot's SQLite dialect. Anything we can't
    statically prove safe is rejected with a reason — never silently allowed.
    """
    if not isinstance(sql, str):
        return SafetyResult(False, "SQL must be a string")

    text = sql.strip()
    if not text:
        return SafetyResult(False, "Empty SQL")

    try:
        statements = sqlglot.parse(text, read="sqlite")
    except Exception as exc:
        return SafetyResult(False, f"SQL parse error: {exc}")

    # sqlglot strips comments during parse, so multi-statement detection here
    # is comment-safe — a `;` inside /* ... */ stays one statement.
    statements = [stmt for stmt in statements if stmt is not None]
    if len(statements) != 1:
        return SafetyResult(False, "Exactly one statement required")

    expression = statements[0]

    # Top-level must be SELECT-shaped.
    head = expression
    if isinstance(head, exp.With):
        head = head.this
    if not isinstance(head, (exp.Select, exp.Union)):
        return SafetyResult(False, f"Only SELECT/UNION queries are allowed (got {type(expression).__name__})")

    # Reject any mutating / DDL / privileged node anywhere in the AST.
    for banned in _BANNED_TYPES:
        if next(expression.find_all(banned), None) is not None:
            return SafetyResult(False, f"Disallowed clause: {banned.__name__}")

    # CTE names are virtual tables introduced by the query itself; exempt
    # them from the allowlist check (the CTE body is still validated since
    # we walk every Table node below).
    cte_names = {
        (cte.alias_or_name or "").lower()
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    }

    # All Table refs must be in the allowlist (or in cte_names); no schema qualifiers.
    referenced: set[str] = set()
    for table in expression.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            return SafetyResult(False, "Unnamed table reference")
        if name.startswith("sqlite_"):
            return SafetyResult(False, f"Internal table not allowed: {name}")
        if getattr(table, "db", "") and table.db:
            return SafetyResult(False, "Schema-qualified tables not allowed")
        if name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            return SafetyResult(False, f"Table not allowed: {name}")
        referenced.add(name)

    if not referenced:
        return SafetyResult(False, "Statement references no tables")

    return SafetyResult(True, tables=frozenset(referenced))


def open_readonly_connection(db_path: str) -> sqlite3.Connection:
    """Open an sqlite connection in mode=ro, with row factory."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _install_progress_cancel(conn: sqlite3.Connection, timeout_ms: int) -> None:
    if timeout_ms <= 0:
        return
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    def _abort() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(_abort, 1000)


def _check_params(params: list[Any] | tuple[Any, ...] | None) -> list[Any]:
    if params is None:
        return []
    bound = list(params)
    for value in bound:
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise SqlSafetyError(f"Param of unsupported type: {type(value).__name__}")
    return bound


@dataclass
class SafeQueryResult:
    rows: list[sqlite3.Row]
    column_names: list[str]
    truncated: bool
    tables: frozenset[str]


def execute_safe(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    db_path: str | None = None,
    row_cap: int = DEFAULT_ROW_CAP,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    conn: sqlite3.Connection | None = None,
) -> SafeQueryResult:
    """Validate and execute LLM-generated SQL.

    Returns a SafeQueryResult; raises SqlSafetyError on validation or
    execution failure (incl. timeout).
    """
    safety = validate_sql(sql)
    if not safety.ok:
        raise SqlSafetyError(safety.reason or "rejected")

    bound = _check_params(params)

    owns_conn = False
    if conn is None:
        if not db_path:
            raise SqlSafetyError("execute_safe requires conn or db_path")
        conn = open_readonly_connection(db_path)
        owns_conn = True

    try:
        _install_progress_cancel(conn, timeout_ms)
        cursor = conn.execute(sql, bound)
        column_names = [desc[0] for desc in (cursor.description or [])]
        fetched = cursor.fetchmany(row_cap + 1)
        truncated = len(fetched) > row_cap
        rows = fetched[:row_cap]
        return SafeQueryResult(
            rows=rows,
            column_names=column_names,
            truncated=truncated,
            tables=safety.tables,
        )
    except sqlite3.Error as exc:
        raise SqlSafetyError(f"sqlite error: {exc}") from exc
    finally:
        if owns_conn:
            try:
                conn.set_progress_handler(None, 0)
            except Exception:
                pass
            conn.close()


def format_rows(result: SafeQueryResult, max_lines: int = 20) -> str:
    """Deterministically render rows as a short text block.

    Single-aggregate (one row, one column) → just the value.
    Otherwise: header + up to max_lines rows + "(N more)" if truncated.
    """
    if not result.rows:
        return "No matching entries."

    if len(result.rows) == 1 and len(result.column_names) == 1:
        return str(result.rows[0][0])

    lines = [" | ".join(result.column_names)]
    for row in result.rows[:max_lines]:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    extra = len(result.rows) - max_lines
    if extra > 0:
        lines.append(f"({extra} more rows)")
    if result.truncated:
        lines.append(f"(result capped at {DEFAULT_ROW_CAP} rows)")
    return "\n".join(lines)
