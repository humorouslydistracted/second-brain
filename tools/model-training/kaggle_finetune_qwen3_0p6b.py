# =========================
# Qwen3-0.6B v2 parser fine-tune (Kaggle) — single .py
#
# .py mirror of `kaggle_finetune_qwen3_0p6b.ipynb`. Same logic, no notebook
# cell metadata. Use this if you'd rather paste the whole script into one
# Kaggle code cell, or run it from a terminal-style cell. The notebook
# version stays the canonical Kaggle UX (one cell per stage, easier to
# rerun individually).
#
# 0.6B sibling of `kaggle_finetune.ipynb` (the production 1.7B path).
# Use this when you want to A/B reliability + on-device latency against
# the smaller model.
#
# Mirrors the patched `colab_finetune.py` (2026-05-09 trainer fixes baked
# in: `train_on_responses_only`, `packing=False`, `MAX_SEQ_LENGTH=1536`).
# Differences vs the 1.7B Kaggle notebook:
#
#   - MODEL_NAME → unsloth/Qwen3-0.6B-unsloth-bnb-4bit
#   - LORA_R     → 8 (16 over-fits 0.6B on this dataset size)
#   - OUTPUT_DIR → /kaggle/working/unsloth_qwen3_0p6b_parser_run
#
# ---------- Prerequisites ----------
# 1. Upload `synthetic_finetune_dataset_v4_v2_schema/` as a Kaggle dataset.
#    Note the slug — it becomes part of the input path /kaggle/input/<slug>/.
# 2. Add the dataset to this notebook (Right sidebar → "+ Add Data").
# 3. Pick a GPU accelerator (T4 x2 or P100, 16 GB, free tier).
# 4. Enable Internet (Settings → Internet → On). Required for `pip install unsloth`.
# 5. (Optional) HF_TOKEN secret. Add-ons → Secrets → New Secret named `HF_TOKEN`.
#    Not required for Qwen3-0.6B (public).
# =========================

# ---------- CONFIG (edit these for your setup) ----------
DATASET_ROOT = "/kaggle/input/synthetic-finetune-v4-v2-schema/synthetic_finetune_dataset_v4_v2_schema"

# /kaggle/working/ persists for the session and is what "Output" in the sidebar shows.
OUTPUT_DIR = "/kaggle/working/unsloth_qwen3_0p6b_parser_run"

MODEL_NAME = "unsloth/Qwen3-0.6B-unsloth-bnb-4bit"   # 0.6B variant (this script)
# MODEL_NAME = "unsloth/Qwen3-1.7B-bnb-4bit"          # production 1.7B — use kaggle_finetune.ipynb instead

HF_TOKEN = None  # set explicitly or wire from Kaggle Secrets below

MAX_SEQ_LENGTH = 1536  # 2026-05-09: bumped from 1024 to fit 12-item buy/expense
                       # multi-record JSON outputs (each record ~70 tokens).
NUM_TRAIN_EPOCHS = 1
LEARNING_RATE = 2e-4
PER_DEVICE_BATCH_SIZE = 8
GRADIENT_ACCUMULATION_STEPS = 2
LORA_R = 8             # 0.6B: smaller LoRA. r=16 over-fits this base on 60k rows.
SEED = 3407
SAVE_MERGED_16BIT = False     # set True if you want a merged 16-bit copy under /kaggle/working/
TRAIN_ON_ALL_SAMPLES = True   # False → 80/10/10 split
ENABLE_PACKING = False  # 2026-05-09: packing without completion-only loss masking
                        # leaks gradient across example boundaries.

SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""

TRAINING_SUBDIRS = ("parse_write", "parse_query", "parse_followup_query")

# Optional: pull HF_TOKEN from Kaggle Secrets instead of pasting in plain text.
# from kaggle_secrets import UserSecretsClient
# HF_TOKEN = UserSecretsClient().get_secret("HF_TOKEN")


def build_system_prompt(anchor_date):
    """Append `Today: <YYYY-MM-DD>` to the system prompt for v2 rows.

    v2 schema (per docs/model-training.md Section 7) trains the model with a
    ``Today:`` line in the system prompt and matching anchor in each row's
    relative-date resolution. v1 rows do not carry ``anchor_date`` and skip
    the line, which keeps the chat-template framing byte-identical to the
    historical v1 training run when this script is pointed at the v1 dataset.
    """
    if anchor_date:
        return f"{SYSTEM_PROMPT}\n\nToday: {anchor_date}"
    return SYSTEM_PROMPT


