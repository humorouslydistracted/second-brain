"""Local inference for the fine-tuned Qwen3-1.7B parser adapter.

Loads the LoRA adapter with the same chat template / system prompt that was
used during training and evaluation, so behavior matches what the Colab eval
already measured.

Run from a separate local GPU environment with Unsloth, bitsandbytes, peft,
and CUDA torch installed. This helper is retained for the retired Flask
prototype and is not part of the active Android build.

Examples:
    # interactive REPL
    python infer_finetuned_parser.py

    # curated preset that hits eval slices not yet covered by the 100-case run
    python infer_finetuned_parser.py --preset

    # one-shot
    python infer_finetuned_parser.py --prompt "expense: tomato 40, bus fare 18 yesterday"

    # follow-up form: pass prior structured query context as JSON
    python infer_finetuned_parser.py \\
        --prompt "ask: of that how much was groceries" \\
        --context "{\\"task\\":\\"parse_query\\",\\"domain\\":\\"expense\\",\\"intent\\":\\"total\\",\\"date_start\\":\\"2026-04-01\\",\\"date_end\\":\\"2026-04-30\\"}"
"""

import argparse
import json
import sys
import time
from pathlib import Path

import unsloth  # must come before transformers import for unsloth patches
import torch
from peft import PeftModel
from unsloth import FastLanguageModel


SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_ADAPTER = (
    SCRIPT_DIR
    / "unsloth_qwen3_parser_run-20260506T070456Z-3-002"
    / "unsloth_qwen3_parser_run"
    / "lora_adapter"
)
DEFAULT_BASE_MODEL = "unsloth/Qwen3-1.7B-bnb-4bit"

SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""


# Curated preset prompts that hit the slices the 100-case Colab eval did NOT
# touch (ledger writes, weight writes, all parse_query domains, follow-ups).
# Each entry is (label, prompt) or (label, prompt, context_dict).
PRESET_PROMPTS = [
    # parse_write — already validated in eval, kept as smoke checks
    ("write/expense  basic",        "expense: kothamalli 40, bus fare 18 yesterday"),
    ("write/buy      basic",        "buy: dove 3, parachute, surf excel"),
    ("write/todo     basic",        "todo: pay EB bill tomorrow"),

    # parse_write/ledger — NOT covered by eval yet
    ("write/ledger   I owe",        "ledger: I owe Arun 500 for room rent"),
    ("write/ledger   they owe me",  "ledger: Bala owes me 1200"),
    ("write/ledger   borrowed",     "ledger: borrowed 8k from appa for rent"),
    ("write/ledger   lent",         "ledger: lent Kiran 900"),
    ("write/ledger   repay",        "ledger: paid Arun back 500"),
    ("write/ledger   collect",      "ledger: Bala returned 1200"),
    ("write/ledger   settle",       "ledger: settled with Kiran"),
    ("write/ledger   ambiguous",    "ledger: gave Maddy 5k"),  # should likely 'confirm'

    # parse_write/weight — NOT covered by eval yet
    ("write/weight   self bare",    "weight: 72.4"),
    ("write/weight   self ctx",     "weight: 72.4 before breakfast"),
    ("write/weight   named",        "weight: Arun 72.4 before breakfast"),
    ("write/weight   multi-entry",  "weight: mom 64.1, dad 78.3 after walk"),

    # parse_write — reject expectations
    ("write/expense  reject",       "expense: apples"),
    ("write/ledger   reject",       "ledger: Arun 500"),
    ("write/todo     reject",       "todo: tomorrow"),

    # parse_query/note
    ("query/note     broad",        "ask: show my notes"),
    ("query/note     yesterday",    "ask: what did I write yesterday"),
    ("query/note     topical",      "ask: cipla notes"),

    # parse_query/expense
    ("query/expense  total month",  "ask: what is my total expense this month"),
    ("query/expense  compare",      "ask: compare this month and last month"),
    ("query/expense  group+month",  "ask: what did I spend on groceries in april"),
    ("query/expense  exclusion",    "ask: show my expenses apart from groceries"),
    ("query/expense  recent",       "ask: show recent expenses"),
    ("query/expense  Tanglish",     "ask: indha maasam parachute shampoo expense evalo"),

    # parse_query/buy
    ("query/buy      list",         "ask: what do I need to buy"),
    ("query/buy      explicit",     "ask: show my buy list"),

    # parse_query/todo
    ("query/todo     list",         "ask: show my todo list"),
    ("query/todo     due",          "ask: what is due this week"),
    ("query/todo     all",          "ask: show all todos"),

    # parse_query/weight
    ("query/weight   self latest",  "ask: what is my latest weight"),
    ("query/weight   self history", "ask: show my weight history"),
    ("query/weight   named",        "ask: show Arun weight history"),
    ("query/weight   change",       "ask: how much did Arun change since January"),

    # parse_query/ledger
    ("query/ledger   who owes me",  "ask: who owes me money"),
    ("query/ledger   how much owe", "ask: how much do I owe Arun"),
    ("query/ledger   open with",    "ask: show open ledger with Kiran"),
    ("query/ledger   last month",   "ask: ledger from last month"),

    # parse_followup_query — context inheritance
    (
        "follow/expense  filter add",
        "ask: of that how much was groceries",
        {
            "task": "parse_query", "domain": "expense", "intent": "total",
            "date_start": "2026-04-01", "date_end": "2026-04-30",
            "compare_date_start": None, "compare_date_end": None,
            "filters": {"group": None, "description_text": None,
                        "exclude_group": None, "exclude_description_text": None},
            "limit": None, "query_text": None,
        },
    ),
    (
        "follow/weight   range narrow",
        "ask: only from last month",
        {
            "task": "parse_query", "domain": "weight", "intent": "history",
            "date_start": "2025-11-05", "date_end": "2026-05-05",
            "compare_date_start": None, "compare_date_end": None,
            "filters": {"person_text": "Arun"},
            "limit": None, "query_text": None,
        },
    ),
    (
        "follow/ledger   person filter",
        "ask: only Arun",
        {
            "task": "parse_query", "domain": "ledger", "intent": "list",
            "date_start": "2026-04-01", "date_end": "2026-04-30",
            "compare_date_start": None, "compare_date_end": None,
            "filters": {"person_text": None, "perspective": None, "status": None},
            "limit": None, "query_text": None,
        },
    ),
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adapter", default=str(DEFAULT_ADAPTER),
                        help="Path to LoRA adapter directory (PEFT format).")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL,
                        help="Base model name on HuggingFace or local path.")
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--prompt", default=None,
                        help="One-shot prompt. Skips REPL.")
    parser.add_argument("--context", default=None,
                        help="Optional prior structured query context (JSON string) for follow-up parsing.")
    parser.add_argument("--preset", action="store_true",
                        help="Run the curated preset prompts and exit.")
    parser.add_argument("--hf-token", default=None,
                        help="Optional HuggingFace token if base model needs auth.")
    return parser.parse_args()


