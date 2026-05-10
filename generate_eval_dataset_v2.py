from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from generate_large_schema_frozen_dataset import (
    COVERAGE_BUCKETS,
    COVERAGE_CLASSIFIERS,
    SEED,
    build_coverage_targets,
    make_buy_query,
    make_buy_write,
    make_expense_query,
    make_expense_write,
    make_followup,
    make_ledger_query,
    make_ledger_write,
    make_note_query,
    round_robin_merge,
    make_todo_query,
    make_todo_write,
    make_weight_query,
    make_weight_write,
)


OUT_DIR = Path("eval_finetune_dataset_v2_schema_frozen")
TRAIN_ROOT = Path("synthetic_finetune_dataset_v3_large_india_first")
EVAL_SEED = SEED + 7001
WRITE_PER_LANE = 40
QUERY_PER_LANE = 35
FOLLOWUP_COUNT = 90


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(OUT_DIR), help="Output directory for the held-out eval set.")
    parser.add_argument("--train-root", default=str(TRAIN_ROOT), help="Training dataset root used for overlap checks.")
    parser.add_argument("--write-per-lane", type=int, default=WRITE_PER_LANE, help="Held-out write cases per write lane.")
    parser.add_argument("--query-per-lane", type=int, default=QUERY_PER_LANE, help="Held-out query cases per query lane.")
    parser.add_argument("--followup-count", type=int, default=FOLLOWUP_COUNT, help="Held-out follow-up cases.")
    return parser.parse_args()


def canonical_case(case: dict) -> str:
    return json.dumps(case, ensure_ascii=False, sort_keys=True)


def pick_mode(rng: random.Random) -> str:
    return "india" if rng.random() < 0.7 else "global"


def range_text(expected: dict) -> str | None:
    start = expected.get("date_start")
    end = expected.get("date_end")
    if start is None and end is None:
        return None
    if start == end:
        return f"on {start}"
    return f"from {start} to {end}"


def compare_range_text(expected: dict) -> str | None:
    start = expected.get("compare_date_start")
    end = expected.get("compare_date_end")
    if start is None and end is None:
        return None
    if start == end:
        return f"on {start}"
    return f"from {start} to {end}"


