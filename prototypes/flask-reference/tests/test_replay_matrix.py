from __future__ import annotations

import csv
import importlib
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any


APP_DIR = Path(__file__).resolve().parent
LOGS_PATH = APP_DIR / "logs.txt"
SOURCE_DB_PATH = APP_DIR / "second_brain.db"
ARTIFACT_DIR = APP_DIR / "artifacts" / "replay_matrix"
TMP_DIR = APP_DIR / ".tmp" / "replay_matrix"
INPUT_MARKER = "\u203a "
TABLES = [
    "activity_log",
    "notes",
    "captures",
    "expenses",
    "ledger",
    "weights",
    "todos",
    "pending_actions",
    "user_routing_memory",
    "embeddings",
    "persons",
]
KIND_PREFIXES = ("write", "query", "clarification", "unknown", "person_command")


@dataclass
class HistoricalEntry:
    source_order_desc: int
    input_text: str
    logged_kind: str | None
    logged_timestamp: str | None
    logged_response: str
    logged_parsed_line: str | None
    logged_time_line: str | None
    logged_rule: str | None = None
    logged_tier: str | None = None
    logged_confidence: float | None = None


@dataclass
class ReplayCase:
    case_id: str
    text: str
    source: str
    mode: str
    probe_family: str
    scenario: str
    anchor_text: str | None = None
    notes: str | None = None
    historical: HistoricalEntry | None = None


@dataclass
class ReplayResult:
    case_id: str
    source: str
    mode: str
    probe_family: str
    scenario: str
    input_text: str
    anchor_text: str | None
    notes: str | None
    http_status: int
    activity_log_id: int | None
    actual_kind: str | None
    actual_response_text: str | None
    actual_tier: str | None
    actual_rule: str | None
    actual_confidence: float | None
    actual_note_id: int | None
    actual_timing_summary: str | None
    total_ms: float | None
    timings_ms: dict[str, float] = field(default_factory=dict)
    table_changes: dict[str, Any] = field(default_factory=dict)
    historical_comparison: dict[str, Any] | None = None


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def strip_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def parse_parsed_line(line: str | None) -> dict[str, Any]:
    if not line:
        return {"raw": None, "rule": None, "tier": None, "confidence": None}
    body = line.strip()
    if body.startswith("[parsed:") and body.endswith("]"):
        body = body[len("[parsed:") : -1].strip()
    tokens = [token.strip() for token in body.split("·")]
    tier = None
    rule = tokens[0] if tokens else None
    confidence = None
    for token in tokens:
        lowered = token.lower()
        if lowered.startswith("conf "):
            try:
                confidence = float(lowered.split(" ", 1)[1])
            except ValueError:
                confidence = None
        if lowered in {"tier0", "tier1_legacy", "planner", "fastpath", "memo", "error"}:
            tier = lowered
    return {
        "raw": body,
        "rule": rule,
        "tier": tier,
        "confidence": confidence,
    }


def parse_logs(path: Path) -> list[HistoricalEntry]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[HistoricalEntry] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith(INPUT_MARKER):
            index += 1
            continue

        input_text = line[len(INPUT_MARKER) :]
        index += 1

        logged_kind = None
        logged_timestamp = None
        if index < len(lines):
            kind_line = lines[index].strip()
            parts = kind_line.split()
            if parts and parts[0] in KIND_PREFIXES:
                logged_kind = parts[0]
                logged_timestamp = " ".join(parts[1:]) if len(parts) > 1 else None
                index += 1

        response_lines: list[str] = []
        parsed_line = None
        time_line = None
        while index < len(lines) and not lines[index].startswith(INPUT_MARKER):
            current = lines[index]
            if current.startswith("[parsed:") and current.endswith("]"):
                parsed_line = current
            elif current.startswith("[time:") and current.endswith("]"):
                time_line = current
            else:
                response_lines.append(current)
            index += 1

        parsed = parse_parsed_line(parsed_line)
        entries.append(
            HistoricalEntry(
                source_order_desc=len(entries) + 1,
                input_text=input_text,
                logged_kind=logged_kind,
                logged_timestamp=logged_timestamp,
                logged_response="\n".join(strip_blank_edges(response_lines)),
                logged_parsed_line=parsed_line,
                logged_time_line=time_line,
                logged_rule=parsed["rule"],
                logged_tier=parsed["tier"],
                logged_confidence=parsed["confidence"],
            )
        )
    return entries


