import argparse
import gc
import json
from pathlib import Path

# Heavy GPU-only imports (unsloth / torch / peft) live inside evaluate_model so
# this module can still be imported from a CPU-only env for offline scoring
# tests against existing predictions.jsonl files.


SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""


def build_system_prompt(anchor_date):
    if anchor_date:
        return f"{SYSTEM_PROMPT}\n\nToday: {anchor_date}"
    return SYSTEM_PROMPT


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate base and/or fine-tuned Qwen parser models on held-out app cases."
    )
    parser.add_argument(
        "--dataset",
        default="eval_finetune_dataset_v3_schema_frozen/heldout_cases.jsonl",
        help="Path to held-out eval dataset jsonl.",
    )
    parser.add_argument(
        "--base-model",
        default=None,
        help="Base model name or local path, for example unsloth/Qwen3-1.7B-bnb-4bit",
    )
    parser.add_argument(
        "--finetuned-model",
        default=None,
        help="Fine-tuned full model path, or LoRA adapter path.",
    )
    parser.add_argument(
        "--finetuned-base-model",
        default=None,
        help="Base model name to use when --finetuned-model points to an adapter directory, for example unsloth/Qwen3-1.7B-bnb-4bit.",
    )
    parser.add_argument(
        "--output-dir",
        default="eval_run_outputs",
        help="Directory to save predictions and summaries.",
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=2048,
        help="Model max sequence length.",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=256,
        help="Generation cap per example.",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help="Optional Hugging Face token.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of cases to run.",
    )
    args = parser.parse_args()
    if not args.base_model and not args.finetuned_model:
        parser.error("Provide at least one of --base-model or --finetuned-model")
    return args


def resolve_existing_path(path_value):
    path = Path(path_value)
    if path.exists():
        return path
    if not path.is_absolute():
        script_relative = SCRIPT_DIR / path
        if script_relative.exists():
            return script_relative
    return path


def resolve_output_path(path_value):
    path = Path(path_value)
    if path.is_absolute():
        return path
    return SCRIPT_DIR / path


def load_cases(path):
    path = resolve_existing_path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    cases = []
    legacy_schema_rows = 0
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "id" not in row or "input" not in row or "expected" not in row:
                raise ValueError(f"Missing required fields in {path}:{line_no}")
            expected = row["expected"]
            if any(
                legacy_key in expected
                for legacy_key in ("date_refs", "date_text", "due_date_text")
            ):
                legacy_schema_rows += 1
            cases.append(row)
    if legacy_schema_rows:
        print(
            f"Warning: {legacy_schema_rows} eval rows look like legacy schema rows "
            f"in {path}. Results will still run, but a schema-aligned held-out set is recommended."
        )
    return cases


def expected_has_any(expected, *keys):
    return any(key in expected for key in keys)


