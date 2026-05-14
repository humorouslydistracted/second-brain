# =========================
# Unsloth Qwen3-0.6B SFT — single Colab cell (smaller-model variant)
#
# This is the 0.6B sibling of `colab_finetune.py`. The 1.7B path is the
# production one; this script exists so we can A/B reliability + on-device
# latency against the smaller model without disturbing the locked 1.7B
# pipeline. Everything here mirrors `colab_finetune.py` except:
#
#   - MODEL_NAME            → unsloth/Qwen3-0.6B-unsloth-bnb-4bit
#   - LORA_R                → 8  (16 over-fits 0.6B on this dataset size)
#   - OUTPUT_DIR            → …/unsloth_qwen3_0p6b_parser_run
#
# The prompt template, completion-only-loss masking, packing=False, MAX_SEQ
# bump to 1536, anchor-date Today: injection, and dataset loader are all
# unchanged so the trained adapter remains drop-in compatible with the
# existing GGUF conversion + Android runtime (after the matching
# colab_convert_to_gguf_qwen3_0p6b.ipynb run).
# =========================

# ---------- CONFIG ----------
DATASET_ROOT = "/content/drive/MyDrive/notes_app_finetuning/synthetic_finetune_dataset_v4_v2_schema"   # CHANGE THIS
OUTPUT_DIR   = "/content/drive/MyDrive/notes_app_finetuning/unsloth_qwen3_0p6b_parser_run"             # CHANGE IF YOU WANT

MODEL_NAME = "unsloth/Qwen3-0.6B-unsloth-bnb-4bit"   # 0.6B variant (this script)
# MODEL_NAME = "unsloth/Qwen3-1.7B-bnb-4bit"          # production 1.7B — use colab_finetune.py instead

MOUNT_DRIVE = False
HF_TOKEN = None   # put your HF token string here only if needed

MAX_SEQ_LENGTH = 1536  # 2026-05-09: bumped from 1024 to fit 12-item buy/expense
                       # multi-record JSON output (each record ~70 tokens, plus
                       # ~150 for system+user). 1024 truncated past ~13 records.
NUM_TRAIN_EPOCHS = 1
LEARNING_RATE = 2e-4
PER_DEVICE_BATCH_SIZE = 8
GRADIENT_ACCUMULATION_STEPS = 2
LORA_R = 8             # 0.6B: smaller LoRA. r=16 over-fits this base on the
                       # 60k-row v4 dataset; the existing local 0.6B script
                       # (local_finetune_qwen3_0p6b_gtx1650.py) settled on r=8.
SEED = 3407
SAVE_MERGED_16BIT = False
TRAIN_ON_ALL_SAMPLES = True
ENABLE_PACKING = False  # 2026-05-09: turned off — packing without completion-only loss
                        # masking leaks gradient across example boundaries. With
                        # train_on_responses_only below the model now learns the
                        # JSON output specifically, not generic chat-template tokens.

SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""


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


TRAINING_SUBDIRS = ("parse_write", "parse_query", "parse_followup_query")

# ---------- INSTALL ----------
import sys, subprocess, os

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
    "bitsandbytes"
)

# ---------- MOUNT DRIVE ----------
if MOUNT_DRIVE:
    if os.path.exists("/content/drive/MyDrive"):
        print("Google Drive already available. Skipping drive.mount().")
    else:
        try:
            from google.colab import drive
            drive.mount("/content/drive")
        except Exception as exc:
            raise RuntimeError(
                "Could not mount Google Drive from inside this Python script. "
                "In Colab, mount Drive in a notebook cell first, then rerun this script "
                "with MOUNT_DRIVE = False."
            ) from exc

# ---------- IMPORTS ----------
import json
import random
from pathlib import Path

import torch
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig

random.seed(SEED)

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
            for line_no, line in enumerate(f, start=1):
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
                        row["context"],
                        ensure_ascii=False,
                        separators=(",", ":")
                    )
                    user_text = (
                        "Previous structured query context:\n"
                        f"{context_text}\n\n"
                        "User input:\n"
                        f"{user_text}"
                    )

                assistant_text = json.dumps(
                    row["output"],
                    ensure_ascii=False,
                    separators=(",", ":")
                )

                examples.append({
                    "source_file": str(path),
                    "user_text": user_text,
                    "assistant_text": assistant_text,
                    "anchor_date": row.get("anchor_date"),
                })

    if not examples:
        raise ValueError(
            f"No training examples with input/output were found under {dataset_root}. "
            "Point DATASET_ROOT at a dataset root containing parse_write/parse_query/parse_followup_query."
        )
    if skipped_rows:
        print(f"Skipped non-training rows (for example reference_only data): {skipped_rows}")

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
        raise ValueError("Dataset is too small after splitting. Add more examples.")

    train_items = items[:n_train]
    valid_items = items[n_train:n_train + n_valid]
    test_items = items[n_train + n_valid:]

    return train_items, valid_items, test_items

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

# ---------- LOAD MODEL ----------
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

# ---------- LOAD + CONVERT DATA ----------
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
    valid_rows = []
    test_rows = []
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
# strongest (`data:{}`). With train_on_responses_only, loss is masked for
# everything before the assistant marker — every gradient update is on the
# JSON output we actually want the model to learn.
from unsloth.chat_templates import train_on_responses_only

trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)

trainer_stats = trainer.train()
print(trainer_stats)

# ---------- SAVE ----------
adapter_dir = Path(OUTPUT_DIR) / "lora_adapter"
adapter_dir.mkdir(parents=True, exist_ok=True)

model.save_pretrained(str(adapter_dir))
tokenizer.save_pretrained(str(adapter_dir))
print(f"Saved LoRA adapter to: {adapter_dir}")

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

sanity_prompts = [
    "expense: kothamalli 40, bus fare 18 yesterday",
    "ledger: Arun owes me 2400",
    "ask: what was my total expense last month",
    "Previous structured query context:\n"
    "{\"task\":\"parse_query\",\"domain\":\"expense\",\"intent\":\"total\",\"date_start\":\"2026-04-01\",\"date_end\":\"2026-04-30\",\"compare_date_start\":null,\"compare_date_end\":null,\"filters\":{\"group\":null,\"description_text\":null,\"exclude_group\":null,\"exclude_description_text\":null},\"limit\":null,\"query_text\":null}\n\n"
    "User input:\nask: of that how much was transport",
]

sanity_anchor = next((ex.get("anchor_date") for ex in raw_examples if ex.get("anchor_date")), None)
if sanity_anchor:
    print(f"\n=== SANITY CHECKS (Today: {sanity_anchor}) ===\n")
else:
    print("\n=== SANITY CHECKS ===\n")
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