def build_historical_cases(entries: list[HistoricalEntry]) -> list[ReplayCase]:
    chronological = list(reversed(entries))
    cases: list[ReplayCase] = []
    for index, entry in enumerate(chronological, start=1):
        cases.append(
            ReplayCase(
                case_id=f"H{index:03d}",
                text=entry.input_text,
                source="historical_logs",
                mode="stateful",
                probe_family="historical_replay",
                scenario="historical_log_replay",
                anchor_text=entry.input_text,
                historical=entry,
                notes="Replayed from logs.txt in chronological order.",
            )
        )
    return cases


def build_variant_cases(existing_inputs: set[str]) -> list[ReplayCase]:
    cases: list[ReplayCase] = []
    seen = set(existing_inputs)

    def add(
        text: str,
        family: str,
        scenario: str,
        *,
        anchor: str | None = None,
        notes: str | None = None,
    ) -> None:
        normalized = normalize_text(text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        cases.append(
            ReplayCase(
                case_id=f"V{len(cases) + 1:03d}",
                text=text,
                source="generated_variant",
                mode="stateful",
                probe_family=family,
                scenario=scenario,
                anchor_text=anchor,
                notes=notes,
            )
        )

    note_topics = [
        ("vivekananda", "vivekananda kept travelling and neglected his rest"),
        ("fundera park", "fundera park may need one more visit before judging it"),
        ("mcp", "mcp progress still needs a concise status note for Amit"),
        ("cipla", "cipla needs better notes before any decision is made"),
        ("tamilnad mercentile bank", "tamilnad mercentile bank deserves a deeper review note"),
    ]
    for topic, content in note_topics:
        add(
            f"note: {content}",
            "note_write",
            f"notes_{topic}",
            anchor=f"note: {topic}",
            notes="Explicit note write derived from observed note-topic inputs.",
        )
        add(
            f"remember that {content}",
            "note_write",
            f"notes_{topic}",
            anchor=topic,
            notes="Free-form note write using the same observed topic.",
        )
        add(
            f"show notes about {topic}",
            "note_query",
            f"notes_{topic}",
            anchor=f"give me notes about {topic}",
        )
        add(
            f"find {topic} in my notes",
            "note_query",
            f"notes_{topic}",
            anchor=f"any info of {topic} in our notes",
        )
        add(
            f"search my notes for {topic}",
            "note_query",
            f"notes_{topic}",
            anchor=f"any mention of {topic} in the notes",
        )
    for text in [
        "show recent notes",
        "show latest 3 notes",
        "show me the last 7 notes",
        "recent saved notes",
        "what are my latest notes",
        "show all saved notes",
        "latest saved note",
        "show note snippets about vivekananda",
        "do i have notes about mcp",
        "any note on fundera park in my notes",
    ]:
        add(text, "note_query", "notes_recency", anchor="show me saved notes")

    todo_contents = [
        "update maddy about datascience in iit chennai",
        "call Amit about MCP",
        "renew driving license",
        "book briyani festival tickets",
        "complete cipla notes review",
    ]
    for content in todo_contents:
        verb = content.split()[0].lower()
        add(
            f"todo: {content}",
            "todo_write",
            "todo_batch",
            anchor="todo: update maddy to explore about datascience in iit chennai",
        )
        add(
            f"todo {content}",
            "todo_write",
            "todo_batch",
            anchor="todo update maddy to explore about datascience in iit chennai",
        )
        add(
            f"remind me to {content}",
            "todo_write",
            "todo_batch",
            anchor="update the status about mcp to Amit",
        )
        add(
            f"{verb} reminder for {content}",
            "todo_probe",
            "todo_batch",
            anchor="todo list pls",
            notes="Short ambiguous todo-like probe derived from observed action text.",
        )
    for text in [
        "show pending todo list",
        "show pending tasks",
        "show done todos",
        "pending todo list",
        "done task list",
        "what is on my todo list",
        "list pending reminders",
    ]:
        add(text, "todo_query", "todo_queries", anchor="show todo list")

    weight_specs = [
        ("jeevi", 64.2, 64.4),
        ("prani", 11.8, 12.0),
        ("murugan", 65.8, 66.1),
    ]
    for person, base_value, contextual_value in weight_specs:
        add(
            f"{person} {base_value}",
            "weight_write",
            f"weights_{person}",
            anchor=f"{person} 62",
        )
        add(
            f"{person} weight {contextual_value} after lunch",
            "weight_write",
            f"weights_{person}",
            anchor=f"{person} weight 65.3",
        )
        add(
            f"{person} weight",
            "weight_query",
            f"weights_{person}",
            anchor=f"{person} weight",
        )
        add(
            f"latest weight of {person}",
            "weight_query",
            f"weights_{person}",
            anchor=f"latest weight of {person}",
        )
        add(
            f"last 2 {person} weight",
            "weight_query",
            f"weights_{person}",
            anchor=f"last 3 {person} weight",
        )
        add(
            f"show last 4 {person} weight with date",
            "weight_query",
            f"weights_{person}",
            anchor=f"show last 3 {person} weight with date",
        )

    expense_variants = [
        ("petrol 650", "expense_write", "expenses_writes", "petrol 500"),
        ("ginger 45", "expense_write", "expenses_writes", "ginger 35"),
        ("milk 70", "expense_write", "expenses_writes", "milk 60"),
        ("tea & snacks 85", "expense_write", "expenses_writes", "tea & snacks 30"),
        ("food 350, water bottle 25, pepsi 120", "expense_write", "expenses_writes", "food 300, water bottle 20, tea & snacks 30, lays 50, pepsi 100"),
        ("groceries 1450", "expense_write", "expenses_writes", "groceries expense for this month"),
        ("electricity 900", "expense_write", "expenses_writes", "expense status"),
        ("what is my current month expense", "expense_query", "expenses_queries", "this month expense"),
        ("show me this month expense list", "expense_query", "expenses_queries", "list the expense one by one"),
        ("analyse this month expense", "expense_query", "expenses_queries", "this month expense"),
        ("show last 4 expenses", "expense_query", "expenses_queries", "last 5 expense"),
        ("show last 2 expenses one by one", "expense_query", "expenses_queries", "last 3 expense"),
        ("petrol expense this month", "expense_query", "expenses_queries", "petrol expense for this month"),
        ("food expense this month", "expense_query", "expenses_queries", "groceries expense for this month"),
        ("ginger expense", "expense_query", "expenses_queries", "ginger 35"),
        ("groceries expense this month", "expense_query", "expenses_queries", "groceries expense for this month"),
        ("april expense", "expense_query", "expenses_queries", "april month expense"),
        ("may month expense", "expense_query", "expenses_queries", "this month expense"),
        ("last month petrol expense", "expense_query", "expenses_queries", "petrol expense for last month"),
        ("expense list for this month", "expense_query", "expenses_queries", "list the expense one by one"),
        ("show each expense for this month", "expense_query", "expenses_queries", "list the expense one by one"),
        ("last two month expense", "expense_query", "expenses_queries", "last 2 month expense"),
    ]
    for text, family, scenario, anchor in expense_variants:
        add(text, family, scenario, anchor=anchor)

    ledger_variants = [
        ("gave maddy 5k", "ledger_write", "ledger_flow", "clear maddy ledger"),
        ("got 2k from ravi", "ledger_write", "ledger_flow", "how much do i owe ravi"),
        ("ravi returned 1k", "ledger_write", "ledger_flow", "ravi ledger"),
        ("sent thenna 750", "ledger_write", "ledger_flow", "all ledger"),
        ("maddy gave me 3k", "ledger_write", "ledger_flow", "maddy balance"),
        ("show me maddy balance", "ledger_query", "ledger_flow", "maddy balance"),
        ("how much do i owe ravi now", "ledger_query", "ledger_flow", "how much do i owe ravi"),
        ("who owes me money", "ledger_query", "ledger_flow", "who all owe me money and how much. list individually"),
        ("show who all owe me money", "ledger_query", "ledger_flow", "show who all owe me money"),
        ("who do i owe", "ledger_query", "ledger_flow", "how much money i owe"),
        ("show ledger for maddy", "ledger_query", "ledger_flow", "maddy ledger"),
        ("show ledger for ravi", "ledger_query", "ledger_flow", "ravi ledger"),
        ("show all ledger entries", "ledger_query", "ledger_flow", "all ledger"),
        ("clear ravi ledger", "ledger_settlement", "ledger_flow", "clear maddy ledger"),
        ("settled maddy balance", "ledger_settlement", "ledger_flow", "settled maddy amount"),
        ("wrote off thenna", "ledger_settlement", "ledger_flow", "wrote off maddy"),
        ("1", "clarify_reply", "ledger_flow", "clear maddy ledger"),
        ("2", "clarify_reply", "ledger_flow", "clear maddy ledger"),
    ]
    for text, family, scenario, anchor in ledger_variants:
        add(text, family, scenario, anchor=anchor)

    for text, family, anchor in [
        ("update the status about mcp to Amit", "ambiguous_probe", "update the status about mcp to Amit"),
        ("march month", "ambiguous_probe", "march month"),
        ("expense status please", "ambiguous_probe", "expense status"),
        ("weight status please", "ambiguous_probe", "weight status"),
        ("ledger status", "ambiguous_probe", "all ledger"),
        ("vivekananda update", "ambiguous_probe", "vivekananda note"),
        ("mcp update", "ambiguous_probe", "any mention of mcp in the notes"),
        ("april month", "ambiguous_probe", "april month expense"),
        ("fundera park update", "ambiguous_probe", "any note about fundera park"),
        ("todo status", "ambiguous_probe", "show todo list"),
    ]:
        add(text, family, "mixed_ambiguity", anchor=anchor)

    if len(cases) < 100:
        raise RuntimeError(f"Expected at least 100 variant cases, built only {len(cases)}")
    return cases[:100]


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_db(src: Path, dst: Path) -> None:
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)


