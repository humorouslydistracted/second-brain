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
| `tools/model-training/` | Kaggle, Colab, local fine-tuning, MiniLM export, and GGUF conversion |

Large artifacts such as LoRA adapters, GGUF files, ONNX exports, generated
datasets, and local databases are intentionally ignored by Git.

## Typical Pipeline

1. Generate or update synthetic parser data with `tools/datasets`.
2. Fine-tune on Kaggle or Colab with the scripts in `tools/model-training`.
3. Evaluate the adapter against held-out data.
4. Convert the adapter to a GGUF parser model.
5. Copy the GGUF and MiniLM files to the app's `files/models/` folder.
6. Compare parser quality and latency from the Android Activity log.
