import argparse
import json
import os
import random
from pathlib import Path

import torch
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import SFTConfig, SFTTrainer


SYSTEM_PROMPT = """You are a parser for a tag-first personal data app.
Return JSON only.
Do not add markdown.
Do not add explanations.
Do not add extra keys.
Use null for missing values.
Follow the schema shown by the examples exactly."""

TRAINING_SUBDIRS = ("parse_write", "parse_query", "parse_followup_query")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Laptop-safe local fine-tuning for Qwen3-0.6B on smaller GPUs like GTX 1650."
    )
    parser.add_argument(
        "--dataset-root",
        default="synthetic_finetune_dataset_v3_large_india_first",
        help="Training dataset root containing parse_write/parse_query/parse_followup_query.",
    )
    parser.add_argument(
        "--output-dir",
        default="local_runs/qwen3_0p6b_gtx1650",
        help="Directory for checkpoints, adapters, and converted subset data.",
    )
    parser.add_argument(
        "--model-name",
        default="unsloth/Qwen3-0.6B-unsloth-bnb-4bit",
        help="Base model to fine-tune.",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help="Optional Hugging Face token.",
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=512,
        help="Smaller context length for 4GB VRAM-class GPUs.",
    )
    parser.add_argument(
        "--train-rows",
        type=int,
        default=12000,
        help="Cap training rows for laptop runs. Use 0 to train on every available row.",
    )
    parser.add_argument(
        "--num-train-epochs",
        type=int,
        default=1,
        help="Epoch count. Keep low for laptop runs.",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=2e-4,
        help="Learning rate for LoRA fine-tuning.",
    )
    parser.add_argument(
        "--per-device-batch-size",
        type=int,
        default=1,
        help="Micro-batch size for local VRAM limits.",
    )
    parser.add_argument(
        "--gradient-accumulation-steps",
        type=int,
        default=16,
        help="Gradient accumulation to keep effective batch reasonable.",
    )
    parser.add_argument(
        "--lora-r",
        type=int,
        default=8,
        help="Smaller LoRA rank for laptop-safe training.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=3407,
        help="Random seed.",
    )
    parser.add_argument(
        "--save-steps",
        type=int,
        default=100,
        help="Checkpoint every N optimizer steps.",
    )
    parser.add_argument(
        "--save-total-limit",
        type=int,
        default=2,
        help="How many intermediate checkpoints to keep.",
    )
    parser.add_argument(
        "--resume-from-checkpoint",
        default=None,
        help="Optional checkpoint path to resume from.",
    )
    parser.add_argument(
        "--disable-packing",
        action="store_true",
        help="Turn off TRL packing if you hit an issue on your local stack.",
    )
    parser.add_argument(
        "--skip-sanity-check",
        action="store_true",
        help="Skip the quick post-training generation check.",
    )
    return parser.parse_args()


def discover_training_files(dataset_root: Path):
    subdir_files = []
    for subdir in TRAINING_SUBDIRS:
        target = dataset_root / subdir
        if target.exists():
            subdir_files.extend(sorted(target.rglob("*.jsonl")))
    if subdir_files:
        return subdir_files
    return sorted(dataset_root.rglob("*.jsonl"))


def load_raw_examples(dataset_root: Path):
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
                        separators=(",", ":"),
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
                    separators=(",", ":"),
                )

                examples.append(
                    {
                        "source_file": str(path),
                        "user_text": user_text,
                        "assistant_text": assistant_text,
                    }
                )

    if not examples:
        raise ValueError(
            f"No training examples with input/output were found under {dataset_root}."
        )
    if skipped_rows:
        print(f"Skipped non-training rows (for example reference_only data): {skipped_rows}")

    return examples


def truncate_examples(examples, max_rows: int, seed: int):
    if max_rows <= 0 or len(examples) <= max_rows:
        return list(examples)
    rng = random.Random(seed)
    examples = list(examples)
    rng.shuffle(examples)
    return examples[:max_rows]


def make_chat_text(tokenizer, user_text, assistant_text):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        enable_thinking=False,
    )


def save_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_trainer(model, tokenizer, train_dataset, args, supports_bf16):
    common_sft_kwargs = dict(
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        per_device_train_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        warmup_steps=5,
        num_train_epochs=args.num_train_epochs,
        learning_rate=args.learning_rate,
        logging_steps=25,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        fp16=not supports_bf16,
        bf16=supports_bf16,
        seed=args.seed,
        output_dir=args.output_dir,
        report_to="none",
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        packing=not args.disable_packing,
    )
    try:
        sft_args = SFTConfig(dataset_num_proc=1, **common_sft_kwargs)
    except TypeError:
        print("SFTConfig(dataset_num_proc=1) is not supported by this TRL version. Continuing without it.")
        sft_args = SFTConfig(**common_sft_kwargs)

    return SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        args=sft_args,
    )


def main():
    args = parse_args()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    random.seed(args.seed)

    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA GPU not found. This script is intended for local NVIDIA GPU fine-tuning."
        )

    dataset_root = Path(args.dataset_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading base model...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_name,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        load_in_8bit=False,
        full_finetuning=False,
        token=args.hf_token,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=args.lora_r,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
        use_rslora=False,
        loftq_config=None,
    )

    raw_examples = load_raw_examples(dataset_root)
    print(f"Loaded raw examples: {len(raw_examples)}")
    train_examples = truncate_examples(raw_examples, args.train_rows, args.seed)
    print(f"Training examples after cap: {len(train_examples)}")

    formatted = []
    for ex in train_examples:
        text = make_chat_text(tokenizer, ex["user_text"], ex["assistant_text"])
        formatted.append(
            {
                "text": text,
                "user_text": ex["user_text"],
                "assistant_text": ex["assistant_text"],
                "source_file": ex["source_file"],
            }
        )

    converted_dir = output_dir / "converted_dataset"
    save_jsonl(converted_dir / "train_subset.jsonl", formatted)
    train_dataset = Dataset.from_list(formatted)

    supports_bf16 = torch.cuda.is_available() and getattr(
        torch.cuda, "is_bf16_supported", lambda: False
    )()
    trainer = build_trainer(model, tokenizer, train_dataset, args, supports_bf16)

    print("Starting training...")
    if args.resume_from_checkpoint:
        trainer_stats = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    else:
        trainer_stats = trainer.train()
    print(trainer_stats)

    adapter_dir = output_dir / "lora_adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"Saved LoRA adapter to: {adapter_dir}")

    adapter_merged_dir = output_dir / "lora_adapter_unsloth"
    adapter_merged_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained_merged(str(adapter_merged_dir), tokenizer, save_method="lora")
    print(f"Saved Unsloth LoRA adapter to: {adapter_merged_dir}")

    if args.skip_sanity_check:
        return

    FastLanguageModel.for_inference(model)
    sanity_prompts = [
        "expense: kothamalli 40, bus fare 18 yesterday",
        "ledger: Arun owes me 2400",
        "ask: what is my total expense this month",
    ]

    print("\n=== SANITY CHECKS ===\n")
    for prompt in sanity_prompts:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
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
            max_new_tokens=192,
            do_sample=False,
        )
        generated = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )
        print("PROMPT:")
        print(prompt)
        print("OUTPUT:")
        print(generated.strip())
        print("-" * 80)


if __name__ == "__main__":
    main()
