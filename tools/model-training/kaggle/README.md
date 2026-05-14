# Kaggle Workflows

Use these files when running parser fine-tuning or evaluation on Kaggle.

## Files

| File | Purpose |
| --- | --- |
| `finetune_qwen3_1p7b.ipynb` | Main Qwen3-1.7B parser fine-tune notebook. |
| `finetune_qwen3_0p6b.ipynb` | Qwen3-0.6B parser fine-tune notebook. |
| `finetune_qwen3_0p6b.py` | Script mirror of the 0.6B Kaggle notebook. |
| `evaluate_qwen3_1p7b.ipynb` | Evaluate a Qwen3-1.7B adapter against the v3 held-out eval set. |

## Inputs

Upload these generated folders as Kaggle datasets:

- `synthetic_finetune_dataset_v4_v2_schema/` for training
- `eval_finetune_dataset_v3_schema_frozen/heldout_cases.jsonl` for evaluation

## Current Training Contract

- `MAX_SEQ_LENGTH = 1536`
- `ENABLE_PACKING = False`
- `train_on_responses_only` must be used
- The model learns only the assistant JSON response
- Runtime prompts must include a `Today: <YYYY-MM-DD>` line

Download the LoRA adapter from Kaggle output, then convert it to GGUF with the
matching notebook in `../colab/`.
