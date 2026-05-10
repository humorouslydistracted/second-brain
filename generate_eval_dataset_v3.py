"""v3 held-out eval generator for the v2 parser schema.

Companion to ``generate_large_schema_frozen_dataset_v2.py`` (the v2 training
generator). Produces a held-out evaluation set that:

- uses the same v2 makers as training, so parse_query rows carry the uniform
  v2 field set (``disposition``, ``reason_code``, ``clarify_reason``,
  ``clarify_options``) and parse_followup_query rows carry
  ``inherit_context: true`` plus ``disposition: "accept"``;
- spreads rows across the same 5 anchors (``ANCHORS``), with each row carrying
  a top-level ``anchor_date`` for prompt-time injection (``Today: <date>``);
- de-duplicates against the v2 training dataset
  (``synthetic_finetune_dataset_v4_v2_schema/``) when it exists, so eval rows
  are genuinely held out.

Output dir: ``eval_finetune_dataset_v3_schema_frozen/``.

This file does NOT supersede ``generate_eval_dataset_v2.py`` (which targets the
v1 schema). Both are kept so the v1 adapter can still be evaluated against the
v1 schema if needed.

Per ``dataset_v2_plan.md`` Section 9, this is Phase 2 Step 6.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from generate_large_schema_frozen_dataset_v2 import (
    ANCHOR_MONTHS,
    SEED,
    make_buy_query,
    make_buy_write,
    make_expense_query,
    make_expense_write,
    make_followup,
    make_ledger_query,
    make_ledger_write,
    make_note_query,
    make_todo_query,
    make_todo_write,
    make_weight_query,
    make_weight_write,
    pick_anchor_iso,
)


OUT_DIR = Path("eval_finetune_dataset_v3_schema_frozen")
TRAIN_ROOT = Path("synthetic_finetune_dataset_v4_v2_schema")
EVAL_SEED = SEED + 7001

# Default per-bucket counts when no --total is given. The sum (200 + 210 + 90 = 500)
# is also the target total when a downstream tool uses the historical "500-case"
# label for the v3 eval set. The proportions below preserve the same mix at any
# user-chosen total.
WRITE_PER_LANE = 40
QUERY_PER_DOMAIN = 35
FOLLOWUP_COUNT = 90

# Bucket-share ratios. Used by --total to derive per-bucket counts proportionally.
# These sum to 1.0 and reflect the historical 200/210/90 split:
#   writes  : 200 / 500 = 0.40
#   queries : 210 / 500 = 0.42
#   followups: 90 / 500 = 0.18
WRITE_SHARE = 0.40
QUERY_SHARE = 0.42
FOLLOWUP_SHARE = 0.18


WRITE_PLAN = [
    ("expense", make_expense_write),
    ("buy", make_buy_write),
    ("todo", make_todo_write),
    ("weight", make_weight_write),
    ("ledger", make_ledger_write),
]

QUERY_PLAN = [
    ("expense", make_expense_query),
    ("buy", make_buy_query),
    ("todo", make_todo_query),
    ("weight", make_weight_query),
    ("ledger", make_ledger_query),
    ("note", make_note_query),
]

FOLLOWUP_PLAN = [
    ("mixed", make_followup),
]


def derive_counts_from_total(total: int) -> tuple[int, int, int]:
    """Distribute `total` across (write_per_lane, query_per_domain, followup_count)
    using the bucket-share ratios above, with a hard floor of 1 per lane / domain
    so even a tiny eval covers every file.

    Returns (write_per_lane, query_per_domain, followup_count). The actual emitted
    row count is `5 * write_per_lane + 6 * query_per_domain + followup_count`,
    which may differ from `total` by a few rows due to integer rounding.
    """
    if total < (len(WRITE_PLAN) + len(QUERY_PLAN) + 1):
        # Floor: at minimum one case per write lane (5) + one per query domain (6) + one followup = 12.
        return 1, 1, 1
    write_alloc = round(total * WRITE_SHARE)
    query_alloc = round(total * QUERY_SHARE)
    followup_alloc = total - write_alloc - query_alloc
    write_per_lane = max(1, write_alloc // len(WRITE_PLAN))
    query_per_domain = max(1, query_alloc // len(QUERY_PLAN))
    followup_count = max(1, followup_alloc)
    return write_per_lane, query_per_domain, followup_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Output directory for the v3 held-out eval set.")
    parser.add_argument(
        "--train-root",
        default=str(TRAIN_ROOT),
        help="v2 training dataset root used for held-out overlap checks. Skipped cleanly if it does not exist.",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=None,
        help=(
            "Target total eval cases across all lanes. Distributes proportionally as "
            "writes/queries/followups = 40/42/18, with a hard floor of 1 row per "
            "lane / domain so even small evals cover every file. Common picks: "
            "50, 100, 500. Per-bucket flags below override individual buckets when "
            "set explicitly. If --total is omitted, the historical defaults "
            "(40/35/90 -> 500 cases) are used."
        ),
    )
    parser.add_argument(
        "--write-per-lane",
        type=int,
        default=None,
        help=f"Held-out write cases per write lane. Overrides --total. Default {WRITE_PER_LANE}.",
    )
    parser.add_argument(
        "--query-per-domain",
        type=int,
        default=None,
        help=f"Held-out query cases per query domain. Overrides --total. Default {QUERY_PER_DOMAIN}.",
    )
    parser.add_argument(
        "--followup-count",
        type=int,
        default=None,
        help=f"Held-out follow-up cases. Overrides --total. Default {FOLLOWUP_COUNT}.",
    )
    parser.add_argument("--seed", type=int, default=EVAL_SEED, help="RNG seed for eval generation.")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print a sanity report (anchor / disposition / lane counts and sample rows). Does not write files.",
    )
    args = parser.parse_args()

    # Resolve per-bucket counts. Precedence:
    #   1. Explicit per-bucket flags (--write-per-lane / --query-per-domain / --followup-count) win.
    #   2. --total fills in any remaining buckets via proportional allocation.
    #   3. Otherwise fall back to the historical defaults (40 / 35 / 90).
    if args.total is not None:
        wpl, qpd, fc = derive_counts_from_total(args.total)
    else:
        wpl, qpd, fc = WRITE_PER_LANE, QUERY_PER_DOMAIN, FOLLOWUP_COUNT
    if args.write_per_lane is None:
        args.write_per_lane = wpl
    if args.query_per_domain is None:
        args.query_per_domain = qpd
    if args.followup_count is None:
        args.followup_count = fc
    return args


def canonical_key(row: dict) -> str:
    """Stable signature for de-duplication across input + expected (+ optional context).

    Mirrors how v2 generator/v2 eval shaped uniqueness, but lifted into the
    eval-row representation: an eval row carries ``input`` and ``expected``
    (sometimes ``context``); a training row carries ``input`` and ``output``
    (sometimes ``context``). We normalize both shapes into the same signature
    so overlap checks work in either direction.
    """
    if "expected" in row:
        body = {"input": row["input"], "expected": row["expected"]}
    else:
        body = {"input": row["input"], "expected": row["output"]}
    if "context" in row:
        body["context"] = row["context"]
    return json.dumps(body, ensure_ascii=False, sort_keys=True)


def pick_mode(rng: random.Random) -> str:
    return "india" if rng.random() < 0.7 else "global"


def pick_anchor(rng: random.Random) -> str:
    """Delegates to the v2 generator's per-row random anchor picker so the
    eval set inherits the same anchor-month + randomized-day strategy."""
    return pick_anchor_iso(rng)


def load_training_signatures(train_root: Path) -> set[str]:
    signatures: set[str] = set()
    if not train_root.exists():
        return signatures
    for subdir in ("parse_write", "parse_query", "parse_followup_query"):
        target = train_root / subdir
        if not target.exists():
            continue
        for path in target.rglob("*.jsonl"):
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    signatures.add(canonical_key(raw))
    return signatures


def make_eval_case(case_id: str, row: dict) -> dict:
    case = {
        "id": case_id,
        "anchor_date": row.get("anchor_date"),
        "input": row["input"],
        "expected": row["output"],
    }
    if "context" in row:
        case["context"] = row["context"]
    return case


def collect_lane(
    label: str,
    maker,
    count: int,
    prefix: str,
    start_index: int,
    rng: random.Random,
    training_signatures: set[str],
    used_signatures: set[str],
) -> tuple[list[dict], int, int]:
    """Generate ``count`` unique held-out cases for one lane / domain.

    Falls back to allowing training-overlap rows after a high attempt budget,
    matching the v2 eval generator's behavior when fresh held-out rows are
    exhausted. Returns (cases, next_index, training_overlap_count).
    """
    cases: list[dict] = []
    overlap_count = 0
    next_index = start_index
    attempts = 0
    allow_training_overlap = False
    max_attempts = max(count * 500, 500)
    while len(cases) < count:
        anchor = pick_anchor(rng)
        mode = pick_mode(rng)
        row = maker(anchor, mode, rng)
        case = make_eval_case(f"{prefix}_{label}_{next_index:03d}", row)
        sig = canonical_key(case)
        if sig in used_signatures:
            attempts += 1
            if attempts >= max_attempts:
                raise RuntimeError(
                    f"Could not collect {count} unique cases for {prefix}/{label}. "
                    f"Got {len(cases)} after {attempts} attempts."
                )
            continue
        if not allow_training_overlap and sig in training_signatures:
            attempts += 1
            if attempts >= max_attempts:
                allow_training_overlap = True
                attempts = 0
            continue
        cases.append(case)
        used_signatures.add(sig)
        if sig in training_signatures:
            overlap_count += 1
        next_index += 1
        attempts = 0
    return cases, next_index, overlap_count


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_readme(
    total_cases: int,
    write_per_lane: int,
    query_per_domain: int,
    followup_count: int,
) -> str:
    return f"""Held-out evaluation set for the v2 parser schema.

