"""
Faithful Python port of `android/app/src/main/java/com/secondbrain/app/parser/ManualParser.kt`.

Goal: let us run the on-device rules engine offline against the v4 dataset
to measure reliability without rebuilding the APK on every iteration.

When the Kotlin file changes, this file MUST be updated in lockstep —
otherwise eval numbers diverge from real device behavior.

Reference: `manual_parser.py.md` is the diff-tracking notes (TBD).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# Expense group inference (V1.1 — sourced from synthetic_dataset_assets.py)
# ─────────────────────────────────────────────────────────────────────────────

_GROUPS_JSON_PATH = os.path.join(os.path.dirname(__file__), "expense_groups_full.json")
_GROUPS = {"items": {}, "words": {}}
if os.path.exists(_GROUPS_JSON_PATH):
    with open(_GROUPS_JSON_PATH, "r", encoding="utf-8") as _f:
        _GROUPS = json.load(_f)


def infer_group(description: str):
    """
    Two-pass lookup:
      1. Exact item-text match (case-insensitive) against the corpus that
         seeded the v4 dataset. Catches in-list items perfectly.
      2. Per-word vote against the same corpus. Most-frequent group wins.
    Falls back to None when nothing in the corpus matches — the runner
    stores null which matches the dataset's `group` shape for unknowns.
    """
    if not description:
        return None
    norm = description.strip().lower()
    items = _GROUPS.get("items", {})
    if norm in items:
        return items[norm]
    # Substring containment for verbose user-typed entries that include
    # extra qualifier words.
    for k, v in items.items():
        if k in norm:
            return v
    # Word-level vote.
    words = _GROUPS.get("words", {})
    votes = {}
    for w in re.split(r"[^a-z0-9]+", norm):
        if len(w) >= 4 and w in words:
            votes[words[w]] = votes.get(words[w], 0) + 1
    if votes:
        return max(votes.items(), key=lambda kv: kv[1])[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tag detection
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_TAGS = {"expense", "buy", "todo", "weight", "ledger", "ask", "note"}


def split_tag(text: str):
    colon = text.find(":")
    if colon <= 0:
        return None
    head = text[:colon].strip().lower()
    if head not in KNOWN_TAGS:
        return None
    return head, text[colon + 1:]


# ─────────────────────────────────────────────────────────────────────────────
# Amounts
# ─────────────────────────────────────────────────────────────────────────────

# Mirrors AMOUNT_RE in ManualParser.kt
AMOUNT_RE = re.compile(
    r"(?:rs\.?\s*|₹\s*|usd\s+|\$\s*)?"
    # `\b` BEFORE the number prevents digits inside `ZEE5`/`1509abc`
    # from being matched as standalone amounts. NO `\b` after — that
    # would block `5k`/`2L` (`5k` is one word, no boundary between
    # digit and `k`).
    r"\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    # Trailing suffix: each option ends with a word boundary so `k`
    # doesn't consume the leading char of `kaasu`/`kasu`, `l` doesn't
    # eat into `lakh`, `lakh` matches `lakh` not `lakhier`.
    r"(?:\s*(?:/-|(?:k|l|crore|crores|lakh|lakhs|thousand|rs\.?|rupees?|₹)\b))?",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
COLON_AMOUNT_RE = re.compile(
    r"([A-Za-z][\w\s'\-]*?)\s*:\s*"
    r"((?:rs\.?\s*|₹\s*|\$\s*)?\d+(?:[\.,]\d+)?\s*"
    r"(?:k|l|crore|crores|lakh|lakhs|thousand)?)",
    re.IGNORECASE,
)
CURRENCY_WORD_RE = re.compile(
    r"(?<!\w)(rs\.?|rupees?|₹|inr|usd|kaasu|kasu)(?!\w)",
    re.IGNORECASE,
)

# V2: extra framing words that decorate expense/buy descriptions without
# adding meaning. Stripped from both ends so `on petrol`/`petrol ku` →
# `petrol`, `purchased X worth 5L` → `X`.
_FRAMING_PREFIX_RE = re.compile(
    r"^\s*(?:on|for|spent|purchased|bought|paid|paid\s+for|worth)\s+",
    re.IGNORECASE,
)
_FRAMING_SUFFIX_RE = re.compile(
    r"\s+(?:ku|kku|le|la|for|worth|"
    r"vaanginen|vaangina|vaaganum|vaanga\s+vendiyathu|"
    r"vanganum|kekanum|book\s+pannanum|"
    r"coming|comming|this|after\s+house\s+warming)\s*$",
    re.IGNORECASE,
)


def strip_framing(s: str) -> str:
    """Strip framing prefixes/suffixes and currency-marker words."""
    prev = None
    cur = s
    # Iterate because suffixes can cascade (`X ku vaanginen`).
    while cur != prev:
        prev = cur
        cur = _FRAMING_PREFIX_RE.sub("", cur)
        cur = _FRAMING_SUFFIX_RE.sub("", cur)
    return strip_currency_words(cur)


def parse_amount(raw: str):
    t = raw.strip().lower()
    for prefix in ("rs.", "rs", "₹", "usd", "$"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    if t.endswith("/-"):
        t = t[:-2].strip()
    m = NUMBER_RE.search(t)
    if not m:
        return None
    base = float(m.group(0).replace(",", ""))
    tail = t[m.end():].strip()
    if tail in ("k", "thousand"):
        return base * 1000.0
    if tail in ("l", "lakh", "lakhs"):
        return base * 100000.0
    if tail in ("crore", "crores"):
        return base * 10000000.0
    return base


def normalize_amount_number(v: float):
    """Mirror Kotlin: keep integers as ints in JSON for clean round-trips."""
    iv = int(v)
    if abs(v - iv) < 1e-9:
        return iv
    return v


def strip_currency_words(s: str) -> str:
    s = CURRENCY_WORD_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(",:;.-").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Dates
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DateRange:
    start: date
    end: date


def this_day(today: date) -> DateRange:
    return DateRange(today, today)


def this_month(today: date) -> DateRange:
    start = today.replace(day=1)
    if today.month == 12:
        end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    return DateRange(start, end)


def last_month(today: date) -> DateRange:
    if today.month == 1:
        anchor = today.replace(year=today.year - 1, month=12, day=1)
    else:
        anchor = today.replace(month=today.month - 1, day=1)
    if anchor.month == 12:
        end = anchor.replace(year=anchor.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = anchor.replace(month=anchor.month + 1, day=1) - timedelta(days=1)
    return DateRange(anchor, end)


def this_week(today: date) -> DateRange:
    # Monday-Sunday week
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return DateRange(monday, sunday)


def last_week(today: date) -> DateRange:
    monday = today - timedelta(days=today.weekday() + 7)
    return DateRange(monday, monday + timedelta(days=6))


def this_year(today: date) -> DateRange:
    return DateRange(date(today.year, 1, 1), date(today.year, 12, 31))


def last_year(today: date) -> DateRange:
    return DateRange(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))


def _next_month(today: date) -> DateRange:
    """Whole-month range of the month AFTER today's month."""
    if today.month == 12:
        start = date(today.year + 1, 1, 1)
        end = date(today.year + 1, 1, 31)
    else:
        start = date(today.year, today.month + 1, 1)
        # Last day of next month: jump one more, subtract one day
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    return DateRange(start, end)


def weekend(today: date) -> DateRange:
    """The upcoming Sat-Sun (or this Sat-Sun if today IS the weekend)."""
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    return DateRange(sat, sat + timedelta(days=1))


# Day-name → Python weekday()
_DAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def next_day(today: date, dow: int) -> DateRange:
    """Strictly future: if today is the same DOW, jump 7 days ahead."""
    delta = (dow - today.weekday()) % 7
    if delta == 0:
        delta = 7
    d = today + timedelta(days=delta)
    return DateRange(d, d)


def last_day(today: date, dow: int) -> DateRange:
    """Strictly past: if today is the same DOW, jump 7 days back."""
    delta = (today.weekday() - dow) % 7
    if delta == 0:
        delta = 7
    d = today - timedelta(days=delta)
    return DateRange(d, d)


def n_days_ago(today: date, n: int) -> DateRange:
    d = today - timedelta(days=n)
    return DateRange(d, d)


# `<month> <ordinal> week` ranges. ordinal: 1..4 (and "last" for week 5/end).
_MONTH_NAMES_LIST = ["january", "february", "march", "april", "may", "june",
                     "july", "august", "september", "october", "november", "december"]
_MONTH_NAMES_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"]
_ORDINALS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "last": 5,
}


def month_week(today: date, month: int, ordinal: int, year: int) -> DateRange:
    """
    `<month> <ordinal> week`. Ordinal 1..4 maps to days 1-7, 8-14, 15-21,
    22-28; ordinal 5 ("last week") maps to day 22 → end-of-month.
    """
    if ordinal == 5:
        start = date(year, month, 22)
        # End of month
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
    else:
        start = date(year, month, 1 + (ordinal - 1) * 7)
        end = date(year, month, ordinal * 7)
    return DateRange(start, end)


def first_half_month(today: date, month: int, year: int) -> DateRange:
    return DateRange(date(year, month, 1), date(year, month, 15))


def second_half_month(today: date, month: int, year: int) -> DateRange:
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return DateRange(date(year, month, 16), end)


# Order matters: longer phrases first.
DATE_RANGE_PHRASES = [
    ("last month", last_month),
    ("this month", this_month),
    ("current month", this_month),
    ("last week", last_week),
    ("this week", this_week),
    ("current week", this_week),
    ("last year", last_year),
    ("this year", this_year),
    ("current year", this_year),
    ("today", this_day),
    ("yesterday", lambda t: this_day(t - timedelta(days=1))),
    ("tomorrow", lambda t: this_day(t + timedelta(days=1))),
]


