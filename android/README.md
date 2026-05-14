# Second Brain Android App

This folder contains the active product surface: a native Android app built
with Kotlin, Jetpack Compose, SQLite, MiniLM ONNX embeddings, and llama.cpp
through JNI.

## Build

Requirements:

- Android SDK 34+
- JDK 17+
- Android NDK `30.0.14904198`
- CMake `4.1.2`

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:assembleDebug
```

Output:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Runtime Model Files

Install the APK once so Android creates the scoped-storage folder, then copy
model files into:

```text
/sdcard/Android/data/com.secondbrain.app/files/models/
```

Parser model examples:

```text
qwen3-1.7b-parser-q4_k_m.gguf
qwen3-0.6b-parser-q4_k_m.gguf
```

Embedder files:

```text
minilm.onnx
vocab.txt
minilm_tokenizer_config.json
```

After copying, open the app and use Settings to load the parser model and
embedder. The app can discover multiple parser GGUF files and lets the user
switch between them from Settings.

## Main Components

| Path | Responsibility |
| --- | --- |
| `app/src/main/java/com/secondbrain/app/MainActivity.kt` | Compose entry point and navigation host |
| `app/src/main/java/com/secondbrain/app/orchestrator/` | Parser dispatch, write/query execution, undo metadata |
| `app/src/main/java/com/secondbrain/app/parser/` | Parser schema, shape adapter, manual parser fallback |
| `app/src/main/java/com/secondbrain/app/data/` | SQLite database and DAOs |
| `app/src/main/java/com/secondbrain/app/embedding/` | MiniLM ONNX encoder and tokenizer |
| `app/src/main/cpp/` | llama.cpp JNI bridge |

## Troubleshooting

- `llama_model_load_from_file failed`: confirm the GGUF is in the app's
  `files/models/` directory, not Downloads.
- `UnsatisfiedLinkError: secondbrain_jni`: clean and rebuild the Android app.
- Slow first model load: native libraries and model pages may be cold; retry
  after the first load completes.