def load_model(args):
    adapter_path = Path(args.adapter)
    if not adapter_path.exists():
        sys.exit(f"Adapter folder not found: {adapter_path}")
    if not (adapter_path / "adapter_config.json").exists():
        sys.exit(f"Not a PEFT adapter folder (missing adapter_config.json): {adapter_path}")

    print(f"[load] base = {args.base_model}")
    print(f"[load] adapter = {adapter_path}")
    t0 = time.time()
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        load_in_8bit=False,
        full_finetuning=False,
        token=args.hf_token,
    )
    model = PeftModel.from_pretrained(model, str(adapter_path), is_trainable=False)
    FastLanguageModel.for_inference(model)
    print(f"[load] ready in {time.time()-t0:.1f}s on device "
          f"{'cuda' if torch.cuda.is_available() else 'cpu'}")
    return model, tokenizer


def build_user_text(prompt: str, context: dict | None) -> str:
    user_text = prompt.strip()
    if context is not None:
        ctx = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        user_text = (
            "Previous structured query context:\n"
            f"{ctx}\n\n"
            "User input:\n"
            f"{user_text}"
        )
    return user_text


def run_one(model, tokenizer, prompt: str, context: dict | None, max_new_tokens: int) -> tuple[str, float]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_text(prompt, context)},
    ]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = tokenizer(text, return_tensors="pt").to(device)
    t0 = time.time()
    outputs = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    elapsed = time.time() - t0
    generated = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True,
    ).strip()
    return generated, elapsed


def pretty_print(label: str, prompt: str, context: dict | None, raw: str, elapsed: float) -> None:
    print("-" * 88)
    print(f"[{label}]  ({elapsed:.2f}s)")
    if context is not None:
        print(f"  context: {json.dumps(context, ensure_ascii=False)[:120]}...")
    print(f"  input  : {prompt}")
    try:
        parsed = json.loads(raw)
        print(f"  output : {json.dumps(parsed, ensure_ascii=False, indent=2)}")
    except Exception:
        print(f"  output (UNPARSEABLE): {raw}")


def run_preset(model, tokenizer, max_new_tokens: int) -> None:
    print(f"\nRunning {len(PRESET_PROMPTS)} preset prompts.\n")
    valid = 0
    total_t = 0.0
    for entry in PRESET_PROMPTS:
        if len(entry) == 2:
            label, prompt = entry
            context = None
        else:
            label, prompt, context = entry
        raw, elapsed = run_one(model, tokenizer, prompt, context, max_new_tokens)
        total_t += elapsed
        pretty_print(label, prompt, context, raw, elapsed)
        try:
            json.loads(raw)
            valid += 1
        except Exception:
            pass
    print("-" * 88)
    print(f"valid_json: {valid}/{len(PRESET_PROMPTS)}  total: {total_t:.1f}s  "
          f"avg: {total_t/len(PRESET_PROMPTS):.2f}s/prompt")


def run_repl(model, tokenizer, max_new_tokens: int) -> None:
    print("\nInteractive mode. Type a prompt and press Enter. Empty line or Ctrl-C to exit.")
    print("Tip: prefix a line with `context:` followed by JSON to set follow-up context for the next prompt.\n")
    pending_context: dict | None = None
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            return
        if line.lower().startswith("context:"):
            try:
                pending_context = json.loads(line[len("context:"):].strip())
                print(f"  [context set: {json.dumps(pending_context, ensure_ascii=False)[:120]}...]")
            except Exception as exc:
                print(f"  [context parse error: {exc}]")
            continue
        raw, elapsed = run_one(model, tokenizer, line, pending_context, max_new_tokens)
        pretty_print("repl", line, pending_context, raw, elapsed)
        pending_context = None


def main():
    args = parse_args()
    context = json.loads(args.context) if args.context else None
    model, tokenizer = load_model(args)

    if args.preset:
        run_preset(model, tokenizer, args.max_new_tokens)
        return
    if args.prompt:
        raw, elapsed = run_one(model, tokenizer, args.prompt, context, args.max_new_tokens)
        pretty_print("one-shot", args.prompt, context, raw, elapsed)
        return
    run_repl(model, tokenizer, args.max_new_tokens)


if __name__ == "__main__":
    main()
