"""
Local equivalent of `colab/export_minilm_onnx.ipynb`.

Run from PowerShell after activating the venv (see export_minilm_onnx_README.md):
    python export_minilm_onnx.py

Outputs three files under `./minilm_export/`:
    minilm.onnx                    (~6 MB int8 / ~22 MB f32)
    minilm_vocab.txt               (~230 KB)
    minilm_tokenizer_config.json   (<1 KB)

Push these to the phone via adb. The Android app reads them from
/sdcard/Android/data/com.secondbrain.app/files/models/.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# -------- CONFIG ------------------------------------------------------------
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
OUT_DIR = Path("minilm_export")
QUANTIZE_INT8 = True       # set False to keep ~22 MB f32; True gives ~6 MB
MAX_SEQ_LEN = 256          # matches the Kotlin tokenizer config
# ----------------------------------------------------------------------------

OUT_DIR.mkdir(parents=True, exist_ok=True)
ONNX_OUT = OUT_DIR / "minilm.onnx"
VOCAB_OUT = OUT_DIR / "minilm_vocab.txt"
TOKENIZER_CONFIG_OUT = OUT_DIR / "minilm_tokenizer_config.json"
WORK_DIR = OUT_DIR / "work"
WORK_DIR.mkdir(parents=True, exist_ok=True)


def step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}", flush=True)


def main() -> None:
    step(1, f"Exporting {MODEL_ID} to ONNX (this downloads ~80 MB on first run)...")
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer

    model = ORTModelForFeatureExtraction.from_pretrained(MODEL_ID, export=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    export_dir = WORK_DIR / "export"
    model.save_pretrained(str(export_dir))
    tokenizer.save_pretrained(str(export_dir))

    src_onnx = export_dir / "model.onnx"
    if not src_onnx.exists():
        sys.exit(f"ERROR: optimum did not produce {src_onnx}")
    shutil.copy(src_onnx, ONNX_OUT)
    print(f"    wrote {ONNX_OUT}  ({ONNX_OUT.stat().st_size / 1_048_576:.1f} MB)")

    if QUANTIZE_INT8:
        step(2, "Quantizing to int8 (lossy, ~4x smaller, marginal accuracy hit)...")
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quant_path = WORK_DIR / "minilm_int8.onnx"
        quantize_dynamic(
            model_input=str(ONNX_OUT),
            model_output=str(quant_path),
            weight_type=QuantType.QUInt8,
        )
        quant_path.replace(ONNX_OUT)
        print(f"    quantized -> {ONNX_OUT}  ({ONNX_OUT.stat().st_size / 1_048_576:.1f} MB)")
    else:
        step(2, "Skipping int8 quantization (QUANTIZE_INT8=False)")

    step(3, "Saving tokenizer vocab + config for the Kotlin tokenizer...")
    src_vocab = export_dir / "vocab.txt"
    if not src_vocab.exists():
        sys.exit(f"ERROR: tokenizer did not produce {src_vocab}")
    shutil.copy(src_vocab, VOCAB_OUT)

    cfg = {
        "do_lower_case": bool(getattr(tokenizer, "do_lower_case", True)),
        "unk_token": tokenizer.unk_token,
        "pad_token": tokenizer.pad_token,
        "cls_token": tokenizer.cls_token,
        "sep_token": tokenizer.sep_token,
        "max_seq_len": MAX_SEQ_LEN,
        "embedding_dim": 384,
        "pooling": "mean",
        "l2_normalize": True,
    }
    TOKENIZER_CONFIG_OUT.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"    wrote {VOCAB_OUT}  ({VOCAB_OUT.stat().st_size:,} bytes)")
    print(f"    wrote {TOKENIZER_CONFIG_OUT}")

    step(4, "Sanity check: cosine similarity on a related/unrelated pair...")
    import numpy as np
    import onnxruntime as ort

    sess = ort.InferenceSession(str(ONNX_OUT), providers=["CPUExecutionProvider"])

    # all-MiniLM-L6-v2 is a BERT-family model: it expects three inputs
    # (input_ids, attention_mask, token_type_ids). For single-sentence
    # embeddings, token_type_ids is an all-zero vector. The tokenizer
    # produces it automatically; we just have to forward it.
    expected_inputs = {i.name for i in sess.get_inputs()}

    def embed(text: str) -> np.ndarray:
        enc = tokenizer(
            text, padding="max_length", truncation=True,
            max_length=MAX_SEQ_LEN, return_tensors="np",
        )
        feed: dict[str, np.ndarray] = {
            "input_ids": enc["input_ids"].astype(np.int64),
            "attention_mask": enc["attention_mask"].astype(np.int64),
        }
        if "token_type_ids" in expected_inputs:
            feed["token_type_ids"] = enc.get(
                "token_type_ids",
                np.zeros_like(enc["input_ids"]),
            ).astype(np.int64)
        outputs = sess.run(None, feed)
        last = outputs[0][0]                                  # (seq, 384)
        mask = enc["attention_mask"][0][:, None].astype(np.float32)
        pooled = (last * mask).sum(axis=0) / mask.sum().clip(min=1.0)
        pooled /= np.linalg.norm(pooled) + 1e-12
        return pooled

    a = embed("How much did I spend on petrol last month?")
    b = embed("Show me transport expenses for last month")
    c = embed("Recipe for dosa batter")
    sim_related = float(a @ b)
    sim_unrelated = float(a @ c)
    print(f"    similar:    {sim_related:.3f}   (should be > 0.5)")
    print(f"    unrelated:  {sim_unrelated:.3f}   (should be < 0.4)")
    if sim_related <= sim_unrelated:
        print("    WARNING: similar pair did NOT score higher than unrelated. Investigate.")

    step(5, "Done.")
    print(f"\nFiles ready in {OUT_DIR.resolve()}:")
    for p in (ONNX_OUT, VOCAB_OUT, TOKENIZER_CONFIG_OUT):
        print(f"  {p.name}  ({p.stat().st_size:,} bytes)")
    print("\nPush them to the phone:")
    print("  adb shell mkdir -p /sdcard/Android/data/com.secondbrain.app/files/models/")
    print(f'  adb push "{ONNX_OUT}"            /sdcard/Android/data/com.secondbrain.app/files/models/')
    print(f'  adb push "{VOCAB_OUT}"           /sdcard/Android/data/com.secondbrain.app/files/models/')
    print(f'  adb push "{TOKENIZER_CONFIG_OUT}" /sdcard/Android/data/com.secondbrain.app/files/models/')


if __name__ == "__main__":
    main()
