# Colab Workflows

Use these files when running parser training or conversion on Google Colab.

## Files

| File | Purpose |
| --- | --- |
| `finetune_qwen3_1p7b.py` | Main Qwen3-1.7B parser fine-tune script. |
| `finetune_qwen3_0p6b.py` | Smaller Qwen3-0.6B parser fine-tune script for latency experiments. |
| `convert_gguf_qwen3_1p7b.ipynb` | Merge the 1.7B LoRA adapter and export `qwen3-1.7b-parser-q4_k_m.gguf`. |
| `convert_gguf_qwen3_0p6b.ipynb` | Merge the 0.6B LoRA adapter and export `qwen3-0.6b-parser-q4_k_m.gguf`. |
| `export_minilm_onnx.ipynb` | Export MiniLM ONNX and tokenizer files for Android note retrieval. |

## Current Training Contract

- Dataset root: `synthetic_finetune_dataset_v4_v2_schema/`
- Training subfolders: `parse_write/`, `parse_query/`, `parse_followup_query/`
- No `reference_only/` rows
- `MAX_SEQ_LENGTH = 1536`
- `ENABLE_PACKING = False`
- `train_on_responses_only` must be applied after `SFTTrainer(...)`
- Every v2 row carries `anchor_date`; the prompt must include `Today: <anchor_date>`

After training, use the matching conversion notebook and upload the final GGUF
through GitHub Releases instead of committing it to Git.