Purpose:
- evaluate any v2-trained adapter against unseen rows using the same v2
  parse_query disposition contract (accept / clarify / reject) and the same
  uniform field set
- carry per-row ``anchor_date`` so the eval harness can inject
  ``Today: <YYYY-MM-DD>`` into the system prompt the same way training did

Format:
- ``heldout_cases.jsonl``
- one JSON object per line
- fields:
  - ``id``
  - ``anchor_date`` (YYYY-MM-DD, one of the 5 v2 anchors)
  - ``input``
  - optional ``context`` (parse_followup_query only)
  - ``expected``

Tasks covered:
- ``parse_write``  -> v1-shape output (lane, disposition, reason_code, records)
- ``parse_query`` -> v2 uniform output (disposition + clarify_reason +
  clarify_options + reason_code in addition to intent / dates / filters)
- ``parse_followup_query`` -> v2 uniform output + ``inherit_context: true``

Anchors (per dataset_v2_plan.md Section 7.1, day-of-month randomized per row):
  2026-01-XX, 2026-03-XX, 2026-05-XX, 2026-08-XX, 2026-11-XX

Size:
- ``{total_cases}`` total cases
- ``{write_per_lane * len(WRITE_PLAN)}`` write ({write_per_lane} per lane)
- ``{query_per_domain * len(QUERY_PLAN)}`` query ({query_per_domain} per domain)
- ``{followup_count}`` follow-up

