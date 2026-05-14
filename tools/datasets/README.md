# Dataset And Evaluation Tools

This folder contains the synthetic data generators, evaluation scripts, and
manual parser helpers used to train and measure the structured parser.

## Main Files

| File | Purpose |
| --- | --- |
| `generate_large_schema_frozen_dataset*.py` | Generate synthetic parser training datasets. |
| `generate_eval_dataset*.py` | Generate held-out evaluation cases. |
| `synthetic_dataset_assets.py` | Names, items, templates, and India-context phrase pools. |
| `evaluate_finetune.py` | Evaluate a fine-tuned parser adapter. |
| `evaluate_manual_parser.py` | Evaluate the deterministic parser implementation. |
| `manual_parser.py` | Python reference for rule-based parser behavior. |
| `expense_groups_full.json` | Expense grouping reference data. |

Generated datasets are intentionally ignored by Git.