# ---------- GPU PIN ----------
# Pin to a single GPU. Kaggle's "T4 x2" accelerator exposes both GPUs to
# the kernel, and accelerate/transformers can silently shard the model
# across them via `device_map="auto"`. Unsloth's 4-bit path doesn't
# benefit from that on a 0.6B/1.7B model and the cross-device traffic
# slows training; worse, it occasionally OOMs the second GPU mid-epoch
# because the LoRA optimizer state is uneven.
#
# Setting CUDA_VISIBLE_DEVICES="0" BEFORE importing torch hides device 1
# from the runtime entirely, so every subsequent .to("cuda") and the
# trainer's bf16/fp16 path land on a single device.
#
# Override by changing the value (e.g. "1" to use the second T4) or by
# setting the env var before invoking the script.
import os
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
print(f"GPU pin: CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']}")


# ---------- INSTALL ----------
import sys
import subprocess


def pip_install(*packages):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--upgrade", *packages])


pip_install(
    "unsloth",
    "unsloth_zoo",
    "datasets",
    "trl",
    "transformers",
    "accelerate",
    "peft",
    "bitsandbytes",
)


# ---------- IMPORTS + GPU info ----------
import json
import random
from pathlib import Path

import unsloth  # noqa: F401  -- import before torch on some Kaggle envs
import torch
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig

random.seed(SEED)
print(f"torch {torch.__version__}  cuda available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM total: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")


# ---------- HELPERS ----------
def discover_training_files(dataset_root: Path):
    subdir_files = []
    for subdir in TRAINING_SUBDIRS:
        target = dataset_root / subdir
        if target.exists():
            subdir_files.extend(sorted(target.rglob("*.jsonl")))
    if subdir_files:
        return subdir_files
    return sorted(dataset_root.rglob("*.jsonl"))


def load_raw_examples(dataset_root):
    dataset_root = Path(dataset_root)
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {dataset_root}")

    files = discover_training_files(dataset_root)
    if not files:
        raise FileNotFoundError(f"No .jsonl files found under: {dataset_root}")

    examples = []
    skipped_rows = 0
    for path in files:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if "input" not in row or "output" not in row:
                    skipped_rows += 1
                    continue

                user_text = row["input"].strip()
                if "context" in row:
                    context_text = json.dumps(
                        row["context"], ensure_ascii=False, separators=(",", ":"),
                    )
                    user_text = (
                        "Previous structured query context:\n"
                        f"{context_text}\n\n"
                        "User input:\n"
                        f"{user_text}"
                    )

                assistant_text = json.dumps(
                    row["output"], ensure_ascii=False, separators=(",", ":"),
                )

                examples.append({
                    "source_file": str(path),
                    "user_text": user_text,
                    "assistant_text": assistant_text,
                    "anchor_date": row.get("anchor_date"),
                })

    if not examples:
        raise ValueError(
            f"No training examples with input/output were found under {dataset_root}."
        )
    if skipped_rows:
        print(f"Skipped non-training rows: {skipped_rows}")
    return examples


def make_chat_text(tokenizer, user_text, assistant_text, anchor_date=None):
    messages = [
        {"role": "system", "content": build_system_prompt(anchor_date)},
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        enable_thinking=False,
    )


def split_dataset(items, seed=3407):
    rng = random.Random(seed)
    items = list(items)
    rng.shuffle(items)
    n = len(items)
    n_test = max(1, int(n * 0.1))
    n_valid = max(1, int(n * 0.1))
    n_train = n - n_valid - n_test
    if n_train < 1:
        raise ValueError("Dataset is too small after splitting.")
    return items[:n_train], items[n_train:n_train + n_valid], items[n_train + n_valid:]


def save_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def shuffle_examples(items, seed=3407):
    items = list(items)
    rng = random.Random(seed)
    rng.shuffle(items)
    return items


# ---------- LOAD MODEL + LORA ----------
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL_NAME,
    max_seq_length=MAX_SEQ_LENGTH,
    load_in_4bit=True,
    load_in_8bit=False,
    full_finetuning=False,
    token=HF_TOKEN,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_R,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=LORA_R,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=SEED,
    use_rslora=False,
    loftq_config=None,
)


# ---------- LOAD + FORMAT DATA ----------
raw_examples = load_raw_examples(DATASET_ROOT)
raw_examples = shuffle_examples(raw_examples, seed=SEED)
print(f"Loaded raw examples: {len(raw_examples)} (globally shuffled across lanes/files)")

formatted = []
for ex in raw_examples:
    text = make_chat_text(
        tokenizer=tokenizer,
        user_text=ex["user_text"],
        assistant_text=ex["assistant_text"],
        anchor_date=ex.get("anchor_date"),
    )
    formatted.append({
        "text": text,
        "user_text": ex["user_text"],
        "assistant_text": ex["assistant_text"],
        "anchor_date": ex.get("anchor_date"),
        "source_file": ex["source_file"],
    })

anchor_count = sum(1 for ex in raw_examples if ex.get("anchor_date"))
print(f"Rows carrying anchor_date (v2 schema): {anchor_count}/{len(raw_examples)}")

