# Model Training

The parser model is trained to map short personal inputs into JSON for a
tag-first notes app.

## Supported Domains

- notes
- expenses
- todos
- buy-list items
- weights
- ledger entries
- conversational queries over the above data

## Training Shape

The dataset generators create examples for:

- `parse_write`
- `parse_query`
- `parse_followup_query`

The model output is validated by the Android app before any write/query runner
uses it. This keeps the training target narrow and avoids relying on the model
for arithmetic or database state.

## Tooling

| Folder | Purpose |
| --- | --- |
| `tools/datasets/` | Synthetic dataset generation, held-out eval generation, manual parser evaluation |
| `tools/model-training/colab/` | Colab fine-tuning, MiniLM export, and GGUF conversion |
| `tools/model-training/kaggle/` | Kaggle fine-tuning and held-out evaluation |

Large artifacts such as LoRA adapters, GGUF files, ONNX exports, generated
datasets, and local databases are intentionally ignored by Git.

## Typical Pipeline

1. Generate parser data with `tools/datasets/generate_large_schema_frozen_dataset_v2.py`.
2. Generate held-out eval rows with `tools/datasets/generate_eval_dataset_v3.py`.
3. Fine-tune on Kaggle or Colab with the scripts in `tools/model-training`.
4. Evaluate the adapter against the v3 held-out eval set.
5. Convert the adapter to a GGUF parser model.
6. Publish large GGUF artifacts through GitHub Releases.
7. Copy the GGUF and MiniLM files to the app's `files/models/` folder.
8. Compare parser quality and latency from the Android Activity log.

The current training root is `synthetic_finetune_dataset_v4_v2_schema/`. It
must contain only `parse_write/`, `parse_query/`, and
`parse_followup_query/`; `reference_only/` belongs to old experiments and is
not part of the current parser training target.
