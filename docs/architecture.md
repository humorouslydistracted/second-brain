# Architecture

Second Brain separates capture, parsing, storage, and retrieval so a small local
model is not asked to be a database.

## Flow

1. The user writes a note or tagged input in the Android app.
2. The parser layer turns the input into a structured JSON payload.
3. Kotlin validators normalize the payload and reject invalid shapes.
4. SQLite write/query runners perform the actual data operation.
5. The UI renders a concise response and records diagnostics in the activity
   log.

## Runtime Layers

| Layer | Responsibility |
| --- | --- |
| Compose UI | Home feed, domain screens, Settings, Activity log, app navigation |
| Orchestrator | Single entry point for tagged writes, queries, clarification, and undo |
| Parser service | Runs the selected local GGUF parser through llama.cpp/JNI |
| Manual parser | Deterministic fallback/parser for supported common patterns |
| SQLite | Source of truth for notes, structured records, embeddings, and logs |
| MiniLM embedder | ONNX sentence embeddings for hybrid note retrieval |

## Parser Contract

The model should only produce structured JSON. It should not calculate totals,
carry long-term memory, or decide final database state on its own.

The app code owns:

- date filtering
- totals and balances
- CRUD operations
- undo behavior
- activity/request logging
- final UI rendering

This makes model errors visible and recoverable: invalid JSON or invalid fields
are rejected before they reach SQLite.

## Privacy

Runtime data stays on the Android device. Model training notebooks and dataset
generators are development tools only; the app does not call a server or cloud
model during normal use.