def sanitize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, float):
        return round(value, 6)
    return value


def dict_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: sanitize_value(row[key]) for key in row.keys()}


def snapshot_table(conn: sqlite3.Connection, table_name: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"count": None, "max_id": None, "latest_row": None, "error": None}
    try:
        count_row = conn.execute(f"SELECT COUNT(*) AS c, MAX(id) AS max_id FROM {table_name}").fetchone()
        snapshot["count"] = int(count_row["c"] or 0)
        snapshot["max_id"] = count_row["max_id"]
        latest = None
        if snapshot["max_id"] is not None:
            latest = conn.execute(f"SELECT * FROM {table_name} WHERE id = ? LIMIT 1", (snapshot["max_id"],)).fetchone()
        snapshot["latest_row"] = dict_from_row(latest)
    except sqlite3.Error as exc:
        snapshot["error"] = str(exc)
    return snapshot


def snapshot_tables(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return {table: snapshot_table(conn, table) for table in TABLES}
    finally:
        conn.close()


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for table in TABLES:
        b = before.get(table, {})
        a = after.get(table, {})
        if b != a:
            changes[table] = {
                "count_before": b.get("count"),
                "count_after": a.get("count"),
                "count_delta": (
                    (a.get("count") or 0) - (b.get("count") or 0)
                    if isinstance(a.get("count"), int) and isinstance(b.get("count"), int)
                    else None
                ),
                "max_id_before": b.get("max_id"),
                "max_id_after": a.get("max_id"),
                "before_latest_row": b.get("latest_row"),
                "after_latest_row": a.get("latest_row"),
                "before_error": b.get("error"),
                "after_error": a.get("error"),
            }
    return changes


class FlaskReplayRunner:
    def __init__(self, db_path: Path) -> None:
        os.environ["SECOND_BRAIN_DB_PATH"] = str(db_path)
        os.environ["SECOND_BRAIN_PREWARM"] = "0"
        for module_name in ("second_brain_core", "second_brain_orchestrator", "app"):
            sys.modules.pop(module_name, None)

        self.core_module = importlib.import_module("second_brain_core")
        self.orchestrator_module = importlib.import_module("second_brain_orchestrator")
        self.app_module = importlib.import_module("app")
        self.client = self.app_module.app.test_client()
        self.configure_db(db_path)

    def configure_db(self, db_path: Path) -> None:
        self.db_path = db_path
        self.app_module.DB_PATH = str(db_path)
        self.core_module.ensure_activity_log_schema(str(db_path))

        def _orchestrate(text: str, *, _db_path=str(db_path)):
            return self.orchestrator_module.handle(text, db_path=_db_path)

        self.app_module.orchestrate = _orchestrate

    def runtime_status(self) -> dict[str, Any]:
        llm_service, embedding_service = self.orchestrator_module.get_runtime_services()
        return {
            "llm": llm_service.status(),
            "embedding": embedding_service.status(),
        }

    def run_case(self, case: ReplayCase) -> ReplayResult:
        before = snapshot_tables(self.db_path)
        response = self.client.post("/note", data={"text": case.text}, follow_redirects=False)
        after = snapshot_tables(self.db_path)
        table_changes = diff_snapshots(before, after)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            activity_log_id = after["activity_log"]["max_id"]
            activity_row = None
            if activity_log_id is not None:
                activity_row = conn.execute(
                    "SELECT id, input_text, response_text, kind, metadata_json, created_at "
                    "FROM activity_log WHERE id = ?",
                    (activity_log_id,),
                ).fetchone()
        finally:
            conn.close()

        metadata = {}
        if activity_row and activity_row["metadata_json"]:
            try:
                metadata = json.loads(activity_row["metadata_json"])
            except json.JSONDecodeError:
                metadata = {"metadata_decode_error": activity_row["metadata_json"]}

        timings_ms = metadata.get("timings_ms") or {}
        total_ms = timings_ms.get("orchestrator.total_ms") if isinstance(timings_ms, dict) else None
        result = ReplayResult(
            case_id=case.case_id,
            source=case.source,
            mode=case.mode,
            probe_family=case.probe_family,
            scenario=case.scenario,
            input_text=case.text,
            anchor_text=case.anchor_text,
            notes=case.notes,
            http_status=response.status_code,
            activity_log_id=activity_row["id"] if activity_row else None,
            actual_kind=activity_row["kind"] if activity_row else None,
            actual_response_text=activity_row["response_text"] if activity_row else None,
            actual_tier=metadata.get("tier"),
            actual_rule=metadata.get("rule"),
            actual_confidence=metadata.get("confidence"),
            actual_note_id=metadata.get("note_id"),
            actual_timing_summary=metadata.get("timing_summary"),
            total_ms=total_ms,
            timings_ms=timings_ms if isinstance(timings_ms, dict) else {},
            table_changes=table_changes,
        )
        if case.historical is not None:
            hist_first = (case.historical.logged_response or "").splitlines()
            act_first = (result.actual_response_text or "").splitlines()
            result.historical_comparison = {
                "logged_kind": case.historical.logged_kind,
                "logged_tier": case.historical.logged_tier,
                "logged_rule": case.historical.logged_rule,
                "logged_response": case.historical.logged_response,
                "logged_time_line": case.historical.logged_time_line,
                "kind_match": case.historical.logged_kind == result.actual_kind,
                "tier_match": case.historical.logged_tier == result.actual_tier,
                "rule_match": case.historical.logged_rule == result.actual_rule,
                "response_exact_match": normalize_text(case.historical.logged_response) == normalize_text(result.actual_response_text or ""),
                "response_first_line_match": hist_first[:1] == act_first[:1],
            }
        return result


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def latency_stats(results: list[ReplayResult]) -> dict[str, Any]:
    values = [result.total_ms for result in results if isinstance(result.total_ms, (int, float))]
    if not values:
        return {}
    return {
        "count": len(values),
        "min_ms": round(min(values), 3),
        "p50_ms": round(percentile(values, 0.50) or 0.0, 3),
        "p90_ms": round(percentile(values, 0.90) or 0.0, 3),
        "p95_ms": round(percentile(values, 0.95) or 0.0, 3),
        "p99_ms": round(percentile(values, 0.99) or 0.0, 3),
        "max_ms": round(max(values), 3),
        "mean_ms": round(mean(values), 3),
        "median_ms": round(median(values), 3),
    }


def summarize_counts(items: list[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = item or "<none>"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def summarize_table_changes(results: list[ReplayResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for table in result.table_changes.keys():
            counts[table] = counts.get(table, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def summarize_historical(results: list[ReplayResult]) -> dict[str, Any]:
    comparisons = [result.historical_comparison for result in results if result.historical_comparison]
    total = len(comparisons)
    if total == 0:
        return {}
    tier_comparable = sum(1 for item in comparisons if item.get("logged_tier") is not None)
    rule_comparable = sum(1 for item in comparisons if item.get("logged_rule") is not None)
    parsed_available = sum(1 for item in comparisons if item.get("logged_rule") is not None or item.get("logged_tier") is not None)
    time_available = sum(1 for item in comparisons if item.get("logged_time_line"))
    return {
        "total_cases": total,
        "parsed_available_count": parsed_available,
        "time_available_count": time_available,
        "kind_match_count": sum(1 for item in comparisons if item["kind_match"]),
        "tier_comparable_count": tier_comparable,
        "tier_match_count": sum(1 for item in comparisons if item.get("logged_tier") is not None and item["tier_match"]),
        "rule_comparable_count": rule_comparable,
        "rule_match_count": sum(1 for item in comparisons if item.get("logged_rule") is not None and item["rule_match"]),
        "response_exact_match_count": sum(1 for item in comparisons if item["response_exact_match"]),
        "response_first_line_match_count": sum(1 for item in comparisons if item["response_first_line_match"]),
    }


def top_slowest(results: list[ReplayResult], limit: int = 15) -> list[dict[str, Any]]:
    filtered = [result for result in results if isinstance(result.total_ms, (int, float))]
    ordered = sorted(filtered, key=lambda item: item.total_ms or 0.0, reverse=True)[:limit]
    return [
        {
            "case_id": result.case_id,
            "source": result.source,
            "input_text": result.input_text,
            "kind": result.actual_kind,
            "tier": result.actual_tier,
            "rule": result.actual_rule,
            "total_ms": result.total_ms,
        }
        for result in ordered
    ]


def results_to_jsonable(results: list[ReplayResult]) -> list[dict[str, Any]]:
    return [asdict(result) for result in results]


def write_results_csv(path: Path, results: list[ReplayResult]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "source",
                "mode",
                "probe_family",
                "scenario",
                "input_text",
                "anchor_text",
                "http_status",
                "activity_log_id",
                "actual_kind",
                "actual_tier",
                "actual_rule",
                "actual_confidence",
                "actual_note_id",
                "total_ms",
                "actual_timing_summary",
                "changed_tables",
                "historical_kind_match",
                "historical_tier_match",
                "historical_rule_match",
                "historical_response_first_line_match",
            ],
        )
        writer.writeheader()
        for result in results:
            comparison = result.historical_comparison or {}
            writer.writerow(
                {
                    "case_id": result.case_id,
                    "source": result.source,
                    "mode": result.mode,
                    "probe_family": result.probe_family,
                    "scenario": result.scenario,
                    "input_text": result.input_text,
                    "anchor_text": result.anchor_text,
                    "http_status": result.http_status,
                    "activity_log_id": result.activity_log_id,
                    "actual_kind": result.actual_kind,
                    "actual_tier": result.actual_tier,
                    "actual_rule": result.actual_rule,
                    "actual_confidence": result.actual_confidence,
                    "actual_note_id": result.actual_note_id,
                    "total_ms": result.total_ms,
                    "actual_timing_summary": result.actual_timing_summary,
                    "changed_tables": ", ".join(result.table_changes.keys()),
                    "historical_kind_match": comparison.get("kind_match"),
                    "historical_tier_match": comparison.get("tier_match"),
                    "historical_rule_match": comparison.get("rule_match"),
                    "historical_response_first_line_match": comparison.get("response_first_line_match"),
                }
            )


def build_summary_markdown(
    run_metadata: dict[str, Any],
    historical_results: list[ReplayResult],
    variant_results: list[ReplayResult],
) -> str:
    historical_summary = summarize_historical(historical_results)
    all_results = historical_results + variant_results
    lines: list[str] = []

    lines.append("# Replay Matrix Summary")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- Generated at: `{run_metadata['generated_at']}`")
    lines.append(f"- Source DB: `{run_metadata['source_db']}`")
    lines.append(f"- Logs file: `{run_metadata['logs_file']}`")
    lines.append(f"- Historical cases: `{len(historical_results)}`")
    lines.append(f"- Variant cases: `{len(variant_results)}`")
    lines.append(f"- Total cases: `{len(all_results)}`")
    lines.append(f"- LLM backend after historical run: `{run_metadata['historical_runtime']['llm']['backend']}`")
    lines.append(f"- LLM backend after variant run: `{run_metadata['variant_runtime']['llm']['backend']}`")
    lines.append("")

    lines.append("## Historical Replay")
    lines.append("")
    lines.append("These 100 cases were replayed from `logs.txt` in chronological order and compared against the behavior recorded in that file.")
    lines.append("")
    lines.append(f"- Kind match: `{historical_summary.get('kind_match_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append(f"- Parsed metadata available in logs: `{historical_summary.get('parsed_available_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append(f"- Timing metadata available in logs: `{historical_summary.get('time_available_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append(f"- Tier match: `{historical_summary.get('tier_match_count', 0)}/{historical_summary.get('tier_comparable_count', 0)}` comparable cases")
    lines.append(f"- Rule match: `{historical_summary.get('rule_match_count', 0)}/{historical_summary.get('rule_comparable_count', 0)}` comparable cases")
    lines.append(f"- Response first-line match: `{historical_summary.get('response_first_line_match_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append(f"- Response exact match: `{historical_summary.get('response_exact_match_count', 0)}/{historical_summary.get('total_cases', 0)}`")
    lines.append("")

    mismatch_rows = [
        result
        for result in historical_results
        if result.historical_comparison
        and (
            not result.historical_comparison["kind_match"]
            or not result.historical_comparison["tier_match"]
            or not result.historical_comparison["rule_match"]
        )
    ][:20]
    lines.append("### First 20 historical mismatches")
    lines.append("")
    if mismatch_rows:
        for result in mismatch_rows:
            comparison = result.historical_comparison or {}
            lines.append(
                f"- `{result.case_id}` `{result.input_text}` | logged `{comparison.get('logged_kind')}/{comparison.get('logged_tier')}/{comparison.get('logged_rule')}` -> replay `{result.actual_kind}/{result.actual_tier}/{result.actual_rule}`"
            )
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Variant Matrix")
    lines.append("")
    lines.append("These 100 cases are generated from the same observed patterns, but they are recorded without forcing a correctness expectation. The output below is what the current live path actually did.")
    lines.append("")
    lines.append("### Variant route distribution")
    lines.append("")
    for label, counts in [
        ("Kinds", summarize_counts([result.actual_kind for result in variant_results])),
        ("Tiers", summarize_counts([result.actual_tier for result in variant_results])),
        ("Rules", summarize_counts([result.actual_rule for result in variant_results])),
        ("Probe families", summarize_counts([result.probe_family for result in variant_results])),
    ]:
        lines.append(f"- {label}: `{json.dumps(counts, ensure_ascii=False)}`")
    lines.append("")

    lines.append("## Latency")
    lines.append("")
    for label, subset in [
        ("Historical", historical_results),
        ("Variants", variant_results),
        ("All cases", all_results),
    ]:
        stats = latency_stats(subset)
        lines.append(f"- {label}: `{json.dumps(stats, ensure_ascii=False)}`")
    lines.append("")

    lines.append("### Slowest cases")
    lines.append("")
    for row in top_slowest(all_results, limit=20):
        lines.append(
            f"- `{row['case_id']}` `{row['input_text']}` -> `{row['kind']}/{row['tier']}/{row['rule']}` in `{row['total_ms']}` ms"
        )
    lines.append("")

    lines.append("## Side Effects")
    lines.append("")
    lines.append(f"- Historical changed tables: `{json.dumps(summarize_table_changes(historical_results), ensure_ascii=False)}`")
    lines.append(f"- Variant changed tables: `{json.dumps(summarize_table_changes(variant_results), ensure_ascii=False)}`")
    lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    lines.append("- `artifacts/replay_matrix/case_definitions.json`")
    lines.append("- `artifacts/replay_matrix/results.json`")
    lines.append("- `artifacts/replay_matrix/results.csv`")
    lines.append("- `artifacts/replay_matrix/summary.md`")
    lines.append("- `artifacts/replay_matrix/historical_replay.db`")
    lines.append("- `artifacts/replay_matrix/variant_replay.db`")
    lines.append("")
    return "\n".join(lines)


def run_replay_batch(runner: FlaskReplayRunner, cases: list[ReplayCase]) -> list[ReplayResult]:
    results: list[ReplayResult] = []
    for case in cases:
        results.append(runner.run_case(case))
    return results


def main() -> int:
    if not SOURCE_DB_PATH.exists():
        print(f"FAIL: source DB not found at {SOURCE_DB_PATH}")
        return 1
    if not LOGS_PATH.exists():
        print(f"FAIL: logs file not found at {LOGS_PATH}")
        return 1

    ensure_clean_dir(TMP_DIR)
    ensure_clean_dir(ARTIFACT_DIR)

    historical_entries = parse_logs(LOGS_PATH)
    historical_cases = build_historical_cases(historical_entries)
    existing_inputs = {normalize_text(entry.input_text) for entry in historical_entries}
    variant_cases = build_variant_cases(existing_inputs)

    historical_db = ARTIFACT_DIR / "historical_replay.db"
    variant_db = ARTIFACT_DIR / "variant_replay.db"
    copy_db(SOURCE_DB_PATH, historical_db)
    copy_db(SOURCE_DB_PATH, variant_db)

    historical_runner = FlaskReplayRunner(historical_db)
    historical_results = run_replay_batch(historical_runner, historical_cases)
    historical_runtime = historical_runner.runtime_status()

    variant_runner = FlaskReplayRunner(variant_db)
    variant_results = run_replay_batch(variant_runner, variant_cases)
    variant_runtime = variant_runner.runtime_status()

    run_metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(SOURCE_DB_PATH),
        "logs_file": str(LOGS_PATH),
        "historical_runtime": historical_runtime,
        "variant_runtime": variant_runtime,
        "historical_case_count": len(historical_cases),
        "variant_case_count": len(variant_cases),
    }

    case_definitions = {
        "historical_cases": [asdict(case) for case in historical_cases],
        "variant_cases": [asdict(case) for case in variant_cases],
    }
    results_payload = {
        "run_metadata": run_metadata,
        "historical_summary": summarize_historical(historical_results),
        "historical_latency": latency_stats(historical_results),
        "variant_latency": latency_stats(variant_results),
        "all_latency": latency_stats(historical_results + variant_results),
        "historical_results": results_to_jsonable(historical_results),
        "variant_results": results_to_jsonable(variant_results),
    }
    summary_md = build_summary_markdown(run_metadata, historical_results, variant_results)

    (ARTIFACT_DIR / "case_definitions.json").write_text(
        json.dumps(case_definitions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACT_DIR / "results.json").write_text(
        json.dumps(results_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_results_csv(ARTIFACT_DIR / "results.csv", historical_results + variant_results)
    (ARTIFACT_DIR / "summary.md").write_text(summary_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "historical_cases": len(historical_cases),
                "variant_cases": len(variant_cases),
                "total_cases": len(historical_cases) + len(variant_cases),
                "artifacts_dir": str(ARTIFACT_DIR),
                "historical_latency": latency_stats(historical_results),
                "variant_latency": latency_stats(variant_results),
                "historical_summary": summarize_historical(historical_results),
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
