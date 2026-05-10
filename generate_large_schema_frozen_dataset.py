from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from synthetic_dataset_assets import (
    GLOBAL_BUY,
    GLOBAL_EXPENSE,
    GLOBAL_LEDGER_REASONS,
    GLOBAL_NAMES,
    GLOBAL_NOTE_TOPICS,
    GLOBAL_TODOS,
    GLOBAL_TODO_NOUNS,
    INDIA_BUY,
    INDIA_EXPENSE,
    INDIA_LEDGER_REASONS,
    INDIA_NAMES,
    INDIA_NOTE_TOPICS,
    INDIA_TODOS,
    INDIA_TODO_NOUNS,
    RANGE_OPTIONS,
    SINGLE_DATE_OPTIONS,
)

ANCHOR_DATE = "2026-05-05"
OUT_DIR = Path("synthetic_finetune_dataset_v3_large_india_first")
SEED = 20260506

WRITE_COUNT = 4000
QUERY_COUNT = 4000
REFERENCE_COUNT = 4000
FOLLOWUP_COUNT = 5000

# Uniqueness policy:
# - "strict": fail if a lane cannot reach the requested unique count
# - "soft": keep unique rows while possible, then allow repeats to fill the target
UNIQUENESS_POLICY = "soft"

EXPENSE_WRITE_PATTERNS = [
    "{desc} {amt}",
    "{amt} {desc}",
    "{desc}-{amt}",
    "{amt}-{desc}",
    "{desc}:{amt}",
    "{amt}:{desc}",
    "{desc} for {amt}",
    "{amt} on {desc}",
    "{desc} ku {amt}",
    "{desc} {amt} kaasu",
]

EXPENSE_NATURAL_PATTERNS = [
    "paid {amt} for {desc} at local market",
    "spent {amt} on {desc}",
    "bought {desc} for {amt}",
    "got {desc} for {amt} from neighborhood store",
    "purchased {desc} worth {amt}",
]

BUY_PREFIX_PATTERNS = [
    "need to get {first} and {second}",
    "pick up {first} and {second}",
    "get {first} plus {second}",
    "buy {first} along with {second}",
    "{first} um {second} um vaanganum",
    "{first} kooda {second} yum vangikanum",
]

BUY_TRIPLE_PATTERNS = [
    "pick up {first}, {second} and {third}",
    "need {first}, {second}, and {third}",
    "buy {first}, {second}, {third}",
    "{first}, {second}, {third} vaanganum",
]

TODO_TIME_PATTERNS = [
    "call bank at 4pm",
    "doctor appointment tomorrow 6:30 pm",
    "submit form by 11am",
    "call school at 10am",
    "pay fee before 5pm",
]

NOTE_SEARCH_PATTERNS = [
    "show my notes about {q}",
    "any mention of {q} in my notes",
    "find {q} in my notes",
    "what did I write about {q}",
    "did I note anything about {q}",
    "search my notes for {q}",
    "look up {q} in my notes",
    "pull notes related to {q}",
    "show note snippets about {q}",
    "find anything I wrote on {q}",
]

EXPENSE_GROUP_QUERY_PATTERNS = [
    "what did I spend on {group} in april",
    "what is my total {group} expense this month",
    "how much went to {group} this month",
    "show {group} expenses for this month",
    "total spent on {group} in current month",
    "show me this month {group} spending",
    "how much did {group} cost me this month",
    "april {group} expense summary",
]

EXPENSE_COMPARE_PATTERNS = [
    "compare this month and last month spending",
    "compare this month with last month expense",
    "month over month expense comparison",
    "show expense comparison for this month versus last month",
    "how does this month expense compare with last month",
    "compare monthly spending for current and previous month",
]

RECENT_EXPENSE_PATTERNS = [
    "recent expenses",
    "show recent expenses",
    "show my latest expenses",
    "last few expenses",
    "show my last 10 expenses",
    "latest expense entries",
]

BUY_QUERY_PATTERNS = [
    "show my buy list",
    "what do I need to buy",
    "show my latest buy list",
    "show today buy list",
    "what items are pending in my buy list",
    "show open buy items",
    "what should I buy today",
    "latest buy items",
]

TODO_OPEN_PATTERNS = [
    "show my todo list",
    "show my tasks",
    "show pending tasks",
    "show open tasks",
    "what tasks are still open",
    "list my pending todos",
    "show unfinished tasks",
    "what remains in my todo list",
]

LEDGER_SUMMARY_PATTERNS = [
    "show my ledger",
    "ledger summary",
    "show open ledger",
    "show open balances",
    "who is in my open ledger",
    "show pending ledger balances",
]

LEDGER_RECENT_PATTERNS = [
    "recent ledger entries",
    "show recent ledger entries",
    "latest ledger entries",
    "show last ledger entries",
    "show last 10 ledger entries",
]

NOTE_LATEST_PATTERNS = [
    "show my notes",
    "show my latest note",
    "what have I written recently",
    "show my recent notes",
    "open my latest note bucket",
    "show latest notes",
]

TANGLISH_QUERY_SHARE = 0.28
TANGLISH_FOLLOWUP_SHARE = 0.22
TRAIN_COVERAGE_PASSES = 2


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def count_expense_items(catalog: dict[str, list[str]]) -> int:
    return sum(len(items) for items in catalog.values())