def build_user_text(case):
    user_text = case["input"].strip()
    if "context" in case:
        context_text = json.dumps(
            case["context"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        user_text = (
            "Previous structured query context:\n"
            f"{context_text}\n\n"
            "User input:\n"
            f"{user_text}"
        )
    return user_text


def normalize_json(value):
    if isinstance(value, dict):
        return {key: normalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    return value


def safe_json_loads(text):
    text = text.strip()
    if not text:
        return None, "empty_output"
    try:
        return json.loads(text), None
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate), None
        except Exception as exc:
            return None, f"json_parse_error: {exc}"
    return None, "no_json_object_found"


def compare_record_field(expected_records, predicted_records, field_name):
    if not isinstance(predicted_records, list):
        return False
    if len(expected_records) != len(predicted_records):
        return False
    expected_values = [record.get(field_name) for record in expected_records]
    predicted_values = [record.get(field_name) for record in predicted_records]
    return expected_values == predicted_values


def compare_query_range(expected, predicted, start_key, end_key):
    if start_key not in expected and end_key not in expected:
        return None
    return predicted.get(start_key) == expected.get(start_key) and predicted.get(end_key) == expected.get(end_key)


def score_prediction(expected, predicted):
    metrics = {
        "valid_json": predicted is not None,
        "exact_match": False,
        "task_match": None,
        "lane_or_domain_match": None,
        "disposition_match": None,
        "reason_code_match": None,
        "clarify_reason_match": None,
        "clarify_options_match": None,
        "intent_match": None,
        "record_count_match": None,
        "ledger_action_match": None,
        "amounts_match": None,
        "weight_values_match": None,
        "write_dates_match": None,
        "unit_text_match": None,
        "query_date_range_match": None,
        "compare_range_match": None,
        "filters_match": None,
        "limit_match": None,
        "query_text_match": None,
        "inherit_context_match": None,
    }

    if predicted is None:
        return metrics

    metrics["exact_match"] = normalize_json(predicted) == normalize_json(expected)
    metrics["task_match"] = predicted.get("task") == expected.get("task")

    task = expected.get("task")
    if task == "parse_write":
        metrics["lane_or_domain_match"] = predicted.get("lane") == expected.get("lane")
        if expected_has_any(expected, "disposition"):
            metrics["disposition_match"] = predicted.get("disposition") == expected.get("disposition")
        if expected_has_any(expected, "reason_code"):
            metrics["reason_code_match"] = predicted.get("reason_code") == expected.get("reason_code")
        expected_records = expected.get("records", [])
        predicted_records = predicted.get("records")
        metrics["record_count_match"] = (
            isinstance(predicted_records, list) and len(predicted_records) == len(expected_records)
        )
        if expected_records and isinstance(predicted_records, list):
            if any("date" in record for record in expected_records):
                metrics["write_dates_match"] = compare_record_field(
                    expected_records, predicted_records, "date"
                )
            if any("unit_text" in record for record in expected_records):
                metrics["unit_text_match"] = compare_record_field(
                    expected_records, predicted_records, "unit_text"
                )

        lane = expected.get("lane")
        if lane == "ledger":
            field_name = "action" if any("action" in record for record in expected_records) else "direction"
            metrics["ledger_action_match"] = compare_record_field(
                expected_records, predicted_records, field_name
            )
            metrics["amounts_match"] = compare_record_field(
                expected_records, predicted_records, "amount"
            )
        elif lane == "expense":
            metrics["amounts_match"] = compare_record_field(
                expected_records, predicted_records, "amount"
            )
        elif lane == "weight":
            metrics["weight_values_match"] = compare_record_field(
                expected_records, predicted_records, "value"
            )
    else:
        # parse_query / parse_followup_query. v2 rows carry a uniform field set
        # (disposition, reason_code, clarify_reason, clarify_options) across
        # accept / clarify / reject; v1 rows do not have these fields. Score
        # each new field only when expected exposes it, so v1 eval rows still
        # run cleanly through this branch.
        metrics["lane_or_domain_match"] = predicted.get("domain") == expected.get("domain")
        metrics["intent_match"] = predicted.get("intent") == expected.get("intent")
        metrics["query_date_range_match"] = compare_query_range(expected, predicted, "date_start", "date_end")
        metrics["compare_range_match"] = compare_query_range(
            expected, predicted, "compare_date_start", "compare_date_end"
        )
        metrics["filters_match"] = predicted.get("filters") == expected.get("filters")
        metrics["limit_match"] = predicted.get("limit") == expected.get("limit")
        metrics["query_text_match"] = predicted.get("query_text") == expected.get("query_text")
        if expected_has_any(expected, "disposition"):
            metrics["disposition_match"] = predicted.get("disposition") == expected.get("disposition")
        if expected_has_any(expected, "reason_code"):
            metrics["reason_code_match"] = predicted.get("reason_code") == expected.get("reason_code")
        if expected_has_any(expected, "clarify_reason"):
            metrics["clarify_reason_match"] = (
                predicted.get("clarify_reason") == expected.get("clarify_reason")
            )
        if expected_has_any(expected, "clarify_options"):
            metrics["clarify_options_match"] = (
                predicted.get("clarify_options") == expected.get("clarify_options")
            )
        if task == "parse_followup_query":
            metrics["inherit_context_match"] = (
                predicted.get("inherit_context") == expected.get("inherit_context")
            )

    return metrics


def format_rate(correct, applicable):
    if not applicable:
        return None
    return round((correct / applicable) * 100.0, 2)


def summarize_rows(rows):
    summary = {
        "total_cases": len(rows),
        "metrics": {},
        "task_breakdown": {},
    }

    metric_names = [
        "valid_json",
        "exact_match",
        "task_match",
        "lane_or_domain_match",
        "disposition_match",
        "reason_code_match",
        "clarify_reason_match",
        "clarify_options_match",
        "intent_match",
        "record_count_match",
        "ledger_action_match",
        "amounts_match",
        "weight_values_match",
        "write_dates_match",
        "unit_text_match",
        "query_date_range_match",
        "compare_range_match",
        "filters_match",
        "limit_match",
        "query_text_match",
        "inherit_context_match",
    ]

    for metric_name in metric_names:
        applicable = 0
        correct = 0
        for row in rows:
            value = row["metrics"][metric_name]
            if value is None:
                continue
            applicable += 1
            if value:
                correct += 1
        summary["metrics"][metric_name] = {
            "correct": correct,
            "applicable": applicable,
            "rate_percent": format_rate(correct, applicable),
        }

    by_task = {}
    for row in rows:
        task = row["expected"]["task"]
        by_task.setdefault(task, {"total": 0, "exact_match": 0, "valid_json": 0})
        by_task[task]["total"] += 1
        if row["metrics"]["exact_match"]:
            by_task[task]["exact_match"] += 1
        if row["metrics"]["valid_json"]:
            by_task[task]["valid_json"] += 1

    for task, counts in by_task.items():
        summary["task_breakdown"][task] = {
            "total": counts["total"],
            "valid_json": counts["valid_json"],
            "valid_json_rate_percent": format_rate(counts["valid_json"], counts["total"]),
            "exact_match": counts["exact_match"],
            "exact_match_rate_percent": format_rate(counts["exact_match"], counts["total"]),
        }

    return summary


def print_summary(label, summary, rows, max_failures=8):
    print(f"\n=== {label} ===")
    print(f"Total cases: {summary['total_cases']}")

    preferred_metrics = [
        "valid_json",
        "exact_match",
        "task_match",
        "lane_or_domain_match",
        "disposition_match",
        "reason_code_match",
        "clarify_reason_match",
        "clarify_options_match",
        "intent_match",
        "record_count_match",
        "ledger_action_match",
        "amounts_match",
        "weight_values_match",
        "write_dates_match",
        "unit_text_match",
        "query_date_range_match",
        "compare_range_match",
        "filters_match",
        "inherit_context_match",
    ]
    for metric_name in preferred_metrics:
        metric = summary["metrics"][metric_name]
        if metric["applicable"] == 0:
            continue
        rate = metric["rate_percent"]
        print(
            f"{metric_name}: {metric['correct']}/{metric['applicable']} "
            f"({rate}%)"
        )

    failures = [row for row in rows if not row["metrics"]["exact_match"]]
    if failures:
        print("\nFirst exact-match failures:")
        for row in failures[:max_failures]:
            print(f"- {row['id']}")
            print(f"  raw_output: {row['raw_output']}")


def save_jsonl(path, rows):
    path = resolve_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def evaluate_model(label, model_name, cases, args):
    import unsloth  # noqa: F401
    import torch
    from peft import PeftModel
    from unsloth import FastLanguageModel

    print(f"\nLoading model for {label}: {model_name}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    adapter_path = resolve_existing_path(model_name)
    use_adapter_loading = (
        label == "finetuned"
        and args.finetuned_base_model
        and adapter_path.exists()
        and (adapter_path / "adapter_config.json").exists()
    )

    if use_adapter_loading:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=args.finetuned_base_model,
            max_seq_length=args.max_seq_length,
            load_in_4bit=True,
            load_in_8bit=False,
            full_finetuning=False,
            token=args.hf_token,
        )
        model = PeftModel.from_pretrained(model, str(adapter_path), is_trainable=False)
    else:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(adapter_path) if adapter_path.exists() else model_name,
            max_seq_length=args.max_seq_length,
            load_in_4bit=True,
            load_in_8bit=False,
            full_finetuning=False,
            token=args.hf_token,
        )
    FastLanguageModel.for_inference(model)

    rows = []
    for case in cases:
        user_text = build_user_text(case)
        messages = [
            {"role": "system", "content": build_system_prompt(case.get("anchor_date"))},
            {"role": "user", "content": user_text},
        ]
        prompt_text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = tokenizer(prompt_text, return_tensors="pt").to(device)
        outputs = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )
        generated = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        ).strip()
        parsed_output, parse_error = safe_json_loads(generated)
        metrics = score_prediction(case["expected"], parsed_output)

        rows.append(
            {
                "id": case["id"],
                "input": case["input"],
                "context": case.get("context"),
                "expected": case["expected"],
                "raw_output": generated,
                "parsed_output": parsed_output,
                "parse_error": parse_error,
                "metrics": metrics,
            }
        )

    summary = summarize_rows(rows)

    output_dir = resolve_output_path(args.output_dir) / label
    output_dir.mkdir(parents=True, exist_ok=True)
    save_jsonl(output_dir / "predictions.jsonl", rows)
    with (output_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print_summary(label, summary, rows)

    del model
    del tokenizer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return summary


def main():
    args = parse_args()
    cases = load_cases(args.dataset)
    if args.limit is not None:
        cases = cases[: args.limit]

    summaries = {}
    if args.base_model:
        summaries["base"] = evaluate_model("base", args.base_model, cases, args)
    if args.finetuned_model:
        summaries["finetuned"] = evaluate_model("finetuned", args.finetuned_model, cases, args)

    combined_path = resolve_output_path(args.output_dir) / "combined_summary.json"
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    with combined_path.open("w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)

    print(f"\nSaved combined summary to: {combined_path}")


if __name__ == "__main__":
    main()