def extract_date_range_phrase(lower: str, today: date):
    # V2: Tanglish phrases handled FIRST so they don't get partially
    # consumed by English fallback patterns.
    #   pona <day>            → last <day>           (DateRange)
    #   pona maasam           → last month
    #   pona varusham         → last year
    #   indha maasam          → this month
    #   indha varusham        → this year
    #   varum maasam          → next month  (treated as next month range)
    #   nethu / nethaiku      → yesterday
    #   naliku / naalai       → tomorrow
    #   indha kaalaila        → today
    tanglish_simple = [
        ('pona maasam', lambda t: last_month(t)),
        ('pona varusham', lambda t: last_year(t)),
        ('pona varusam', lambda t: last_year(t)),
        ('indha maasam', lambda t: this_month(t)),
        ('indha varusham', lambda t: this_year(t)),
        ('indha varusam', lambda t: this_year(t)),
        ('varum maasam', lambda t: _next_month(t)),
        ('indha kaalaila', lambda t: this_day(t)),
        ('nethaiku', lambda t: this_day(t - timedelta(days=1))),
        ('nethu', lambda t: this_day(t - timedelta(days=1))),
        ('naliku', lambda t: this_day(t + timedelta(days=1))),
        ('naalai', lambda t: this_day(t + timedelta(days=1))),
    ]
    for phrase, fn in tanglish_simple:
        idx = lower.find(phrase)
        if idx >= 0:
            residual = (lower[:idx] + lower[idx + len(phrase):]).strip()
            try:
                rng = fn(today)
                return rng, residual
            except Exception:
                pass

    # Tanglish: pona <day> → last <day>
    m = re.search(r"\bpona\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
    if m:
        dow = list(_DAYS).index(m.group(1))
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return last_day(today, dow), residual

    # Tanglish: varum <day> → next <day>
    m = re.search(r"\bvarum\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
    if m:
        dow = list(_DAYS).index(m.group(1))
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return next_day(today, dow), residual

    # Pass 1: simple canonical phrases (this/last week/month/year/etc.)
    for phrase, fn in DATE_RANGE_PHRASES:
        idx = lower.find(phrase)
        if idx >= 0:
            residual = (lower[:idx] + lower[idx + len(phrase):]).strip()
            return fn(today), residual

    # Pass 2: weekend / wknd
    m = re.search(r"\b(weekend|wknd)\b", lower)
    if m:
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return weekend(today), residual

    # Pass 3: `next <day>` / `last <day>` / `this <day>`
    m = re.search(r"\b(next|last|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
    if m:
        kind, day = m.group(1), m.group(2)
        dow = _DAYS[day]
        if kind == "next":
            rng = next_day(today, dow)
        elif kind == "last":
            rng = last_day(today, dow)
        else:
            # `this <day>` → the upcoming-or-today instance
            delta = (dow - today.weekday()) % 7
            d = today + timedelta(days=delta)
            rng = DateRange(d, d)
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return rng, residual

    # Pass 4: `<n> days ago` / `<n> day ago`
    m = re.search(r"\b(\d+|two|three|four|five|six|seven)\s+days?\s+ago\b", lower)
    if m:
        word_to_n = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        token = m.group(1)
        n = int(token) if token.isdigit() else word_to_n.get(token, 1)
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return n_days_ago(today, n), residual

    # Pass 5: `<month> <ordinal> week` (e.g. `may fourth week`, `july second week`)
    months_pattern = "|".join(_MONTH_NAMES_LIST + _MONTH_NAMES_ABBR)
    ordinals_pattern = "|".join(_ORDINALS.keys())
    m = re.search(rf"\b({months_pattern})\s+({ordinals_pattern})\s+week\b", lower)
    if m:
        month_name, ord_name = m.group(1), m.group(2)
        month = next((i + 1 for i, n in enumerate(_MONTH_NAMES_LIST) if n.startswith(month_name) or month_name.startswith(n[:3])), None)
        if month:
            ordinal = _ORDINALS[ord_name]
            year = today.year
            residual = (lower[:m.start()] + lower[m.end():]).strip()
            return month_week(today, month, ordinal, year), residual

    # Pass 5b: `<ordinal> week` (current month implied)
    m = re.search(rf"\b({ordinals_pattern})\s+week\b", lower)
    if m:
        ordinal = _ORDINALS[m.group(1)]
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return month_week(today, today.month, ordinal, today.year), residual

    # Pass 6: `first/second half of <month>` / `<month> first half`
    m = re.search(rf"\b(first|second)\s+half\s+of\s+({months_pattern})\b", lower)
    if m:
        half_kind, month_name = m.group(1), m.group(2)
        month = next((i + 1 for i, n in enumerate(_MONTH_NAMES_LIST) if n.startswith(month_name) or month_name.startswith(n[:3])), None)
        if month:
            fn = first_half_month if half_kind == "first" else second_half_month
            residual = (lower[:m.start()] + lower[m.end():]).strip()
            return fn(today, month, today.year), residual

    # Pass 7: bare `<month>` name resolves to that month full-range
    m = re.search(rf"\b({months_pattern})\b", lower)
    if m:
        month_name = m.group(1)
        month = next((i + 1 for i, n in enumerate(_MONTH_NAMES_LIST) if n.startswith(month_name) or month_name.startswith(n[:3])), None)
        if month:
            year = today.year
            start = date(year, month, 1)
            if month == 12:
                end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end = date(year, month + 1, 1) - timedelta(days=1)
            residual = (lower[:m.start()] + lower[m.end():]).strip()
            return DateRange(start, end), residual

    # Pass 8: `week close` / `week-end` / `week ending` → upcoming Sunday
    m = re.search(r"\bweek\s+(?:close|end|ending)\b", lower)
    if m:
        sunday = today + timedelta(days=(6 - today.weekday()) % 7)
        residual = (lower[:m.start()] + lower[m.end():]).strip()
        return DateRange(sunday, sunday), residual

    return None, lower


TRAILING_ABSOLUTE_DATE_RE = re.compile(
    r"\s+(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|july|aug|sep|sept|oct|nov|dec)\w*(?:\s+\d{4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|july|aug|sep|sept|oct|nov|dec)\w*\s+\d{1,2}(?:\s+\d{4})?|"
    r"\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?)\s*$",
    re.IGNORECASE,
)

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_absolute_date(raw: str, today: date):
    t = raw.strip().lower()
    # Numeric DD-MM-YYYY / DD/MM
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})(?:[-/](\d{2,4}))?", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = m.group(3) or str(today.year)
        if len(y) == 2:
            y = "20" + y
        try:
            return date(int(y), mo, d)
        except ValueError:
            return None
    # `15 jan` / `15 jan 2026`
    m = re.fullmatch(r"(\d{1,2})\s+(\w+?)(?:\s+(\d{4}))?", t)
    if m:
        d = int(m.group(1))
        mo_name = m.group(2).rstrip(".")
        y = int(m.group(3)) if m.group(3) else today.year
        mo = next((v for k, v in MONTH_NAMES.items() if mo_name.startswith(k)), None)
        if mo is not None:
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    # `jan 15` / `jan 15 2026`
    m = re.fullmatch(r"(\w+?)\s+(\d{1,2})(?:\s+(\d{4}))?", t)
    if m:
        mo_name = m.group(1).rstrip(".")
        d = int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        mo = next((v for k, v in MONTH_NAMES.items() if mo_name.startswith(k)), None)
        if mo is not None:
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    return None


def strip_trailing_date(text: str, today: date):
    """
    Find and strip a trailing date phrase. V2 expansion: also recognizes
    `next/last <day>`, `weekend`, Tanglish (`pona <day>`, `nethu`,
    `naliku`, `innaiku`, `indha kaalaila`, `pona maasam`, etc.) at the
    END of the text.
    """
    lower = text.lower().rstrip()

    # Tanglish single-word dates at end (relative to today).
    tanglish_simple = [
        ("indha kaalaila", today),
        ("innaiku", today),
        ("nethaiku", today - timedelta(days=1)),
        ("nethu", today - timedelta(days=1)),
        ("naalaiku", today + timedelta(days=1)),
        ("naliku", today + timedelta(days=1)),
        ("naalai", today + timedelta(days=1)),
    ]
    for phrase, dt in tanglish_simple:
        if lower.endswith(phrase):
            stripped = text[: len(text) - len(phrase)].strip().rstrip(",;:-").strip()
            return stripped, dt

    # `pona <day>` / `varum <day>` / `next <day>` / `last <day>` / `this <day>`
    m = re.search(
        r"\b(?:pona|last|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        lower,
    )
    if m:
        dow = list(_DAYS).index(m.group(1))
        rng = last_day(today, dow)
        stripped = text[: m.start()].strip().rstrip(",;:-").strip()
        return stripped, rng.start
    m = re.search(
        r"\b(?:varum|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        lower,
    )
    if m:
        dow = list(_DAYS).index(m.group(1))
        rng = next_day(today, dow)
        stripped = text[: m.start()].strip().rstrip(",;:-").strip()
        return stripped, rng.start
    m = re.search(
        r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        lower,
    )
    if m:
        day = m.group(1)
        dow = list(_DAYS).index(day)
        delta = (dow - today.weekday()) % 7
        d = today + timedelta(days=delta)
        stripped = text[: m.start()].strip().rstrip(",;:-").strip()
        return stripped, d

    # `<n> days ago`
    m = re.search(r"\b(\d+|two|three|four|five|six|seven)\s+days?\s+ago\s*$", lower)
    if m:
        word_to_n = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        token = m.group(1)
        n = int(token) if token.isdigit() else word_to_n.get(token, 1)
        stripped = text[: m.start()].strip().rstrip(",;:-").strip()
        return stripped, today - timedelta(days=n)

    # `last/this week|month|year` / `weekend`
    for phrase, fn in [
        ("last week", lambda t: last_week(t)),
        ("last month", lambda t: last_month(t)),
        ("last year", lambda t: last_year(t)),
        ("this week", lambda t: this_week(t)),
        ("this month", lambda t: this_month(t)),
        ("this year", lambda t: this_year(t)),
        ("weekend", lambda t: weekend(t)),
    ]:
        if lower.endswith(phrase):
            rng = fn(today)
            stripped = text[: len(text) - len(phrase)].strip().rstrip(",;:-").strip()
            return stripped, rng.start

    # `pona maasam` / `indha maasam` / `varum maasam` / `pona varusham` etc.
    for phrase, fn in [
        ("pona maasam", lambda t: last_month(t)),
        ("indha maasam", lambda t: this_month(t)),
        ("varum maasam", lambda t: _next_month(t)),
        ("pona varusham", lambda t: last_year(t)),
        ("indha varusham", lambda t: this_year(t)),
    ]:
        if lower.endswith(phrase):
            rng = fn(today)
            stripped = text[: len(text) - len(phrase)].strip().rstrip(",;:-").strip()
            return stripped, rng.start

    # Canonical English single-day phrases.
    for phrase, dt in (
        ("yesterday", today - timedelta(days=1)),
        ("tomorrow", today + timedelta(days=1)),
        ("today", today),
    ):
        if lower.endswith(phrase):
            stripped = text[: len(text) - len(phrase)].strip().rstrip(",;:-").strip()
            return stripped, dt

    m = TRAILING_ABSOLUTE_DATE_RE.search(text)
    if m:
        parsed = parse_absolute_date(m.group(1).strip(), today)
        if parsed is not None:
            stripped = text[: m.start()].strip().rstrip(",;").strip()
            return stripped, parsed
    return text, None


def find_date_range_anywhere(text: str, today: date):
    """
    Like find_date_anywhere but returns a full DateRange. Used by
    queries where the gold output uses date_start/date_end ranges
    (last month = first..last day of month, etc.).
    """
    lower = text.lower()
    for phrase, fn in [
        ("last week", lambda t: last_week(t)),
        ("last month", lambda t: last_month(t)),
        ("last year", lambda t: last_year(t)),
        ("this week", lambda t: this_week(t)),
        ("this month", lambda t: this_month(t)),
        ("this year", lambda t: this_year(t)),
        ("current month", lambda t: this_month(t)),
        ("current week", lambda t: this_week(t)),
        ("current year", lambda t: this_year(t)),
        ("weekend", lambda t: weekend(t)),
        ("pona maasam", lambda t: last_month(t)),
        ("indha maasam", lambda t: this_month(t)),
        ("varum maasam", lambda t: _next_month(t)),
        ("pona varusham", lambda t: last_year(t)),
        ("indha varusham", lambda t: this_year(t)),
    ]:
        if phrase in lower:
            return fn(today)
    d = find_date_anywhere(text, today)
    if d is not None:
        return DateRange(d, d)
    return None


def find_date_anywhere(text: str, today: date):
    """
    Scan the ENTIRE text for a date phrase (Tanglish, English, absolute).
    Used by lanes whose dataset keeps the date phrase IN the record's
    text field (notably todo) — so we set `date` correctly but return
    text unchanged.

    Returns the resolved date or None.
    """
    lower = text.lower()
    # Tanglish single-word dates (anywhere)
    tanglish_simple = [
        ("indha kaalaila", today),
        ("innaiku", today),
        ("nethaiku", today - timedelta(days=1)),
        ("nethu", today - timedelta(days=1)),
        ("naalaiku", today + timedelta(days=1)),
        ("naliku", today + timedelta(days=1)),
        ("naalai", today + timedelta(days=1)),
    ]
    for phrase, dt in tanglish_simple:
        if phrase in lower:
            return dt
    # pona <day>, varum <day>, next/last/this <day>
    m = re.search(r"\b(?:pona|last|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
    if m:
        dow = list(_DAYS).index(m.group(1))
        return last_day(today, dow).start
    m = re.search(r"\b(?:varum|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
    if m:
        dow = list(_DAYS).index(m.group(1))
        return next_day(today, dow).start
    m = re.search(r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
    if m:
        day = m.group(1)
        dow = list(_DAYS).index(day)
        delta = (dow - today.weekday()) % 7
        return today + timedelta(days=delta)
    m = re.search(r"\b(\d+|two|three|four|five|six|seven)\s+days?\s+ago\b", lower)
    if m:
        word_to_n = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        token = m.group(1)
        n = int(token) if token.isdigit() else word_to_n.get(token, 1)
        return today - timedelta(days=n)
    for phrase, fn in [
        ("last week", lambda t: last_week(t)),
        ("last month", lambda t: last_month(t)),
        ("last year", lambda t: last_year(t)),
        ("this week", lambda t: this_week(t)),
        ("this month", lambda t: this_month(t)),
        ("this year", lambda t: this_year(t)),
        ("weekend", lambda t: weekend(t)),
        ("pona maasam", lambda t: last_month(t)),
        ("indha maasam", lambda t: this_month(t)),
        ("varum maasam", lambda t: _next_month(t)),
        ("pona varusham", lambda t: last_year(t)),
        ("indha varusham", lambda t: this_year(t)),
    ]:
        if phrase in lower:
            return fn(today).start
    if "yesterday" in lower:
        return today - timedelta(days=1)
    if "tomorrow" in lower:
        return today + timedelta(days=1)
    if " today" in lower or lower.startswith("today"):
        return today
    # Absolute dates
    m = TRAILING_ABSOLUTE_DATE_RE.search(text)
    if m:
        return parse_absolute_date(m.group(1).strip(), today)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Multi-record split
# ─────────────────────────────────────────────────────────────────────────────

MULTI_SPLIT_RE = re.compile(r"\s*(?:,|;|\||&|\sand\s)\s*")
MULTI_SPLIT_NL_RE = re.compile(r"\s*(?:\r?\n|,|;|\||&|\sand\s)\s*")
# V2: pre-mask `\d,\d` (e.g. `17,628`) so the comma there isn't a record
# separator. Replace the comma with a sentinel that survives the split,
# then restore.
_NUM_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_NUM_COMMA_SENTINEL = "\x00NCOMMA\x00"


def _mask_number_commas(s: str) -> str:
    return _NUM_COMMA_RE.sub(_NUM_COMMA_SENTINEL, s)


def _unmask_number_commas(s: str) -> str:
    return s.replace(_NUM_COMMA_SENTINEL, ",")


def split_multi(body: str):
    masked = _mask_number_commas(body)
    return [_unmask_number_commas(p.strip()) for p in MULTI_SPLIT_RE.split(masked) if p.strip()]


def split_multi_nl(body: str):
    masked = _mask_number_commas(body)
    return [_unmask_number_commas(p.strip()) for p in MULTI_SPLIT_NL_RE.split(masked) if p.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────

def _date_str(d: date) -> str:
    return d.isoformat()


def accept_write(lane: str, records: list) -> dict:
    return {
        "task": "parse_write",
        "lane": lane,
        "disposition": "accept",
        "reason_code": None,
        "records": records,
    }


def confirm_write(lane: str, records: list, reason_code: str) -> dict:
    return {
        "task": "parse_write",
        "lane": lane,
        "disposition": "confirm",
        "reason_code": reason_code,
        "records": records,
    }


def reject(lane, reason_code: str) -> dict:
    return {
        "task": "parse_write",
        "lane": lane or "expense",
        "disposition": "reject",
        "reason_code": reason_code,
        "records": [],
    }


def accept_query(domain, intent, date_start, date_end, filters, limit, query_text):
    return {
        "task": "parse_query",
        "domain": domain,
        "disposition": "accept",
        "intent": intent,
        "date_start": date_start,
        "date_end": date_end,
        "compare_date_start": None,
        "compare_date_end": None,
        "filters": filters,
        "limit": limit,
        "query_text": query_text,
        "reason_code": None,
        "clarify_reason": None,
        "clarify_options": None,
    }


def reject_query(reason_code: str) -> dict:
    return {
        "task": "parse_query",
        "domain": "note",
        "disposition": "reject",
        "intent": None,
        "date_start": None,
        "date_end": None,
        "compare_date_start": None,
        "compare_date_end": None,
        "filters": {},
        "limit": None,
        "query_text": None,
        "reason_code": reason_code,
        "clarify_reason": None,
        "clarify_options": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# String helpers
# ─────────────────────────────────────────────────────────────────────────────

def titleish(s: str) -> str:
    return s[:1].upper() + s[1:].lower() if s else s


# ─────────────────────────────────────────────────────────────────────────────
# Write: expense
# ─────────────────────────────────────────────────────────────────────────────

def parse_expense_write(body: str, today: date) -> dict:
    stripped, shared_date = strip_trailing_date(body, today)
    # V2: if no trailing date found but the body has one embedded, use that.
    if shared_date is None:
        shared_date = find_date_anywhere(body, today)
    parts = split_multi(stripped)
    records = []
    for p in parts:
        rec = parse_single_expense(p, shared_date or today)
        if rec is None:
            return reject("expense", "incomplete_input")
        records.append(rec)
    if not records:
        return reject("expense", "incomplete_input")
    return accept_write("expense", records)


def parse_single_expense(text: str, fallback_date: date):
    trimmed, per_record_date = strip_trailing_date(text, fallback_date)
    rec_date = per_record_date or fallback_date
    cm = COLON_AMOUNT_RE.search(trimmed)
    if cm:
        desc = strip_framing(cm.group(1))
        amt = parse_amount(cm.group(2))
        if amt is None or not desc:
            return None
        return expense_record(desc, amt, rec_date)
    m = AMOUNT_RE.search(trimmed)
    if m is None:
        return None
    # V2: strip a date phrase out of the right-side residual before
    # framing-strip so `Iodex tube for 2,558 weekend` doesn't keep
    # `weekend` glued to the description.
    after_raw, post_date = strip_trailing_date(trimmed[m.end():], fallback_date)
    if post_date is not None:
        rec_date = post_date
    before = strip_framing(trimmed[: m.start()])
    after = strip_framing(after_raw)
    amt = parse_amount(m.group(0))
    if amt is None:
        return None
    if before and not after:
        desc = before
    elif after and not before:
        desc = after
    elif before and after:
        desc = f"{before} {after}"
    else:
        return None
    if not desc:
        return None
    return expense_record(desc, amt, rec_date)


def expense_record(description: str, amount: float, d: date) -> dict:
    return {
        "description": description,
        "amount": normalize_amount_number(amount),
        "date": _date_str(d),
        "group": infer_group(description),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Write: buy
# ─────────────────────────────────────────────────────────────────────────────

QTY_UNIT_TRAILING_RE = re.compile(
    r"\s+(\d+(?:\.\d+)?)\s*(kg|kgs|g|gms|grams|ml|l|ltr|litre|litres|liter|liters|"
    r"pack|packs|packet|packets|dozen|box|bottle|piece|pieces|nos|no)?\s*$",
    re.IGNORECASE,
)
# Unit text normalization to match dataset canonical form.
_UNIT_NORMALIZE = {
    "kgs": "kg", "gms": "g", "grams": "g", "ltr": "L", "litre": "L",
    "litres": "L", "liter": "L", "liters": "L", "packs": "pack",
    "packets": "pack", "packet": "pack",
}


def _norm_unit(u):
    if u is None:
        return None
    low = u.lower()
    return _UNIT_NORMALIZE.get(low, u)


def parse_buy_write(body: str, today: date) -> dict:
    stripped, shared_date = strip_trailing_date(body, today)
    if shared_date is None:
        shared_date = find_date_anywhere(body, today)
    parts = split_multi_nl(stripped)
    records = []
    for p in parts:
        rec = parse_single_buy(p, shared_date or today)
        if rec is None:
            return reject("buy", "incomplete_input")
        records.append(rec)
    if not records:
        return reject("buy", "incomplete_input")
    return accept_write("buy", records)


def parse_single_buy(text: str, fallback_date: date):
    trimmed, per_record_date = strip_trailing_date(text, fallback_date)
    rec_date = per_record_date or fallback_date
    # V1.1: drop leading bullet markers + filler verbs.
    raw = re.sub(r"^[\-\*•\d]+[\.\)]?\s+", "", trimmed.strip())
    raw = re.sub(r"^(?:pick\s+up|get|grab|buy)\s+", "", raw, flags=re.IGNORECASE).strip()
    # V2: trailing day-name (`X wednesday`, `X monday`).
    raw = re.sub(
        r"\s+(?:on\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*$",
        "", raw, flags=re.IGNORECASE,
    ).strip()
    # V2: Tanglish trailing tails (`list la add pannanum`, `vanganum`,
    # `vaanga vendiyathu`, `coming monday`, etc.).
    raw = re.sub(
        r"\s+list\s+(?:la|le)\s+add\s+pann(?:anum|a)\s*$",
        "", raw, flags=re.IGNORECASE,
    ).strip()
    raw = strip_framing(raw).strip()
    if not raw:
        return None
    m = QTY_UNIT_TRAILING_RE.search(raw)
    if m:
        item = raw[: m.start()].strip()
        qty = (m.group(1) or "").strip() or None
        unit = _norm_unit((m.group(2) or "").strip() or None)
        if not item:
            return None
        return buy_record(item, qty, unit, rec_date)
    return buy_record(raw, None, None, rec_date)


def buy_record(item: str, qty, unit, d: date) -> dict:
    return {
        "item_text": item,
        "quantity_text": qty,
        "unit_text": unit,
        "date": _date_str(d),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Write: todo
# ─────────────────────────────────────────────────────────────────────────────

def parse_todo_write(body: str, today: date) -> dict:
    parts = [p.strip() for p in re.split(r"[\n;]", body) if p.strip()]
    # V1.1: comma-split fires when there are ≥2 commas (was: ≥3 parts of
    # ≥3 chars each). The previous heuristic missed `office locker key,
    # collect bike repair 13 feb` which is two commas worth of tasks.
    if len(parts) == 1:
        sole = parts[0]
        comma_parts = [p.strip() for p in sole.split(",") if p.strip()]
        if len(comma_parts) >= 2 and all(len(p) >= 3 for p in comma_parts):
            parts = comma_parts
    records = []
    for p in parts:
        # Strip leading bullet markers (`- ` / `* ` / `• ` / `1. `).
        clean_p = re.sub(r"^[\-\*•\d]+[\.\)]?\s+", "", p)
        # V2: per-record date detection. The dataset keeps the date
        # phrase IN the text field (verbatim) but sets `date` correctly.
        # So we scan the WHOLE record text for a date and don't strip.
        d = find_date_anywhere(clean_p, today)
        cleaned = clean_p.strip()
        if not cleaned:
            return reject("todo", "incomplete_input")
        records.append({"text": cleaned, "date": _date_str(d or today)})
    if not records:
        return reject("todo", "incomplete_input")
    return accept_write("todo", records)


# ─────────────────────────────────────────────────────────────────────────────
# Write: weight
# ─────────────────────────────────────────────────────────────────────────────

def parse_weight_write(body: str, today: date) -> dict:
    stripped, shared_date = strip_trailing_date(body, today)
    if shared_date is None:
        shared_date = find_date_anywhere(body, today)
    parts = split_multi(stripped)
    if len(parts) > 1:
        records = []
        for p in parts:
            rec = parse_single_weight(p, shared_date or today)
            if rec is None:
                return reject("weight", "incomplete_input")
            records.append(rec)
        return accept_write("weight", records)
    # Single record path
    rec = parse_single_weight(stripped, shared_date or today)
    if rec is None:
        return reject("weight", "incomplete_input")
    return accept_write("weight", [rec])


def parse_single_weight(text: str, fallback_date: date):
    inner_stripped, per_record_date = strip_trailing_date(text, fallback_date)
    rec_date = per_record_date or fallback_date
    s = inner_stripped.strip()
    m = NUMBER_RE.search(s)
    if not m:
        return None
    try:
        value = float(m.group(0))
    except ValueError:
        return None
    if value <= 0.0 or value >= 200.0:
        return None
    before = s[: m.start()].strip()
    after = re.sub(r"\bkg\b", "", s[m.end():], flags=re.IGNORECASE).strip().lstrip(",-:").strip()
    person, residual = extract_weight_person_hint(before)
    note = after if after and after.lower() != "kg" else None
    note_final = " ".join([x for x in [residual.strip() or None, note] if x]) or None
    return {
        "person_text": person or "self",
        "value": normalize_amount_number(value),
        "unit": "kg",
        "date": _date_str(rec_date),
        "note": note_final,
    }


def extract_weight_person_hint(before: str):
    cleaned = re.sub(r"\bweight\b", "", before, flags=re.IGNORECASE).strip().lower()
    if not cleaned:
        return "self", ""
    if cleaned in ("my", "i", "me", "myself"):
        return "self", ""
    original = re.sub(r"\bweight\b", "", before, flags=re.IGNORECASE).strip()
    parts = re.split(r"\s+", original)
    first = parts[0]
    if first.lower() == "my":
        return "self", " ".join(parts[1:])
    return first, " ".join(parts[1:])


# ─────────────────────────────────────────────────────────────────────────────
# Write: ledger
# ─────────────────────────────────────────────────────────────────────────────

LEDGER_REPAY_DEBT = [
    "paid back", "repaid", "repay", "settled with",
    # Tanglish: bakki kudutiten (paid the rest), thiruppi kudutiten (returned)
    "bakki kudutiten", "bakki kudutten", "thiruppi kudutiten",
]
LEDGER_COLLECT_CRED = [
    "returned", "paid me back", "gave back",
    # Tanglish: vasooli pannita / vasooli panniten (collected)
    "vasooli pannita", "vasooli panniten", "vasooli pannita",
]
LEDGER_ADD_CREDIT = [
    "gave", "lent", "sent", "advanced", "lent to",
    # Tanglish: kasu kudutiten / kudutiten (gave money to)
    "kasu kudutiten", "kudutiten", "kudutten", "kuduthen",
]
LEDGER_ADD_DEBT = [
    "borrowed from", "got from", "received from", "received", "took from", "owe", "i owe",
    # Tanglish: vaangiten / vaangina / vaanginen (received/borrowed from)
    "vaangiten", "vaangina", "vaanginen", "vaaninen",
]
LEDGER_SETTLE = [
    "settled", "cleared", "closed", "wrote off",
    # Tanglish: account close pannitten / settle pannitten (closed/settled account)
    "account close pannitten", "account close pannina",
    "settle pannitten", "settle pannina",
    "close pannitten", "close pannina",
]

# Postpositional Tanglish patterns:
#   <person> kitta <amount> vaangiten   → received from <person> → add_debt
#   <person> kitta <amount> vasooli pannita → collected from <person> → collect_credit
#   <person> ku <amount> kudutiten      → gave to <person> → add_credit
#   <person> ku <amount> kasu kudutiten → gave money to <person> → add_credit
#   <person> account close pannitten    → settled with <person> → settle
#   <person> ku settle pannitten        → settled with <person> → settle
TANGLISH_LEDGER_PATTERNS = [
    # (regex, action) — first capture group must be person, second must be amount
    (re.compile(r"(\S+)\s+kitta\s+(.+?)\s+(?:vasooli\s+pann(?:ita|iten|inen))", re.IGNORECASE), "collect_credit"),
    (re.compile(r"(\S+)\s+kitta\s+(.+?)\s+(?:vaang(?:iten|ina|inen))", re.IGNORECASE), "add_debt"),
    (re.compile(r"(\S+)\s+kitta\s+(.+?)\s+(?:bakki\s+kudut(?:iten|ten|hen))", re.IGNORECASE), "repay_debt"),
    (re.compile(r"(\S+)\s+ku\s+(?:kasu\s+)?(.+?)\s+(?:kudut(?:iten|ten|hen))", re.IGNORECASE), "add_credit"),
    (re.compile(r"(\S+)\s+(?:account\s+)?close\s+pann(?:itten|ina)", re.IGNORECASE), "settle"),
    (re.compile(r"(\S+)\s+ku\s+settle\s+pann(?:itten|ina)", re.IGNORECASE), "settle"),
]


def parse_ledger_write(body: str, today: date) -> dict:
    stripped, shared_date = strip_trailing_date(body, today)
    parts = split_multi(stripped)
    records = []
    any_ambiguous = False
    for p in parts:
        outcome = parse_single_ledger(p, shared_date or today)
        if outcome is None:
            return reject("ledger", "incomplete_input")
        rec, ambiguous = outcome
        if ambiguous:
            any_ambiguous = True
        records.append(rec)
    if not records:
        return reject("ledger", "incomplete_input")
    if any_ambiguous and len(records) == 1:
        return confirm_write("ledger", records, "ambiguous_direction")
    return accept_write("ledger", records)


def parse_single_ledger(text: str, fallback_date: date):
    cleaned, per_record_date = strip_trailing_date(text, fallback_date)
    rec_date = per_record_date or fallback_date
    lower = cleaned.lower()

    # V2: Tanglish positional patterns try FIRST. They unambiguously
    # encode person, amount, and direction in one shot.
    for pat, action in TANGLISH_LEDGER_PATTERNS:
        m = pat.search(cleaned)
        if m:
            person = titleish(m.group(1))
            if action == "settle":
                return ledger_record(person, "settle", None, rec_date), False
            amt = parse_amount(m.group(2))
            if amt is None:
                continue
            return ledger_record(person, action, amt, rec_date), False

    # V2: `<person> took <amt> from me` → add_credit (they took = I gave)
    m = re.search(r"(\S+)\s+took\s+(.+?)\s+from\s+me\b", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is not None:
            return ledger_record(person, "add_credit", amt, rec_date), False

    # V2: `took <amt> from <person>` (no subject) → add_debt
    m = re.search(r"\btook\s+(.+?)\s+from\s+(\S+)\b", cleaned, re.IGNORECASE)
    if m:
        amt = parse_amount(m.group(1))
        person = titleish(m.group(2))
        if amt is not None:
            return ledger_record(person, "add_debt", amt, rec_date), False

    # V2 Tanglish: `<person> ku <amt> kudukanum` → add_credit
    m = re.search(r"(\S+)\s+ku\s+(.+?)\s+kudukanum\b", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is not None:
            return ledger_record(person, "add_credit", amt, rec_date), False

    # V2: `I paid <person> back <amount>` → repay_debt
    m = re.search(r"\bi\s+paid\s+(\S+)\s+back\s+(.+)", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is not None:
            return ledger_record(person, "repay_debt", amt, rec_date), False

    # V2: `paid <person> back <amount>` (no `I` subject) → repay_debt
    m = re.search(r"\bpaid\s+(\S+)\s+back\s+(.+)", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is not None:
            return ledger_record(person, "repay_debt", amt, rec_date), False

    # V2: `collected <amount> from <person>` → collect_credit
    m = re.search(r"\bcollected\s+(.+?)\s+from\s+(\S+)", cleaned, re.IGNORECASE)
    if m:
        amt = parse_amount(m.group(1))
        person = titleish(m.group(2))
        if amt is not None:
            return ledger_record(person, "collect_credit", amt, rec_date), False

    # V2: `done with <person>` → settle
    m = re.search(r"\bdone\s+with\s+(\S+)", cleaned, re.IGNORECASE)
    if m:
        return ledger_record(titleish(m.group(1)), "settle", None, rec_date), False

    # V2 Tanglish: `<person> ku full kasu kudutiten` → repay_debt (no amount)
    m = re.search(r"(\S+)\s+ku\s+full\s+kasu\s+kudut", cleaned, re.IGNORECASE)
    if m:
        return ledger_record(titleish(m.group(1)), "repay_debt", None, rec_date), False

    # V2 Tanglish: `<person> ku <amount> bakki` → add_debt
    # (Tanglish: "<amount> remaining/owed to <person>")
    m = re.search(r"(\S+)\s+ku\s+(.+?)\s+bakki\b", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is not None:
            return ledger_record(person, "add_debt", amt, rec_date), False

    # V2: `<person> paid me back fully` (no amount) → settle
    if re.search(r"\bpaid\s+me\s+back\s+fully\b", cleaned, re.IGNORECASE):
        # Person token is the first word before "paid me back"
        before = cleaned[:cleaned.lower().find("paid me back")].strip()
        person = before.split()[-1] if before else None
        if person:
            return ledger_record(titleish(person), "settle", None, rec_date), False

    # V2: `paid back <person> fully` → settle
    m = re.search(r"\bpaid\s+back\s+(\S+)\s+fully\b", cleaned, re.IGNORECASE)
    if m:
        return ledger_record(titleish(m.group(1)), "settle", None, rec_date), False

    # V2: `settled <amount> to <person>` → repay_debt
    m = re.search(r"\bsettled\s+(.+?)\s+to\s+(\S+)\b", cleaned, re.IGNORECASE)
    if m:
        amt = parse_amount(m.group(1))
        if amt is not None:
            return ledger_record(titleish(m.group(2)), "repay_debt", amt, rec_date), False

    # X owes me <amt>
    m = re.search(r"(\S+)\s+owes?\s+me\s+(.+)", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is None:
            return None
        return ledger_record(person, "add_credit", amt, rec_date), False

    # I owe X <amt>
    m = re.search(r"i\s+owe\s+(\S+)\s+(.+)", cleaned, re.IGNORECASE)
    if m:
        person = titleish(m.group(1))
        amt = parse_amount(m.group(2))
        if amt is None:
            return None
        return ledger_record(person, "add_debt", amt, rec_date), False

    # settle / close (English keywords + remaining Tanglish settle phrasings)
    for kw in LEDGER_SETTLE:
        idx = lower.find(kw)
        if idx >= 0:
            rest = cleaned[idx + len(kw):].strip()
            tokens_after = rest.split()
            tokens_before = cleaned[:idx].strip().split()
            person = (tokens_after[0] if tokens_after else (tokens_before[-1] if tokens_before else None))
            if not person:
                return None
            return ledger_record(titleish(person), "settle", None, rec_date), False

    for kw in LEDGER_REPAY_DEBT:
        if kw in lower:
            res = extract_person_and_amount(cleaned, kw)
            if res is None:
                return None
            return ledger_record(res[0], "repay_debt", res[1], rec_date), False

    for kw in LEDGER_COLLECT_CRED:
        if kw in lower:
            res = extract_person_and_amount(cleaned, kw)
            if res is None:
                return None
            return ledger_record(res[0], "collect_credit", res[1], rec_date), False

    for kw in LEDGER_ADD_CREDIT:
        if re.search(rf"\b{re.escape(kw)}\b", cleaned, re.IGNORECASE):
            res = extract_person_and_amount(cleaned, kw)
            if res is None:
                return None
            return ledger_record(res[0], "add_credit", res[1], rec_date), False

    for kw in LEDGER_ADD_DEBT:
        if kw in lower:
            res = extract_person_and_amount(cleaned, kw)
            if res is None:
                return None
            return ledger_record(res[0], "add_debt", res[1], rec_date), False

    # V2: bare `<person> <amount>` with no action verb → reject (matches
    # dataset gold: `Badri 4295` returns disposition=reject, not confirm).
    # The ambiguous-direction path is reserved for inputs that DO have
    # a verb but the direction is unclear (e.g. `gave Yusuf 613.81`
    # without an `I` subject — still triggers an LEDGER_ADD_CREDIT match
    # earlier and returns accept).
    return None


def extract_person_and_amount(text: str, keyword: str):
    am = AMOUNT_RE.search(text)
    if not am:
        return None
    amt = parse_amount(am.group(0))
    if amt is None:
        return None
    tokens = [t for t in re.split(r"[\s,]+", text) if t]
    stop = {"i", "me", "to", "from", "the", "a", "an"} | set(keyword.lower().split()) | {
        "rs", "rs.", "rupees", "rupee", "thousand", "lakh", "lakhs", "crore", "crores", "k", "l",
    }
    person = None
    for tok in tokens:
        low = tok.lower().rstrip(",.:")
        if low in stop:
            continue
        if NUMBER_RE.fullmatch(low):
            continue
        if AMOUNT_RE.fullmatch(low):
            continue
        if not any(ch.isalpha() for ch in low):
            continue
        person = tok.rstrip(",.:")
        break
    if person is None:
        return None
    return titleish(person), amt


def ledger_record(person: str, action: str, amount, d: date) -> dict:
    return {
        "person_text": person,
        "action": action,
        "amount": normalize_amount_number(amount) if amount is not None else None,
        "date": _date_str(d),
        "note": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Query
# ─────────────────────────────────────────────────────────────────────────────

def detect_domain(text: str):
    """
    V1.1.1 priority order (precedence is the whole game):
      1. Embedded chip prefix in residual: `todo:` / `expense:` /
         `weight:` / `buy:` / `ledger:` / `note:` wins absolutely.
         The user explicitly chose the lane.
      2. Strong domain noun: `todos?`, `tasks?`, `weight`, `expense(s)`,
         `spend(ing/s)`, `buy/shopping list`, `note(s)/bucket`. These
         beat ledger-shape signals so that `pending tasks` stays in
         todo rather than getting hijacked by `pending`.
      3. Ledger-shape signals: `ledger`, `balance(s)`, `owe(s/d)`,
         `lent`, `borrowed`, `outstanding dues`, `pending position`,
         `who owes me`, `<person> account close`. Only fires when no
         stronger marker matched.
      4. Catch-all: `note`/`notes`/`bucket` (already handled above).
    """
    t = text.lower()

    # 1. Embedded chip prefix in residual ("ask: todo: pending tasks").
    chip = re.search(r"\b(todo|task|tasks|expense|buy|weight|ledger|note)\s*:", t)
    if chip:
        word = chip.group(1)
        return {
            "todo": "todo", "task": "todo", "tasks": "todo",
            "expense": "expense", "buy": "buy",
            "weight": "weight", "ledger": "ledger", "note": "note",
        }.get(word)

    # 2a. Strong domain nouns. Order matters within this block too.
    if re.search(r"\b(weight|weighing)\b", t):
        return "weight"
    # `todo`/`todos`/`task`/`tasks`/`to do`/`reminder`/`on my list` are
    # all task-shaped and beat ledger's `pending`.
    if re.search(r"\b(todos?|tasks?|to\s*do|reminders?)\b", t):
        return "todo"
    if "on my list" in t or "in my list" in t or "to-do" in t:
        return "todo"
    # done/finished today is querying todos with status=done
    if re.search(r"\b(done|finished|completed)\b\s+(today|this\s+week|yesterday|last\s+week)\b", t):
        return "todo"
    if re.search(r"\b(what|which)\s+did\s+i\s+(finish|complete|do)\b", t):
        return "todo"
    # Buy / shopping (allow trailing "list" or no "list")
    if re.search(r"\b(shopping(\s+list)?|buy(\s+list)?|to\s+buy)\b", t):
        return "buy"
    if re.search(r"\b(expenses?|spend|spent|spending|spendings?|costs?)\b", t):
        return "expense"

    # 3. Ledger-shape signals (only after the strong nouns above). The
    # word list here was tuned against gold-standard frequencies in the
    # v4 dataset: `entries`/`activity`/`borrow`/`lend`/`close out`/
    # `settled with`/`where do i stand`/`stand` all skew >97% ledger.
    # `history` is intentionally NOT here — it's split across weight
    # (309) / ledger (209) / todo (182) and would be a coin flip.
    ledger_signals = (
        r"\b(ledger|balance|balances|owe|owes|owed|borrowed|borrow|borrows|"
        r"lent|lend|lends|outstanding|dues|entries|activity|activities)\b"
    )
    if re.search(ledger_signals, t):
        return "ledger"
    # `pending` is ledger only when no task/todo word appeared earlier
    # (those would have caught it above).
    if re.search(r"\bpending\b", t):
        return "ledger"
    # `clear <X>` / `wrote off <X>` / `settled with` are ledger.
    if re.search(r"\b(clear|wrote off|cleared|settled\s+with|settle|close\s+out)\b", t):
        return "ledger"
    # `where do i stand` / `stand with X`
    if re.search(r"\b(where\s+do\s+i\s+stand|stand\s+with)\b", t):
        return "ledger"
    # `who owes me` / `who do i owe` even without other ledger words
    if re.search(r"\bwho\s+(?:still\s+)?(?:all\s+)?(?:owes?|i\s+owe|do\s+i\s+owe)\b", t):
        return "ledger"
    # `transactions` / `entries with X` / `account close` only when not
    # clearly bank/transaction context for tasks.
    if re.search(r"\b(transactions?|account)\b", t):
        return "ledger"

    # 4. Note / bucket as catch-all.
    if re.search(r"\b(notes?|bucket)\b", t):
        return "note"

    return None


def query_expense(residual, date_range, today):
    """
    V1.1 intent priority:
      1. Explicit list-marker (`list`, `breakdown`, `last N`, `latest`,
         `recent`, `top N`, `expenses` plural-only, `expense list`)
         → `list`
      2. Explicit total-marker (`total`, `summary`, `how much`, `tally`,
         `cost`, `spending`, `spend on`, `expense` singular)
         → `total`
      3. Default → `list` (matches dataset distribution: list >> total
         when neither marker is present and a date phrase IS).
    """
    t = residual.lower()
    # Strong total markers (always win): tuned against the v4 frequency
    # buckets — these keywords are 95-100% gold='total'.
    strong_total = bool(re.search(
        r"\b(total|summary|tally|how\s+much|how\s+many|sum)\b", t,
    ))
    # Strong list markers (always win when present and no strong total).
    strong_list = bool(re.search(
        r"\b(list|breakdown|top\s+\d+|biggest|highest|"
        r"last\s+\d+|recent|latest|show\s+(?:all|me)\s+(?:all|the))\b", t,
    ))
    # Weak signals: `cost` (singular, 100% total), `expense` (singular,
    # 75% total), `spending` (60% total). `expenses` (plural, 83% list)
    # is the default-list signal.
    weak_total = bool(re.search(r"\b(costs?|expense|spending|spend\s+on|spent\s+on)\b", t))
    has_expenses_plural = bool(re.search(r"\bexpenses\b", t))

    if strong_total:
        intent = "total"
    elif strong_list:
        intent = "list"
    elif weak_total and not has_expenses_plural:
        intent = "total"
    else:
        intent = "list"
    # Limit only fires for explicit `last N` / `recent` / `latest` / `top N`.
    limit = None
    m = re.search(r"\b(?:last|top)\s+(\d+)\b", t)
    if m:
        limit = int(m.group(1))
    elif re.search(r"\b(recent|latest)\b", t):
        limit = 10
    # Default range when neither side is given:
    #   - total intent without date → this month
    #   - list intent without date → leave null (dataset uses null often)
    rng = date_range or (this_month(today) if intent == "total" else None)

    # V2: filter inference for expense queries.
    KNOWN_EXPENSE_GROUPS = {
        "groceries", "transport", "dining", "bills_utilities", "recharge_subscription",
        "household", "health", "personal_care", "education", "work", "entertainment",
        "travel", "vehicle", "shopping", "other",
    }
    group_filter = None
    desc_filter = None
    exclude_group_filter = None
    exclude_desc_filter = None

    # Exclusion: `apart from X` / `other than X` / `excluding X` / `except X`
    excl_m = re.search(
        r"\b(?:other\s+than|apart\s+from|excluding|except)\s+(.+?)(?:\s*$|\s+(?:this|last|current|next|today|yesterday))",
        t,
    )
    excl_residual = t
    if excl_m:
        cand = excl_m.group(1).strip().rstrip(",.:;")
        if cand:
            if cand in KNOWN_EXPENSE_GROUPS:
                exclude_group_filter = cand
            else:
                exclude_desc_filter = cand
        # Remove the exclusion phrase from residual for downstream parsing.
        excl_residual = t[: excl_m.start()] + t[excl_m.end():]

    # V2: explicit-pattern filter extraction. Only fires when the input
    # clearly anchors a filter (`<noun> spending`, `spent on <noun>`,
    # `<noun> expense <date>`, etc.) — generic queries like `total
    # expense this month` should NOT get a description filter.
    if not exclude_group_filter and not exclude_desc_filter:
        # Strip chip-prefix and stop words to build the searchable body.
        body = re.sub(r"^\s*expense\s*:\s*", " ", excl_residual, flags=re.IGNORECASE).strip()

        # Pattern A: `<noun> spending` / `<noun> spend` / `<noun> cost(s)?`
        m = re.search(
            r"^(.+?)\s+(?:spending|spend|costs?|expense)\s*$",
            body, re.IGNORECASE,
        )
        # Pattern B: `spent on <noun>` / `spend on <noun>` / `spending on <noun>`
        if m is None:
            m = re.search(
                r"\b(?:spent|spend|spending)\s+on\s+(.+?)\s*$",
                body, re.IGNORECASE,
            )
        # Pattern C: `<noun> expense <date>` / `<noun> spending <date>`
        # (date phrase already extracted, so body might just be `<noun>
        # expense`)
        if m is None:
            m = re.search(
                r"^(?:show\s+(?:me|my)?\s*|give\s+me\s+|tell\s+me\s+)?"
                r"(.+?)\s+(?:expense|spending)\s*$",
                body, re.IGNORECASE,
            )
        # Pattern D: `<group/item> expense` followed by `for/this/last <date>`
        if m is None:
            m = re.search(
                r"\b(?:total\s+)?(.+?)\s+expense\b",
                body, re.IGNORECASE,
            )
        if m:
            cand = m.group(1).strip().rstrip(",.:;-")
            # Drop leading framing words.
            cand = re.sub(
                r"^(?:show|give|tell|my|me|i|the|all|every|of|"
                r"how\s+much|how\s+many|total|tally\s+up|tally|"
                r"current\s+month|this\s+month|last\s+month|today|"
                r"yesterday|tomorrow|next|last|this|current)\s+",
                "", cand, flags=re.IGNORECASE,
            ).strip()
            # Reject obvious noise.
            STOP = {
                "what", "what's", "whats", "how", "did", "do", "i", "me", "my",
                "the", "a", "an", "and", "or", "for", "from", "in", "of", "on",
                "to", "this", "last", "next", "current", "history", "list",
                "total", "summary", "tally", "show", "give", "tell", "me",
                "expense", "expenses", "spending", "spend", "cost", "costs",
                "month", "week", "year", "yesterday", "today", "tomorrow", "now",
            }
            tokens = cand.lower().split()
            non_stop_tokens = [w for w in tokens if w not in STOP and not w.isdigit() and len(w) > 1]
            # Require at least one substantive token AND total length ≥ 3.
            if non_stop_tokens and len(cand) >= 3 and len(tokens) <= 6:
                if cand.lower() in KNOWN_EXPENSE_GROUPS:
                    group_filter = cand.lower()
                else:
                    desc_filter = cand

    filters = {
        "group": group_filter,
        "description_text": desc_filter,
        "exclude_group": exclude_group_filter,
        "exclude_description_text": exclude_desc_filter,
    }
    return accept_query(
        "expense", intent,
        rng.start.isoformat() if rng else None,
        rng.end.isoformat() if rng else None,
        filters, limit, None,
    )


def query_buy(residual, date_range=None):
    """
    V1.1.2: search vs list distinguished by item-anchor detection.
    Search fires when the residual mentions an item with one of:
      - `<item> in/on (my )? (buy|shopping) list`
      - `is <item> on/in <list>`
      - `did i add <item>`
      - `<item> to buy`
      - `show <item> in <list>`
    Otherwise list (default for `show buy list`, `pending buy items`).
    """
    t = residual.lower()
    # Try search-shaped patterns first. Generic "what to buy" / "things
    # to buy" must NOT match — those are list intents asking for the
    # whole buy list. Only fire search when the input has an explicit
    # search verb or an item-anchored "in X list" with a non-generic
    # candidate.
    GENERIC_BUY_NOUNS = {
        "what", "what's", "whats", "things", "items", "stuff", "anything",
        "something", "everything", "nothing", "show items", "show what",
        "what do i need", "what i need",
    }
    item_text = None
    patterns = [
        # `is <item> on/in (my )? (buy|shopping) (list)?`
        r"\bis\s+(.+?)\s+(?:on|in)\s+(?:my\s+)?(?:buy|shopping)\s*(?:list)?\s*$",
        # `did i add <item> to (the )? buy`
        r"\bdid\s+i\s+add\s+(.+?)\s+to\s+(?:the\s+|my\s+)?(?:buy|shopping)\s*(?:list)?\s*$",
        # `add <item> to (the )? buy` (treats user as search-shaped)
        r"\badd\s+(.+?)\s+to\s+(?:the\s+|my\s+)?(?:buy|shopping)\s*(?:list)?\s*$",
        # `show <item> in (my )? (buy|shopping) list`
        r"\bshow\s+(.+?)\s+(?:in|on)\s+(?:my\s+)?(?:buy|shopping)\s*(?:list)?\s*$",
        # `find <item>` / `look up <item>`
        r"\b(?:find|look\s+up)\s+(.+?)$",
        # `have i added <item>` / `have i bought <item>`
        r"\bhave\s+i\s+(?:added|bought)\s+(.+?)\s+(?:to|on|in|$)",
        # `any <item> in/on buy`
        r"\bany\s+(.+?)\s+(?:in|on)\s+(?:my\s+)?(?:buy|shopping)\s*(?:list)?\s*$",
        # `<item> in (my )? (buy|shopping) list` — item-anchored only,
        # `<item>` must be non-generic. Last in the list because it's
        # the most permissive.
        r"^(.+?)\s+(?:in|on)\s+(?:my\s+)?(?:buy|shopping)\s+list\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            cand = m.group(1).strip().rstrip(",.:")
            cand = re.sub(r"^(?:buy|shopping)\s*:?\s*", "", cand, flags=re.IGNORECASE)
            if cand and cand.lower() not in GENERIC_BUY_NOUNS:
                item_text = cand
                break
    intent = "search" if item_text else "list"
    filters = {
        "status": "open" if intent == "list" else None,
        "item_text": item_text,
    }
    return accept_query(
        "buy", intent,
        date_range.start.isoformat() if date_range else None,
        date_range.end.isoformat() if date_range else None,
        filters, None, None,
    )


def query_todo(residual, date_range, today):
    """
    V1.1.2: search vs list distinguished by noun-anchor + on-my-list
    pattern. Intent priority:
      - `history` only when input has both `history` AND no other intent
        cue
      - `search` when an item-shaped phrase appears with `on my list` /
        `find` / `search my todos` / etc.
      - `list` default
    Status: `done`/`finished`/`completed` → done; `pending` → open;
    default → open for `list` intent, null otherwise.
    """
    t = residual.lower()
    text_match = None
    search_patterns = [
        # V2: order specific patterns first so `find X on my list` extracts
        # `X` not `find X`.
        # `find <noun> on my list` / `find <noun>`
        r"\b(?:find|look\s+up|locate)\s+(.+?)(?:\s+on\s+my\s+list)?\s*$",
        # `is <noun> on my list`
        r"\bis\s+(.+?)\s+on\s+my\s+list\s*$",
        # `search my todos for <noun>`
        r"\bsearch\s+my\s+todos?\s+for\s+(.+?)\s*$",
        # `<noun> on my list`
        r"^(.+?)\s+on\s+my\s+list\s*$",
        # `remind <noun> on my list`
        r"^remind\s+(.+?)\s+on\s+my\s+list\s*$",
        # `do i have <noun> (pending|todo)?`
        r"\bdo\s+i\s+have\s+(.+?)\s+(?:pending|todo|task)\s*$",
    ]
    for pat in search_patterns:
        m = re.search(pat, t)
        if m:
            cand = m.group(1).strip().rstrip(",.:")
            cand = re.sub(r"^(?:todo|tasks?|to\s*do)\s*:?\s*", "", cand, flags=re.IGNORECASE)
            if cand:
                text_match = cand
                break

    # V2: `finish` / `complete` (without -ed) also count as done queries.
    is_done_query = bool(re.search(r"\b(done|finish(?:ed)?|complet(?:e|ed))\b", t))
    is_history = (
        re.search(r"\bhistory\b", t)
        and not text_match
    )
    # V2: `every/all/full todo(s)` → status=None (asking for the FULL list).
    is_all_query = bool(re.search(r"\b(every|all|full)\s+(?:todos?|tasks?|to\s*do)\b", t))

    if text_match:
        intent = "search"
        status = None
    elif is_history:
        intent = "history"
        status = None
    elif is_all_query:
        intent = "list"
        status = None
    else:
        intent = "list"
        status = "done" if is_done_query else "open"

    rng = date_range or (this_day(today) if re.search(r"\btoday\b", t) else None)
    filters = {"status": status, "text_match": text_match}
    return accept_query(
        "todo", intent,
        rng.start.isoformat() if rng else None,
        rng.end.isoformat() if rng else None,
        filters, None, None,
    )


def query_weight(residual, original_text, date_range=None, today=None):
    """
    V2: history intent over-predicted as `latest` in V1.1 — 1010 rows
    of `pred='latest' vs gold='history'`. The dataset uses `history`
    for:
      - explicit log/readings: `weight log`, `weight readings`,
        `pull up my weight log`, `weight history`
      - past-date references: `<person> weight from last friday`,
        `last sunday my weight`, `what was X weight on last monday`
      - change-over-time framings: `show me how my weight has
        changed`, `weight has changed`
    """
    t = residual.lower()
    has_past_date_marker = bool(re.search(
        r"\b(last|previous|yesterday|nethu|pona)\b\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|year|maasam|varusham)",
        t,
    )) or bool(re.search(r"\bfrom\s+last\b", t)) or bool(re.search(r"\bon\s+last\b", t))
    # History markers: PLURAL `readings`/`logs`/`records` only;
    # `weight log` (preceded by `weight`) but not bare `log` (verb form).
    has_history_log = bool(re.search(r"\b(weight\s+log|weight\s+logs|readings|records|recordings)\b", t))
    has_history_word = bool(re.search(r"\bhistory\b", t))
    has_changed_phrasing = bool(re.search(r"\bhas\s+changed\b|how\s+.+\s+changed\b", t))
    has_trend = bool(re.search(r"\btrend\b", t))
    has_change_only = bool(re.search(r"\bchange\b", t)) and not has_changed_phrasing
    has_all = bool(re.search(r"\b(everyone|all|family)\b", t))

    if has_all:
        intent = "latest_all"
    elif has_history_log or has_history_word or has_past_date_marker or has_changed_phrasing:
        intent = "history"
    elif has_trend:
        intent = "trend"
    elif has_change_only:
        intent = "change"
    else:
        intent = "latest"

    person_hint = extract_person_from_query(original_text)
    if person_hint is None:
        if re.search(r"\b(my|me|i)\b", t):
            person_hint = "self"
        elif intent == "latest_all":
            person_hint = None
        else:
            person_hint = "self"
    filters = {"person_text": person_hint}
    # V2: weight history/trend/change defaults to a 6-month window
    # ending at anchor when no explicit range is given. Dataset uses
    # this convention across hundreds of `weight log` / `weight trend`
    # / `weight readings` / `weight has changed` rows.
    if date_range is None and intent in ("history", "trend", "change") and today is not None:
        y, mth = today.year, today.month - 6
        while mth <= 0:
            y -= 1
            mth += 12
        try:
            start = today.replace(year=y, month=mth)
        except ValueError:
            start = today.replace(year=y, month=mth, day=28)
        date_range = DateRange(start, today)
    return accept_query(
        "weight", intent,
        date_range.start.isoformat() if date_range else None,
        date_range.end.isoformat() if date_range else None,
        filters, None, None,
    )


def query_ledger(residual, original_text, date_range=None):
    """
    V1.1 intent priority:
      1. Person-specific lookup → `balance` (when "balance" / "owe" /
         "owes me" + a specific person) or `list` (when "transactions" /
         "entries" / "history with X")
      2. Aggregate view → `summary` (multi-person, who-owes, all
         outstanding)
      3. `recent` / `latest` / `list` of recent → `list` with limit=10
    """
    t = residual.lower()
    person_hint = extract_person_from_query(original_text)
    has_recent_marker = bool(re.search(r"\b(recent|latest|recent\s+entries|recent\s+transactions|last\s+\d+)\b", t))
    has_history_marker = bool(re.search(r"\b(history|transactions|entries)\b", t))
    has_balance_marker = bool(re.search(r"\bbalance(s)?\b", t))
    has_summary_marker = bool(re.search(r"\b(summary|outstanding|pending|dues|open\s+balances?|where\s+do\s+my)\b", t))
    has_who_marker = bool(re.search(r"\bwho\s+(?:still\s+)?(?:all\s+)?(?:owes?|i\s+owe|do\s+i\s+owe)\b", t))

    if has_recent_marker:
        intent = "list"
        limit = 10
        m = re.search(r"\blast\s+(\d+)\b", t)
        if m:
            limit = int(m.group(1))
    elif has_history_marker and person_hint:
        intent = "list"
        limit = None
    elif person_hint and has_balance_marker:
        intent = "balance"
        limit = None
    elif person_hint and not has_summary_marker:
        intent = "balance"
        limit = None
    elif has_who_marker or has_summary_marker:
        intent = "summary"
        limit = None
    elif has_balance_marker:
        intent = "summary"
        limit = None
    else:
        intent = "summary"
        limit = None

    if re.search(r"who\s+(?:still\s+)?(?:all\s+)?owes?\s+me", t):
        perspective = "i_owe_them"
    elif re.search(r"who\s+do\s+i\s+owe|how\s+much\s+do\s+i\s+owe|^i\s+owe\b", t):
        perspective = "they_owe_me"
    else:
        perspective = None

    # V2: status filter only when intent is summary/balance. For
    # `list` intent (recent/history/transactions), the dataset uses
    # status=None (all entries, not just open ones).
    status_filter = "open" if intent in ("summary", "balance") else None
    filters = {"person_text": person_hint, "perspective": perspective, "status": status_filter}
    return accept_query(
        "ledger", intent,
        date_range.start.isoformat() if date_range else None,
        date_range.end.isoformat() if date_range else None,
        filters, limit, None,
    )


def query_note(residual, date_range, original_text):
    """
    V2: query_text extraction uses POSITIVE patterns (regex with a
    topic-anchor capture group) instead of the V1.1 subtractive
    framing-word stripper which over-stripped and under-stripped.

    Intent rules:
      - `latest` / `most recent` → latest
      - date_range present → list
      - otherwise → search (with topic extracted positively)
    """
    t = residual.lower()
    if re.search(r"\b(latest|most recent)\b", t):
        intent = "latest"
    elif date_range is not None:
        intent = "list"
    else:
        intent = "search"

    search_text = None
    if intent == "search":
        # Strip chip prefixes from the original input first so capture
        # groups don't include them.
        body = re.sub(r"^\s*ask\s*:\s*", "", original_text, flags=re.IGNORECASE)
        body = re.sub(r"^\s*note\s*:\s*", "", body, flags=re.IGNORECASE)
        body = body.strip()

        # Positive patterns. Order matters: longer/more specific first.
        # Each capture group becomes the topic.
        patterns = [
            # `notes la <X> irukka`  (Tanglish: "is there <X> in notes")
            r"^notes?\s+la\s+(.+?)\s+irukka\s*$",
            # `<X> pathi notes? irukka`  (Tanglish: "any notes about <X>")
            r"^(.+?)\s+pathi\s+notes?\s+irukka\s*$",
            # `<X> mentions in notes?` / `<X> mentions in my notes?`
            r"^(.+?)\s+mentions?\s+in\s+(?:my\s+)?notes?\s*$",
            # `any mention of <X> in (my )? notes?`
            r"\bany\s+mention\s+of\s+(.+?)\s+in\s+(?:my\s+)?notes?\s*$",
            # `any mention of <X>` (with optional `in notes` later)
            r"\bany\s+mention\s+of\s+(.+?)$",
            # `any notes? about <X>`
            r"\bany\s+notes?\s+about\s+(.+?)$",
            # `have i noted anything about <X>`
            r"\bhave\s+i\s+noted\s+anything\s+about\s+(.+?)$",
            # `did i note anything about <X>`
            r"\bdid\s+i\s+note\s+anything\s+about\s+(.+?)$",
            # `what did i write about <X>`
            r"\bwhat\s+did\s+i\s+(?:write|note|jot)\s+(?:down\s+)?about\s+(.+?)$",
            # `find <X> in my notes`
            r"\bfind\s+(.+?)\s+in\s+(?:my\s+)?notes?\s*$",
            # `look up <X> in my notes`
            r"\blook\s+up\s+(.+?)\s+in\s+(?:my\s+)?notes?\s*$",
            # `search my notes? for <X>`
            r"\bsearch\s+(?:my\s+)?notes?\s+for\s+(.+?)$",
            # `show my notes? about <X>` / `show notes? about <X>`
            r"\bshow\s+(?:my\s+)?notes?\s+about\s+(.+?)$",
            # `note snippets about <X>` / `snippets about <X>`
            r"\b(?:note\s+)?snippets\s+(?:about\s+)?(.+?)$",
            # `notes mentioning <X>` / `note mentioning <X>`
            r"\bnotes?\s+mentioning\s+(.+?)$",
            # `pull notes? (related to|about) <X>`
            r"\bpull\s+notes?\s+(?:related\s+to|about|on)\s+(.+?)$",
            # `<X> notes?`  (e.g. `kitchen exhaust cleaning notes`)
            r"^(.+?)\s+notes?\s*$",
            # Fallback: whatever's left after stripping `notes`
            r"^(.+?)$",
        ]
        for pat in patterns:
            m = re.search(pat, body, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                # Strip lingering framing words at the edges.
                cand = re.sub(r"^(?:my\s+|the\s+|a\s+|an\s+)", "", cand, flags=re.IGNORECASE)
                cand = re.sub(r"\s+(?:in|on|about|for|the)\s*$", "", cand, flags=re.IGNORECASE)
                cand = cand.strip().rstrip(",.:;")
                if cand and cand.lower() not in {"notes", "note", "the", "of", "in", "on"}:
                    search_text = cand
                    break

    return accept_query(
        "note", intent,
        date_range.start.isoformat() if date_range else None,
        date_range.end.isoformat() if date_range else None,
        {}, None, search_text,
    )


def extract_person_from_query(text: str):
    cleaned = text.strip()
    if cleaned.lower().startswith("ask:"):
        cleaned = cleaned[4:].strip()
    tokens = re.split(r"\s+", cleaned)
    stop = {
        "ask", "show", "list", "latest", "my", "his", "her", "their", "weight",
        "balance", "expense", "buy", "todo", "note", "ledger", "summary", "recent",
    }
    for tok in tokens:
        if not tok:
            continue
        if tok[0].isupper() and tok.lower() not in stop:
            return tok.rstrip(",.:")
    return None


def parse_query(body: str, today: date) -> dict:
    text = body.strip()
    lower = text.lower()
    date_range, residual = extract_date_range_phrase(lower, today)
    # V2: fall back to "anywhere" date detection if the canonical phrase
    # pass didn't find one. Date_range queries fail at high volume in
    # V1.1 because phrases like `on monday` / `since last week` / etc.
    # need the broader scanner.
    if date_range is None:
        date_range = find_date_range_anywhere(lower, today)
    domain = detect_domain(residual or lower)
    if domain is None:
        return reject_query("manual_unrecognized")
    if domain == "expense":
        return query_expense(residual, date_range, today)
    if domain == "buy":
        return query_buy(residual, date_range)
    if domain == "todo":
        return query_todo(residual, date_range, today)
    if domain == "weight":
        return query_weight(residual, text, date_range, today)
    if domain == "ledger":
        return query_ledger(residual, text, date_range)
    if domain == "note":
        return query_note(residual, date_range, text)
    return reject_query("manual_unrecognized")


# ─────────────────────────────────────────────────────────────────────────────
# Top-level
# ─────────────────────────────────────────────────────────────────────────────

def parse(user_input: str, today: date | None = None) -> dict:
    today = today or date.today()
    text = user_input.strip()
    if not text:
        return reject(None, "empty_input")
    tagged = split_tag(text)
    if tagged is None:
        return reject(None, "no_tag")
    tag, body = tagged
    body_trim = body.strip()
    if not body_trim:
        return reject(tag, "incomplete_input")
    try:
        if tag == "expense":
            return parse_expense_write(body_trim, today)
        if tag == "buy":
            return parse_buy_write(body_trim, today)
        if tag == "todo":
            return parse_todo_write(body_trim, today)
        if tag == "weight":
            return parse_weight_write(body_trim, today)
        if tag == "ledger":
            return parse_ledger_write(body_trim, today)
        if tag == "ask":
            return parse_query(body_trim, today)
        return reject(None, "no_tag")
    except Exception:
        return reject(tag, "manual_unrecognized")


if __name__ == "__main__":
    # Quick smoke test mirroring the dogfood log inputs.
    samples = [
        "expense: petrol 500",
        "expense: apple 200rs, 100 manga, 600rs jillathi",
        "buy: tomato, salt 1kg, paasi parupu",
        "weight: my weight 67.5 after walk",
        "ledger: i owe jeevi 30k",
        "ledger: gave Maddy 5k",
        "ask: this month total expense",
        "ask: who owes me money",
    ]
    today = date(2026, 5, 11)
    for s in samples:
        print("\nINPUT:", s)
        print(json.dumps(parse(s, today), ensure_ascii=False))