def report_assets() -> None:
    report = {
        "india_names": len(INDIA_NAMES),
        "global_names": len(GLOBAL_NAMES),
        "india_note_topics": len(INDIA_NOTE_TOPICS),
        "global_note_topics": len(GLOBAL_NOTE_TOPICS),
        "india_expense_items_total": count_expense_items(INDIA_EXPENSE),
        "global_expense_items_total": count_expense_items(GLOBAL_EXPENSE),
        "india_buy_items": len(INDIA_BUY),
        "global_buy_items": len(GLOBAL_BUY),
        "india_todo_actions": len(INDIA_TODOS),
        "india_todo_nouns": len(INDIA_TODO_NOUNS),
        "global_todo_actions": len(GLOBAL_TODOS),
        "global_todo_nouns": len(GLOBAL_TODO_NOUNS),
        "india_ledger_reasons": len(INDIA_LEDGER_REASONS),
        "global_ledger_reasons": len(GLOBAL_LEDGER_REASONS),
        "single_date_options": len(SINGLE_DATE_OPTIONS),
        "range_options": len(RANGE_OPTIONS),
        "expense_write_patterns": len(EXPENSE_WRITE_PATTERNS),
        "expense_natural_patterns": len(EXPENSE_NATURAL_PATTERNS),
        "buy_prefix_patterns": len(BUY_PREFIX_PATTERNS),
        "buy_triple_patterns": len(BUY_TRIPLE_PATTERNS),
        "todo_time_patterns": len(TODO_TIME_PATTERNS),
        "note_search_patterns": len(NOTE_SEARCH_PATTERNS),
        "expense_group_query_patterns": len(EXPENSE_GROUP_QUERY_PATTERNS),
        "expense_compare_patterns": len(EXPENSE_COMPARE_PATTERNS),
        "recent_expense_patterns": len(RECENT_EXPENSE_PATTERNS),
        "buy_query_patterns": len(BUY_QUERY_PATTERNS),
        "todo_open_patterns": len(TODO_OPEN_PATTERNS),
        "ledger_summary_patterns": len(LEDGER_SUMMARY_PATTERNS),
        "ledger_recent_patterns": len(LEDGER_RECENT_PATTERNS),
        "note_latest_patterns": len(NOTE_LATEST_PATTERNS),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


def canonical_row(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def shuffled_cycle_sequence(total: int, items: list[str], rng: random.Random) -> list[str]:
    if total <= 0 or not items:
        return []
    sequence: list[str] = []
    while len(sequence) < total:
        cycle = list(items)
        rng.shuffle(cycle)
        sequence.extend(cycle)
    return sequence[:total]


def build_coverage_targets(total: int, buckets: list[str], rng: random.Random, passes: int = 1) -> list[str]:
    if total <= 0 or not buckets:
        return []
    target_total = min(total, len(buckets) * max(1, passes))
    return shuffled_cycle_sequence(target_total, buckets, rng)


def round_robin_merge(groups: list[list[dict]]) -> list[dict]:
    merged: list[dict] = []
    working = [list(group) for group in groups if group]
    while working:
        next_working: list[list[dict]] = []
        for group in working:
            if group:
                merged.append(group.pop(0))
            if group:
                next_working.append(group)
        working = next_working
    return merged


def choose_modes(total: int, rng: random.Random) -> list[str]:
    india = int(total * 0.7)
    global_n = total - india
    modes = (["india"] * india) + (["global"] * global_n)
    rng.shuffle(modes)
    return modes


def pick_name(mode: str, rng: random.Random) -> str:
    return rng.choice(INDIA_NAMES if mode == "india" else GLOBAL_NAMES)


def pick_topic(mode: str, rng: random.Random) -> str:
    return rng.choice(INDIA_NOTE_TOPICS if mode == "india" else GLOBAL_NOTE_TOPICS)


def use_tanglish(mode: str, rng: random.Random, chance: float = TANGLISH_QUERY_SHARE) -> bool:
    return mode == "india" and rng.random() < chance


def contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_expense_write(row: dict) -> str:
    output = row["output"]
    if output["disposition"] == "reject":
        if output["reason_code"] == "invalid_lane_content":
            return "reject_invalid_lane"
        payload = row["input"].split(":", 1)[1].strip().lower()
        return "reject_amount_only" if payload[:1].isdigit() or payload.startswith("rs ") else "reject_desc_only"
    if len(output["records"]) > 1:
        return "accept_multi"
    lowered = row["input"].lower()
    natural_markers = ("paid ", "spent ", "bought ", "purchased ", "got ", "pochu", "vaanginen", "vanginen")
    return "accept_natural" if any(marker in lowered for marker in natural_markers) else "accept_single"


def classify_buy_write(row: dict) -> str:
    output = row["output"]
    if output["disposition"] == "reject":
        return "reject_invalid_lane" if output["reason_code"] == "invalid_lane_content" else "reject_incomplete"
    if "\n" in row["input"]:
        return "accept_multiline"
    lowered = row["input"].lower()
    natural_markers = ("need to get", "pick up", "along with", "plus", "vaanganum", "vangikanum")
    if any(marker in lowered for marker in natural_markers):
        return "accept_natural"
    return "accept_multi" if len(output["records"]) > 1 else "accept_single"


def classify_todo_write(row: dict) -> str:
    output = row["output"]
    if output["disposition"] == "reject":
        return "reject_incomplete"
    body = row["input"].split(":", 1)[1]
    first_text = output["records"][0]["text"] if output["records"] else ""
    if first_text in TODO_TIME_PATTERNS:
        return "accept_time_hint"
    if "\n- " in body or body.lstrip().startswith("- "):
        return "accept_bullets"
    if "\n" in body:
        return "accept_multiline"
    if ";" in body:
        return "accept_semicolon"
    return "accept_single" if len(output["records"]) == 1 else "accept_multi"


def classify_weight_write(row: dict) -> str:
    output = row["output"]
    if output["disposition"] == "reject":
        return "reject_invalid_lane" if output["reason_code"] == "invalid_lane_content" else "reject_incomplete"
    if len(output["records"]) > 1:
        return "accept_multi"
    record = output["records"][0]
    if record.get("note"):
        return "accept_with_note"
    return "accept_self" if record["person_text"] == "self" else "accept_named"


def classify_ledger_write(row: dict) -> str:
    output = row["output"]
    disposition = output["disposition"]
    if disposition == "reject":
        return "reject_ambiguous_direction" if output["reason_code"] == "ambiguous_direction" else "reject_incomplete"
    if disposition == "confirm":
        return "confirm_ambiguous_direction"
    if len(output["records"]) > 1:
        return "accept_multi"
    return f"accept_{output['records'][0]['action']}"


def classify_note_query(row: dict) -> str:
    output = row["output"]
    if output["intent"] == "latest_bucket":
        return "latest"
    if output["intent"] == "recent":
        return "recent"
    if output["intent"] == "day_bucket":
        lowered = row["input"].lower()
        return "day_yesterday" if "yesterday" in lowered or "nethu" in lowered else "day_specific"
    lowered = row["input"].lower()
    if lowered.startswith("ask: note:"):
        return "scoped_search"
    query_text = output.get("query_text") or ""
    return "typo_search" if "0" in query_text or query_text.endswith("e") else "search"


def classify_expense_query(row: dict) -> str:
    output = row["output"]
    lowered = row["input"].lower()
    filters = output["filters"]
    if lowered.startswith("ask: expense:"):
        return "scoped"
    if output["intent"] == "compare":
        return "compare"
    if output.get("limit") == 10 and output["intent"] == "list" and output["date_start"] is None:
        return "recent"
    if filters["exclude_group"] or filters["exclude_description_text"]:
        return "exclude"
    if filters["group"]:
        return "group"
    if filters["description_text"]:
        return "desc"
    if output["date_start"] == "2026-04-01" and output["intent"] == "total":
        return "last_month"
    if output["date_start"] == "2026-05-05" and output["intent"] == "list":
        return "today"
    if output["intent"] == "list":
        return "list_default"
    return "total_default"


def classify_buy_query(row: dict) -> str:
    output = row["output"]
    lowered = row["input"].lower()
    if lowered.startswith("ask: buy:"):
        return "scoped"
    if output["intent"] == "search":
        return "search"
    if output["intent"] == "latest_day":
        return "latest"
    if output["date_start"] == "2026-05-05" and any(token in lowered for token in ("all buy", "done buy", "open buy", "ella buy", "done buy items", "open buy items")):
        return "all"
    if output["date_start"] == "2026-05-05":
        return "today"
    return "date"


def classify_todo_query(row: dict) -> str:
    output = row["output"]
    lowered = row["input"].lower()
    if lowered.startswith("ask: todo:"):
        return "scoped"
    if output["intent"] == "history":
        return "history"
    if output["intent"] == "search":
        return "search"
    if output["date_start"] == "2026-05-04" and output["date_end"] == "2026-05-10":
        return "due_week"
    if output["date_start"] == "2026-05-05" and output["filters"]["status"] == "done":
        return "done_today"
    if output["date_start"] == "2026-05-05":
        return "today"
    if output["filters"]["status"] is None:
        return "all"
    return "open"


def classify_weight_query(row: dict) -> str:
    output = row["output"]
    lowered = row["input"].lower()
    if lowered.startswith("ask: weight:"):
        return "scoped"
    if output["intent"] == "latest_all":
        return "latest_all"
    if output["intent"] == "history" and output["date_start"] == "2025-11-05" and output["date_end"] == "2026-05-05":
        return "history"
    if output["intent"] == "trend":
        return "trend"
    if output["intent"] == "change":
        return "change"
    if output["date_start"] is not None:
        return "date"
    return "latest"


def classify_ledger_query(row: dict) -> str:
    output = row["output"]
    lowered = row["input"].lower()
    filters = output["filters"]
    if lowered.startswith("ask: ledger:"):
        return "scoped"
    if output["intent"] == "latest_balance":
        return "latest"
    if output["intent"] == "settled_list":
        return "settled"
    if output["date_start"] is not None:
        return "range"
    if output.get("limit") == 10:
        return "recent"
    if output["intent"] == "balance":
        return "owe" if filters["perspective"] == "i_owe_them" else "owed"
    if output["intent"] == "open_summary":
        return "who" if filters["perspective"] else "summary"
    if filters["person_text"] and filters["status"] == "open":
        return "open_with"
    return "person"


def classify_followup(row: dict) -> str:
    return row["output"]["domain"]


COVERAGE_BUCKETS = {
    "parse_write/expense": ["reject_desc_only", "reject_amount_only", "reject_invalid_lane", "accept_single", "accept_multi", "accept_natural"],
    "parse_write/buy": ["reject_incomplete", "reject_invalid_lane", "accept_single", "accept_multi", "accept_natural", "accept_multiline"],
    "parse_write/todo": ["reject_incomplete", "accept_single", "accept_multi", "accept_multiline", "accept_bullets", "accept_time_hint"],
    "parse_write/weight": ["reject_incomplete", "reject_invalid_lane", "accept_self", "accept_named", "accept_multi", "accept_with_note"],
    "parse_write/ledger": ["reject_ambiguous_direction", "reject_incomplete", "confirm_ambiguous_direction", "accept_add_debt", "accept_add_credit", "accept_repay_debt", "accept_collect_credit", "accept_settle", "accept_multi"],
    "parse_query/note": ["latest", "recent", "day_yesterday", "day_specific", "search", "scoped_search", "typo_search"],
    "parse_query/expense": ["total_default", "list_default", "today", "last_month", "group", "desc", "exclude", "recent", "compare", "scoped"],
    "parse_query/buy": ["latest", "today", "date", "search", "all", "scoped"],
    "parse_query/todo": ["open", "today", "all", "history", "due_week", "done_today", "search", "scoped"],
    "parse_query/weight": ["latest", "history", "trend", "change", "latest_all", "date", "scoped"],
    "parse_query/ledger": ["summary", "person", "owe", "owed", "who", "open_with", "recent", "range", "settled", "latest", "scoped"],
    "parse_followup_query/mixed_followups": ["expense", "buy", "todo", "weight", "ledger", "note"],
}


COVERAGE_CLASSIFIERS = {
    "parse_write/expense": classify_expense_write,
    "parse_write/buy": classify_buy_write,
    "parse_write/todo": classify_todo_write,
    "parse_write/weight": classify_weight_write,
    "parse_write/ledger": classify_ledger_write,
    "parse_query/note": classify_note_query,
    "parse_query/expense": classify_expense_query,
    "parse_query/buy": classify_buy_query,
    "parse_query/todo": classify_todo_query,
    "parse_query/weight": classify_weight_query,
    "parse_query/ledger": classify_ledger_query,
    "parse_followup_query/mixed_followups": classify_followup,
}


def amount_text_and_value(rng: random.Random, large_ok: bool = True, foreign_ok: bool = False) -> tuple[str, float | int]:
    styles = ["plain", "rs", "comma", "decimal", "k"]
    if large_ok:
        styles.extend(["L", "lakh", "crore"])
    if foreign_ok:
        styles.append("usd")
    style = rng.choice(styles)
    if style == "plain":
        value = rng.randint(18, 9999)
        return str(value), value
    if style == "rs":
        value = rng.randint(18, 9999)
        return f"rs {value}", value
    if style == "comma":
        value = rng.randint(1200, 25000)
        return f"{value:,}", value
    if style == "decimal":
        value = round(rng.uniform(18, 999), 2)
        return str(value), value
    if style == "k":
        base = rng.choice([1.5, 2, 2.5, 5, 7.5, 9])
        return f"{base}k", int(base * 1000)
    if style == "L":
        base = rng.choice([1.5, 2, 3, 4.5])
        return f"{base}L", int(base * 100000)
    if style == "lakh":
        base = rng.choice([2, 3, 5, 7])
        return f"{base} lakh", base * 100000
    if style == "crore":
        base = rng.choice([1, 2, 3])
        return f"{base} crore", base * 10000000
    value = rng.choice([20, 35, 49, 60, 75])
    return f"USD {value}", value


AMOUNT_BANDS = {
    "micro": {"min": 10, "max": 350, "styles": ["plain", "rs", "decimal"]},
    "small": {"min": 18, "max": 2500, "styles": ["plain", "rs", "comma", "decimal"]},
    "medium": {"min": 80, "max": 12000, "styles": ["plain", "rs", "comma", "decimal", "k"]},
    "large": {"min": 350, "max": 120000, "styles": ["plain", "rs", "comma", "k", "decimal"]},
    "xlarge": {"min": 1500, "max": 600000, "styles": ["comma", "k", "L", "lakh"]},
    "huge": {"min": 5000, "max": 30000000, "styles": ["comma", "k", "L", "lakh", "crore"]},
}

VERY_SMALL_EXPENSE_KEYWORDS = {
    "tea", "coffee", "chai", "bun", "platform ticket", "share auto", "auto fare", "bus fare", "parking meter",
    "parking", "air fill", "water bottle", "tender coconut", "milk packet", "match box", "xerox", "bus kaasu",
    "auto kaasu", "tea kaasu",
}

SMALL_EXPENSE_KEYWORDS = {
    "curd rice", "veg meals", "filter coffee", "lemon juice", "dosa", "parotta", "kulfi", "chips", "banana",
    "coriander", "mint", "tomato", "onion", "mustard", "cumin", "kothamalli", "puthina", "kadugu", "jeeragam",
    "karuveppilai", "soap", "toothpaste", "match box", "agarbathi", "camphor",
}

LARGE_EXPENSE_KEYWORDS = {
    "rent", "emi", "deposit", "advance", "insurance", "course fee", "school fees", "exam fee", "service",
    "repair", "guest house", "hostel", "intercity", "booking", "travel", "visa", "university", "maintenance",
    "generator charge", "property tax", "room deposit", "community hall",
}

XLARGE_EXPENSE_KEYWORDS = {
    "villa token", "community hall advance", "hostel deposit", "guest house advance", "personal loan emi",
    "car insurance", "bike insurance",
}


def format_amount_for_style(style: str, min_value: float, max_value: float, rng: random.Random) -> tuple[str, float | int]:
    min_i = int(round(min_value))
    max_i = int(round(max_value))
    if style == "plain":
        value = rng.randint(min_i, max_i)
        return str(value), value
    if style == "rs":
        value = rng.randint(min_i, max_i)
        return f"rs {value}", value
    if style == "comma":
        low = max(min_i, 1000)
        high = max(low, max_i)
        value = rng.randint(low, high)
        return f"{value:,}", value
    if style == "decimal":
        high = min(max_value, max(min_value, 2500))
        low = min(min_value, high)
        value = round(rng.uniform(low, high), 2)
        return str(value), value
    if style == "k":
        low = max(min_value / 1000, 1.5)
        high = max(low, max_value / 1000)
        base = round(rng.uniform(low, min(high, 25.0)), 1)
        if base.is_integer():
            base = int(base)
        return f"{base}k", int(base * 1000)
    if style == "L":
        low = max(min_value / 100000, 1.5)
        high = max(low, max_value / 100000)
        base = round(rng.uniform(low, min(high, 9.5)), 1)
        if base.is_integer():
            base = int(base)
        return f"{base}L", int(base * 100000)
    if style == "lakh":
        low = max(min_value / 100000, 1.0)
        high = max(low, max_value / 100000)
        base = round(rng.uniform(low, min(high, 95.0)), 1)
        if base.is_integer():
            base = int(base)
        return f"{base} lakh", int(base * 100000)
    if style == "crore":
        low = max(min_value / 10000000, 1.0)
        high = max(low, max_value / 10000000)
        base = round(rng.uniform(low, min(high, 9.0)), 1)
        if base.is_integer():
            base = int(base)
        return f"{base} crore", int(base * 10000000)
    value = rng.choice([20, 35, 49, 60, 75])
    return f"USD {value}", value


def expense_amount_band(group: str, desc: str) -> str:
    desc_l = desc.lower()
    if contains_any(desc_l, VERY_SMALL_EXPENSE_KEYWORDS):
        return "micro"
    if contains_any(desc_l, SMALL_EXPENSE_KEYWORDS):
        return "small"
    if contains_any(desc_l, XLARGE_EXPENSE_KEYWORDS):
        return "huge"
    if contains_any(desc_l, LARGE_EXPENSE_KEYWORDS):
        return "xlarge"
    if group == "groceries":
        if contains_any(desc_l, {"rice sack", "groundnut oil", "sesame oil", "filter coffee powder"}):
            return "medium"
        return "small"
    if group in {"transport", "dining", "personal_care"}:
        return "small"
    if group in {"bills_utilities", "recharge_subscription", "household", "health", "work", "shopping"}:
        return "medium"
    if group in {"education", "entertainment", "vehicle"}:
        return "large"
    if group == "travel":
        return "xlarge"
    if group == "other":
        return "huge" if contains_any(desc_l, {"rent", "emi", "advance", "donation"}) else "large"
    return "medium"


def expense_amount_text_and_value(group: str, desc: str, mode: str, rng: random.Random) -> tuple[str, float | int]:
    band_name = expense_amount_band(group, desc)
    band = AMOUNT_BANDS[band_name]
    styles = list(band["styles"])
    if mode == "global" and rng.random() < 0.08 and band_name in {"micro", "small"}:
        styles.append("usd")
    style = rng.choice(styles)
    return format_amount_for_style(style, band["min"], band["max"], rng)


def pick_single_date_phrase(rng: random.Random, include_none: bool = True) -> tuple[str | None, str]:
    options = SINGLE_DATE_OPTIONS if include_none else SINGLE_DATE_OPTIONS[1:]
    return rng.choice(options)


def expense_catalog(mode: str) -> dict[str, list[str]]:
    return INDIA_EXPENSE if mode == "india" else GLOBAL_EXPENSE


def pick_expense_item(mode: str, rng: random.Random) -> tuple[str, str]:
    catalog = expense_catalog(mode)
    group = rng.choice(list(catalog.keys()))
    return rng.choice(catalog[group]), group


def pick_buy_item(mode: str, rng: random.Random) -> str:
    pool = INDIA_BUY if mode == "india" else GLOBAL_BUY
    invalid_keywords = {"fee", "bill", "salary", "maintenance", "insurance", "reimbursement", "salary", "emi"}
    for _ in range(40):
        item = rng.choice(pool)
        if not any(keyword in item.lower() for keyword in invalid_keywords):
            return item
    return rng.choice(pool)


def pick_todo_text(mode: str, rng: random.Random) -> str:
    if rng.random() < 0.25:
        pool = INDIA_TODO_NOUNS if mode == "india" else GLOBAL_TODO_NOUNS
    else:
        pool = INDIA_TODOS if mode == "india" else GLOBAL_TODOS
    return rng.choice(pool)

def make_expense_write(mode: str, rng: random.Random) -> dict:
    tanglish = use_tanglish(mode, rng, 0.18)
    if rng.random() < 0.09:
        bad = rng.choice(["desc_only", "amount_only", "invalid_lane"])
        if bad == "desc_only":
            text = rng.choice([
                "expense: apples",
                "expense: coriander",
                "expense: brown chana",
                "expense: kothamalli",
                "expense: shampoo",
                "expense: milk packet",
            ])
            reason = "incomplete_input"
        elif bad == "amount_only":
            text = rng.choice([
                "expense: 250",
                "expense: rs 40",
                "expense: 99",
                "expense: 1,250",
                "expense: 72.5",
            ])
            reason = "incomplete_input"
        else:
            text = rng.choice([
                "expense: call plumber tomorrow",
                "expense: renew license",
                "expense: buy kothamalli tomorrow",
                "expense: schedule dentist appointment",
                "expense: remind me to pay EB bill",
                "expense: book train ticket for next week",
            ])
            reason = "invalid_lane_content"
        return {"input": text, "output": {"task": "parse_write", "lane": "expense", "disposition": "reject", "reason_code": reason, "records": []}}
    n = rng.choices([1, 2, 3], [0.45, 0.4, 0.15])[0]
    date_phrase, date_value = pick_single_date_phrase(rng)
    records = []
    chunks = []
    natural_sentence = n == 1 and rng.random() < 0.25
    for _ in range(n):
        desc, group = pick_expense_item(mode, rng)
        txt, value = expense_amount_text_and_value(group, desc, mode, rng)
        records.append({"description": desc, "amount": value, "date": date_value, "group": group})
        if natural_sentence:
            if tanglish:
                chunks.append(rng.choice([
                    "{desc} ku {amt} pochu",
                    "{desc} vaanginen {amt}",
                    "{amt} ku {desc} vanginen",
                ]).format(desc=desc, amt=txt))
            else:
                chunks.append(rng.choice(EXPENSE_NATURAL_PATTERNS).format(desc=desc, amt=txt))
        else:
            chunks.append(rng.choice(EXPENSE_WRITE_PATTERNS).format(desc=desc, amt=txt))
    input_text = "expense: " + ", ".join(chunks)
    if date_phrase:
        input_text += f" {date_phrase}"
    return {"input": input_text, "output": {"task": "parse_write", "lane": "expense", "disposition": "accept", "reason_code": None, "records": records}}


def quantity_piece(rng: random.Random) -> tuple[str | None, str | None]:
    if rng.random() < 0.4:
        return None, None
    q = str(rng.choice([1, 2, 3, 4, 5, 6, 10, 12, 50, 100]))
    unit = rng.choice([None, "kg", "g", "ml", "L", "pack", "reams", "bars"])
    return q, unit


FOOD_OR_POWDER_KEYWORDS = {
    "curd", "rice", "poha", "hing", "asafoetida", "coriander", "fenugreek", "millets", "dal", "flour", "oil",
    "seeds", "cumin", "toothpaste", "banana", "paneer", "semiya", "tomato", "onion", "garlic", "paste",
    "bagel", "oat", "granola", "olive", "coffee", "tea", "mushroom", "spinach", "sauce", "yogurt", "powder",
    "sugar", "salt", "tamarind", "papad", "rava", "maida", "besan", "milk", "starter", "chips", "pickle",
    "phenyl", "dettol", "wipes", "cleaner", "wash", "shampoo", "lotion", "cream", "syrup", "eyedrops", "oil",
    "kothamalli", "puthina", "karuveppilai", "kadugu", "jeeragam", "sombu", "milagu", "manjal", "perungayam",
    "vendhayam", "ulutham", "thuvaram", "paasi", "kadalai", "arisi", "ravai", "aval", "milagai", "sambar podi",
    "rasam podi", "vengayam", "thakkali", "thengai", "thayir", "nei", "ennai",
}

BAR_LIKE_KEYWORDS = {
    "soap", "bars", "detergent cake", "agarbathi", "camphor", "cotton wick", "candles",
}

BAR_LIKE_EXACT_ITEMS = {"lux", "dove", "lux soap", "dove soap"}

PACK_ONLY_KEYWORDS = {
    "pads", "napkins", "tissue", "towels", "clips", "markers", "pens", "batteries", "battery", "pods", "filters",
    "hooks", "mailers", "wipes", "plates", "cells", "coils", "match box", "rubber bands", "pins",
}

COUNT_ONLY_KEYWORDS = {
    "bulb", "notebook", "helmet", "visor", "blanket", "cups", "extension", "charger", "cable", "lamp", "light",
    "board", "box", "tube light", "phone", "storage", "basket", "tumbler", "mug", "gasket", "bottle", "torch",
    "socks", "board", "organizer", "sleeve", "tripod", "scarf", "bag", "tote", "jacket", "pack",
}

HERB_OR_LEAF_KEYWORDS = {
    "kothamalli", "puthina", "karuveppilai", "coriander", "mint", "banana leaf", "fenugreek leaves",
}

SPICE_KEYWORDS = {
    "kadugu", "jeeragam", "sombu", "milagu", "manjal", "perungayam", "vendhayam", "hing", "asafoetida",
    "mustard seeds", "cumin", "turmeric powder", "milagai podi", "sambar podi", "rasam podi",
}

RICE_OR_FLOUR_KEYWORDS = {
    "rice", "arisi", "flour", "maavu", "rava", "ravai", "poha", "aval", "millets", "dal", "paruppu", "semiya",
}

LIQUID_BUY_KEYWORDS = {
    "oil", "ennai", "lotion", "shampoo", "cleaner", "hand wash", "wash", "milk", "curd", "thayir", "starter",
    "syrup", "face wash", "phenyl", "toilet cleaner", "glass cleaner",
}

COCONUT_OR_COUNT_PRODUCE_KEYWORDS = {
    "coconut", "thengai", "banana leaf",
}

DRY_GROCERY_KEYWORDS = {
    "tamarind", "salt", "sugar", "papad", "pickle", "chips", "tea", "coffee powder", "powder",
}

VEGETABLE_KG_KEYWORDS = {
    "vengayam", "thakkali", "onion", "tomato", "garlic", "ginger", "mushroom", "spinach", "parsley", "avocado",
}

SEMI_SOLID_GRAM_KEYWORDS = {
    "hummus", "yogurt", "greek yogurt", "paneer",
}


def quantity_piece_for_item(item: str, rng: random.Random) -> tuple[str | None, str | None]:
    if rng.random() < 0.4:
        return None, None

    item_l = item.lower()
    q = str(rng.choice([1, 2, 3, 4, 5, 6]))

    if any(k in item_l for k in HERB_OR_LEAF_KEYWORDS):
        return str(rng.choice([1, 2, 3])), None
    if any(k in item_l for k in COCONUT_OR_COUNT_PRODUCE_KEYWORDS):
        return str(rng.choice([1, 2, 3, 4])), None
    if any(k in item_l for k in VEGETABLE_KG_KEYWORDS):
        qty = rng.choice([(250, "g"), (500, "g"), (1, "kg"), (2, "kg")])
        return str(qty[0]), qty[1]
    if any(k in item_l for k in SEMI_SOLID_GRAM_KEYWORDS):
        qty = rng.choice([(200, "g"), (250, "g"), (500, "g"), (1, "kg")])
        return str(qty[0]), qty[1]
    if any(k in item_l for k in SPICE_KEYWORDS):
        return str(rng.choice([50, 100, 200, 250, 500])), "g"
    if any(k in item_l for k in RICE_OR_FLOUR_KEYWORDS):
        qty = rng.choice([(500, "g"), (1, "kg"), (2, "kg"), (5, "kg")])
        return str(qty[0]), qty[1]
    if any(k in item_l for k in DRY_GROCERY_KEYWORDS):
        qty = rng.choice([(100, "g"), (250, "g"), (500, "g"), (1, "kg"), (2, "kg")])
        return str(qty[0]), qty[1]
    if any(k in item_l for k in LIQUID_BUY_KEYWORDS):
        qty = rng.choice([(200, "ml"), (500, "ml"), (750, "ml"), (1, "L"), (2, "L")])
        return str(qty[0]), qty[1]

    if any(k in item_l for k in COUNT_ONLY_KEYWORDS):
        return str(rng.choice([1, 2, 3, 4])), rng.choice([None, "pack"])
    if item_l in BAR_LIKE_EXACT_ITEMS or any(k in item_l for k in BAR_LIKE_KEYWORDS):
        return str(rng.choice([1, 2, 3, 4, 5])), rng.choice([None, "bars", "pack"])
    if any(k in item_l for k in PACK_ONLY_KEYWORDS):
        return str(rng.choice([1, 2, 3, 4, 5, 10])), rng.choice([None, "pack", "reams"])
    if any(k in item_l for k in FOOD_OR_POWDER_KEYWORDS):
        return q, rng.choice([None, "kg", "g", "ml", "L", "pack"])

    return str(rng.choice([1, 2, 3, 4])), rng.choice([None, "pack"])


def make_buy_write(mode: str, rng: random.Random) -> dict:
    roll = rng.random()
    if roll < 0.08:
        text = rng.choice([
            "buy: 2kg",
            "buy: tomorrow",
            "buy: one more",
            "buy: later this week",
            "buy: 500 ml",
            "buy: another one",
        ])
        return {"input": text, "output": {"task": "parse_write", "lane": "buy", "disposition": "reject", "reason_code": "incomplete_input", "records": []}}
    if roll < 0.12:
        text = rng.choice([
            "buy: haircut",
            "buy: pay water bill",
            "buy: call AC service",
            "buy: renew passport",
            "buy: schedule pest control",
            "buy: send invoice reminder",
        ])
        return {"input": text, "output": {"task": "parse_write", "lane": "buy", "disposition": "reject", "reason_code": "invalid_lane_content", "records": []}}
    n = rng.choices([1, 2, 3], [0.4, 0.4, 0.2])[0]
    date_phrase, date_value = pick_single_date_phrase(rng)
    records = []
    items = []
    for _ in range(n):
        item = pick_buy_item(mode, rng)
        q, unit = quantity_piece_for_item(item, rng)
        records.append({"item_text": item, "quantity_text": q, "unit_text": unit, "date": date_value})
        if q and unit:
            items.append(f"{item} {q}{unit}" if unit in {"kg", "g", "ml", "L"} else f"{item} {q} {unit}")
        elif q:
            items.append(f"{item} {q}")
        else:
            items.append(item)
    style = rng.choice(["list", "natural", "multiline"])
    if style == "natural" and n >= 2:
        if n == 2:
            body = rng.choice(BUY_PREFIX_PATTERNS).format(first=items[0], second=items[1])
        else:
            body = rng.choice(BUY_TRIPLE_PATTERNS).format(first=items[0], second=items[1], third=items[2])
    elif style == "multiline" and n >= 2:
        body = "\n".join(items)
    else:
        body = ", ".join(items)
    input_text = "buy: " + body
    if date_phrase:
        input_text += f" {date_phrase}"
    return {"input": input_text, "output": {"task": "parse_write", "lane": "buy", "disposition": "accept", "reason_code": None, "records": records}}


def make_todo_write(mode: str, rng: random.Random) -> dict:
    if rng.random() < 0.1:
        text = rng.choice([
            "todo: tomorrow",
            "todo: 4pm",
            "todo: urgent",
            "todo: later",
            "todo: monday",
            "todo: soon",
        ])
        return {"input": text, "output": {"task": "parse_write", "lane": "todo", "disposition": "reject", "reason_code": "incomplete_input", "records": []}}
    n = rng.choices([1, 2, 3], [0.45, 0.35, 0.2])[0]
    date_phrase, date_value = pick_single_date_phrase(rng)
    tasks = [pick_todo_text(mode, rng) for _ in range(n)]
    if rng.random() < 0.1:
        tasks[0] = rng.choice(TODO_TIME_PATTERNS)
    records = [{"text": t, "date": date_value} for t in tasks]
    style = rng.choice(["comma", "newline", "bullets", "semicolon"])
    if style == "newline" and n >= 2:
        body = "\n".join(tasks)
    elif style == "bullets" and n >= 2:
        body = "\n".join(f"- {t}" for t in tasks)
    elif style == "semicolon" and n >= 2:
        body = "; ".join(tasks)
    else:
        body = ", ".join(tasks)
    input_text = "todo: " + body
    if date_phrase:
        input_text += f" {date_phrase}"
    return {"input": input_text, "output": {"task": "parse_write", "lane": "todo", "disposition": "accept", "reason_code": None, "records": records}}


def make_weight_write(mode: str, rng: random.Random) -> dict:
    roll = rng.random()
    tanglish = use_tanglish(mode, rng, 0.18)
    if roll < 0.1:
        text = rng.choice([
            "weight: after breakfast",
            "weight: waist 34",
            "weight: Marta 159 lb",
            "weight: kg 72",
            "weight: before lunch",
            "weight: Riya 180 lb",
        ])
        reason = "invalid_lane_content" if "waist" in text or "lb" in text else "incomplete_input"
        return {"input": text, "output": {"task": "parse_write", "lane": "weight", "disposition": "reject", "reason_code": reason, "records": []}}
    n = rng.choices([1, 2], [0.75, 0.25])[0]
    date_phrase, date_value = pick_single_date_phrase(rng)
    notes = [None, "before breakfast", "after walk", "empty stomach", "after yoga"]
    records = []
    chunks = []
    for _ in range(n):
        use_self = n == 1 and rng.random() < 0.25
        person = "self" if use_self else pick_name(mode, rng)
        val = round(rng.uniform(48.0, 89.9), 2)
        note = rng.choice(notes)
        text_person = rng.choice(["my weight", "self", ""]) if person == "self" else person
        include_note = bool(note)
        if rng.random() < 0.2 and person != "self":
            include_note = False
        record_note = note if include_note else None
        records.append({"person_text": person, "value": val, "unit": "kg", "date": date_value, "note": record_note})
        if person == "self" and text_person == "" and include_note and note:
            chunk = f"en weight {val} {note}" if tanglish else f"my weight {val} {note}"
        elif person == "self" and text_person == "":
            chunk = f"{val}"
        elif include_note and note:
            chunk = f"{text_person} {val} {note}".strip()
        else:
            chunk = f"{text_person} {val}".strip()
        if not include_note and rng.random() < 0.7 and person != "self":
            chunk = f"{text_person} {val} kg"
        if tanglish and person != "self" and include_note and note and rng.random() < 0.4:
            chunk = f"{person} {val} {note}"
        chunks.append(chunk)
    input_text = "weight: " + ", ".join(chunks)
    if date_phrase:
        input_text += f" {date_phrase}"
    return {"input": input_text, "output": {"task": "parse_write", "lane": "weight", "disposition": "accept", "reason_code": None, "records": records}}


def ledger_accept_record(person: str, action: str, amount, date_value: str, note: str | None) -> dict:
    return {"person_text": person, "action": action, "amount": amount, "date": date_value, "note": note}


def make_ledger_write(mode: str, rng: random.Random) -> dict:
    roll = rng.random()
    tanglish = use_tanglish(mode, rng, 0.2)
    if roll < 0.12:
        text = rng.choice([
            "ledger: Abeer 500",
            "ledger: gave 500",
            "ledger: settled",
            "ledger: return 500",
            "ledger: received 700",
            "ledger: closed account",
        ])
        reason = "ambiguous_direction" if "Abeer 500" in text else "incomplete_input"
        return {"input": text, "output": {"task": "parse_write", "lane": "ledger", "disposition": "reject", "reason_code": reason, "records": []}}
    if roll < 0.24:
        person = pick_name(mode, rng)
        txt, value = amount_text_and_value(rng, large_ok=True, foreign_ok=(mode == "global"))
        if rng.random() < 0.5:
            if tanglish:
                text = f"ledger: {person} ku {txt} kuduthen"
            else:
                text = f"ledger: gave {person} {txt}"
            record = ledger_accept_record(person, "add_credit", value, "2026-05-05", None)
        else:
            if tanglish:
                text = f"ledger: {person} kitte irundhu {txt} vanginen"
            else:
                text = f"ledger: received {txt} from {person}"
            record = ledger_accept_record(person, "add_debt", value, "2026-05-05", None)
        return {"input": text, "output": {"task": "parse_write", "lane": "ledger", "disposition": "confirm", "reason_code": "ambiguous_direction", "records": [record]}}
    date_phrase, date_value = pick_single_date_phrase(rng)
    n = rng.choices([1, 2], [0.8, 0.2])[0]
    records = []
    parts = []
    actions = ["add_debt", "add_credit", "repay_debt", "collect_credit", "settle"]
    for _ in range(n):
        person = pick_name(mode, rng)
        action = rng.choices(actions, [0.25, 0.25, 0.18, 0.18, 0.14])[0]
        note = None
        if rng.random() < 0.25 and action != "settle":
            pool = INDIA_LEDGER_REASONS if mode == "india" else GLOBAL_LEDGER_REASONS
            note = rng.choice(pool)
        if action == "settle":
            amount = None
            if tanglish and rng.random() < 0.6:
                part = rng.choice([f"{person} oda settle panniten", f"{person} account clear panniten"])
            else:
                part = rng.choice([f"settled with {person}", f"cleared {person}"])
        else:
            txt, amount = amount_text_and_value(rng, large_ok=True, foreign_ok=(mode == "global" and rng.random() < 0.15))
            if action == "add_debt":
                if tanglish and rng.random() < 0.6:
                    part = rng.choice([f"{person} ku naan {txt} kuduikanum", f"{person} kitte irundhu {txt} vaanginen"])
                else:
                    part = rng.choice([f"I owe {person} {txt}", f"borrowed {txt} from {person}"])
            elif action == "add_credit":
                if tanglish and rng.random() < 0.6:
                    part = rng.choice([f"{person} enaku {txt} tharanum", f"{person} ku {txt} kuduthen"])
                else:
                    part = rng.choice([f"{person} owes me {txt}", f"lent {person} {txt}"])
            elif action == "repay_debt":
                if tanglish and rng.random() < 0.6:
                    part = rng.choice([f"{person} ku {txt} thiruppi kuduthen", f"{person} amount {txt} settle panninen"])
                else:
                    part = rng.choice([f"I paid {person} back {txt}", f"repaid {person} {txt}"])
            else:
                if tanglish and rng.random() < 0.6:
                    part = rng.choice([f"{person} {txt} thiruppi kuduthan", f"{person} kitte irundhu {txt} vanginen"])
                else:
                    part = rng.choice([f"{person} returned {txt}", f"collected {txt} from {person}", f"{person} paid me back {txt}"])
            if note:
                part += rng.choice([" for ", " from "]) + note
        records.append(ledger_accept_record(person, action, amount, date_value, note))
        parts.append(part)
    input_text = "ledger: " + ", ".join(parts)
    if date_phrase:
        input_text += f" {date_phrase}"
    return {"input": input_text, "output": {"task": "parse_write", "lane": "ledger", "disposition": "accept", "reason_code": None, "records": records}}


def make_note_reference(mode: str, rng: random.Random) -> dict:
    if rng.random() < 0.05:
        return {"input": "note:", "reference_behavior": {"accepted": False, "reason": "empty_note", "save_mode": "reject"}}
    topic = pick_topic(mode, rng)
    style = rng.choice(["plain", "structured", "multiline", "short", "dated"])
    if style == "structured":
        body = rng.choice([f"expense: {topic}", f"todo: {topic}", f"weight: {topic}"])
    elif style == "multiline":
        body = f"{topic}\nsecond line about {topic}\nthird line reminder"
    elif style == "short":
        body = rng.choice(["1", "x", "ok"])
    elif style == "dated":
        body = f"yesterday I wrote about {topic}"
    else:
        body = f"note about {topic}"
    return {
        "input": f"note: {body}",
        "reference_behavior": {
            "accepted": True,
            "save_mode": "append_same_day_bucket",
            "bucket_date": ANCHOR_DATE,
            "preserve_text": "near_exact_multiline" if "\n" in body else "near_exact",
            "resolve_date_phrases": False,
        },
    }

def make_note_query(mode: str, rng: random.Random) -> dict:
    topic = pick_topic(mode, rng)
    tanglish = use_tanglish(mode, rng)
    form = rng.choice(["latest", "recent", "day", "search", "scoped_search", "typo"])
    if form == "latest":
        patterns = NOTE_LATEST_PATTERNS if not tanglish else [
            "innaiku notes kaatu",
            "latest note kaatu",
            "recenta naan ezhuthina notes kaatu",
            "en latest notes kaatu",
        ]
        return {"input": "ask: " + rng.choice(patterns), "output": {"task": "parse_query", "domain": "note", "intent": "latest_bucket", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {}, "limit": None, "query_text": None}}
    if form == "recent":
        options = [
            ("show notes from last week", "last week"),
            ("show notes from april", "april"),
            ("show notes from today", "today"),
            ("show notes from current month", "current month"),
            ("show notes from past 10 days", "past 10 days"),
        ]
        if tanglish:
            options.extend([
                ("pona vaaram notes kaatu", "pona vaaram"),
                ("indha maasam notes kaatu", "indha maasam"),
                ("innaiku notes kaatu", "innaiku"),
                ("nethu notes kaatu", "nethu"),
            ])
        phrase, key = rng.choice(options)
        start, end = RANGE_OPTIONS[key]
        intent = "recent" if key not in {"today", "innaiku", "yesterday", "nethu"} else "day_bucket"
        return {"input": f"ask: {phrase}", "output": {"task": "parse_query", "domain": "note", "intent": intent, "date_start": start, "date_end": end, "compare_date_start": None, "compare_date_end": None, "filters": {}, "limit": None, "query_text": None}}
    if form == "day":
        options = [
            ("what did I write yesterday", "yesterday"),
            ("show notes from last sunday", "last sunday"),
            ("what did I write on may 1", "on may 1"),
            ("show notes from friday", "friday"),
        ]
        if tanglish:
            options.extend([
                ("nethu naan enna ezhuthinen", "nethu"),
                ("last sunday notes kaatu", "last sunday"),
                ("may 1 la naan enna note ezhuthinen", "on may 1"),
                ("friday notes kaatu", "friday"),
            ])
        phrase, key = rng.choice(options)
        start, end = RANGE_OPTIONS[key]
        return {"input": f"ask: {phrase}", "output": {"task": "parse_query", "domain": "note", "intent": "day_bucket", "date_start": start, "date_end": end, "compare_date_start": None, "compare_date_end": None, "filters": {}, "limit": None, "query_text": None}}
    q = topic if form != "typo" else topic.replace("o", "0", 1) if "o" in topic else topic + "e"
    prefix = rng.choice(["ask: ", "ask: note: "]) if form == "scoped_search" else "ask: "
    if tanglish:
        text = rng.choice([
            "en note la {q} pathi enna irukku",
            "{q} pathi naan enna note ezhuthinen",
            "{q} nu notes la search pannu",
            "{q} related note snippets kaatu",
        ]).format(q=q)
    else:
        text = rng.choice(NOTE_SEARCH_PATTERNS).format(q=q)
    return {"input": prefix + text, "output": {"task": "parse_query", "domain": "note", "intent": "search", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {}, "limit": None, "query_text": q}}


def blank_expense_filters():
    return {"group": None, "description_text": None, "exclude_group": None, "exclude_description_text": None}


def make_expense_query(mode: str, rng: random.Random) -> dict:
    catalog = expense_catalog(mode)
    group = rng.choice(list(catalog.keys()))
    desc = rng.choice(catalog[group])
    tanglish = use_tanglish(mode, rng)
    form = rng.choice(["total_default", "list_default", "today", "last_month", "group", "desc", "exclude", "recent", "compare", "scoped"])
    f = blank_expense_filters()
    if form == "total_default":
        text = rng.choice(["what is my total expense", "expense summary", "what is my total expense this month"]) if not tanglish else rng.choice([
            "indha maasam total expense evalo",
            "indha maasam expense summary kaatu",
            "indha maasam total selavu evalo",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "total", "date_start": "2026-05-01", "date_end": "2026-05-31", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "list_default":
        text = "show my expenses" if not tanglish else rng.choice([
            "indha maasam expense kaatu",
            "en expenses kaatu",
            "selavu list kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "list", "date_start": "2026-05-01", "date_end": "2026-05-31", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "today":
        text = rng.choice(["what did I spend today", "show today expense"]) if not tanglish else rng.choice([
            "innaiku enna expense",
            "innaiku selavu kaatu",
            "innaiku evlo expense pannen",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "list", "date_start": "2026-05-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "last_month":
        text = "what was my total expense last month" if not tanglish else rng.choice([
            "pona maasam total expense evalo",
            "pona maasam selavu summary kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "total", "date_start": "2026-04-01", "date_end": "2026-04-30", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "group":
        f["group"] = group
        if tanglish:
            phrase, key = rng.choice([
                (f"{group} la indha maasam evlo pochu", "indha maasam"),
                (f"indha maasam {group} expense evalo", "indha maasam"),
                (f"april la {group} ku evlo pochu", "april"),
                (f"{group} selavu indha maasam kaatu", "indha maasam"),
            ])
        else:
            phrase = rng.choice(EXPENSE_GROUP_QUERY_PATTERNS).format(group=group)
            key = "april" if "april" in phrase else "this month"
        start, end = RANGE_OPTIONS[key]
        return {"input": "ask: " + phrase, "output": {"task": "parse_query", "domain": "expense", "intent": "total", "date_start": start, "date_end": end, "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "desc":
        f["description_text"] = desc
        text = f"what did I spend on {desc} this month" if not tanglish else rng.choice([
            f"{desc} ku indha maasam evlo pochu",
            f"indha maasam {desc} expense evalo",
            f"{desc} selavu indha maasam kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "total", "date_start": "2026-05-01", "date_end": "2026-05-31", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "exclude":
        if rng.random() < 0.5:
            f["exclude_group"] = group
            text = f"show my expenses apart from {group}" if not tanglish else rng.choice([
                f"{group} thavira expense kaatu",
                f"{group} illama matha expense kaatu",
            ])
        else:
            f["exclude_description_text"] = desc
            text = f"expenses except {desc}" if not tanglish else rng.choice([
                f"{desc} thavira expense kaatu",
                f"{desc} vida matha expense kaatu",
            ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "list", "date_start": "2026-05-01", "date_end": "2026-05-31", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}
    if form == "recent":
        prefix = "ask: expense: " if rng.random() < 0.35 else "ask: "
        patterns = RECENT_EXPENSE_PATTERNS if not tanglish else [
            "recent expense kaatu",
            "latest expenses kaatu",
            "kadasiya expense entries kaatu",
        ]
        return {"input": prefix + rng.choice(patterns), "output": {"task": "parse_query", "domain": "expense", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": 10, "query_text": None}}
    if form == "compare":
        if rng.random() < 0.5:
            f["group"] = group
            text = f"compare {group} this month and last month" if not tanglish else rng.choice([
                f"{group} indha maasam vs pona maasam compare pannu",
                f"{group} ku indha maasamum pona maasamum evlo pochu compare pannu",
            ])
        else:
            text = rng.choice(EXPENSE_COMPARE_PATTERNS) if not tanglish else rng.choice([
                "indha maasamum pona maasamum expense compare pannu",
                "current maasam vs pona maasam expense compare pannu",
                "month over month selavu compare kaatu",
            ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "expense", "intent": "compare", "date_start": "2026-05-01", "date_end": "2026-05-31", "compare_date_start": "2026-04-01", "compare_date_end": "2026-04-30", "filters": f, "limit": None, "query_text": None}}
    f["description_text"] = desc
    body = f"what did I spend on {desc} this month" if not tanglish else rng.choice([
        f"{desc} ku indha maasam evlo pochu",
        f"{desc} expense indha maasam kaatu",
    ])
    return {"input": "ask: expense: " + body, "output": {"task": "parse_query", "domain": "expense", "intent": "total", "date_start": "2026-05-01", "date_end": "2026-05-31", "compare_date_start": None, "compare_date_end": None, "filters": f, "limit": None, "query_text": None}}


def make_buy_query(mode: str, rng: random.Random) -> dict:
    item = pick_buy_item(mode, rng)
    status = rng.choice(["open", "done", None])
    tanglish = use_tanglish(mode, rng)
    form = rng.choice(["latest", "today", "date", "search", "all", "scoped"])
    filters = {"status": "open", "item_text": None}
    if form == "latest":
        patterns = BUY_QUERY_PATTERNS[:3] if not tanglish else [
            "buy list kaatu",
            "enna vanganum",
            "latest buy list kaatu",
            "vaanga vendiya list kaatu",
        ]
        return {"input": "ask: " + rng.choice(patterns), "output": {"task": "parse_query", "domain": "buy", "intent": "latest_day", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": filters, "limit": None, "query_text": None}}
    if form == "today":
        text = "what do I need to buy today" if not tanglish else rng.choice([
            "innaiku enna vanganum",
            "innaiku buy list kaatu",
            "innaiku vaanga vendiyadhu enna",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "buy", "intent": "list", "date_start": "2026-05-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": filters, "limit": None, "query_text": None}}
    if form == "date":
        options = [("show yesterday buy list", "yesterday"), ("show friday buy list", "friday"), ("show buy list from may 9", "on may 9"), ("show weekend buy list", "weekend")]
        if tanglish:
            options.extend([
                ("nethu buy list kaatu", "nethu"),
                ("friday buy list kaatu", "friday"),
                ("may 9 buy list kaatu", "on may 9"),
                ("weekend buy list kaatu", "weekend"),
            ])
        phrase, key = rng.choice(options)
        start, end = RANGE_OPTIONS[key]
        return {"input": "ask: " + phrase, "output": {"task": "parse_query", "domain": "buy", "intent": "list", "date_start": start, "date_end": end, "compare_date_start": None, "compare_date_end": None, "filters": filters, "limit": None, "query_text": None}}
    if form == "search":
        filters["item_text"] = item
        text = f"show {item} in my buy list" if not tanglish else rng.choice([
            f"buy list la {item} irukka",
            f"{item} buy list la kaatu",
            f"{item} vaanganuma irukku",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "buy", "intent": "search", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": filters, "limit": None, "query_text": None}}
    if form == "all":
        filters["status"] = status
        if not tanglish:
            phrase = "show all buy items today" if status is None else ("show done buy items today" if status == "done" else "show open buy items today")
        else:
            phrase = "innaiku ella buy items kaatu" if status is None else ("innaiku done buy items kaatu" if status == "done" else "innaiku open buy items kaatu")
        return {"input": "ask: " + phrase, "output": {"task": "parse_query", "domain": "buy", "intent": "list", "date_start": "2026-05-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": filters, "limit": None, "query_text": None}}
    filters["item_text"] = item if rng.random() < 0.5 else None
    if filters["item_text"] is None:
        body = "show my buy list" if not tanglish else "buy list kaatu"
        intent = "latest_day"
    else:
        body = f"show {item} in my buy list" if not tanglish else f"buy list la {item} irukka"
        intent = "search"
    return {"input": "ask: buy: " + body, "output": {"task": "parse_query", "domain": "buy", "intent": intent, "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": filters, "limit": None, "query_text": None}}


def make_todo_query(mode: str, rng: random.Random) -> dict:
    task = pick_todo_text(mode, rng)
    tanglish = use_tanglish(mode, rng)
    form = rng.choice(["open", "today", "all", "history", "due_week", "done_today", "search", "scoped"])
    if form == "open":
        patterns = TODO_OPEN_PATTERNS if not tanglish else [
            "todo list kaatu",
            "pending tasks kaatu",
            "enna seiyanum kaatu",
            "open tasks kaatu",
        ]
        return {"input": "ask: " + rng.choice(patterns), "output": {"task": "parse_query", "domain": "todo", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"status": "open", "text_match": None}, "limit": None, "query_text": None}}
    if form == "today":
        text = rng.choice(["what do I need to do today", "show today tasks"]) if not tanglish else rng.choice([
            "innaiku enna seiyanum",
            "innaiku tasks kaatu",
            "innaiku pending todo kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "todo", "intent": "list", "date_start": "2026-05-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": {"status": "open", "text_match": None}, "limit": None, "query_text": None}}
    if form == "all":
        text = "show all todos" if not tanglish else rng.choice([
            "ella todos kaatu",
            "open um done um ella todo kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "todo", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"status": None, "text_match": None}, "limit": None, "query_text": None}}
    if form == "history":
        text = "show my task history" if not tanglish else rng.choice([
            "task history kaatu",
            "kadasiya 10 todo history kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "todo", "intent": "history", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"status": None, "text_match": None}, "limit": 10, "query_text": None}}
    if form == "due_week":
        text = "what is due this week" if not tanglish else rng.choice([
            "indha vaaram enna seiyanum",
            "indha week pending tasks kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "todo", "intent": "list", "date_start": "2026-05-04", "date_end": "2026-05-10", "compare_date_start": None, "compare_date_end": None, "filters": {"status": "open", "text_match": None}, "limit": None, "query_text": None}}
    if form == "done_today":
        text = "what did I finish today" if not tanglish else rng.choice([
            "innaiku enna mudichen",
            "innaiku done tasks kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "todo", "intent": "list", "date_start": "2026-05-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": {"status": "done", "text_match": None}, "limit": None, "query_text": None}}
    if form == "search":
        text = f"show {task}" if not tanglish else rng.choice([
            f"{task} todo kaatu",
            f"{task} related task kaatu",
        ])
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "todo", "intent": "search", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"status": None, "text_match": task}, "limit": None, "query_text": None}}
    body = "show pending tasks" if not tanglish else "pending tasks kaatu"
    return {"input": "ask: todo: " + body, "output": {"task": "parse_query", "domain": "todo", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"status": "open", "text_match": None}, "limit": None, "query_text": None}}


def make_weight_query(mode: str, rng: random.Random) -> dict:
    person = "self" if rng.random() < 0.5 else pick_name(mode, rng)
    person_text = "my" if person == "self" else person
    tanglish = use_tanglish(mode, rng)
    form = rng.choice(["latest", "history", "trend", "change", "latest_all", "date", "scoped"])
    if form == "latest":
        text = (f"what is {person_text} latest weight" if person != "self" else "what is my latest weight") if not tanglish else (f"{person} latest weight enna" if person != "self" else "en latest weight enna")
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "weight", "intent": "latest", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person}, "limit": None, "query_text": None}}
    if form == "history":
        limit = 5 if person != "self" else None
        text = (f"show {person_text} weight history" if person != "self" else "show my weight history") if not tanglish else (f"{person} weight history kaatu" if person != "self" else "en weight history kaatu")
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "weight", "intent": "history", "date_start": "2025-11-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person}, "limit": limit, "query_text": None}}
    if form == "trend":
        text = (f"show {person_text} weight trend" if person != "self" else "show my weight trend") if not tanglish else (f"{person} weight trend kaatu" if person != "self" else "en weight trend kaatu")
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "weight", "intent": "trend", "date_start": "2025-11-05", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person}, "limit": None, "query_text": None}}
    if form == "change":
        text = (f"how much did {person} change since January" if person != "self" else "how much did my weight change since January") if not tanglish else (f"{person} january lendhu evalo maari irukku" if person != "self" else "january lendhu en weight evalo maari irukku")
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "weight", "intent": "change", "date_start": "2026-01-01", "date_end": "2026-05-05", "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person}, "limit": None, "query_text": None}}
    if form == "latest_all":
        text = "show latest weights" if not tanglish else "latest weights kaatu"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "weight", "intent": "latest_all", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": None}, "limit": None, "query_text": None}}
    if form == "date":
        options = [
            ("ask: weight from yesterday", "yesterday", "self"),
            ("ask: show weights last week", "last week", None),
            ("ask: show my weight from may 1", "on may 1", "self"),
            ("ask: show my weight from friday", "friday", "self"),
        ]
        if tanglish:
            options.extend([
                ("ask: nethu en weight enna", "nethu", "self"),
                ("ask: pona vaaram weights kaatu", "pona vaaram", None),
                ("ask: may 1 la en weight enna", "on may 1", "self"),
                ("ask: friday en weight enna", "friday", "self"),
            ])
        phrase, key, person_filter = rng.choice(options)
        start, end = RANGE_OPTIONS[key]
        return {"input": phrase, "output": {"task": "parse_query", "domain": "weight", "intent": "history", "date_start": start, "date_end": end, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person_filter}, "limit": None, "query_text": None}}
    body = "latest" if not tanglish else "en latest weight enna"
    return {"input": "ask: weight: " + body, "output": {"task": "parse_query", "domain": "weight", "intent": "latest", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": "self"}, "limit": None, "query_text": None}}


def make_ledger_query(mode: str, rng: random.Random) -> dict:
    person = pick_name(mode, rng)
    tanglish = use_tanglish(mode, rng)
    form = rng.choice(["summary", "person", "owe", "owed", "who", "open_with", "recent", "range", "settled", "latest", "scoped"])
    if form == "summary":
        patterns = LEDGER_SUMMARY_PATTERNS if not tanglish else [
            "open ledger kaatu",
            "ledger summary kaatu",
            "open balance kaatu",
        ]
        return {"input": "ask: " + rng.choice(patterns), "output": {"task": "parse_query", "domain": "ledger", "intent": "open_summary", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": None, "perspective": None, "status": "open"}, "limit": None, "query_text": None}}
    if form == "person":
        text = f"show {person} ledger" if not tanglish else f"{person} ledger kaatu"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person, "perspective": None, "status": None}, "limit": None, "query_text": None}}
    if form == "owe":
        text = f"how much do I owe {person}" if not tanglish else f"{person} ku naan evlo kuduikanum"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "balance", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person, "perspective": "i_owe_them", "status": "open"}, "limit": None, "query_text": None}}
    if form == "owed":
        text = f"how much does {person} owe me" if not tanglish else f"{person} enaku evlo tharanum"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "balance", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person, "perspective": "they_owe_me", "status": "open"}, "limit": None, "query_text": None}}
    if form == "who":
        perspective = rng.choice(["they_owe_me", "i_owe_them"])
        if not tanglish:
            text = "who owes me money" if perspective == "they_owe_me" else "whom do I owe"
        else:
            text = "yaar enaku kaasu tharanum" if perspective == "they_owe_me" else "naan yaarukku kaasu kuduikanum"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "open_summary", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": None, "perspective": perspective, "status": "open"}, "limit": None, "query_text": None}}
    if form == "open_with":
        text = f"show open ledger with {person}" if not tanglish else f"{person} oda open ledger kaatu"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person, "perspective": None, "status": "open"}, "limit": None, "query_text": None}}
    if form == "recent":
        patterns = LEDGER_RECENT_PATTERNS if not tanglish else [
            "recent ledger entries kaatu",
            "latest ledger entries kaatu",
            "kadasiya ledger entries kaatu",
        ]
        return {"input": "ask: " + rng.choice(patterns), "output": {"task": "parse_query", "domain": "ledger", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": None, "perspective": None, "status": None}, "limit": 10, "query_text": None}}
    if form == "range":
        options = [
            ("ask: ledger from last month", "2026-04-01", "2026-04-30"),
            ("ask: ledger from this month", "2026-05-01", "2026-05-31"),
            ("ask: ledger from last week", "2026-04-27", "2026-05-03"),
        ]
        if tanglish:
            options.extend([
                ("ask: pona maasam ledger kaatu", "2026-04-01", "2026-04-30"),
                ("ask: indha maasam ledger kaatu", "2026-05-01", "2026-05-31"),
                ("ask: pona vaaram ledger kaatu", "2026-04-27", "2026-05-03"),
            ])
        phrase, ds, de = rng.choice(options)
        return {"input": phrase, "output": {"task": "parse_query", "domain": "ledger", "intent": "list", "date_start": ds, "date_end": de, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": None, "perspective": None, "status": None}, "limit": None, "query_text": None}}
    if form == "settled":
        target = person if rng.random() < 0.4 else None
        if not tanglish:
            text = "show settled ledgers" if target is None else f"show settled ledger for {target}"
        else:
            text = "settled ledgers kaatu" if target is None else f"{target} settled ledger kaatu"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "settled_list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": target, "perspective": None, "status": "settled"}, "limit": None, "query_text": None}}
    if form == "latest":
        text = "show latest ledger" if not tanglish else "latest ledger kaatu"
        return {"input": "ask: " + text, "output": {"task": "parse_query", "domain": "ledger", "intent": "latest_balance", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": None, "perspective": None, "status": None}, "limit": None, "query_text": None}}
    body = f"show {person} ledger" if not tanglish else f"{person} ledger kaatu"
    return {"input": "ask: ledger: " + body, "output": {"task": "parse_query", "domain": "ledger", "intent": "list", "date_start": None, "date_end": None, "compare_date_start": None, "compare_date_end": None, "filters": {"person_text": person, "perspective": None, "status": None}, "limit": None, "query_text": None}}

def make_followup(mode: str, rng: random.Random) -> dict:
    domain = rng.choices(["expense", "buy", "todo", "weight", "ledger", "note"], [0.35, 0.1, 0.15, 0.15, 0.15, 0.10])[0]
    tanglish = use_tanglish(mode, rng, TANGLISH_FOLLOWUP_SHARE)
    if domain == "expense":
        base = make_expense_query(mode, rng)["output"]
        if base["intent"] == "compare" and rng.random() < 0.4:
            group = rng.choice(list(expense_catalog(mode).keys()))
            ctx = dict(base)
            ctx["filters"] = dict(base["filters"])
            inp = "ask: only " + group if not tanglish else "ask: " + group + " mattum"
            return {"context": base, "input": inp, "output": {**ctx, "task": "parse_followup_query", "inherit_context": True, "filters": {"group": group, "description_text": None, "exclude_group": None, "exclude_description_text": None}}}
        group = rng.choice(list(expense_catalog(mode).keys()))
        desc = rng.choice(expense_catalog(mode)[group])
        choices = [
            ("ask: of that how much was " + group, {"group": group, "description_text": None, "exclude_group": None, "exclude_description_text": None}, base["intent"]),
            ("ask: only " + desc, {"group": None, "description_text": desc, "exclude_group": None, "exclude_description_text": None}, "list"),
            ("ask: apart from " + group, {"group": None, "description_text": None, "exclude_group": group, "exclude_description_text": None}, base["intent"]),
            ("ask: list those instead", dict(base["filters"]), "list"),
            ("ask: only from yesterday", dict(base["filters"]), base["intent"]),
        ]
        if tanglish:
            choices.extend([
                ("ask: adhula " + group + " evlo", {"group": group, "description_text": None, "exclude_group": None, "exclude_description_text": None}, base["intent"]),
                ("ask: " + desc + " mattum", {"group": None, "description_text": desc, "exclude_group": None, "exclude_description_text": None}, "list"),
                ("ask: " + group + " thavira", {"group": None, "description_text": None, "exclude_group": group, "exclude_description_text": None}, base["intent"]),
                ("ask: nethu mattum", dict(base["filters"]), base["intent"]),
            ])
        inp, new_filters, new_intent = rng.choice(choices)
        out = dict(base)
        out["task"] = "parse_followup_query"
        out["inherit_context"] = True
        out["intent"] = new_intent
        out["filters"] = new_filters
        if inp.endswith("yesterday"):
            out["date_start"] = "2026-05-04"
            out["date_end"] = "2026-05-04"
        return {"context": base, "input": inp, "output": out}
    if domain == "buy":
        base = make_buy_query(mode, rng)["output"]
        item = pick_buy_item(mode, rng)
        choices = [
            ("ask: show only done ones", {"status": "done", "item_text": base["filters"]["item_text"]}, base["intent"], base["date_start"], base["date_end"]),
            ("ask: only " + item, {"status": base["filters"]["status"], "item_text": item}, "search", base["date_start"], base["date_end"]),
            ("ask: only yesterday", dict(base["filters"]), base["intent"], "2026-05-04", "2026-05-04"),
            ("ask: show open ones", {"status": "open", "item_text": base["filters"]["item_text"]}, "list", base["date_start"], base["date_end"]),
        ]
        if tanglish:
            choices.extend([
                ("ask: done ones mattum", {"status": "done", "item_text": base["filters"]["item_text"]}, base["intent"], base["date_start"], base["date_end"]),
                ("ask: " + item + " mattum", {"status": base["filters"]["status"], "item_text": item}, "search", base["date_start"], base["date_end"]),
                ("ask: nethu mattum", dict(base["filters"]), base["intent"], "2026-05-04", "2026-05-04"),
                ("ask: open ones mattum", {"status": "open", "item_text": base["filters"]["item_text"]}, "list", base["date_start"], base["date_end"]),
            ])
        inp, new_filters, new_intent, ds, de = rng.choice(choices)
        out = dict(base)
        out.update({"task": "parse_followup_query", "inherit_context": True, "intent": new_intent, "filters": new_filters, "date_start": ds, "date_end": de})
        return {"context": base, "input": inp, "output": out}
    if domain == "todo":
        base = make_todo_query(mode, rng)["output"]
        task = pick_todo_text(mode, rng)
        choices = [
            ("ask: show only done ones", {"status": "done", "text_match": base["filters"]["text_match"]}, base["intent"], base["date_start"], base["date_end"]),
            ("ask: only " + task, {"status": base["filters"]["status"], "text_match": task}, "search", base["date_start"], base["date_end"]),
            ("ask: show all of them", {"status": None, "text_match": base["filters"]["text_match"]}, base["intent"], base["date_start"], base["date_end"]),
            ("ask: only from yesterday", {"status": base["filters"]["status"], "text_match": base["filters"]["text_match"]}, base["intent"], "2026-05-04", "2026-05-04"),
        ]
        if tanglish:
            choices.extend([
                ("ask: done mattum", {"status": "done", "text_match": base["filters"]["text_match"]}, base["intent"], base["date_start"], base["date_end"]),
                ("ask: " + task + " mattum", {"status": base["filters"]["status"], "text_match": task}, "search", base["date_start"], base["date_end"]),
                ("ask: ellam kaatu", {"status": None, "text_match": base["filters"]["text_match"]}, base["intent"], base["date_start"], base["date_end"]),
                ("ask: nethu mattum", {"status": base["filters"]["status"], "text_match": base["filters"]["text_match"]}, base["intent"], "2026-05-04", "2026-05-04"),
            ])
        inp, new_filters, new_intent, ds, de = rng.choice(choices)
        out = dict(base)
        out.update({"task": "parse_followup_query", "inherit_context": True, "intent": new_intent, "filters": new_filters, "date_start": ds, "date_end": de})
        return {"context": base, "input": inp, "output": out}
    if domain == "weight":
        base = make_weight_query(mode, rng)["output"]
        person = pick_name(mode, rng)
        choices = [
            ("ask: just latest", {"person_text": base["filters"]["person_text"]}, "latest", None, None, None),
            ("ask: only from last month", {"person_text": base["filters"]["person_text"]}, "history", "2026-04-01", "2026-04-30", base.get("limit")),
            ("ask: only " + person, {"person_text": person}, "latest", None, None, None),
            ("ask: show trend instead", {"person_text": base["filters"]["person_text"]}, "trend", "2025-11-05", "2026-05-05", None),
        ]
        if tanglish:
            choices.extend([
                ("ask: latest mattum", {"person_text": base["filters"]["person_text"]}, "latest", None, None, None),
                ("ask: pona maasam mattum", {"person_text": base["filters"]["person_text"]}, "history", "2026-04-01", "2026-04-30", base.get("limit")),
                ("ask: " + person + " mattum", {"person_text": person}, "latest", None, None, None),
                ("ask: trend kaatu", {"person_text": base["filters"]["person_text"]}, "trend", "2025-11-05", "2026-05-05", None),
            ])
        inp, new_filters, new_intent, ds, de, limit = rng.choice(choices)
        out = dict(base)
        out.update({"task": "parse_followup_query", "inherit_context": True, "intent": new_intent, "filters": new_filters})
        out["date_start"], out["date_end"] = ds, de
        out["limit"] = limit
        return {"context": base, "input": inp, "output": out}
    if domain == "ledger":
        base = make_ledger_query(mode, rng)["output"]
        person = pick_name(mode, rng)
        choices = [
            ("ask: show entries for that", {"person_text": base["filters"]["person_text"], "perspective": base["filters"]["perspective"], "status": base["filters"]["status"]}, "list"),
            ("ask: only " + person, {"person_text": person, "perspective": base["filters"]["perspective"], "status": base["filters"]["status"]}, base["intent"]),
            ("ask: only people who owe me", {"person_text": base["filters"]["person_text"], "perspective": "they_owe_me", "status": "open"}, "open_summary"),
            ("ask: only open ones", {"person_text": base["filters"]["person_text"], "perspective": base["filters"]["perspective"], "status": "open"}, base["intent"]),
        ]
        if tanglish:
            choices.extend([
                ("ask: andha entries kaatu", {"person_text": base["filters"]["person_text"], "perspective": base["filters"]["perspective"], "status": base["filters"]["status"]}, "list"),
                ("ask: " + person + " mattum", {"person_text": person, "perspective": base["filters"]["perspective"], "status": base["filters"]["status"]}, base["intent"]),
                ("ask: enaku tharanavanga mattum", {"person_text": base["filters"]["person_text"], "perspective": "they_owe_me", "status": "open"}, "open_summary"),
                ("ask: open mattum", {"person_text": base["filters"]["person_text"], "perspective": base["filters"]["perspective"], "status": "open"}, base["intent"]),
            ])
        inp, new_filters, new_intent = rng.choice(choices)
        out = dict(base)
        out.update({"task": "parse_followup_query", "inherit_context": True, "intent": new_intent, "filters": new_filters})
        return {"context": base, "input": inp, "output": out}
    base = make_note_query(mode, rng)["output"]
    topic = pick_topic(mode, rng)
    choices = [
        ("ask: only yesterday", {}, "search", "2026-05-04", "2026-05-04", base.get("query_text")),
        ("ask: only from last sunday", {}, "day_bucket", "2026-05-03", "2026-05-03", None),
        ("ask: show the latest note instead", {}, "latest_bucket", None, None, None),
        ("ask: only about " + topic, {}, "search", base.get("date_start"), base.get("date_end"), topic),
        ("ask: only from current month", {}, "recent", "2026-05-01", "2026-05-31", base.get("query_text")),
    ]
    if tanglish:
        choices.extend([
            ("ask: nethu mattum", {}, "search", "2026-05-04", "2026-05-04", base.get("query_text")),
            ("ask: latest note kaatu", {}, "latest_bucket", None, None, None),
            ("ask: " + topic + " pathi mattum", {}, "search", base.get("date_start"), base.get("date_end"), topic),
            ("ask: indha maasam mattum", {}, "recent", "2026-05-01", "2026-05-31", base.get("query_text")),
        ])
    inp, filters, intent, ds, de, qtext = rng.choice(choices)
    out = dict(base)
    out.update({"task": "parse_followup_query", "inherit_context": True, "intent": intent, "filters": filters, "date_start": ds, "date_end": de, "query_text": qtext})
    return {"context": base, "input": inp, "output": out}


def targeted_rows(
    target_buckets: list[str],
    maker,
    mode_sequence: list[str],
    classifier,
    rng: random.Random,
    label: str,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    idx = 0
    for bucket in target_buckets:
        attempts = 0
        max_attempts = max(2000, len(target_buckets) * 200)
        while True:
            mode = mode_sequence[idx % len(mode_sequence)]
            idx += 1
            attempts += 1
            row = maker(mode, rng)
            if classifier(row) != bucket:
                if attempts >= max_attempts:
                    raise RuntimeError(
                        f"Could not generate coverage bucket {bucket!r} for {label} after {attempts} attempts."
                    )
                continue
            key = canonical_row(row)
            if key in seen:
                if attempts >= max_attempts:
                    rows.append(row)
                    break
                continue
            seen.add(key)
            rows.append(row)
            break
    return rows


def unique_rows(
    count: int,
    maker,
    mode_sequence: list[str],
    rng: random.Random,
    label: str,
    initial_rows: list[dict] | None = None,
) -> list[dict]:
    rows = list(initial_rows or [])
    seen = {canonical_row(row) for row in rows}
    unique_bank = list(rows)
    idx = 0
    stale_attempts = 0
    max_stale_attempts = max(10000, count * 50)
    while len(rows) < count:
        mode = mode_sequence[idx % len(mode_sequence)]
        row = maker(mode, rng)
        key = canonical_row(row)
        idx += 1
        if key in seen:
            stale_attempts += 1
            if stale_attempts >= max_stale_attempts:
                if UNIQUENESS_POLICY == "soft" and unique_bank:
                    while len(rows) < count:
                        rows.append(rng.choice(unique_bank))
                    print(
                        f"[soft-uniqueness] {label}: requested {count}, unique capacity reached "
                        f"{len(unique_bank)} after {idx} attempts; filled remaining rows with repeats."
                    )
                    return rows
                raise RuntimeError(
                    f"Generator stalled for {label}: requested {count} unique rows, "
                    f"but only reached {len(rows)} unique rows after {idx} attempts. "
                    f"This lane likely lacks enough unique combinations for the requested count."
                )
            continue
        seen.add(key)
        rows.append(row)
        unique_bank.append(row)
        stale_attempts = 0
    return rows


def generate_lane_rows(
    count: int,
    maker,
    coverage_key: str,
    rng: random.Random,
    coverage_passes: int = TRAIN_COVERAGE_PASSES,
) -> list[dict]:
    classifier = COVERAGE_CLASSIFIERS[coverage_key]
    buckets = COVERAGE_BUCKETS[coverage_key]
    targets = build_coverage_targets(count, buckets, rng, passes=coverage_passes)
    initial_rows = targeted_rows(
        targets,
        maker,
        choose_modes(max(count, len(targets) * 3), rng),
        classifier,
        rng,
        coverage_key,
    )
    rows = unique_rows(
        count,
        maker,
        choose_modes(max(count, 1), rng),
        rng,
        coverage_key,
        initial_rows=initial_rows,
    )
    rng.shuffle(rows)
    return rows


def generate_dataset(
    out_dir: Path = OUT_DIR,
    write_count: int = WRITE_COUNT,
    query_count: int = QUERY_COUNT,
    reference_count: int = REFERENCE_COUNT,
    followup_count: int = FOLLOWUP_COUNT,
) -> None:
    rng = random.Random(SEED)
    if out_dir.exists():
        for p in out_dir.rglob("*"):
            if p.is_file():
                p.unlink()
        for p in sorted([x for x in out_dir.rglob("*") if x.is_dir()], reverse=True):
            if p != out_dir:
                p.rmdir()
    out_dir.mkdir(exist_ok=True)
    (out_dir / "parse_write").mkdir(exist_ok=True)
    (out_dir / "parse_query").mkdir(exist_ok=True)
    (out_dir / "parse_followup_query").mkdir(exist_ok=True)
    (out_dir / "reference_only").mkdir(exist_ok=True)

    write_rows = {
        "expense": generate_lane_rows(write_count, make_expense_write, "parse_write/expense", rng),
        "buy": generate_lane_rows(write_count, make_buy_write, "parse_write/buy", rng),
        "todo": generate_lane_rows(write_count, make_todo_write, "parse_write/todo", rng),
        "weight": generate_lane_rows(write_count, make_weight_write, "parse_write/weight", rng),
        "ledger": generate_lane_rows(write_count, make_ledger_write, "parse_write/ledger", rng),
    }
    query_rows = {
        "note": generate_lane_rows(query_count, make_note_query, "parse_query/note", rng),
        "expense": generate_lane_rows(query_count, make_expense_query, "parse_query/expense", rng),
        "buy": generate_lane_rows(query_count, make_buy_query, "parse_query/buy", rng),
        "todo": generate_lane_rows(query_count, make_todo_query, "parse_query/todo", rng),
        "weight": generate_lane_rows(query_count, make_weight_query, "parse_query/weight", rng),
        "ledger": generate_lane_rows(query_count, make_ledger_query, "parse_query/ledger", rng),
    }
    followups = generate_lane_rows(followup_count, make_followup, "parse_followup_query/mixed_followups", rng)
    note_reference = unique_rows(reference_count, make_note_reference, choose_modes(reference_count, rng), rng, "reference_only/note_write_reference")
    rng.shuffle(note_reference)

    for name, rows in write_rows.items():
        write_jsonl(out_dir / "parse_write" / f"{name}.jsonl", rows)
    for name, rows in query_rows.items():
        write_jsonl(out_dir / "parse_query" / f"{name}.jsonl", rows)
    write_jsonl(out_dir / "parse_followup_query" / "mixed_followups.jsonl", followups)
    write_jsonl(out_dir / "reference_only" / "note_write_reference.jsonl", note_reference)

    total = (write_count * 5) + (query_count * 6) + followup_count + reference_count
    readme = f"""# Large Schema-Frozen Dataset v3

Generated by `generate_large_schema_frozen_dataset.py`

Source rules:
- `finetuning_data_sanity.md`
- `dataset_india_context_rulebook.md`

Anchor date:
- `{ANCHOR_DATE}`

Context ratio target:
- `70%` India
- `30%` global

Counts:
- parse_write/expense.jsonl -> {write_count}
- parse_write/buy.jsonl -> {write_count}
- parse_write/todo.jsonl -> {write_count}
- parse_write/weight.jsonl -> {write_count}
- parse_write/ledger.jsonl -> {write_count}
- parse_query/note.jsonl -> {query_count}
- parse_query/expense.jsonl -> {query_count}
- parse_query/buy.jsonl -> {query_count}
- parse_query/todo.jsonl -> {query_count}
- parse_query/weight.jsonl -> {query_count}
- parse_query/ledger.jsonl -> {query_count}
- parse_followup_query/mixed_followups.jsonl -> {followup_count}
- reference_only/note_write_reference.jsonl -> {reference_count}

Total JSON objects:
- {total}
- each parser lane is guaranteed to include explicit coverage rows for every important bucket before final shuffle
- output rows are shuffled after coverage seeding so the training set does not stay in a fixed pattern order
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="Print asset/template coverage counts without generating the dataset.")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Output dataset directory.")
    parser.add_argument("--write-count", type=int, default=WRITE_COUNT, help="Rows per parse_write lane.")
    parser.add_argument("--query-count", type=int, default=QUERY_COUNT, help="Rows per parse_query lane.")
    parser.add_argument("--reference-count", type=int, default=REFERENCE_COUNT, help="Rows for reference_only/note_write_reference.")
    parser.add_argument("--followup-count", type=int, default=FOLLOWUP_COUNT, help="Rows for parse_followup_query/mixed_followups.")
    args = parser.parse_args()

    if args.report:
        report_assets()
        return

    generate_dataset(
        out_dir=Path(args.out_dir),
        write_count=args.write_count,
        query_count=args.query_count,
        reference_count=args.reference_count,
        followup_count=args.followup_count,
    )


if __name__ == "__main__":
    main()
