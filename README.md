# Second Brain

Second Brain is an offline-first Android notes app that turns messy personal
notes into structured local data. It is built for quick capture first: write
free-form notes, expenses, todos, ledger entries, weights, and buy-list items;
then query them conversationally without sending data to a server.

The current product surface is the native Android app in `android/`.

## Why It Exists

Most note apps store text but do not understand it. Second Brain keeps the text
entry flow lightweight while adding structured recall:

- "expense: rice 80, bus 25"
- "todo: pay electricity bill tomorrow"
- "ledger: Arun owes me 500"
- "weight: 72.4 before breakfast"
- "ask: this month expenses"

The app stores exact rows in SQLite and uses a small local parser model only to
turn human text into structured intent. SQL handles totals, filters, balances,
and history.

## Highlights

- Native Android app built with Kotlin, Jetpack Compose, SQLite, JNI, and
  llama.cpp.
- Local parser path for expenses, todos, buy-list items, weights, ledger
  entries, notes, and conversational queries.
- Hybrid note retrieval using lexical scoring plus MiniLM embeddings exported
  to ONNX.
- Activity log with request diagnostics for parser JSON, SQL, timings, and
  user-visible responses.
- Undo support for reversible writes.
- Self-name handling for "me", "my", and similar personal references.
- Multi-model picker for parser GGUF files in the app's local model folder.
- Training, conversion, evaluation, and dataset tooling for Qwen3 parser
  experiments on Kaggle, Colab, or a local GPU machine.

## Tech Stack

| Area | Choices |
| --- | --- |
| App | Kotlin, Jetpack Compose, Material 3 |
| Runtime model | llama.cpp through JNI, Qwen3 parser GGUF files |
| Embeddings | MiniLM ONNX through onnxruntime-android |
| Storage | SQLite tables for notes, expenses, ledger, weights, todos, buy-list, people, embeddings, and logs |
| Tooling | Python dataset generators, Kaggle/Colab fine-tuning notebooks, GGUF conversion notebooks |
| Privacy | No account, no backend, no telemetry |

## Repository Layout

```text
.
|-- android/                    # Active Android app
|-- docs/                       # Public architecture and model notes
|-- tools/
|   |-- datasets/               # Synthetic data, eval, and manual parser tooling
|   `-- model-training/         # Kaggle/Colab/local fine-tune + export tooling
|-- prototypes/
|   `-- flask-reference/        # Retired Python web prototype and regression tests
|-- LICENSE
`-- README.md
```

## Install

Download an APK from the GitHub releases page and sideload it on an Android
device. The model files are intentionally not committed to the repository
because they are large.

The app expects parser and embedder files under:

```text
/sdcard/Android/data/com.secondbrain.app/files/models/
```

Typical files:

- `qwen3-1.7b-parser-q4_k_m.gguf`
- `qwen3-0.6b-parser-q4_k_m.gguf` optional smaller parser
- `minilm.onnx`
- `vocab.txt`
- `minilm_tokenizer_config.json`

Open Settings in the app and load the parser model and embedder after copying
the files.

## Build From Source

Requirements:

- Android Studio with Android SDK 34+
- JDK 17 or newer
- Android NDK matching `android/app/build.gradle.kts`
- CMake matching `android/app/build.gradle.kts`

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
cd android
.\gradlew.bat :app:assembleDebug
```

Debug APK:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

See [android/README.md](android/README.md) for model placement and Android
build notes.

## Model And Dataset Tooling

The parser model is trained as a structured JSON parser, not as a general
chatbot. The intended split is:

- model: parse messy user text into JSON intent
- app code: validate, store, query, calculate, and render

See:

- [docs/architecture.md](docs/architecture.md)
- [docs/model-training.md](docs/model-training.md)
- [tools/model-training](tools/model-training)
- [tools/datasets](tools/datasets)

## Privacy

Second Brain is designed for private local data:

- no account
- no analytics service
- no cloud sync
- no cloud model API
- user notes and structured records stay in the local SQLite database

Kaggle, Colab, and local GPU scripts are optional development tools for building
model artifacts. Runtime use is on-device.

## Status

This is an active personal/open-source project. The Android app is the current
surface; the Flask prototype is archived under `prototypes/flask-reference/`
for design history and regression reference.

## License

[MIT](LICENSE)
