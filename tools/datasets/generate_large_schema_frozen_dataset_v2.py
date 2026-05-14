"""
v2 dataset generator for the tag-first parser fine-tune.

Source of truth: docs/model-training.md.
Schema reference: docs/model-training.md - "Shared Schema Freeze v2".
Diversity rules: docs/model-training.md - "v2 Amendments".

Differences from the earlier v1 generator:
- Multi-anchor: every row carries a top-level "anchor_date"; relative date
  phrases resolve relative to that row's anchor.
- Harmonized intent vocabulary per docs/model-training.md Section 1.3.
- New parse_query dispositions: accept | clarify | reject.
- Per-lane x per-pattern Tanglish gating (Pattern A/B/C). Pattern C is 0%
  everywhere. Tanglish date phrases (innaiku, indha maasam, ...) are excluded
  from queries entirely; they appear only in todo-write Pattern B contexts.
- Phrasing pool expansion: 10-15 templates per form, 35/30/20/15 style mix.
- Scoped queries 25-35 percent per lane (up from <5 percent in v1).
- New slices: adversarial domain pairs, bare-nameless variants, real typo
  module, action-shaped clarify, multi-person compare reject.
- Reject pool widening: rejects sample from full asset pool.
- Ledger reason notes dropped: every ledger record's "note" field is null.
- reference_only/ is not generated. Note write is a deterministic app bypass.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from synthetic_dataset_assets import (
    GLOBAL_BUY,
    GLOBAL_EXPENSE,
    GLOBAL_NAMES,
    GLOBAL_NOTE_TOPICS,
    GLOBAL_TODOS,
    GLOBAL_TODO_NOUNS,
    INDIA_BUY,
    INDIA_EXPENSE,
    INDIA_NAMES,
    INDIA_NOTE_TOPICS,
    INDIA_TODOS,
    INDIA_TODO_NOUNS,
    RANGE_OPTIONS,
    SINGLE_DATE_OPTIONS,
    TANGLISH_RANGE_KEYS,
    TANGLISH_SINGLE_DATE_KEYS,
)


# Per docs/model-training.md Section 7.1, refined in the v2 review session.
#
# Anchors are 5 (year, month) pairs spread across 2026. Day-of-month is
# randomized PER ROW (uniform within the actual length of the chosen month).
# This keeps the seasonal coverage of the 5-anchor strategy but widens
# `Today: <YYYY-MM-DD>` token exposure so the model doesn't only ever see
# day=15 strings during training.
ANCHOR_MONTHS: list[tuple[int, int]] = [
    (2026, 1),
    (2026, 3),
    (2026, 5),
    (2026, 8),
    (2026, 11),
]

# Back-compat: a stable list of one representative date per anchor month
# (day=15). Not used to pick training anchors any more — `pick_anchor_iso`
# below is the live picker. Retained because external callers (notably
# `generate_eval_dataset_v3.py`) historically imported `ANCHORS`.
ANCHORS: list[str] = [f"{y:04d}-{m:02d}-15" for y, m in ANCHOR_MONTHS]

OUT_DIR = Path("synthetic_finetune_dataset_v4_v2_schema")
SEED = 20260507

WRITE_COUNT = 5000
QUERY_COUNT = 5000
FOLLOWUP_COUNT = 6000
# v2: reference_only is not generated. The deterministic note-write bypass
# stays out of SFT and does not need synthetic rows.
REFERENCE_COUNT = 0

UNIQUENESS_POLICY = "soft"

# Adversarial / specialty slice counts per docs/model-training.md Section 5.
ADVERSARIAL_PAIR_COUNT = 400       # produces 800 rows
ACTION_CLARIFY_COUNT = 300   # ledger
MULTI_PERSON_REJECT_COUNT = 300    # weight

# Date-phrase routing per Section 7.3.
DATE_BREADTH_CANONICAL = 0.60
DATE_BREADTH_RANDOM_KEY = 0.30
DATE_BREADTH_ABSOLUTE = 0.10

# Typo module rate per Section 5.3.
SEARCH_TYPO_RATE = 0.07

# Bare-nameless rate per Section 5.2.
BARE_NAMELESS_RATE = 0.10


# ---------------------------------------------------------------------------
# Date resolver
#
# Each anchor in ANCHORS gets a precomputed mapping of canonical date phrases
# to either a single resolved date or a (start, end) range. Tanglish date
# keys (Pattern C) are NOT included in the query-safe pool; they are tracked
# separately for todo-write Pattern B usage.
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
_WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]


def _parse_iso(s: str) -> date:
    return date.fromisoformat(s)


def _iso(d: date) -> str:
    return d.isoformat()


def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _add_months(d: date, n: int) -> date:
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    last = _last_day_of_month(date(year, month, 1)).day
    return date(year, month, min(d.day, last))


def _india_fiscal_year(d: date) -> tuple[date, date]:
    if d.month >= 4:
        return date(d.year, 4, 1), date(d.year + 1, 3, 31)
    return date(d.year - 1, 4, 1), date(d.year, 3, 31)


def _india_fiscal_quarter(d: date) -> tuple[date, date]:
    fy_start, _ = _india_fiscal_year(d)
    months_in = (d.year - fy_start.year) * 12 + (d.month - fy_start.month)
    q_idx = months_in // 3
    q_start_month = fy_start.month + q_idx * 3
    q_start_year = fy_start.year + (fy_start.month - 1 + q_idx * 3) // 12
    q_start_month = (fy_start.month - 1 + q_idx * 3) % 12 + 1
    q_start = date(q_start_year, q_start_month, 1)
    q_end = _last_day_of_month(_add_months(q_start, 2))
    return q_start, q_end


def compute_options_for_anchor(anchor_iso: str) -> dict:
    """Build the (single, range, todo_write_extra, absolute_dates) lookup for
    one anchor. Used both for date-phrase generation and for the per-anchor
    random-key pool described in docs/model-training.md Section 7.3."""
    a = _parse_iso(anchor_iso)
    single: dict[str, str] = {}
    range_: dict[str, tuple[str, str]] = {}

    # Pure relative singles
    single["today"] = _iso(a)
    single["tdy"] = _iso(a)
    single["yesterday"] = _iso(a - timedelta(days=1))
    single["yday"] = _iso(a - timedelta(days=1))
    single["tomorrow"] = _iso(a + timedelta(days=1))
    single["tmrw"] = _iso(a + timedelta(days=1))
    single["two days ago"] = _iso(a - timedelta(days=2))
    single["three days ago"] = _iso(a - timedelta(days=3))
    single["this morning"] = _iso(a)
    single["this afternoon"] = _iso(a)
    single["this noon"] = _iso(a)
    single["this evening"] = _iso(a)
    single["tonight"] = _iso(a)
    single["last night"] = _iso(a - timedelta(days=1))
    single["last evening"] = _iso(a - timedelta(days=1))
    single["early morning"] = _iso(a)
    single["morn"] = _iso(a)
    single["eve"] = _iso(a)
    single["night"] = _iso(a)

    # Weekdays - bare and "last" / "next"
    for i, name in enumerate(_WEEKDAY_NAMES):
        diff_back = (a.weekday() - i) % 7
        bare = a - timedelta(days=diff_back)
        single[name] = _iso(bare)
        last_diff = diff_back if diff_back > 0 else 7
        single[f"last {name}"] = _iso(a - timedelta(days=last_diff))
        next_diff = (i - a.weekday()) % 7
        next_diff = next_diff if next_diff > 0 else 7
        single[f"next {name}"] = _iso(a + timedelta(days=next_diff))
        single[f"coming {name}"] = single[f"next {name}"]

    # Range form of single dates
    for k, v in list(single.items()):
        range_[k] = (v, v)

    # Week ranges
    monday = a - timedelta(days=a.weekday())
    sunday = monday + timedelta(days=6)
    range_["this week"] = (_iso(monday), _iso(sunday))
    range_["this wk"] = range_["this week"]
    range_["current wk"] = range_["this week"]
    range_["week beginning"] = (_iso(monday), _iso(monday))
    range_["week close"] = (_iso(sunday), _iso(sunday))
    last_mon = monday - timedelta(days=7)
    last_sun = last_mon + timedelta(days=6)
    range_["last week"] = (_iso(last_mon), _iso(last_sun))
    range_["last wk"] = range_["last week"]
    range_["week before last"] = (_iso(monday - timedelta(days=14)), _iso(monday - timedelta(days=8)))
    range_["monday to friday"] = (_iso(monday), _iso(monday + timedelta(days=4)))
    range_["last business week"] = (_iso(last_mon), _iso(last_mon + timedelta(days=4)))

    # Trailing-N-day windows (anchor inclusive)
    range_["past week"] = (_iso(a - timedelta(days=6)), _iso(a))
    range_["past fortnight"] = (_iso(a - timedelta(days=13)), _iso(a))
    range_["past 10 days"] = (_iso(a - timedelta(days=9)), _iso(a))
    range_["past 2 weeks"] = (_iso(a - timedelta(days=13)), _iso(a))
    range_["past month"] = (_iso(a - timedelta(days=29)), _iso(a))
    range_["past 60 days"] = (_iso(a - timedelta(days=59)), _iso(a))
    range_["last 3 days"] = (_iso(a - timedelta(days=2)), _iso(a))
    range_["last 7 days"] = (_iso(a - timedelta(days=6)), _iso(a))
    range_["last 30 days"] = (_iso(a - timedelta(days=29)), _iso(a))
    range_["last 60 days"] = (_iso(a - timedelta(days=59)), _iso(a))

    # Months relative to anchor
    month_start = a.replace(day=1)
    month_end = _last_day_of_month(a)
    range_["this month"] = (_iso(month_start), _iso(month_end))
    range_["current month"] = range_["this month"]
    range_["month to date"] = (_iso(month_start), _iso(a))
    range_["till today"] = range_["month to date"]
    range_["month start"] = (_iso(month_start), _iso(month_start))
    range_["month end"] = (_iso(month_end), _iso(month_end))
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    range_["last month"] = (_iso(last_month_start), _iso(last_month_end))

    # Calendar months: bare "<month>" resolves to the most-recent occurrence
    # on or before the anchor (so for anchor 2026-01-15 the key "december"
    # resolves to 2025-12, not a future December). No "last year" suffix is
    # generated; users naturally say "december" rather than "december last
    # year".
    month_year_pairs: list[tuple[int, int, str]] = []
    for m in range(1, 13):
        year = a.year if m <= a.month else a.year - 1
        month_year_pairs.append((year, m, _MONTH_NAMES[m - 1]))

    for year, m, name in month_year_pairs:
        m_start = date(year, m, 1)
        m_end = _last_day_of_month(m_start)
        range_[name] = (_iso(m_start), _iso(m_end))
        range_[f"{name} month"] = range_[name]
        range_[f"first half of {name}"] = (_iso(m_start), _iso(date(year, m, 15)))
        range_[f"second half of {name}"] = (_iso(date(year, m, 16)), _iso(m_end))
        for w_idx, w_name in enumerate(["first", "second", "third", "fourth"]):
            w_start = m_start + timedelta(days=7 * w_idx)
            w_end = m_end if w_idx == 3 else min(w_start + timedelta(days=6), m_end)
            range_[f"{name} {w_name} week"] = (_iso(w_start), _iso(w_end))
        # absolute single-day phrasings
        for d_n in range(1, m_end.day + 1):
            d = date(year, m, d_n)
            for fmt in (
                f"on {name} {d_n}",
                f"{name} {d_n}",
                f"on {d_n} {name}",
                f"{d_n} {name}",
            ):
                single[fmt] = _iso(d)
                range_[fmt] = (_iso(d), _iso(d))
        for s in (1, 16):
            e = 15 if s == 1 else m_end.day
            range_[f"from {name} {s} to {name} {e}"] = (
                _iso(date(year, m, s)),
                _iso(date(year, m, e)),
            )

    # Quarter relative to anchor (calendar)
    q_idx = (a.month - 1) // 3
    q_start = date(a.year, q_idx * 3 + 1, 1)
    q_end = _last_day_of_month(_add_months(q_start, 2))
    range_["this quarter"] = (_iso(q_start), _iso(q_end))
    range_["current quarter"] = range_["this quarter"]
    range_["quarter to date"] = (_iso(q_start), _iso(a))

    # Indian fiscal quarter / fiscal year
    fq_start, fq_end = _india_fiscal_quarter(a)
    fy_start, fy_end = _india_fiscal_year(a)
    range_["this financial quarter"] = (_iso(fq_start), _iso(fq_end))
    range_["current financial quarter"] = range_["this financial quarter"]
    range_["this financial year"] = (_iso(fy_start), _iso(fy_end))
    range_["current financial year"] = range_["this financial year"]

    # Year to date / since january
    range_["year to date"] = (_iso(date(a.year, 1, 1)), _iso(a))
    range_["since january"] = range_["year to date"]

    # Weekend (the upcoming Sat-Sun, or current if anchor is on the weekend)
    sat_diff = (5 - a.weekday()) % 7
    sat = a + timedelta(days=sat_diff)
    sun = sat + timedelta(days=1)
    single["weekend"] = _iso(sat)
    single["this weekend"] = _iso(sat)
    single["wknd"] = _iso(sat)
    range_["weekend"] = (_iso(sat), _iso(sun))
    range_["this weekend"] = range_["weekend"]
    range_["wknd"] = range_["weekend"]

    # Tanglish keys (todo-write Pattern B only). Built separately so they can
    # never leak into query generation.
    todo_write_single: dict[str, str] = {
        "innaiku": single["today"],
        "inniku": single["today"],
        "nethu": single["yesterday"],
        "naalaiku": single["tomorrow"],
        "indha kaalaila": single["today"],
        "indha saayangaalam": single["today"],
        "pona sunday": single["last sunday"],
        "pona friday": single["last friday"],
    }
    todo_write_range: dict[str, tuple[str, str]] = {
        "indha maasam": range_["this month"],
        "current maasam": range_["this month"],
        "pona maasam": range_["last month"],
        "indha vaaram": range_["this week"],
        "pona vaaram": range_["last week"],
        "innaiku": range_["today"],
        "nethu": range_["yesterday"],
    }

    return {
        "anchor": anchor_iso,
        "single": single,
        "range": range_,
        "todo_write_single": todo_write_single,
        "todo_write_range": todo_write_range,
    }


# Lazy cache of resolved date options per anchor ISO date.
#
# Anchor day-of-month is now randomized per row, so the cache key space is up
# to ~150 distinct dates (5 months times ~30 days) rather than the 5 fixed
# strings of the earlier v2 design. Building on demand keeps cold-start cost
# proportional to the rows actually generated.
_ANCHOR_OPTIONS_CACHE: dict[str, dict] = {}


def _last_day_of_year_month(year: int, month: int) -> int:
    return _last_day_of_month(date(year, month, 1)).day


def pick_anchor_iso(rng: random.Random) -> str:
    """Pick a random anchor: uniform month from ANCHOR_MONTHS, uniform day in
    that month. Year is fixed at 2026 for every entry currently."""
    year, month = rng.choice(ANCHOR_MONTHS)
    day = rng.randint(1, _last_day_of_year_month(year, month))
    return f"{year:04d}-{month:02d}-{day:02d}"


def options_for(anchor: str) -> dict:
    cached = _ANCHOR_OPTIONS_CACHE.get(anchor)
    if cached is not None:
        return cached
    cached = compute_options_for_anchor(anchor)
    _ANCHOR_OPTIONS_CACHE[anchor] = cached
    return cached


def query_safe_range_keys(anchor: str) -> list[str]:
    """Range keys allowed in parse_query rows. Excludes Tanglish Pattern C
    keys and time-of-day keys (queries don't support time-of-day filtering)."""
    return [
        k for k in options_for(anchor)["range"].keys()
        if k not in TANGLISH_RANGE_KEYS and k not in TIME_OF_DAY_KEYS
    ]


def query_safe_single_keys(anchor: str) -> list[str]:
    return [
        k for k in options_for(anchor)["single"].keys()
        if k not in TANGLISH_SINGLE_DATE_KEYS and k not in TIME_OF_DAY_KEYS
    ]


def resolve_range(anchor: str, key: str) -> tuple[str, str]:
    return options_for(anchor)["range"][key]


def resolve_single(anchor: str, key: str) -> str:
    return options_for(anchor)["single"][key]


# Anchor-relative semantic helpers used by query makers.

def anchor_today(anchor: str) -> str:
    return resolve_single(anchor, "today")


def anchor_yesterday(anchor: str) -> str:
    return resolve_single(anchor, "yesterday")


def anchor_this_month(anchor: str) -> tuple[str, str]:
    return resolve_range(anchor, "this month")


def anchor_last_month(anchor: str) -> tuple[str, str]:
    return resolve_range(anchor, "last month")


def anchor_this_week(anchor: str) -> tuple[str, str]:
    return resolve_range(anchor, "this week")


def anchor_six_months_window(anchor: str) -> tuple[str, str]:
    """Default weight history range: anchor minus 6 months -> anchor."""
    a = _parse_iso(anchor)
    start = _add_months(a, -6)
    return _iso(start), _iso(a)


def anchor_year_to_date(anchor: str) -> tuple[str, str]:
    return resolve_range(anchor, "year to date")


# ---------------------------------------------------------------------------
# parse_query disposition shape builders
#
# Per docs/model-training.md "Shared Schema Freeze v2", every parse_query
# row carries a uniform field set across dispositions: disposition,
# reason_code, clarify_reason, clarify_options. Accept rows fill intent /
# date_start / date_end / filters / limit / query_text; clarify and reject
# rows leave them null.
# ---------------------------------------------------------------------------

PARSE_QUERY_FIELDS = (
    "task", "domain", "disposition", "intent",
    "date_start", "date_end", "compare_date_start", "compare_date_end",
    "filters", "limit", "query_text",
    "reason_code", "clarify_reason", "clarify_options",
)


def parse_query_accept(
    *,
    domain: str,
    intent: str,
    filters: dict,
    date_start: str | None = None,
    date_end: str | None = None,
    compare_date_start: str | None = None,
    compare_date_end: str | None = None,
    limit: int | None = None,
    query_text: str | None = None,
) -> dict:
    return {
        "task": "parse_query",
        "domain": domain,
        "disposition": "accept",
        "intent": intent,
        "date_start": date_start,
        "date_end": date_end,
        "compare_date_start": compare_date_start,
        "compare_date_end": compare_date_end,
        "filters": filters,
        "limit": limit,
        "query_text": query_text,
        "reason_code": None,
        "clarify_reason": None,
        "clarify_options": None,
    }


def parse_query_clarify(
    *,
    domain: str,
    clarify_reason: str,
    clarify_options: list[str],
) -> dict:
    return {
        "task": "parse_query",
        "domain": domain,
        "disposition": "clarify",
        "intent": None,
        "date_start": None,
        "date_end": None,
        "compare_date_start": None,
        "compare_date_end": None,
        "filters": None,
        "limit": None,
        "query_text": None,
        "reason_code": None,
        "clarify_reason": clarify_reason,
        "clarify_options": clarify_options,
    }


def parse_query_reject(
    *,
    domain: str,
    reason_code: str,
) -> dict:
    return {
        "task": "parse_query",
        "domain": domain,
        "disposition": "reject",
        "intent": None,
        "date_start": None,
        "date_end": None,
        "compare_date_start": None,
        "compare_date_end": None,
        "filters": None,
        "limit": None,
        "query_text": None,
        "reason_code": reason_code,
        "clarify_reason": None,
        "clarify_options": None,
    }


def parse_followup_query_accept(
    *,
    domain: str,
    intent: str,
    filters: dict | None,
    date_start: str | None = None,
    date_end: str | None = None,
    compare_date_start: str | None = None,
    compare_date_end: str | None = None,
    limit: int | None = None,
    query_text: str | None = None,
) -> dict:
    return {
        "task": "parse_followup_query",
        "domain": domain,
        "disposition": "accept",
        "intent": intent,
        "date_start": date_start,
        "date_end": date_end,
        "compare_date_start": compare_date_start,
        "compare_date_end": compare_date_end,
        "filters": filters,
        "limit": limit,
        "query_text": query_text,
        "reason_code": None,
        "clarify_reason": None,
        "clarify_options": None,
        "inherit_context": True,
    }


# ---------------------------------------------------------------------------
# Form-distribution weights per docs/model-training.md Section 3.1.
# Each entry: form -> percentage. Scoped percentage is tracked separately.
# Within a scoped row, the form distribution is the same as unscoped.
# ---------------------------------------------------------------------------

EXPENSE_FORM_WEIGHTS: dict[str, float] = {
    # 2026-05-09: rebalanced. Audit of v4_v2_schema showed 80% of expense
    # query training rows had BOTH description_text=null AND group=null,
    # which the model learned as the dominant correct answer — `ask: total
    # milk expense` returned ₹34607 (everything) because the model defaulted
    # to null filters. Bumped desc 6→18, group 7→12, exclude 2→3 so the
    # filter-bearing share rises from ~21% to ~39% of the bucket.
    # 2026-05-09 (later): added top_n form (weight 5) for "top 3 expenses",
    # "biggest spending", "highest amount" phrasings — model needs to emit
    # explicit `limit` field for these.
    "total": 14, "list": 12, "today": 5, "group": 12, "desc": 18,
    "recent": 4, "last_month": 3, "exclude": 3, "compare": 1, "history": 1,
    "top_n": 5,
}
WEIGHT_FORM_WEIGHTS: dict[str, float] = {
    # multi_person_compare_reject bumped from §3.1's 2% to 3% so the §5.6
    # explicit row target (~150 rows in 4000) is hit naturally inside the
    # weight lane budget. All other weights match §3.1.
    "latest": 35, "history": 12, "latest_all": 8, "trend": 6, "date": 6,
    "change": 3, "multi_person_compare_reject": 3,
}
LEDGER_FORM_WEIGHTS: dict[str, float] = {
    # action_clarify bumped from §3.1's 2% to 4% so the §5.5 explicit row
    # target (~200 rows in 4000) is hit. All other weights match §3.1.
    "summary": 18, "balance": 14, "person": 11, "who": 11, "recent": 7,
    "range": 4, "search": 3, "latest": 2, "action_clarify": 4,
}
BUY_FORM_WEIGHTS: dict[str, float] = {
    "list": 35, "search": 18, "today": 7, "date": 5, "all": 5,
}
TODO_FORM_WEIGHTS: dict[str, float] = {
    "list_open": 28, "today": 11, "search": 9, "all": 7,
    "due_week": 7, "history": 4, "done_today": 4,
}
NOTE_FORM_WEIGHTS: dict[str, float] = {
    "search": 28, "list_recent": 22, "latest": 10, "list_absolute": 3,
    "list_day": 0,  # rolled into list_recent / search by phrasing
    # 2026-05-09: bare-name clarify lane. ~7% of note queries train the model
    # to emit disposition=clarify when the input is just a bare name or
    # 1-word ambiguous reference. Without this, dogfood logs (#65, #93)
    # showed the model silently misclassified to todo/ledger and returned
    # wrong rows. Note is the natural landing because it's the catch-all
    # lane — but the clarify_options point the user to other lanes.
    "bare_name_clarify": 7,
}

LANE_FORM_WEIGHTS: dict[str, dict[str, float]] = {
    "expense": EXPENSE_FORM_WEIGHTS,
    "weight": WEIGHT_FORM_WEIGHTS,
    "ledger": LEDGER_FORM_WEIGHTS,
    "buy": BUY_FORM_WEIGHTS,
    "todo": TODO_FORM_WEIGHTS,
    "note": NOTE_FORM_WEIGHTS,
}

SCOPED_SHARE: dict[str, float] = {
    "expense": 0.28,
    "weight": 0.28,
    "ledger": 0.28,
    "buy": 0.30,
    "todo": 0.30,
    "note": 0.30,
}


def weighted_choice(weights: dict[str, float], rng: random.Random) -> str:
    keys = list(weights.keys())
    vals = [weights[k] for k in keys]
    return rng.choices(keys, weights=vals)[0]


# ---------------------------------------------------------------------------
# Per-pattern Tanglish gating per docs/model-training.md Section 2.
# ---------------------------------------------------------------------------

# Pattern A (Tamil noun in English frame) shares per lane.
PATTERN_A_SHARE: dict[str, float] = {
    "expense_write": 0.30,
    "buy_write": 0.30,
    "todo_write": 0.05,
    "weight_write": 0.0,
    "ledger_write": 0.0,
    "expense_query": 0.18,
    "buy_query": 0.18,
    "todo_query": 0.06,
    "weight_query": 0.0,
    "ledger_query": 0.0,
    "note_query": 0.18,
}

# Pattern B (English nouns + Tamil verbs / dative / postposition / time).
# Only enabled for todo-write per Section 2.
PATTERN_B_SHARE: dict[str, float] = {
    "expense_write": 0.0,
    "buy_write": 0.0,
    "todo_write": 0.50,
    "weight_write": 0.0,
    "ledger_write": 0.0,
    "expense_query": 0.0,
    "buy_query": 0.0,
    "todo_query": 0.0,
    "weight_query": 0.0,
    "ledger_query": 0.0,
    "note_query": 0.0,
}


def use_pattern_a(slot: str, mode: str, rng: random.Random) -> bool:
    if mode != "india":
        return False
    return rng.random() < PATTERN_A_SHARE.get(slot, 0.0)


def use_pattern_b(slot: str, mode: str, rng: random.Random) -> bool:
    if mode != "india":
        return False
    return rng.random() < PATTERN_B_SHARE.get(slot, 0.0)


# ---------------------------------------------------------------------------
# Asset pickers
# ---------------------------------------------------------------------------

def pick_name(mode: str, rng: random.Random) -> str:
    return rng.choice(INDIA_NAMES if mode == "india" else GLOBAL_NAMES)


def pick_topic(mode: str, rng: random.Random) -> str:
    return rng.choice(INDIA_NOTE_TOPICS if mode == "india" else GLOBAL_NOTE_TOPICS)


def expense_catalog(mode: str) -> dict[str, list[str]]:
    return INDIA_EXPENSE if mode == "india" else GLOBAL_EXPENSE


def pick_expense_item(mode: str, rng: random.Random) -> tuple[str, str]:
    catalog = expense_catalog(mode)
    group = rng.choice(list(catalog.keys()))
    return rng.choice(catalog[group]), group


def pick_buy_item(mode: str, rng: random.Random) -> str:
    return rng.choice(INDIA_BUY if mode == "india" else GLOBAL_BUY)


def pick_todo_text(mode: str, rng: random.Random) -> str:
    if rng.random() < 0.4:
        pool = INDIA_TODO_NOUNS if mode == "india" else GLOBAL_TODO_NOUNS
    else:
        pool = INDIA_TODOS if mode == "india" else GLOBAL_TODOS
    return rng.choice(pool)


def contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


# ---------------------------------------------------------------------------
# Amount helpers (ported from v1; unchanged in v2)
# ---------------------------------------------------------------------------

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


def amount_text_and_value(rng: random.Random, large_ok: bool = True, foreign_ok: bool = False) -> tuple[str, float | int]:
    # 2026-05-09: expanded styles for currency notation depth (gap #1).
    # User dogfood logs show input shapes like `25k` / `25K` / `Rs.25000` /
    # `25000/-` / `25 thousand` — many were unseen by the model.
    styles = ["plain", "rs", "rs_dot", "rs_slash", "comma", "decimal",
              "k_lower", "k_upper", "k_thousand"]
    if large_ok:
        styles.extend(["L", "L_upper", "lakh", "lakhs", "crore", "crores"])
    if foreign_ok:
        styles.append("usd")
    style = rng.choice(styles)
    if style == "plain":
        value = rng.randint(18, 9999)
        return str(value), value
    if style == "rs":
        value = rng.randint(18, 9999)
        return f"rs {value}", value
    if style == "rs_dot":
        # `Rs.500`, `Rs.25000` — common Indian shorthand
        value = rng.randint(50, 25000)
        prefix = rng.choice(["Rs.", "Rs. ", "rs.", "INR ", "inr "])
        return f"{prefix}{value}", value
    if style == "rs_slash":
        # `500/-`, `25000/-` — Indian rupee suffix shorthand
        value = rng.randint(50, 50000)
        return f"{value}/-", value
    if style == "comma":
        value = rng.randint(1200, 25000)
        return f"{value:,}", value
    if style == "decimal":
        value = round(rng.uniform(18, 999), 2)
        return str(value), value
    if style == "k_lower":
        base = rng.choice([1.5, 2, 2.5, 5, 7.5, 9])
        return f"{base}k", int(base * 1000)
    if style == "k_upper":
        base = rng.choice([1, 2, 5, 10, 25, 50])
        return f"{base}K", int(base * 1000)
    if style == "k_thousand":
        # Spelled-out: `5 thousand`, `25 thousand`
        base = rng.choice([2, 5, 10, 25, 50, 100])
        return f"{base} thousand", base * 1000
    if style == "L":
        base = rng.choice([1.5, 2, 3, 4.5])
        return f"{base}L", int(base * 100000)
    if style == "L_upper":
        base = rng.choice([1, 2, 3, 5])
        return f"{base}L", int(base * 100000)
    if style == "lakh":
        base = rng.choice([2, 3, 5, 7])
        return f"{base} lakh", base * 100000
    if style == "lakhs":
        base = rng.choice([2, 3, 5, 7, 10])
        return f"{base} lakhs", base * 100000
    if style == "crore":
        base = rng.choice([1, 2, 3])
        return f"{base} crore", base * 10000000
    if style == "crores":
        base = rng.choice([1, 2, 3])
        return f"{base} crores", base * 10000000
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


# ---------------------------------------------------------------------------
# Buy quantity helpers (ported from v1; unchanged in v2)
# ---------------------------------------------------------------------------

FOOD_OR_POWDER_KEYWORDS = {
    "curd", "rice", "poha", "hing", "asafoetida", "coriander", "fenugreek", "millets", "dal", "flour", "oil",
    "seeds", "cumin", "toothpaste", "banana", "paneer", "semiya", "tomato", "onion", "garlic", "paste",
    "bagel", "oat", "granola", "olive", "coffee", "tea", "mushroom", "spinach", "sauce", "yogurt", "powder",
    "sugar", "salt", "tamarind", "papad", "rava", "maida", "besan", "milk", "starter", "chips", "pickle",
    "phenyl", "dettol", "wipes", "cleaner", "wash", "shampoo", "lotion", "cream", "syrup", "eyedrops",
    "kothamalli", "puthina", "karuveppilai", "kadugu", "jeeragam", "sombu", "milagu", "manjal", "perungayam",
    "vendhayam", "ulutham", "thuvaram", "paasi", "kadalai", "arisi", "ravai", "aval", "milagai", "sambar podi",
    "rasam podi", "vengayam", "thakkali", "thengai", "thayir", "nei", "ennai",
}
BAR_LIKE_KEYWORDS = {"soap", "bars", "detergent cake", "agarbathi", "camphor", "cotton wick", "candles"}
BAR_LIKE_EXACT_ITEMS = {"lux", "dove", "lux soap", "dove soap"}
PACK_ONLY_KEYWORDS = {
    "pads", "napkins", "tissue", "towels", "clips", "markers", "pens", "batteries", "battery", "pods", "filters",
    "hooks", "mailers", "wipes", "plates", "cells", "coils", "match box", "rubber bands", "pins",
}
COUNT_ONLY_KEYWORDS = {
    "bulb", "notebook", "helmet", "visor", "blanket", "cups", "extension", "charger", "cable", "lamp", "light",
    "board", "box", "tube light", "phone", "storage", "basket", "tumbler", "mug", "gasket", "bottle", "torch",
    "socks", "organizer", "sleeve", "tripod", "scarf", "bag", "tote", "jacket", "pack",
}
HERB_OR_LEAF_KEYWORDS = {"kothamalli", "puthina", "karuveppilai", "coriander", "mint", "banana leaf", "fenugreek leaves"}
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
COCONUT_OR_COUNT_PRODUCE_KEYWORDS = {"coconut", "thengai", "banana leaf"}
DRY_GROCERY_KEYWORDS = {"tamarind", "salt", "sugar", "papad", "pickle", "chips", "tea", "coffee powder", "powder"}
VEGETABLE_KG_KEYWORDS = {"vengayam", "thakkali", "onion", "tomato", "garlic", "ginger", "mushroom", "spinach", "parsley", "avocado"}
SEMI_SOLID_GRAM_KEYWORDS = {"hummus", "yogurt", "greek yogurt", "paneer"}


def quantity_piece_for_item(item: str, rng: random.Random) -> tuple[str | None, str | None]:
    if rng.random() < 0.4:
        return None, None
    item_l = item.lower()
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
        return str(rng.choice([1, 2, 3, 4, 5, 6])), rng.choice([None, "kg", "g", "ml", "L", "pack"])
    return str(rng.choice([1, 2, 3, 4])), rng.choice([None, "pack"])


# ---------------------------------------------------------------------------
# Date phrase pickers (anchor-aware)
#
# `pick_write_date_phrase` defaults to query-safe English keys + a leading
# "no phrase" option (~50% of writes have no explicit date). Pass
# `include_tanglish_dates=True` for todo-write Pattern B usage; that path is
# the only place Tanglish dates appear in writes.
# ---------------------------------------------------------------------------

WRITE_CANONICAL_SINGLE_KEYS = [
    "today", "yesterday", "tomorrow", "two days ago", "three days ago",
    "this morning", "this afternoon", "this evening", "tonight", "last night",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "last sunday", "last monday", "last tuesday", "last thursday", "last friday",
    "next monday", "next friday", "next saturday", "coming monday",
    "weekend", "this weekend", "month start", "month end",
]


# 2026-05-09: absolute date format pool. Re-weighted 2026-05-09 (later) per
# user's actual typing pattern: dominant form is `<day> <month-abbrev>`
# (`15 jan`, `1 mar`, `25 dec`) with no leading zero on day. Month spelled
# with mixed length (3-letter `jan`, 4-letter `july`/`sept`, full
# `January`). Year rare. Numeric forms (`15-02-2026`, `15/2`) ~10%.
#
# User's verbatim spec: "1,2,3-9,10-31 followed by space jan,feb,mar,apr,
# may,jun,july,sept,oct,nov,dev. it may interchange to month folled by
# date. rarely year will come into picture but it might. maybe 10 percent
# i will use month in 01-12."
_MONTH_ABBREVS_USER = [
    # User's typed list. Three-letter for most, four-letter for july/sept,
    # full name occasionally.
    ("jan", "January"),
    ("feb", "February"),
    ("mar", "March"),
    ("apr", "April"),
    ("may", "May"),
    ("jun", "June"),
    ("july", "July"),     # 4-letter abbrev per user
    ("aug", "August"),
    ("sept", "September"), # 4-letter abbrev per user
    ("oct", "October"),
    ("nov", "November"),
    ("dec", "December"),
]


def _ordinal_suffix(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _format_month_name_date(d, rng: random.Random) -> str:
    """User's dominant date form: `<day> <month>` or `<month> <day>`.
    No leading zero. Mix abbrev / full / lowercase / capitalized.
    """
    abbrev, full = _MONTH_ABBREVS_USER[d.month - 1]
    # Choose abbrev vs full (~80% abbrev, ~20% full).
    name = abbrev if rng.random() < 0.80 else full
    # Choose case (~70% lowercase, ~30% capitalized — user types fast,
    # often skips capitalisation).
    if name == abbrev and rng.random() < 0.70:
        name = name  # lowercase
    elif name == full and rng.random() < 0.50:
        name = name.lower()
    else:
        name = name.capitalize()
    # Choose order: ~70% `<day> <month>`, ~30% `<month> <day>`
    if rng.random() < 0.70:
        return f"{d.day} {name}"
    else:
        return f"{name} {d.day}"


def _format_numeric_date(d, rng: random.Random) -> str:
    """Numeric forms — used ~15% of the time per user (`maybe 10 percent
    i will use month in 01-12`). Year present only on ~30% of these.
    """
    sep = rng.choice(["-", "/", "."])
    include_year = rng.random() < 0.30
    if include_year:
        # Year format: full or 2-digit (~50/50).
        if rng.random() < 0.50:
            year = str(d.year)
        else:
            year = f"{d.year % 100:02d}"
        # Order: dd-mm-yyyy (Indian) ~70%, mm-dd-yyyy (US-ish) ~30%
        if rng.random() < 0.70:
            return f"{d.day}{sep}{d.month}{sep}{year}"
        else:
            return f"{d.month}{sep}{d.day}{sep}{year}"
    else:
        # Short form: dd-mm or mm-dd
        if rng.random() < 0.70:
            return f"{d.day}{sep}{d.month}"
        else:
            return f"{d.month}{sep}{d.day}"


def pick_numeric_date_phrase(anchor: str, rng: random.Random) -> tuple[str, str]:
    """Pick a random date within +-60 days of the anchor and format it.
    Returns (phrase, ISO date string).

    Distribution per user's stated typing pattern:
      85% — `<day> <month>` or `<month> <day>` (dominant form)
      15% — numeric (`15-02-2026`, `15/2`, etc.)
    """
    anchor_date = _parse_iso(anchor)
    offset = rng.randint(-60, 60)
    target = anchor_date + timedelta(days=offset)
    if rng.random() < 0.85:
        phrase = _format_month_name_date(target, rng)
    else:
        phrase = _format_numeric_date(target, rng)
    return phrase, _iso(target)


# 2026-05-09: Festival/event-relative date pool (gap #3). Indian users
# anchor a lot of buy/todo decisions to festivals ("buy: kili pachai saree
# before Pongal", "todo: amma ku call pannanum after Diwali"). The dataset
# had zero coverage of these. Festival dates are 2026-locked since the
# generator's anchors all sit in 2026 (`ANCHORS = [2026-01-15, 2026-03-15,
# 2026-05-15, 2026-08-15, 2026-11-15]`).
_FESTIVAL_DATES_2026: dict[str, str] = {
    "Pongal":         "2026-01-14",
    "Republic Day":   "2026-01-26",
    "Holi":           "2026-03-04",
    "Tamil New Year": "2026-04-14",
    "Vishu":          "2026-04-14",
    "Easter":         "2026-04-05",
    "Akshaya Tritiya":"2026-04-19",
    "Ramzan":         "2026-03-21",
    "Eid":            "2026-03-21",
    "Bakrid":         "2026-05-27",
    "Aadi":           "2026-07-17",   # Aadi month start
    "Independence Day":"2026-08-15",
    "Onam":           "2026-08-26",
    "Vinayagar Chaturthi":"2026-09-15",
    "Ganesh Chaturthi":"2026-09-15",
    "Navratri":       "2026-10-12",
    "Dussehra":       "2026-10-20",
    "Vijayadashami":  "2026-10-20",
    "Karthigai":      "2026-12-04",
    "Karthigai Deepam":"2026-12-04",
    "Diwali":         "2026-11-08",
    "Deepavali":      "2026-11-08",
    "Christmas":      "2026-12-25",
    "New Year":       "2026-12-31",
}

_EVENT_DATE_TEMPLATES = [
    # Personal events (date computed at row-render time as +/-N from anchor).
    "before exam",       # exam in 7-21 days
    "after exam",        # exam was 1-14 days ago
    "before wedding",
    "after wedding",
    "before birthday",
    "after birthday",
    "before paati function",   # grandmother's function
    "after paati function",
    "before house warming",
    "after house warming",
    "before bday",
    "after bday",
    "before puja",
    "after puja",
]


def pick_festival_date_phrase(anchor: str, rng: random.Random) -> tuple[str, str] | None:
    """Pick a festival/event-relative phrase (`before Pongal`, `after Diwali`,
    `before exam`) and resolve to an ISO date.  Returns None if no festival
    or event resolves cleanly for this anchor (e.g. the festival has already
    passed and there's no following one).

    Returns (phrase, resolved date YYYY-MM-DD).
    """
    anchor_date = _parse_iso(anchor)
    use_festival = rng.random() < 0.65
    if use_festival:
        # Pick a festival within +/-90 days of anchor for natural-feeling phrasing.
        candidates = []
        for name, iso_date in _FESTIVAL_DATES_2026.items():
            fd = _parse_iso(iso_date)
            delta_days = (fd - anchor_date).days
            if -90 <= delta_days <= 90:
                candidates.append((name, fd, delta_days))
        if not candidates:
            return None
        name, fd, delta_days = rng.choice(candidates)
        # before/after based on whether festival is in past or future.
        # If festival is past: phrase = "after {festival}". If future: "before {festival}".
        # Resolved date is a few days before/after the festival.
        if delta_days > 0:
            # Future festival → "before X" → resolves to a date 1-7 days before
            phrase = f"before {name}"
            resolved = fd - timedelta(days=rng.randint(1, 7))
        else:
            # Past festival → "after X" → resolves to a date 1-7 days after
            phrase = f"after {name}"
            resolved = fd + timedelta(days=rng.randint(1, 7))
        return phrase, _iso(resolved)
    else:
        # Personal event: pick a random offset from anchor (event date itself
        # is not stored; we just resolve the input phrase to a sensible date).
        phrase = rng.choice(_EVENT_DATE_TEMPLATES)
        if phrase.startswith("before "):
            # Event is N days from anchor; "before" means a few days earlier.
            event_offset = rng.randint(7, 21)
            resolved = anchor_date + timedelta(days=event_offset - rng.randint(1, 5))
        else:
            # "after" event — event was N days ago.
            event_offset = rng.randint(1, 14)
            resolved = anchor_date - timedelta(days=event_offset - rng.randint(0, 3))
        return phrase, _iso(resolved)


def pick_write_date_phrase(
    anchor: str,
    rng: random.Random,
    include_none: bool = True,
    include_tanglish_dates: bool = False,
) -> tuple[str | None, str]:
    """Return (phrase | None, resolved YYYY-MM-DD).

    None phrase means "no explicit date in input" -> resolve to anchor.
    """
    opts = options_for(anchor)
    if include_none and rng.random() < 0.5:
        return None, opts["single"]["today"]
    # 2026-05-09 (later): 18% of dated writes use an absolute date form. The
    # underlying pick_numeric_date_phrase was re-weighted to match user's
    # actual typing pattern: 85% `<day> <month>` (`15 jan`, `1 mar`,
    # `25 dec`, `Mar 15`) and 15% numeric (`15-02-2026`, `15/2`, `15.2`).
    # Bumped from 12% → 18% so each format gets enough exposure (~150
    # examples per format at 5k rows/lane).
    if rng.random() < 0.18:
        return pick_numeric_date_phrase(anchor, rng)
    # 2026-05-09: 8% of dated writes use a festival/event-relative phrase
    # (`before Pongal`, `after Diwali`, `before exam`). Indian context
    # heavy — these patterns were 0% covered before this branch.
    if rng.random() < 0.08:
        festival = pick_festival_date_phrase(anchor, rng)
        if festival is not None:
            return festival
        # Fall through if no festival resolved cleanly for this anchor.
    pool: list[str] = []
    canonical_present = [k for k in WRITE_CANONICAL_SINGLE_KEYS if k in opts["single"]]
    pool.extend(canonical_present)
    # 30% of write date phrases pull from the wider random pool (named-relative
    # only; absolute "may 9" style is too noisy for writes and is excluded).
    if rng.random() < 0.30:
        wide = [k for k in opts["single"].keys()
                if k not in TANGLISH_SINGLE_DATE_KEYS
                and not _is_absolute_date_key(k)]
        pool = wide if wide else pool
    if include_tanglish_dates and rng.random() < 0.5:
        pool = list(opts["todo_write_single"].keys())
    key = rng.choice(pool)
    if include_tanglish_dates and key in opts["todo_write_single"]:
        return key, opts["todo_write_single"][key]
    return key, opts["single"][key]


def _is_absolute_date_key(key: str) -> bool:
    """Heuristic: absolute calendar phrasings like 'on may 9', 'may 12',
    'on 9 may', '9 may', 'from april 1 to april 15'."""
    for m in _MONTH_NAMES:
        if key == m or key == f"{m} month":
            return False
        if key.startswith(f"first half of {m}") or key.startswith(f"second half of {m}"):
            return False
        if key.endswith(f"{m} first week") or key.endswith(f"{m} second week") or key.endswith(f"{m} third week") or key.endswith(f"{m} fourth week"):
            return False
        if key.startswith(f"{m} ") or key.startswith(f"on {m} "):
            return True
        if key.endswith(f" {m}") or key.startswith("on ") and m in key:
            return True
        if key.startswith(f"from {m} "):
            return True
    return False


# ---------------------------------------------------------------------------
# Reject pools (per docs/model-training.md Section 6)
# ---------------------------------------------------------------------------

# Buy "incomplete" lane: time / quantity / pronoun fragments only
BUY_INCOMPLETE_FRAGMENTS = [
    "tomorrow", "later this week", "next week", "today", "tonight", "this evening",
    "2kg", "500 ml", "1 L", "100g", "one more", "another one", "few more",
    "some", "couple", "this much", "that one", "these",
    "naliku", "innaiku", "nethu",  # Tanglish time-only fragments are still rejected
]

# Buy "invalid_lane": service / admin / appointment actions (subset of INDIA_TODOS)
_BUY_INVALID_LANE_PREFIXES = ("call ", "renew ", "submit ", "book ", "schedule ", "pay ", "send ", "scan ", "check ")


def buy_invalid_lane_sample(rng: random.Random) -> str:
    pool = [t for t in INDIA_TODOS + GLOBAL_TODOS if any(t.startswith(p) for p in _BUY_INVALID_LANE_PREFIXES)]
    if not pool:
        pool = INDIA_TODOS
    return rng.choice(pool)


# Todo "incomplete": time / qualifier-only fragments
TODO_INCOMPLETE_FRAGMENTS = [
    "tomorrow", "today", "later", "soon", "tonight", "monday", "friday", "weekend",
    "4pm", "6:30 pm", "11am", "evening", "morning", "this week", "next week",
    "urgent", "important", "asap", "high priority", "follow up", "remember",
]

# Weight invalid-lane: waist / non-kg / measurement / value-less name
WEIGHT_INVALID_LANE_FRAGMENTS = [
    "waist 34", "chest 38", "hip 36",
    "Marta 159 lb", "Riya 180 lb", "Hanna 170 lb",
    "kg 72", "weight 80",  # no person association
    "before breakfast", "after walk", "empty stomach",  # context note only
]


def weight_invalid_lane_sample(mode: str, rng: random.Random) -> str:
    static = list(WEIGHT_INVALID_LANE_FRAGMENTS)
    # Add a name-without-value rotation
    name = pick_name(mode, rng)
    static.extend([name, f"{name} kg", f"{name} weight"])
    return rng.choice(static)


def expense_desc_only_sample(mode: str, rng: random.Random) -> str:
    catalog = INDIA_EXPENSE if mode == "india" else GLOBAL_EXPENSE
    group = rng.choice(list(catalog.keys()))
    return rng.choice(catalog[group])


def expense_amount_only_sample(rng: random.Random) -> str:
    txt, _ = amount_text_and_value(rng, large_ok=True, foreign_ok=False)
    return txt


def expense_invalid_lane_sample(mode: str, rng: random.Random) -> str:
    pool = INDIA_TODOS if mode == "india" else GLOBAL_TODOS
    return rng.choice(pool)


# ---------------------------------------------------------------------------
# parse_write surface templates
# ---------------------------------------------------------------------------

EXPENSE_WRITE_PATTERNS = [
    "{desc} {amt}", "{amt} {desc}",
    "{desc}-{amt}", "{amt}-{desc}",
    "{desc}:{amt}", "{amt}:{desc}",
    "{desc} for {amt}", "{amt} on {desc}",
]
EXPENSE_NATURAL_PATTERNS = [
    "paid {amt} for {desc} at local market",
    "spent {amt} on {desc}",
    "bought {desc} for {amt}",
    "got {desc} for {amt} from neighborhood store",
    "purchased {desc} worth {amt}",
]
EXPENSE_TANGLISH_A_PATTERNS = [
    "{desc} ku {amt}",
    "{desc} ku {amt} pochu",
    "{desc} {amt} kaasu",
    "{desc} vaanginen {amt}",
    "{amt} ku {desc} vaanginen",
]

BUY_PREFIX_PATTERNS = [
    "need to get {first} and {second}",
    "pick up {first} and {second}",
    "get {first} plus {second}",
    "buy {first} along with {second}",
    "grab {first} and {second}",
]
BUY_TRIPLE_PATTERNS = [
    "pick up {first}, {second} and {third}",
    "need {first}, {second}, and {third}",
    "buy {first}, {second}, {third}",
    "grab {first}, {second}, {third}",
]
# v2 review fix: Pattern B/C entries dropped (`vaanganum`, `vangikanum`,
# `kooda...yum`). Per docs/model-training.md §2, buy write Pattern B/C share is 0%.
# Pattern A in buy writes still flows through item names (Tamil grocery
# words like `vengayam`, `kothamalli`, `murukku` come straight from
# INDIA_BUY without verb wrappers).

TODO_TIME_HINT_PATTERNS = [
    "call bank at 4pm",
    "doctor appointment tomorrow 6:30 pm",
    "submit form by 11am",
    "call school at 10am",
    "pay fee before 5pm",
]

# Pattern B for todo-write (the only place Pattern B is allowed in v2).
# Surface formula: <english noun phrase> + <tamil postposition / dative> +
#                  <tamil verb of obligation>, optional Tanglish time prefix.
TODO_PATTERN_B_VERBS = [
    "pannanum", "kattanum", "podanum", "vaanganum", "kudukkanum",
    "edukanum", "anupanum", "settle pannanum", "book pannanum",
    "renew pannanum", "scan pannanum", "submit pannanum", "check pannanum",
    "follow up pannanum", "complete pannanum",
]
TODO_PATTERN_B_DATIVE_PREFIXES = [
    "amma ku", "appa ku", "thambi ku", "anna ku", "akka ku",
    "friend kitta", "neighbour kitta", "office la", "school la",
    "bank ku", "shop la", "doctor kitta", "tailor kitta",
]
TODO_PATTERN_B_OBJECTS = [
    "medicine", "EB bill", "rent receipt", "bill", "form", "document",
    "passport xerox", "PAN copy", "Aadhaar copy", "school fees", "fees",
    "milk account", "tailor balance", "FASTag", "metro card", "gas booking",
    "RO service", "bike service", "scooter insurance", "wifi complaint",
    "tickets", "report", "screenshot", "courier",
]


def render_todo_pattern_b(anchor: str, rng: random.Random) -> tuple[str, str]:
    """Compose a Pattern B todo-write phrase.

    Returns (input_text, resolved_date). The phrase may include a Tanglish
    time prefix (`naalaiku`, `innaiku`) per docs/model-training.md Section 2.
    """
    obj = rng.choice(TODO_PATTERN_B_OBJECTS)
    verb = rng.choice(TODO_PATTERN_B_VERBS)
    use_dative = rng.random() < 0.55
    use_time_prefix = rng.random() < 0.45
    parts: list[str] = []
    todo_write_single = options_for(anchor)["todo_write_single"]
    todo_write_range = options_for(anchor)["todo_write_range"]
    if use_time_prefix:
        time_key = rng.choice(list(todo_write_single.keys()))
        parts.append(time_key)
        date_value = todo_write_single[time_key]
    else:
        date_value = options_for(anchor)["single"]["today"]
    if use_dative:
        parts.append(rng.choice(TODO_PATTERN_B_DATIVE_PREFIXES))
    parts.append(obj)
    parts.append(verb)
    return " ".join(parts), date_value


# 2026-05-09: person-in-todo-text pool. Dogfood logs (#71/#72/#73) showed
# that `todo: prabu son paaka ponum tomorrow` style inputs caused the model
# to hallucinate a `person_text` field that doesn't exist on todo, leaking
# from ledger/weight schema. Train rows where a person name is embedded
# INSIDE the text field (whole phrase preserved), so the model learns todo
# has no separate person slot.
TODO_PERSON_RELATIONS = [
    "son", "daughter", "wife", "husband", "amma", "appa", "anna",
    "akka", "thambi", "thangachi", "neighbour", "friend", "uncle",
    "aunty", "manager", "boss", "tailor", "boy",
]
TODO_PERSON_VERB_PHRASES = [
    "paaka ponum",          # go to see
    "ku call pannanum",     # call them
    "kitta sollanum",       # tell them
    "kooda meeting potuko", # have a meeting with
    "kitta kekanum",        # ask them
    "ku message anuppanum", # send them a message
    "kitta confirm pannanum",
    "ku reply panna marakaadhe",  # don't forget to reply
    "kooda dinner ponum",
    "ku payment kudukkanum",      # pay them
    "kitta documents kudukkanum",
    "kooda call setup pannanum",
    "kitta follow up pannanum",
]


# 2026-05-09: English day-of-week phrases for todo bodies. Currently the
# todo_write_single dict only carries Tanglish singles (`naalaiku`,
# `innaiku`). User's failing inputs (#71/#72/#73) used English `tomorrow`
# and `this weekend`, which were rare in person-in-text rows. Map English
# phrase -> resolved date via the existing single/range options.
def _english_day_phrase_with_date(anchor: str, rng: random.Random) -> tuple[str, str] | None:
    """Pick an English day-of-week phrase and resolve it against the anchor.
    Returns (phrase, date_value), or None if no English options apply for
    this anchor.
    """
    opts = options_for(anchor)
    single = opts["single"]
    candidates: list[tuple[str, str]] = []
    # Common single-day English phrases.
    if "tomorrow" in single:
        candidates.append(("tomorrow", single["tomorrow"]))
    if "yesterday" in single:
        candidates.append(("yesterday", single["yesterday"]))
    # `weekend` — use upcoming Saturday from the range options if present.
    rng_opts = opts["range"]
    if "weekend" in rng_opts:
        sat, _ = rng_opts["weekend"]
        candidates.append(("this weekend", sat))
        candidates.append(("weekend", sat))
    # Day-of-week phrases via canonical aliases.
    for key, label in (
        ("next monday", "next monday"),
        ("next tuesday", "next tuesday"),
        ("next friday", "next friday"),
        ("next sunday", "next sunday"),
        ("this friday", "this friday"),
        ("this sunday", "this sunday"),
    ):
        if key in single:
            candidates.append((label, single[key]))
        elif key in rng_opts:
            ds, _ = rng_opts[key]
            candidates.append((label, ds))
    if not candidates:
        return None
    return rng.choice(candidates)


def render_todo_pattern_b_with_person(
    anchor: str, mode: str, rng: random.Random
) -> tuple[str, str]:
    """Pattern B variant where a real person name is embedded inside the
    text field.  The whole phrase stays as the record's text — the model
    must NOT split out a person field (todo schema has no person_text).
    """
    name = pick_name(mode, rng)
    use_relation = rng.random() < 0.4
    use_time_prefix = rng.random() < 0.55
    # 2026-05-09: 50/50 split between Tanglish time prefix and English
    # day-of-week phrase. User typed `tomorrow prabu son paaka ponum` (#71)
    # which was 0% covered before this branch.
    use_english_day = use_time_prefix and rng.random() < 0.50
    todo_write_single = options_for(anchor)["todo_write_single"]
    parts: list[str] = []
    date_value = options_for(anchor)["single"]["today"]
    time_phrase: str | None = None
    if use_time_prefix and use_english_day:
        eng = _english_day_phrase_with_date(anchor, rng)
        if eng is not None:
            time_phrase, date_value = eng
    if use_time_prefix and time_phrase is None:
        # Fall back to Tanglish time keys.
        time_key = rng.choice(list(todo_write_single.keys()))
        time_phrase = time_key
        date_value = todo_write_single[time_key]
    # 2026-05-09: ~30% of rows put the time phrase at the FRONT of the body
    # (`tomorrow prabu son paaka ponum`); the rest use suffix
    # (`prabu son paaka ponum tomorrow`). Both are user-natural orderings.
    name_token = name.lower() if rng.random() < 0.6 else name
    body_core: list[str] = [name_token]
    if use_relation:
        body_core.append(rng.choice(TODO_PERSON_RELATIONS))
    body_core.append(rng.choice(TODO_PERSON_VERB_PHRASES))
    if time_phrase is None:
        return " ".join(body_core), date_value
    if rng.random() < 0.30:
        # Date at front.
        return time_phrase + " " + " ".join(body_core), date_value
    else:
        # Date as suffix.
        return " ".join(body_core) + " " + time_phrase, date_value


# ---------------------------------------------------------------------------
# parse_write makers
# ---------------------------------------------------------------------------

def make_expense_write(anchor: str, mode: str, rng: random.Random) -> dict:
    if rng.random() < 0.10:
        bad = rng.choice(["desc_only", "amount_only", "invalid_lane"])
        if bad == "desc_only":
            text = f"expense: {expense_desc_only_sample(mode, rng)}"
            reason = "incomplete_input"
        elif bad == "amount_only":
            text = f"expense: {expense_amount_only_sample(rng)}"
            reason = "incomplete_input"
        else:
            text = f"expense: {expense_invalid_lane_sample(mode, rng)}"
            reason = "invalid_lane_content"
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "expense", "disposition": "reject", "reason_code": reason, "records": []},
        }

    # 2026-05-09: long-list branch. ~12% of accept rows train 4-10 items.
    # Real-user expense dumps (#75 logs) had 6 items in one input
    # (`kothamalli 10rs, manjal 50rs, rent 25k, ...`); the dataset previously
    # capped at 3 records per row.
    if rng.random() < 0.12:
        n = rng.choices(
            [4, 5, 6, 7, 8, 9, 10],
            [0.30, 0.25, 0.18, 0.12, 0.08, 0.05, 0.02],
        )[0]
    else:
        n = rng.choices([1, 2, 3], [0.45, 0.4, 0.15])[0]
    date_phrase, date_value = pick_write_date_phrase(anchor, rng)
    pattern_a = use_pattern_a("expense_write", mode, rng)
    natural_sentence = n == 1 and rng.random() < 0.25

    records = []
    chunks: list[str] = []
    for _ in range(n):
        desc, group = pick_expense_item(mode, rng)
        txt, value = expense_amount_text_and_value(group, desc, mode, rng)
        records.append({"description": desc, "amount": value, "date": date_value, "group": group})
        if natural_sentence and pattern_a:
            chunks.append(rng.choice(EXPENSE_TANGLISH_A_PATTERNS).format(desc=desc, amt=txt))
        elif natural_sentence:
            chunks.append(rng.choice(EXPENSE_NATURAL_PATTERNS).format(desc=desc, amt=txt))
        elif pattern_a:
            chunks.append(rng.choice(EXPENSE_TANGLISH_A_PATTERNS + EXPENSE_WRITE_PATTERNS).format(desc=desc, amt=txt))
        else:
            chunks.append(rng.choice(EXPENSE_WRITE_PATTERNS).format(desc=desc, amt=txt))
    input_text = "expense: " + ", ".join(chunks)
    if date_phrase:
        input_text += f" {date_phrase}"
    # Trailing-comma augmentation (8% of multi-item rows). Same rationale as
    # buy/todo: real users habitually leave a dangling comma when typing.
    if n >= 2 and rng.random() < 0.08:
        input_text += rng.choice([",", ", "])
    input_text = apply_input_noise(input_text, rng, has_multi_items=(n >= 2))
    return {
        "anchor_date": anchor,
        "input": input_text,
        "output": {"task": "parse_write", "lane": "expense", "disposition": "accept", "reason_code": None, "records": records},
    }