Configuring size at generation time:
- ``--total <N>``: target total cases. Distributes proportionally as 40%
  writes / 42% queries / 18% followups, with a hard floor of 1 row per
  lane / domain so every file is represented even at small totals.
  Common picks: ``--total 50`` (~47 rows, Colab-cheap), ``--total 100``
  (exactly 100), ``--total 500`` (exactly 500, historical default).
- ``--write-per-lane`` / ``--query-per-domain`` / ``--followup-count``
  override individual buckets (win over ``--total``).
- Run with ``--report`` first to preview the resolved per-bucket counts
  without writing files.

Important notes:
- generated with a separate eval seed; rows are checked against
  ``synthetic_finetune_dataset_v4_v2_schema/`` (the v2 training dataset) when
  it exists; if it does not, no overlap check is applied
- limited training-overlap fallback may engage if a lane runs out of fresh
  unique rows; the count is reported at generation time
- v3 does NOT use the v1 coverage-bucket fronting interleave; it relies on
  the v2 maker's own per-form weights and a global shuffle

Example usage:

```bash
python evaluate_finetune.py \\
  --dataset eval_finetune_dataset_v3_schema_frozen/heldout_cases.jsonl \\
  --base-model unsloth/Qwen3-1.7B-bnb-4bit \\
  --finetuned-model /content/drive/MyDrive/unsloth_qwen3_parser_run/lora_adapter \\
  --finetuned-base-model unsloth/Qwen3-1.7B-bnb-4bit \\
  --output-dir /content/drive/MyDrive/unsloth_eval_run
```
"""


def report(args: argparse.Namespace, training_signatures: set[str]) -> None:
    rng = random.Random(args.seed)
    used: set[str] = set()
    final_total = (
        args.write_per_lane * len(WRITE_PLAN)
        + args.query_per_domain * len(QUERY_PLAN)
        + args.followup_count
    )
    print(f"v3 eval generator report  (seed={args.seed})")
    print(f"out_dir          : {args.out_dir}")
    print(f"train_root       : {args.train_root} (exists={Path(args.train_root).exists()})")
    print(f"training_sigs    : {len(training_signatures)} signatures loaded")
    print(f"anchor_months    : {[f'{y:04d}-{m:02d}' for y, m in ANCHOR_MONTHS]}")
    print(f"anchor_day       : randomized per row (uniform within month)")
    if args.total is not None:
        print(f"--total          : {args.total} (proportional split: writes 40% / queries 42% / followups 18%)")
    print(f"write_per_lane   : {args.write_per_lane}  -> {args.write_per_lane * len(WRITE_PLAN)} write rows")
    print(f"query_per_domain : {args.query_per_domain}  -> {args.query_per_domain * len(QUERY_PLAN)} query rows")
    print(f"followup_count   : {args.followup_count}")
    print(f"final total rows : {final_total}")
    print()

    # Tiny smoke samples per lane / domain for the report.
    smoke_n = 40
    print(f"smoke samples (n={smoke_n} per lane / domain) - per-anchor & per-disposition counts")
    for label, maker in WRITE_PLAN:
        anchors_seen: Counter = Counter()
        disp: Counter = Counter()
        for _ in range(smoke_n):
            row = maker(pick_anchor(rng), pick_mode(rng), rng)
            anchors_seen[row.get("anchor_date")] += 1
            disp[row["output"].get("disposition")] += 1
        print(f"  parse_write/{label:<7}  anchors={dict(anchors_seen)}  dispositions={dict(disp)}")
    for label, maker in QUERY_PLAN:
        anchors_seen: Counter = Counter()
        disp: Counter = Counter()
        intents: Counter = Counter()
        for _ in range(smoke_n):
            row = maker(pick_anchor(rng), pick_mode(rng), rng)
            anchors_seen[row.get("anchor_date")] += 1
            disp[row["output"].get("disposition")] += 1
            intents[row["output"].get("intent")] += 1
        print(f"  parse_query/{label:<7}  anchors={dict(anchors_seen)}  dispositions={dict(disp)}  intents={dict(intents)}")
    for label, maker in FOLLOWUP_PLAN:
        anchors_seen: Counter = Counter()
        domains: Counter = Counter()
        for _ in range(smoke_n):
            row = maker(pick_anchor(rng), pick_mode(rng), rng)
            anchors_seen[row.get("anchor_date")] += 1
            domains[row["output"].get("domain")] += 1
        print(f"  parse_followup_query/{label:<7}  anchors={dict(anchors_seen)}  domains={dict(domains)}")

    print()
    print("sample rows (first row per lane / domain) -")
    for label, maker in WRITE_PLAN + QUERY_PLAN + FOLLOWUP_PLAN:
        row = maker(pick_anchor(rng), pick_mode(rng), rng)
        case = make_eval_case(f"sample_{label}_001", row)
        print(f"  {label}: {json.dumps(case, ensure_ascii=False)[:240]}")


def main() -> None:
    args = parse_args()
    training_signatures = load_training_signatures(Path(args.train_root))
    if args.report:
        report(args, training_signatures)
        return

    rng = random.Random(args.seed)
    used_signatures: set[str] = set()
    next_index = 1

    write_groups: dict[str, list[dict]] = {}
    write_overlap = 0
    for label, maker in WRITE_PLAN:
        rows, next_index, overlap = collect_lane(
            label,
            maker,
            args.write_per_lane,
            "write_v3",
            next_index,
            rng,
            training_signatures,
            used_signatures,
        )
        write_groups[label] = rows
        write_overlap += overlap

    query_groups: dict[str, list[dict]] = {}
    query_overlap = 0
    for label, maker in QUERY_PLAN:
        rows, next_index, overlap = collect_lane(
            label,
            maker,
            args.query_per_domain,
            "query_v3",
            next_index,
            rng,
            training_signatures,
            used_signatures,
        )
        query_groups[label] = rows
        query_overlap += overlap

    followup_groups: dict[str, list[dict]] = {}
    followup_overlap = 0
    for label, maker in FOLLOWUP_PLAN:
        rows, next_index, overlap = collect_lane(
            label,
            maker,
            args.followup_count,
            "followup_v3",
            next_index,
            rng,
            training_signatures,
            used_signatures,
        )
        followup_groups[label] = rows
        followup_overlap += overlap

    # Per-form weights drive the within-maker diversity. We do a single global
    # shuffle here so a smaller --limit smoke run still hits multiple lanes /
    # domains rather than only the leading one. No coverage-bucket fronting.
    cases: list[dict] = []
    for groups in (write_groups, query_groups, followup_groups):
        for rows in groups.values():
            cases.extend(rows)
    rng.shuffle(cases)

    out_dir = Path(args.out_dir)
    out_path = out_dir / "heldout_cases.jsonl"
    readme_path = out_dir / "README.md"
    write_jsonl(out_path, cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(
        build_readme(len(cases), args.write_per_lane, args.query_per_domain, args.followup_count),
        encoding="utf-8",
    )

    anchor_counts = Counter(case.get("anchor_date") for case in cases)
    disp_counts = Counter()
    for case in cases:
        expected = case.get("expected") or {}
        disp_counts[(expected.get("task"), expected.get("disposition"))] += 1

    print(f"Wrote {len(cases)} cases to {out_path}")
    print(f"Anchor distribution: {dict(sorted(anchor_counts.items()))}")
    print(f"Task / disposition distribution: {dict(disp_counts)}")
    print(
        f"Training-overlap fallback used for "
        f"{write_overlap + query_overlap + followup_overlap} eval rows "
        f"(write={write_overlap}, query={query_overlap}, followup={followup_overlap})."
    )


if __name__ == "__main__":
    main()
