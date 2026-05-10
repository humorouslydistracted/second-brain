# Second Brain — Android (Phase 3c)

**Phase 3c adds, on top of 3b:**
- On-device sentence embeddings via `onnxruntime-android` 1.17.1.
- Pure-Kotlin BERT WordPiece tokenizer (`embedding/WordPieceTokenizer.kt`,
  ~150 lines, no extra JNI surface).
- `MiniLmEncoder.encode(text) -> FloatArray(384)` with mean pooling +
  L2-normalize done in Kotlin (model graph stays vanilla, so swapping the
  ONNX file in future doesn't require code changes).
- `EmbeddingsDao` stores vectors in the existing `embeddings` table as
  little-endian Float32 BLOBs (1536 bytes per note).
- **Embed-on-save** in `Orchestrator.saveNote` — fire-and-forget on a
  Default dispatcher so the user's write turn doesn't block on encoding.
- **Hybrid note search** in `QueryRunner.runNote`: 0.55 × lexical
  (substring + token-overlap) + 0.45 × cosine. Abstains with "No notes
  match" if the top score is below 0.20.
- Settings screen now shows embedding model status, count of stored
  embeddings, count of pending (unembedded) notes, **Load embedder**
  button, and **Re-embed pending notes** button for backfilling notes
  that were saved before you pushed the model.

## Pushing the embedding model files

Per Phase 3c, run `colab_export_minilm_onnx.ipynb` once. It produces three
files. Push them to the same models dir as the GGUF:

```bash
adb push minilm.onnx                  /sdcard/Android/data/com.secondbrain.app/files/models/
adb push minilm_vocab.txt             /sdcard/Android/data/com.secondbrain.app/files/models/
adb push minilm_tokenizer_config.json /sdcard/Android/data/com.secondbrain.app/files/models/
```

After push, open Settings → tap **Load embedder**. Status flips to
"Loaded." and "Embeddings stored / pending" counts populate.

If you've been using the app already, tap **Re-embed pending notes** to
backfill old notes with embeddings.

## Multilingual swap (future)

Today's tokenizer is BERT WordPiece for English `all-MiniLM-L6-v2`. To
upgrade to multilingual `paraphrase-multilingual-MiniLM-L12-v2`:
- Swap the export notebook to point at the multilingual model.
- Implement an XLM-RoBERTa SentencePiece Unigram tokenizer in Kotlin
  (Viterbi over vocab + scores from `tokenizer.json`), OR pull in
  `ai.djl.huggingface:tokenizers` (~12 MB APK cost) and load
  `tokenizer.json` directly.
- The ONNX graph signature is identical — same `input_ids` /
  `attention_mask` inputs, same 384-dim output — so `MiniLmEncoder`
  itself doesn't change.

**Phase 3b adds, on top of 3a:**
- Real Notes editor (list + single editor + add + delete + clear all).
- Real Expenses / Ledger / Weights / Todos / People / Dashboard screens
  with read views, basic add/delete/clear, and per-section "Copy" buttons
  that dump currently-visible rows in plain-text-table format.
- Numbered-clarify resolution: when the LLM returns `disposition=clarify`
  (query lane) or `disposition=confirm` (write lane, e.g. ambiguous
  ledger direction), the orchestrator persists a `pending_actions` row
  and Home shows a banner "Pending: … reply with 1–N or 'cancel'." Reply
  with the number and the action executes.
- Ledger settle: parser `action=settle` closes the running balance with
  a reverse-direction entry of equal amount.

**Phase 3a delivers:**
- SQLite database with all v1 tables (notes, captures, expenses, ledger,
  weights, todos, buy_items, persons, embeddings, pending_actions,
  runtime_state, activity_log, **request_log**, plus `ledger_balance` view).
- Parser layer: chat-template prompt builder + JSON validator + v2 schema
  data classes (`ParserSchema.kt` mirrors `validate_parser_payload` in the
  Python runtime).
- Tag chip rules — locked behavior:
  - `ask`, `expense`, `ledger`, `weight`, `todo`, `note`, `buy` chips
  - typed `<tag>:` while chip is active → strip text + toast "Tag already active"
  - typed `<tag>:` while chip is NOT active → strip text + activate chip
  - combo rule: `ask` + at most one domain, OR exactly one write, OR none
  - tap a write chip while another write is active → mutual exclusion
- Orchestrator: every Home submission goes through `Orchestrator.handle()`
  which calls the LLM parser, dispatches Write or Query payloads against
  SQLite, and captures everything in `request_log` (user input + chips +
  LLM prompt + raw JSON + every SQL with args + result samples + final
  text + per-stage timings + errors).
- Home screen with chip row, input box, Send, "Copy logs" button, and the
  last-10 activity feed.
- Activity log screen with checkbox-multi-select copy, "Copy all", "Clear".
- Settings screen with model load + GPU/CPU toggle + "Clear all logs".
- Drawer navigation to all 10 destinations (Notes / Dashboard / Expenses /
  Ledger / Weights / Todos / People are stubbed in 3a; real screens land in
  Phase 3b).

**Phase 3c will add:**
- ONNX MiniLM embeddings via `onnxruntime-android` + bundled XLM-RoBERTa
  SentencePiece tokenizer + hybrid lexical+semantic note search (a
  proper port of the Python `query_notes_result` hybrid scorer). Today
  notes search is lexical-only (LIKE).

---

## What's here

```
android/
├── settings.gradle.kts
├── build.gradle.kts
├── gradle.properties
├── gradle/wrapper/gradle-wrapper.properties
└── app/
    ├── build.gradle.kts
    ├── proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml
        ├── cpp/
        │   ├── CMakeLists.txt          # FetchContent of llama.cpp @ b3938, GGML_VULKAN=ON
        │   └── llama_jni.cpp           # JNI shim: load / generate / free
        ├── java/com/secondbrain/app/
        │   ├── MainActivity.kt         # one-screen Compose UI
        │   ├── LlamaCpp.kt             # Kotlin wrapper over JNI, single-thread dispatcher
        │   └── ChatTemplate.kt         # mirrors second_brain_finetuned_parser.py
        └── res/values/
            ├── strings.xml
            └── themes.xml
```

## Prerequisites

1. **Android Studio Hedgehog (2023.1) or later.** You said you already have it.
2. **NDK 26.3.11579264** (Studio → SDK Manager → SDK Tools → NDK side-by-side
   → check 26.3.11579264). Required: NDK r26+ ships Vulkan headers that
   llama.cpp's GGML_VULKAN backend needs.
3. **CMake 3.22.1** (same SDK Manager screen).
4. **Pixel 7 with USB debugging enabled.** ADB authorized.
5. **The GGUF from Phase 1** (`qwen3-1.7b-parser-q4_k_m.gguf`, ~1.1 GB).

## First-time build steps

1. Open Android Studio → "Open" → select the `android/` folder. Studio will
   sync Gradle, fetch dependencies, and clone llama.cpp into the CMake
   build dir on first native build (this clone happens once, takes ~2 min).
2. Plug in your Pixel 7. Studio should detect it.
3. Click **Run ▶** (or `Shift+F10`). First build is slow — llama.cpp
   compiles every source file. Expect 5-10 minutes. Subsequent builds
   are incremental.

## Pushing the GGUF to the phone

The app expects the file at:

```
/sdcard/Android/data/com.secondbrain.app/files/models/qwen3-1.7b-parser-q4_k_m.gguf
```

This path is `getExternalFilesDir("models")` — no permissions needed, file
survives app updates, and lives in the app's external scoped storage.

```bash
# After installing the APK once (so the dir exists):
adb shell mkdir -p /sdcard/Android/data/com.secondbrain.app/files/models/
adb push qwen3-1.7b-parser-q4_k_m.gguf /sdcard/Android/data/com.secondbrain.app/files/models/
```

PowerShell users:

```powershell
adb shell mkdir -p /sdcard/Android/data/com.secondbrain.app/files/models/
adb push .\qwen3-1.7b-parser-q4_k_m.gguf /sdcard/Android/data/com.secondbrain.app/files/models/
```

## What the screen does

- **Load model**: loads the GGUF with full-layer Vulkan offload by default.
  Toggle the switch to "CPU only" to compare timings. Reports load latency.
- **Prompt**: pre-filled with `ask: latest buy list` (your reported failing
  case). Edit it to whatever you want to test.
- **Send**: builds the exact same prompt the Python runtime would build
  (system prompt + `Today: <YYYY-MM-DD>` + Qwen3 chat template,
  enable_thinking=False), runs greedy generation up to 256 tokens, and
  shows the raw model output. Copy button next to the output.
- **Status line**: shows load + generate timings.

## What success looks like

For input `ask: latest buy list`, the output should be a single JSON object
along the lines of:

```json
{"task":"parse_query","domain":"buy","disposition":"accept","intent":"list","date_start":null,"date_end":null,"compare_date_start":null,"compare_date_end":null,"filters":{"status":"open","item_text":null},"limit":null,"query_text":null,"reason_code":null,"clarify_reason":null,"clarify_options":null}
```

If you instead get:
- non-JSON garble → chat template byte-mismatch (compare with Python output)
- valid JSON but with `intent: "latest"` → v2 parser hallucination we know
  about and will harden in Phase 3
- crash on load → check `adb logcat -s secondbrain_jni LlamaCpp` for the
  specific llama.cpp error

## What's deliberately missing

- DB, schema, captures, structured queries
- Tag chips and combo rules
- Activity log and request_log
- Per-section Copy buttons
- Embedding model
- Notes editor and all drawer screens
- Streaming generation (we just block until done)
- Tokenizer.json on the Kotlin side (llama.cpp tokenizes from the GGUF)

These are Phase 3.

## Troubleshooting

- **`UnsatisfiedLinkError: secondbrain_jni`** — clean rebuild. Studio
  sometimes caches an older `.so`.
- **`llama_model_load_from_file failed`** — check the file is actually at
  the path and not in `/Download` or `/sdcard/`. Run `adb shell ls -la
  /sdcard/Android/data/com.secondbrain.app/files/models/`.
- **GPU load takes a long time the first time** — Vulkan shader compilation
  is cached after the first run by the Adreno driver. Cold-cold should be
  ~5-10 s on Pixel 7; warm should be ~1-2 s.
- **CPU is faster than GPU on a small batch** — that's expected on phones
  for 1.7B models with short prompts; the GPU win shows up on long
  generations. Use the toggle to compare.
