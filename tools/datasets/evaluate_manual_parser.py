"""
Evaluate `manual_parser.py` against the v4 frozen-schema dataset.

For every (input, golden_output, anchor_date) row in
`synthetic_finetune_dataset_v4_v2_schema/parse_write/*.jsonl` and
`.../parse_query/*.jsonl`, run the rules engine and compare the predicted
payload against the gold. Compute per-lane / per-domain accuracy and
bucket failures so we can see exactly where the rules are weak.

Usage:
    python evaluate_manual_parser.py
    python evaluate_manual_parser.py --root <other-dataset-root>
    python evaluate_manual_parser.py --limit-per-lane 1000
    python evaluate_manual_parser.py --show-failures 5
    python evaluate_manual_parser.py --out-json eval_manual_v1.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import manual_parser


DEFAULT_ROOT = "synthetic_finetune_dataset_v4_v2_schema"
WRITE_LANES = ("expense", "buy", "todo", "weight", "ledger")
QUERY_DOMAINS = ("expense", "buy", "todo", "weight", "ledger", "note")


# ─────────────────────────────────────────────────────────────────────────────
# Comparison
# ─────────────────────────────────────────────────────────────────────────────

def parse_anchor(s):
    if not s:
        return date.today()
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def normalize_str(x):
    if x is None:
        return None
    if isinstance(x, str):
        # case-insensitive description compare; the golden uses mixed
        # capitalization (e.g. "Tide drain cleaner") and the rules
        # preserve user casing. For exact-match scoring we honour case
        # because group/category lookups care, but for failure-bucket
        # analysis we also compute a case-insensitive variant.
        return x
    return x


def cmp_writes(pred: dict, gold: dict) -> dict:
    """Returns a dict of granular boolean checks plus per-record diffs."""
    out = {
        "task_match": pred.get("task") == gold.get("task"),
        "lane_match": pred.get("lane") == gold.get("lane"),
        "disposition_match": pred.get("disposition") == gold.get("disposition"),
        "reason_code_match": (pred.get("reason_code") or None) == (gold.get("reason_code") or None),
        "record_count_match": len(pred.get("records") or []) == len(gold.get("records") or []),
        "exact_match": False,
        "per_record_failures": [],
    }
    # Exact match: stable JSON
    out["exact_match"] = json.dumps(pred, sort_keys=True, ensure_ascii=False) == \
                        json.dumps(gold, sort_keys=True, ensure_ascii=False)
    if not out["record_count_match"]:
        return out
    # Per-record diff
    for i, (pr, gr) in enumerate(zip(pred.get("records") or [], gold.get("records") or [])):
        rec_failures = {}
        for k in set(pr.keys()) | set(gr.keys()):
            pv, gv = pr.get(k), gr.get(k)
            if pv != gv:
                # Normalize numeric near-equality (e.g. 5000 vs 5000.0)
                if isinstance(pv, (int, float)) and isinstance(gv, (int, float)):
                    if abs(float(pv) - float(gv)) < 1e-6:
                        continue
                rec_failures[k] = {"pred": pv, "gold": gv}
        if rec_failures:
            out["per_record_failures"].append({"record_index": i, "fields": rec_failures})
    return out


def cmp_queries(pred: dict, gold: dict) -> dict:
    out = {
        "task_match": pred.get("task") == gold.get("task"),
        "domain_match": pred.get("domain") == gold.get("domain"),
        "disposition_match": pred.get("disposition") == gold.get("disposition"),
        "intent_match": pred.get("intent") == gold.get("intent"),
        "date_start_match": pred.get("date_start") == gold.get("date_start"),
        "date_end_match": pred.get("date_end") == gold.get("date_end"),
        "compare_dates_match": (pred.get("compare_date_start") == gold.get("compare_date_start") and
                                pred.get("compare_date_end") == gold.get("compare_date_end")),
        "limit_match": pred.get("limit") == gold.get("limit"),
        "query_text_match": pred.get("query_text") == gold.get("query_text"),
        "filters_match": pred.get("filters") == gold.get("filters"),
        "filter_diffs": {},
        "exact_match": False,
    }
    out["exact_match"] = json.dumps(pred, sort_keys=True, ensure_ascii=False) == \
                        json.dumps(gold, sort_keys=True, ensure_ascii=False)
    pf = pred.get("filters") or {}
    gf = gold.get("filters") or {}
    diffs = {}
    for k in set(pf.keys()) | set(gf.keys()):
        if pf.get(k) != gf.get(k):
            diffs[k] = {"pred": pf.get(k), "gold": gf.get(k)}
    out["filter_diffs"] = diffs
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Failure bucketing
# ─────────────────────────────────────────────────────────────────────────────

def write_failure_bucket(pred, gold, cmp_result):
    """Best-effort label of the dominant failure mode for a write row."""
    if cmp_result["exact_match"]:
        return None
    if not cmp_result["disposition_match"]:
        return f"disposition: pred={pred.get('disposition')!r} vs gold={gold.get('disposition')!r}"
    if not cmp_result["lane_match"]:
        return f"lane: pred={pred.get('lane')!r} vs gold={gold.get('lane')!r}"
    if not cmp_result["record_count_match"]:
        return f"record_count: pred={len(pred.get('records') or [])} vs gold={len(gold.get('records') or [])}"
    # First per-record field that differs is our bucket label.
    for prf in cmp_result["per_record_failures"]:
        for field in prf["fields"]:
            return f"field: {field}"
    return "other"


def query_failure_bucket(pred, gold, cmp_result):
    if cmp_result["exact_match"]:
        return None
    if not cmp_result["domain_match"]:
        return f"domain: pred={pred.get('domain')!r} vs gold={gold.get('domain')!r}"
    if not cmp_result["disposition_match"]:
        return f"disposition: pred={pred.get('disposition')!r} vs gold={gold.get('disposition')!r}"
    if not cmp_result["intent_match"]:
        return f"intent: pred={pred.get('intent')!r} vs gold={gold.get('intent')!r}"
    if not cmp_result["date_start_match"] or not cmp_result["date_end_match"]:
        return "date_range"
    if not cmp_result["limit_match"]:
        return f"limit: pred={pred.get('limit')!r} vs gold={gold.get('limit')!r}"
    if not cmp_result["query_text_match"]:
        return "query_text"
    if cmp_result["filter_diffs"]:
        return "filters: " + ",".join(sorted(cmp_result["filter_diffs"].keys()))
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# Per-lane / per-domain runner
# ─────────────────────────────────────────────────────────────────────────────

def run_writes(root: Path, limit: int, show_failures: int):
    summary = {}
    detail_failures = {}
    for lane in WRITE_LANES:
        path = root / "parse_write" / f"{lane}.jsonl"
        if not path.exists():
            print(f"[skip] {path} not found", file=sys.stderr)
            continue
        rows = load_jsonl(path, limit)
        n = len(rows)
        agg = {
            "n": n, "exact": 0, "task": 0, "lane": 0, "disposition": 0,
            "reason_code": 0, "record_count": 0,
        }
        per_field = Counter()
        bucket = Counter()
        examples = []
        for row in rows:
            pred = manual_parser.parse(row["input"], parse_anchor(row.get("anchor_date")))
            res = cmp_writes(pred, row["output"])
            agg["task"] += int(res["task_match"])
            agg["lane"] += int(res["lane_match"])
            agg["disposition"] += int(res["disposition_match"])
            agg["reason_code"] += int(res["reason_code_match"])
            agg["record_count"] += int(res["record_count_match"])
            agg["exact"] += int(res["exact_match"])
            for prf in res["per_record_failures"]:
                for field in prf["fields"]:
                    per_field[field] += 1
            label = write_failure_bucket(pred, row["output"], res)
            if label is not None:
                bucket[label] += 1
                if len(examples) < show_failures * 8:
                    examples.append({
                        "input": row["input"],
                        "label": label,
                        "pred": pred,
                        "gold": row["output"],
                    })
        summary[lane] = {
            "n": n,
            "exact_pct": pct(agg["exact"], n),
            "lane_pct": pct(agg["lane"], n),
            "disposition_pct": pct(agg["disposition"], n),
            "record_count_pct": pct(agg["record_count"], n),
            "top_field_failures": per_field.most_common(8),
            "top_buckets": bucket.most_common(8),
        }
        # Pick a few examples per top bucket for the report.
        per_bucket_samples = defaultdict(list)
        for ex in examples:
            if len(per_bucket_samples[ex["label"]]) < show_failures:
                per_bucket_samples[ex["label"]].append(ex)
        detail_failures[f"write/{lane}"] = dict(per_bucket_samples)
    return summary, detail_failures


def run_queries(root: Path, limit: int, show_failures: int):
    summary = {}
    detail_failures = {}
    for domain in QUERY_DOMAINS:
        path = root / "parse_query" / f"{domain}.jsonl"
        if not path.exists():
            print(f"[skip] {path} not found", file=sys.stderr)
            continue
        rows = load_jsonl(path, limit)
        n = len(rows)
        agg = {
            "n": n, "exact": 0, "task": 0, "domain": 0, "disposition": 0,
            "intent": 0, "date_range": 0, "limit": 0, "query_text": 0, "filters": 0,
        }
        bucket = Counter()
        examples = []
        for row in rows:
            pred = manual_parser.parse(row["input"], parse_anchor(row.get("anchor_date")))
            res = cmp_queries(pred, row["output"])
            agg["task"] += int(res["task_match"])
            agg["domain"] += int(res["domain_match"])
            agg["disposition"] += int(res["disposition_match"])
            agg["intent"] += int(res["intent_match"])
            agg["date_range"] += int(res["date_start_match"] and res["date_end_match"])
            agg["limit"] += int(res["limit_match"])
            agg["query_text"] += int(res["query_text_match"])
            agg["filters"] += int(res["filters_match"])
            agg["exact"] += int(res["exact_match"])
            label = query_failure_bucket(pred, row["output"], res)
            if label is not None:
                bucket[label] += 1
                if len(examples) < show_failures * 8:
                    examples.append({
                        "input": row["input"],
                        "label": label,
                        "pred": pred,
                        "gold": row["output"],
                    })
        summary[domain] = {
            "n": n,
            "exact_pct": pct(agg["exact"], n),
            "domain_pct": pct(agg["domain"], n),
            "intent_pct": pct(agg["intent"], n),
            "date_range_pct": pct(agg["date_range"], n),
            "filters_pct": pct(agg["filters"], n),
            "top_buckets": bucket.most_common(8),
        }
        per_bucket_samples = defaultdict(list)
        for ex in examples:
            if len(per_bucket_samples[ex["label"]]) < show_failures:
                per_bucket_samples[ex["label"]].append(ex)
        detail_failures[f"query/{domain}"] = dict(per_bucket_samples)
    return summary, detail_failures


def load_jsonl(path: Path, limit: int):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def pct(num, denom):
    if denom == 0:
        return 0.0
    return round(100 * num / denom, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=DEFAULT_ROOT)
    p.add_argument("--limit-per-lane", type=int, default=0,
                   help="0 = no cap; otherwise sample this many rows per file")
    p.add_argument("--show-failures", type=int, default=3,
                   help="Number of example rows to show per failure bucket")
    p.add_argument("--out-json", default=None,
                   help="Optional path to write the full machine-readable report")
    args = p.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Dataset root not found: {root}", file=sys.stderr)
        sys.exit(2)

    print(f"Evaluating ManualParser against {root}")
    print(f"Cap per file: {args.limit_per_lane or 'all'}")
    print()

    write_summary, write_failures = run_writes(root, args.limit_per_lane, args.show_failures)
    print("=" * 80)
    print("WRITES (parse_write)")
    print("=" * 80)
    for lane, s in write_summary.items():
        print(f"\n[{lane}]  n={s['n']}  exact={s['exact_pct']}%  "
              f"disposition={s['disposition_pct']}%  records-aligned={s['record_count_pct']}%")
        if s["top_field_failures"]:
            print("  Top field mismatches:")
            for field, count in s["top_field_failures"]:
                print(f"    {field}: {count}")
        if s["top_buckets"]:
            print("  Top failure buckets:")
            for bucket, count in s["top_buckets"]:
                print(f"    {count:5d}  {bucket}")
        if args.show_failures and write_failures.get(f"write/{lane}"):
            for label, examples in write_failures[f"write/{lane}"].items():
                print(f"  Examples for `{label}`:")
                for ex in examples:
                    print(f"    INPUT: {ex['input']}")
                    print(f"    PRED:  {json.dumps(ex['pred'], ensure_ascii=False)[:200]}")
                    print(f"    GOLD:  {json.dumps(ex['gold'], ensure_ascii=False)[:200]}")
                    print()

    query_summary, query_failures = run_queries(root, args.limit_per_lane, args.show_failures)
    print("\n" + "=" * 80)
    print("QUERIES (parse_query)")
    print("=" * 80)
    for domain, s in query_summary.items():
        print(f"\n[{domain}]  n={s['n']}  exact={s['exact_pct']}%  "
              f"domain={s['domain_pct']}%  intent={s['intent_pct']}%  "
              f"dates={s['date_range_pct']}%  filters={s['filters_pct']}%")
        if s["top_buckets"]:
            print("  Top failure buckets:")
            for bucket, count in s["top_buckets"]:
                print(f"    {count:5d}  {bucket}")
        if args.show_failures and query_failures.get(f"query/{domain}"):
            for label, examples in query_failures[f"query/{domain}"].items():
                print(f"  Examples for `{label}`:")
                for ex in examples:
                    print(f"    INPUT: {ex['input']}")
                    print(f"    PRED:  {json.dumps(ex['pred'], ensure_ascii=False)[:200]}")
                    print(f"    GOLD:  {json.dumps(ex['gold'], ensure_ascii=False)[:200]}")
                    print()

    # Roll-up
    print("\n" + "=" * 80)
    print("ROLL-UP")
    print("=" * 80)
    total_n = sum(s["n"] for s in write_summary.values()) + sum(s["n"] for s in query_summary.values())
    total_exact = sum(int(s["exact_pct"] * s["n"] / 100) for s in write_summary.values()) + \
                  sum(int(s["exact_pct"] * s["n"] / 100) for s in query_summary.values())
    print(f"Rows evaluated: {total_n}")
    print(f"Exact-match (whole payload identical to golden): {pct(total_exact, total_n)}%")
    print()
    print("Per-lane exact-match (writes):")
    for lane, s in write_summary.items():
        print(f"  {lane:8s}  {s['exact_pct']:5.1f}%  (n={s['n']})")
    print("Per-domain exact-match (queries):")
    for domain, s in query_summary.items():
        print(f"  {domain:8s}  {s['exact_pct']:5.1f}%  (n={s['n']})")

    if args.out_json:
        report = {
            "root": str(root),
            "limit_per_lane": args.limit_per_lane,
            "writes": write_summary,
            "queries": query_summary,
            "roll_up": {
                "rows": total_n,
                "exact_pct": pct(total_exact, total_n),
            },
        }
        Path(args.out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nFull report written to {args.out_json}")


if __name__ == "__main__":
    main()
