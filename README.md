# Second Brain

A fully-local, on-device note-taking app for Android — dump notes in free-form English, query them conversationally, and let a small fine-tuned language model do the structured parsing for expenses, ledger, weights, todos, buy-lists, and notes. No accounts, no cloud, no telemetry. Everything runs on the phone.

## Core

- **General notes first.** Arbitrary text is saved as a normal note and embedded for semantic search. Same-day notes group into one daily blob with `[HH:MM:SS]` timestamps, newest at the top.
- **Structured layers on top.** Tap a chip (`expense:`, `todo:`, `buy:`, `weight:`, `ledger:`, `note:`, `ask:`) and the on-device parser extracts structured rows for the matching SQLite table.
- **Conversational queries.** The `ask:` lane handles "show this month expenses", "what is jeevi's latest weight", "who owes me money", typo-tolerant note retrieval, etc. Structured arithmetic stays in SQL — the model only parses intent.
- **Hybrid note search.** Lexical scoring (exact phrase / token / fuzzy / trigram) blended with cosine similarity over MiniLM embeddings, with an abstain threshold so unrelated hits aren't returned with false confidence.
- **Append-only with undo.** Every write shows an undo chip for ~5 seconds. Wrong entries are reversible without going through an edit screen.

## Surfaces

- **Home** — chat-style activity feed, ambient nudge strip, processing banner, undo chip, compact 2×3 tiles for the six structured domains, chip row, input bar.
- **Activity log** — paginated full history of every input + response with one-tap copy of the diagnostic block (parser prompt, raw JSON, SQL with bound args, sample rows, timings).
- **Notes / Expenses / Ledger / Weights / Todos / Buy / People** — direct CRUD with section-level Copy and Clear.
- **Settings** — model + embedder load state, RAG synthesis toggle, event-log dump.

## Stack

- **Parser** — Qwen3-1.7B fine-tuned on a synthetic India-first dataset (~62k rows across `parse_write` / `parse_query` / `parse_followup_query`), exported as a Q4_K_M GGUF. Runs on-device via llama.cpp + JNI.
- **Embeddings** — `all-MiniLM-L6-v2` exported to ONNX, served via onnxruntime-android. WordPiece tokenizer in pure Kotlin.
- **Storage** — SQLite (`notes`, `expenses`, `ledger`, `weights`, `todos`, `buy_items`, `persons`, `embeddings`, `activity_log`, `request_log`, `event_log`).
- **UI** — Jetpack Compose, minSdk 26, arm64-only.

## Getting started

1. Grab the latest `app-debug.apk` from the [Releases](https://github.com/humorouslydistracted/second-brain/releases) page.
2. Sideload it on a Pixel 7 (or similar arm64 device with ~3 GB free).
3. Open the app once so its scoped-storage folder is created at `/sdcard/Android/data/com.secondbrain.app/files/`.
4. Push the four model files into that folder's `models/` subdirectory:
   - `qwen3-1.7b-parser-q4_k_m.gguf` (the fine-tuned parser)
   - `minilm.onnx`, `vocab.txt`, `minilm_tokenizer_config.json` (the embedding stack)
5. Settings → **Load model** + **Load embedder**.
6. Home → tap a chip → type → Send.

The model files are not bundled in the APK (1+ GB combined). Build them yourself via `colab_convert_to_gguf.ipynb` (parser) and `colab_export_minilm_onnx.ipynb` (embedder), or contact the author.

## Building from source

The Android build is the canonical surface. Full prerequisites, exact commands, and the table of permanent fixes for known build issues live in **[`android_port.md`](android_port.md) § "🛠 BUILD GUIDE"**.

Quick path on Windows:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
cd android
.\gradlew.bat --no-daemon assembleDebug
```

Output lands at `android\app\build\outputs\apk\debug\app-debug.apk` (~55 MB).

First clean build is ~5–10 min (Gradle cache populate + llama.cpp clone via FetchContent + ~270 C++ files compiled). Incremental Kotlin-only changes are ~30–60 s.

## Repository layout

```
android/                                Active product surface (Kotlin + JNI + Compose)
android_port.md                         Android architecture, phase status, build guide
project_development.md                  Engine + dataset + fine-tune history (long)
finetuning_data_sanity.md               Locked v1 schema for parse_write / parse_query / parse_followup_query
dataset_v2_plan.md                      v2 schema/diversity/anchor_date plan
dataset_india_context_rulebook.md       India-context dataset rules
current_state.md                        Short orientation index across the docs above

generate_large_schema_frozen_dataset_v2.py   v2 synthetic dataset generator
synthetic_dataset_assets.py                   Asset pools (names, items, dates, Tanglish)
generate_eval_dataset_v3.py                   v2-schema held-out eval generator
colab_finetune.py                             Colab/Kaggle fine-tune script (Unsloth + train_on_responses_only)
colab_convert_to_gguf.ipynb                   Merge LoRA → Q4_K_M GGUF
colab_export_minilm_onnx.ipynb                Export MiniLM → ONNX
kaggle_finetune.ipynb / kaggle_evaluate.ipynb Kaggle equivalents

second_brain_core.py / second_brain_orchestrator.py / app.py
                                        Retired Flask reference engine (kept for parser-design history)
seed.sql                                Engine-side schema + seed reference
```

## Status

The Android app is the active product surface as of 2026-05-08. The Flask web app is retired and kept only as the historical engine reference — see `project_development.md` for the full multi-month development log.

Open work items, in-progress fine-tune cycles, and shipped/queued features are tracked in `current_state.md` and `android_port.md`.

## License

[MIT](LICENSE)