# 2026-05-09: Input-side noise augmentation (gaps #7 + #8). Real users
# don't type clean canonical input — they double-space, capitalise random
# words, omit spaces between item and quantity, and mix separators in the
# same row. Records output stays untouched. Apply at the very end of each
# write maker, AFTER all the structured rendering is done.
_MIXED_SEPARATOR_POOL = [", ", "; ", " / ", " + ", " and ", " & "]


def apply_input_noise(input_text: str, rng: random.Random, has_multi_items: bool | None = None) -> str:
    """Random whitespace + casing + separator-mix noise on the input only.
    Each kind fires independently with low probability so most rows stay
    clean and only ~10-15% have any kind of noise.
    """
    out = input_text
    if has_multi_items is None:
        has_multi_items = ("," in out) or ("\n" in out) or (";" in out)
    # Whitespace edge case: occasional double space (typing-fumble).
    if rng.random() < 0.04:
        # Replace one random space with two spaces.
        idx = out.find(" ")
        if idx >= 0:
            out = out[:idx] + "  " + out[idx+1:]
    # Leading/trailing whitespace.
    if rng.random() < 0.03:
        out = rng.choice(["  " + out, out + "  ", " " + out + " "])
    # Casing fumble: random word ALL CAPS (user emphasising), or first letter
    # of one word capitalised mid-sentence.
    if rng.random() < 0.04:
        words = out.split(" ")
        if len(words) > 2:
            i = rng.randint(1, len(words) - 1)
            if rng.random() < 0.5:
                words[i] = words[i].upper()
            else:
                words[i] = words[i].capitalize()
            out = " ".join(words)
    # Missing space between number and unit (`paasi parupu1kg`).
    # Only safe when the word boundary is between a letter and a digit.
    if rng.random() < 0.05:
        # Find " {digit}" and remove the space.
        import re as _re
        out = _re.sub(r"(\w) (\d)", r"\1\2", out, count=1)
    # Mixed separators: replace one comma with a different separator.
    if has_multi_items and rng.random() < 0.05:
        # Find first comma and replace with a different separator (not the same
        # comma; if the row already used commas the rest stay).
        idx = out.find(",")
        if idx > 0:
            sep = rng.choice(_MIXED_SEPARATOR_POOL)
            # Strip whitespace right after the comma since the new separator brings its own.
            tail_start = idx + 1
            while tail_start < len(out) and out[tail_start] == " ":
                tail_start += 1
            out = out[:idx] + sep + out[tail_start:]
    return out


