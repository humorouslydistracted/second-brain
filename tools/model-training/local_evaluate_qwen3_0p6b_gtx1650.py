import argparse
import gc
import json
from pathlib import Path

import torch

import evaluate_finetune as base_eval


DEFAULT_DATASET = "eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl"
DEFAULT_BASE_MODEL = "unsloth/Qwen3-0.6B-unsloth-bnb-4bit"
DEFAULT_FINETUNED_MODEL = "local_runs/qwen3_0p6b_gtx1650/lora_adapter"
DEFAULT_OUTPUT_DIR = "local_runs/qwen3_0p6b_gtx1650/eval"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Laptop-safe evaluator defaults for Qwen3-0.6B local runs."
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help="Path to held-out eval dataset jsonl.",
    )
    parser.add_argument(
        "--base-model",
        default=DEFAULT_BASE_MODEL,
        help="Base model name or local path.",
    )
    parser.add_argument(
        "--finetuned-model",
        default=DEFAULT_FINETUNED_MODEL,
        help="Fine-tuned full model path, or LoRA adapter path.",
    )
    parser.add_argument(
        "--finetuned-base-model",
        default=DEFAULT_BASE_MODEL,
        help="Base model name to use when --finetuned-model points to an adapter directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save predictions and summaries.",
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=512,
        help="Model max sequence length.",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=192,
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
        default=200,
        help="Optional number of cases to run. Default 200 for laptop-friendly evaluation.",
    )
    parser.add_argument(
        "--skip-base",
        action="store_true",
        help="Skip base-model evaluation.",
    )
    parser.add_argument(
        "--skip-finetuned",
        action="store_true",
        help="Skip fine-tuned model evaluation.",
    )
    args = parser.parse_args()
    if args.skip_base:
        args.base_model = None
    if args.skip_finetuned:
        args.finetuned_model = None
    if not args.base_model and not args.finetuned_model:
        parser.error("Both base and fine-tuned evaluation were disabled.")
    return args


def main():
    args = parse_args()
    cases = base_eval.load_cases(args.dataset)
    if args.limit is not None and args.limit > 0:
        cases = cases[: args.limit]

    if args.finetuned_model and not Path(args.finetuned_model).exists():
        print(
            f"Fine-tuned model path not found: {args.finetuned_model}. "
            "Skipping fine-tuned evaluation."
        )
        args.finetuned_model = None

    summaries = {}
    if args.base_model:
        summaries["base"] = base_eval.evaluate_model("base", args.base_model, cases, args)
    if args.finetuned_model:
        summaries["finetuned"] = base_eval.evaluate_model("finetuned", args.finetuned_model, cases, args)

    combined_path = Path(args.output_dir) / "combined_summary.json"
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    with combined_path.open("w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)

    print(f"\nSaved combined summary to: {combined_path}")
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