converted_dir = Path(OUTPUT_DIR) / "converted_dataset"
if TRAIN_ON_ALL_SAMPLES:
    train_rows = list(formatted)
    valid_rows, test_rows = [], []
    print("Training on all formatted examples. No internal split.")
    print(f"Train: {len(train_rows)}")
    save_jsonl(converted_dir / "train_all.jsonl", train_rows)
    train_dataset = Dataset.from_list(train_rows)
    valid_dataset = None
else:
    train_rows, valid_rows, test_rows = split_dataset(formatted, seed=SEED)
    print(f"Train: {len(train_rows)}")
    print(f"Valid: {len(valid_rows)}")
    print(f"Test : {len(test_rows)}")
    save_jsonl(converted_dir / "train.jsonl", train_rows)
    save_jsonl(converted_dir / "valid.jsonl", valid_rows)
    save_jsonl(converted_dir / "test.jsonl", test_rows)
    train_dataset = Dataset.from_list(train_rows)
    valid_dataset = Dataset.from_list(valid_rows)


# ---------- TRAIN ----------
supports_bf16 = torch.cuda.is_available() and getattr(torch.cuda, "is_bf16_supported", lambda: False)()

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    args=SFTConfig(
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LENGTH,
        per_device_train_batch_size=PER_DEVICE_BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION_STEPS,
        warmup_steps=5,
        num_train_epochs=NUM_TRAIN_EPOCHS,
        learning_rate=LEARNING_RATE,
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        fp16=not supports_bf16,
        bf16=supports_bf16,
        seed=SEED,
        output_dir=OUTPUT_DIR,
        report_to="none",
        save_strategy="epoch",
        packing=ENABLE_PACKING,
    ),
)

# 2026-05-09: completion-only loss masking. Without this, SFTTrainer computes
# loss across the FULL chat template (system + user + assistant), so the JSON
# output gets only ~10-15% of the gradient signal. Result: model drifts off the
# trained `records:[]` schema and emits whatever pre-training pattern is
# strongest (`data:{}`).
from unsloth.chat_templates import train_on_responses_only

trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)

trainer_stats = trainer.train()
print(trainer_stats)


# ---------- SAVE ADAPTER ----------
adapter_dir = Path(OUTPUT_DIR) / "lora_adapter"
adapter_dir.mkdir(parents=True, exist_ok=True)
model.save_pretrained(str(adapter_dir))
tokenizer.save_pretrained(str(adapter_dir))
print(f"Saved LoRA adapter (peft format) to: {adapter_dir}")

adapter_merged_dir = Path(OUTPUT_DIR) / "lora_adapter_unsloth"
adapter_merged_dir.mkdir(parents=True, exist_ok=True)
model.save_pretrained_merged(str(adapter_merged_dir), tokenizer, save_method="lora")
print(f"Saved Unsloth LoRA adapter to: {adapter_merged_dir}")

if SAVE_MERGED_16BIT:
    merged_dir = Path(OUTPUT_DIR) / "merged_16bit"
    merged_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained_merged(str(merged_dir), tokenizer, save_method="merged_16bit")
    print(f"Saved merged 16-bit model to: {merged_dir}")


# ---------- QUICK INFERENCE CHECK ----------
FastLanguageModel.for_inference(model)

sanity_anchor = next((ex.get("anchor_date") for ex in raw_examples if ex.get("anchor_date")), None)
if sanity_anchor:
    print(f"\n=== SANITY CHECKS (Today: {sanity_anchor}) ===\n")
else:
    print("\n=== SANITY CHECKS ===\n")

sanity_prompts = [
    "expense: kothamalli 40, bus fare 18 yesterday",
    "ledger: Arun owes me 2400",
    "ask: what was my total expense last month",
    "Previous structured query context:\n"
    "{\"task\":\"parse_query\",\"domain\":\"expense\",\"intent\":\"total\",\"date_start\":\"2026-04-01\",\"date_end\":\"2026-04-30\",\"compare_date_start\":null,\"compare_date_end\":null,\"filters\":{\"group\":null,\"description_text\":null,\"exclude_group\":null,\"exclude_description_text\":null},\"limit\":null,\"query_text\":null}\n\n"
    "User input:\nask: of that how much was transport",
]

for prompt in sanity_prompts:
    messages = [
        {"role": "system", "content": build_system_prompt(sanity_anchor)},
        {"role": "user", "content": prompt},
    ]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = tokenizer(text, return_tensors="pt").to("cuda")
    outputs = model.generate(
        **inputs,
        max_new_tokens=256,
        do_sample=False,
    )
    generated = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )
    print("PROMPT:")
    print(prompt)
    print("OUTPUT:")
    print(generated.strip())
    print("-" * 80)
