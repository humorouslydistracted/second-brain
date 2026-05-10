# Android Port — Tracker

**Active workstream as of 2026-05-08. v1 spec complete + 18 builds in,
inference working at native speed on Pixel 7. Now in UX/dogfood
iteration.** This is the source of truth for the Android client and
supersedes the Flask app for new work. Flask is kept as the
historical/dogfooding reference; nothing new lands there. For the broader
product context (parser schema, dataset, fine-tune history), keep reading
`project_development.md`. For runtime build/install instructions on the
phone, see `android/README.md`.

**Status at a glance**

| Phase | Status | Headline deliverable |
|---|---|---|
| 1 — GGUF conversion notebook | ✅ shipped | `colab_convert_to_gguf.ipynb` produces a Q4_K_M ~1.1 GB GGUF |
| 2 — Skeleton app + JNI smoke test | ✅ shipped | `android/` loads GGUF, runs one prompt, GPU/CPU toggle |
| 3a — Foundation + Home + Activity + Settings | ✅ shipped | DB, parser+validator, chip rules, orchestrator, request_log, Home/Activity/Settings end-to-end |
| 3b — Structured screens + clarify resolution | ✅ shipped | Notes/Expenses/Ledger/Weights/Todos/People/Dashboard with per-section Copy; numbered-clarify resolution |
| 3c — ONNX MiniLM + hybrid note search | ✅ shipped | `colab_export_minilm_onnx.ipynb` + local fallback `export_minilm_onnx.py`; pure-Kotlin BERT WordPiece tokenizer; embed-on-save; hybrid lex+semantic scorer with abstain |
| 3-build — first install on Pixel 7 + working inference | ✅ build #18, 2026-05-08 20:21 | After 18 build iterations: `app-debug.apk` 52.15 MB, llama.cpp `b6500`, CPU-only at ~10 tok/s on Pixel 7 (8 s for 82-token prompt prefill + ~50 token generation), in-app importer for model files, auto-load on launch, Cancel via abort_callback, comprehensive request_log, Qwen3 thinking-tag suppression. **Inference functional end-to-end.** |
| 3d — GPU/Vulkan offload | 🟡 queued | requires two-stage llama.cpp build (host `vulkan-shaders-gen` then Android arm64 lib); single-pass AGP build can't satisfy this |
| **3e — UX overhaul from device dogfooding** | **✅ build #19, 2026-05-08 21:06** | Tag chips reordered (ask/todo/expense/note/weight/buy/ledger), Home redesigned chat-style (feed at top, chips+input pinned at bottom), top-right custom toast overlay with 2.5 s auto-dismiss + slide animations, **submission queue** (input clears immediately, processing shows as 3-dot-pulse bubble inline, multiple submissions queue serially), DB v2 (`datetime('now','localtime')` defaults so timestamps match phone notification time), new `event_log` table for the comprehensive diagnostic feed (capped at 2000 rows with auto-archive to dated `.jsonl` files), `Thread.setDefaultUncaughtExceptionHandler` captures Kotlin/Java crashes into event_log, "Clear all logs" now emits on `AppStatusBus` so Home + Activity log re-fetch immediately. Deferred to 3f: per-CRUD toast emissions, Settings UI for event_log cap config, Copy event log button. |
| 3f — UX polish + per-CRUD toasts | 🟡 queued | Toast emissions on every CRUD op (Add/Delete/Clear in Notes/Expenses/Ledger/Weights/Todos/People), Settings UI for `event_log` cap dropdown + Copy event log button, persistent worker resumption if app killed mid-queue. |
| **3g — Home redesign + auto-add people + activity-log fixes** | **✅ build #26, 2026-05-08** | Home rewritten as a 2-page `HorizontalPager`: page 0 = 6 tiles (Todos / Expenses / Buy / Weights / Notes / Ledger) each showing a one-line live count, page 1 = chat-history feed with pending bubbles + recent activity. Shared bottom `HomeInputBar`. Drawer trimmed to 4 entries (Home, Activity log, People, Settings) — domain composables remain registered for tile-click navigation. `WriteRunner.ensurePersonExists` auto-adds new persons when weight/ledger writes reference an unknown name + emits an AppStatusBus toast. ActivityLogScreen copy bug fixed: `buildClipboard(selectedIds)` takes an explicit snapshot before the IO hop and uses a single batched IN-clause query (was per-row, racing on selection mutation). Stable toolbar layout: All / None / spacer / Refresh / Copy(N) / Clear. |
| **3h — Icon + self-name + undo + notes-per-day + RAG synth toggle** | **✅ build #27, 2026-05-08** | Adaptive launcher icon (vector "SB" lettermark on navy circle). First-launch self-name onboarding modal hoisted at `MainActivity` root; `data/SelfName.kt` persists to `runtime_state`; `WriteRunners.resolveSelf()` rewrites `{self, me, i, myself, mine, myne}` to the saved name on weight + ledger person fields. Editable Settings field for the same. Per-day notes grouping in `Orchestrator.saveNote()` — first note today inserts a new row prefixed `[HH:MM:SS]`, subsequent notes UPDATE that row appending `\n\n[HH:MM:SS] <text>`. `parser/NoteSynthSetting.kt` toggle (Settings switch, off by default) — when on, `QueryRunner.runNote` adds an extra LLM round-trip that synthesizes a 1-2 sentence answer over the retrieved snippets and prepends it. **Undo button**: every reversible orchestrator request returns an `UndoToken` (row deletes per lane + auto-added persons + note insert/append restore + tied embedding rows); HomeViewModel surfaces a 5 s undo chip above the input bar; tap → `Undoer.execute` rolls back in a transaction (auto-added persons only deleted if no other table references them). |
| Schema mismatch (`data:` vs trained `records:`) | 🟡 root cause found 2026-05-09, re-finetune queued | Model emits `{"data":{...}}` instead of trained `{"records":[...]}`. **Root cause: `colab_finetune.py` was missing completion-only loss masking** — SFTTrainer was computing loss across the entire chat template (system + user + assistant), so the JSON output got only ~10-15% of the gradient signal. Dataset is correct (100% of rows use `records:[]`); the trainer was diluting the schema signal. Fix: added `train_on_responses_only(trainer, instruction_part, response_part)` after the SFTTrainer call + flipped `packing=False` (packing without completion-only loss leaks gradient across example boundaries). `MAX_SEQ_LENGTH` bumped 1024→1536 to fit 12-item record JSON outputs. Combined with the dataset patches below, `parser/ShapeAdapter.kt` will become dormant. |
| Dataset gap patches (2026-05-09, 20 total) | ✅ shipped to generator, awaiting regen + retrain | **Round 1 (12 patches mapped 1:1 to dogfood failures):** (1) buy long-list 4-12 items, (2) todo long-list 4-8 + person-in-text variants (`prabu son paaka ponum`), (3) expense long-list 4-10, (4) trailing-comma augmentation, (5) buy undated bare phrasings + bare-rate 10%→35%, (6) note bare-name clarify rows, (7) expense filter null-bias rebalance + undated desc rows, (8) ledger bare-balance with `perspective:null` + bare-rate 10%→30%, (9) Tanglish verb branch in buy (`vanganum`/`vaanganum`/`kekanum`/`kooda`), (10) English day-of-week in person-in-text todos, (11) buy quantity aliases (`gms`/`ltr`/`kgs`/`packet`), (12) settle/repay Tanglish + English phrasings (`settle pannitten`/`paid back fully`). **Round 2 (8 patches added after user pushback for "in this lifetime" robustness):** (13) currency notation depth (`5K`/`5 thousand`/`Rs.5000`/`5000/-`/`5L`/`5 lakhs`/`3 crores` — `amount_text_and_value` extended 8→16 styles), (14) absolute date format breadth (`15-02-2026`/`15/02/2026`/`15.02.2026`/`15-02-26`/`15/2`/`15th Feb`/`Feb 15`/`15th of Feb` via 15 formatters in `pick_numeric_date_phrase`, 12% of dated writes), (15) festival/event-relative dates (24 festivals: Pongal/Diwali/Onam/Karthigai/etc. + 14 personal events: `before exam`/`after wedding`, 8% of dated writes), (16) top-N expense queries (`top 3 expenses`/`biggest 5 spending`, new `top_n` form weight 5, emits explicit `limit:n`), (17+18) input noise (`apply_input_noise` shared helper across all 5 write makers — double-space, leading/trailing, ALL-CAPS, no-space-digit, mixed separators), (19) quantity fractions/ranges (`half kg`/`1/2 kg`/`2-3 kg`/`~2 kg`/`about 2 kg` — input only, records canonical), (20) corpus expansion ~360 items (~100 Tanglish vegetables/pulses/snacks/dairy/meat/festival items + ~200 brand-product compounds: Amul/Aavin dairy, Aachi/Sakthi/MTR spices, Aashirvaad atta, India Gate basmati, Tata Sampann dal, Mysore Sandal/Cinthol/Pears soaps, Surf Excel/Tide detergents, Colgate/Sensodyne toothpaste, etc.). **Pool sizes after Round 2:** INDIA_BUY 1288→1550 (+262), INDIA_EXPENSE['groceries'] 421→494 (+73), INDIA_EXPENSE['personal_care'] 263→288 (+25). `synthetic_dataset_assets.py` `_TANGLISH_BUY_ONLY` pool (Round 1) covers user's actual logged items: Manjal, kasthuri methi, kasthuri manjal, killer nighty, kili pachai saree, Gaza gasa, uluntha parupu, etc. **Smoke-verified at 800 rows/lane:** records-per-row extends to 11 buy / 8 todo / 10 expense; all 16 currency styles firing; all 5 absolute date formats firing; 53 festival/event phrases; 29/500 top-N expense queries; 102 buy rows mention a known brand; expense filter-bearing share 21%→43%; Tanglish verb fires in 7% of buy rows. **Deliberately NOT in scope:** Malayalam/Kannada/Telugu (user only types Tanglish+English), voice-to-text augmentation (always types), yes/no & when-did query intents (need Android schema changes), status-change/delete-edit lanes (need new lanes), multi-keyword expense filter (needs new `description_text_set` field). All deferred to separate cycles. |
| Ambient nudges feature (V1 spec locked, build queued) | 📋 design done 2026-05-09, gated by re-finetune | Replaces "morning digest" idea per user redirect. App maintains a pool of one-at-a-time domain-rotating callouts (`Jeevi's last weight 32 days ago`, `Maddy still owes ₹5k`, `salt on buy list 14 days`, etc.). On app launch (if last surface >30 min ago AND unsurfaced count > 0) → surface one fact as chat bubble in Home page-1, mark surfaced. Pool refreshes when unsurfaced count < 3. Six generators: 5 deterministic SQL (weight/buy/todo/ledger/expense) + 1 LLM-driven (notes — runs at every refresh per user request, uses exclusion-list prompt against already-surfaced note IDs). New `nudge_facts` table. Tap-to-navigate + dismiss. Full design in memory: `ambient_nudges_design.md`. |
| Query response LLM polish (V1 spec locked, build queued) | 📋 design done 2026-05-09, gated by re-finetune | User flagged template responses feel SQL-like (`Jeevi weight: 60.0kg on 2026-05-03`). Adds a synthesis layer in `Orchestrator.handle` AFTER `QueryRunner.run` returns template text: passes `(userQuery, templateText)` to the on-device parser model with a "render naturally in 1-2 sentences using ONLY these facts" prompt. Falls back to template on failure. Settings toggle (default ON). Chevron expands raw template text underneath. Queries only — writes stay snappy. Mirrors existing `NoteSynthSetting` pattern (build #27). Full design in memory: `query_response_polish.md`. |
| Weight runner fallback fix (Layer 1) | ✅ shipped 2026-05-09 | User dogfood log #105 (`ask: what is jeevi weight` → returned Amma's weight) revealed `runWeight` silently fell back to "most recent person in weights table" when filter was null. Producing confident wrong answers. New helper `resolvePersonForWeight(...)` first tries to recover a person name from the input text by intersecting tokens against the persons table + distinct persons in weights table; only falls back to "self" if no name is in the input either (no more "most recent" footgun). `QueryRunner.run` now takes `userText` parameter, threaded from `Orchestrator.handle`. Compiles clean (BUILD SUCCESSFUL 21s). Will ship in next APK. |
| Followup dataset cross-domain rows (Layer 3a) | ✅ shipped to generator, awaiting regen + retrain | Audit found 6000/6000 (100%) of `parse_followup_query` rows were same-domain. Zero "context discard" rows. Model would be biased toward over-inheriting if context-passing is wired on Android. New `_followup_cross_domain` helper: ~25% of followup rows now use a context from one domain + an input/output from a different domain, with `output.task = "parse_query"` (NOT `parse_followup_query`). Smoke verified 26.8% cross-domain rate, all 536 cross-domain rows have correct `parse_query` task. Trains the model "switch domain → discard prior context". |
| Question-shape weight query templates (Layer 2) | ✅ shipped to generator, awaiting regen + retrain | `WEIGHT_LATEST_TEMPLATES` expanded with bare-question shapes the user actually types: `{person} weight`, `weight of {person}`, `what is {person} weight`, `what's {person} weight`, `whats {person} weight`, `how much does {person} weigh`, `{person} weight please`, `{person} weight?`, plus matching verb-form variants. Fixes the #105 phrasing failure where `ask: what is jeevi weight` produced null person filter. ~10 new `noun` + 8 new `verb` + 11 new `question` templates. |
| Followup context-passing on Android (Layer 3b — DEFERRED) | 📋 deferred until after re-finetune validates | User wants this feature. Plan: store last accepted query JSON in `runtime_state` on every successful `parse_query`; update `ChatTemplate.buildPrompt` to optionally accept a context JSON and inject the dataset's exact `Previous structured query context:\n{ctx}\n\nUser input:\n{text}` block; `Orchestrator.handle` reads stored context and passes it for queries (not writes); when payload `task == parse_followup_query`, runner merges `inherit_context` fields. ~150 lines of Kotlin. Held until new GGUF lands so the model isn't biased toward over-inheriting before the cross-domain training takes effect. |
| `ParserService.maxTokens` 200 → 512 (2026-05-09) | ✅ shipped, BUILD SUCCESSFUL | The new dataset trains buy/expense lists up to 12 items (~300 tokens of records JSON + 30-token wrapper ≈ 330 tokens output). The previous 200-token cap would silently truncate every long-list output and produce broken JSON falling through to note-save. Bumped default to 512 for headroom on 15-item lists with longer item names. |
| **Build #28 — UX overhaul (2026-05-09)** | ✅ all six fixes shipped, BUILD SUCCESSFUL | Six in-session fixes after device dogfood feedback. **(1)** Todo tile crash — root cause was a one-character mismatch: `TilesPage` rendered a tile with route `"todo"` (singular) but `AppNav.kt` only registered the composable as `"todos"` (plural). `navController.navigate("todo")` threw `IllegalArgumentException: navigation destination 'todo' is not in the navigation graph`. Fixed in `HomeScreen.kt`. **(2)** Self-name moved from Settings to People page. New `PeopleScreen` shows an `AssistChip("self")` next to whichever person matches `SelfName.get(db)`. Each person row has a 3-dot overflow with `Set as self / Rename / Delete`. Switching self only changes future writes — historical `weights`/`ledger` rows stay unchanged (the data layer was already correct, just the UI surface moved). Renaming an active-self person also updates the saved self_name so resolution stays consistent. Settings field removed. **(3)** Compact 2×3 tile grid at bottom of Home. Removed the HorizontalPager entirely (no more page-0 tiles vs page-1 chat swipe). New layout top-to-bottom: AmbientFactStrip → ProcessingBanner → UndoChip → ChatHistoryPage (scrollable, takes available space) → CompactTilesGrid (2 rows × 3 cols, 78dp tall vs old 120dp) → HomeInputBar. Tiles are always visible directly above the input. **(4)** Rotating ambient nudge strip in the top area. New `AmbientFacts.kt` computes 6–14 natural-language one-liners from real DB state via pure SQL: stale weights (`Jeevi was last weighed N days ago`), long-pending buy items (`salt has been on your buy list for N days`), open ledger balances (`Maddy still owes you ₹5,000` / `You still owe Thenna ₹2,000`), pending todo backlog (`N todos from earlier still pending`), this-month expense total, headline counts. Caller is `HomeViewModel` which rotates one fact every 8s via a coroutine and recomputes the pool on every AppStatusBus event. **V0 is template-only**, no LLM call — the planned V1 (LLM polish + LLM-driven note callouts with exclusion-list prompt) is the existing `ambient_nudges_design.md` spec, deferred to land after re-finetune validates. **(5)** Notes per-day blob now newest-first. `Orchestrator.saveNote` flipped from `existingText + "\n\n[HH:MM:SS] $content"` to `"[$now] $content\n\n$existingText"` so the latest entry sits at the top of today's row. **(6)** Removed the auto-jump-to-chat-page-on-Send. The `LaunchedEffect(state.pending.size)` that scrolled the pager to page 1 was disorienting per user feedback; with the new layout there's no pager anyway, but the explicit removal stays in case anyone re-introduces a swipe. Feedback now comes from the always-visible ProcessingBanner + AppToastHost. **All six compile clean. APK ready for push.** |

**Where we are:** the app installs, models auto-load, inference runs at
expected Pixel 7 CPU speeds, and one-shot `weight:` / `expense:` / `todo:`
submissions reach the LLM and get JSON back. Next round of iteration is
driven by real-device dogfooding — see "3e UX iteration" below.

---

## ⚠️ STRONG NOTE — read before any re-finetune

**Root cause of schema drift was identified 2026-05-09 and fixed in
`colab_finetune.py`.** The dataset was always correct (100% of rows in
`synthetic_finetune_dataset_v4_v2_schema/` use `records:[]`); the trainer
was the problem. SFTTrainer was computing loss on the entire chat
template — system + user + assistant — so the JSON output got only
~10–15% of the gradient signal. The model learned to predict generic
chat-template tokens well and the strict JSON shape weakly, then fell
back at inference to the simpler `data:{...}` pattern from pre-training.

**The trainer fix (already committed):**

```python
# colab_finetune.py — added after the SFTTrainer(...) call
from unsloth.chat_templates import train_on_responses_only

trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",
    response_part="<|im_start|>assistant\n",
)
```

Plus `ENABLE_PACKING = False` (packing without completion-only loss
masking leaks gradient across example boundaries) and `MAX_SEQ_LENGTH`
bumped 1024 → 1536 to fit the new 12-item record JSON outputs.

`parser/ShapeAdapter.kt` stays in place as defense-in-depth — early
exits when the model already emits `records:[]`, costs nothing.

**Pre-flight checklist before kicking off the next Colab/Kaggle run:**

1. **Verify the trainer fix is in `colab_finetune.py`.** Search for
   `train_on_responses_only` near the SFTTrainer block. If it's
   missing, this re-finetune will reproduce the schema drift.
2. **Verify `MAX_SEQ_LENGTH = 1536`** (line ~19) and
   `ENABLE_PACKING = False` (line ~28). Reverting either undoes the fix.
3. **Re-generate the dataset** with the 2026-05-09 patches applied:
   `python generate_large_schema_frozen_dataset_v2.py --write-count 5000
   --query-count 5000 --followup-count 6000`. This re-runs the long-list,
   trailing-comma, person-in-text, Tanglish-verb, etc. patches.
4. **Confirm the right adapter folder is used at conversion time.**
   The Kaggle / Colab output ends up at
   `unsloth_qwen3_parser_run-<timestamp>/lora_adapter/`.
   Point `colab_convert_to_gguf.ipynb`'s `ADAPTER_DIR` at the **newest**
   folder, not an older one — easy to mix up across runs.
5. **Confirm the training script reads the right dataset path.**
   Must point at `synthetic_finetune_dataset_v4_v2_schema/` and load
   from `parse_write/`, `parse_query/`, `parse_followup_query/` —
   **never `reference_only/`** (that's the deterministic note-write
   reference, not parser data).

**After the new GGUF is on the phone**, verify the fix took:

- Open the app → `weight: testperson 50kg` → Send.
- ☰ Activity log → check the row → Copy selected → look at the LLM RAW JSON.
- If it shows `"records":[{...}]` directly: **trainer fix worked, ShapeAdapter is dormant**.
- If it still shows `"data":{...}`: the `train_on_responses_only` call
  may not have been applied (check Colab cell output for the line
  `"train_on_responses_only"` — Unsloth logs this when invoked). If
  it logged but schema still drifts, the adapter wasn't loaded
  correctly during conversion (check `ADAPTER_DIR` in the GGUF
  notebook).

**Keep `parser/ShapeAdapter.kt` in place even after the re-finetune.**
It costs nothing when the model emits the right shape (early exit on
`payload.has("records")`) and protects the runtime against future
schema drift if a later fine-tune diverges.

**Other ShapeAdapter risks to be aware of while it's the active path:**

- Ledger direction-to-action mapping is a best-effort guess
  (`gave→add_credit`, `received→add_debt`). Stress-test ledger writes
  before trusting them; consider using the Ledger screen's manual Add
  form during dogfooding instead.
- Buy `quantity_text` is whatever the model puts in the value side of
  `details: {item: ...}`. May not always be a quantity.
- Hardcoded defaults: weight always gets `unit:"kg"`, expense always
  gets `group:null`. Fine for v1; revisit if the dataset adds
  unit-aware records.

Tracked as **issue #17** in the build-issues table below.

---

---

## Why Android, why now (2026-05-08 pivot)

Flask was useful as an engine harness, but the user pointed out that
without an actual UI on the device they couldn't tell when the v2 fine-tune
was misbehaving. The product has always been an Android-first design;
project_development.md's "Project Snapshot" already calls out the Android
target stack as `llama.cpp + Qwen (4-bit GGUF) + ONNX MiniLM + SQLite +
Java/Kotlin + JNI`. We're now executing on that.

---

## Locked architecture decisions

Captured across four rounds of clarifying questions on 2026-05-08. None of
these should be revisited without an explicit user decision.

### Runtime

- **Native Kotlin port.** No Python on device. The Python orchestrator,
  parser-validator, SQL safety gate, and core SQL runners are all
  re-implemented in Kotlin. Reasoning: smallest install, fastest cold
  start, cleanest Play Store path, no Chaquopy/Termux fragility.
- **LLM runtime: llama.cpp via JNI**, GGUF format. Pinned to commit
  `b3938`. Originally targeted Vulkan GPU offload by default; **shipping
  CPU-only in v1** because llama.cpp's Vulkan backend requires a
  two-stage cross-compile (host `vulkan-shaders-gen` then Android arm64
  lib) which AGP's single-pass externalNativeBuild can't express. GPU
  ships in Phase 3d. The user-facing GPU toggle in Settings stays as a
  no-op until then.
- **Adapter packaging: merged GGUF Q4_K_M.** LoRA merged into base
  `Qwen/Qwen3-1.7B`, converted via llama.cpp's `convert_hf_to_gguf.py`,
  quantized to Q4_K_M. Single ~1.1 GB file shipped.
- **Conversion environment: Colab.** Notebook at `colab_convert_to_gguf.ipynb`.
- **Embeddings: ONNX MiniLM via `onnxruntime-android` 1.17.1** — shipped
  in 3c with English-only `all-MiniLM-L6-v2` and a hand-written BERT
  WordPiece tokenizer in Kotlin (~150 lines). Multilingual swap to
  `paraphrase-multilingual-MiniLM-L12-v2` is documented as future work
  (would need an XLM-RoBERTa SentencePiece Unigram tokenizer or pulling
  in `ai.djl.huggingface:tokenizers`).

### App shell

- **Jetpack Compose**, Material 3, minSdk 26, target 34, **NDK
  30.0.14904198, CMake 4.1.2** (whatever Studio's SDK Manager defaulted
  to on this machine; build.gradle.kts pins to these exact versions).
- **arm64-v8a only.** Pixel 7 is arm64; smaller native libs.
- **No emulator for LLM testing** — the user tests on physical Pixel 7.
  Phone is GrapheneOS, which lets MTP file copy reach scoped storage,
  so USB debugging is not required for either APK install or model file
  push (per round-5 follow-up).
- **No permissions.** Fully on-device per project's core philosophy.
- **GGUF lives in the app's external scoped storage**
  (`getExternalFilesDir("models")`) — `adb push` once, no permissions
  needed, survives app updates.
- **Fresh empty DB on first install.** No migration from the Flask
  `second_brain.db`.
- **All 10 v1 screens at launch:** Home, Activity log, Notes, Dashboard,
  Expenses, Ledger, Weights, Todos, People, Settings.

### UX (the bits the user cares hardest about)

- **Tag chips above the input box.** 7 chips: `ask`, `expense`, `ledger`,
  `weight`, `todo`, `note`, `buy`.
- **Combo rule:** `ask` + at most one domain tag, OR exactly one write
  tag, OR none. Tapping a write chip while another write is active
  replaces it (mutual exclusion).
- **Auto-convert typed `<tag>:` to chip.** When the user types a recognized
  prefix and that chip is *not* already active, the typed text is stripped
  and the chip becomes active.
- **Chip wins on duplicate.** When the user types `<tag>:` while that
  chip is *already* active, the typed text is stripped and a toast says
  `Tag already active: <tag>:`. (User confirmed this in round 4 — note
  the original message implied the inverse; chip-wins is the locked
  decision.)
- **No hard-require on `ask:`.** Untagged input falls back to "save as
  plain note" rather than blocking submit.
- **Numbered-clarify resolution.** When the parser returns
  `disposition=clarify` (query) or `disposition=confirm` (write, e.g.
  ambiguous ledger direction), the orchestrator persists a
  `pending_actions` row and Home shows a banner. The user replies `1`,
  `2`, … or `cancel/none/skip` to resolve.

### Logging — the user's first-priority requirement

- **Comprehensive per-request capture.** New SQLite table `request_log`
  records: user input, active chips, tier path, full LLM prompt, raw
  LLM JSON, every SQL statement with args + row counts + sample rows,
  final response text, per-stage timings, and any error text.
- **Clipboard format: plain-text blocks separated by `---`.** Labeled
  lines: `USER INPUT / CHIPS / TIER / LLM_PROMPT / LLM_JSON / SQL_TRACE
  / FINAL / TIMINGS / ERROR`.
- **Activity log + request_log are linked by `activity_id`** so a
  selected activity row pulls its full diagnostic block on Copy.
- **Clear logs button** (Settings + Activity log screen) wipes BOTH
  `activity_log` and `request_log` so each round of troubleshooting
  starts from a fresh state after code changes.
- **Per-section Copy buttons** on every domain page (Notes / Expenses /
  Ledger / Weights / Todos / People / Dashboard) dump the currently
  visible rows in plain-text-table format — easy to paste back into chat
  for troubleshooting. Uses shared `ui/common/SectionHeader.kt`.

---

## Phase breakdown (with current status)

### Phase 1 — GGUF conversion notebook  ✅ shipped 2026-05-08

`colab_convert_to_gguf.ipynb` (22 cells). Loads non-quantized
`Qwen/Qwen3-1.7B`, attaches the `unsloth_qwen3_parser_run-20260507T152809Z`
LoRA adapter, calls `merge_and_unload()`, saves a clean HF snapshot,
clones llama.cpp, converts to F16 GGUF, builds `llama-quantize`,
quantizes to Q4_K_M, and runs a CPU sanity test against
`ask: latest buy list` to confirm JSON output. Auto-downloads the file.

### Phase 2 — Skeleton Android app  ✅ shipped 2026-05-08

15 files in `android/`. Bare-minimum app that loads the GGUF and runs
one prompt, with a GPU/CPU toggle. Validates that:
- The GGUF actually loads on Pixel 7 with Vulkan offload.
- The Kotlin chat-template prompt builder is byte-identical to
  `second_brain_finetuned_parser.py` (system prompt + `Today:` line +
  Qwen3 chat template, `enable_thinking=False`).
- The fine-tuned parser's JSON output matches the Python runtime.

### Phase 3a — Foundation + Home + Activity + Settings  ✅ shipped 2026-05-08

18 new files. End-to-end LLM round trip with full diagnostic logging.
- SQLite schema for all v1 tables + `ledger_balance` view + new
  `request_log` table.
- `parser/ParserSchema.kt` mirrors `validate_parser_payload` from the
  Python runtime; sealed `ParserPayload.Write/Query` types.
- `parser/ParserService.kt` wraps `LlamaCpp.generate` with prompt build +
  validate + per-stage timings; strips trailing chat-template tokens.
- `orchestrator/Tags.kt` — pure-function chip rules with notices.
- `orchestrator/RequestLog.kt` — `RequestLogBuilder` + `runSql` extension
  that auto-captures every SQL statement + sample rows.
- `orchestrator/WriteRunners.kt` — all 5 write lanes including ledger
  `settle` (closes balance with reverse-direction entry).
- `orchestrator/QueryRunners.kt` — all 6 query domains, lenient on model
  hallucinations.
- `orchestrator/Orchestrator.kt` — single entry point. Note-only bypass
  when chips are empty or `{NOTE}`.
- Drawer + sticky top bar + Home (chips, input, Send, Copy logs,
  recent-10) + Activity log (multi-select copy / clear) + Settings
  (model load + GPU toggle + clear logs).

### Phase 3b — Structured screens + clarify resolution  ✅ shipped 2026-05-08

12 new files. All 10 screens now navigable with real data.
- `data/Daos.kt` — read/write DAOs for every domain table.
- `orchestrator/PendingActions.kt` — clarify create + numbered/cancel
  resolution. Runs **before** the LLM in `Orchestrator.handle`.
- `orchestrator/WriteRunners.kt` (edit) — ledger `disposition=confirm`
  now persists a 3-option pending action.
- `orchestrator/QueryRunners.kt` (edit) — `disposition=clarify` persists
  pending with model's options + a save-raw fallback.
- `ui/common/SectionHeader.kt` — shared header with Copy + Clear and
  `renderTable()` helper.
- 7 screens: Notes (list + single editor), Expenses, Ledger (with
  balances summary), Weights (with latest-per-person), Todos (with
  toggle), People (with cascading rename), Dashboard.
- Home pending-action banner.

### Phase 3c — ONNX MiniLM + hybrid note search  ✅ shipped 2026-05-08

Pivoted from multilingual `paraphrase-multilingual-MiniLM-L12-v2` to
English-only `all-MiniLM-L6-v2`. Reasoning: XLM-RoBERTa SentencePiece
Unigram in pure Kotlin is 300-500 lines of fiddly Viterbi code, and
pulling in `ai.djl.huggingface:tokenizers` for the JNI binding adds
~12 MB of native libs and another debug surface. BERT WordPiece for
all-MiniLM-L6-v2 is ~150 lines of pure Kotlin with zero extra native
deps. Multilingual swap is documented as a future task.

Files added:
- `colab_export_minilm_onnx.ipynb` — exports + (optionally) int8-quantizes
  the model, saves vocab.txt + tiny tokenizer config JSON, sanity-tests
  the produced files, auto-downloads.
- `embedding/WordPieceTokenizer.kt` — pure-Kotlin BERT tokenizer with
  NFD accent stripping, lowercase, whitespace + punctuation pre-tokenize,
  greedy longest-match WordPiece, [CLS] / [SEP] wrap, [PAD] padding.
- `embedding/MiniLmEncoder.kt` — onnxruntime wrapper with single-thread
  dispatcher (ONNX sessions aren't safe for concurrent use), mean
  pooling weighted by attention mask, L2 normalize. Returns
  `FloatArray(384)` or null when not loaded.
- `embedding/EmbeddingsDao.kt` — store/load FloatArray as little-endian
  Float32 BLOB; `unembeddedNoteIds()` for backfill.

Wired in:
- `Orchestrator.saveNote` fires off encoding on a SupervisorJob /
  Default dispatcher → embedding lands a few seconds after the note
  save. Per project contract: "Indexing can be asynchronous."
- `QueryRunner.runNote` is now a hybrid scorer: 0.55 × lexical
  (substring + token-overlap) + 0.45 × cosine. Abstains when top score
  < 0.20 (returns "No notes match" rather than a confident lie).
- `SettingsScreen` shows model file presence, load button, embedding
  count, pending (unembedded) note count, and a Re-embed All button
  for backfill.

Open items deliberately left for later:
- ANN index (HNSW or sqlite-vss) — current scoring is O(N) cosine in
  RAM, fine up to a few thousand notes.
- Multilingual model swap — see README "Multilingual swap (future)".
- Embedder warmup on app start (currently lazy on first encode call).

---

## File layout

```
android/
├── settings.gradle.kts, build.gradle.kts, gradle.properties
├── gradle/wrapper/
├── README.md                              # build + adb push instructions
├── .gitignore
└── app/
    ├── build.gradle.kts                    # AGP 8.5.2, Kotlin 2.0.20, Compose 2024.09.02,
    │                                       # GGML_VULKAN=ON, arm64-only, NDK 26.3
    ├── proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml             # no permissions; .SecondBrainApp wired
        ├── cpp/
        │   ├── CMakeLists.txt              # FetchContent llama.cpp @ b3938
        │   └── llama_jni.cpp                # init / load / generate / free; greedy sampling
        ├── java/com/secondbrain/app/
        │   ├── SecondBrainApp.kt           # initializes DatabaseHolder
        │   ├── MainActivity.kt              # AppNav host
        │   ├── LlamaCpp.kt                 # Kotlin JNI wrapper, single-thread dispatcher
        │   ├── ChatTemplate.kt             # mirrors second_brain_finetuned_parser.py
        │   ├── data/
        │   │   ├── Database.kt             # SQLiteOpenHelper + all DDL + DatabaseHolder
        │   │   └── Daos.kt                 # NotesDao, ExpensesDao, LedgerDao, WeightsDao,
        │   │                                # TodosDao, PeopleDao, BuyDao + helpers
        │   ├── parser/
        │   │   ├── ParserSchema.kt         # data classes + validator (v2 schema)
        │   │   └── ParserService.kt        # LLM call + JSON parse + timings
        │   ├── embedding/                   # Phase 3c
        │   │   ├── WordPieceTokenizer.kt   # pure-Kotlin BERT tokenizer (~150 lines)
        │   │   ├── MiniLmEncoder.kt        # onnxruntime-android wrapper, mean-pool + L2-norm
        │   │   └── EmbeddingsDao.kt        # FloatArray ↔ Float32 BLOB; backfill helper
        │   ├── diag/                        # Phase 3e — comprehensive diagnostic feed
        │   │   └── EventLog.kt             # singleton: info/warn/error/throwable, 2000-row cap, dated .jsonl auto-archive, IST timestamps
        │   ├── AppStatusBus.kt              # SharedFlow bus for transient status messages (drives toasts)
        │   ├── AppStartup.kt                # auto-load LLM + embedder on app launch, emits to bus
        │   ├── orchestrator/
        │   │   ├── Tags.kt                 # chip rules (locked UX)
        │   │   ├── RequestLog.kt           # RequestLogBuilder + DAOs + clipboard format
        │   │   ├── PendingActions.kt       # clarify create + numbered resolve
        │   │   ├── WriteRunners.kt         # all 5 write lanes
        │   │   ├── QueryRunners.kt         # all 6 query domains
        │   │   └── Orchestrator.kt         # single entry point
        │   └── ui/
        │       ├── Theme.kt
        │       ├── nav/AppNav.kt           # drawer + sticky topbar + 10 routes
        │       ├── common/
        │       │   ├── SectionHeader.kt    # shared Copy/Clear header + renderTable()
        │       │   └── AppToastHost.kt     # 3e — top-right Compose toast overlay (slide+fade, 2.5 s, max 4 stacked)
        │       ├── home/                    # ChipRow + HomeScreen + HomeViewModel (3e: bottom-bar input + queue + 3-dot pulse)
        │       ├── activity/               # ActivityLogScreen + VM
        │       ├── notes/                   # list + single editor
        │       ├── expenses/, ledger/, weights/, todos/, people/, dashboard/
        │       ├── settings/               # model load, GPU toggle, clear logs
        │       └── stub/                    # leftover from 3a; unused after 3b
        └── res/values/
            ├── strings.xml
            └── themes.xml
```

---

## 🛠 BUILD GUIDE — point here when rebuilding

Single source of truth for going from "fresh repo + Pixel 7" to a
working installed APK with models loaded. Follow top-to-bottom on
first run; after that, only sub-section 4 (Build the APK) is needed
unless something earlier changes.

---

### 1. Prerequisites (one-time per machine)

| Component | Required | How to verify |
|---|---|---|
| Windows 10/11 with at least **6 GB free on C:** during build | yes | `Get-PSDrive C` |
| Python 3.10+ on PATH | yes (for ONNX export) | `python --version` |
| Android Studio installed (Studio binary itself isn't used; the SDK + bundled JBR are) | yes | `C:\Program Files\Android\Android Studio\jbr\bin\java.exe` exists |
| Android SDK with **NDK 30.0.14904198** + **CMake 4.1.2** (or whatever Studio's SDK Manager defaulted to — bump `app/build.gradle.kts` to match if different) | yes | `ls $env:LOCALAPPDATA\Android\Sdk\ndk` and `...\cmake` |
| Phone: Pixel 7 with GrapheneOS, MTP file copy enabled | yes for install | n/a |
| USB debugging | **not required** under GrapheneOS — MTP can write to scoped storage |

To install NDK + CMake via SDK Manager: Studio → More Actions →
SDK Manager → SDK Tools tab → tick **Show Package Details** →
expand **NDK (Side by side)** and **CMake**, tick the versions, Apply.

### 2. Generate the model files (run once per re-finetune of the parser)

| Output file | Source | Where to run |
|---|---|---|
| `qwen3-1.7b-parser-q4_k_m.gguf` (~1.1 GB) | `colab_convert_to_gguf.ipynb` — merges latest LoRA adapter into base, converts + quantizes | Colab T4 |
| `minilm.onnx` (~6 MB int8) + `minilm_vocab.txt` (~232 KB) + `minilm_tokenizer_config.json` (<1 KB) | `colab_export_minilm_onnx.ipynb` (Colab) OR `export_minilm_onnx.py` (local laptop) | either; local is faster after first run |

ONNX export is **independent** of parser fine-tuning — only redo it if
you swap the embedding model. Re-finetune of the parser only requires
re-running the GGUF notebook.

### 3. Bootstrap the Android build env (one-time per machine)

These files must exist before the first `gradlew` run. They're already
in this repo; only repeat if you cloned fresh:

```
android/gradlew                      # copied from music_app/android/
android/gradlew.bat                  # copied from music_app/android/
android/gradle/wrapper/gradle-wrapper.jar  # copied from music_app/android/gradle/wrapper/
android/local.properties             # contains: sdk.dir=C\:\\Users\\myuva\\AppData\\Local\\Android\\Sdk
```

The Gradle wrapper jar is intentionally a binary copy from the music_app
project; we don't generate it from scratch because that requires Studio.

### 4. Build the APK

The actual day-to-day command. Run from PowerShell, **not Bash**:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
cd C:\Users\myuva\Documents\note_taking_app_development\android
.\gradlew.bat --no-daemon assembleDebug
```

- **First clean build:** ~5-10 min (Gradle cache populate + llama.cpp
  clone via FetchContent + ~270 C++ files compiled).
- **Incremental Kotlin-only changes:** ~30-60 s.
- **Incremental C++ changes:** ~1-2 min.
- **Output:** `android\app\build\outputs\apk\debug\app-debug.apk`
  (~37 MB).

If something goes weirdly wrong:

```powershell
# Clean wipe — last resort, costs the full 5-10 min on next build
.\gradlew.bat --no-daemon clean assembleDebug
```

If a previous build wedged (kill -9 / disk-full / power loss) and the
next build fails with `Access is denied` on Gradle internal files:

```powershell
# Kill any stale Gradle/CMake processes
Get-Process | Where-Object { $_.ProcessName -match 'java|gradle|cmake|clang|ninja' } |
  ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

# Wipe the Gradle daemon cache
Remove-Item C:\Users\myuva\.gradle\daemon -Recurse -Force -ErrorAction SilentlyContinue

# Try again
.\gradlew.bat --no-daemon assembleDebug
```

### 5. Install on the phone (no USB debugging needed under GrapheneOS)

1. Plug in Pixel 7 via USB, set to **File transfer** mode.
2. Copy `app-debug.apk` to anywhere on the phone (e.g. `Downloads/`).
3. On the phone: open Files → tap the APK → allow "install unknown
   apps" for that file manager (one-time prompt) → install.
4. **Open the app once** so the scoped-storage folder gets created at
   `/sdcard/Android/data/com.secondbrain.app/files/`.
5. Now copy the 4 model files into that folder's `models/`
   subdirectory (create the subfolder if missing):
   - `qwen3-1.7b-parser-q4_k_m.gguf`
   - `minilm.onnx`
   - `minilm_vocab.txt`
   - `minilm_tokenizer_config.json`

   Final paths must be:
   ```
   /sdcard/Android/data/com.secondbrain.app/files/models/qwen3-1.7b-parser-q4_k_m.gguf
   /sdcard/Android/data/com.secondbrain.app/files/models/minilm.onnx
   /sdcard/Android/data/com.secondbrain.app/files/models/minilm_vocab.txt
   /sdcard/Android/data/com.secondbrain.app/files/models/minilm_tokenizer_config.json
   ```

6. App → ☰ **Settings** → **Load model** (LLM) → **Load embedder**
   (ONNX). Both report load times.

### 6. Verify the build works

1. App → ☰ **Home** → tap `ask:` chip → tap `buy:` chip → type
   `latest buy list` → Send.
2. Wait ~10-20 s for parser output (CPU inference, see disclosure
   below).
3. ☰ **Activity log** → check the row → **Copy selected**.
4. Paste that block into chat. Contains LLM prompt + raw JSON + SQL +
   per-stage timings — exactly what's needed to debug anything that
   went sideways.

### 7. Known issues & permanent fixes

18 builds were needed to get from "code compiles" to "Qwen3 inference
working at native speed on a Pixel 7". Every fix is committed; future
re-builds should be one-shot. Listed here in the order they appear
during the pipeline.

| # | Phase | Symptom | Permanent fix |
|---|---|---|---|
| A | ONNX export (Colab) | `numpy.dtype size changed, may indicate binary incompatibility` after `pip install numpy==1.26.4` then `from optimum.onnxruntime import ...` | Don't pin numpy. Use `pip install --upgrade transformers "optimum[exporters,onnxruntime]" onnx onnxruntime sentence-transformers` and restart the kernel. Updated install cell ships in `colab_export_minilm_onnx.ipynb`; `export_minilm_onnx.py` uses the same loose pins. |
| B | ONNX export (any) | `Required inputs (['token_type_ids']) are missing from input feed` during sanity test | BERT-family models have 3 inputs; pass `token_type_ids` as zeros. Fixed in `export_minilm_onnx.py` (introspects `sess.get_inputs()`) and in `MiniLmEncoder.kt` (checks `s.inputNames.contains("token_type_ids")`). |
| 1 | Build | Disk full mid-build (< 3 GB free on C:) | Cleanup checklist: `pip cache purge` (~16 GB), `~\AppData\Local\Temp\*`, `~\AppData\Local\CrashDumps\*`, old project venvs, `.lmstudio` if no longer using LM Studio. Aim for ≥ 6 GB free. |
| 2 | Build | `Could not write cache value to ...registry.bin (Access is denied)` after a previous wedge | Kill all java/gradle processes; `Remove-Item ~\.gradle\daemon -Recurse -Force`; rerun. |
| 3 | Build (config) | `[CXX1429] error when building with cmake` because NDK/CMake version requested by build.gradle.kts isn't installed | Pin `ndkVersion` and `externalNativeBuild.cmake.version` in `app/build.gradle.kts` to match what's actually installed under `$env:LOCALAPPDATA\Android\Sdk\ndk\` and `...\cmake\`. Currently 30.0.14904198 / 4.1.2. |
| 4 | Build (config) | `Could NOT find Vulkan (missing: glslc) (found version "x.y.z")` | `app/src/main/cpp/CMakeLists.txt` sets `Vulkan_GLSLC_EXECUTABLE` to `<NDK>/shader-tools/<host>/glslc.exe`. Fix is currently inert because GGML_VULKAN=OFF, but stays in place for Phase 3d. |
| 5 | Build (config) | glslc fix didn't take effect | Use **`CMAKE_HOST_WIN32`** (not `WIN32`) to pick the host shader-tools dir. `WIN32` describes the *target* during cross-compile (Android, false). |
| 6 | Build (Kotlin compile) | `Argument type mismatch: actual type is kotlin.Result<kotlin.Int>, but kotlin.Result<kotlin.Unit> was expected` in `MiniLmEncoder.kt::load` | The trailing `Log.i(...)` call returns `Int`, so `runCatching {}` infers `Result<Int>`. Add an explicit `Unit` as the last expression of the runCatching block. |
| 7 | Build (Kotlin compile) | `'return' is prohibited here` in `Orchestrator.kt` inside `withContext { ... }` | Suspend-inline lambdas reject non-local returns. Use `return@withContext value` for early exit; for the normal path make the lambda's last expression the result with no `return` keyword. |
| 8 | Build (CMake/Ninja) | `'vulkan-shaders-gen' is not recognized as an internal or external command` during `[3/21] Generate vulkan shaders` | llama.cpp's Vulkan backend builds a host tool at build time; AGP cross-compiles it for Android arm64 instead of host. Disabled Vulkan: `-DGGML_VULKAN=OFF` in `app/build.gradle.kts`. CPU-only ships in v1; GPU support is **Phase 3d** (requires two-stage build). |
| 9 | Build (linker) | `error: use of undeclared identifier 'ggml_backend_load_all' / 'llama_model_load_from_file' / 'llama_init_from_model' / 'llama_model_get_vocab'`; `no matching function for call to 'llama_batch_get_one'` | First time around: rewrote JNI to use b3938 API. Then we hit (10) below and bumped pin, so JNI got rewritten BACK to use the newer API. Current state: pin is `b6500`, JNI uses `llama_model_load_from_file`, `llama_init_from_model`, `llama_model_get_vocab`, `llama_vocab_is_eog`, vocab-arg tokenize/detokenize, 2-arg `llama_batch_get_one(tokens, n_tokens)`. If you ever bump the pin again, expect to revisit `llama_jni.cpp`. |
| 10 | Runtime (model load) | Settings → Load model: `llama_load_model_from_file failed for: ...` after just 370 ms. File is 1223 MB and intact. | llama.cpp `b3938` (Sept 2024) predates Qwen3 architecture support, which landed in llama.cpp around April 2025. **Bumped pin to `b6500`** (mid-2025, has Qwen3 + bug fixes). |
| 11 | Runtime (model file copy) | After `adb`-less install on GrapheneOS, the `Android/data/com.secondbrain.app/files/models/` folder isn't visible via MTP. Can't drop GGUF/ONNX in. | Built **in-app importer** in Settings: `OpenMultipleDocuments` SAF picker copies user-chosen files into `getExternalFilesDir("models")` with their original filenames. Bypasses scoped-storage MTP visibility entirely. |
| 12 | Runtime (state mgmt) | Auto-load completes successfully but Home keeps saying "Model not loaded". Settings → tap Load model → hangs forever. | Two ViewModels (Home, Settings) had stale `modelReady` / `loaded` fields that nobody ever wrote. Added `LlamaCpp.isLoaded()` / `MiniLmEncoder.isLoaded()` live accessors; Home's onSend gate reads them directly. Settings calls `syncLoadedFromRuntime()` on entry + on every `AppStatusBus` event. |
| 13 | Runtime (cancel) | Cancel button doesn't interrupt a slow inference. Native loop's between-tokens flag check never fires because we're stuck inside one decode. | llama.cpp ships an `abort_callback` polled inside its inner work loops. Wired our `g_abort_flag` to it via a real (non-lambda) function pointer. Cancel now interrupts mid-decode within ~100 ms. Plus a hard-fallback: if soft abort doesn't take within 5 s, `LlamaCpp.forceUnload()` frees the context — next Send needs a model reload. |
| 14 | Runtime (n_batch crash) | Reducing `n_batch` below the prompt size crashes the app on Send. | `n_batch` is the MAX batch size. We submit the full prompt as one batch (~80-300 tokens). Keep `n_batch >= 512`. Don't second-guess this without slicing prompts manually. |
| 15 | **Runtime (the real bug — 20-50× slowdown)** | First inference stuck at `prefill=0ms decoded=0` for 100+ s on an 82-token prompt. Same problem after every parameter tweak. | **AGP debug variant compiles llama.cpp/ggml at `-O0` with asserts enabled.** First-principles diagnosis: a Pixel 7 prefilling 82 tokens at expected ~3-5 s vs observed >100 s = exactly the magnitude of debug-mode matmul on arm64. Fix: force `CMAKE_BUILD_TYPE=Release` for the native subtree (in BOTH `CMakeLists.txt` AND `app/build.gradle.kts` cppFlags as belt-and-suspenders), add `-march=armv8.2-a+dotprod+fp16` to enable the fast Q4_K_M kernels, and log `llama_print_system_info()` at first model load to verify dotprod actually compiled in. **This was the real bug. Everything before it was guesswork.** Build #17 results: prefill 3.27 s, decode 4.64 s for 51 tokens (~11 tok/s), total 8 s — exactly what the hardware should produce. |
| 16 | Runtime (output) | After speed fix, JSON parser fails with `Value <think> of type java.lang.String cannot be converted to JSONObject`. Native stats show clean 8-11 s inference. | Qwen3 wraps every reply in `<think>...</think>` by default. Python's `apply_chat_template(enable_thinking=False)` injects an empty `<think></think>` after the assistant marker so the model skips thinking. Our hand-rolled `ChatTemplate.kt` didn't do that. Two fixes: (a) ChatTemplate now appends `<think>\n\n</think>\n\n` after `<\|im_start\|>assistant\n`, (b) ParserService strips any `<think>...</think>` block defensively via regex before JSON.parse. |
| 17 | Runtime (parser quality) | Even with thinking stripped, model emits `{"data": {...}}` instead of the v2-trained `{"records": [...]}`. Validator rejects → falls back to plain note. | **OPEN.** Either (a) the v2 fine-tune wasn't trained on the v2 schema correctly, (b) some other adapter got loaded, or (c) the model is generalizing away from the training distribution. Tracked in 3e UX iteration; needs investigation of training-time examples + a canonical eval before deciding to re-finetune vs adapt the orchestrator. |

### 7b. Phase 3e — UX overhaul from device dogfooding (build #19, 2026-05-08 21:06)

After build #18 produced working inference, real-device testing surfaced
a list of UX papercuts. Build #19 addressed most in one pass; the rest
are tracked as Phase 3f below.

| Item | Status in #19 | Note |
|---|---|---|
| Remove model/embedder status row from Home | ✅ done | Top of Home is now activity-only. Status moved to Settings. |
| Toast position top-right (not bottom-center) | ✅ done | New `ui/common/AppToastHost.kt` — Compose `Popup` anchored top-right with slide-in-from-right + fade animations. Modern Android (11+) blocks programmatic positioning of system Toasts so we don't use `android.widget.Toast` at all. |
| Toast scope — every user action | 🟡 partial | Build #19 wired toasts for: app start, model+embedder auto-load, "Clear all logs", chip-rule notices. Per-CRUD toasts on Notes/Expenses/Ledger/Weights/Todos/People are deferred to **3f** (~30 one-line additions). |
| Toast duration 2-3 s | ✅ done | Hardcoded 2.5 s in `AppToastHost`. |
| Input + chips pinned to bottom | ✅ done | Home is now `Scaffold(bottomBar = …)`. Chip row + input box + Send + Cancel + Copy logs all pinned above the system nav bar. |
| Tag chip order | ✅ done | Enum reordered to **`ask, todo, expense, note, weight, buy, ledger`**. |
| IST timestamps (not UTC) | ✅ done | DB v2: every `created_at` default switched to `datetime('now','localtime')`. Existing rows wipe on the v1→v2 upgrade per the rebuild policy in `Database.kt::onUpgrade`. New rows show in IST. |
| Per-row `created_at` always populated | ✅ already there | All tables had `created_at` with `datetime('now',...)` defaults; v2 just changes the timezone. |
| New `event_log` table — comprehensive diagnostic feed | ✅ done | New `diag/EventLog.kt` singleton with `info/warn/error/throwable` and `Category`/`Severity` enums. Async writes, mirrors to logcat. **Capped at 2000 rows** (`EventLog.cap`); when exceeded, oldest 500 rows are exported to a dated `event_log_YYYYMMDD.jsonl` under `getExternalFilesDir("logs")` and deleted from the DB. Wired into: app `onCreate`/`onDestroy`, model/embedder load events, every orchestrator submit start/done/fail, uncaught crashes. More wiring (per-CRUD, per-SQL) deferred to 3f. |
| Settings UI for cap config + Copy event log | 🟡 deferred to 3f | DAO + storage exist; just need the dropdown and clipboard button. |
| Crash capture | ✅ done (Java/Kotlin) | `SecondBrainApp.onCreate` installs `Thread.setDefaultUncaughtExceptionHandler` that calls `EventLog.throwable(...)` before deferring to the previous handler. Native (SIGSEGV) crashes still leave only kernel tombstones — would need a JNI signal handler, deferred. |
| "Clear all logs" UI refresh | ✅ done | Button now wipes activity_log + request_log + event_log + archive files; emits `"Cleared all logs..."` on `AppStatusBus`; HomeViewModel listens to the bus and refreshes its recent-feed snapshot when the message contains "Cleared". |
| Submission queue — input doesn't lock | ✅ done | New `PendingItem` data class + `PendingStatus` enum. `HomeViewModel.onSend` now: clears input/chips immediately, appends a `QUEUED` PendingItem, ensures the worker coroutine is running. Worker pulls one item at a time (LLM is single-threaded), marks PROCESSING, calls `Orchestrator.handle`, marks DONE/FAILED with the response. UI: pending items render at the top of the feed as secondary-colored bubbles with `…` 3-dot pulse animation while processing; 300 ms after DONE they fade and the actual activity-log row takes over below. Cancel button (visible only while processing) calls `LlamaCpp.abort()` with a 5 s soft timeout, then `forceUnload()` as hard fallback. |
| Schema mismatch (`data:` vs trained `records:`) | 🟡 open | Model emits `{"data":{...}}` instead of `{"records":[...]}`. Decide: re-finetune on Kaggle vs adapt the orchestrator. Pending dataset/output review. |

**Files added in 3e:** `diag/EventLog.kt`, `ui/common/AppToastHost.kt`,
`AppStatusBus.kt` (was already there from 3a-late).

**Files heavily modified in 3e:** `data/Database.kt` (v2 schema),
`SecondBrainApp.kt` (crash handler + EventLog bind), `MainActivity.kt`
(AppToastHost wrap, removed system Toast), `ui/home/HomeViewModel.kt`
(complete rewrite around PendingItem queue), `ui/home/HomeScreen.kt`
(new layout: bottom-bar input, pending bubbles, 3-dot pulse),
`orchestrator/Tags.kt` (enum reorder), `orchestrator/RequestLog.kt`
(`clear()` now also wipes event_log).

### 8. When you re-finetune the parser

Quick workflow checklist (so you don't have to re-derive each time):

1. New LoRA adapter folder lands at
   `unsloth_qwen3_parser_run-<NEW_TIMESTAMP>/lora_adapter/`.
2. Run `colab_convert_to_gguf.ipynb` in Colab pointing at the new
   adapter; download `qwen3-1.7b-parser-q4_k_m.gguf` (same filename).
3. Replace the file on the phone — overwrite the existing one in
   `/sdcard/Android/data/com.secondbrain.app/files/models/`.
4. **Force-stop the app** on the phone (Settings → Apps → Second Brain
   → Force stop), reopen it, Settings → Load model. New weights are
   in.
5. **Only if the dataset schema changed** (new intents / domains /
   filter keys / disposition values / chat template tweaks) you also
   need an APK rebuild after editing:
   - `parser/ParserSchema.kt` — `QUERY_INTENTS`, `QUERY_DOMAINS`,
     `QUERY_FILTER_KEYS`, `WRITE_LANES`, `LEDGER_ACTIONS`
   - `orchestrator/QueryRunners.kt` — runner branches per new
     domain/intent
   - `orchestrator/WriteRunners.kt` — write branches per new lane
   - `ChatTemplate.kt` — must match the Python runtime byte-for-byte
   Then redo Section 4.

If you don't change the dataset between fine-tunes, no APK rebuild is
needed — the GGUF swap is enough.

---

## Known cuts and follow-ups

- **Edit-in-place** exists only for Notes content and People rename.
  Other domains are delete + re-add (matches Flask). Easy to add per-row
  edit cards if dogfooding shows the need.
- **Buy items** don't have a dedicated screen — parser writes go through
  the orchestrator and reads happen via `ask: buy:` queries on Home.
  ~80 lines to add a Buy screen if wanted.
- **Streaming LLM generation** is not implemented; the JNI bridge blocks
  until the model finishes (max 256 tokens). Token-by-token streaming
  is a polish item — would need a callback channel through JNI.
- ~~**No undo toast** on writes~~ **Shipped in build #27** as a 5 s undo
  chip above Home's input bar. Reverses row inserts (expense/buy/todo/
  weight/ledger), note save (delete-row or restore-content for per-day
  appends), auto-added persons (only if no other table references them),
  and tied MiniLM embedding rows. PendingActions clarify-resolution
  inserts are NOT undoable — those are user follow-ups, not fresh
  submissions; per-row Delete on each domain page is still the path for
  that case.
- **English-only embeddings.** Phase 3c shipped `all-MiniLM-L6-v2` with
  pure-Kotlin BERT WordPiece. Tanglish/India-context notes will get
  weaker semantic recall (lexical scoring still works). To upgrade to
  multilingual `paraphrase-multilingual-MiniLM-L12-v2`, swap the export
  notebook + either implement an XLM-RoBERTa SentencePiece Unigram
  tokenizer in Kotlin OR pull `ai.djl.huggingface:tokenizers` (~12 MB
  APK). The ONNX graph signature is identical, so `MiniLmEncoder.kt`
  itself doesn't change.
- **O(N) cosine** for embedding search. Fine up to a few thousand
  notes. When that breaks, swap in HNSW or `sqlite-vss` —
  `EmbeddingsDao` interface stays.
- **Embedder warmup is lazy.** First note query after app start pays a
  one-time ~150 ms ONNX session-init cost. Cheap to add a startup
  warmup later.

---

## Cross-references

- `colab_convert_to_gguf.ipynb` — GGUF conversion notebook
- `android/README.md` — phone-side build + push + run instructions
- `project_development.md` — Flask app history, parser schema, dataset,
  fine-tune lineage, dogfooding logs (do not duplicate that here)
- `current_state.md` (in `~/.claude/.../memory/`) — quick orientation
  index that future Claude sessions read first