def paraphrase_query_input(
    expected: dict,
    rng: random.Random,
    source_input: str | None = None,
    coverage_bucket: str | None = None,
) -> str:
    domain = expected["domain"]
    intent = expected["intent"]
    filters = expected.get("filters", {}) or {}
    date_text = range_text(expected)
    compare_text = compare_range_text(expected)
    tanglish = rng.random() < 0.22

    if coverage_bucket in {"scoped", "scoped_search", "typo_search", "day_yesterday"} and source_input:
        return source_input

    if domain == "expense":
        group = filters.get("group")
        desc = filters.get("description_text")
        ex_group = filters.get("exclude_group")
        ex_desc = filters.get("exclude_description_text")
        if intent == "compare":
            if group:
                text = f"compare {group} spending {date_text} against {compare_text}"
            else:
                text = f"compare my expense totals {date_text} against {compare_text}"
            if tanglish:
                text = text.replace("compare", "compare pannu")
            return "ask: " + text
        if group and intent == "total":
            text = f"sum up {group} spending {date_text}"
            if tanglish:
                text = f"{group} expense {date_text.replace('from ', '').replace(' to ', ' - ')} evalo"
            return "ask: " + text
        if desc and intent == "total":
            text = f"how much did I spend on {desc} {date_text}"
            if tanglish:
                text = f"{desc} ku {date_text.replace('from ', '').replace(' to ', ' - ')} evlo pochu"
            return "ask: " + text
        if ex_group:
            return "ask: " + (f"list my expenses excluding {ex_group} {date_text}" if not tanglish else f"{ex_group} thavira expense {date_text.replace('from ', '').replace(' to ', ' - ')} kaatu")
        if ex_desc:
            return "ask: " + (f"list my expenses excluding {ex_desc} {date_text}" if not tanglish else f"{ex_desc} thavira expense {date_text.replace('from ', '').replace(' to ', ' - ')} kaatu")
        if expected.get("limit") == 10 and intent == "list" and expected.get("date_start") is None:
            return "ask: " + ("list my last 10 expense entries" if not tanglish else "kadasiya 10 expense entries kaatu")
        if intent == "total":
            return "ask: " + (f"tell me my total spending {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} total expense evalo")
        return "ask: " + (f"show my expense entries {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} expense list kaatu")

    if domain == "buy":
        item = filters.get("item_text")
        status = filters.get("status")
        if intent == "search" and item:
            return "ask: " + (f"check whether {item} is present in my buy list" if not tanglish else f"buy list la {item} irukka")
        if date_text:
            status_text = "open " if status == "open" else "done " if status == "done" else ""
            return "ask: " + (f"show {status_text}buy items {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} {status_text}buy items kaatu")
        return "ask: " + ("show the current buy list" if not tanglish else "current buy list kaatu")

    if domain == "todo":
        text_match = filters.get("text_match")
        status = filters.get("status")
        if intent == "search" and text_match:
            return "ask: " + (f"find todo items matching {text_match}" if not tanglish else f"{text_match} related todo kaatu")
        if intent == "history":
            return "ask: " + ("show the latest 10 todo history entries" if not tanglish else "latest 10 todo history kaatu")
        if date_text:
            if status == "done":
                return "ask: " + (f"show completed tasks {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} mudicha tasks kaatu")
            return "ask: " + (f"show open tasks {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} open tasks kaatu")
        if status is None:
            return "ask: " + ("show todos regardless of status" if not tanglish else "ella todos kaatu")
        return "ask: " + ("list all open todo items" if not tanglish else "open todo items kaatu")

    if domain == "weight":
        person = filters.get("person_text")
        if intent == "latest_all":
            return "ask: " + ("show the latest weight for every tracked person" if not tanglish else "ellar latest weight kaatu")
        subject = "me" if person == "self" else person
        if intent == "latest":
            return "ask: " + (f"give me the latest weight for {subject}" if not tanglish else f"{'en' if person == 'self' else person} latest weight enna")
        if intent == "history":
            return "ask: " + (f"show weight history for {subject} {date_text}" if not tanglish else f"{'en' if person == 'self' else person} weight history {date_text.replace('from ', '').replace(' to ', ' - ')} kaatu")
        if intent == "trend":
            return "ask: " + (f"show the weight trend for {subject} {date_text}" if not tanglish else f"{'en' if person == 'self' else person} weight trend kaatu")
        return "ask: " + (f"how much has {subject} changed {date_text}" if not tanglish else f"{'en' if person == 'self' else person} weight {date_text.replace('from ', '').replace(' to ', ' - ')} evalo maari irukku")

    if domain == "ledger":
        person = filters.get("person_text")
        perspective = filters.get("perspective")
        status = filters.get("status")
        if intent == "balance" and person and perspective == "i_owe_them":
            return "ask: " + (f"what is my current open balance with {person} on the I-owe side" if not tanglish else f"{person} ku naan ippo evlo kuduikanum")
        if intent == "balance" and person and perspective == "they_owe_me":
            return "ask: " + (f"what is {person}'s current open balance toward me" if not tanglish else f"{person} ippo enaku evlo tharanum")
        if intent == "open_summary":
            if perspective == "they_owe_me":
                return "ask: " + ("list everyone who currently owes me money" if not tanglish else "yaar ellam enaku kaasu tharanum")
            if perspective == "i_owe_them":
                return "ask: " + ("list everyone I currently owe money to" if not tanglish else "naan yaar yaarukku kaasu kuduikanum")
            return "ask: " + ("show only the current open ledger balances" if not tanglish else "current open ledger balances kaatu")
        if intent == "settled_list":
            if person:
                return "ask: " + (f"show settled ledger records for {person}" if not tanglish else f"{person} settled ledger kaatu")
            return "ask: " + ("show all settled ledger records" if not tanglish else "settled ledger records kaatu")
        if intent == "latest_balance":
            return "ask: " + ("show the most recently changed ledger balance" if not tanglish else "latest maari irukka ledger balance kaatu")
        if person and status == "open":
            return "ask: " + (f"show the open ledger details for {person}" if not tanglish else f"{person} open ledger details kaatu")
        if date_text:
            return "ask: " + (f"show ledger entries {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} ledger entries kaatu")
        if person:
            return "ask: " + (f"show ledger history and summary for {person}" if not tanglish else f"{person} ledger history um summary um kaatu")
        return "ask: " + ("show the 10 most recent ledger entries" if not tanglish else "recent ledger entries kaatu")

    if domain == "note":
        q = expected.get("query_text")
        if intent == "latest_bucket":
            return "ask: " + ("show the latest note bucket" if not tanglish else "latest note bucket kaatu")
        if intent == "day_bucket":
            return "ask: " + (f"show notes {date_text}" if not tanglish else f"{date_text.replace('on ', '').replace('from ', '').replace(' to ', ' - ')} notes kaatu")
        if intent == "recent":
            return "ask: " + (f"show note buckets {date_text}" if not tanglish else f"{date_text.replace('from ', '').replace(' to ', ' - ')} notes kaatu")
        return "ask: " + (f"find notes related to {q}" if not tanglish else f"{q} pathi notes thedu")

    return "ask: " + expected["domain"]


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
                    row = json.loads(line)
                    case = {
                        "input": row["input"],
                        "expected": row["output"],
                    }
                    if "context" in row:
                        case["context"] = row["context"]
                    signatures.add(canonical_case(case))
    return signatures