# 2026-05-09: Tanglish verb pool for buy lane. User confirmed they exclusively
# write buy lists in Tanglish (`Manjal, kasthuri methi, ...`) and may type
# verb-suffixed forms like `manjal vaanganum`. The dataset previously had
# zero verb-Tanglish coverage in buy (the v2 cleanup removed _TANGLISH_VEHICLE
# / _TANGLISH_DINING which were the only verb-bearing buy-adjacent entries).
# These verbs are written-Tanglish only — no spoken-only `kaatu` / Pattern C.
BUY_TANGLISH_TRAILING_VERBS = [
    "vanganum",         # need to buy
    "vaanganum",        # alt spelling
    "vaaaanganum",      # elongated colloquial
    "kekanum",          # need to ask (for stock)
    "book pannanum",    # need to book
    "order pannanum",   # need to order
    "vaanga vendiyathu", # need to be bought
    "vendi irukku",     # is needed
    "edukanum",         # need to take/get
    "list la add pannanum",  # add to the list
]
# Per-item verb suffixes (shorter, used after each item).
BUY_TANGLISH_PER_ITEM_VERBS = [
    "vanganum", "vaanganum", "kekanum", "vendi irukku",
]
# Tanglish list connectors (instead of plain comma).
BUY_TANGLISH_CONNECTORS = [
    ", ", ", ", ", ", ", ", ", ",     # comma still dominates (matches user logs)
    " kooda ",       # along with
    " appuram ",     # then
    " mattum ",      # also
]


def make_buy_write(anchor: str, mode: str, rng: random.Random) -> dict:
    roll = rng.random()
    if roll < 0.06:
        text = f"buy: {rng.choice(BUY_INCOMPLETE_FRAGMENTS)}"
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "buy", "disposition": "reject", "reason_code": "incomplete_input", "records": []},
        }
    if roll < 0.10:
        text = f"buy: {buy_invalid_lane_sample(rng)}"
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "buy", "disposition": "reject", "reason_code": "invalid_lane_content", "records": []},
        }

    # 2026-05-09: long-list branch. ~12% of accept rows now train 4-12 items so
    # the model handles real-world buy lists (user dogfood logs showed 6-12 item
    # lists with all rows past N=3 either dropped or producing malformed JSON).
    # Distribution biased to 4-7 items (most common) with a long tail to 12.
    if rng.random() < 0.12:
        n = rng.choices(
            [4, 5, 6, 7, 8, 9, 10, 11, 12],
            [0.22, 0.20, 0.16, 0.12, 0.10, 0.08, 0.06, 0.04, 0.02],
        )[0]
    else:
        n = rng.choices([1, 2, 3], [0.4, 0.4, 0.2])[0]
    date_phrase, date_value = pick_write_date_phrase(anchor, rng)
    records = []
    items: list[str] = []
    chosen_items: list[str] = []
    for _ in range(n):
        # v2 review fix: when picking N items, retry if the new pick textually
        # overlaps an already-chosen one (substring either way, case-insensitive).
        # This stops `Anil salt` from co-occurring with `salt` in the same row.
        attempt = 0
        while True:
            attempt += 1
            item = pick_buy_item(mode, rng)
            il = item.lower()
            overlap = any(il in c.lower() or c.lower() in il for c in chosen_items)
            if not overlap or attempt >= 25:
                # Cap attempts so a small remaining pool can't loop forever.
                break
        chosen_items.append(item)
        q, unit = quantity_piece_for_item(item, rng)
        records.append({"item_text": item, "quantity_text": q, "unit_text": unit, "date": date_value})
        # 2026-05-09: user-style unit aliases for the displayed input (records
        # keep canonical units). Real users type `500gms` / `1ltr` / `2 packet`
        # — dogfood logs (#48: `paasi parupu 500gms`, `milk 1ltr`) showed
        # these spellings. Bias toward them in india-mode.
        display_unit = unit
        if mode == "india" and unit and rng.random() < 0.35:
            display_unit = {
                "g": rng.choice(["g", "gms", "gms"]),     # 2/3 alias
                "kg": rng.choice(["kg", "kg", "kgs"]),    # occasional `kgs`
                "ml": "ml",                                # `ml` is universal
                "L": rng.choice(["L", "ltr", "litre"]),
                "pack": rng.choice(["pack", "packet"]),
            }.get(unit, unit)
        # 2026-05-09: fraction/range display variants (gap #9). 8% of buy
        # items with a quantity show the qty as `half kg` / `1/2 kg` /
        # `2-3 kg` / `~2 kg` / `about 2 kg`. Records keep canonical numeric
        # qty + unit. Common patterns for groceries.
        display_qty = q
        use_fraction_range = q and unit in {"kg", "g", "L", "ml"} and rng.random() < 0.08
        if use_fraction_range:
            shape = rng.choices(
                ["half", "fraction", "range_dash", "range_to", "approx", "about"],
                [0.20, 0.15, 0.20, 0.10, 0.20, 0.15],
            )[0]
            try:
                qnum = float(q)
            except (TypeError, ValueError):
                qnum = None
            if shape == "half" and unit == "kg" and qnum and qnum >= 1:
                display_qty = "half"
            elif shape == "half" and unit == "g" and qnum and qnum >= 250:
                display_qty = "half"
            elif shape == "fraction":
                display_qty = rng.choice(["1/2", "3/4", "1/4"])
            elif shape == "range_dash" and qnum:
                lo = max(1, int(qnum) - 1)
                hi = max(lo + 1, int(qnum) + 1)
                display_qty = f"{lo}-{hi}"
            elif shape == "range_to" and qnum:
                lo = max(1, int(qnum) - 1)
                hi = max(lo + 1, int(qnum) + 1)
                display_qty = f"{lo} to {hi}"
            elif shape == "approx":
                display_qty = f"~{q}"
            elif shape == "about":
                display_qty = f"about {q}"
        if display_qty and display_unit:
            # `half kg`, `1/2 kg`, `2-3 kg` always need a space; the no-space
            # joining is only safe for plain-numeric quantities.
            qty_is_numeric = bool(display_qty) and display_qty[0].isdigit() and not any(
                c in display_qty for c in " -/~"
            )
            if qty_is_numeric and display_unit in {"kg", "g", "ml", "L", "gms", "kgs", "ltr"}:
                items.append(f"{item} {display_qty}{display_unit}")
            else:
                items.append(f"{item} {display_qty} {display_unit}")
        elif display_qty:
            items.append(f"{item} {display_qty}")
        else:
            items.append(item)
    # 2026-05-09: Tanglish-input branch. ~20% of india-mode rows render the
    # input with Tanglish verb suffixes (the user types these by default).
    # Records output stays in canonical form — the model must learn to
    # extract the same items regardless of whether the input is a bare list,
    # English verb phrase, or Tanglish verb phrase.
    use_tanglish = mode == "india" and rng.random() < 0.20
    if use_tanglish:
        # Pick one of three Tanglish input shapes:
        #   1. trailing-verb:   `manjal, kothamalli vaanganum`
        #   2. per-item-verb:   `manjal vanganum, kothamalli vanganum`
        #   3. bare list (no verb): `Manjal, kasthuri methi, kasthuri manjal`
        #      — matches user's most common pattern from dogfood logs
        shape = rng.choices(["trailing", "per_item", "bare"], [0.35, 0.20, 0.45])[0]
        if shape == "trailing":
            sep = rng.choice(BUY_TANGLISH_CONNECTORS)
            body = sep.join(items) + " " + rng.choice(BUY_TANGLISH_TRAILING_VERBS)
        elif shape == "per_item":
            verb = rng.choice(BUY_TANGLISH_PER_ITEM_VERBS)
            body = ", ".join(f"{it} {verb}" for it in items)
        else:
            sep = rng.choice(BUY_TANGLISH_CONNECTORS)
            body = sep.join(items)
    else:
        # Style: 'natural' patterns only fit n=2 or n=3 (template slots). For
        # n>=4 use comma or multiline forms — these are what users actually
        # type.
        style = rng.choice(["list", "natural", "multiline"])
        if style == "natural" and n == 2:
            body = rng.choice(BUY_PREFIX_PATTERNS).format(first=items[0], second=items[1])
        elif style == "natural" and n == 3:
            body = rng.choice(BUY_TRIPLE_PATTERNS).format(first=items[0], second=items[1], third=items[2])
        elif style == "multiline" and n >= 2:
            body = "\n".join(items)
        else:
            body = ", ".join(items)
    input_text = "buy: " + body
    if date_phrase:
        input_text += f" {date_phrase}"
    # 2026-05-09: trailing-comma augmentation. ~8% of multi-item buy rows now
    # have a trailing ',' or ', ' on the input. Output unchanged. The model
    # must learn that a dangling comma is end-of-list, not a phantom item.
    # Dogfood logs (#77/#78/#79) showed that real users habitually leave a
    # trailing comma when typing lists; the model had never seen this and
    # invented broken multi-record shapes in response.
    if n >= 2 and rng.random() < 0.08:
        input_text += rng.choice([",", ", "])
    input_text = apply_input_noise(input_text, rng, has_multi_items=(n >= 2))
    return {
        "anchor_date": anchor,
        "input": input_text,
        "output": {"task": "parse_write", "lane": "buy", "disposition": "accept", "reason_code": None, "records": records},
    }


