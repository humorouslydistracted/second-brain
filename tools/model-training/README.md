# Model Training Tools

This folder contains scripts and notebooks for parser fine-tuning, evaluation,
MiniLM export, and GGUF conversion.

## Main Files

| File | Purpose |
| --- | --- |
| `kaggle_finetune*.ipynb` / `.py` | Kaggle training workflows. |
| `colab_finetune*.py` | Colab/local fallback training workflows. |
| `colab_convert_to_gguf*.ipynb` | Merge LoRA adapters and export quantized GGUF parser files. |
| `colab_export_minilm_onnx.ipynb` / `export_minilm_onnx.py` | Export MiniLM embedder files for Android. |
| `infer_finetuned_parser.py` | Local adapter inference helper. |
| `requirements_local_*.txt` | Windows/local GPU dependency notes. |

Generated model artifacts are ignored by Git. Store release artifacts through
GitHub Releases or another artifact store rather than committing them.