def make_case(case_id: str, row: dict, coverage_bucket: str | None = None) -> dict:
    case = {
        "id": case_id,
        "input": row["input"],
        "expected": row["output"],
    }
    if coverage_bucket is not None:
        case["coverage_bucket"] = coverage_bucket
    if "context" in row:
        case["context"] = row["context"]
    return case


def classify_case_bucket(case: dict, coverage_key: str) -> str:
    row = {
        "input": case["input"],
        "output": case["expected"],
    }
    if "context" in case:
        row["context"] = case["context"]
    return COVERAGE_CLASSIFIERS[coverage_key](row)


def collect_cases(
    plan,
    prefix: str,
    start_index: int,
    rng: random.Random,
    training_signatures: set[str],
    used_signatures: set[str],
) -> tuple[dict[str, list[dict]], int, int]:
    case_groups: dict[str, list[dict]] = {}
    current_index = start_index
    overlap_count = 0
    for label, maker, count in plan:
        if prefix.startswith("write_"):
            coverage_key = f"parse_write/{label}"
        elif prefix.startswith("query_"):
            coverage_key = f"parse_query/{label}"
        else:
            coverage_key = "parse_followup_query/mixed_followups"
        coverage_buckets = COVERAGE_BUCKETS[coverage_key]
        coverage_targets = build_coverage_targets(count, coverage_buckets, rng, passes=1)
        lane_cases: list[dict] = []
        attempts = 0
        allow_training_overlap = False
        target_index = 0
        max_attempts = max(count * 500, len(coverage_targets) * 500)
        while len(lane_cases) < count:
            mode = pick_mode(rng)
            row = maker(mode, rng)
            case = make_case(f"{prefix}_{label}_{current_index:03d}", row)
            if case["expected"]["task"] == "parse_query":
                raw_bucket = COVERAGE_CLASSIFIERS[coverage_key](row)
                case["input"] = paraphrase_query_input(
                    case["expected"],
                    rng,
                    source_input=row["input"],
                    coverage_bucket=raw_bucket,
                )
            bucket = classify_case_bucket(case, coverage_key)
            if target_index < len(coverage_targets) and bucket != coverage_targets[target_index]:
                attempts += 1
                if attempts >= max_attempts:
                    if not allow_training_overlap:
                        allow_training_overlap = True
                        attempts = 0
                        continue
                    raise RuntimeError(
                        f"Could not collect enough coverage cases for {prefix}/{label}. "
                        f"Stopped on coverage bucket {coverage_targets[target_index]!r} after {attempts} attempts."
                    )
                continue
            case["coverage_bucket"] = bucket
            signature = canonical_case({
                "input": case["input"],
                "expected": case["expected"],
                **({"context": case["context"]} if "context" in case else {}),
            })
            if signature in used_signatures:
                attempts += 1
                if attempts >= max_attempts:
                    raise RuntimeError(
                        f"Could not collect enough held-out cases for {prefix}/{label}. "
                        f"Collected {len(lane_cases)}/{count} after {attempts} attempts."
                    )
                continue
            if not allow_training_overlap and signature in training_signatures:
                attempts += 1
                if attempts >= max_attempts:
                    allow_training_overlap = True
                    attempts = 0
                continue
            lane_cases.append(case)
            used_signatures.add(signature)
            current_index += 1
            attempts = 0
            if signature in training_signatures:
                overlap_count += 1
            if target_index < len(coverage_targets):
                target_index += 1
        case_groups[label] = lane_cases
    return case_groups, current_index, overlap_count


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_readme(total_cases: int, write_per_lane: int, query_per_lane: int, followup_count: int) -> str:
    return f"""Held-out evaluation set for the frozen v1 parser schema.

Purpose:
- keep a schema-aligned unseen test set outside the training dataset
- compare base vs fine-tuned Qwen on the app parser tasks
- evaluate the current frozen schema, not the older pre-freeze format

Format:
- `heldout_cases.jsonl`
- one JSON object per line
- fields:
  - `id`
  - `input`
  - optional `context`
  - `expected`

Tasks covered:
- `parse_write`
- `parse_query`
- `parse_followup_query`

Size:
- `{total_cases}` total cases
- `{write_per_lane * len(WRITE_PLAN)}` write
- `{query_per_lane * len(QUERY_PLAN)}` query
- `{followup_count}` follow-up

Important notes:
- cases are generated with a separate eval seed
- the generator prefers rows not already present in `synthetic_finetune_dataset_v3_large_india_first/`
- if a lane runs out of fresh held-out space, limited training-overlap fallback is allowed and reported at generation time
- the file order is coverage-first: the leading prefix is intentionally interleaved so a smaller `--limit` run still touches every tool/lane and the important rare buckets before the long tail
- this dataset matches the frozen schema:
  - resolved `date_start` / `date_end`
  - optional compare ranges
  - ledger `action`
  - write `disposition` / `reason_code`

Example usage:

```bash
python evaluate_finetune.py \\
  --dataset eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl \\
  --base-model unsloth/Qwen3-1.7B-bnb-4bit \\
  --finetuned-model /content/drive/MyDrive/unsloth_qwen3_parser_run/lora_adapter \\
  --finetuned-base-model unsloth/Qwen3-1.7B-bnb-4bit \\
  --output-dir /content/drive/MyDrive/unsloth_eval_run
```
"""