def make_todo_write(anchor: str, mode: str, rng: random.Random) -> dict:
    if rng.random() < 0.10:
        text = f"todo: {rng.choice(TODO_INCOMPLETE_FRAGMENTS)}"
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "todo", "disposition": "reject", "reason_code": "incomplete_input", "records": []},
        }

    pattern_b = use_pattern_b("todo_write", mode, rng)

    if pattern_b:
        # 2026-05-09: long-list branch (~10% of pattern-B rows go to 4-8 items).
        if rng.random() < 0.10:
            n = rng.choices([4, 5, 6, 7, 8], [0.32, 0.26, 0.20, 0.14, 0.08])[0]
        else:
            n = rng.choices([1, 2], [0.65, 0.35])[0]
        date_value = options_for(anchor)["single"]["today"]
        records = []
        chunks: list[str] = []
        date_phrase = None
        for i in range(n):
            # 2026-05-09: ~25% of pattern-B chunks now embed a real person name
            # inside the text field (e.g. `prabu son paaka ponum`). Trains the
            # model that todo has no separate person slot — fixes the schema
            # leak from #71/#72/#73 dogfood logs.
            if rng.random() < 0.25:
                chunk, chunk_date = render_todo_pattern_b_with_person(anchor, mode, rng)
            else:
                chunk, chunk_date = render_todo_pattern_b(anchor, rng)
            if i == 0:
                date_value = chunk_date
            chunks.append(chunk)
            records.append({"text": chunk, "date": chunk_date})
        body = ", ".join(chunks) if rng.random() < 0.6 else "\n".join(chunks)
        input_text = "todo: " + body
        # Trailing-comma augmentation (8% of multi-item rows).
        if n >= 2 and rng.random() < 0.08:
            input_text += rng.choice([",", ", "])
        input_text = apply_input_noise(input_text, rng, has_multi_items=(n >= 2))
        return {
            "anchor_date": anchor,
            "input": input_text,
            "output": {"task": "parse_write", "lane": "todo", "disposition": "accept", "reason_code": None, "records": records},
        }

    # 2026-05-09: long-list branch (~10% of non-pattern-B rows go to 4-8 items).
    if rng.random() < 0.10:
        n = rng.choices([4, 5, 6, 7, 8], [0.32, 0.26, 0.20, 0.14, 0.08])[0]
    else:
        n = rng.choices([1, 2, 3], [0.45, 0.35, 0.2])[0]
    date_phrase, date_value = pick_write_date_phrase(anchor, rng)
    tasks = [pick_todo_text(mode, rng) for _ in range(n)]
    if rng.random() < 0.10:
        tasks[0] = rng.choice(TODO_TIME_HINT_PATTERNS)
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
    # Trailing-comma augmentation (8% of multi-item rows).
    if n >= 2 and rng.random() < 0.08:
        input_text += rng.choice([",", ", "])
    input_text = apply_input_noise(input_text, rng, has_multi_items=(n >= 2))
    return {
        "anchor_date": anchor,
        "input": input_text,
        "output": {"task": "parse_write", "lane": "todo", "disposition": "accept", "reason_code": None, "records": records},
    }


def make_weight_write(anchor: str, mode: str, rng: random.Random) -> dict:
    if rng.random() < 0.10:
        text = f"weight: {weight_invalid_lane_sample(mode, rng)}"
        # Decide reason from the chosen text
        text_l = text.lower()
        if "waist" in text_l or "chest" in text_l or "hip" in text_l or "lb" in text_l:
            reason = "invalid_lane_content"
        elif text_l.endswith(":"):
            reason = "incomplete_input"
        elif any(name_marker in text_l for name_marker in ("kg ", " kg")) and not any(c.isdigit() for c in text):
            reason = "incomplete_input"
        elif "before " in text_l or "after " in text_l or "empty stomach" in text_l:
            reason = "incomplete_input"
        else:
            reason = "incomplete_input"
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "weight", "disposition": "reject", "reason_code": reason, "records": []},
        }

    n = rng.choices([1, 2], [0.75, 0.25])[0]
    date_phrase, date_value = pick_write_date_phrase(anchor, rng)
    notes = [None, "before breakfast", "after walk", "empty stomach", "after yoga"]
    records = []
    chunks: list[str] = []
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
            chunk = f"my weight {val} {note}"
        elif person == "self" and text_person == "":
            chunk = f"{val}"
        elif include_note and note:
            chunk = f"{text_person} {val} {note}".strip()
        else:
            chunk = f"{text_person} {val}".strip()
        if not include_note and rng.random() < 0.7 and person != "self":
            chunk = f"{text_person} {val} kg"
        chunks.append(chunk)
    input_text = "weight: " + ", ".join(chunks)
    if date_phrase:
        input_text += f" {date_phrase}"
    input_text = apply_input_noise(input_text, rng, has_multi_items=(n >= 2))
    return {
        "anchor_date": anchor,
        "input": input_text,
        "output": {"task": "parse_write", "lane": "weight", "disposition": "accept", "reason_code": None, "records": records},
    }


def make_ledger_write(anchor: str, mode: str, rng: random.Random) -> dict:
    roll = rng.random()
    if roll < 0.12:
        # Reject: ambiguous direction (bare name + amount, no verb) OR incomplete
        if rng.random() < 0.6:
            person = pick_name(mode, rng)
            txt, _ = amount_text_and_value(rng, large_ok=False, foreign_ok=False)
            text = f"ledger: {person} {txt}"
            reason = "ambiguous_direction"
        else:
            text = rng.choice([
                "ledger: gave 500", "ledger: settled", "ledger: return 500",
                "ledger: received 700", "ledger: closed account", "ledger: cleared",
            ])
            reason = "incomplete_input"
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "ledger", "disposition": "reject", "reason_code": reason, "records": []},
        }

    if roll < 0.24:
        # Confirm: ambiguous direction (verb is gave/received but the actor is
        # implicit — model should ask which side).
        person = pick_name(mode, rng)
        txt, value = amount_text_and_value(rng, large_ok=True, foreign_ok=(mode == "global"))
        if rng.random() < 0.5:
            text = f"ledger: gave {person} {txt}"
            record = {"person_text": person, "action": "add_credit", "amount": value, "date": options_for(anchor)["single"]["today"], "note": None}
        else:
            text = f"ledger: received {txt} from {person}"
            record = {"person_text": person, "action": "add_debt", "amount": value, "date": options_for(anchor)["single"]["today"], "note": None}
        return {
            "anchor_date": anchor,
            "input": text,
            "output": {"task": "parse_write", "lane": "ledger", "disposition": "confirm", "reason_code": "ambiguous_direction", "records": [record]},
        }

    # Accept
    date_phrase, date_value = pick_write_date_phrase(anchor, rng)
    n = rng.choices([1, 2], [0.8, 0.2])[0]
    actions = ["add_debt", "add_credit", "repay_debt", "collect_credit", "settle"]
    records = []
    parts: list[str] = []
    for _ in range(n):
        person = pick_name(mode, rng)
        action = rng.choices(actions, [0.25, 0.25, 0.18, 0.18, 0.14])[0]
        # 2026-05-09: 25% chance to use Tanglish phrasing for ledger actions
        # (india-mode only). User asked specifically for `settle pannitten`,
        # `kasu kudutiten`, `Maddy ku amount kudutiten` style. Records output
        # stays canonical regardless of input phrasing.
        use_tanglish = mode == "india" and rng.random() < 0.25
        if action == "settle":
            amount = None
            if use_tanglish:
                part = rng.choice([
                    f"{person} ku settle pannitten",       # settled with X
                    f"{person} account close pannitten",   # closed X account
                    f"{person} kitta complete settle",     # complete settle
                    f"{person} ku full kasu kudutiten",    # paid full money
                ])
            else:
                part = rng.choice([
                    f"settled with {person}",
                    f"cleared {person}",
                    f"cleared {person} account",
                    f"closed {person} account",
                    f"settled {person}",
                    f"done with {person}",
                ])
        else:
            txt, amount = amount_text_and_value(rng, large_ok=True, foreign_ok=(mode == "global" and rng.random() < 0.15))
            if action == "add_debt":
                if use_tanglish:
                    part = rng.choice([
                        f"{person} kitta {txt} vaangiten",     # took X from person
                        f"{person} ku {txt} kudukanum",        # owe X to person
                        f"{person} ku {txt} bakki",            # X due to person
                    ])
                else:
                    part = rng.choice([
                        f"I owe {person} {txt}",
                        f"borrowed {txt} from {person}",
                        f"took {txt} from {person}",
                    ])
            elif action == "add_credit":
                if use_tanglish:
                    part = rng.choice([
                        f"{person} ku {txt} kudutiten",        # gave X to person
                        f"{person} kitta {txt} bakki",         # X is pending from person
                        f"{person} en kitta {txt} vaangina",   # they took X from me
                    ])
                else:
                    part = rng.choice([
                        f"{person} owes me {txt}",
                        f"lent {person} {txt}",
                        f"gave {person} {txt}",
                        f"{person} took {txt} from me",
                    ])
            elif action == "repay_debt":
                if use_tanglish:
                    part = rng.choice([
                        f"{person} ku {txt} thirupi kudutiten",   # gave back X to person
                        f"{person} ku full kasu kudutiten",       # paid full to person
                        f"{person} bakki kudutiten",              # paid pending to person
                    ])
                else:
                    part = rng.choice([
                        f"I paid {person} back {txt}",
                        f"repaid {person} {txt}",
                        f"paid back {person} fully",       # 'fully' user-style
                        f"settled {txt} to {person}",
                    ])
            else:  # collect_credit
                if use_tanglish:
                    part = rng.choice([
                        f"{person} en kitta {txt} thirupi kuduthar",  # they gave X back to me
                        f"{person} kitta {txt} vasooli pannita",      # collected X from them
                        f"{person} bakki kuduthar",                   # they paid pending
                    ])
                else:
                    part = rng.choice([
                        f"{person} returned {txt}",
                        f"collected {txt} from {person}",
                        f"{person} paid me back {txt}",
                        f"{person} paid back fully",       # user-style "fully"
                    ])
        # v2: ledger reason notes are dropped. note field is always null.
        records.append({"person_text": person, "action": action, "amount": amount, "date": date_value, "note": None})
        parts.append(part)
    input_text = "ledger: " + ", ".join(parts)
    if date_phrase:
        input_text += f" {date_phrase}"
    input_text = apply_input_noise(input_text, rng, has_multi_items=(n >= 2))
    return {
        "anchor_date": anchor,
        "input": input_text,
        "output": {"task": "parse_write", "lane": "ledger", "disposition": "accept", "reason_code": None, "records": records},
    }


# ---------------------------------------------------------------------------
# parse_query date-phrase routing
#
# Per docs/model-training.md Section 7.3:
#   60% canonical phrasings (today / this month / last month / ...)
#   30% random named-relative key from the pool
#   10% absolute calendar dates / ranges
#
# Tanglish keys (Pattern C) are excluded from queries entirely (Section 2).
#
# Each form expresses a *semantic* range (e.g. "this_month") via the helpers
# below. The semantic key resolves to a (start, end) pair against the row's
# anchor; the surface phrase rendered into the input text is selected per
# the 60/30/10 mix.
# ---------------------------------------------------------------------------

# Canonical surface aliases per semantic range. The first entry is the
# default canonical phrase; the rest are interchangeable canonicals (no
# Tanglish, no absolutes). All entries must resolve to the same anchor-
# relative range as the semantic key.
# v2 review fix: query-side date phrases must not include time-of-day variants
# (`this morning`, `this evening`, `tonight`, `last night`) because no lane
# supports time-of-day filtering. They remain available to write rows via
# `WRITE_CANONICAL_SINGLE_KEYS` (which is independent of these aliases),
# because `expense: tea 20 this evening` is a realistic write input.
SEMANTIC_RANGE_ALIASES: dict[str, list[str]] = {
    "today": ["today"],
    "yesterday": ["yesterday"],
    "tomorrow": ["tomorrow"],
    "this week": ["this week", "current week", "this wk"],
    "last week": ["last week", "last wk"],
    "this month": ["this month", "current month"],
    "last month": ["last month"],
    "month to date": ["month to date", "till today"],
    "this quarter": ["this quarter", "current quarter"],
    "this financial year": ["this financial year", "current financial year"],
    "year to date": ["year to date", "since january"],
    "weekend": ["weekend", "this weekend"],
    "monday to friday": ["monday to friday"],
}

# Surface keys that resolve to a calendar date but imply a time-of-day filter
# we don't support. Filtered out of the query random-pool too, so they can't
# leak in via the 30% random-key route.
TIME_OF_DAY_KEYS: set[str] = {
    "this morning", "this afternoon", "this noon", "this evening",
    "tonight", "early morning", "morn", "eve", "night",
    "last night", "last evening",
}

# Random-pool keys (the 30% bucket). These are anchor-resolvable named
# relative keys that are NOT in any canonical alias list above. Built once
# per anchor.
def _build_random_pool_keys(anchor: str) -> list[str]:
    canonical_set: set[str] = set()
    for aliases in SEMANTIC_RANGE_ALIASES.values():
        canonical_set.update(aliases)
    pool: list[str] = []
    for k in options_for(anchor)["range"].keys():
        if k in canonical_set:
            continue
        if k in TANGLISH_RANGE_KEYS:
            continue
        if k in TIME_OF_DAY_KEYS:
            continue
        if _is_absolute_date_key(k):
            continue
        # also skip the bare per-day singletons that came from the absolute
        # enumeration (those should land in the absolute bucket via
        # `_pick_absolute_phrase`).
        pool.append(k)
    return pool


_RANDOM_POOL_KEYS_CACHE: dict[str, list[str]] = {}


def _random_pool_keys(anchor: str) -> list[str]:
    cached = _RANDOM_POOL_KEYS_CACHE.get(anchor)
    if cached is not None:
        return cached
    cached = _build_random_pool_keys(anchor)
    _RANDOM_POOL_KEYS_CACHE[anchor] = cached
    return cached


def _absolute_keys_for_anchor(anchor: str) -> list[str]:
    """All explicit calendar phrasings (`on may 9`, `from may 1 to may 5`)."""
    return [k for k in options_for(anchor)["range"].keys() if _is_absolute_date_key(k)]


_ABSOLUTE_KEYS_CACHE: dict[str, list[str]] = {}


def _absolute_keys(anchor: str) -> list[str]:
    cached = _ABSOLUTE_KEYS_CACHE.get(anchor)
    if cached is not None:
        return cached
    cached = _absolute_keys_for_anchor(anchor)
    _ABSOLUTE_KEYS_CACHE[anchor] = cached
    return cached


def pick_date_input_phrase(
    anchor: str,
    semantic_key: str,
    rng: random.Random,
) -> tuple[str, tuple[str, str]]:
    """Pick a surface date phrase aligned with the form's semantic range.

    Returns (phrase, (start, end)). `phrase` is to be embedded in the input
    text; `(start, end)` is the resolved range for the output schema.

    Routing per Section 7.3:
      60%: a canonical alias (same range as semantic_key).
      30%: a random named-relative key (range may differ from semantic_key
           when the form allows override; callers that need the form's
           canonical range should use `pick_canonical_phrase`).
      10%: an absolute calendar phrasing (with the form's canonical range,
           rendered as `from <start> to <end>` or a single-day phrasing).
    """
    canonical_aliases = SEMANTIC_RANGE_ALIASES.get(semantic_key)
    if canonical_aliases is None:
        # Fallback: if the semantic key has no aliases, use it directly.
        return semantic_key, options_for(anchor)["range"][semantic_key]

    semantic_range = options_for(anchor)["range"][semantic_key]
    roll = rng.random()
    if roll < DATE_BREADTH_CANONICAL:
        return rng.choice(canonical_aliases), semantic_range
    if roll < DATE_BREADTH_CANONICAL + DATE_BREADTH_RANDOM_KEY:
        pool = _random_pool_keys(anchor)
        if pool:
            key = rng.choice(pool)
            return key, options_for(anchor)["range"][key]
        return rng.choice(canonical_aliases), semantic_range
    # 10% absolute: render the semantic range as an absolute calendar phrase.
    start, end = semantic_range
    if start == end:
        sd = _parse_iso(start)
        month_name = _MONTH_NAMES[sd.month - 1]
        phrase = rng.choice([f"on {month_name} {sd.day}", f"{month_name} {sd.day}", f"on {sd.day} {month_name}"])
        return phrase, semantic_range
    sd = _parse_iso(start)
    ed = _parse_iso(end)
    sm = _MONTH_NAMES[sd.month - 1]
    em = _MONTH_NAMES[ed.month - 1]
    phrase = f"from {sm} {sd.day} to {em} {ed.day}"
    return phrase, semantic_range


def pick_canonical_phrase(anchor: str, semantic_key: str, rng: random.Random) -> tuple[str, tuple[str, str]]:
    """Same as pick_date_input_phrase but always uses canonical alias (no
    random pool override). Useful for forms whose date range must stay tied
    to the form's semantic range (e.g. compare needs both this_month and
    last_month, override would break the schema)."""
    aliases = SEMANTIC_RANGE_ALIASES.get(semantic_key, [semantic_key])
    return rng.choice(aliases), options_for(anchor)["range"][semantic_key]


def pick_random_named_range(anchor: str, rng: random.Random) -> tuple[str, tuple[str, str]]:
    """Sample a named-relative range key uniformly from the random pool.
    Used for forms like recent_expense where the date semantics is
    deliberately broad."""
    pool = _random_pool_keys(anchor)
    if not pool:
        return pick_canonical_phrase(anchor, "this month", rng)
    key = rng.choice(pool)
    return key, options_for(anchor)["range"][key]


def pick_absolute_single_phrase(anchor: str, rng: random.Random) -> tuple[str, str]:
    """Sample an absolute single-day phrasing (`on may 9`, `may 12`).
    Returns (phrase, resolved_date). Used by note `list_absolute` and any
    form that wants a calendar-specific day."""
    keys = _absolute_keys(anchor)
    candidates = [k for k in keys if options_for(anchor)["range"][k][0] == options_for(anchor)["range"][k][1]]
    if not candidates:
        return options_for(anchor)["single"]["today"], options_for(anchor)["single"]["today"]
    key = rng.choice(candidates)
    start, _ = options_for(anchor)["range"][key]
    return key, start


# ---------------------------------------------------------------------------
# Surface-style picker (Section 4.2)
#
#   35% noun-phrase / fragment
#   30% verb-led English
#   20% question-shaped
#   15% Pattern A (Tanglish noun in English frame) -- only where the lane
#       budget allows; else this share rolls over to noun-phrase.
# ---------------------------------------------------------------------------

STYLE_WEIGHTS_BASE = {"noun": 35.0, "verb": 30.0, "question": 20.0, "tanglish_a": 15.0}


def pick_style(slot: str, mode: str, rng: random.Random) -> str:
    """Pick a surface style for one query row.

    `slot` is the parse_query slot key for Pattern A gating, e.g.
    `expense_query`, `note_query`, `weight_query`. If Pattern A is disabled
    for the slot (or mode is global), the 15% Tanglish_A budget rolls into
    noun-phrase.
    """
    a_share_pct = PATTERN_A_SHARE.get(slot, 0.0) * 100 if mode == "india" else 0.0
    if a_share_pct <= 0:
        weights = {
            "noun": STYLE_WEIGHTS_BASE["noun"] + STYLE_WEIGHTS_BASE["tanglish_a"],
            "verb": STYLE_WEIGHTS_BASE["verb"],
            "question": STYLE_WEIGHTS_BASE["question"],
        }
    else:
        # Use the slot-specific Pattern A share as the tanglish_a weight,
        # rebalancing the rest proportionally.
        non_a = 100 - a_share_pct
        scale = non_a / (STYLE_WEIGHTS_BASE["noun"] + STYLE_WEIGHTS_BASE["verb"] + STYLE_WEIGHTS_BASE["question"])
        weights = {
            "noun": STYLE_WEIGHTS_BASE["noun"] * scale,
            "verb": STYLE_WEIGHTS_BASE["verb"] * scale,
            "question": STYLE_WEIGHTS_BASE["question"] * scale,
            "tanglish_a": a_share_pct,
        }
    keys = list(weights.keys())
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def render_template(templates: dict[str, list[str]], style: str, rng: random.Random, **fmt: object) -> str:
    """Pick a template from the requested style; fall back to noun if the
    style bucket is empty."""
    options = templates.get(style)
    if not options:
        options = templates.get("noun") or templates.get("verb") or []
    if not options:
        return ""
    return rng.choice(options).format(**fmt)


def maybe_scoped(lane: str, body: str, rng: random.Random) -> str:
    """Apply the scoped-prefix wrap. Caller decides scoped/unscoped via
    `rng.random() < SCOPED_SHARE[lane]`; this helper just builds the
    `ask: <domain>: ` prefix when scoped."""
    return f"ask: {lane}: {body}"


def query_input(scoped: bool, lane: str, body: str) -> str:
    return f"ask: {lane}: {body}" if scoped else f"ask: {body}"


