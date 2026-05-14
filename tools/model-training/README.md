# Model Training Tools

This folder contains the public training and export workflow for the Android
parser model.

## Layout

| Folder/File | Purpose |
| --- | --- |
| `colab/` | Colab fine-tuning, GGUF conversion, and MiniLM export notebooks. |
| `kaggle/` | Kaggle fine-tuning and evaluation notebooks/scripts. |
| `export_minilm_onnx.py` | Local equivalent of the MiniLM ONNX export notebook. |

The current dataset comes from `tools/datasets/generate_large_schema_frozen_dataset_v2.py`.
The current held-out eval set comes from `tools/datasets/generate_eval_dataset_v3.py`.

## Current Model Paths

- `Qwen3-1.7B` is the main quality-oriented parser path.
- `Qwen3-0.6B` is the smaller latency-oriented A/B path.
- Both export to GGUF names understood by the Android app:
  - `qwen3-1.7b-parser-q4_k_m.gguf`
  - `qwen3-0.6b-parser-q4_k_m.gguf`

Generated model artifacts are ignored by Git. Store large artifacts through
GitHub Releases or another artifact store rather than committing them.