def main() -> None:
    args = parse_args()
    rng = random.Random(EVAL_SEED)
    out_dir = Path(args.out_dir)
    out_path = out_dir / "heldout_cases.jsonl"
    readme_path = out_dir / "README.md"
    training_signatures = load_training_signatures(Path(args.train_root))
    used_signatures: set[str] = set()
    write_plan = [(label, maker, args.write_per_lane) for label, maker in WRITE_PLAN]
    query_plan = [(label, maker, args.query_per_lane) for label, maker in QUERY_PLAN]
    followup_plan = [(label, maker, args.followup_count) for label, maker in FOLLOWUP_PLAN]

    write_cases, next_index, write_overlap = collect_cases(
        write_plan, "write_v2", 1, rng, training_signatures, used_signatures
    )
    query_cases, next_index, query_overlap = collect_cases(
        query_plan, "query_v2", next_index, rng, training_signatures, used_signatures
    )
    followup_cases, next_index, followup_overlap = collect_cases(
        followup_plan, "followup_v2", next_index, rng, training_signatures, used_signatures
    )

    front_groups = []
    remainder_groups = []
    for group_map, prefix in ((write_cases, "write_v2"), (query_cases, "query_v2"), (followup_cases, "followup_v2")):
        for label, rows in group_map.items():
            if prefix == "write_v2":
                coverage_key = f"parse_write/{label}"
            elif prefix == "query_v2":
                coverage_key = f"parse_query/{label}"
            else:
                coverage_key = "parse_followup_query/mixed_followups"
            front_count = min(len(rows), len(COVERAGE_BUCKETS[coverage_key]))
            front_groups.append(rows[:front_count])
            remainder_groups.append(rows[front_count:])

    cases = round_robin_merge(front_groups) + round_robin_merge(remainder_groups)
    write_jsonl(out_path, cases)
    out_dir.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(
        build_readme(len(cases), args.write_per_lane, args.query_per_lane, args.followup_count),
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} cases to {out_path}")
    print(
        "Training-overlap fallback used for "
        f"{write_overlap + query_overlap + followup_overlap} eval rows "
        f"(write={write_overlap}, query={query_overlap}, followup={followup_overlap})."
    )


if __name__ == "__main__":
    main()