# ---------------------------------------------------------------------------
# §5.3 typo module
#
# Applied to ~7% of search-form rows on note / expense desc / buy / todo.
# The same typo is applied to both the asset string in the input text and
# to the filter field (query_text / description_text / item_text /
# text_match), so the model sees consistent noisy input/output pairs.
# ---------------------------------------------------------------------------

_VOWEL_SWAP = {"a": "o", "o": "a", "e": "i", "i": "e",
               "A": "O", "O": "A", "E": "I", "I": "E"}
_PHONETIC_PAIRS = [("ph", "f"), ("f", "ph"), ("sh", "ch"), ("ch", "sh"),
                   ("c", "k"), ("k", "c")]


def apply_typo(text: str, rng: random.Random) -> str:
    if not text or len(text) < 3:
        return text
    transform = rng.choice(["vowel_swap", "transpose", "drop", "double_drop", "phonetic"])
    if transform == "vowel_swap":
        positions = [i for i, c in enumerate(text) if c in _VOWEL_SWAP]
        if not positions:
            return text
        i = rng.choice(positions)
        return text[:i] + _VOWEL_SWAP[text[i]] + text[i + 1:]
    if transform == "transpose":
        candidates = [i for i in range(len(text) - 1)
                      if text[i].isalpha() and text[i + 1].isalpha() and text[i] != text[i + 1]]
        if not candidates:
            return text
        i = rng.choice(candidates)
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    if transform == "drop":
        candidates = [i for i, c in enumerate(text) if c.isalpha()]
        if not candidates:
            return text
        i = rng.choice(candidates)
        return text[:i] + text[i + 1:]
    if transform == "double_drop":
        for i in range(len(text) - 1):
            if text[i].isalpha() and text[i] == text[i + 1]:
                return text[:i] + text[i + 1:]
        # Fall through: no double letter found, plain drop.
        candidates = [i for i, c in enumerate(text) if c.isalpha()]
        if not candidates:
            return text
        i = rng.choice(candidates)
        return text[:i] + text[i + 1:]
    # phonetic
    pairs = list(_PHONETIC_PAIRS)
    rng.shuffle(pairs)
    for src, tgt in pairs:
        idx = text.lower().find(src)
        if idx >= 0:
            return text[:idx] + tgt + text[idx + len(src):]
    return text


def maybe_typo(text: str, rng: random.Random, rate: float = SEARCH_TYPO_RATE) -> str:
    return apply_typo(text, rng) if rng.random() < rate else text


# ---------------------------------------------------------------------------
# §5.2 bare-nameless template pools
#
# Per docs/model-training.md Section 5.2, applicable forms drop the `my`/`en`
# possessive at ~10% rate. For weight/ledger the filter still maps to
# `person_text: "self"` (weight) or null (ledger); for expense/todo/buy
# bare-nameless rows keep the same filters as the named version.
# ---------------------------------------------------------------------------

WEIGHT_LATEST_BARE = ["latest weight", "current weight", "todays weight", "current body weight"]
WEIGHT_HISTORY_BARE = ["weight history", "weight log", "weight readings", "weight record"]
WEIGHT_TREND_BARE = ["weight trend", "weight movement", "weight pattern"]
WEIGHT_CHANGE_BARE = ["weight change", "weight delta", "weight shift"]

EXPENSE_TOTAL_BARE = ["total spent", "total spending", "monthly spend"]
EXPENSE_LIST_BARE = ["expense list", "spending list", "expenses"]
EXPENSE_TODAY_BARE = ["today spending", "today expense", "todays expenses"]

TODO_LIST_OPEN_BARE = ["pending tasks", "open tasks", "todo list"]
TODO_TODAY_BARE = ["today tasks", "todays todo list", "todays tasks"]

BUY_LIST_BARE = [
    # 2026-05-09: expanded for the user's common bare phrasings observed in
    # device dogfood logs (#81/#82/#96 returned 0 rows because the model
    # emitted today-only date filters for these inputs).
    "pending buy items", "open buy list", "buy list",
    "list",                   # `ask: buy: list` (chip-scoped form)
    "show buy", "show buy list", "buy items",
    "whats on buy", "what's on buy", "what to buy",
    "open buy", "pending buy",
    "all buy items", "all open buy",
]
BUY_TODAY_BARE = ["today buy list", "today buy items"]

LEDGER_SUMMARY_BARE = [
    # 2026-05-09: expanded for the user's bare phrasings. Dogfood log #64
    # (`ask: balance` → 0 rows) showed the model hallucinated
    # perspective='i_owe_them' for these short queries because they were
    # not in the bare pool. Now they are.
    "pending balance", "outstanding ledger", "whats pending", "open balance",
    "balance", "balances", "show balances", "show balance",
    "ledger summary", "ledger", "all balances",
    "who owes what", "all open balances", "outstanding balances",
]


# ---------------------------------------------------------------------------
# §5.5 action-shaped clarify
# ---------------------------------------------------------------------------

ACTION_CLARIFY_TEMPLATES = [
    "settle {person}",
    "settle {person} amount",
    "clear {person} ledger",
    "settled {person} amount",
    "close {person} balance",
    "pay {person} back",
    "write off {person}",
    "clear {person} account",
    "settle account with {person}",
    "close out {person}",
]

ACTION_CLARIFY_OPTIONS = ["yes - settle now", "show settled list"]


# ---------------------------------------------------------------------------
# §5.6 multi-person compare reject
# ---------------------------------------------------------------------------

MULTI_PERSON_COMPARE_TEMPLATES = [
    "compare {p1} and {p2} latest weight",
    "{p1} vs {p2} weight",
    "{p1} and {p2} weight history",
    "{p1} and {p2} weight trend",
    "compare {p1} {p2} weights",
    "show {p1} and {p2} weight side by side",
    "{p1} vs {p2} weight comparison",
    "compare weight of {p1} and {p2}",
    "show comparison between {p1} and {p2} weight",
]


# ---------------------------------------------------------------------------
# Template pools (Section 4)
#
# Per docs/model-training.md Section 4.3: high-frequency intents (total, list,
# latest, summary, balance) target 15 templates; low-frequency intents
# (compare, change, exclude, history) target 8-10. Within a form the styles
# are split roughly 35% noun / 30% verb / 20% question / 15% Pattern A.
#
# Pattern A is enabled per-lane per Section 2:
#   expense_query, buy_query, note_query: medium share
#   todo_query: low share
#   weight_query, ledger_query: 0
# ---------------------------------------------------------------------------

# === note ===
NOTE_LATEST_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "latest note", "most recent note", "last note", "latest note snippet",
        "today's note", "newest note", "most recent note bucket",
    ],
    "verb": [
        "show my latest note", "give me my last note", "pull up my latest note",
        "open my most recent note", "show today's note bucket",
    ],
    "question": [
        "what is my latest note", "what was the last thing i noted",
        "what did i note recently", "what's my most recent note",
    ],
    # No natural Pattern A here (no embedded Tamil noun). Empty list -> falls
    # back to noun via render_template.
    "tanglish_a": [],
}

NOTE_LIST_RECENT_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "notes from {date}", "{date} notes", "note list for {date}", "recent notes from {date}",
        "{date} note bucket", "notes between {date}",
    ],
    "verb": [
        "show notes from {date}", "list my notes from {date}", "pull notes for {date}",
        "give me notes from {date}", "open my notes for {date}",
    ],
    "question": [
        "what notes do i have from {date}", "any notes from {date}",
        "what did i write {date}", "any notes between {date}",
    ],
    "tanglish_a": [],
}

NOTE_LIST_ABSOLUTE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "notes from {date}", "{date} notes", "note bucket on {date}",
        "{date} note bucket",
    ],
    "verb": [
        "show notes from {date}", "list notes from {date}", "open my notes for {date}",
    ],
    "question": [
        "what did i write on {date}", "any notes from {date}",
        "what notes do i have on {date}",
    ],
    "tanglish_a": [],
}

NOTE_SEARCH_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "notes about {q}", "{q} notes", "notes related to {q}", "{q} mentions in notes",
        "note snippets about {q}", "notes mentioning {q}", "notes covering {q}",
    ],
    "verb": [
        "show my notes about {q}", "find {q} in my notes", "search my notes for {q}",
        "look up {q} in my notes", "pull notes related to {q}", "search notes for {q}",
    ],
    "question": [
        "what did i write about {q}", "did i note anything about {q}",
        "any mention of {q} in my notes", "have i noted anything about {q}",
    ],
    # Pattern A — Tamil/India-flavored noun (the {q} topic) inside an English
    # frame. Avoids `kaatu`/`pannu` (Pattern C / spoken-only).
    "tanglish_a": [
        "notes la {q} irukka", "{q} pathi notes irukka",
    ],
}

# === expense ===
EXPENSE_TOTAL_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "total {date} expense", "{date} total spend", "{date} expense total",
        "expense summary {date}", "total spend for {date}", "{date} spending total",
        "{date} total spending", "total {date} spending",
    ],
    "verb": [
        "show {date} total expense", "give me {date} total spend",
        "calculate my {date} total expense", "tally up {date} expenses",
        "tell me {date} total expense", "add up my {date} expenses",
    ],
    "question": [
        "what is my {date} total expense", "how much did i spend {date}",
        "what's the total expense for {date}", "how much went out {date}",
        "what was my total spend {date}",
    ],
    "tanglish_a": [],
}

EXPENSE_LIST_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "expense list", "{date} expense list", "{date} expenses", "expenses for {date}",
        "{date} spending list", "{date} spend list", "{date} spending breakdown",
    ],
    "verb": [
        "show my expenses", "list {date} expenses", "give me {date} expenses",
        "pull up {date} expense list", "show me my {date} spending",
        "list out my {date} expenses",
    ],
    "question": [
        "what are my {date} expenses", "what did i spend on {date}",
        "what's on my expense list for {date}", "any expenses {date}",
    ],
    "tanglish_a": [],
}

# Note: time-of-day phrasings (`this morning`, `this evening`, `tonight`) are
# NOT used as `{date}` in expense queries any more; they were dropped from
# SEMANTIC_RANGE_ALIASES in the v2 review fix because the lane doesn't
# support time-of-day filtering.
EXPENSE_TODAY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "today expenses", "{date} expenses", "today's spend", "{date} spend",
        "today's expense list",
    ],
    "verb": [
        "show today expense", "list {date} expense", "show {date} spending",
        "show today's expenses",
    ],
    "question": [
        "what did i spend today", "what's my {date} expense",
        "what did i spend {date}",
    ],
    "tanglish_a": [],
}

EXPENSE_GROUP_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{group} expense {date}", "{date} {group} expense", "{group} spend for {date}",
        "{group} spending {date}", "{group} total {date}",
    ],
    "verb": [
        "show {group} expenses for {date}", "tally my {group} spend {date}",
        "show me {date} {group} spending", "give me {group} expense for {date}",
        "list {group} expenses {date}",
    ],
    "question": [
        "what is my total {group} expense {date}", "how much went to {group} {date}",
        "how much did {group} cost me {date}", "what's my {group} spend {date}",
    ],
    "tanglish_a": [],
}

# {desc} can be a Tamil item (`vengayam`, `kothamalli`); the noun bucket
# already produces Pattern A naturally (`vengayam expense this month`).
EXPENSE_DESC_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{desc} expense {date}", "{date} {desc} spend", "{desc} cost {date}",
        "{desc} spending {date}", "spend on {desc} {date}",
    ],
    "verb": [
        "show my {desc} expense {date}", "tally {desc} spend for {date}",
        "give me {desc} expense for {date}", "show how much i spent on {desc} {date}",
    ],
    "question": [
        "what did i spend on {desc} {date}", "how much did {desc} cost {date}",
        "how much went to {desc} {date}",
    ],
    "tanglish_a": [],
}

EXPENSE_RECENT_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "recent expenses", "latest expenses", "last few expenses", "recent spend list",
        "recent spending", "last 10 expenses",
    ],
    "verb": [
        "show recent expenses", "list my latest expenses", "pull up the latest expenses",
        "show last few expenses",
    ],
    "question": [
        "what are my recent expenses", "what did i spend lately",
        "what's been my recent spending",
    ],
    "tanglish_a": [],
}

EXPENSE_LAST_MONTH_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "last month total expense", "{date} total spend", "{date} expense total",
        "last month spending total",
    ],
    "verb": [
        "show {date} total expense", "give me {date} total spend",
        "show last month spending total",
    ],
    "question": [
        "what was my total expense {date}", "how much did i spend {date}",
        "how much did i spend last month",
    ],
    "tanglish_a": [],
}

EXPENSE_EXCLUDE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "expenses apart from {target}", "{date} expenses except {target}",
        "expense list excluding {target}", "expenses other than {target}",
        "spending apart from {target}",
    ],
    "verb": [
        "show my expenses apart from {target}", "list expenses except {target}",
        "pull expenses other than {target}", "exclude {target} from my expenses",
    ],
    "question": [
        "what did i spend on except {target}", "what's left after excluding {target}",
        "any expenses other than {target}",
    ],
    "tanglish_a": [],
}

EXPENSE_COMPARE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "this vs last month expense", "month over month expense comparison",
        "expense comparison this and last month", "this and last month spending",
    ],
    "verb": [
        "compare this month and last month spending",
        "compare this month with last month expense",
        "show expense comparison for this month versus last month",
        "compare this and last month",
    ],
    "question": [
        "how does this month expense compare with last month",
        "is my expense up or down vs last month",
        "this month vs last month — how am i doing",
    ],
    "tanglish_a": [],
}

EXPENSE_HISTORY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "expense history", "{date} expense history", "spending history",
        "{date} spending history",
    ],
    "verb": [
        "show my expense history", "show {date} expense history",
        "show my spending history",
    ],
    "question": [
        "what is my expense history", "what's my expense history for {date}",
        "what does my spending history look like",
    ],
    "tanglish_a": [],
}

# === buy ===
BUY_LIST_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "buy list", "pending buy items", "open buy list", "shopping list",
        "items to buy", "current buy list", "things to buy", "buy checklist",
    ],
    "verb": [
        "show my buy list", "pull up the buy list", "list pending buy items",
        "give me my shopping list", "show items to buy", "open my buy list",
    ],
    "question": [
        "what do i need to buy", "what's left to buy", "what's on my buy list",
        "any pending buy items", "what's still to buy",
    ],
    "tanglish_a": [],
}

BUY_SEARCH_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{item} in buy list", "{item} on shopping list", "{item} to buy",
        "{item} in my shopping list",
    ],
    "verb": [
        "show {item} in my buy list", "find {item} in my shopping list",
        "search buy list for {item}", "look for {item} in my buy list",
    ],
    "question": [
        "is {item} on my buy list", "did i add {item} to buy",
        "have i added {item} to my buy list",
    ],
    # Pattern A — `{item}` may be a Tamil item (`kothamalli`, `vengayam`,
    # `murukku`). `irukka` is the natural Tanglish written form here. We do
    # NOT use `kaatu` (spoken-only) or `vaanganuma` (Pattern C).
    "tanglish_a": [
        "buy list la {item} irukka", "{item} buy list la irukka",
    ],
}

BUY_TODAY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "today buy list", "{date} buy list", "buy items for {date}",
        "{date} shopping list",
    ],
    "verb": [
        "show {date} buy list", "list {date} buy items", "give me {date} buy list",
    ],
    "question": [
        "what do i need to buy {date}", "what's on the buy list for {date}",
        "anything to buy {date}",
    ],
    "tanglish_a": [],
}

BUY_DATE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{date} buy list", "buy list for {date}", "items to buy for {date}",
        "{date} shopping list",
    ],
    "verb": [
        "show buy list for {date}", "list buy items from {date}",
        "show shopping list for {date}",
    ],
    "question": [
        "what was on the buy list for {date}", "anything to buy for {date}",
    ],
    "tanglish_a": [],
}

BUY_ALL_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{status_word} buy items {date}", "{date} {status_word} buy items",
        "every {status_word} buy item {date}", "{status_word} items on the buy list {date}",
    ],
    "verb": [
        "show {status_word} buy items {date}", "list {status_word} buy items {date}",
        "pull up {status_word} buy items {date}",
    ],
    "question": [
        "what are my {status_word} buy items {date}",
        "any {status_word} buy items {date}",
    ],
    "tanglish_a": [],
}

BUY_STATUS_WORDS = {None: "all", "done": "done", "open": "open"}


# ---------------------------------------------------------------------------
# parse_query makers (note / expense / buy)
# ---------------------------------------------------------------------------

def blank_expense_filters() -> dict:
    return {"group": None, "description_text": None, "exclude_group": None, "exclude_description_text": None}


def make_note_query(anchor: str, mode: str, rng: random.Random) -> dict:
    form = weighted_choice(NOTE_FORM_WEIGHTS, rng)
    scoped = rng.random() < SCOPED_SHARE["note"]
    style = pick_style("note_query", mode, rng)
    today = anchor_today(anchor)

    if form == "bare_name_clarify":
        # 2026-05-09: bare-name / 1-word ambiguous queries. Trains the model
        # to emit disposition=clarify rather than silently misclassifying.
        # Body is just a bare person name OR a short relation phrase.
        name = pick_name(mode, rng)
        body_styles = [
            name,                     # `prani`
            name.lower(),             # `prani`  (also lowercase form)
            f"{name} info",
            f"{name} stuff",
            f"about {name}",
            f"any {name}",
            f"{name}?",
            f"{name} something",
        ]
        body = rng.choice(body_styles)
        out = parse_query_clarify(
            domain="note",
            clarify_reason="ambiguous_bare_name",
            clarify_options=[
                f"search notes for {name}",
                f"check ledger balance with {name}",
                f"check todos mentioning {name}",
            ],
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "note", body), "output": out}

    if form == "search":
        topic = pick_topic(mode, rng)
        topic_typoed = maybe_typo(topic, rng)
        body = render_template(NOTE_SEARCH_TEMPLATES, style, rng, q=topic_typoed)
        out = parse_query_accept(domain="note", intent="search", filters={}, query_text=topic_typoed)
        return {"anchor_date": anchor, "input": query_input(scoped, "note", body), "output": out}

    if form == "list_recent":
        # Random named-relative range OR canonical "this week" / "last week" etc.
        roll = rng.random()
        if roll < 0.5:
            phrase, (ds, de) = pick_canonical_phrase(anchor, rng.choice(["this week", "last week", "this month", "last month"]), rng)
        else:
            phrase, (ds, de) = pick_random_named_range(anchor, rng)
        body = render_template(NOTE_LIST_RECENT_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="note", intent="list", filters={}, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "note", body), "output": out}

    if form == "latest":
        body = render_template(NOTE_LATEST_TEMPLATES, style, rng)
        out = parse_query_accept(domain="note", intent="latest", filters={})
        return {"anchor_date": anchor, "input": query_input(scoped, "note", body), "output": out}

    # list_absolute (and list_day collapses here): single specific calendar day
    if rng.random() < 0.6:
        phrase, day = pick_absolute_single_phrase(anchor, rng)
    else:
        # alternate: "yesterday" / "last sunday" style single days (canonical)
        key = rng.choice(["yesterday", "last sunday", "last monday", "last friday"])
        phrase, (day, _) = pick_canonical_phrase(anchor, key, rng)
    body = render_template(NOTE_LIST_ABSOLUTE_TEMPLATES, style, rng, date=phrase)
    out = parse_query_accept(domain="note", intent="list", filters={}, date_start=day, date_end=day)
    return {"anchor_date": anchor, "input": query_input(scoped, "note", body), "output": out}


