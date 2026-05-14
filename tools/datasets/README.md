# Dataset And Evaluation Tools

This folder contains the current parser dataset pipeline and parser evaluation
helpers. Generated datasets are intentionally ignored by Git because they are
large and reproducible.

## Current Pipeline

| File | Purpose |
| --- | --- |
| `generate_large_schema_frozen_dataset_v2.py` | Canonical training generator. Outputs `synthetic_finetune_dataset_v4_v2_schema/` with `parse_write/`, `parse_query/`, and `parse_followup_query/`. |
| `generate_eval_dataset_v3.py` | Canonical held-out eval generator for the v2 parser schema. Outputs `eval_finetune_dataset_v3_schema_frozen/heldout_cases.jsonl`. |
| `synthetic_dataset_assets.py` | Shared names, items, templates, date phrases, Tanglish phrases, and India-context pools. |
| `evaluate_finetune.py` | Evaluates a fine-tuned Qwen parser adapter against held-out rows. |
| `evaluate_manual_parser.py` | Evaluates the deterministic manual parser against the current training dataset. |
| `manual_parser.py` | Python reference implementation for the app's rule-based parser behavior. |
| `expense_groups_full.json` | Expense grouping reference data used by parser and dataset tooling. |

## Typical Commands

```powershell
python tools\datasets\generate_large_schema_frozen_dataset_v2.py --out-dir synthetic_finetune_dataset_v4_v2_schema --write-count 5000 --query-count 5000 --followup-count 6000
python tools\datasets\generate_eval_dataset_v3.py --out-dir eval_finetune_dataset_v3_schema_frozen
```

The current training dataset must not contain a `reference_only/` folder. Note
writes are deterministic app behavior, not parser SFT rows.