def make_expense_query(anchor: str, mode: str, rng: random.Random) -> dict:
    form = weighted_choice(EXPENSE_FORM_WEIGHTS, rng)
    scoped = rng.random() < SCOPED_SHARE["expense"]
    style = pick_style("expense_query", mode, rng)
    catalog = expense_catalog(mode)
    f = blank_expense_filters()

    if form == "total":
        ds, de = anchor_this_month(anchor)
        if rng.random() < BARE_NAMELESS_RATE:
            body = rng.choice(EXPENSE_TOTAL_BARE)
        else:
            phrase, (ds, de) = pick_date_input_phrase(anchor, "this month", rng)
            body = render_template(EXPENSE_TOTAL_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="expense", intent="total", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "list":
        ds, de = anchor_this_month(anchor)
        if rng.random() < BARE_NAMELESS_RATE:
            body = rng.choice(EXPENSE_LIST_BARE)
        else:
            phrase, (ds, de) = pick_date_input_phrase(anchor, "this month", rng)
            body = render_template(EXPENSE_LIST_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="expense", intent="list", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "today":
        phrase, (ds, de) = pick_canonical_phrase(anchor, "today", rng)
        if rng.random() < BARE_NAMELESS_RATE:
            body = rng.choice(EXPENSE_TODAY_BARE)
        else:
            body = render_template(EXPENSE_TODAY_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="expense", intent="list", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "group":
        group = rng.choice(list(catalog.keys()))
        f["group"] = group
        phrase, (ds, de) = pick_date_input_phrase(anchor, "this month", rng)
        body = render_template(EXPENSE_GROUP_TEMPLATES, style, rng, date=phrase, group=group)
        out = parse_query_accept(domain="expense", intent="total", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "desc":
        group = rng.choice(list(catalog.keys()))
        desc = rng.choice(catalog[group])
        desc_typoed = maybe_typo(desc, rng)
        f["description_text"] = desc_typoed
        # 2026-05-09: ~30% of desc-form rows now use undated phrasings
        # (`total milk expense`, `expense on petrol`, `{desc} expense`) with
        # date_start=None / date_end=None. User dogfood logs (#85, #88, #100)
        # showed undated `{keyword} expense` phrasings consistently failed
        # because the model only saw dated variants during training.
        if rng.random() < 0.30:
            undated_templates = [
                "total {desc} expense", "{desc} expense", "expense on {desc}",
                "spend on {desc}", "{desc} spend", "{desc} total",
                "how much on {desc}", "what did i spend on {desc}",
                "show {desc} expenses", "tally {desc} spend",
                "give me {desc} expense", "{desc} cost so far",
            ]
            body = rng.choice(undated_templates).format(desc=desc_typoed)
            out = parse_query_accept(
                domain="expense", intent="total", filters=f,
                date_start=None, date_end=None,
            )
        else:
            phrase, (ds, de) = pick_date_input_phrase(anchor, "this month", rng)
            body = render_template(EXPENSE_DESC_TEMPLATES, style, rng, date=phrase, desc=desc_typoed)
            out = parse_query_accept(domain="expense", intent="total", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "recent":
        body = render_template(EXPENSE_RECENT_TEMPLATES, style, rng)
        out = parse_query_accept(domain="expense", intent="list", filters=f, limit=10)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "top_n":
        # 2026-05-09: top-N / biggest-N expense queries. The N is explicit in
        # the input AND in the output `limit` field. Trains the model to
        # extract numeric N from natural phrasings.
        n = rng.choice([3, 5, 10])
        templates = [
            f"top {n} expenses",
            f"biggest {n} expenses",
            f"top {n} spending",
            f"highest {n} expenses",
            f"my top {n} expenses",
            f"show top {n} spending",
            f"{n} biggest expenses",
            f"{n} most expensive expenses",
            f"top {n} expense {{date}}",
            f"biggest {n} spends {{date}}",
        ]
        # Optional date qualifier on a third of rows.
        if rng.random() < 0.33:
            phrase, (ds, de) = pick_canonical_phrase(anchor, "this month", rng)
            tpl = templates[-2] if rng.random() < 0.5 else templates[-1]
            body = tpl.format(date=phrase)
            out = parse_query_accept(
                domain="expense", intent="list", filters=f,
                date_start=ds, date_end=de, limit=n,
            )
        else:
            body = rng.choice([t for t in templates if "{date}" not in t])
            out = parse_query_accept(
                domain="expense", intent="list", filters=f, limit=n,
            )
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "last_month":
        phrase, (ds, de) = pick_canonical_phrase(anchor, "last month", rng)
        body = render_template(EXPENSE_LAST_MONTH_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="expense", intent="total", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "exclude":
        if rng.random() < 0.5:
            target = rng.choice(list(catalog.keys()))
            f["exclude_group"] = target
        else:
            group = rng.choice(list(catalog.keys()))
            target = rng.choice(catalog[group])
            f["exclude_description_text"] = target
        phrase, (ds, de) = pick_date_input_phrase(anchor, "this month", rng)
        body = render_template(EXPENSE_EXCLUDE_TEMPLATES, style, rng, date=phrase, target=target)
        out = parse_query_accept(domain="expense", intent="list", filters=f, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    if form == "compare":
        body = render_template(EXPENSE_COMPARE_TEMPLATES, style, rng)
        ds_curr, de_curr = anchor_this_month(anchor)
        ds_prev, de_prev = anchor_last_month(anchor)
        out = parse_query_accept(
            domain="expense", intent="compare", filters=f,
            date_start=ds_curr, date_end=de_curr,
            compare_date_start=ds_prev, compare_date_end=de_prev,
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}

    # form == "history"  -> intent total, this month per Q2
    phrase, (ds, de) = pick_canonical_phrase(anchor, "this month", rng)
    body = render_template(EXPENSE_HISTORY_TEMPLATES, style, rng, date=phrase)
    out = parse_query_accept(domain="expense", intent="total", filters=f, date_start=ds, date_end=de)
    return {"anchor_date": anchor, "input": query_input(scoped, "expense", body), "output": out}


def make_buy_query(anchor: str, mode: str, rng: random.Random) -> dict:
    form = weighted_choice(BUY_FORM_WEIGHTS, rng)
    scoped = rng.random() < SCOPED_SHARE["buy"]
    style = pick_style("buy_query", mode, rng)
    item = pick_buy_item(mode, rng)

    if form == "list":
        # 2026-05-09: bare rate bumped 10% → 35% for buy specifically. The user
        # types `buy list` / `open buy list` / `ask: buy: list` constantly and
        # the 10% exposure rate wasn't enough — model defaulted to a today-only
        # date filter for these phrasings (logs #81/#82/#96). Buy is an
        # inventory-style lane: undated list IS the canonical query.
        if rng.random() < 0.35:
            body = rng.choice(BUY_LIST_BARE)
        else:
            body = render_template(BUY_LIST_TEMPLATES, style, rng)
        out = parse_query_accept(
            domain="buy", intent="list",
            filters={"status": "open", "item_text": None},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "buy", body), "output": out}

    if form == "search":
        item_typoed = maybe_typo(item, rng)
        body = render_template(BUY_SEARCH_TEMPLATES, style, rng, item=item_typoed)
        out = parse_query_accept(
            domain="buy", intent="search",
            filters={"status": None, "item_text": item_typoed},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "buy", body), "output": out}

    if form == "today":
        phrase, (ds, de) = pick_canonical_phrase(anchor, "today", rng)
        if rng.random() < BARE_NAMELESS_RATE:
            body = rng.choice(BUY_TODAY_BARE)
        else:
            body = render_template(BUY_TODAY_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(
            domain="buy", intent="list",
            filters={"status": "open", "item_text": None},
            date_start=ds, date_end=de,
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "buy", body), "output": out}

    if form == "date":
        date_keys = ["yesterday", "last sunday", "last monday", "last friday", "weekend"]
        phrase, (ds, de) = pick_canonical_phrase(anchor, rng.choice(date_keys), rng)
        body = render_template(BUY_DATE_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(
            domain="buy", intent="list",
            filters={"status": "open", "item_text": None},
            date_start=ds, date_end=de,
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "buy", body), "output": out}

    # form == "all"
    status = rng.choice([None, "done", "open"])
    phrase, (ds, de) = pick_canonical_phrase(anchor, "today", rng)
    body = render_template(BUY_ALL_TEMPLATES, style, rng, date=phrase, status_word=BUY_STATUS_WORDS[status])
    out = parse_query_accept(
        domain="buy", intent="list",
        filters={"status": status, "item_text": None},
        date_start=ds, date_end=de,
    )
    return {"anchor_date": anchor, "input": query_input(scoped, "buy", body), "output": out}


# === todo ===
TODO_LIST_OPEN_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "pending tasks", "open todos", "open task list", "pending todo list",
        "task list", "things to do", "todo list", "open tasks",
        "what's pending",
    ],
    "verb": [
        "show pending tasks", "show my todo list", "show open todos",
        "list pending tasks", "give me my todo list", "list open todos",
    ],
    "question": [
        "what is pending", "what do i need to do", "what's left to do",
        "anything pending", "what's still open",
    ],
    "tanglish_a": [],
}

TODO_TODAY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{date} tasks", "{date} todo list", "{date} todos", "{date} to do",
        "{date} task list",
    ],
    "verb": [
        "show {date} tasks", "list {date} todos", "show me {date} todo list",
        "give me {date} tasks",
    ],
    "question": [
        "what do i need to do {date}", "what's on my list {date}",
        "any tasks for {date}",
    ],
    "tanglish_a": [],
}

TODO_SEARCH_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{q} todo", "{q} task", "{q} on my list", "{q} pending task",
        "{q} reminder",
    ],
    "verb": [
        "show {q}", "find {q} on my list", "look up {q} in todos",
        "search my todos for {q}",
    ],
    "question": [
        "is {q} on my list", "do i have {q} pending",
        "any todo about {q}",
    ],
    "tanglish_a": [],
}

TODO_ALL_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "all todos", "every todo", "open and done todos", "complete todo list",
        "all tasks", "full task list",
    ],
    "verb": [
        "show all todos", "list every todo", "give me all todos",
        "show open and done todos",
    ],
    "question": [
        "what's the full todo list", "what are all my todos",
    ],
    "tanglish_a": [],
}

TODO_DUE_WEEK_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "due this week", "tasks due {date}", "{date} pending tasks",
        "tasks for {date}", "{date} due tasks",
    ],
    "verb": [
        "show what is due {date}", "list pending tasks for {date}",
        "show {date} pending todos", "list {date} due tasks",
    ],
    "question": [
        "what is due {date}", "what's pending for {date}",
        "what tasks are due {date}",
    ],
    "tanglish_a": [
    ],
}

TODO_HISTORY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "task history", "todo history", "completed task history",
        "task log", "completed tasks list",
    ],
    "verb": [
        "show my task history", "list completed todos",
        "give me my todo history", "show task log",
    ],
    "question": [
        "what is my task history", "what tasks have i done",
    ],
    "tanglish_a": [],
}

TODO_DONE_TODAY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "done {date}", "{date} done tasks", "{date} completed tasks",
        "{date} finished tasks",
    ],
    "verb": [
        "show what i finished {date}", "list completed tasks {date}",
        "show done todos {date}", "show {date} finished tasks",
    ],
    "question": [
        "what did i finish {date}", "what did i complete {date}",
        "anything i finished {date}",
    ],
    "tanglish_a": [],
}

# === weight ===
WEIGHT_LATEST_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        # Person-less templates (e.g. "latest weight") live in the
        # BARE_NAMELESS pool only, since the maker always emits a
        # person_text filter; rendering a person-less template with a
        # named person would produce input/output disagreement.
        "{person_text} latest weight", "current weight {person_text}",
        "{person_text} current weight", "{person_text} most recent weight",
        "{person_text} weight reading",
        # 2026-05-09 (later): bare-question forms. User dogfood log #105
        # showed `ask: what is jeevi weight` failed because the model only
        # saw `what is X latest weight` style. Add bare-noun question shapes.
        "{person_text} weight",            # the user's exact bare form
        "weight of {person_text}",
        "weight {person_text}",
        "{person_text}'s weight",
    ],
    "verb": [
        "show {person_text} latest weight", "give me {person_text} current weight",
        "tell me {person_text} latest weight", "log {person_text} latest weight",
        # 2026-05-09 (later): natural-verb question variants
        "show {person_text} weight",
        "give me {person_text} weight",
        "tell me {person_text} weight",
        "show me {person_text}'s weight",
        "fetch {person_text} weight",
        "pull up {person_text} weight",
        "find {person_text} weight",
        "look up {person_text} weight",
    ],
    "question": [
        "what is {person_text} latest weight", "what's {person_text} current weight",
        "how much does {person_text} weigh now",
        # 2026-05-09 (later): natural-question shapes — the user's #105
        # failure was `what is jeevi weight` (no `latest`/`current`).
        "what is {person_text} weight",
        "what's {person_text} weight",
        "whats {person_text} weight",       # missing apostrophe
        "what is the weight of {person_text}",
        "what's the weight of {person_text}",
        "how much does {person_text} weigh",
        "how much {person_text} weighs",
        "do you know {person_text} weight",
        "can you tell {person_text} weight",
        "{person_text} weight please",
        "{person_text} weight?",
    ],
    "tanglish_a": [],  # Section 2: weight queries are 0% Pattern A
}

WEIGHT_HISTORY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{person_text} weight history", "weight log {person_text}", "{person_text} weight readings",
    ],
    "verb": [
        "show {person_text} weight history", "list {person_text} weight readings",
        "pull up {person_text} weight log",
    ],
    "question": [
        "what is {person_text} weight history", "show me how {person_text} weight has changed",
    ],
    "tanglish_a": [],
}

WEIGHT_TREND_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{person_text} weight trend", "weight trend {person_text}",
    ],
    "verb": [
        "show {person_text} weight trend", "graph {person_text} weight",
    ],
    "question": [
        "is {person_text} weight going up or down", "what's {person_text} weight trend",
    ],
    "tanglish_a": [],
}

WEIGHT_CHANGE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{person_text} weight change since {date}", "{person_text} weight delta {date}",
    ],
    "verb": [
        "show {person_text} weight change since {date}",
        "tell me how much {person_text} weight changed since {date}",
    ],
    "question": [
        "how much did {person_text} weight change since {date}",
        "by how much has {person_text} lost or gained since {date}",
    ],
    "tanglish_a": [],
}

WEIGHT_LATEST_ALL_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "latest weights", "everyone's latest weight", "all latest weights",
    ],
    "verb": [
        "show latest weights", "list everyone's latest weight",
    ],
    "question": [
        "what are the latest weights", "what is everyone's latest weight",
    ],
    "tanglish_a": [],
}

WEIGHT_DATE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{person_text} weight from {date}", "{date} {person_text} weight",
    ],
    "verb": [
        "show {person_text} weight from {date}", "log {person_text} weight on {date}",
    ],
    "question": [
        "what was {person_text} weight on {date}",
    ],
    "tanglish_a": [],
}

# === ledger ===
# v2 review: ledger query templates rewritten away from literal "ledger" word
# (which was in 66/100 ledger queries in the prior dry run). Real users say
# "balance", "what i owe", "who owes me", "pending", etc. The scope tag
# `ask: ledger:` carries the lane signal when present.

LEDGER_SUMMARY_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "open balances", "pending balances", "outstanding balances", "open balance summary",
        "what's pending", "pending money", "open dues", "outstanding dues",
        "open ledger", "ledger summary",
    ],
    "verb": [
        "show pending balances", "list open balances", "show outstanding dues",
        "summarize pending money", "show what's outstanding", "show open dues",
    ],
    "question": [
        "what's pending overall", "what's outstanding", "what's the pending position",
        "any open balances", "where do my balances stand",
    ],
    "tanglish_a": [],
}

# Perspective-aware balance templates (v2 review fix).
#
# Bare phrasings ("X balance", "balance with X", "tell me X balance") are
# direction-neutral and must emit perspective=null. Direction-specific
# phrasings live in LEDGER_BALANCE_I_OWE_TEMPLATES /
# LEDGER_BALANCE_THEY_OWE_TEMPLATES so the maker can pair them with the
# correct perspective filter.
LEDGER_BALANCE_NEUTRAL_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{person_text} balance", "balance with {person_text}", "{person_text} pending",
        "open balance with {person_text}", "{person_text} outstanding",
    ],
    "verb": [
        "show {person_text} balance", "tell me {person_text} balance",
        "give me {person_text} balance", "show balance with {person_text}",
    ],
    "question": [
        "what's the balance with {person_text}", "where do i stand with {person_text}",
        "what's pending with {person_text}",
    ],
    "tanglish_a": [],
}

LEDGER_BALANCE_I_OWE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "what i owe {person_text}", "amount i owe {person_text}", "my dues to {person_text}",
        "what's pending to {person_text}",
    ],
    "verb": [
        "show what i owe {person_text}", "tell me how much i owe {person_text}",
        "list what i owe {person_text}",
    ],
    "question": [
        "how much do i owe {person_text}", "how much do i still owe {person_text}",
        "what do i owe {person_text}",
    ],
    "tanglish_a": [],
}

LEDGER_BALANCE_THEY_OWE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "what {person_text} owes me", "amount {person_text} owes me", "{person_text} dues to me",
        "what's pending from {person_text}",
    ],
    "verb": [
        "show what {person_text} owes me", "tell me how much {person_text} owes me",
        "list what {person_text} owes me",
    ],
    "question": [
        "how much does {person_text} owe me", "how much is {person_text} still owing me",
        "what does {person_text} owe me",
    ],
    "tanglish_a": [],
}

LEDGER_PERSON_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{person_text} entries", "entries with {person_text}", "history with {person_text}",
        "all transactions with {person_text}", "{person_text} ledger",
    ],
    "verb": [
        "show entries with {person_text}", "list transactions with {person_text}",
        "pull history with {person_text}", "show {person_text} entries",
    ],
    "question": [
        "what entries do i have with {person_text}",
        "what's the history with {person_text}",
    ],
    "tanglish_a": [],
}

LEDGER_WHO_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "who owes me", "people who owe me", "list of debtors",
        "people i owe", "who i owe", "list of creditors",
    ],
    "verb": [
        "show who owes me", "list people i owe", "tell me whom i owe",
        "show people who owe me", "list debtors",
    ],
    "question": [
        "who owes me money", "whom do i owe", "who do i need to pay",
        "who still owes me",
    ],
    "tanglish_a": [],
}

LEDGER_RECENT_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "recent transactions", "latest transactions", "recent activity",
        "recent borrows and lends", "recent ledger entries",
    ],
    "verb": [
        "show recent transactions", "list recent activity",
        "show latest transactions",
    ],
    "question": [
        "what are my recent transactions", "any recent activity",
    ],
    "tanglish_a": [],
}

LEDGER_RANGE_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "{date} transactions", "transactions from {date}", "{date} activity",
        "borrows and lends {date}", "{date} ledger entries",
    ],
    "verb": [
        "show transactions from {date}", "list {date} activity",
        "show {date} borrows and lends",
    ],
    "question": [
        "what transactions are from {date}", "what activity from {date}",
    ],
    "tanglish_a": [],
}

LEDGER_SEARCH_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "settled entries", "settled balances", "settled with {person_text}",
        "cleared balances", "settled ledger for {person_text}",
    ],
    "verb": [
        "show settled entries", "list settled balances",
        "show settled with {person_text}", "list cleared balances",
    ],
    "question": [
        "what's already settled", "which balances are settled",
        "what did i settle with {person_text}",
    ],
    "tanglish_a": [],
}

LEDGER_LATEST_TEMPLATES: dict[str, list[str]] = {
    "noun": [
        "latest activity", "most recent transaction", "latest borrow or lend",
        "latest ledger",
    ],
    "verb": [
        "show latest activity", "give me the most recent transaction",
    ],
    "question": [
        "what is my latest activity", "what was the last transaction",
    ],
    "tanglish_a": [],
}


# ---------------------------------------------------------------------------
# parse_query makers (todo / weight / ledger)
# ---------------------------------------------------------------------------

def make_todo_query(anchor: str, mode: str, rng: random.Random) -> dict:
    form = weighted_choice(TODO_FORM_WEIGHTS, rng)
    scoped = rng.random() < SCOPED_SHARE["todo"]
    style = pick_style("todo_query", mode, rng)

    if form == "list_open":
        if rng.random() < BARE_NAMELESS_RATE:
            body = rng.choice(TODO_LIST_OPEN_BARE)
        else:
            body = render_template(TODO_LIST_OPEN_TEMPLATES, style, rng)
        out = parse_query_accept(domain="todo", intent="list", filters={"status": "open", "text_match": None})
        return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}

    if form == "today":
        phrase, (ds, de) = pick_canonical_phrase(anchor, "today", rng)
        if rng.random() < BARE_NAMELESS_RATE:
            body = rng.choice(TODO_TODAY_BARE)
        else:
            body = render_template(TODO_TODAY_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="todo", intent="list", filters={"status": "open", "text_match": None}, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}

    if form == "search":
        task = pick_todo_text(mode, rng)
        task_typoed = maybe_typo(task, rng)
        body = render_template(TODO_SEARCH_TEMPLATES, style, rng, q=task_typoed)
        out = parse_query_accept(domain="todo", intent="search", filters={"status": None, "text_match": task_typoed})
        return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}

    if form == "all":
        body = render_template(TODO_ALL_TEMPLATES, style, rng)
        out = parse_query_accept(domain="todo", intent="list", filters={"status": None, "text_match": None})
        return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}

    if form == "due_week":
        phrase, (ds, de) = pick_canonical_phrase(anchor, "this week", rng)
        body = render_template(TODO_DUE_WEEK_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(domain="todo", intent="list", filters={"status": "open", "text_match": None}, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}

    if form == "history":
        body = render_template(TODO_HISTORY_TEMPLATES, style, rng)
        out = parse_query_accept(domain="todo", intent="history", filters={"status": None, "text_match": None}, limit=10)
        return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}

    # done_today
    phrase, (ds, de) = pick_canonical_phrase(anchor, "today", rng)
    body = render_template(TODO_DONE_TODAY_TEMPLATES, style, rng, date=phrase)
    out = parse_query_accept(domain="todo", intent="list", filters={"status": "done", "text_match": None}, date_start=ds, date_end=de)
    return {"anchor_date": anchor, "input": query_input(scoped, "todo", body), "output": out}


def make_weight_query(anchor: str, mode: str, rng: random.Random) -> dict:
    form = weighted_choice(WEIGHT_FORM_WEIGHTS, rng)
    scoped = rng.random() < SCOPED_SHARE["weight"]

    if form == "multi_person_compare_reject":
        # §5.6: reject multi-person weight comparisons.
        p1 = pick_name(mode, rng)
        p2 = pick_name(mode, rng)
        while p2 == p1:
            p2 = pick_name(mode, rng)
        body = rng.choice(MULTI_PERSON_COMPARE_TEMPLATES).format(p1=p1, p2=p2)
        out = parse_query_reject(domain="weight", reason_code="multi_person_compare_unsupported")
        return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}

    style = pick_style("weight_query", mode, rng)
    # §5.2: decide bare-nameless first so the rate matches the target.
    # When bare fires, force person="self" (the only sensible mapping for a
    # person-less weight query, per session lock).
    is_bare = rng.random() < BARE_NAMELESS_RATE
    if is_bare:
        person = "self"
    else:
        person = "self" if rng.random() < 0.5 else pick_name(mode, rng)
    person_text_phrase = "my" if person == "self" else person

    if form == "latest":
        if is_bare:
            body = rng.choice(WEIGHT_LATEST_BARE)
        else:
            body = render_template(WEIGHT_LATEST_TEMPLATES, style, rng, person_text=person_text_phrase)
        out = parse_query_accept(domain="weight", intent="latest", filters={"person_text": person})
        return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}

    if form == "history":
        ds, de = anchor_six_months_window(anchor)
        limit = None if person == "self" else 5
        if is_bare:
            body = rng.choice(WEIGHT_HISTORY_BARE)
        else:
            body = render_template(WEIGHT_HISTORY_TEMPLATES, style, rng, person_text=person_text_phrase)
        out = parse_query_accept(domain="weight", intent="history", filters={"person_text": person}, date_start=ds, date_end=de, limit=limit)
        return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}

    if form == "trend":
        ds, de = anchor_six_months_window(anchor)
        if is_bare:
            body = rng.choice(WEIGHT_TREND_BARE)
        else:
            body = render_template(WEIGHT_TREND_TEMPLATES, style, rng, person_text=person_text_phrase)
        out = parse_query_accept(domain="weight", intent="trend", filters={"person_text": person}, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}

    if form == "change":
        ds, de = anchor_year_to_date(anchor)
        phrase, _ = pick_canonical_phrase(anchor, "year to date", rng)
        if is_bare:
            body = rng.choice(WEIGHT_CHANGE_BARE)
        else:
            body = render_template(WEIGHT_CHANGE_TEMPLATES, style, rng, person_text=person_text_phrase, date=phrase)
        out = parse_query_accept(domain="weight", intent="change", filters={"person_text": person}, date_start=ds, date_end=de)
        return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}

    if form == "latest_all":
        body = render_template(WEIGHT_LATEST_ALL_TEMPLATES, style, rng)
        out = parse_query_accept(domain="weight", intent="latest_all", filters={"person_text": None})
        return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}

    # form == "date"
    date_keys = ["yesterday", "last sunday", "last monday", "last friday", "weekend"]
    phrase, (ds, de) = pick_canonical_phrase(anchor, rng.choice(date_keys), rng)
    body = render_template(WEIGHT_DATE_TEMPLATES, style, rng, person_text=person_text_phrase, date=phrase)
    out = parse_query_accept(domain="weight", intent="history", filters={"person_text": person}, date_start=ds, date_end=de)
    return {"anchor_date": anchor, "input": query_input(scoped, "weight", body), "output": out}


def make_ledger_query(anchor: str, mode: str, rng: random.Random) -> dict:
    form = weighted_choice(LEDGER_FORM_WEIGHTS, rng)
    scoped = rng.random() < SCOPED_SHARE["ledger"]

    if form == "action_clarify":
        # §5.5: action-shaped query that the parser cannot disambiguate
        # between "settle now" (write) and "show settled list" (query).
        person = pick_name(mode, rng)
        body = rng.choice(ACTION_CLARIFY_TEMPLATES).format(person=person)
        out = parse_query_clarify(
            domain="ledger",
            clarify_reason="looks_like_action",
            clarify_options=list(ACTION_CLARIFY_OPTIONS),
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    style = pick_style("ledger_query", mode, rng)
    person = pick_name(mode, rng)

    if form == "summary":
        # 2026-05-09: bare rate bumped 10% → 30% for ledger summary. The user
        # types `balance` / `show balances` / `ledger` constantly (#64 returned
        # 0 rows because the model hallucinated perspective='i_owe_them' for
        # these short inputs). The accept output keeps perspective=None and
        # status="open" so the user sees their actual outstanding balances.
        if rng.random() < 0.30:
            body = rng.choice(LEDGER_SUMMARY_BARE)
        else:
            body = render_template(LEDGER_SUMMARY_TEMPLATES, style, rng)
        out = parse_query_accept(
            domain="ledger", intent="summary",
            filters={"person_text": None, "perspective": None, "status": "open"},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    if form == "balance":
        # v2 review fix: bare "X balance" / "balance with X" / "tell me X
        # balance" must resolve to perspective=null (return both sides).
        # Direction-specific phrasings ("how much do i owe X" / "how much
        # does X owe me") have their own template buckets so the perspective
        # filter aligns with the rendered surface form.
        balance_kind = rng.choices(
            ["neutral", "i_owe", "they_owe"],
            weights=[0.5, 0.25, 0.25],
        )[0]
        if balance_kind == "i_owe":
            tpl = LEDGER_BALANCE_I_OWE_TEMPLATES
            perspective = "i_owe_them"
        elif balance_kind == "they_owe":
            tpl = LEDGER_BALANCE_THEY_OWE_TEMPLATES
            perspective = "they_owe_me"
        else:
            tpl = LEDGER_BALANCE_NEUTRAL_TEMPLATES
            perspective = None
        body = render_template(tpl, style, rng, person_text=person)
        out = parse_query_accept(
            domain="ledger", intent="balance",
            filters={"person_text": person, "perspective": perspective, "status": "open"},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    if form == "person":
        body = render_template(LEDGER_PERSON_TEMPLATES, style, rng, person_text=person)
        out = parse_query_accept(
            domain="ledger", intent="list",
            filters={"person_text": person, "perspective": None, "status": None},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    if form == "who":
        perspective = rng.choice(["they_owe_me", "i_owe_them"])
        body = render_template(LEDGER_WHO_TEMPLATES, style, rng)
        out = parse_query_accept(
            domain="ledger", intent="summary",
            filters={"person_text": None, "perspective": perspective, "status": "open"},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    if form == "recent":
        body = render_template(LEDGER_RECENT_TEMPLATES, style, rng)
        out = parse_query_accept(
            domain="ledger", intent="list",
            filters={"person_text": None, "perspective": None, "status": None},
            limit=10,
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    if form == "range":
        phrase, (ds, de) = pick_date_input_phrase(anchor, rng.choice(["this month", "last month", "this week", "last week"]), rng)
        body = render_template(LEDGER_RANGE_TEMPLATES, style, rng, date=phrase)
        out = parse_query_accept(
            domain="ledger", intent="list",
            filters={"person_text": None, "perspective": None, "status": None},
            date_start=ds, date_end=de,
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    if form == "search":
        target = person if rng.random() < 0.4 else None
        body = render_template(LEDGER_SEARCH_TEMPLATES, style, rng, person_text=person if target else "")
        # If target is None, strip the "for " part by switching to a target-less template
        if target is None and "for " in body:
            body = render_template(LEDGER_SEARCH_TEMPLATES, "noun", rng, person_text="")
            body = body.replace(" for ", "").strip()
        out = parse_query_accept(
            domain="ledger", intent="search",
            filters={"person_text": target, "perspective": None, "status": "settled"},
        )
        return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}

    # form == "latest"  -> folded latest_balance: summary with limit=1
    body = render_template(LEDGER_LATEST_TEMPLATES, style, rng)
    out = parse_query_accept(
        domain="ledger", intent="summary",
        filters={"person_text": None, "perspective": None, "status": None},
        limit=1,
    )
    return {"anchor_date": anchor, "input": query_input(scoped, "ledger", body), "output": out}


# ---------------------------------------------------------------------------
# §5.1 Adversarial domain pairs
#
# Each pair carries the SAME person name across two domains so the model
# must attend to the domain word, not just the person. Pairs are emitted
# to a dedicated parse_query/adversarial.jsonl (per user choice in this
# session) so the slice cannot be lost to per-lane shuffling.
# ---------------------------------------------------------------------------

ADVERSARIAL_WEIGHT_TEMPLATES = [
    "{person} latest weight",
    "what is {person} latest weight",
    "{person} current weight",
    "show {person} latest weight",
    "{person} weight",
]

ADVERSARIAL_LEDGER_BALANCE_TEMPLATES = [
    "{person} balance",
    "balance with {person}",
    "how much do i owe {person}",
    "how much does {person} owe me",
    "show {person} balance",
]

ADVERSARIAL_TODO_TEMPLATES = [
    "call {person} todo",
    "{person} call task",
    "find call {person} on my list",
    "any todo about {person}",
    "{person} todo",
]

ADVERSARIAL_NOTE_TEMPLATES = [
    "notes about {person}",
    "find {person} in my notes",
    "any mention of {person} in my notes",
    "show notes related to {person}",
    "{person} note snippets",
]


def make_adversarial_pair(anchor: str, mode: str, rng: random.Random) -> list[dict]:
    """Return a list of two parse_query rows that share the same person
    name but live in different domains. Caller writes both rows to the
    same adversarial.jsonl file so the pair stays intact in training."""
    person = pick_name(mode, rng)
    pair_kind = rng.choice(["weight_ledger", "weight_todo", "weight_note"])

    weight_body = rng.choice(ADVERSARIAL_WEIGHT_TEMPLATES).format(person=person)
    weight_row = {
        "anchor_date": anchor,
        "input": f"ask: {weight_body}",
        "output": parse_query_accept(
            domain="weight", intent="latest", filters={"person_text": person},
        ),
    }

    if pair_kind == "weight_ledger":
        body = rng.choice(ADVERSARIAL_LEDGER_BALANCE_TEMPLATES).format(person=person)
        # Pick a perspective that fits the phrasing.
        body_l = body.lower()
        if "how much do i owe" in body_l:
            perspective = "i_owe_them"
        elif "how much does" in body_l and "owe me" in body_l:
            perspective = "they_owe_me"
        else:
            perspective = rng.choice(["i_owe_them", "they_owe_me"])
        other_row = {
            "anchor_date": anchor,
            "input": f"ask: {body}",
            "output": parse_query_accept(
                domain="ledger", intent="balance",
                filters={"person_text": person, "perspective": perspective, "status": "open"},
            ),
        }
    elif pair_kind == "weight_todo":
        body = rng.choice(ADVERSARIAL_TODO_TEMPLATES).format(person=person)
        text_match = f"call {person}" if "call" in body else person
        other_row = {
            "anchor_date": anchor,
            "input": f"ask: {body}",
            "output": parse_query_accept(
                domain="todo", intent="search",
                filters={"status": None, "text_match": text_match},
            ),
        }
    else:  # weight_note
        body = rng.choice(ADVERSARIAL_NOTE_TEMPLATES).format(person=person)
        other_row = {
            "anchor_date": anchor,
            "input": f"ask: {body}",
            "output": parse_query_accept(
                domain="note", intent="search", filters={}, query_text=person,
            ),
        }

    return [weight_row, other_row]


# ---------------------------------------------------------------------------
# parse_followup_query maker
#
# A followup row carries the prior parse_query output as `context` and the
# user's next utterance as `input`. The output is a parse_followup_query
# with `inherit_context: true` and v2 intents only.
#
# Per docs/model-training.md Section 1.2, parse_followup_query allows only the
# `accept` disposition. Followups inherit from accept-shape contexts; if
# the base maker returns a reject/clarify row, retry until accept.
# ---------------------------------------------------------------------------

FOLLOWUP_DOMAIN_WEIGHTS: dict[str, float] = {
    "expense": 35, "buy": 10, "todo": 15, "weight": 15, "ledger": 15, "note": 10,
}


def _accept_base_query(maker, anchor: str, mode: str, rng: random.Random) -> dict:
    for _ in range(20):
        row = maker(anchor, mode, rng)
        if row["output"]["disposition"] == "accept":
            return row
    return row


def _followup_expense(anchor: str, mode: str, rng: random.Random) -> dict:
    base = _accept_base_query(make_expense_query, anchor, mode, rng)["output"]
    catalog = expense_catalog(mode)
    group = rng.choice(list(catalog.keys()))
    desc = rng.choice(catalog[group])
    today_iso = anchor_today(anchor)
    yest_iso = anchor_yesterday(anchor)
    choices = [
        ("ask: of that how much was " + group,
         {"group": group, "description_text": None, "exclude_group": None, "exclude_description_text": None},
         base["intent"], base["date_start"], base["date_end"]),
        ("ask: only " + desc,
         {"group": None, "description_text": desc, "exclude_group": None, "exclude_description_text": None},
         "list", base["date_start"], base["date_end"]),
        ("ask: apart from " + group,
         {"group": None, "description_text": None, "exclude_group": group, "exclude_description_text": None},
         base["intent"], base["date_start"], base["date_end"]),
        ("ask: list those instead",
         dict(base["filters"]) if base["filters"] else {"group": None, "description_text": None, "exclude_group": None, "exclude_description_text": None},
         "list", base["date_start"], base["date_end"]),
        ("ask: only from yesterday",
         dict(base["filters"]) if base["filters"] else {"group": None, "description_text": None, "exclude_group": None, "exclude_description_text": None},
         base["intent"], yest_iso, yest_iso),
        ("ask: only today",
         dict(base["filters"]) if base["filters"] else {"group": None, "description_text": None, "exclude_group": None, "exclude_description_text": None},
         base["intent"], today_iso, today_iso),
    ]
    inp, new_filters, new_intent, ds, de = rng.choice(choices)
    out = parse_followup_query_accept(
        domain="expense", intent=new_intent, filters=new_filters,
        date_start=ds, date_end=de,
        compare_date_start=base["compare_date_start"], compare_date_end=base["compare_date_end"],
        limit=base["limit"], query_text=base["query_text"],
    )
    return {"anchor_date": anchor, "context": base, "input": inp, "output": out}


def _followup_buy(anchor: str, mode: str, rng: random.Random) -> dict:
    base = _accept_base_query(make_buy_query, anchor, mode, rng)["output"]
    item = pick_buy_item(mode, rng)
    yest_iso = anchor_yesterday(anchor)
    base_filters = base["filters"] or {"status": "open", "item_text": None}
    choices = [
        ("ask: show only done ones", {"status": "done", "item_text": base_filters.get("item_text")}, base["intent"], base["date_start"], base["date_end"]),
        ("ask: only " + item, {"status": base_filters.get("status"), "item_text": item}, "search", base["date_start"], base["date_end"]),
        ("ask: only yesterday", dict(base_filters), base["intent"], yest_iso, yest_iso),
        ("ask: show open ones", {"status": "open", "item_text": base_filters.get("item_text")}, "list", base["date_start"], base["date_end"]),
    ]
    inp, new_filters, new_intent, ds, de = rng.choice(choices)
    out = parse_followup_query_accept(
        domain="buy", intent=new_intent, filters=new_filters,
        date_start=ds, date_end=de,
        limit=base["limit"], query_text=base["query_text"],
    )
    return {"anchor_date": anchor, "context": base, "input": inp, "output": out}


def _followup_todo(anchor: str, mode: str, rng: random.Random) -> dict:
    base = _accept_base_query(make_todo_query, anchor, mode, rng)["output"]
    task = pick_todo_text(mode, rng)
    yest_iso = anchor_yesterday(anchor)
    base_filters = base["filters"] or {"status": "open", "text_match": None}
    choices = [
        ("ask: show only done ones", {"status": "done", "text_match": base_filters.get("text_match")}, base["intent"], base["date_start"], base["date_end"]),
        ("ask: only " + task, {"status": base_filters.get("status"), "text_match": task}, "search", base["date_start"], base["date_end"]),
        ("ask: show all of them", {"status": None, "text_match": base_filters.get("text_match")}, base["intent"], base["date_start"], base["date_end"]),
        ("ask: only from yesterday", {"status": base_filters.get("status"), "text_match": base_filters.get("text_match")}, base["intent"], yest_iso, yest_iso),
    ]
    inp, new_filters, new_intent, ds, de = rng.choice(choices)
    out = parse_followup_query_accept(
        domain="todo", intent=new_intent, filters=new_filters,
        date_start=ds, date_end=de,
        limit=base["limit"], query_text=base["query_text"],
    )
    return {"anchor_date": anchor, "context": base, "input": inp, "output": out}


def _followup_weight(anchor: str, mode: str, rng: random.Random) -> dict:
    base = _accept_base_query(make_weight_query, anchor, mode, rng)["output"]
    person = pick_name(mode, rng)
    last_month_range = anchor_last_month(anchor)
    six_mo = anchor_six_months_window(anchor)
    base_filters = base["filters"] or {"person_text": "self"}
    choices = [
        ("ask: just latest", {"person_text": base_filters.get("person_text")}, "latest", None, None, None),
        ("ask: only from last month", {"person_text": base_filters.get("person_text")}, "history", last_month_range[0], last_month_range[1], base["limit"]),
        ("ask: only " + person, {"person_text": person}, "latest", None, None, None),
        ("ask: show trend instead", {"person_text": base_filters.get("person_text")}, "trend", six_mo[0], six_mo[1], None),
    ]
    inp, new_filters, new_intent, ds, de, lim = rng.choice(choices)
    out = parse_followup_query_accept(
        domain="weight", intent=new_intent, filters=new_filters,
        date_start=ds, date_end=de,
        limit=lim, query_text=None,
    )
    return {"anchor_date": anchor, "context": base, "input": inp, "output": out}


def _followup_ledger(anchor: str, mode: str, rng: random.Random) -> dict:
    base = _accept_base_query(make_ledger_query, anchor, mode, rng)["output"]
    person = pick_name(mode, rng)
    base_filters = base["filters"] or {"person_text": None, "perspective": None, "status": None}
    choices = [
        ("ask: show entries for that",
         {"person_text": base_filters.get("person_text"), "perspective": base_filters.get("perspective"), "status": base_filters.get("status")},
         "list"),
        ("ask: only " + person,
         {"person_text": person, "perspective": base_filters.get("perspective"), "status": base_filters.get("status")},
         base["intent"]),
        ("ask: only people who owe me",
         {"person_text": base_filters.get("person_text"), "perspective": "they_owe_me", "status": "open"},
         "summary"),
        ("ask: only open ones",
         {"person_text": base_filters.get("person_text"), "perspective": base_filters.get("perspective"), "status": "open"},
         base["intent"]),
    ]
    inp, new_filters, new_intent = rng.choice(choices)
    out = parse_followup_query_accept(
        domain="ledger", intent=new_intent, filters=new_filters,
        date_start=base["date_start"], date_end=base["date_end"],
        limit=base["limit"], query_text=base["query_text"],
    )
    return {"anchor_date": anchor, "context": base, "input": inp, "output": out}


def _followup_note(anchor: str, mode: str, rng: random.Random) -> dict:
    base = _accept_base_query(make_note_query, anchor, mode, rng)["output"]
    topic = pick_topic(mode, rng)
    yest_iso = anchor_yesterday(anchor)
    sun_iso = options_for(anchor)["single"]["last sunday"]
    this_month = anchor_this_month(anchor)
    choices = [
        ("ask: only yesterday", {}, "search", yest_iso, yest_iso, base["query_text"]),
        ("ask: only from last sunday", {}, "list", sun_iso, sun_iso, None),
        ("ask: show the latest note instead", {}, "latest", None, None, None),
        ("ask: only about " + topic, {}, "search", base["date_start"], base["date_end"], topic),
        ("ask: only from current month", {}, "list", this_month[0], this_month[1], base["query_text"]),
    ]
    inp, new_filters, new_intent, ds, de, qt = rng.choice(choices)
    out = parse_followup_query_accept(
        domain="note", intent=new_intent, filters=new_filters,
        date_start=ds, date_end=de,
        query_text=qt,
    )
    return {"anchor_date": anchor, "context": base, "input": inp, "output": out}


def _followup_cross_domain(anchor: str, mode: str, rng: random.Random) -> dict:
    """2026-05-09: cross-domain followup. Train the model that when the user
    asks a clearly different domain question, the prior `context` should be
    DISCARDED — output `task: parse_query` (NOT parse_followup_query) with
    no inheritance.

    Without these rows, the followup dataset is 100% same-domain and biases
    the model toward over-inheriting. The model would then emit Frankenstein
    outputs like `expense + person_text:jeevi` when the user types
    `ask: total expense` then switches to `ask: jeevi weight`.
    """
    DOMAIN_MAKERS = {
        "expense": make_expense_query,
        "buy":     make_buy_query,
        "todo":    make_todo_query,
        "weight":  make_weight_query,
        "ledger":  make_ledger_query,
        "note":    make_note_query,
    }
    domains = list(DOMAIN_MAKERS.keys())
    ctx_domain = rng.choice(domains)
    cur_domain = rng.choice([d for d in domains if d != ctx_domain])
    ctx_row = _accept_base_query(DOMAIN_MAKERS[ctx_domain], anchor, mode, rng)
    cur_row = _accept_base_query(DOMAIN_MAKERS[cur_domain], anchor, mode, rng)
    return {
        "anchor_date": anchor,
        "context": ctx_row["output"],
        "input": cur_row["input"],
        # KEY DIFFERENCE: output is `parse_query` (a fresh query, not a
        # followup). The implicit message: prior context is discarded.
        # This is the entire signal the model needs to learn "switch
        # domain → ignore context".
        "output": cur_row["output"],
    }


def make_followup(anchor: str, mode: str, rng: random.Random) -> dict:
    # 2026-05-09: 25% of followup rows are now cross-domain context-discard
    # cases. Trains the model that when the new question is clearly a
    # different domain, ignore the prior context and emit a fresh
    # `parse_query` instead of `parse_followup_query`. Without this, the
    # 100% same-domain followup dataset biased the model toward
    # always-inherit, which produced cross-domain hallucination during
    # device dogfood.
    if rng.random() < 0.25:
        return _followup_cross_domain(anchor, mode, rng)
    domain = weighted_choice(FOLLOWUP_DOMAIN_WEIGHTS, rng)
    if domain == "expense":
        return _followup_expense(anchor, mode, rng)
    if domain == "buy":
        return _followup_buy(anchor, mode, rng)
    if domain == "todo":
        return _followup_todo(anchor, mode, rng)
    if domain == "weight":
        return _followup_weight(anchor, mode, rng)
    if domain == "ledger":
        return _followup_ledger(anchor, mode, rng)
    return _followup_note(anchor, mode, rng)


# ---------------------------------------------------------------------------
# Generation drivers
# ---------------------------------------------------------------------------

def _pick_anchor_and_mode(rng: random.Random) -> tuple[str, str]:
    return pick_anchor_iso(rng), ("india" if rng.random() < 0.7 else "global")


def generate_lane_rows(
    count: int,
    maker,
    rng: random.Random,
    label: str,
) -> list[dict]:
    """Generate `count` unique rows from `maker(anchor, mode, rng)`. Falls
    back to soft uniqueness (allowing repeats) once the unique capacity is
    exhausted, to mirror v1's UNIQUENESS_POLICY = "soft" behavior."""
    rows: list[dict] = []
    seen: set[str] = set()
    stale = 0
    max_stale = max(10000, count * 50)
    while len(rows) < count:
        anchor, mode = _pick_anchor_and_mode(rng)
        row = maker(anchor, mode, rng)
        key = canonical_row(row)
        if key in seen:
            stale += 1
            if stale >= max_stale:
                # Fall back to allowing repeats.
                rows.append(row)
                continue
            continue
        seen.add(key)
        rows.append(row)
        stale = 0
    rng.shuffle(rows)
    return rows


def generate_adversarial_pairs(
    pair_count: int,
    rng: random.Random,
) -> list[dict]:
    """Generate `pair_count` adversarial pairs. Each pair contributes 2
    consecutive rows to the output list so the pairing survives any
    downstream shuffling at the lane level. We do NOT shuffle the result
    here so pairs stay adjacent in the output file."""
    rows: list[dict] = []
    for _ in range(pair_count):
        anchor, mode = _pick_anchor_and_mode(rng)
        pair = make_adversarial_pair(anchor, mode, rng)
        rows.extend(pair)
    return rows


# ---------------------------------------------------------------------------
# Output / IO
# ---------------------------------------------------------------------------

def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def canonical_row(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# --report
# ---------------------------------------------------------------------------

def report_assets() -> None:
    # v2-aware report. v1 lookups stay so we can compare against v1 numbers.
    report: dict[str, object] = {}
    report["v2_anchor_months"] = [f"{y:04d}-{m:02d}" for y, m in ANCHOR_MONTHS]
    report["v2_anchor_month_count"] = len(ANCHOR_MONTHS)
    report["v2_anchor_day_strategy"] = (
        "randomized per row, uniform within the anchor month"
    )
    # Backward-compat: representative day=15 anchors for the per-month option
    # snapshot below.
    report["v2_anchors_representative"] = ANCHORS
    report["v2_out_dir"] = str(OUT_DIR)
    report["v2_counts"] = {
        "write_per_lane": WRITE_COUNT,
        "query_per_domain": QUERY_COUNT,
        "followup": FOLLOWUP_COUNT,
        "reference": REFERENCE_COUNT,
        "adversarial_pairs": ADVERSARIAL_PAIR_COUNT,
        "action_clarify_rows": ACTION_CLARIFY_COUNT,
        "multi_person_reject_rows": MULTI_PERSON_REJECT_COUNT,
    }

    report["assets"] = {
        "india_names": len(INDIA_NAMES),
        "global_names": len(GLOBAL_NAMES),
        "india_note_topics": len(INDIA_NOTE_TOPICS),
        "global_note_topics": len(GLOBAL_NOTE_TOPICS),
        "india_expense_groups": len(INDIA_EXPENSE),
        "india_expense_items_total": sum(len(v) for v in INDIA_EXPENSE.values()),
        "global_expense_groups": len(GLOBAL_EXPENSE),
        "global_expense_items_total": sum(len(v) for v in GLOBAL_EXPENSE.values()),
        "india_buy_items": len(INDIA_BUY),
        "global_buy_items": len(GLOBAL_BUY),
        "india_todo_actions": len(INDIA_TODOS),
        "india_todo_nouns": len(INDIA_TODO_NOUNS),
        "global_todo_actions": len(GLOBAL_TODOS),
        "global_todo_nouns": len(GLOBAL_TODO_NOUNS),
        "single_date_options_v1_pool": len(SINGLE_DATE_OPTIONS),
        "range_options_v1_pool": len(RANGE_OPTIONS),
        "tanglish_single_date_keys_blocked_in_queries": sorted(TANGLISH_SINGLE_DATE_KEYS),
        "tanglish_range_keys_blocked_in_queries": sorted(TANGLISH_RANGE_KEYS),
    }

    # Per-anchor option counters. With per-row randomized day, we sample one
    # representative anchor per month (day=15) so this section stays bounded
    # and comparable across runs.
    per_anchor: dict[str, dict] = {}
    for anchor in ANCHORS:
        opts = options_for(anchor)
        per_anchor[anchor] = {
            "single_total": len(opts["single"]),
            "range_total": len(opts["range"]),
            "query_safe_singles": len(query_safe_single_keys(anchor)),
            "query_safe_ranges": len(query_safe_range_keys(anchor)),
            "todo_write_singles": len(opts["todo_write_single"]),
            "todo_write_ranges": len(opts["todo_write_range"]),
            "today": opts["single"]["today"],
            "yesterday": opts["single"]["yesterday"],
            "tomorrow": opts["single"]["tomorrow"],
            "this_week": opts["range"]["this week"],
            "last_month": opts["range"]["last month"],
        }
    report["v2_per_anchor_options"] = per_anchor

    # Form weight tables (sanity check that they sum to ~100 modulo small drift).
    form_weight_totals: dict[str, float] = {}
    for lane, weights in LANE_FORM_WEIGHTS.items():
        form_weight_totals[lane] = round(sum(weights.values()), 2)
    report["v2_lane_form_weight_totals"] = form_weight_totals
    report["v2_scoped_share"] = SCOPED_SHARE
    report["v2_pattern_a_share"] = PATTERN_A_SHARE
    report["v2_pattern_b_share"] = PATTERN_B_SHARE

    # Slice rate sanity.
    report["v2_slice_rates"] = {
        "search_typo_rate": SEARCH_TYPO_RATE,
        "bare_nameless_rate": BARE_NAMELESS_RATE,
        "date_breadth_canonical": DATE_BREADTH_CANONICAL,
        "date_breadth_random_key": DATE_BREADTH_RANDOM_KEY,
        "date_breadth_absolute": DATE_BREADTH_ABSOLUTE,
    }

    report["v2_generators_implemented"] = {
        "parse_write": True,
        "parse_query": True,
        "parse_followup_query": True,
        "adversarial_pairs": True,
        "action_clarify": True,
        "multi_person_compare_reject": True,
    }

    # parse_write reject pool sizes (Section 6).
    report["v2_parse_write_reject_pools"] = {
        "expense_desc_only": sum(len(v) for v in INDIA_EXPENSE.values()) + sum(len(v) for v in GLOBAL_EXPENSE.values()),
        "expense_invalid_lane": len(INDIA_TODOS) + len(GLOBAL_TODOS),
        "buy_incomplete": len(BUY_INCOMPLETE_FRAGMENTS),
        "buy_invalid_lane_pool_size": len([t for t in INDIA_TODOS + GLOBAL_TODOS if any(t.startswith(p) for p in _BUY_INVALID_LANE_PREFIXES)]),
        "todo_incomplete": len(TODO_INCOMPLETE_FRAGMENTS),
        "weight_invalid_lane_static": len(WEIGHT_INVALID_LANE_FRAGMENTS),
    }

    # parse_write surface template counts.
    report["v2_parse_write_template_counts"] = {
        "expense_write_patterns": len(EXPENSE_WRITE_PATTERNS),
        "expense_natural_patterns": len(EXPENSE_NATURAL_PATTERNS),
        "expense_tanglish_a_patterns": len(EXPENSE_TANGLISH_A_PATTERNS),
        "buy_prefix_patterns": len(BUY_PREFIX_PATTERNS),
        "buy_triple_patterns": len(BUY_TRIPLE_PATTERNS),
        "todo_time_hint_patterns": len(TODO_TIME_HINT_PATTERNS),
        "todo_pattern_b_verbs": len(TODO_PATTERN_B_VERBS),
        "todo_pattern_b_dative_prefixes": len(TODO_PATTERN_B_DATIVE_PREFIXES),
        "todo_pattern_b_objects": len(TODO_PATTERN_B_OBJECTS),
    }

    # Smoke sample: 500 rows per write lane to verify disposition / pattern
    # ratios. Uses a separate RNG seeded deterministically so the smoke does
    # not perturb the main generation seed.
    smoke_rng = random.Random(SEED + 1)
    smoke_sample_size = 500
    write_makers = {
        "expense": make_expense_write,
        "buy": make_buy_write,
        "todo": make_todo_write,
        "weight": make_weight_write,
        "ledger": make_ledger_write,
    }
    smoke: dict[str, dict] = {}
    for lane, maker in write_makers.items():
        anchor_counts: Counter = Counter()
        disp_counts: Counter = Counter()
        reason_counts: Counter = Counter()
        ledger_note_present = 0
        tanglish_dates_in_writes = 0
        pattern_b_count = 0
        for _ in range(smoke_sample_size):
            anchor = pick_anchor_iso(smoke_rng)
            mode = "india" if smoke_rng.random() < 0.7 else "global"
            row = maker(anchor, mode, smoke_rng)
            anchor_counts[row["anchor_date"]] += 1
            disp_counts[row["output"]["disposition"]] += 1
            reason_counts[row["output"].get("reason_code")] += 1
            if lane == "ledger":
                for rec in row["output"]["records"]:
                    if rec.get("note") is not None:
                        ledger_note_present += 1
            if lane == "todo":
                lowered = row["input"].lower()
                if any(verb in lowered for verb in ("pannanum", "kattanum", "podanum", "vaanganum", "kudukkanum")):
                    pattern_b_count += 1
                for tk in TANGLISH_SINGLE_DATE_KEYS | TANGLISH_RANGE_KEYS:
                    if tk in lowered:
                        tanglish_dates_in_writes += 1
                        break
        smoke[lane] = {
            "n": smoke_sample_size,
            "by_anchor": dict(anchor_counts),
            "by_disposition": dict(disp_counts),
            "by_reason_code": {str(k): v for k, v in reason_counts.items()},
        }
        if lane == "ledger":
            smoke[lane]["ledger_note_field_nonnull_count"] = ledger_note_present
        if lane == "todo":
            smoke[lane]["pattern_b_rows_observed"] = pattern_b_count
            smoke[lane]["pattern_b_rows_with_tanglish_date"] = tanglish_dates_in_writes
    report["v2_parse_write_smoke_500"] = smoke

    # parse_query template counts.
    template_pools = {
        "note_latest": NOTE_LATEST_TEMPLATES, "note_list_recent": NOTE_LIST_RECENT_TEMPLATES,
        "note_list_absolute": NOTE_LIST_ABSOLUTE_TEMPLATES, "note_search": NOTE_SEARCH_TEMPLATES,
        "expense_total": EXPENSE_TOTAL_TEMPLATES, "expense_list": EXPENSE_LIST_TEMPLATES,
        "expense_today": EXPENSE_TODAY_TEMPLATES, "expense_group": EXPENSE_GROUP_TEMPLATES,
        "expense_desc": EXPENSE_DESC_TEMPLATES, "expense_recent": EXPENSE_RECENT_TEMPLATES,
        "expense_last_month": EXPENSE_LAST_MONTH_TEMPLATES, "expense_exclude": EXPENSE_EXCLUDE_TEMPLATES,
        "expense_compare": EXPENSE_COMPARE_TEMPLATES, "expense_history": EXPENSE_HISTORY_TEMPLATES,
        "buy_list": BUY_LIST_TEMPLATES, "buy_search": BUY_SEARCH_TEMPLATES,
        "buy_today": BUY_TODAY_TEMPLATES, "buy_date": BUY_DATE_TEMPLATES, "buy_all": BUY_ALL_TEMPLATES,
        "todo_list_open": TODO_LIST_OPEN_TEMPLATES, "todo_today": TODO_TODAY_TEMPLATES,
        "todo_search": TODO_SEARCH_TEMPLATES, "todo_all": TODO_ALL_TEMPLATES,
        "todo_due_week": TODO_DUE_WEEK_TEMPLATES, "todo_history": TODO_HISTORY_TEMPLATES,
        "todo_done_today": TODO_DONE_TODAY_TEMPLATES,
        "weight_latest": WEIGHT_LATEST_TEMPLATES, "weight_history": WEIGHT_HISTORY_TEMPLATES,
        "weight_trend": WEIGHT_TREND_TEMPLATES, "weight_change": WEIGHT_CHANGE_TEMPLATES,
        "weight_latest_all": WEIGHT_LATEST_ALL_TEMPLATES, "weight_date": WEIGHT_DATE_TEMPLATES,
        "ledger_summary": LEDGER_SUMMARY_TEMPLATES,
        "ledger_balance_neutral": LEDGER_BALANCE_NEUTRAL_TEMPLATES,
        "ledger_balance_i_owe": LEDGER_BALANCE_I_OWE_TEMPLATES,
        "ledger_balance_they_owe": LEDGER_BALANCE_THEY_OWE_TEMPLATES,
        "ledger_person": LEDGER_PERSON_TEMPLATES, "ledger_who": LEDGER_WHO_TEMPLATES,
        "ledger_recent": LEDGER_RECENT_TEMPLATES, "ledger_range": LEDGER_RANGE_TEMPLATES,
        "ledger_search": LEDGER_SEARCH_TEMPLATES, "ledger_latest": LEDGER_LATEST_TEMPLATES,
    }
    template_counts: dict[str, dict[str, int]] = {}
    for name, pool in template_pools.items():
        template_counts[name] = {style: len(items) for style, items in pool.items()}
        template_counts[name]["total"] = sum(len(items) for items in pool.values())
    report["v2_parse_query_template_counts"] = template_counts

    # parse_query smoke: 1000 rows per domain. Now tracks dispositions and
    # slice counters too (clarify on ledger, reject on weight).
    query_makers = {
        "note": make_note_query,
        "expense": make_expense_query,
        "buy": make_buy_query,
        "todo": make_todo_query,
        "weight": make_weight_query,
        "ledger": make_ledger_query,
    }
    query_smoke: dict[str, dict] = {}
    smoke_n = 1000
    for domain, maker in query_makers.items():
        intent_counts: Counter = Counter()
        disposition_counts: Counter = Counter()
        scoped_count = 0
        tanglish_in_input = 0
        for _ in range(smoke_n):
            anchor = pick_anchor_iso(smoke_rng)
            mode = "india" if smoke_rng.random() < 0.7 else "global"
            row = maker(anchor, mode, smoke_rng)
            intent_counts[str(row["output"]["intent"])] += 1
            disposition_counts[row["output"]["disposition"]] += 1
            text_l = row["input"].lower()
            if text_l.startswith(f"ask: {domain}:"):
                scoped_count += 1
            for tk in TANGLISH_RANGE_KEYS | TANGLISH_SINGLE_DATE_KEYS:
                if tk in text_l:
                    tanglish_in_input += 1
                    break
        query_smoke[domain] = {
            "n": smoke_n,
            "by_intent": dict(intent_counts),
            "by_disposition": dict(disposition_counts),
            "scoped_share": round(scoped_count / smoke_n, 3),
            "tanglish_date_in_query_input": tanglish_in_input,  # MUST be 0
        }
    report["v2_parse_query_smoke_1000"] = query_smoke

    # §5 slice smoke: project the §5.5/§5.6 row counts to a 4000-row lane,
    # plus an adversarial pair smoke.
    weight_smoke = query_smoke["weight"]
    ledger_smoke = query_smoke["ledger"]
    projected = {
        "weight_multi_person_reject_in_4000": int(round(weight_smoke["by_disposition"].get("reject", 0) * 4)),
        "ledger_action_clarify_in_4000": int(round(ledger_smoke["by_disposition"].get("clarify", 0) * 4)),
    }
    report["v2_slice_projection"] = projected

    # Typo and bare-nameless smoke. Re-generate a controlled sample.
    search_rows: list[dict] = []
    for _ in range(2000):
        anchor = pick_anchor_iso(smoke_rng)
        mode = "india" if smoke_rng.random() < 0.7 else "global"
        # Drive each search lane evenly.
        kind = smoke_rng.choice(["note", "expense_desc", "buy_search", "todo_search"])
        if kind == "note":
            r = make_note_query(anchor, mode, smoke_rng)
            if r["output"]["intent"] == "search":
                search_rows.append(("note", r))
        elif kind == "expense_desc":
            r = make_expense_query(anchor, mode, smoke_rng)
            if r["output"]["filters"].get("description_text"):
                search_rows.append(("expense_desc", r))
        elif kind == "buy_search":
            r = make_buy_query(anchor, mode, smoke_rng)
            if r["output"]["intent"] == "search":
                search_rows.append(("buy", r))
        else:
            r = make_todo_query(anchor, mode, smoke_rng)
            if r["output"]["intent"] == "search":
                search_rows.append(("todo", r))
    typo_counts = Counter()
    typo_totals = Counter()
    bare_counts = Counter()
    for kind, r in search_rows:
        typo_totals[kind] += 1
        out = r["output"]
        # Look at the asset-bearing field per lane.
        canonical_pool: list[str]
        actual: str | None
        if kind == "note":
            actual = out.get("query_text")
            canonical_pool = INDIA_NOTE_TOPICS + GLOBAL_NOTE_TOPICS
        elif kind == "expense_desc":
            actual = out["filters"].get("description_text")
            canonical_pool = []
            for cat in INDIA_EXPENSE.values():
                canonical_pool.extend(cat)
            for cat in GLOBAL_EXPENSE.values():
                canonical_pool.extend(cat)
        elif kind == "buy":
            actual = out["filters"].get("item_text")
            canonical_pool = INDIA_BUY + GLOBAL_BUY
        else:  # todo
            actual = out["filters"].get("text_match")
            canonical_pool = INDIA_TODOS + GLOBAL_TODOS + INDIA_TODO_NOUNS + GLOBAL_TODO_NOUNS
        if actual and actual not in canonical_pool:
            typo_counts[kind] += 1
    report["v2_typo_smoke"] = {
        "by_lane_search_n": dict(typo_totals),
        "by_lane_typo_observed": dict(typo_counts),
        "rates": {k: (round(typo_counts[k] / typo_totals[k], 3) if typo_totals[k] else 0.0)
                  for k in typo_totals},
        "target_rate": SEARCH_TYPO_RATE,
    }

    # Bare-nameless smoke per applicable form.
    bare_pools = {
        "weight_latest": (set(WEIGHT_LATEST_BARE), make_weight_query, "latest"),
        "expense_total": (set(EXPENSE_TOTAL_BARE), make_expense_query, "total"),
        "buy_list": (set(BUY_LIST_BARE), make_buy_query, "list"),
        "todo_list_open": (set(TODO_LIST_OPEN_BARE), make_todo_query, "list"),
        "ledger_summary": (set(LEDGER_SUMMARY_BARE), make_ledger_query, "summary"),
    }
    bare_smoke: dict[str, dict] = {}
    for label, (pool, maker, expect_intent) in bare_pools.items():
        n_total = 0
        n_bare = 0
        for _ in range(2000):
            a = pick_anchor_iso(smoke_rng)
            m = "india" if smoke_rng.random() < 0.7 else "global"
            r = maker(a, m, smoke_rng)
            if r["output"]["intent"] != expect_intent:
                continue
            n_total += 1
            stripped = r["input"]
            if stripped.startswith("ask: "):
                stripped = stripped[len("ask: "):]
            if stripped.startswith(f"{label.split('_')[0]}: "):
                stripped = stripped[len(f"{label.split('_')[0]}: "):]
            if stripped.strip() in pool:
                n_bare += 1
        bare_smoke[label] = {
            "n": n_total,
            "bare": n_bare,
            "rate": round(n_bare / n_total, 3) if n_total else 0.0,
        }
    report["v2_bare_nameless_smoke"] = bare_smoke
    report["v2_bare_nameless_target_rate"] = BARE_NAMELESS_RATE

    # Adversarial smoke.
    adversarial_pair_kinds = Counter()
    adversarial_n = 200
    adversarial_distinct_persons: set[str] = set()
    adversarial_violations = 0
    for _ in range(adversarial_pair_kinds.most_common(0) and 0 or adversarial_n):
        a = pick_anchor_iso(smoke_rng)
        m = "india" if smoke_rng.random() < 0.7 else "global"
        pair = make_adversarial_pair(a, m, smoke_rng)
        if len(pair) != 2:
            adversarial_violations += 1
            continue
        weight_row, other_row = pair
        if weight_row["output"]["domain"] != "weight":
            adversarial_violations += 1
        kind = other_row["output"]["domain"]
        adversarial_pair_kinds[kind] += 1
        # The same person should appear in both inputs (substring match).
        # Person name is whatever appears after `ask: `.
        for_inp = weight_row["input"].lower()
        other_inp = other_row["input"].lower()
        # We don't have the person name explicitly, so check via filter
        # fields where applicable.
        person_field = (
            other_row["output"]["filters"].get("person_text")
            or other_row["output"]["filters"].get("text_match")
            or other_row["output"].get("query_text")
        )
        if person_field:
            if isinstance(person_field, str):
                base_person = person_field.replace("call ", "")
                adversarial_distinct_persons.add(base_person)
                if base_person.lower() not in for_inp or base_person.lower() not in other_inp:
                    adversarial_violations += 1
    report["v2_adversarial_smoke"] = {
        "pairs_generated": adversarial_n,
        "by_pair_kind": dict(adversarial_pair_kinds),
        "distinct_persons_seen": len(adversarial_distinct_persons),
        "violations": adversarial_violations,
        "target_pair_count": ADVERSARIAL_PAIR_COUNT,
    }

    # Followup smoke.
    fu_domain_counts: Counter = Counter()
    fu_intent_counts: Counter = Counter()
    fu_disposition_counts: Counter = Counter()
    fu_anchor_counts: Counter = Counter()
    fu_violations = 0
    fu_n = 1000
    for _ in range(fu_n):
        a = pick_anchor_iso(smoke_rng)
        m = "india" if smoke_rng.random() < 0.7 else "global"
        row = make_followup(a, m, smoke_rng)
        fu_anchor_counts[row["anchor_date"]] += 1
        fu_domain_counts[row["output"]["domain"]] += 1
        fu_intent_counts[str(row["output"]["intent"])] += 1
        fu_disposition_counts[row["output"]["disposition"]] += 1
        # Schema invariants.
        out = row["output"]
        if (out["task"] != "parse_followup_query"
                or out.get("inherit_context") is not True
                or out["disposition"] != "accept"
                or out["reason_code"] is not None
                or out["clarify_reason"] is not None
                or out["clarify_options"] is not None
                or "context" not in row
                or "input" not in row):
            fu_violations += 1
    report["v2_parse_followup_smoke_1000"] = {
        "n": fu_n,
        "by_domain": dict(fu_domain_counts),
        "by_intent": dict(fu_intent_counts),
        "by_disposition": dict(fu_disposition_counts),
        "by_anchor": dict(fu_anchor_counts),
        "violations": fu_violations,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Generation entrypoint (stub for checkpoint 1)
# ---------------------------------------------------------------------------

def generate_dataset(
    out_dir: Path = OUT_DIR,
    write_count: int = WRITE_COUNT,
    query_count: int = QUERY_COUNT,
    followup_count: int = FOLLOWUP_COUNT,
    adversarial_pair_count: int = ADVERSARIAL_PAIR_COUNT,
) -> None:
    """Full v2 generation entrypoint.

    Layout:
      <out_dir>/
        parse_write/{expense,buy,todo,weight,ledger}.jsonl
        parse_query/{note,expense,buy,todo,weight,ledger}.jsonl
        parse_query/adversarial.jsonl
        parse_followup_query/mixed_followups.jsonl

    Per docs/model-training.md, the v2 layout omits reference_only/. The
    deterministic note-write bypass stays out of SFT and does not need
    synthetic rows.

    Every row has a top-level "anchor_date" key carrying the row's anchor
    (one of ANCHORS). Training and evaluation prompts inject the anchor as
    a `Today: <YYYY-MM-DD>` line in the system message (Section 7.2).
    """
    rng = random.Random(SEED)
    if out_dir.exists():
        for p in out_dir.rglob("*"):
            if p.is_file():
                p.unlink()
        for p in sorted([x for x in out_dir.rglob("*") if x.is_dir()], reverse=True):
            if p != out_dir:
                p.rmdir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "parse_write").mkdir(exist_ok=True)
    (out_dir / "parse_query").mkdir(exist_ok=True)
    (out_dir / "parse_followup_query").mkdir(exist_ok=True)

    write_makers = {
        "expense": make_expense_write,
        "buy": make_buy_write,
        "todo": make_todo_write,
        "weight": make_weight_write,
        "ledger": make_ledger_write,
    }
    query_makers = {
        "note": make_note_query,
        "expense": make_expense_query,
        "buy": make_buy_query,
        "todo": make_todo_query,
        "weight": make_weight_query,
        "ledger": make_ledger_query,
    }

    write_rows: dict[str, list[dict]] = {}
    for lane, maker in write_makers.items():
        write_rows[lane] = generate_lane_rows(write_count, maker, rng, f"parse_write/{lane}")

    query_rows: dict[str, list[dict]] = {}
    for domain, maker in query_makers.items():
        query_rows[domain] = generate_lane_rows(query_count, maker, rng, f"parse_query/{domain}")

    adversarial_rows = generate_adversarial_pairs(adversarial_pair_count, rng)
    followup_rows = generate_lane_rows(followup_count, make_followup, rng, "parse_followup_query/mixed_followups")

    for lane, rows in write_rows.items():
        write_jsonl(out_dir / "parse_write" / f"{lane}.jsonl", rows)
    for domain, rows in query_rows.items():
        write_jsonl(out_dir / "parse_query" / f"{domain}.jsonl", rows)
    write_jsonl(out_dir / "parse_query" / "adversarial.jsonl", adversarial_rows)
    write_jsonl(out_dir / "parse_followup_query" / "mixed_followups.jsonl", followup_rows)

    total = (
        write_count * len(write_makers)
        + query_count * len(query_makers)
        + len(adversarial_rows)
        + followup_count
    )
    readme = f"""# Schema-Frozen Dataset v4 (v2 schema)

Generated by `generate_large_schema_frozen_dataset_v2.py`.

Source rules:
- `docs/model-training.md` (canonical)
- `docs/model-training.md` -> "Shared Schema Freeze v2"
- `docs/model-training.md` -> "v2 Amendments"

Anchors (multi-anchor per Section 7.1):
- {", ".join(ANCHORS)}

Each row carries a top-level `anchor_date` key. Training and inference
prompts must inject that anchor as a `Today: <YYYY-MM-DD>` line in the
system message (Section 7.2).

India-context ratio: 70% / global 30%.

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
- parse_query/adversarial.jsonl -> {len(adversarial_rows)}  ({adversarial_pair_count} pairs)
- parse_followup_query/mixed_followups.jsonl -> {followup_count}

Total JSON objects: {total}

reference_only/ is intentionally omitted in v2. The deterministic note-write
bypass stays out of SFT.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="Print v2 asset / template / option counters without generating the dataset.")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Output dataset directory.")
    parser.add_argument("--write-count", type=int, default=WRITE_COUNT, help="Rows per parse_write lane.")
    parser.add_argument("--query-count", type=int, default=QUERY_COUNT, help="Rows per parse_query domain.")
    parser.add_argument("--followup-count", type=int, default=FOLLOWUP_COUNT, help="Rows for parse_followup_query/mixed_followups.")
    args = parser.parse_args()

    if args.report:
        report_assets()
        return

    generate_dataset(
        out_dir=Path(args.out_dir),
        write_count=args.write_count,
        query_count=args.query_count,
        followup_count=args.followup_count,
    )


if __name__ == "__main__":
    main()
