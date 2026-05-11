# Second Brain App â€” Development Tracker

**Source of truth for ongoing development.** All future work starts from this file. Update it as we progress.

---

## Project Snapshot

Fully local, on-device second brain for Android (Pixel 7, 8GB RAM). Dump notes in free-form English, query conversationally. No cloud.

**Final stack (Android target):** llama.cpp + Qwen (4-bit GGUF) + ONNX MiniLM embeddings + SQLite + NanoHTTPD (Java/Kotlin + JNI).

**Current phase:** Orchestrator refactor is functionally green, the captures/notes split is complete across both surfaces, the read/write membrane has been hardened against natural-language note retrieval, audit-trail bloat in `notes` has been eliminated, and journal-style questions get a UX-friendly clarify menu. The 510-case out-of-the-box stress run lands at 97% ok, 1.4% real-danger, 0 audit pollution, 0 exceptions. Remaining priorities: (a) latency reduction on the real-Qwen path (cold-start LLM and embedding load are the dominant costs), and (b) deterministic date-range parsing for queries the planner currently handles only with a real LLM. The target runtime is **note-first**: a small deterministic structured lane (expense / ledger / weight / todo), arbitrary text defaulting to a normal saved note, legacy investment/health bias removed from the hot path, complex structured read queries handled by **LLM-assisted safe read-only SQL** instead of ever-growing phrase-specific rules.

**Core philosophy:** Dump and forget. Append-only. Confirmation toast as 2-second safety net, not double-checking.

**Current active workstream (2026-05-08 onwards):** Android port. The Flask app is retired as the active surface and kept only as the historical engine reference. New work happens in the `android/` subfolder and is tracked in **`android_port.md`** — that file owns architecture decisions, phase status, and file layout for the Android client. This document continues to own parser schema, dataset, fine-tune lineage, and Flask dogfooding history.

**For build steps + every issue we hit + permanent fixes, jump straight to `android_port.md` § "🛠 BUILD GUIDE — point here when rebuilding".** That section is the one-stop reference for prerequisites, model-file generation, the actual `gradlew assembleDebug` command, phone install, verification, and the table of 11 known issues with permanent fixes. Point any future Claude session at it. For phone-side install see `android/README.md`.

---

## ⚠️ STRONG NOTE — read before any re-finetune session

**The current fine-tuned model emits `{"data":{...}}` instead of the v2-trained `{"records":[{...}]}` schema.** Build #20 ships a runtime translation layer (`android/app/src/main/java/com/secondbrain/app/parser/ShapeAdapter.kt`) that coerces the legacy shape into the trained shape per lane, so the app works today. **That layer is transitional. The proper fix lives in this re-finetune workflow.**

**Before you kick off the next Kaggle/Colab fine-tune session, verify in this exact order:**

1. **Dataset shape** — random-sample 5-10 rows from `synthetic_finetune_dataset_v4_v2_schema/` and confirm every `output` field uses `"records":[{...}]` (NOT `"data":{...}`). If even one row shows `"data":{...}`, regenerate the dataset before training.
2. **Training prompt template matches inference template** — both must include:
   - The `Today: <YYYY-MM-DD>` line in the system prompt
   - An empty `<think></think>` priming after `<|im_start|>assistant\n` (Qwen3 `enable_thinking=False`)
   The Android side's `ChatTemplate.kt` is the canonical reference — keep training in sync with that file. A drift between training-time and inference-time templates is the most likely root cause of the current schema mismatch.
3. **Right adapter selected for conversion** — Kaggle/Colab fine-tune outputs to `unsloth_qwen3_parser_run-<NEW_TIMESTAMP>/lora_adapter/`. Point `colab_convert_to_gguf.ipynb`'s `ADAPTER_DIR` at the **newest** folder. Easy to mix up across runs.
4. **Right dataset path in `kaggle_finetune.ipynb`** — must point at `synthetic_finetune_dataset_v4_v2_schema/`, must load only `parse_write/`, `parse_query/`, `parse_followup_query/` — **never `reference_only/`** (that's deterministic note-write reference behavior, not parser data; loading it would teach the wrong schema).

**After the new GGUF lands on the phone:**

- Open the app → run `weight: testperson 50kg` → Send.
- ☰ Activity log → check the row → Copy selected → look at the `LLM RAW JSON` block.
- ✅ If it shows `"records":[{...}]` directly: re-finetune is correct, ShapeAdapter is dormant (early-exits when records is present).
- ❌ If it still shows `"data":{...}`: the ShapeAdapter is still translating; the re-finetune did NOT fix the root cause. Investigate further before declaring victory.

**Keep `parser/ShapeAdapter.kt` in place even after a clean re-finetune.** It costs nothing when the model emits the right shape (single early exit) and protects against future schema drift if a later fine-tune diverges. Specific fragility to be aware of while ShapeAdapter is the active path:

- **Ledger direction-to-action mapping is a guess** — `gave→add_credit`, `received→add_debt`. Stress-test ledger writes carefully or use the Ledger drawer's manual Add form during dogfooding.
- Buy `quantity_text` is whatever the model puts in `details: {item: ...}`'s value side; might not always be a quantity.
- Hardcoded defaults: weight always gets `unit:"kg"`, expense always gets `group:null`. Revisit if dataset adds unit-aware records.

This is also tracked as **issue #17** in `android_port.md` § "Issues hit during the first build" and as Phase 3e item "Schema mismatch" in the same file.

---

**Earlier active workstream (pre-2026-05-08):** End-to-end app completion using the currently fine-tuned parser model. Start from this tracker first, then use `finetuning_data_sanity.md` and `dataset_india_context_rulebook.md` only as supporting references for parser behavior and future retraining. The current fine-tuned `Qwen3-1.7B` run is already strong enough to proceed with app integration, especially on write parsing. The next logical step is to wire the current adapter into the app flow, finish product integration end to end, log real parser failures during development, and only then return to targeted re-fine-tuning / query-follow-up evaluation if actual app behavior shows gaps.

---

## Product Clarifications (locked 2026-05-03)

These decisions override older domain-specific assumptions elsewhere in this file.

1. **Note app first.** The product is a general note-taking app first, not an investment/health-specific assistant. Arbitrary text defaults to a normal saved note unless it clearly matches a small structured pattern.
2. **No user-facing note segregation.** User notes are not split into health / investment / other buckets in product behavior. Notes may still carry transitional metadata internally, but retrieval should treat all user notes as one searchable pool by default.
3. **Structured data is a special layer.** Expenses, ledger, weights, and todos are special capabilities on top of the note app, not the core identity of the app.
4. **Cross-data reasoning is allowed.** The LLM may use structured data when a query is too nuanced for rules alone (example: "expenses apart from petrol last month" or "groceries only last month" where the category boundary is semantic rather than rule-based).
5. **Desired note-query output.** Ideal response shape for note queries is: short synthesized answer first, then the original note snippets. If latency or reliability is at risk, returning the original snippets alone is acceptable.
6. **Faithfulness over polish.** Any LLM synthesis should stay close to the user's original wording. Light paraphrase is acceptable; aggressive rewriting is not required.
7. **Retrieval scope and robustness.** General-note search should run across all saved notes by default and should tolerate typos / approximate matches in both the query and the saved note text.
8. **Indexing can be asynchronous.** Notes do not need to become searchable in the same write transaction; indexing a few seconds later is acceptable if retrieval remains reliable.
9. **Latency budget.** Every user-visible action should complete within a 5-10 second hard max. Faster is preferred, especially for note retrieval.
10. **LLM usage policy.** Use the LLM where it adds real value. Retrieval-only answers are acceptable when they are materially faster, but the product still aims for AI-assisted answers where latency allows.
11. **Clarification policy.** If routing confidence is below 0.7, ask the user to clarify. Otherwise execute. Saving as a note remains the default for arbitrary text that is not clearly structured.
12. **Explicit `note:` directive.** `note:` is a hard user instruction. Save the content as a plain note with no routing reinterpretation. If the input spans multiple lines, keep that input together as the saved note content.
13. **Explicit `todo:` directive.** `todo:` is a hard user instruction. Save todo items even if the text looks query-shaped. If the content is clearly list-shaped (multiple lines, bullets, or obvious separators), split it into multiple todo rows.
14. **Interaction style.** Plain natural language is the primary UX. A few simple explicit prefixes such as `todo:` and `note:` are acceptable; no large command vocabulary should be required.
15. **Search goal.** For general note queries, return all relevant notes, not just a single best match.
16. **Note-query intent normalization.** Phrasings like `X notes`, `any info on X`, `any mention of X`, `show notes about X`, and `find X in my notes` should converge to the same note-search intent.
17. **Synthesis policy.** Synthesize only when retrieval returns at least one reasonably relevant hit. If not, return snippets only or `no match`.
18. **Rule scope must stay small.** Do not keep adding hundreds of phrasing-specific deterministic query rules. Deterministic handling should stay limited to obvious writes and a small set of simple read patterns.
19. **Complex read-query direction.** For harder structured reads (weights / expenses / ledger / mixed time filters / semantic exclusions), prefer LLM-generated **read-only SQL or an equivalent safe query plan** over brittle phrase-by-phrase routing. This must run only against approved views/tables, never arbitrary mutating SQL.
20. **Comma-number default.** Ambiguous comma-separated numeric input should default to multi-expense write unless there are strong query markers.
21. **Remove domain heuristics.** Old investment/health note-domain heuristics should be removed from the active routing hot path. The app is a generalized note-taking app with special structured capabilities, not a domain-segregated note system.
22. **Next debugging step.** Use the shipped per-stage timings to reduce cold-start latency on the normal note-query hot path. Current likely targets are embedding warm-up / background indexing behavior and removing real Qwen routing from requests that can be satisfied by deterministic routing + retrieval.
23. **Accepted data-model direction.** Adopt the "split the concept" model. `notes` should become **real user notes only** (editable and searchable). Raw typed inputs that produce structured rows should move to a separate immutable capture/event layer (for example `input_events` / `captures`). `activity_log` remains the UI history feed. Structured rows (`expenses`, `ledger`, `weights`, `todos`) should link to the raw capture layer, not to user notes.
24. **Embedding scope going forward.** Embeddings should be built from actual user notes only, not from structured-source captures by default. Structured retrieval continues to come from SQL on the domain tables unless a future feature explicitly adds semantic retrieval there.

## Input Contract And Query Flow (locked 2026-05-05)

These decisions refine/override older "plain untagged natural language is the main lane" assumptions elsewhere in this file. They describe the **target product contract**; the current Flask surface has **not** implemented this chip-based input model yet.

1. **Tag-first input lanes.** Broad routing should not depend on the LLM for normal day-to-day use. The UI should expose tappable chips above the input box so the user can explicitly choose the lane before typing.
2. **Primary write tags.** Current accepted write tags are `expense:`, `todo:`, `buy:`, `weight:`, `ledger:`, `note:`. Accepted note-like extensions are `journal:`, `idea:`, `watch:`, and `work:`. These act as lightweight input lanes, not as separate product silos.
3. **Primary query tag.** Use one explicit query lane such as `ask:` as the main retrieval / question tag. `search:` may exist as an alias if needed, but `retrieval:` is considered too internal/technical for the user-facing UX.
4. **Optional query-scope narrowing.** `ask:` may optionally be narrowed to a specific retrieval domain. Conceptually this is better represented in UI as `ask + auto|expense|buy|todo|weight|ledger|note`, but literal forms such as `ask: expense:` are also acceptable. `auto` remains the default broad query mode; scoped `ask` is an optional precision aid, not a requirement.
5. **Tag decides the lane.** After a tag is chosen, parsing happens **inside that lane only**. The LLM/rules should not re-decide whether `expense:` is actually a note, whether `ledger:` is actually a todo, etc., except for validation/clarify paths.
6. **Scoped `ask` behavior.** Plain `ask:` lets the model detect the retrieval domain. Scoped `ask` narrows that job. For example, `ask + expense` means the model should parse expense intent/date/filter details inside the expense domain instead of first deciding which tool to use. If a scoped `ask` and the actual question text conflict strongly, the app should clarify rather than silently switching domains.
7. **Untagged input is not the primary UX.** If untagged input is still allowed, it should default to a plain note or otherwise be de-emphasized. Reliability takes priority over fully open natural-language routing.
8. **Always save raw input first.** Every tagged submission should first land in the capture/history layer, then be parsed, validated, and written to the destination table(s).
9. **Parsing strategy inside a lane.** Use rules first for obvious cases, then the fine-tuned/current LLM for messy phrasings, typos, and multi-entry extraction. The LLM's job is narrow: parse within the chosen lane, not globally infer the user's mode from scratch.
10. **Ledger confirmation stays special.** `ledger:` remains the one write lane where confirmation is desirable by default, because direction is easy to misread (`I owe X` vs `X owes me`, settlements, returns, partial repayments). Expense/todo/most weight writes should remain execute-first with toast/undo.
11. **Structured query path.** Queries about expenses / weights / ledger / todos should resolve to structured intent, then Android/Kotlin/app code should build the deterministic SQLite query. The final arithmetic/trend/balance result must come from SQLite/app logic, not from the LLM.
12. **Note-retrieval path.** Queries about saved notes/journal/ideas/watch/work entries should go through lexical search + embeddings/RAG over the note corpus, then optionally through an LLM synthesis step that stays faithful to the retrieved snippets.
13. **RAG scope.** RAG is for note retrieval and optional history retrieval only. Structured totals, balances, comparisons, and date-filtered facts must not be answered by RAG alone.
14. **Follow-up structured queries.** Follow-ups like `of that how much was groceries` should be handled by storing the prior structured query context (domain, resolved date range, filters, intent), then inheriting/modifying that context for the new query before SQLite executes the final answer. If RAG is used here, it is only to help recover prior query context, never to replace SQLite.
15. **Final wording policy.** When a structured SQL answer and natural-language note context need to be blended, LLM phrasing is acceptable as a complementary final step, but the exact numbers/rows remain code-owned. Notes themselves remain plain text; title/summary/topic generation is optional and asynchronous, not the canonical note representation.
16. **Expense grouping direction.** The source of truth remains the verbatim expense description. If categories/groups are added later (for example `groceries`), they should be a derived/optional overlay for analytics and filtering, not a hard mandatory taxonomy or a user-facing category UI requirement.
17. **Transport boundary is not sacred.** MCP is an implementation detail, not a product requirement. If Android integration is simpler with direct in-process service calls, MCP can be replaced without changing the higher-level routing / SQL-safety / RAG architecture.
18. **Model baseline.** The current Qwen family/model remains the baseline for fine-tuning and runtime experiments unless benchmarks on the real target hardware prove otherwise.

## Current Flask Surface (as shipped 2026-05-03)

This section describes the **actual current user-facing behavior** of the live Flask app. If it conflicts with older aspirational Android/UI notes elsewhere in this file, **this section wins**.

### Navigation chrome

1. The top bar is now **sticky**, so the hamburger menu remains available while scrolling.
2. The hamburger drawer highlights the **current page**, including `Notes`, so the active section is visible without guessing.

### Pages available right now

1. **Home (`/`)** - last 10 activity items plus a **single-line** bottom input box. Each activity shows the user input, the app response, a small `[parsed: ...]` routing line, and a `[time: ...]` timing line.
2. **Activity log (`/activity`)** - paginated full history (50 per page) of all submitted inputs and responses.
3. **Notes (`/notes`)** - a real note editor surface. Shows only real user notes (`structured_type = 'note'`), supports multiline note creation, a **list-plus-single-editor** workflow (pick one note to edit at a time), and note deletion.
4. **People (`/people`)** - add, rename, and delete names.
5. **Dashboard (`/dashboard`)** - current month spend, pending todo count, ledger balances, latest weight per person.
6. **Expenses / Ledger / Weights / Todos (`/expenses`, `/ledger`, `/weights`, `/todos`)** - management pages with direct add forms, individual delete actions, and section-level `Clear all` actions. Todos also support toggle between `pending` and `done`.
7. **Settings (`/settings`)** - stub only; no real settings features yet.

### How the Home input behaves

1. The Home input is the primary interaction surface for both **writes** and **queries**.
2. The current web UI input is **single-line only**. Backend support exists for multiline `note:` / `todo:` payloads, but the live Flask surface does not expose a multiline compose box yet.
3. Every submission is written to `activity_log`.
4. Home-input submissions still often create an internal `notes` row even when they end up as expense / ledger / weight / todo / query actions. Page-based structured CRUD now uses the new `captures` layer instead of creating user-note rows.
5. The app may respond immediately, ask a numbered clarification question, or interpret the input as a plain note.
6. Numbered replies like `1`, `2`, etc. are meaningful only when the previous app response asked for a numbered resolution.

### Notes

**What works now**

1. Arbitrary plain text is saved as a normal note when it does not clearly match a structured write or query pattern.
2. `note: ...` is a hard override and always saves a plain note with no router reinterpretation.
3. Notes are stored as plain text, not as markdown documents.
4. Saved plain notes are auto-embedded for later semantic retrieval.
5. Common note-query phrasings are supported: `vivekananda notes`, `any mention of mcp in the notes`, `show me last 5 notes`, `saved notes`, `find vivekananda in my notes`.
6. Recent-note queries return raw saved note lines.
7. Semantic note queries search across the shared note pool by default.
8. `/notes` now supports direct add, edit, and delete for real user notes only, using a **note list + one active editor** instead of opening every note as its own form.
9. Semantic note retrieval reads from the `embeddings` table, and those embeddings are created from actual note-save paths. Structured rows such as expenses / ledger / weights / todos are not themselves embedded.

**Current limitations**

1. The current output for note queries is **not yet consistently the ideal "synthesized answer + original snippets"**. In most general-note cases it still returns raw matching snippets/lines.
2. Synthesis may appear in some searches when legacy domain-tagged hits are involved, so answer style is not fully uniform yet.
3. The note editor is still plain-text only; there is no markdown rendering, notebook hierarchy, or search/filter UI inside `/notes`.
4. The single-line Home input still means multiline note capture is primarily a Notes-page workflow, not a Home-page workflow.
5. Home-input structured writes now use the captures layer end-to-end (Tier 0, Tier 1, multi-entry, legacy bridge); only real plain notes still create rows in `notes`.

### Todos

**What works now**

1. Explicit todo writes: `todo: buy milk`, `task: renew license`.
2. Action-style todo writes: `todo update Amit about MCP`, `remind me to call Ravi tomorrow`.
3. The backend can split explicit `todo:` content into multiple todos when the body is clearly list-shaped (multiple lines, bullets, `;`, `.-`, `|` separators).
4. Todo queries: `show todo list`, `show me todo list`, `done todos`, `pending tasks`.
5. The Todos page supports direct multiline add, toggle between `pending` and `done`, individual delete, and `Clear all`.

**Current limitations**

1. The current Home input is single-line, so multiline `todo:` splitting is mostly a backend capability, not a real web-UI workflow yet.
2. There is no todo text edit UI yet.
3. There are no due dates, reminders, or notifications.

### Weights

**What works now**

1. Weight writes for recognized tracked people: `jeevi 65.3`, `jeevi weight 65.3`, `murugan weight 72 post lunch`.
2. Weight value must be `> 0` and `< 150`.
3. Optional trailing note/context is stored with the weight entry.
4. Latest-weight and short-history queries are supported for tracked names already present in People or weight history: `jeevi`, `jeevi weight`, `last 3 jeevi weight`, `show last 5 prani weight`, `recent murugan weight`.
5. The Weights page supports direct add, individual delete, and `Clear all`.
6. Renaming a person from the People page updates weight history rows to the new name.

**Current limitations**

1. There is still no weight edit-in-place UI; correction is currently delete + re-add.
2. There are no charts/trends screens yet.

### Ledger

**What works now**

1. Natural-language ledger writes: `gave Maddy 5k`, `got 5k from Mani`, `Maddy returned 6k`, `ravi gave me 5k`, `sent Ravi 500`.
2. Unknown names can still be logged in ledger entries.
3. Ledger queries: `Maddy balance`, `who all owe me money`, `who do i owe`.
4. Ambiguous settlement phrases can open a numbered resolution menu: `clear maddy ledger`, `settled maddy amount`, `gave back the amount`, `wrote off maddy`.
5. Numbered replies (`1`, `2`, etc.) can resolve that pending settlement.
6. Renaming a person from the People page updates ledger history rows to the new name.
7. The Ledger page supports direct add, individual delete, and `Clear all`.

**Current limitations**

1. There is no ledger edit-in-place UI yet; correction is currently delete + re-add.
2. There is no person-detail ledger screen yet.

### Expenses

**What works now**

1. Expense writes: `petrol 500`, `milk 60`, `food 300, water bottle 20, tea & snacks 30`.
2. Amount parsing supports forms like `500`, `5k`, `1.5L`, `5,000`.
3. Comma-separated numeric inputs default to multi-expense writes unless strong query markers are present.
4. Expense total queries: `monthly expense`, `this month expense`, `petrol expense`, `groceries expense for this month`.
5. Expense list queries: `list the expense one by one`, `show expense list`.
6. The Expenses page supports direct add, individual delete, and `Clear all`.

**Current limitations**

1. Description/category-style filtering is currently seeded only by a fixed keyword list (`petrol`, `groceries`, `food`, `tea`, `repair`, `medicine`, etc.). Arbitrary descriptions are not guaranteed to behave like first-class categories.
2. Deterministic date parsing is still narrow. Strong support exists for `this month`, `current month`, `monthly`, and hardcoded month-name matches currently represented in the code map.
3. Phrases like `last month`, `yesterday`, `last december`, custom ranges, or semantic filters like `apart from petrol` are **not reliably supported yet** by the current live app.
4. There is no expense edit-in-place UI yet; correction is currently delete + re-add.
5. The Expenses page has no real filter controls yet.

### People

**What works now**

1. People can be added, renamed, and deleted from the People page.
2. Power-user chat commands also work: `ADD_PERSON: ravi`, `MODIFY_PERSON: ravi raghav`, `REMOVE_PERSON: ravi`.
3. Names are stored lowercase.
4. Person rename cascades into ledger and weight rows.

**Current limitations**

1. Deleting a person removes them from the People list but does not delete old ledger/weight history rows.
2. There is no richer person-detail screen yet.

### Dashboard

**What works now**

1. Shows current-month spend total.
2. Shows pending todo count.
3. Shows ledger balances.
4. Shows the latest weight per person.

**Current limitations**

1. It is read-only.
2. No drill-down filters or deeper analytics yet.

### Clarification and memory

1. If the router is unsure, it can show a numbered clarify menu.
2. Valid follow-ups are `1`, `2`, `3`, etc., or `cancel` / `none` / `skip`.
3. Clarify resolutions are memoized in `user_routing_memory`, so repeated phrasings can route faster next time.

### Not implemented yet in the live Flask app

1. No Android surface yet; the active product is the Flask web app.
2. No markdown note editor.
3. No multiline compose box on Home.
4. No real Undo toast in the current Flask UI.
5. No markdown note hierarchy, tags, or search/filter controls inside the Notes page.
6. No edit-in-place UI for expense / ledger / weight / todo rows yet; correction is still mostly delete + re-add.
7. No real filters/search controls on the management pages.
8. Settings is still a placeholder.
9. No fully general LLM-assisted read-only SQL flow for complex structured questions yet.
10. No consistently polished "synthesized answer + original snippets" note-answer format yet.
11. The split-model refactor is fully shipped: page-based CRUD and the Home/orchestrator hot path both write structured rows via `captures`. `notes` now contains only real user notes (plus the small audit trail for settlement and person-command flows — query/clarify/planner audit was eliminated 2026-05-04).
12. No deterministic date-range parsing yet for queries like `ledger from december 2025`, `weight from last sunday` (currently mis-routed; rely on the LLM planner with real Qwen).
---

## App UI â€” what the user sees

The notebooks build the **engine**. The Android app is the **surface**. Every backend feature must answer: *which UI surface invokes it?* If the answer is "type a magic command," that's a power-user shortcut, not a primary path.

Treat this section as the **target Android-facing design sketch**. For the **actual current Flask behavior**, use the "Current Flask Surface (as shipped 2026-05-03)" section above.

### Layout (sketch)

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ â‰¡  Second Brain                         â”‚  â† top bar (hamburger top-left)
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                         â”‚
â”‚  > petrol 500                           â”‚
â”‚  âœ“ â‚¹500 petrol logged                   â”‚  â† scroll of recent input + responses
â”‚                                         â”‚     (chat-style; persists across sessions)
â”‚  > Maddy balance                        â”‚
â”‚  Maddy owes you â‚¹7,000                  â”‚
â”‚                                         â”‚
â”‚  > jeevi 60.1 empty stomach             â”‚
â”‚  âœ“ Jeevi weight: 60.1kg logged          â”‚
â”‚                                         â”‚
â”‚                                         â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ [ Type a note or questionâ€¦       ] [â†’] â”‚  â† single input bar at bottom
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
   â†‘ confirmation toast appears here briefly with Undo
```

### Revised input model (locked 2026-05-05)

The target Android surface should place a **small row of chips above the input box**. Tapping a chip prepends the lane tag and constrains parsing accordingly.

- **Write chips:** `expense:` `todo:` `buy:` `weight:` `ledger:` `note:` `journal:` `idea:` `watch:` `work:`
- **Query chip:** `ask:` (with optional `search:` alias if needed)

This is still lightweight compared with a full command palette or multi-screen mode switch, but it removes the need for the LLM to guess the broad input kind on every submission.

### Surfaces and what they do

| Surface | User does | App calls |
|---|---|---|
| **Bottom input bar + chips row** | Taps a chip such as `expense:` / `ledger:` / `note:` / `ask:` and then types the content inside that explicit lane | capture raw input â†’ parse within the chosen lane â†’ SQLite write or note retrieval / structured query |
| **Main scroll** | Reads back recent input + system responses, chat-style | reads from DB on app launch |
| **Confirmation toast** | Glances; taps **Undo** if wrong | DELETE the just-inserted row |
| **â‰¡ Hamburger drawer** | Opens management screens (NOT a place to type notes) | navigates to a screen |
| â†³ **People** screen | Sees list of names. Taps `+` to add, taps a row to rename/delete. **This is the primary path for person management.** | INSERT/UPDATE/DELETE on `persons` |
| â†³ **Dashboard** | Sees at-a-glance summary: balances, month spend, latest weights, pending todos | `list_summary` (parallel SQL) |
| â†³ **Notes** | Reviews the saved raw-note stream with detected type/domain | SELECT from `notes` |
| â†³ **Expenses / Ledger / Weights / Todos** lists | Filterable per-domain list view (date range, search) | SELECT with WHERE/LIKE |
| â†³ **Settings** | DB backup/restore, model file path | TBD |

### Design decisions implied by this layout

1. **One input bar, explicit lightweight lanes.** The user chooses a chip (`expense:` / `note:` / `ask:` etc.), then the parser works inside that lane. This is intentionally less magical and more reliable than broad freeform routing.
2. **Append-only is invisible.** The user sees the toast and Undo. The fact that ledger reductions are stored as new `received` rows is a backend detail.
3. **Person management has two surfaces** â€” UI screen (primary) and chat shortcut `ADD_PERSON: ravi` / `REMOVE_PERSON: â€¦` / `MODIFY_PERSON: old new` (power-user). Both hit the same `manage_persons` tool. Drop the chat shortcut later if it never gets used.
4. **No category UI.** Expenses are filtered by description-LIKE in queries; if a future "spend by category" screen is needed we'd revisit, but for v1 monthly totals + free-text search are enough.
5. **Toast text is the same string the parser builds.** `parse_note(...)` already returns a structured entry; the UI just formats it. Keeps logic out of the view layer.

### What is NOT in the UI (deliberately)

- No edit-in-place (append-only). Wrong entry â†’ undo within toast window, or delete from the domain list view.
- No date picker on input. Date = now, always.
- No category/tag picker. Free description.
- No heavy mode system or command vocabulary. Lightweight chips are enough; the parser does the rest inside the chosen lane.

### UI decisions (locked for v1)

- **Main scroll:** last **10 activities** (any type â€” note added, query result, person command, etc.). Older items drop off the top. Implementation: `SELECT ... ORDER BY created_at DESC LIMIT 10` from a unified view, or in-memory ring buffer if simpler.
- **People screen:** **names only** for v1 (no entry counts â€” keeps the screen fast and dumb). Drill into a name later if a "person detail" screen is ever needed.
- **Hamburger drawer (MVP â€” all of these ship in v1):**
  1. People
  2. Dashboard / Summary
  3. Notes
  4. Expenses (filterable list)
  5. Ledger (filterable list)
  6. Weights (filterable list)
  7. Todos (filterable list)
  8. Settings (DB backup/restore, model path)
- **Undo window:** **3 seconds.** Toast disappears after 3s, undo no longer available.

---

## Domains Handled

1. **Expenses** â€” `petrol 500`, `tomato 50, groceries 200`, `bore motor repair 7500`. Order varies. Comma-separated multi-entry. Date = now.
2. **Ledger** â€” `gave Maddy 5k`, `got 5k from Mani`, `Maddy returned 6k`, `ravi gave me 5k this month`. Natural-language variants should still become structured rows. New names allowed.
3. **Weights** â€” `jeevi 62`, `jeevi 65.1 empty stomach`, `52 jeevi, 12 prani`. Number < 150. Optional context note.
4. **Todos** â€” explicit action-like notes such as `update Amit about MCP`, `haircut on thursday`, or `TODO: renew license`. Todo is no longer the catch-all fallback.
5. **General notes** â€” arbitrary free-form text. Default destination for non-query text that is not clearly expense / ledger / weight / todo. Saved to `notes` and auto-embedded by the app. No user-facing health / investment segregation.
6. **Note queries** â€” `any info on vivekananda in my notes`, `show me motivation quotes saved`, `cipla notes`. Search runs across all saved notes by default. Ideal output is a synthesized answer followed by original snippets; raw snippets alone are an acceptable fallback.

---

## Tier 0 Grammar (deterministic, no LLM, first match wins)

These are the only rules that get to bypass the LLM. Every input that does **not** match a Tier 0 rule falls through to `user_routing_memory` lookup, then Tier 1 LLM routing. See "Routing Architecture" below.



0. **Person command** â€” line starts with `ADD_PERSON:` / `REMOVE_PERSON:` / `MODIFY_PERSON:` â†’ mutate `persons` table. Highest priority; bypasses comma split.
1. **Explicit note override** â€” line starts with `note:` â†’ save plain note exactly as entered. **No router second-guessing.**
2. **Explicit todo override** â€” line starts with `^todo[:\s]` / `^task[:\s]` (case-insensitive, with or without colon) â†’ `add_todo`. If the body is clearly list-shaped (multi-line, bullets, separators), expand into multiple todos. **No router second-guessing.**
3. **Ledger write** â€” keyword (`gave|give|given|lent|sent` â†’ user gave; `got|received|returned|paid back` â†’ user received) + person + amount. Exception: `gift` â†’ expense. If person is **not in `persons` table**, log anyway and append a nudge: `Tip: ADD_PERSON: <name> to track future entries cleanly` (option B).
4. **Weight write** â€” `<known_person> [weight] <number<150>` only when the input looks like a write, not a read request. Query-shaped phrasing should fall through instead of being coerced into a write.
5. **Expense write** â€” number + description, no person-money keyword, no whitelist name. Ambiguous comma-separated numeric input defaults to multi-expense write unless strong query markers are present.
6. **Ambiguous settlement** â€” phrases like `I gave back the amount` (or `clear <person> ledger`, `settled <person>`, etc.) create a pending numbered choice from current open balances. Replying `1`, `2`, etc. resolves the selected balance. **NOT a todo.**
7. **Anything else** â†’ fallthrough to orchestrator (memoized fast path â†’ Tier 1). Tier 0 should stay small; complex read queries should prefer safe LLM-assisted query planning over ever-growing hardcoded phrase lists.

**No expense categories.** Monthly tracking is by `month` total. For ad-hoc filtering (e.g. "how much on petrol"), use `WHERE description LIKE '%petrol%'`. Decision: a category taxonomy added complexity (keyword lists to maintain, mis-classification edge cases) without paying for itself for monthly tracking.

**Amount parsing:** `5k`â†’5000, `1.5L`â†’150000, `5,000`â†’5000, `500`â†’500.

---

## Routing Architecture

Two-tier orchestrator with a memoized fast path. The orchestrator is its own module (`second_brain_orchestrator.py`); MCP tools stay atomic and never call other tools. UI surfaces (Flask today, Android Activity later) call the orchestrator with raw user input and receive a structured response.

```
[UI surface]
     â†“ raw text
[Orchestrator: second_brain_orchestrator.py]
     â”œâ”€â”€ Tier 0: deterministic grammar (~70%, <50ms, no LLM)
     â”œâ”€â”€ user_routing_memory lookup (memoized clarify resolutions, no LLM)
     â”œâ”€â”€ fast query plan (deterministic query lane, no LLM routing)
     â””â”€â”€ Tier 1: Qwen function-calling (only for the unresolved tail)
            â”œâ”€â”€ tool call (â‰¥0.7 confidence) â†’ execute + parse readback
            â”œâ”€â”€ tool call (<0.7 confidence)  â†’ clarify_with_user
            â”œâ”€â”€ clarify_with_user            â†’ numbered options menu
            â””â”€â”€ invalid JSON (after 1 retry) â†’ heuristic clarify menu
     â†“ MCP tool call
[MCP server: atomic tools only]  â† add_*, query_*, manage_persons, etc.
     â†“
[SQL / vector store / SQLite]
```

### Tier 1 output shape (Qwen â†’ JSON)

The LLM returns exactly one of:
- `{tool: <name>, args: {...}, confidence: 0.0-1.0}` â€” concrete tool call
- `{clarify: true, question: "...", options: [...]}` â€” ambiguous, ask user
- `{unknown: true}` â€” heuristic clarify fallback

### Confidence thresholds and ask-rate budget
- **â‰¥0.7** â†’ default-and-confirm: execute, show parse readback in toast, allow undo
- **<0.7** â†’ ask via numbered options menu
- **Target ask-rate** in steady state: <10% of inputs (drops as `user_routing_memory` populates)

### JSON failure fallback
Qwen 4B at 4-bit will occasionally emit invalid JSON. Recovery chain:
1. One retry with stricter "JSON only, no prose" prompt
2. Heuristic clarify menu built from input features (number â†’ expense/weight/ledger candidates; question shape â†’ query candidates; long prose â†’ note)
3. The last option in **any** clarify menu is always "Save as raw note (don't categorize)"

**Never lose user input.** Every input ends as a saved row, a saved-as-note, or a pending clarify â€” never an error.

### Trust through visibility (toast format)
Every write response shows the parse:
```
âœ“ Saved weight: jeevi â†’ 65.3kg
  [parsed: write_weight Â· conf 0.92 Â· undo (3s)]
```
The parse text comes from the same structured object that produced the DB row, never a UI-side string.

### `user_routing_memory` (memoization)
After a clarify resolution, the orchestrator records `(normalize(input), tool, args)` into `user_routing_memory`. Subsequent identical inputs skip Tier 1 entirely. Eviction: entries unused for 90 days are pruned on app open. v1 does **not** learn from undos (noisy signal â€” undo can mean "I changed my mind" not just "wrong route").

### Why dynamic MCP tool creation is rejected for v1
Qwen 4B at 4-bit cannot reliably write safe code/SQL/tool specs. The domain (notes, expenses, ledger, weights, todos) is bounded and fits ~14 atomic tools. The preferred middle ground for complex structured **read** queries is `query_freeform`: a sandboxed read-only SQL tool against approved views, used only when static tools or minimal deterministic rules are not enough. This is explicitly different from dynamic tool/code creation.

---

## SQLite Schema

```sql
-- Single source of truth for known people. Used by weights (strict) and ledger (loose, with nudge).
-- Mutated only via chat commands ADD_PERSON / REMOVE_PERSON / MODIFY_PERSON (no auto-add).
CREATE TABLE persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,        -- lowercase, trimmed
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    input_kind TEXT NOT NULL DEFAULT 'note',   -- note | query | person_command | resolution_reply
    structured_type TEXT,                      -- expense | ledger | weight | todo | note | query | multi
    note_domain TEXT,                          -- legacy/transitional metadata only; retrieval should not depend on a user-facing domain split
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    processed_at TEXT
);

CREATE TABLE pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,                 -- e.g. ledger_settlement | clarify_intent
    note_id INTEGER,
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL,
    payload_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',    -- pending | resolved | dismissed
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    resolved_at TEXT
);

-- Memoized routing decisions, populated by clarify resolutions.
-- Looked up between Tier 0 and Tier 1 â€” repeated inputs skip the LLM entirely.
-- Pruned: rows with last_used > 90 days are dropped on app open.
CREATE TABLE user_routing_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_pattern TEXT NOT NULL UNIQUE,        -- normalize(input): lowercase, whitespace-collapsed
    resolved_tool TEXT NOT NULL,
    resolved_args_json TEXT,
    hit_count INTEGER DEFAULT 1,
    last_used TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_routing_pattern ON user_routing_memory(input_pattern);

CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    description TEXT NOT NULL,    -- verbatim, used with LIKE for ad-hoc filtering
    date TEXT,
    month TEXT,                   -- '2026-02' precomputed for fast month queries
    raw_note TEXT,
    source_note_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,        -- lowercase, trimmed
    amount REAL NOT NULL,        -- always positive
    direction TEXT NOT NULL,     -- 'gave' | 'received'
    note TEXT,
    date TEXT,
    source_note_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE VIEW ledger_balance AS
SELECT person,
       SUM(CASE WHEN direction='gave' THEN amount ELSE -amount END) AS balance
FROM ledger GROUP BY person;
-- positive = they owe you, negative = you owe them

CREATE TABLE weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,
    weight REAL NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    source_note_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    date TEXT,
    status TEXT DEFAULT 'pending',  -- pending | done
    source_note_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE investment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    event_type TEXT,    -- buy | sell | note | advice
    content TEXT,
    amount REAL,
    date TEXT,
    source TEXT,        -- self | anand | pr sundar | other
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,       -- investment | health | general
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,    -- Float32Array serialized
    source TEXT,
    date TEXT,
    source_note_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## MCP Tools

**Tools are atomic.** Each tool does one job â€” read or write a single domain. Tools never call other tools. The orchestrator (in `second_brain_orchestrator.py`) is the only thing that picks among tools.

1. `handle_input` â€” **legacy** entrypoint kept while the orchestrator refactor is in progress. Will be retired once the orchestrator is fully wired and the regression suite passes.
2. `capture_note` â€” raw-note persistence + auto-embed (post-refactor). Does not classify.
3. `prepare_ledger_settlement` â€” turns ambiguous settlement notes into a numbered options list.
4. `resolve_pending_action` â€” resolves numbered replies like `1` / `2` against the latest pending clarification (settlement OR Tier 1 clarify_with_user).
5. `add_entry` â€” INSERT into the structured table for a parsed expense / ledger / weight / todo entry.
6. `query_ledger` â€” SQL SUM/SELECT for balances, including `who_owes` and `you_owe`.
7. `query_expense` â€” SUM with optional `month` and/or `description LIKE '%X%'` filters; supports `mode=sum|list` so the orchestrator can honor "list one by one"-style phrasing.
8. `get_todos` â€” filter on todos table.
9. `get_weight` â€” latest weight or recent trend for known people.
10. `search_notes` â€” semantic retrieval across all saved notes by default. Ideal answer shape: short synthesized answer + original snippets. Raw snippet-only responses are acceptable when they are materially faster or more reliable.
11. `manage_persons` â€” CRUD on `persons` table. **Primary surface = "People" screen** (â‰¡ â†’ People). Secondary surface = chat shortcuts `ADD_PERSON: name`, `REMOVE_PERSON: name`, `MODIFY_PERSON: old new`.
12. `query_sql` â€” run an LLM-generated read-only SQL statement through the safety gate. Allowlisted tables only (`expenses`, `ledger`, `ledger_balance`, `weights`, `todos`, `persons`); SELECT-only; no DDL/PRAGMA/ATTACH; row cap; statement timeout; `mode=ro` connection. Used for complex structured reads where rules don't fit (e.g. `expenses apart from petrol last month`).
13. `server_status` â€” reports DB path, LLM backend, and embedding backend state.
14. `clarify_with_user` â€” **control-flow tool emitted by the orchestrator** (not by the user). Renders a numbered options menu, persists the pending choice to `pending_actions` (action_type=`clarify_intent`), and awaits a numbered reply. On resolution, writes the chosen `(input â†’ tool, args)` mapping to `user_routing_memory`.

---

## Design Invariants

1. Append-only ledger. Balance from view.
2. Structured queries never go through RAG.
3. LLM is interpreter / formatter, not source of truth.
4. Every user input is persisted first (capture/history layer for structured lanes; note row for real note lanes).
5. Date always = now (auto timestamp).
6. `month` column precomputed.
7. Structured side effects (`expense`, `ledger`, `weight`, `todo`) are linked back to the source capture layer (`source_capture_id`), not to editable user-note rows.
8. General / investment / health notes should be embedded by the app itself, not by a manual pre-run step for user-created content.
9. Query-looking text must not silently become a todo.
10. Ambiguous follow-up actions should return options and accept numbered replies.
11. Confirmation toast on every entry.
12. Embedding and LLM should not run simultaneously on Android (RAM pressure).
13. Routing decisions are concentrated in `second_brain_orchestrator.py`. MCP tools are atomic; tools never call other tools. UI surfaces never make routing decisions.
14. **Never lose user input.** Every input ends as a saved row, a saved-as-note, or a pending clarify â€” never an error. The last option in any clarify menu is always "Save as raw note".
15. **Trust through visibility.** Every write response shows the system's parse of the input (what was saved as what) sourced from the same structured object that produced the DB row, never a UI-side string.
16. Tier 0 grammar is the only place regex makes routing decisions. Anything Tier 0 can't unambiguously classify falls through to memoization â†’ LLM. Tier 0 never silently classifies.
17. In the target product, broad routing should mostly come from explicit input tags/chips rather than from open-ended LLM mode guessing.
18. RAG is for saved-note retrieval and optional history retrieval only. Structured facts still come from SQLite/app logic.
19. Conversational follow-ups over structured data must reuse stored structured query context before execution. Any RAG/history lookup used there is only a helper to recover context, not the final source of truth.
20. Ledger parsing is high-risk and may require default confirmation even after fine-tuning until measured direction accuracy is good enough.

---

## Notebooks Plan & Exit Criteria

| # | Notebook | Goal | Exit criteria | Status |
|---|----------|------|--------------|--------|
| 1 | `notebook_1_sqlite.ipynb` | Schema + seed + 10 SQL test queries (inline schema, no external seed.sql import) | All 10 queries return expected results | ðŸŸ¢ Built â€” verified passing on 2026-05-02 |
| 2 | `notebook_2_preparser.ipynb` | Pure-Python rule parser: `parse_amount`, `tag_category`, `parse_single`, `parse_note` + multi-entry split + confirmation toast simulator | â‰¥85% of clear cases classified correctly; ambiguous flagged | ðŸŸ¡ Built â€” needs `Run All` to confirm exit criteria |
| 3 | `notebook_3_qwen_parser.ipynb` | Qwen LLM fallback (llama-cpp-python or transformers) + JSON extraction + validator + mock-mode + combined ruleâ†’Qwen flow | â‰¥80% of ambiguous cases classified with valid JSON | ðŸŸ¡ Built â€” runtime app now uses a real GGUF model; notebook remains an experiment/reference surface |
| 4 | `notebook_4_vector_store.ipynb` | MiniLM embeddings + cosine search; investment + health chunks; embed-and-store; per-domain top-k search | Top result relevant for all RAG test queries | ðŸŸ¡ Built â€” still useful to seed bundled investment/health content, but no longer required for user-created note indexing |
| 5 | `notebook_5_end_to_end.ipynb` | Full pipeline: parser inlined, 6 tool implementations (search_notes, query_ledger, query_expense, get_todos, get_weight, add_entry), keyword-based router, 10 acceptance queries + latency benchmark | 9/10 correct; SQL <500ms, RAG <5s | ðŸŸ¡ Built â€” legacy reference only; Flask + MCP runtime supersedes it as the active test surface |

**Embedding model:** `paraphrase-multilingual-MiniLM-L12-v2` (matches Android ONNX target).
**LLM:** Qwen2.5-4B or Qwen3-4B, 4-bit quantized GGUF.

---

## Test Queries (Notebook 5 acceptance set)

```
Maddy balance                            â†’ query_ledger â†’ â‚¹7,000 (they owe you)
Who owes me money                        â†’ query_ledger â†’ Maddy 7k, Thenna 20k
Jeevi latest weight                      â†’ query_ledger â†’ 60.1 kg on 2026-04-24
How much did I spend in February         â†’ query_expense â†’ SUM Feb 2026
How much did I spend on petrol           â†’ query_expense â†’ SUM WHERE description LIKE '%petrol%'
Pending todos                            â†’ get_todos
gave Mani 2000                           â†’ add_entry â†’ ledger insert
petrol 500, groceries 300                â†’ add_entry â†’ 2 expense inserts
What did Anand say about Cipla           â†’ search_notes â†’ Anand chunk
Can I eat tomato                         â†’ search_notes â†’ No, nightshade
```

---

## Seed Data Reference

Full seed (ledger initial balances, weight history for jeevi/prani/murugan, sample Feb/Mar 2026 expenses, investment chunks for Anand/PR Sundar/self, health chunks for psoriasis/histamine) is in `second_brain_jupyter_guide.md` sections "Seed Data", "Investment Notes Content", "Health Reference Content". Copy into Notebook 1 / Notebook 4 as needed.

---

## Repo Layout

Current working layout:

```
app.py                           Flask dogfooding surface
second_brain_orchestrator.py     two-tier intent router (Tier 0 grammar + planner + Tier 1 Qwen function-calling)
second_brain_core.py             shared parser / note / SQL / embedding / LLM logic
second_brain_mcp_server.py       real MCP server (atomic tools only, never calls other tools)
second_brain_mcp_client.py       Flask-side MCP client
sql_safety.py                    sqlglot-backed AST gate for LLM-generated read-only SQL
second_brain.db                  primary local database
models/                          local GGUF + embedding cache
templates/                       Flask templates
static/                          Flask CSS/assets
notebook_1_sqlite.ipynb          schema + seed + SQL tests
notebook_2_preparser.ipynb       rule-based parser experiments
notebook_3_qwen_parser.ipynb     LLM fallback experiments
notebook_4_vector_store.ipynb    seed investment/health vector corpus
notebook_5_end_to_end.ipynb      notebook-era end-to-end reference
seed.sql                         standalone schema+seed dump
requirements.txt                 Python dependencies
project_development.md           this tracker
android/                         Android client (active product surface as of 2026-05-08; see android_port.md)
android/app/build/outputs/apk/debug/app-debug.apk   First debug APK (36.8 MB, built 2026-05-08, CPU-only)
android_port.md                  Android port tracker — architecture decisions, phase status, file layout, build issue history
colab_convert_to_gguf.ipynb      Colab notebook: merge LoRA → Q4_K_M GGUF for the Android app
colab_export_minilm_onnx.ipynb   Colab notebook: export all-MiniLM-L6-v2 → ONNX + WordPiece vocab for Android note search
export_minilm_onnx.py            Local laptop equivalent of colab_export_minilm_onnx.ipynb (use after creating .venv-onnx-export)
second_brain_jupyter_guide.md    original spec doc
test_sql_safety.py               adversarial corpus for the SQL safety gate
test_orchestrator_tier0.py       Tier 0 grammar regressions
test_routing_memory.py           memoization layer regressions
test_logs_regression.py          original logs.txt failure-pattern regressions
test_activity_log_regression.py  every misroute observed in the live activity log
test_flask_crud.py               page-based CRUD regressions for /notes /expenses /ledger /weights /todos
test_independent_500.py          out-of-the-box 510-case stress (note-heavy, danger/weak/broken bucketed)
test_replay_matrix.py            200-case historical+variant replay matrix
test_replay_matrix_full_throttle.py  500-case full-throttle generated mix
test_note_corpus_stress_200.py   200-long-note isolated corpus stress
```

**Cross-notebook dependencies:**
- Notebook 1 must run first to create `second_brain.db` with all tables and seed rows.
- Notebook 4 can still seed bundled investment / health content into the `embeddings` table of the same DB.
- The live Flask + MCP app no longer depends on Notebook 5 for routing; `second_brain_core.py` is the runtime source of truth.

---

## Dependencies

All dependencies are in `requirements.txt`. Install with:

```bash
pip install -r requirements.txt
```

Use Python 3.10+ for this repo. Current working local env is a project-local `.venv` on Python 3.14.

What it pulls in:
- **Jupyter stack** â€” `jupyter`, `notebook`, `ipykernel` (run the .ipynb files)
- **Embeddings (NB4 + NB5)** â€” `sentence-transformers`, `numpy`
- **SQL safety gate** â€” `sqlglot` (parses LLM-emitted SQL into an AST so the orchestrator can enforce SELECT-only + table allowlist before execution).
- **Qwen backend (NB3)** â€” `llama-cpp-python` (default; matches Android target). Fallback: uncomment `transformers` + `accelerate` + `torch` in requirements.txt if llama-cpp-python won't build on Windows.
- **Runtime cache/model ownership** â€” GGUF lives under `models/`; embedding downloads/cache also live under `models/embedding_cache` so the dev runtime stays self-contained.
- **Built-ins** â€” `sqlite3`, `re`, `datetime`, `json` (no install needed)

If `llama-cpp-python` fails to install on Windows, you typically need MSVC Build Tools or use the prebuilt wheel: `pip install llama-cpp-python --prefer-binary`.

---

## Development Log

_Append entries here as work proceeds. Format: `YYYY-MM-DD â€” what changed / what was decided / what's next`._

- 2026-05-05 â€” **Input contract clarified around explicit lane tags, follow-up query context, and RAG scope.** The target product should move from broad freeform top-level routing to a **tag-first chip-based input model**: write chips `expense:` / `todo:` / `buy:` / `weight:` / `ledger:` / `note:` plus note-like extensions `journal:` / `idea:` / `watch:` / `work:`, and one explicit query chip `ask:` (with optional `search:` alias). The chosen tag decides the lane; rules/LLM parse **inside** that lane instead of guessing the broad input kind. Structured queries continue to resolve through SQLite/app logic; note retrieval goes through lexical + embedding/RAG retrieval, with optional faithful synthesis over retrieved snippets. Follow-up structured questions like `of that how much was groceries` should be solved by storing prior structured query context and inheriting/modifying it before SQLite runs the next query; RAG/history retrieval may help recover that context but is not the source of truth for arithmetic. Ledger remains special: default confirmation is still acceptable because direction phrases are easy to misread. Notes remain plain text; any title/summary/topic generation is optional/async only. Expense categories/groups may exist later as a derived overlay, but verbatim description remains the source of truth and no mandatory category UI is planned. MCP is now documented as an implementation detail that can be replaced if direct in-process service calls make Android integration simpler. The current Qwen family/model remains the baseline for fine-tuning/runtime experiments unless real-device benchmarks prove otherwise.
- 2026-05-05 â€” **Fine-tuning dataset sanity doc created; `expense:` behavior locked.** Added `finetuning_data_sanity.md` as the source-of-truth document for synthetic-data preparation. The first locked section is `expense:`: multi-entry accepted, trailing date applies to all records, incomplete inputs rejected, default currency is INR, foreign currency is saved numerically with warning/no conversion, actual calendar date is resolved at save time, fixed grouping vocabulary is defined, India-heavy dataset distribution target set to 70%, and refunds/gains are explicitly out of scope for the `expense:` lane.
- 2026-05-05 â€” **`buy:` behavior locked in the fine-tuning sanity doc.** `buy:` stays as a separate user-facing lane, but as a lightweight shopping/procurement checklist rather than a heavy analytics domain. Parsing should be LLM-handled, not rule-first. The boundary is now explicit: `buy:` is mostly noun phrases/items to acquire later; `todo:` is mostly action phrases/tasks to perform. `buy:` supports multi-item lines, optional quantity/unit, brand-heavy wording preservation, resolved dates like `expense:`, immediate rejection of incomplete inputs, no category inference in v1, and open/done checklist lifecycle with simple retrieval of the current buy list.
- 2026-05-05 â€” **`todo:` behavior locked in the fine-tuning sanity doc.** `todo:` is now defined as the action/reminder checklist lane: action phrases, appointments, bill payments, admin chores, and noun-like reminders are all valid. Parsing should preserve user wording closely instead of aggressively normalizing text. Multi-entry, multiline, and bullet-style inputs are allowed; shared trailing date phrases apply to all entries; missing dates default to today; explicit date phrases resolve immediately to actual calendar dates. No separate time field, no recurrence, no priority, no grouping, and only `open/done` state in v1. Broad retrieval should show open tasks by default, while done items are included only when the user explicitly asks for all todos. If the user mistakenly uses `todo:` for shopping-list-like entries, accept them as todos rather than rejecting them.
- 2026-05-05 â€” **`weight:` behavior locked in the fine-tuning sanity doc.** `weight:` is now narrowed to body-weight tracking only, `kg`-only in v1, with multi-entry support and optional short context notes like `before breakfast` or `after walk`. Unknown names are allowed and should create new person entries, while nameless/self-style writes and queries map to a dataset/runtime placeholder `self`, which app/UI code can later bind to the user's default person. Missing dates default to today; explicit date phrases resolve immediately; shared trailing dates apply to all entries in the line. Retrieval should support latest/history/change/trend, and history/trend default to the last 6 months when no explicit range is given.
- 2026-05-06 â€” **`ledger:` behavior locked in the fine-tuning sanity doc.** `ledger:` is now defined as person-to-person debt tracking only: either you owe someone or someone owes you. Clear directions like `I owe X`, `X owes me`, `borrowed from X`, and `lent X` are valid; ambiguous `gave/received` phrasings are supported but should be confirmed. Settlements and partial repayments are mandatory in v1, with `settled with X` clearing the relationship to zero even across multiple prior entries. Multi-entry lines are allowed; unknown names should auto-create person entries; amount parsing/currency behavior should mirror `expense:`; missing dates default to today; explicit dates resolve immediately. Broad ledger retrieval should default to full transaction history, while person-specific retrieval should return both summary and recent dated entries.
- 2026-05-06 â€” **`note:` behavior locked in the fine-tuning sanity doc.** `note:` is now defined as the hard plain-note override: no structured reinterpretation, near-exact text preservation, multiline content stored as one payload, and no auto-splitting. Empty `note:` is rejected, but even very short notes like `note: 1` are valid. Date phrases inside notes stay untouched. A key product rule is now documented: multiple `note:` submissions on the same day should append into one same-day note bucket rather than always creating one separate note per submission. `note:` content remains part of the general searchable note pool.
- 2026-05-06 â€” **Note retrieval behavior locked in the fine-tuning sanity doc.** For v1, note-style retrieval should search plain notes only, not future note-like lanes by default. Broad requests like `show my notes` should return today's note bucket first, or the most recent earlier day if nothing exists today. Topical note retrieval should be typo-tolerant and approximate-match friendly, prefer short summary plus all relevant snippets, and fall back to raw snippets only when confidence is weak. Date filtering applies to note retrieval, and `show my latest note` now means the latest day bucket because same-day note writes append together.
- 2026-05-06 â€” **Expense retrieval behavior locked in the fine-tuning sanity doc.** Broad expense retrieval now defaults to the current month, with total plus a recent list; broad summary requests should show the current-month total plus the last 5 expenses, while `recent expenses` specifically means the last 10 entries. Today's expense queries should return today's list plus today's total. Item queries prefer exact matches but may use approximate lexical matching with a correction toast; broad semantic brand reinterpretation is out of scope for v1. Group-based queries and exclusion queries (`apart from`, `except`, `excluding`) are first-class and should trust inferred expense groups for retrieval. Expense lists should be grouped by date, `expense history` defaults to the current month, and follow-up queries must inherit prior expense domain/date/filter context unless explicitly overridden.
- 2026-05-06 â€” **Todo retrieval behavior locked in the fine-tuning sanity doc.** Broad todo retrieval now defaults to open tasks only. `show my todo list` / `show my tasks` should return open items, grouped by date. Today-specific and due-this-week queries should also stay open-only by default. `show all todos` should include both open and done items, with open first; `task history` defaults to the last 10 open+done tasks; done/completed retrieval by date is supported. Noun-like reminder search and approximate lexical matching are both valid. `show my latest task` means the latest task for today if available, else the most recent earlier day. Follow-up inheritance is important here too, and `buy:` retrieval should remain separate from `todo:` retrieval.
- 2026-05-06 â€” **Weight retrieval behavior locked in the fine-tuning sanity doc.** Self-style weight retrieval now defaults to the `self`/default person automatically. `show my latest weight` should return just the latest value plus date; `show my weight history` defaults to the last 6 months; named-person history like `show Arun weight history` should return the last 5 entries with dates. Trend queries should return a short increase/decrease summary plus supporting entries, while change queries compare the requested starting point to the latest value. Broad `show latest weights` should return the latest weight for all known people, but vague phrases like `show family weights` should be rejected. Optional context notes may be shown inline, same-day duplicate entries collapse to the latest one per person, and approximate person-name matching should require confirmation rather than silent correction.
- 2026-05-06 â€” **Ledger retrieval behavior locked in the fine-tuning sanity doc.** Broad ledger retrieval now defaults to open balances only. Person-specific retrieval like `show Arun ledger` should return summary plus recent dated entries; balance questions like `how much do I owe Arun` return current balance only; `show open ledger with Kiran` returns balance plus recent entries; `recent ledger entries` means the last 10 entries; `ledger from last month` returns current balance plus filtered history; and `show latest ledger` means the most recently changed person balance. Broad history outputs should be grouped by date and shown newest first. Approximate person-name matches should ask for confirmation and reject on no response, while existing people with zero open balance should return `no open ledger found`. Follow-up inheritance is important here too: person/date context should carry forward across ledger follow-ups unless explicitly changed.
- 2026-05-06 â€” **Shared v1 training schema frozen in the sanity doc.** `finetuning_data_sanity.md` now contains the frozen shared schemas for `parse_write`, `parse_query`, and `parse_followup_query`, plus lane-specific record shapes, allowed query intents by domain, expected filter shapes, and explicit exclusions. Important locked decisions: query outputs use resolved `date_start` / `date_end`; compare queries additionally use `compare_date_start` / `compare_date_end`; `note:` is excluded from write-side fine-tuning as a deterministic bypass but remains part of retrieval training; `ledger` uses the action model `{add_debt, add_credit, repay_debt, collect_credit, settle}`; and `buy` remains a full query domain in the schema. Query narrowing is also now locked: `ask:` remains the main query lane, but the UI may optionally provide a scoped hint such as `ask + expense` / `ask: expense:`. That scope is treated as an input-side routing hint, while the output schema remains stable and continues to emit only the canonical parsed `domain`. Future sessions should treat this schema as the dataset-generation baseline rather than revisiting field design from scratch.
- 2026-05-06 â€” **Schema-frozen sample dataset v2 created for review.** A new review dataset now exists at `sample_finetune_dataset_v2_schema_frozen/`. It reflects the frozen v1 schema, includes write/query/follow-up examples across the active domains, and keeps `note:` write behavior in `reference_only/` because note writing is excluded from write-side fine-tuning. Future dataset work should extend this schema-frozen sample set or generate from the same rules, not go back to the older illustrative `sample_finetune_dataset_v1/` shapes.
- 2026-05-06 â€” **Large synthetic generator strengthened, but final dataset run still pending approval.** Added `synthetic_dataset_assets.py` as a dedicated India-first/global asset pool and rewired `generate_large_schema_frozen_dataset.py` to import from it instead of relying on a tiny in-file pool. The generator now also has a `--report` mode for pre-run inspection. Current coverage report: `india_names=150`, `global_names=50`, `india_note_topics=57`, `global_note_topics=30`, `india_expense_items_total=209`, `global_expense_items_total=86`, `india_buy_items=67`, `global_buy_items=30`, `india_todo_actions=45`, `india_todo_nouns=20`, `global_todo_actions=21`, `global_todo_nouns=10`, `india_ledger_reasons=30`, `global_ledger_reasons=15`, `single_date_options=24`, `range_options=24`. Template coverage was also expanded beyond the earlier sample-stage generator: `expense_write_patterns=8`, `expense_natural_patterns=5`, `buy_prefix_patterns=4`, `buy_triple_patterns=3`, `todo_time_patterns=5`, `note_search_patterns=6`, `expense_group_query_patterns=4`, `expense_compare_patterns=3`, `recent_expense_patterns=3`, `buy_query_patterns=4`, `todo_open_patterns=4`, `ledger_summary_patterns=3`, `ledger_recent_patterns=3`, `note_latest_patterns=3`. `dataset_india_context_rulebook.md` was updated to make the review gate explicit: inspect the report first, then run the full 29k-row generation only after explicit confirmation.
- 2026-05-06 â€” **Generator realism/Tanglish pass completed after 1000-row review.** The reviewed `synthetic_finetune_dataset_v3_large_india_first/` sample exposed two classes of problems: semantically absurd positive rows and weak Tanglish coverage on the query side. `generate_large_schema_frozen_dataset.py` was then tightened so robustness comes from realistic messy positives, typo-like queries, Tanglish phrasing, explicit rejects, and explicit confirms, not from nonsense accepts. The main changes were: expense amounts now use group/item-aware amount bands; buy quantities/units now use item-aware rules for herbs, spices, vegetables, liquids, and retail-count items; buy pools are filtered away from obvious todo/bill/service items; and Tanglish phrasing was added directly into `expense` / `buy` / `todo` / `weight` / `ledger` / `note` query generators plus selected write/follow-up generators. The regenerated 1000-row review set now parses cleanly, no longer shows the earlier tiny-expense/huge-amount failures, no longer shows the earlier dry-item/liquid-unit buy failures, and has materially better Tanglish spread across query lanes. Future scaling should use this tightened generator, not the earlier pre-review version.
- 2026-05-06 â€” **Large 10k/10k/10k/20k dataset run completed; soft uniqueness observed on a few lanes.** The strengthened generator was run with `WRITE_COUNT = 10000`, `QUERY_COUNT = 10000`, `REFERENCE_COUNT = 10000`, and `FOLLOWUP_COUNT = 20000`. The run completed successfully. Some lanes exhausted unique phrasing space and fell back to soft uniqueness with repeats: `parse_query/buy` reached `3969` unique rows before repeat-fill, `parse_query/weight` reached `4340`, `parse_query/ledger` reached `6511`, and `reference_only/note_write_reference` reached `3394`. This is acceptable for the current training plan because strict uniqueness is not mandatory; diversity-first generation plus controlled repeats is acceptable once the unique space is exhausted. `reference_only/` remains excluded from SFT training input by design because `note:` write behavior is deterministic and not part of the parser fine-tune path.
- 2026-05-06 â€” **Training/eval scripts aligned to the frozen schema and current model recommendation.** A revised `colab_finetune.py` was prepared to load only `parse_write/`, `parse_query/`, and `parse_followup_query/` rows from the dataset root and skip `reference_only/` rows intentionally. This matches the frozen rule that `note:` write behavior is deterministic/app-controlled and excluded from parser SFT. The revised Colab script defaults to `unsloth/Qwen3-1.7B-bnb-4bit`, with `0.6B` kept as the smaller dry-run option. `evaluate_finetune.py` was updated to score the frozen schema fields (`date_start` / `date_end`, compare ranges, ledger `action`, write `disposition` / `reason_code`, etc.) and now warns when pointed at the legacy `eval_finetune_dataset_v1/heldout_cases.jsonl` file because that held-out set predates the frozen v1 schema. Important historical note: the actual adapter later evaluated in this tracker still came from `colab_finetune_old.py`, not from this revised script.
- 2026-05-06 â€” **Schema-aligned held-out eval set v2 created and now preferred.** `generate_eval_dataset_v2.py` now produces `eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl`, a 500-case held-out set aligned to the frozen v1 parser schema. The current build contains `200` write cases, `210` query cases, and `90` follow-up cases. It was regenerated with the held-out paraphrase logic and completed with `0` training-overlap fallback rows, so the current v2 eval set is cleanly separated from `synthetic_finetune_dataset_v3_large_india_first/`. `evaluate_finetune.py` now defaults to this v2 dataset path; `eval_finetune_dataset_v1/heldout_cases.jsonl` remains legacy-only.
- 2026-05-06 â€” **Separate local GTX1650 experimental path created for Qwen3-0.6B.** Added `create_local_qwen3_0p6b_env.ps1` plus `requirements_local_qwen3_0p6b_windows.txt` to create a dedicated Windows local environment for Unsloth-based `0.6B` experiments. Added `local_finetune_qwen3_0p6b_gtx1650.py` and `local_evaluate_qwen3_0p6b_gtx1650.py` as a separate laptop-safe path from the Colab flow. The local fine-tune defaults are intentionally conservative for 4GB-class GPUs: `Qwen3-0.6B`, `max_seq_length=512`, `per_device_batch_size=1`, `gradient_accumulation_steps=16`, `lora_r=8`, checkpoint saving by steps, and a default training subset cap of `12000` rows instead of the full 130k parser dataset.
- 2026-05-06 â€” **First real `Qwen3-1.7B` Colab fine-tune produced strong write-side parser results.** The actual adapter for this run was trained via `colab_finetune_old.py` on free Colab T4 and saved at `notes_app_finetuning/unsloth_qwen3_parser_run/lora_adapter`. That script trained on all loaded parser rows with no `MAX_TRAIN_ROWS` cap. The first `100` held-out cases covered `parse_write` only and the fine-tuned model achieved `100%` valid JSON, `91%` exact match, `100%` task match, `100%` lane/domain match, `100%` disposition match, `100%` record-count match, `100%` amount/date/unit metrics on applicable rows, and only `9` exact-match misses. The remaining misses looked like plausible expense-group classification disagreements rather than structural parser failures. Important path note for future sessions: use the PEFT adapter folder `lora_adapter` for evaluator adapter loading, not `lora_adapter_unsloth`. T4 time exhausted before query/follow-up evaluation could be completed, so the next GPU session should spend time specifically on `parse_query` and `parse_followup_query` slices rather than re-validating write parsing.
- 2026-05-06 â€” **Downloaded artifact check completed; keep the adapter folder, not the loose merged weight file.** The downloaded run archive `unsloth_qwen3_parser_run-.../unsloth_qwen3_parser_run/` contains the complete adapter bundle needed for the current app/eval path: `lora_adapter/` includes `adapter_config.json`, `adapter_model.safetensors`, tokenizer files, and chat template. That is the artifact to keep. `checkpoint-491/` is optional and only useful for possible training resume/debug. The separately downloaded `model-001.safetensors` is not sufficient on its own for the current app path and is not the preferred artifact to depend on. The base model paired with the kept adapter remains `unsloth/Qwen3-1.7B-bnb-4bit`.
- 2026-05-06 â€” **Added `current_state.md` as a short navigation/orientation index.** The tracker has grown long enough that re-explaining context every session is expensive. The new file points into the right sections of `project_development.md`, `finetuning_data_sanity.md`, and `dataset_india_context_rulebook.md` instead of duplicating them. It also captures the active artifact paths (`unsloth_qwen3_parser_run-.../lora_adapter`), the dataset breakdown (53k rows; `reference_only/` excluded from SFT), the limited eval coverage so far (100 of 500 cases, parse_write only, 91% exact match with the 9 misses all being expense `group` taxonomy disagreements), and the next priorities (local inference helper, Flask wiring, full eval, dogfood-driven re-fine-tune).
- 2026-05-06 â€” **First local 4-bit inference of the fine-tuned adapter on the GTX 1650; covered slices the Colab eval missed.** Created a dedicated Python 3.10 env at `.venv-qwen3-1p7b-1650` (CUDA 12.4 torch, Unsloth + peft + bitsandbytes; install order documented at the top of `requirements_local_qwen3_finetuned_windows.txt`). Wrote `infer_finetuned_parser.py` with REPL, one-shot, and curated `--preset` modes. The 43-prompt preset run (614 s, 14.3 s/prompt) produced **43/43 valid JSON**, with **~33/43 functionally correct vs spec**. Strong wins: all 5 ledger actions (`add_debt|add_credit|repay_debt|collect_credit|settle`), `disposition: confirm + ambiguous_direction` for `gave/received` phrasings, self-mapping for nameless weight (`weight: 72.4` â†’ `person_text: "self"`), Tanglish expense queries, exclusion semantics (`apart from groceries` â†’ `exclude_group`), compare-range resolution (`compare this and last month` â†’ both date ranges populated), and **follow-up context inheritance perfect on all 3 cases tested** (filter add, range narrow, person filter). Real gaps surfaced for a future training pass: (a) `disposition: reject` for incomplete expense/todo inputs not learned (`expense: apples` accepted with `amount: null`; `todo: tomorrow` accepted with `text: "tomorrow"`), (b) note-query date filtering not resolved (`what did I write yesterday` â†’ dates null, phrase stuffed into `query_text`), (c) one domain hallucination (`"due"` instead of `todo` for `what is due this week`), (d) `recent` mapped to `total` instead of `list+limit`. The earlier cap-based explanation is now withdrawn: the tested adapter came from `colab_finetune_old.py`, which trained on all loaded rows, so this is not a simple `MAX_TRAIN_ROWS=4000` issue. Detailed scoring per prompt is in `preset_run_analysis.md`. Next: lock script provenance, run the full 500-case held-out eval to get real numbers on `parse_query` and `parse_followup_query`, and add a runtime allowlist guardrail for `domain` / `intent` so out-of-enum hallucinations cannot reach SQL. Retraining should happen only after choosing a canonical training script path explicitly.
- 2026-05-06 â€” **Training provenance correction recorded.** The `Qwen3-1.7B` adapter referenced in `current_state.md`, the 100-case held-out write-only eval, and the 43-prompt local preset run was trained with `colab_finetune_old.py`. The current `colab_finetune.py` was modified later after a clarification mismatch and must be treated as a separate revised experiment script, not as the historical source of the current adapter. Consequence: prior advice to "just set `MAX_TRAIN_ROWS=0`" does not apply to the existing adapter lineage and should not be used as the default next step without first choosing which Colab script is canonical going forward.
- 2026-05-06 â€” **Synthetic/eval dataset generation hardened for coverage-first behavior.** `generate_large_schema_frozen_dataset.py` now seeds every parser lane with explicit coverage buckets before the final shuffle, so smaller runs do not silently miss rare but important slices like `reject`, note `day_bucket`, expense `recent`, or todo `due_week`. The training rows are then shuffled after coverage seeding to avoid long same-pattern stretches. `generate_eval_dataset_v2.py` now builds a coverage-front prefix and interleaves lane groups so a limited eval run (for example first 100 rows) still touches every major tool/lane and the important rare buckets before the long tail. Supportive change: both Colab fine-tune scripts now explicitly global-shuffle loaded examples across files/lane groups before training. Important non-change: `reference_only/` remains excluded from parser SFT because those rows contain deterministic `note:` write reference behavior (`reference_behavior`), not parser-task JSON outputs, so adding them would teach the wrong schema rather than fix note-query date parsing.
- 2026-05-06 â€” **Feature-flagged fine-tuned parser path integrated into the live Flask/orchestrator runtime.** Added `second_brain_finetuned_parser.py` as a lazy-loaded Unsloth/PEFT runtime wrapper with schema validation, env-based adapter/base-model overrides, and explicit follow-up-context formatting that matches the training/eval prompt shape. `second_brain_orchestrator.py` now intercepts tagged lanes (`expense:` / `buy:` / `todo:` / `weight:` / `ledger:` / `ask:`) after the deterministic `note:` bypass but before the old explicit-todo / fast-path / Tier-1 flow, and executes parser outputs directly instead of routing them back through the legacy tool-picker. Runtime guardrails were added for invalid payloads, lane/task mismatches, and follow-up queries with no saved context. Query follow-up context is now persisted in a small `runtime_state` table under `finetuned_last_query_context`. `second_brain_core.py` gained the supporting storage changes needed for dogfooding this path: new `buy_items` table, new `runtime_state` table, `expenses.group_name`, `todo.date` writes, `buy` support in `add_entry_result`, and date-filter support in `query_notes_result`. `seed.sql` was updated to match that schema, and `app.py`'s capture-cleanup helper now counts `buy_items` references too. The fine-tuned path also adds deterministic execution support for parser-native buy-list writes/queries and stores expense groups from parser writes so group/exclusion queries have something real to filter on for new data. Startup warmup now optionally warms the parser when `SECOND_BRAIN_FINETUNED_PARSER_ENABLED=1`. Verification: `python -m py_compile second_brain_finetuned_parser.py second_brain_core.py second_brain_orchestrator.py app.py` passed; a fake-parser smoke harness verified expense write, buy write/query, expense follow-up context, todo reject clarification, and ambiguous ledger confirm flows end-to-end on a copied DB; existing regressions still passed with the feature flag off (`test_orchestrator_tier0.py` 31/31 and `test_flask_crud.py` all pass). Practical runtime note: because the integrated parser loads Unsloth/CUDA torch in-process, live dogfooding should run the Flask app from `.venv-qwen3-1p7b-1650` (the GPU env) rather than from the light `.venv`; `requirements_local_qwen3_finetuned_windows.txt` now includes `flask`, `mcp`, and `sqlglot` so that env can host the app.
- 2026-05-02 â€” Created `project_development.md` as the working tracker. Source guide kept at `second_brain_jupyter_guide.md` for reference.
- 2026-05-02 â€” Decided: keep all files flat in the project root (no subdirectories). Updated repo layout.
- 2026-05-02 â€” Notebook 1 complete. Created `seed.sql` (schema + ledger/weights/expenses/todos seed) and `notebook_1_sqlite.ipynb`. All 10 verification queries pass (Maddy=7000, Thenna=20000, Jeevi latest 60.1/2026-04-24, Feb total=3506, Feb transport=1000, append-only -6k â†’ Maddy=1000). DB persisted at `second_brain.db`.
- 2026-05-02 â€” User scaffolded notebooks 2, 3, 4, 5. Notebook 1 now uses inline schema/seed (does not import `seed.sql`); `seed.sql` retained as a standalone reference dump. Implementation notes:
  - **NB2** â€” adds `lent`/`sent`/`advanced` to gave-keywords, `paid back`/`gave me` to received-keywords. Extends category dictionaries (transport: car rental, airport; medical: naruvi, horlicks, candid, keto; food: poori, vada, laddu, badam, ananda, etc.). Includes `weight_confirm` branch for new persons and `confirm` flag on amounts in 150â€“999 range with potential person word.
  - **NB3** â€” graceful 3-tier backend selection (llama-cpp-python â†’ transformers â†’ mock). Mock dictionary covers the 7 ambiguous test cases. Uses temperature 0 for determinism. Validator enforces required fields per type.
  - **NB4** â€” 15 investment chunks (Anand on Cipla/SIB/IndusInd/Dr Reddy/IDFC; PR Sundar; self mistakes/strategy/48hr rule; Peter Lynch; pharma allocation; holdings; banking metrics; conviction). 13 health chunks (root cause, gut damage, nightshades, dairy, gluten, histamine, safe grains/veg/fruits/fats/drinks/snacks, antihistamines, cooking alternatives). Embeddings stored as float32 BLOB.
  - **NB5** â€” keyword-based router (no LLM for routing yet); 6 tools wired; 3-run latency averaging. Bare-name pattern (e.g. "jeevi") routes to weight, not ledger.
- 2026-05-02 â€” Updated tracker to reflect all 5 notebooks built. Status legend: ðŸŸ¢ verified passing, ðŸŸ¡ built but needs run-through to confirm exit criteria, â˜ not started.
- 2026-05-02 â€” **Dropped expense `category` everywhere.** Reason: keyword-based auto-tagging adds maintenance burden (long lists, mis-classifications) without paying for itself for monthly tracking. Description is stored verbatim and ad-hoc filters use `WHERE description LIKE '%X%'`. Changes:
  - **Schema** (`seed.sql`, NB1, project_development.md) â€” removed `category` column from `expenses` table.
  - **NB1** â€” Q8 changed from `category='transport'` to `description LIKE '%petrol%'` (still expects 1000).
  - **NB2** â€” deleted `CATEGORY_RULES` and `tag_category` cell; removed `category` field from expense entry dict and from test-case expected fields; toast no longer says "logged under {category}".
  - **NB3** â€” removed `category` field from Qwen prompt's expense JSON shape; updated mock responses; updated ambiguous test cases.
  - **NB5** â€” `query_expense_tool(month=, description_like=)` replaces `category=` param; router uses a 13-keyword description-LIKE seed list (`petrol`, `medicine`, `electricity`, etc.); `add_entry_tool` insert no longer references `category`; "How much did I spend on petrol" test query checks for "petrol" in response (not "transport").
  - **MCP tool list** â€” `query_ledger` example "food this month" replaced with `query_expense â†’ SUM WHERE description LIKE '%petrol%'`.
- 2026-05-02 â€” Stepped back to add an **App UI section** at the top of this file. Realized I'd been designing chat-only flows because notebooks are CLI; the actual product has a bottom input bar (notes + queries), a hamburger drawer for management screens (People, Dashboard, domain lists, Settings), and a confirmation toast with Undo. Reframed `ADD_PERSON:` etc. as power-user shortcuts; the **People screen is the primary path** for person management. No code changes needed in notebooks â€” they validate the engine, and the engine doesn't care which surface called it.
- 2026-05-02 â€” Locked v1 UI decisions: main scroll = **last 10 activities** (any type), People screen = **names only** (no counts), hamburger drawer ships with all 7 items (People, Dashboard, Expenses, Ledger, Weights, Todos, Settings), undo window = **3 seconds**.
- 2026-05-02 â€” Added **persistent `activity_log` table** (replacing the in-memory feed) and a dedicated `/activity` page (paginated, 50/page). Every input + response is now logged with a `kind` tag (`query` / `write` / `person_command` / `unknown`). The home feed reads the last 10 from this table. Survives server restarts. Drawer link "ðŸ“œ Activity log" added between Dashboard and People. Schema added to NB1 + `seed.sql`; `app.py` calls `ensure_activity_log_schema()` on startup so existing DBs get the table without a rebuild. Also fixed router gap: `total monthly expense` was falling through to all-time because "monthly" wasn't in the time-qualifier list â€” added "monthly" / "current month" as synonyms for "this month".
- 2026-05-02 â€” **Switched primary testing surface to Flask** (`app.py` + `templates/`). Notebooks remain as engine validation reference. Decision: notebooks are CLI-style and made the user feel disconnected from how the app would actually work; Flask gives a real UI to touch in browser, faster iteration than Android emulator (which had a 350MB issue last time). Same Python parser, same SQL, same RAG â€” only the view layer is new. Built v0 with: bottom input bar + last-10 in-memory feed (resets on server restart, OK for v0); offcanvas hamburger drawer with all 7 items; People screen with full CRUD; Dashboard with balances/this-month-spend/latest-weights/pending-todos; generic list view for Expenses/Ledger/Weights/Todos. Smoke-tested all 8 routes return 200 and the query router handles balance/weight/expense/todo/RAG queries correctly. Two correctness fixes baked in: (1) balance lookup falls through to `ledger_balance` even for names not in the persons whitelist (so unknown ledger names like option-B nudges still resolve); (2) `MODIFY_PERSON` / People-screen rename cascades to `ledger.person` and `weights.person` (no orphaned history).
- 2026-05-02 â€” **Added `persons` table as single whitelist** (replaces hard-coded `KNOWN_WEIGHT_PERSONS`). Used by weights (strict â€” must be in list) and ledger (loose â€” option B nudge if not in list). Managed only via chat commands `ADD_PERSON: name`, `REMOVE_PERSON: name`, `MODIFY_PERSON: oldname newname`. New 7th MCP tool `manage_persons` mutates the table and refreshes the in-memory `KNOWN_PERSONS` set. Person commands have highest router priority and bypass comma split. Dropped the old `weight_confirm` branch â€” `biscuit 20` / `milk 60` now correctly log as expenses, not new-weight prompts. Files touched: `seed.sql`, NB1 (schema + seed), NB2 (parser, tests, toast), NB5 (parser loads from DB, `manage_persons_tool`, router prefix check, `add_entry_tool` nudge), `project_development.md` (schema, rule 0, MCP tool count 6â†’7).

---

 - 2026-05-02 Ã¢â‚¬â€ **Replaced the Flask-only router with a real MCP server/client path.** Added `second_brain_mcp_server.py` (official Python MCP SDK over stdio), `second_brain_mcp_client.py` (Flask-side MCP client), and `second_brain_core.py` (shared parser/SQL/RAG/LLM logic). Bottom-bar input now goes Flask Ã¢â€ â€™ MCP `route_input` tool Ã¢â€ â€™ MCP domain tools (`add_entry`, `query_ledger`, `query_expense`, `get_todos`, `get_weight`, `search_notes`, `manage_persons`). People add/rename/delete in the Flask UI also call `manage_persons` through MCP instead of mutating SQLite directly.
 - 2026-05-02 Ã¢â‚¬â€ **Integrated the LLM/RAG hooks into MCP.** `search_notes` now owns retrieval + answer formatting behind the MCP boundary, and `route_input` can invoke the Qwen parser fallback for unresolved note shapes. Current runtime status: Qwen backend falls back to mock mode because no GGUF file / transformers backend is installed; RAG retrieval path is wired but returns the expected graceful message until `sentence-transformers` is installed and Notebook 4 populates the `embeddings` table.
 - 2026-05-02 Ã¢â‚¬â€ **Fixed the unsafe queryÃ¢â€ â€™todo failure mode and added expense-list queries.** Query-looking inputs that the router cannot map (example: `show me motivation quotes saved`) now return `unknown` instead of silently creating a todo. Expense queries can now return row lists from the bottom bar (`show me this month expense list`, `list the expense one by one`) instead of totals only. Verified with direct MCP smoke tests and Flask route tests against copied DB files.

- 2026-05-02 â€” **Shifted to a note-first runtime model.** Every input is now saved into `notes` first, then processed into structured facts and linked back with `source_note_id`. Added `pending_actions` for numbered clarification flows such as ambiguous settlements.
- 2026-05-02 â€” **General note search is now app-managed.** User-created notes are auto-embedded into the local vector store by the app itself. `general` note queries return the matched saved note text; `investment` / `health` still use retrieval + Qwen summarization.
- 2026-05-02 â€” **Native-ish dependency ownership is in place for the Python surface.** Added a project-local Python 3.14 `.venv`, downloaded `models/Qwen3-4B-Q4_K_M.gguf`, and moved embedding downloads/cache under `models/embedding_cache` instead of global user-cache paths.
- 2026-05-02 â€” **Verified real MCP end-to-end behavior against copied DBs.** Confirmed raw note save + lookup, natural-language ledger extraction (`ravi gave me 5k this month`), clarification options (`I gave back the amount`), and numbered resolution (`1` settles the selected person).
- 2026-05-02 â€” **Routing post-mortem from `logs.txt` and architecture decision: move from regex-only routing to a two-tier orchestrator with a memoized fast path.** Eight distinct routing failures cataloged (silent miscategorization of `jeevi weight 65.3` returning the old reading instead of saving the new one; `clear maddy ledger` and `settled maddy amount` becoming todos instead of triggering the settlement flow; explicit `TODO:` prefix being read as a query; user-created notes saved but never embedded so `vivekananda notes` returned "no indexed investment notes"; `list the expense one by one` returning a SUM instead of rows; `march month` and `who all owe me money...` saved as raw notes; the notes table polluted with what should have been queries). **Root cause: the router is keyword-based and brittle; intent classification fails before any tool gets called. MCP is fine â€” the routing decision *upstream* of MCP is the bug.** Decisions locked: (a) new module `second_brain_orchestrator.py` owns routing, MCP tools stay atomic; (b) Tier 0 deterministic grammar handles ~70% of inputs in <50ms, Tier 1 Qwen function-calling handles the rest in 2-4s on Pixel 7; (c) confidence threshold 0.7 â€” default-and-confirm above, ask-via-numbered-options below; (d) `user_routing_memory` table memoizes clarify resolutions so repeated inputs skip the LLM; (e) JSON failures recover via one retry then heuristic clarify menu, with "save as raw note" always available â€” **never lose user input**; (f) parse-readback toast format `âœ“ Saved weight: jeevi â†’ 65.3kg [parsed: write_weight Â· 0.92 Â· undo (3s)]`; (g) dynamic MCP tool creation rejected for v1 (Qwen 4B at 4-bit can't write safe code/SQL/tool specs reliably; bounded domain is well-served by ~14 atomic tools; revisit `query_freeform` sandboxed read-only SQL only if dogfooding shows recurring static-tool gaps); (h) Tier 0 rules tightened â€” `^todo[:\s]` always writes a todo, `<known_person> [weight] <num<150>` always writes weight, ambiguous settlement language is no longer routed to todo. Refactor sequence (6 steps) added to Next Action; each step ships independently and Tier 1 starts as a pass-through to existing `route_input` so the app keeps working through the refactor.
- 2026-05-02 â€” **Step 1 of orchestrator refactor shipped: Tier 0 grammar.** New `second_brain_orchestrator.py` module owns routing decisions; sits between any UI surface and the legacy `handle_input` MCP tool. Tier 0 implements four hard rules (person command, explicit todo with three forms including the `todo <verb>` no-colon form, weight write that ignores the `weight` keyword as a query trigger, settlement phrasings beyond `gave back the amount`). Inputs that don't match Tier 0 fall through to the existing pipeline via `process_text_sync` â€” preserves all current behavior for the ~30% of inputs Tier 0 won't classify. New `test_orchestrator_tier0.py`: 27/27 pass, including all of `jeevi weight 65.3` (was silently returning old reading), `TODO: update maddy ...` (was being read as query), `clear maddy ledger` / `settled maddy amount` (were creating polluting todos), and the negative cases `todo list pls` / `biscuit 20` / `jeevi 200` that must still fall through.
- 2026-05-02 â€” **Step 2 of orchestrator refactor shipped: `user_routing_memory` table + DAL.** Memoizes clarify resolutions so repeated inputs skip Tier 1. Schema added to `seed.sql` and to `ensure_runtime_schema` (existing DBs migrate automatically on app start). Three core helpers: `lookup_routing_memory` (returns memoized decision, side-effect: bumps hit_count and last_used), `upsert_routing_memory` (INSERT â€¦ ON CONFLICT DO UPDATE; supports overwriting args on duplicate key), `prune_routing_memory(days=90)` for periodic cleanup. Orchestrator's `handle()` now calls the lookup between Tier 0 and fallthrough; on hit returns `tier="memo"` with a placeholder dispatch (real dispatch lands in step 4). New `test_routing_memory.py`: 10/10 checks pass (schema, miss, roundtrip, hit_count bump, args overwrite, normalize_input collapsing, prune respecting age, orchestrator memo wiring, fallthrough preservation). Decision flagged: `lookup_routing_memory` mutates state (hit_count/last_used) during the read for call-site simplicity. Also flagged: `prune_routing_memory` not yet wired to Flask startup â€” deferred to step 3 since `app.py` is being touched there anyway.
- 2026-05-03 â€” **Step 3 shipped: Flask wired to orchestrator.** `app.py /note` now calls `orchestrate(text)` (orchestrator's `handle`) instead of `process_text_sync`. `activity_log` got a new `metadata_json` column (incremental migration via `_ensure_column`) carrying `{tier, confidence, rule, note_id}` per response. `templates/index.html` renders a small grey parse-readback line under each response: `[parsed: <rule> Â· conf <X.XX> Â· <tier> Â· <kind>]` â€” the trust-through-visibility surface from the design. `prune_routing_memory(days=90)` now runs once at app startup. Decision: JSON blob in `metadata_json` rather than separate columns â€” keeps the schema flat and avoids more migrations.
- 2026-05-03 â€” **Step 4 shipped: real Tier 1 routing with Qwen function-calling + legacy bridge.** `LLMService.route_input` added with strict JSON contract (one of `{tool, args, confidence}`, `{clarify, question, options}`, `{unknown}`); one retry on JSON failure with stricter prompt; mock backend handles the `logs.txt` failure patterns deterministically via the new `MOCK_ROUTE_RESPONSES` dict. Orchestrator's `_dispatch_tool` covers 13 tools (`add_expense/ledger/weight/todo/note`, `manage_person`, `query_ledger/expense/todos/weight/notes`, `prepare_settlement`). Confidence gate at 0.7: â‰¥0.7 executes, <0.7 routes to a numbered clarify menu persisted in `pending_actions` with `action_type="clarify_intent"`. Pending-action pre-check at the top of `handle()` resolves numbered replies (or `cancel`/`none`) to either the legacy settlement flow or the new clarify-intent flow â€” and clarify resolutions automatically `upsert_routing_memory` so repeated inputs skip the LLM. Heuristic clarify fallback when LLM returns unknown twice (always includes "Save as raw note" as the safety-net option). New `_try_legacy_rules` bridges to existing `build_query_or_command_plan` + `parse_note_for_write` so classic patterns (`petrol 500`, `Maddy balance`, `ravi gave me 5k`, etc.) keep working without depending on Qwen quality. Smart legacy ordering: when input has a number or is long prose without a question lead, prefer the write parser â€” fixes the "milk 60 routes to health search because 'milk' is a signal" and "vivekananda prose routes to investment search because 'anand' is a substring" failure modes. Multi-entry collapse: comma-split parts where any is a 'note' get merged into one free-form note write (commas were punctuation, not separators). New cross-domain `query_notes_result` (replaces hard-coded domain in legacy plan when bridging) so `vivekananda notes` finds the user's saved note regardless of what domain the legacy classifier guessed. **Never lose user input** invariant verified: every input ends as a saved row, a saved-as-note, or a pending clarify â€” never an error.
- 2026-05-03 â€” **Step 5 shipped: auto-embed user notes at write time.** Orchestrator's `add_note` tool dispatch (used by Tier 1 LLM, legacy-rules bridge, and clarify resolution) calls `store_note_embedding` immediately after creating the note row. Embedding linked to the note via `source_note_id`. Domain inferred via existing `infer_note_domain` if the LLM didn't provide one. Embedding-failure visibility: response shows " (search index not available)" suffix when the embedding backend can't load â€” user knows the note was saved but won't yet be searchable.
- 2026-05-03 â€” **Step 6 shipped: regression test against `logs.txt` â€” all green.** New `test_logs_regression.py` runs 14 assertions against the eight failure patterns from real dogfooding, plus three follow-ups (clarify resolution writes to memory, memoized input routes via tier=memo, monthly expense returns query). Uses a temp DB copy + a Python-only mock LLM (driven by `MOCK_ROUTE_RESPONSES`) + a deterministic 26-dim letter-frequency embedding so the test runs without loading Qwen GGUF or sentence-transformers. **All 14 checks pass.** Combined test status across the suite: Tier 0 = 27/27, routing memory = 10/10, logs regression = 14/14. Files added today: `test_logs_regression.py`. Files changed today: `app.py`, `templates/index.html`, `seed.sql`, `second_brain_core.py`, `second_brain_orchestrator.py`, `test_orchestrator_tier0.py`, `test_routing_memory.py`. The eight original `logs.txt` failure modes are all closed.
- 2026-05-03 â€” **Product expectations clarified; latency bottleneck identified.** Product contract is now explicit: this is a general note-taking app first, with expense / ledger / weight / todo as special capabilities layered on top. Arbitrary text defaults to a normal note; note retrieval searches across all saved notes by default; ideal note-query output is a short synthesized answer followed by original snippets, with raw snippets alone acceptable if latency/reliability wins. A few simple prefixes like `todo:` / `note:` are acceptable; plain natural language remains primary. Clarification threshold remains `<0.7`. Search indexing may happen a few seconds after save if reliability stays high. Hard user-visible latency budget: 5-10s max. Measured on the current Python runtime: warm embedding retrieval is fast (roughly 30ms query after model warm-up), but real Qwen CPU routing is not (roughly 81s first route, 52s second route in-process with `SECOND_BRAIN_USE_REAL_LLM=1`). Conclusion for the next iteration: fix the LLM hot path first and add per-stage timing instrumentation before further routing changes.
- 2026-05-03 â€” **Latency instrumentation shipped end-to-end.** Added shared `perf_timer` timing hooks in `second_brain_core.py`, threaded timings through the orchestrator hot path, note indexing, note retrieval, embedding load/encode, and LLM route/summarize calls. `OrchestratorResponse` now carries `timings_ms`; Flask stores those timings in `activity_log.metadata_json`; `templates/index.html` and `templates/activity.html` now render a compact `[time: ...]` line under each response. Regression tests were updated to use stable DB copies under the repo's `.tmp` directory instead of Python-created temp subdirectories (sandbox-safe) and still pass: Tier 0 = 27/27, routing memory = all pass, logs regression = all pass. **Measured baselines with the new timings:** note query with mock LLM + cold embedding load is ~8.97s total, dominated by `query_notes.query_embedding.model_load_ms` (~8.93s); the second warm query is ~27ms total, dominated by `query_notes.query_embedding.encode_ms` (~19ms). With `SECOND_BRAIN_USE_REAL_LLM=1`, `any info of vivekananda in our notes` is ~93.7s total: `llm_route.total_ms` ~84.6s (46.6s first JSON attempt + 35.4s retry), then cold embedding model load ~9.0s. This confirms the hot-path problem precisely: real Qwen routing and first-time embedding model load are the two dominant cold-start costs.
- 2026-05-03 â€” **Generalized routing direction clarified further.** `note:` is now a hard plain-note directive; `todo:` is now a hard todo directive and should expand list-shaped content into multiple todos when clear. Complex read queries should not be solved by adding hundreds of phrase-specific regex/rule branches; instead, the preferred direction is minimal deterministic rules for obvious writes/simple reads plus **LLM-assisted safe read-only SQL/query plans** for harder expense / weight / ledger questions. Note-query phrasings like `X notes`, `any mention of X`, `any info on X`, and `find X in my notes` are all the same user intent. Synthesis should happen only after relevant retrieval hits exist. Legacy investment/health heuristics are now explicitly out of contract for the active hot path and should be removed.
- 2026-05-03 â€” **Generalized routing fixes shipped against that clarified contract.** The active hot path now treats `note:` as a hard plain-note save and `todo:` as a hard todo save, including expansion of clearly list-shaped `todo:` bodies into multiple todo rows. Legacy note-query planning is now wired end-to-end for the newer `query_notes` call shape, so inputs like `vivekananda notes`, `any mention of mcp in the notes`, and `show me last 5 notes` no longer fall through into note/expense writes. Query-like note retrieval requests are guarded before numeric write parsing, which prevents cases like `show me last 5 notes` from being coerced into an expense. Weight-history phrasing such as `last 3 jeevi weight` is preserved as a query instead of becoming a bogus `3.0kg` write. Comma-separated numeric input still defaults to multi-expense write unless strong query markers are present. Old note-domain heuristics were also removed from the active write path by forcing plain-note saves to `general`. Regression coverage expanded accordingly: `test_orchestrator_tier0.py` now passes **31/31**, `test_logs_regression.py` now passes **20 checks**, and `test_routing_memory.py` still passes in full.
- 2026-05-03 â€” **Latency hot path reduced further: deterministic query fast-path + startup warmup shipped.** The orchestrator now has a pre-LLM deterministic query lane between `user_routing_memory` and Tier 1 Qwen. High-confidence structured/note queries (`balance`, `expense`, `todo list`, weight-history phrasing, and normalized note-search phrasing like `vivekananda notes` / `show me last 5 notes`) dispatch directly without ever calling `route_input`, which removes the 50-90s Qwen router from the normal note-query path. Added thread-safe singleton loading for both `LLMService` and `EmbeddingService`, plus `warm_runtime_services()` and Flask startup warmup so the app can load the embedding model and LLM backend once per process instead of making the first user query pay every cold-load cost. **Measured with `SECOND_BRAIN_USE_REAL_LLM=1`:** `show me last 5 notes` now runs in about **18.7ms** end-to-end and stays on `tier=fastpath`; `any info of vivekananda in our notes` also stays on `tier=fastpath`, so the previous ~84s `llm_route.total_ms` cost is gone. Without warmup, the first semantic note query is still slow (~34.9s) because it pays cold embedding load (~22.8s) plus first summary generation (~11.9s). With startup warmup, the same first semantic note query drops to about **5.7s** end-to-end; the remaining cost is almost entirely `llm_summary.generate_ms` for the synthesized answer, not routing or embeddings. Summary token budget was also reduced to keep note answers short and closer to the product contract. This does **not** fully solve every cold-start case yet, but it moves normal note retrieval from "unusable" to "within the current hard budget" on the first warmed query.
- 2026-05-03 â€” **Data-model direction changed: split real notes from raw structured captures.** After reviewing the current live behavior, the product now explicitly rejects the current leakage where structured-source inputs are stored in `notes` and then show up in the user-facing Notes experience. Current reality documented: semantic retrieval is driven by the `embeddings` table, which is populated from actual note-save paths, while structured queries still come from SQL on `expenses` / `ledger` / `weights` / `todos`. Accepted direction: `notes` becomes real editable user notes only; structured-origin raw input moves to a separate immutable capture/event layer; `activity_log` remains the UI-facing history feed; structured rows link to captures, not notes; embeddings are built from user notes only. This was accepted specifically to support proper CRUD screens for expenses / ledger / weights / todos plus a real editable Notes UI without internal-capture confusion.
- 2026-05-03 - **Flask CRUD and partial split-model implementation shipped.** `app.py` now exposes real management flows for all major surfaces: `/notes` is a plain-text note editor with multiline add, in-place edit, delete, and embedding refresh; `/expenses`, `/ledger`, `/weights`, and `/todos` now support direct add from their own pages, individual delete, and `Clear all`; Todos also keep toggle-done/reopen. New page-based structured writes use the new `captures` table and attach `source_capture_id` instead of creating user-note rows, while delete/clear flows clean up orphan captures and legacy `source_note_id` note rows when safe. Compatibility fix: weight recognition now derives tracked names from actual weight history as well as the People list, so Tier 0 weight writes and fast-path weight-history queries still work even when the `persons` table is empty in the live DB. Schema alignment also landed in `seed.sql`. Validation status after this pass: `test_flask_crud.py` passes in full, and the existing regressions remain green (`test_orchestrator_tier0.py` 31/31, `test_logs_regression.py` all pass, `test_routing_memory.py` all pass).
- 2026-05-03 â€” **Activity log diagnosis: most queries were misrouting.** Reviewed 25+ live entries. Eight failure modes catalogued: `latest note` / `last note` / `vivekananda note` (singular) silently saved as plain notes because `extract_note_query_args` only recognized the plural `notes`; `weight status` / `expense status` saved as notes (no rule for the "status" pattern); `maddy ledger` / `ravi ledger` / `all ledger` saved as notes (`ledger` not in the ledger trigger list); `how much money i owe` searched notes instead of returning ledger because the ledger branch fell through when no person name matched; `show all notes` did a semantic search for the literal word "all"; `last 3 expense` / `last 5 expense` returned all-time SUMs instead of row lists; `last 3 bills` got eaten by the write parser as a `Rs.3 last bills` expense. Root cause: deterministic phrase-by-phrase routing canâ€™t cover the combinatorial space of natural query phrasings. Decision (matching locked clarification #19): move complex reads to LLM-assisted safe read-only SQL + LLM-driven note retrieval, keep Tier 0 only for unambiguous *writes*, and gate everything LLM-generated through a hard safety layer.
- 2026-05-03 â€” **LLM-as-planner path shipped end-to-end with safety gate, full test coverage.** New `sql_safety.py` parses every LLM-generated SQL statement with `sqlglot` (SQLite dialect) and rejects anything that isn't a SELECT/UNION/WITH against the allowlisted tables `{expenses, ledger, ledger_balance, weights, todos, persons}` â€” no DDL/PRAGMA/ATTACH/Transaction, no schema-qualified refs, no semicolons inside the body, CTE aliases exempted, statement timeout via `set_progress_handler`, row cap at 100, params type-checked. New `query_sql_result` in `second_brain_core.py` and a matching `query_sql` MCP tool route every read through that gate. New `LLMService.plan_query` (Qwen function-calling shape) emits one of `{action: sql_query | note_query | clarify | unknown}`; the prompt embeds the schema and a few-shot block; `MOCK_PLAN_RESPONSES` covers every misroute from the activity log so tests run without GGUF. Relative-date sentinels (`__LAST_MONTH__`, `__CURRENT_MONTH__`) are expanded at execution time by `resolve_plan_relative_dates`, so memoized plans stay correct across month boundaries. Orchestrator change: a new `_try_plan_query` step sits between the (tightened) fastpath and the existing Tier 1 write router; the fastpath now has a defer list so inputs it historically got wrong (`last N expense`, `latest/recent expense/bills`, `how much...`, `<X> status`, `all|every notes/expense/ledger`, `<person> ledger`, `apart from`, `except|excluding`, singular `latest/last note`, `<word> note`) skip straight to the planner. Faithful note synthesis added too: `LLMService.synthesize_notes` runs only when the top embedding hit clears a 0.35 cosine threshold, and the response is `<synth answer>\n\nSources:\n<snippets>` per the locked product contract; below threshold we return snippets-only (the accepted fallback). Test status: `test_sql_safety.py` 40/40, `test_orchestrator_tier0.py` 31/31, `test_routing_memory.py` all pass, `test_logs_regression.py` all pass, `test_flask_crud.py` all pass, new `test_activity_log_regression.py` 19/19 (every input from the activity log now routes correctly). Files added: `sql_safety.py`, `test_sql_safety.py`, `test_activity_log_regression.py`. Files changed: `second_brain_core.py`, `second_brain_orchestrator.py`, `second_brain_mcp_server.py`, `requirements.txt`, plus `plan_query` / `synthesize_notes` shims in the existing test stubs. Real LLM is still gated behind `SECOND_BRAIN_USE_REAL_LLM=1`; mock path now covers every dogfooded input deterministically, so flipping the env var on is the next dogfooding step.
- 2026-05-03 â€” **Read/write membrane + hybrid note retrieval shipped.** Two architectural fixes landed in the live orchestrator/runtime. First, query-shaped read intent is now protected by a hard membrane in `second_brain_orchestrator.py`: if an input looks like a read, Tier 1 / legacy / memo fallback can no longer silently execute `add_note` / `add_expense` / `add_ledger` / `add_todo`; unresolved reads now end in a non-mutating clarification instead. This specifically closes the dangerous class of failures where `did i ever save a note on X`, `ledger history for maddy`, or `last 4 expenses` could create new data. Second, `query_notes_result` in `second_brain_core.py` now uses hybrid note retrieval over real user notes: lexical evidence (exact phrase / exact token / fuzzy token / trigram overlap) is combined with embedding similarity, and the query now **abstains** with `No notes matched ...` when evidence is weak instead of forcing an unrelated semantic hit. The note-query parser was also broadened for real read phrasings (`did i ever save a note on X`, `show every note that mentions X`, singular short-form note queries) without reopening the earlier long-prose misroute. Post-change validation: `test_activity_log_regression.py` **25/25**, `test_logs_regression.py` all pass with new read-only checks, `test_orchestrator_tier0.py` **31/31**, `test_routing_memory.py` all pass, `test_sql_safety.py` **40/40**, `test_flask_crud.py` all pass. Post-change stress reruns moved materially: `test_replay_matrix_full_throttle.py` now reports generated expected-kind pass **400/400** with triage **398 ok / 2 scope-decision-needed** and **no non-ignorable cases**; `expense_query` is now **62/62**, `ledger_query` **10/10**, and `note_query` **210/210** on kind-pass. Remaining scope cases in that 500-case run are typo-heavy `mpc notes` / `find mpc in my notes`. `test_note_corpus_stress_200.py` rerun stayed at **199/200** note writes and **199/200** embeddings, with **176/180** token-hit on comparable note queries; the remaining misses are still typo-heavy retrievals such as `astronamy`, `nutrishun`, and `phliosophy`.
- 2026-05-03 â€” **Notes UI simplified; top bar and drawer behavior improved.** The Flask chrome now keeps the top bar **sticky** so the hamburger menu stays reachable while scrolling. The offcanvas drawer now highlights the **current page**, including `Notes`, so the active section is visible at a glance. The `/notes` surface was simplified from "every note is an open textarea with its own save button" to a cleaner **list + single active editor** model: a note list with previews on one side, one selected note open for editing, and a separate composer for new notes. This reduces visual clutter without changing note storage semantics. Validation after the UI refactor: `test_flask_crud.py` still passes in full.
- 2026-05-04 â€” **Read/write membrane hardened, audit-note bloat eliminated, journal-question UX added (4-fix sweep).** Independent 510-case probe (`test_independent_500.py`) had revealed: 13% of inputs silently created unintended `notes` rows when natural-language note retrievals fell through to the legacy bridge; 40% of inputs were creating audit-trail notes nobody read; long prose with stray numbers was getting eaten by the expense parser; first-person reflective questions had no path to becoming saved journal entries. Fixes shipped: (1) **Tightened `_looks_like_protected_read_intent`**: added `_RETRIEVAL_VERB_PATTERNS` covering past-tense self-reference (wrote/jotted/saved/noted/mentioned/said), `the note about X` / `the X note`, `anything about/saved/wrote`, `everything X has said`, `look up X` / `tell me about X` / `give me my X` / `dump my X` etc., `things X told me`, `conversations with X`, `X's view on Y`, `X advice/recommendation`, existence/negation phrasings, and aggregation tokens (biggest/smallest/average/cumulative/top N). New patterns are gated on `word_count <= 12` so long prose containing the word "average" or "noted" doesn't get misclassified as a query. (2) **Fixed expense parser greediness**: in `_try_legacy_rules`, single-entry expense classifications are downgraded to `add_note` when the input has no currency token (Rs/â‚¹/$/k/L/comma-grouped) AND word count > 4. Catches "milk delivery was 30 mins late today", "meditation streak broken at day 12". (3) **Removed audit-trail notes from query/clarify/planner paths**: `_dispatch_tool` query branches, `_try_plan_query`, `_build_read_barrier_response`, and `_tier1_route` clarify/unknown/low-confidence paths no longer write rows to `notes`. Real notes (`add_note`) and settlement/person-command audit (rare) still create note rows. New `_purge_audit_notes` migration in `ensure_runtime_schema` deletes orphan `structured_type IN ('query','clarify')` rows from existing DBs. `OrchestratorResponse.note_id` is now None for read-only paths; `_persist_clarify` and `_build_heuristic_clarify` accept `note_id=None`. (4) **Journal-question affordance**: new `_looks_like_journal_question` detects first-person reflective questions ("why does cipla keep going up?", "should i sell idfc?", "is meditation worth the time cost?"); when `_build_read_barrier_response` sees one, it offers a clarify menu with `Save as a journal note` as the primary option instead of the generic "looks like a query" message. Two follow-on tightening passes: capped fastpath query plans at `word_count <= 12` so long prose stops drifting into `query_notes`; long-prose default at `_try_legacy_rules` fallthrough now saves as note rather than calling `_dispatch_legacy_plan`; `remind me what i said about X` is no longer accepted as a Tier 0 todo (query-shaped remainder check). Stale assertions in `test_logs_regression.py` that were checking for the now-deleted audit rows were updated to verify behavior (no notes growth) instead of implementation. **Outcome on the 510-case probe**: ok-rate **83% â†’ 97%** (+14pp), real-danger **64 â†’ 7** (â€“89%), audit-only growth **205 â†’ 0** (eliminated), kind-mismatch **82 â†’ 14**, broken/empty/exception **0** (unchanged). Latency p50 13.2 ms, p95 134.8 ms, p99 177.1 ms, max 722 ms (long-form note write embedding). Test status: orchestrator-tier0 31/31, routing-memory all, logs-regression all, activity-log-regression 25/25, flask-crud all, sql-safety 40/40. Remaining 7 dangerous cases are: 3 adversarial inputs that get safely stored as notes (acceptable â€” parameterized SQL prevents execution), 2 date-phrasing edge cases (`ledger from december 2025`, `weight from last sunday`), 1 ambiguous noun-phrase (`dosa batter ratio`), and 1 person-specific phrase (`pr sundar position sizing rule`). Files changed: `second_brain_orchestrator.py`, `second_brain_core.py`, `test_logs_regression.py`. Files added: `test_independent_500.py`, `artifacts/independent_500/{results,analysis}.json`, `artifacts/independent_500/analyze.py`.
- 2026-05-04 â€” **Split-model refactor completed across orchestrator hot path.** Closed the long-running gap where Home/chat structured writes still went note-first while page-based CRUD already used `captures`. The four orchestrator structured-write paths â€” Tier 0 `_execute_write_entry`, Tier 0/legacy multi-entry `_execute_write_entries`, Tier 1 `_dispatch_tool` (`add_expense` / `add_ledger` / `add_weight` / `add_todo`), and the legacy-bridge multi-entry caller â€” now create a `captures` row instead of a `notes` row and link the structured fact via `source_capture_id`. Real user notes (`add_note`, `note:` prefix, `/notes` page) and audit/clarify rows (planner, read-barrier, low-confidence pending, query trace) keep their existing `notes` rows so `pending_actions.note_id` and `OrchestratorResponse.note_id` semantics are preserved. `OrchestratorResponse` got a `capture_id` field alongside `note_id` so activity-log metadata can record which layer owns the row. New idempotent migration `_migrate_structured_notes_to_captures` runs inside `ensure_runtime_schema`: for every legacy structured row pointing at `notes`, it creates the matching capture, repoints `source_capture_id`, NULLs `source_note_id`, and deletes the orphan note row only when its `structured_type` is not `'note'` and no other structured table still references it. Removed `_cleanup_orphan_legacy_note` and the `source_note_id` plumbing from page CRUD since the migration runs at startup and structured rows no longer link back to `notes`. End-to-end smoke (`petrol 500`, `gave maddy 5k`, `jeevi 65.3`, `todo: buy milk`): notes table delta = 0, captures table delta = 4, every new structured row has `source_capture_id` set and `source_note_id` NULL. Test status after the change: `test_orchestrator_tier0.py` 31/31, `test_routing_memory.py` all pass, `test_logs_regression.py` all pass, `test_activity_log_regression.py` 25/25, `test_flask_crud.py` all pass, `test_sql_safety.py` 40/40 â€” no test changes were needed. Files changed: `second_brain_orchestrator.py`, `second_brain_core.py`, `app.py`, `project_development.md`.

## Refactor Progress (Orchestrator Track)

**Goal:** replace the regex-only router with a two-tier orchestrator + memoized fast path, so the routing failures captured in `logs.txt` stop happening. Each step is independently shippable; the app must keep working between steps.

### âœ… Step 1 â€” Create `second_brain_orchestrator.py` with Tier 0 grammar â€” **DONE**

**What it does:** Pre-routes every user input. Tier 0 deterministic rules catch unambiguous patterns (~70% of real inputs). Anything not matched falls through to the existing legacy `handle_input` MCP tool via `process_text_sync`, so non-Tier-0 inputs keep working the way they do today.

**Files added/changed:**
- `second_brain_orchestrator.py` (new, ~280 lines) â€” `OrchestratorResponse` dataclass, `normalize_input`, Tier 0 predicates (`_try_explicit_todo`, `_try_weight_write`, `_try_settlement`), executors that save the raw note + run `add_entry_result` / `manage_persons_result` / `prepare_ledger_settlement_result`, public `handle()` entry point with injectable `fallthrough` for testability.
- `test_orchestrator_tier0.py` (new) â€” 27-case smoke test against actual `logs.txt` failures + edge cases. Uses a temp DB copy and a stub fallthrough so no MCP server is needed.

**Tier 0 rules implemented (first match wins):**
1. Person command â€” `^(ADD|REMOVE|MODIFY)_PERSON: ...` (case-insensitive). Reuses existing `parse_person_command`.
2. Explicit todo â€” three forms:
   - `^todo: ...` / `^task: ...` (colon form, always writes)
   - `^todo <verb> ...` where `<verb>` is in `TODO_START_VERBS` (no colon, but action verb)
   - `^remind me [to] ...`
3. Weight write â€” `^<known_person> [weight] <num> [kg] [optional note]` where person is in `persons` table and `0 < num < 150`. The optional `weight` keyword does **not** force a query route (closes the `jeevi weight 65.3` silent-failure bug).
4. Settlement phrasings â€” adds `clear <person> ledger`, `settle(d) <person> (amount|balance|ledger)`, `<person> settle(d) (amount|balance|ledger)`, `wrote off <person>` on top of the existing `looks_like_settlement_followup`. All trigger the numbered settlement clarification (the same flow as `I gave back the amount` already does).

**Test results:** 27/27 cases pass. Bugs from `logs.txt` that this fixes: `jeevi weight 65.3`, `murugan weight 65.3`, `prani weight 11`, `TODO: update maddy ...`, `todo: update maddy ...`, `todo update maddy ...`, `clear maddy ledger`, `settled maddy amount`, `maddy settled amount`. Bugs deliberately deferred to step 4 (Tier 1 LLM): `march month`, `who all owe me money...`, `vivekananda notes`, `list the expense one by one`.

---

### âœ… Step 2 â€” Add `user_routing_memory` table + DAL â€” **DONE**

**What it does:** Memoizes routing decisions keyed by normalized user input. Sits between Tier 0 and Tier 1 in `handle()`; on a hit, the LLM is skipped entirely. Populated by Tier 1 clarify resolutions (wired in step 4); empty for now, so always misses, but the wiring is in place.

**Files added/changed:**
- `seed.sql` â€” new `user_routing_memory` table (id, input_pattern UNIQUE, resolved_tool, resolved_args_json, hit_count, last_used, created_at) + index on input_pattern. DROP added at the top so re-runs are clean.
- `second_brain_core.py` â€” `ensure_runtime_schema` extended with `CREATE TABLE IF NOT EXISTS user_routing_memory` so existing DBs migrate on app start. Three new helpers:
  - `lookup_routing_memory(conn, normalized_pattern)` â€” returns `{tool, args, hit_count}` or None. Side-effect: bumps `hit_count` and `last_used` on hit.
  - `upsert_routing_memory(conn, normalized_pattern, tool, args)` â€” INSERT â€¦ ON CONFLICT DO UPDATE; bumps hit_count on duplicate.
  - `prune_routing_memory(conn, days=90)` â€” deletes rows with `last_used < now - days`.
- `second_brain_orchestrator.py` â€” `handle()` now calls `lookup_routing_memory` after Tier 0 misses. On hit returns `tier="memo"` with a placeholder dispatch message (real dispatch lands in step 4 with Qwen).
- `test_orchestrator_tier0.py` â€” calls `ensure_runtime_schema(tmp_db)` so the test DB has the new table.
- `test_routing_memory.py` (new) â€” 10-check suite: schema columns present, empty table â†’ miss, upsert+lookup roundtrip, hit_count bumps, args overwrite on duplicate key, normalize_input collapses whitespace + lowercases, prune respects age, recent entry survives prune, orchestrator returns `tier=memo` on hit, non-memoized non-Tier-0 falls through.

**Test results:** Tier 0 = 27/27, routing memory = 10/10.

**Decision flagged for review:** `lookup_routing_memory` increments `hit_count` and `last_used` *during* the read (single SQL UPDATE). If a pure-read variant with explicit hit recording is preferred, split it later.

**Deferred to step 3:** wiring `prune_routing_memory` into Flask startup. Belongs alongside `ensure_activity_log_schema` in `app.py`; will land in step 3 since that file is already being touched there.

---

### âœ… Step 3 â€” Wire Flask `/note` to the orchestrator â€” **DONE**

**Goal:** Make the orchestrator the live routing path for the Flask app. The app's user-visible behavior changes for the first time â€” Tier 0 fixes from steps 1-2 start being live.

**Tasks:**
1. **Edit `app.py` `note()` route** â€” replace `process_text_sync(text)` with `handle(text)` from `second_brain_orchestrator`. Map `OrchestratorResponse` to the existing `{kind, response_text}` shape used by `log_activity`.
2. **Run `prune_routing_memory` at startup** â€” call once after `ensure_activity_log_schema(DB_PATH)` in `app.py`'s `if __name__ == "__main__"` block.
3. **Update `templates/index.html`** â€” render the two-line parse-readback toast format from `OrchestratorResponse.parsed`:
   ```
   âœ“ Saved weight: jeevi â†’ 65.3kg
     [parsed: write_weight Â· conf 0.92 Â· tier0]
   ```
   Confidence shows for tier1 routing; tier0 shows "tier0" as the marker. The second line is small/grey.
4. **Persist tier + confidence in `activity_log`** â€” add `tier` and `confidence` columns (or stash them in a new `metadata_json` column). Decide: schema bump vs. JSON blob. Lean toward JSON blob to avoid more columns.
5. **Smoke test the live Flask app** â€” start `python app.py`, hit each Tier 0 case from `logs.txt` in browser, verify parse readback shows + correct DB rows are written. Document any UI rendering issues.

**Files touched:** `app.py`, `templates/index.html`, possibly `templates/activity.html` if the activity log shows the new metadata, possibly `seed.sql` + `ensure_runtime_schema` if columns are added.

**Risks:** `OrchestratorResponse` shape doesn't 1:1 match the legacy `process_text_sync` return shape â€” the kind values differ slightly (`memo` is new; `clarification` vs `clarify`). Need to standardize before Flask renders.

---

### âœ… Step 4 â€” Replace Tier 1 pass-through with real Qwen function-calling â€” **DONE**

**Goal:** The biggest user-visible win. Catches the 30% of inputs Tier 0 can't handle: `march month`, `who all owe me money`, `list the expense one by one`, novel phrasings. Also closes the loop by populating `user_routing_memory` on every clarify resolution.

**Tasks:**
1. **Define MCP tool schemas in a Qwen-friendly form** â€” for each of the 13 atomic tools (`add_expense`, `add_ledger`, `add_weight`, `add_todo`, `add_note`, `mark_todo_done`, `settle_ledger`, `manage_person`, `query_ledger`, `query_expense`, `query_todos`, `query_weight`, `query_notes`), write a JSON-schema-style description with name, description, params. Live in `second_brain_orchestrator.py` or a new `tool_schemas.py`.
2. **Build the Tier 1 prompt** â€” strict instructions: "return JSON only, no prose. Output one of: `{tool, args, confidence}` / `{clarify, question, options}` / `{unknown}`." Include the user input + tool list + a few-shot block of canonical examples (one expense, one ledger, one query, one note, one ambiguous â†’ clarify).
3. **Wire the LLM call** â€” extend `LLMService` (in `second_brain_core.py`) with a `route_input(text, tools)` method. Uses existing backend selection (llama-cpp-python â†’ transformers â†’ mock). For mock mode, hand-code routing for the eight failure patterns from `logs.txt` so we can test without GGUF.
4. **JSON parsing + retry** â€” parse the response with `extract_json` + `json.loads`. On `JSONDecodeError`, retry once with a stricter system message. On second failure, build a heuristic clarify menu (number â†’ expense/weight/ledger; question shape â†’ query; long prose â†’ note; last option always "Save as raw note").
5. **Tool dispatcher** â€” given `{tool, args}`, call the right MCP tool via `call_tool_sync` (atomic boundary). For `clarify_with_user`, persist the pending choice via `create_pending_action` (action_type=`clarify_intent`).
6. **Confidence gate** â€” `confidence â‰¥ 0.7` â†’ execute + parse readback; `< 0.7` â†’ upgrade to clarify_with_user. The threshold is the locked design value.
7. **`clarify_intent` resolution** â€” extend `resolve_pending_action_result` to handle the new `clarify_intent` action type. On numbered reply, dispatch the chosen tool AND `upsert_routing_memory(normalize_input(original_text), tool, args)`.
8. **Replace orchestrator fallthrough** â€” `handle()` no longer calls `process_text_sync`; it calls `tier1_route(text)` which does steps 2-7 above.
9. **Tests** â€” extend `test_orchestrator_tier0.py` (or new `test_orchestrator_tier1.py`) with mock-LLM cases for the deferred failure patterns. Real Qwen path tested manually.

**Files touched:** `second_brain_orchestrator.py` (major), `second_brain_core.py` (LLMService.route_input + clarify_intent resolver), possibly new `tool_schemas.py`.

**Latency budget on Pixel 7:** target 2-4s for Tier 1 routing. If Qwen 4B at 4-bit is slower, profile before optimizing â€” the user's 95% target trumps speed.

**Risks:** Qwen JSON reliability is the big unknown. Mock mode lets us prove the orchestration logic; real-Qwen tuning is dogfooding work.

---

### âœ… Step 5 â€” Auto-embed user notes at write time â€” **DONE**

**Goal:** Fix the `vivekananda notes` not-retrievable failure. Currently user notes save into `notes` but nothing populates `embeddings`, so semantic search has nothing to match.

**Tasks:**
1. **In the orchestrator's note-write path** â€” after `create_note_record` for an `add_note` action, call `store_note_embedding(conn, embedding_service, note_id, content, domain)` (already exists in `second_brain_core.py`).
2. **Domain inference** â€” current implementation reuses `infer_note_domain(text)`, but this is now a transitional internal detail only. Product behavior should treat user notes as one shared searchable pool.
3. **Latency** â€” MiniLM ONNX runs ~80ms on Pixel 7. If synchronous note indexing hurts UX, move to a write-then-embed background task; user already accepted a short delay before a new note becomes searchable.
4. **Long-note chunking (deferred)** â€” for v1, embed the whole note as one chunk. Chunked embedding (200-token chunks per note, each linked back via `source_note_id`) is a future improvement.
5. **Test** â€” write a free-form note (`vivekananda died of exhaustion not meditation`), then immediately query it (`vivekananda notes`), verify `query_notes` returns the saved chunk text.

**Files touched:** `second_brain_orchestrator.py` (note-write path), possibly `second_brain_core.py` (chunking helper if added).

---

### âœ… Step 7 â€” LLM planner with safe read-only SQL â€” **DONE (2026-05-03)**

**What it does:** Replaces the long tail of phrase-specific deterministic query rules with an LLM planner that emits either read-only SQL (validated against an AST allowlist) or a note search. Only deterministic shortcuts that we know are correct (`<person> balance`, `who owes`, `who do i owe`, `pending todos`, `this month expense`, `last N <person> weight`, `show me last N notes`) stay in the fastpath; everything else goes to the planner. Closes the misroutes catalogued from the live activity log.

**Files added/changed:**
- `sql_safety.py` (new) â€” `validate_sql` (sqlglot-backed AST gate), `execute_safe` (mode=ro conn + row cap + timeout via `set_progress_handler`), `format_rows` (deterministic text rendering).
- `second_brain_core.py` â€” `query_sql_result`, `LLMService.plan_query`, `LLMService.synthesize_notes`, `_validate_plan_response`, `resolve_plan_relative_dates`, `MOCK_PLAN_RESPONSES`, `QWEN_PLAN_PROMPT`, `QWEN_NOTE_SYNTH_PROMPT`. Faithful synth path added to `query_notes_result` (cosine threshold + snippets).
- `second_brain_orchestrator.py` â€” `_FASTPATH_DEFER_PATTERNS`, `_try_plan_query`, planner wired between fastpath and Tier 1 in `handle()`.
- `second_brain_mcp_server.py` â€” `query_sql` MCP tool surface.
- `test_sql_safety.py` (new) â€” 40 adversarial cases.
- `test_activity_log_regression.py` (new) â€” 19 cases across every misroute observed live.
- Existing test stubs got `plan_query` and `synthesize_notes` shims.

**Test results:** `test_sql_safety.py` 40/40, `test_orchestrator_tier0.py` 31/31, `test_routing_memory.py` all pass, `test_logs_regression.py` all pass, `test_activity_log_regression.py` 19/19, `test_flask_crud.py` all pass.

**Latency note:** Mock backend keeps planner cost in the milliseconds. Real Qwen backend still costs 5â€“10s per cold plan call on CPU; `user_routing_memory` memoization is the mitigation, and any input that contains a relative-date token (`last month`, etc.) is currently re-planned rather than memoized.

---

### âœ… Step 6 â€” Regression test against `logs.txt` â€” **DONE**

**Goal:** Prove the eight failure patterns from real dogfooding now route correctly. Catch any new regressions introduced by the refactor.

**Tasks:**
1. **Build a regression harness** â€” `test_logs_regression.py`. Reads each unique input from `logs.txt`, runs through `handle()` against a temp DB copy, asserts the resulting `kind` and one feature of the response (e.g., for a weight write: `weights` table has a new row with the parsed value).
2. **Required passes:**
   - `jeevi weight 65.3` â†’ write_weight, weights row inserted
   - `TODO: update maddy ...` â†’ write, todos row inserted
   - `clear maddy ledger` / `settled maddy amount` â†’ clarification, pending_actions row created
   - `vivekananda notes` (after writing the note) â†’ query, returns matched text
   - `list the expense one by one` â†’ query, returns row list (not sum)
   - `march month` â†’ either clarify or correctly inferred as expense query
   - `who all owe me money...` â†’ query_ledger(who_owes)
3. **Tolerance** â€” target 7/8 passing. Document any remaining gaps as known limitations in this file.

**Files added:** `test_logs_regression.py`.

---

## Post-orchestrator backlog (deferred)

- **Undo toast UX** â€” Step 3 renders the parse readback; the actual undo button + 3s window comes later.
- **Latency optimization** â€” instrumentation is now live; next step is to redesign the note-query hot path using those timings so normal note retrieval avoids the current cold-start penalties.
- **Dashboard/list pages reading via MCP** â€” currently read SQLite directly; should go through MCP read tools for Android parity.
- **Reference corpus cleanup** â€” Notebook 4's old investment/health-specific corpus assumptions need to be folded into the new all-notes retrieval model or explicitly retired. Product behavior is no longer domain-segregated.
- **ONNX embedding runtime for Android** â€” Python uses `sentence-transformers`; Android needs ONNX MiniLM via JNI. Out of scope until Android port begins.
- ~~**Safe read-only SQL layer**~~ â€” **shipped 2026-05-03** as `sql_safety.py` + the `query_sql` MCP tool + `LLMService.plan_query`. See refactor Step 7.
- ~~**Split notes from captures across orchestrator**~~ â€” **shipped 2026-05-04**. Structured-fact writes from Home/Tier 0/Tier 1/legacy bridge all go through `captures`; `notes` is for real user notes only.
- ~~**Audit-trail note bloat**~~ â€” **shipped 2026-05-04**. Query/clarify/planner paths no longer create `notes` rows; `_purge_audit_notes` migration cleans existing DBs at startup.
- ~~**Read/write membrane gaps on natural-language note retrieval**~~ â€” **shipped 2026-05-04**. `_RETRIEVAL_VERB_PATTERNS` covers past-tense self-reference, "the X note", "anything saved", "everything X said", "look up / give me my", existence checks, and aggregation tokens (gated to `word_count <= 12`).
- ~~**Expense parser eating prose**~~ â€” **shipped 2026-05-04**. Single-entry expense classifications are downgraded to `add_note` when there's no currency token AND `word_count > 4`.
- ~~**Journal-question UX**~~ â€” **shipped 2026-05-04**. First-person reflective questions hitting the read barrier now get a clarify menu offering "Save as a journal note" instead of a generic "looks like a query" message.
- **Real-LLM planner dogfooding** â€” mock plan path covers every activity-log input; the next step is flipping `SECOND_BRAIN_USE_REAL_LLM=1` and shadow-logging divergences between mock and Qwen plans before relying on real Qwen for new phrasings.
- **Schema introspection in the planner prompt** â€” currently the schema block is hard-coded. Auto-build it from `PRAGMA table_info` so adding a column never silently breaks SQL-gen.
- **Long-note chunking** â€” if user-created notes get long enough that whole-note embedding loses signal.
- **Date-range parser** â€” `ledger from december 2025`, `weight from last sunday`, `notes between last friday and now`, `expense q1` are still mis-routed in deterministic mode (independent_500 surfaced 2 cases). The planner with real Qwen handles them; a deterministic date-range parser would close them on the mock path too.
- **Final 7 dangerous cases from independent_500** â€” 3 adversarial inputs (safely stored as notes; parameterized SQL prevents execution), 2 date-range phrasings (above), 1 ambiguous noun phrase (`dosa batter ratio`), 1 person-knowledge phrase (`pr sundar position sizing rule`). Real Qwen routing should close most; the noun-phrase case is genuine intent ambiguity.

---

## Notebooks status

NB1 verified passing. NB2/NB3/NB5 remain useful as engine references. NB4 still matters as a reference-corpus experiment, but product behavior is now all-notes retrieval rather than investment/health-specific note buckets. User-created notes no longer need a manual notebook run to become searchable (post-step-5).

---

## Empirical stress runs (2026-05-03)

These runs were executed against the **actual Flask `/note` / `/notes/add` path** on copied DBs. They are not fixes; they are measurement artifacts used to understand where the current app still breaks.

### Run 1 â€” `test_replay_matrix.py` (200-case replay matrix)

- Scope: **100** historical `logs.txt` inputs replayed chronologically + **100** generated variants from the same observed patterns.
- Artifacts: `artifacts/replay_matrix/`
- Historical replay match against the saved `logs.txt` behavior:
  - kind match **73/100**
  - parsed metadata available in logs **76/100**
  - tier match **37/72** comparable cases
  - rule match **36/76** comparable cases
  - response exact match **29-31/100** across reruns
- Main finding: the app is **not** behaviorally stable with respect to older dogfooded history. Many historical misroutes are now fixed, but there is still substantial divergence between what the live app used to do and what the current app does on the same inputs.
- Important failures found in the variant matrix:
  - note-query phrasing around some topics still drifts into unrelated retrieval
  - some note-existence phrasings such as `did i ever save a note on X` still save a new note instead of performing note retrieval
  - plural expense-history phrasing such as `last 4 expenses` can still be misread as a write
  - ledger-history phrasing such as `ledger history for maddy` / `ledger history for ravi` can still be misread as note writes

### Run 2 â€” `test_replay_matrix_full_throttle.py` (500-case full-throttle mixed stress)

- Scope: **500** total cases = **100** historical replay + **400** generated probes.
- Emphasis: note retrieval first, then expense retrieval, todo, weight, ledger.
- Generated focus mix:
  - `note_query` **210**
  - `note_write` **40**
  - `expense_query` **62**
  - `expense_write` **10**
  - `todo_write` **20**
  - `todo_query` **13**
  - `weight_write` **10**
  - `weight_query` **15**
  - `ledger_write` **5**
  - `ledger_query` **10**
  - `ledger_clarification` **5**
- Artifacts: `artifacts/replay_matrix_full_throttle_500/`
- Generated-segment summary:
  - expected-kind pass **390/400**
  - token-hit pass on comparable generated probes **259/314**
  - triage buckets: **381 ok / 13 scope decision / 5 not ignorable / 1 maybe ignorable**
- Main note-retrieval failures:
  - **core `cipla` retrieval is broken** for several normal note-query phrasings (`show notes about cipla`, `find cipla in my notes`, `any mention of cipla in the notes`, `any info on cipla in my notes`, `show saved notes about cipla`) â€” responses came back with unrelated content such as `maddy ledger`
  - typo variants such as `sipla` / `ciplla` are weak or contaminated
  - note-existence phrasing such as `did i ever save a note on vivekananda/fundera park/mcp/cipla/tamilnad mercentile bank/peter lynch` still routes as a **write**, creates a new note, and creates an embedding side effect instead of retrieving
- Main non-note failures:
  - `last 4 expenses` routed as `legacy_write_expense` (`â‚¹4 last expenses logged`)
  - `ledger history for maddy` and `ledger history for ravi` routed as `legacy_write_note`
- Main latency findings from this run:
  - generated note queries were mostly steady-state and acceptable in mock mode: p50 about **28.8ms**, p95 about **34.0ms**
  - there was still a cold-start outlier in the historical segment (`show me motivation quotes saved`) at about **9.3s**

### Structured deterministic coverage inside Run 2

This is the exact basis for the earlier statement that the app is "mostly stable" on deterministic structured flows. The strength is real, but it applies more to **routing and common phrasing** than to every semantic variant.

- **Todos**
  - Total structured todo probes in the 500-case run: **33**
  - Write coverage: **20** cases = **10 core + 10 stretch**, kind-pass **20/20**, p50 about **4.8ms**
  - Query coverage: **13** cases = **4 core + 8 stretch + 1 adversarial**, kind-pass **13/13**, p50 about **5.3ms**
  - Representative passes:
    - `todo: update maddy about datascience in iit chennai`
    - `remind me to call Amit about MCP status`
    - `show me todo list`
    - `show done todos`
    - `todo status`
  - Current read: todos are the strongest structured surface in the tested range.

- **Weights**
  - Total structured weight probes in the 500-case run: **25**
  - Write coverage: **10** cases, kind-pass **10/10**, p50 about **4.9ms**
  - Query coverage: **15** cases = **3 core + 12 stretch**, kind-pass **15/15**, p50 about **5.5ms**
  - Representative passes:
    - `jeevi 64.4`
    - `jeevi weight 64.8 after lunch`
    - `latest weight of jeevi`
    - `last 3 prani weight`
    - `show jeevi weight history`
  - Current read: weights are also genuinely strong in the tested range, both for writes and short-history retrieval.

- **Expenses**
  - Total structured expense probes in the 500-case run: **72**
  - Write coverage: **10** cases, kind-pass **10/10**, p50 about **5.4ms**
  - Query coverage: **62** cases = **20 core + 40 stretch + 2 adversarial**, kind-pass **60/62**, p50 about **5.5ms**
  - Representative passes:
    - `petrol expense this month`
    - `show petrol expense list`
    - `groceries expense this month`
    - `show this month's expenses`
    - `show last 3 expenses one by one`
  - Clear failures:
    - `last 4 expenses` was misrouted as `legacy_write_expense`
    - `bills this month` was misrouted as `legacy_write_note`
  - Important semantic caveat:
    - some queries that "passed" on routing still look wrong on meaning. For example, `what did i spend on ginger this month` and `what did i spend on milk this month` routed as queries but returned the all-month total instead of a clearly filtered category total. So expense correctness is weaker than the raw **60/62** routing pass rate suggests.

- **Ledger**
  - Total structured ledger probes in the 500-case run: **20**
  - Write coverage: **5** cases, kind-pass **5/5**, p50 about **5.8ms**
  - Query coverage: **10** cases = **3 core + 7 stretch**, kind-pass **8/10**, p50 about **6.0ms**
  - Clarification coverage: **5** cases, kind-pass **5/5**, p50 about **5.1ms**
  - Representative passes:
    - `gave maddy 5k`
    - `who owes me money`
    - `who do i owe`
    - `maddy ledger summary`
    - `clear maddy ledger`
  - Clear failures:
    - `ledger history for maddy` was misrouted as `legacy_write_note`
    - `ledger history for ravi` was misrouted as `legacy_write_note`
  - Important semantic caveat:
    - `show ledger for ravi` stayed a query but returned `Best match from note:83: maddy ledger`, which is not acceptable semantically even though it did not mutate data. So ledger is only "mostly stable" for the basic balance/settlement slice, not for broader person-history retrieval.

### Run 3 â€” `test_note_corpus_stress_200.py` (isolated long-note corpus stress)

- Scope: **200 newly seeded long notes** across **20 domains** + **200 note retrieval queries**
- Domains used: astronomy, nutrition, climate policy, distributed systems, programming language design, Indian history, behavioral psychology, urban design, microbiology, film theory, classical music, regenerative agriculture, logistics, linguistics, renewable energy, marine biology, cybersecurity, public health, philosophy, education research
- Write pattern mix:
  - `notes_page_burst4` **80**
  - `home_explicit_burst3` **60**
  - `home_freeform_single` **40**
  - `notes_page_single` **20**
- Query pattern mix:
  - immediate post-seed smoke queries **20**
  - domain-direct queries **40**
  - anchor-exact queries **40**
  - alias queries **20**
  - typo queries **20**
  - complex paraphrase queries **20**
  - complex anchor queries **20**
  - global recency/listing queries **20**
- Artifacts: `artifacts/note_corpus_stress_200/`
- Corpus was reset before seeding so this run measures the new synthetic note corpus cleanly.
- Results:
  - plain notes saved **199/200**
  - embeddings created **199/200**
  - query prompts that stayed queries **200/200**
  - token-hit pass on comparable note queries **177/180**
  - immediate per-domain smoke retrieval **20/20**
  - full-corpus comparable retrieval **157/160**
- Important failures:
  - one free-form long note write (`education research` note containing `transfer task mismatch`) was misrouted as a **query** and answered with pending todos instead of being saved as a plain note
  - typo retrieval failed for `flim theory` and `phliosophy`, both with cross-domain contamination
  - one complex note query (`find the education research note where transfer task mismatch mattered more than headlines`) returned pending todos instead of note retrieval output
- Latency:
  - first `/notes/add` write had a cold-start outlier at about **8.6s**
  - after warm state, long-note writes were mostly around **42-49ms**
  - full-corpus note queries were mostly around **46-52ms**

### Empirical conclusion from the three runs

1. **The app is strongest on todos and weights.** In the current mock-backed runtime, todo writes/queries and weight writes/queries were the cleanest structured surfaces under direct stress. Expense totals/basic lists and ledger balances/settlement clarifications are usable, but their broader phrasing and semantic correctness are weaker than a simple "stable" label suggests.
2. **The app still fails hardest in note retrieval.** Not the normal easy cases (`X notes`, anchor-exact, alias queries) â€” those are mostly good now. The main failures are:
   - semantic drift to unrelated notes
   - note-query phrasings that are still interpreted as writes
   - typo tolerance gaps
   - collisions where note text or note query text triggers another intent family (`task`, `todo`, etc.)
3. **Expense retrieval has both phrase-shape holes and semantic-filter weaknesses.** Totals and simple list queries often route correctly, but history/range language is still fragile and some routed queries still appear to ignore the requested description filter.
4. **Ledger retrieval is acceptable for basic balances and settlement clarification, but weak for history-style phrasing and some person-specific retrievals.**
5. **Cold-start latency is still a real product risk.** Even when steady-state timings are acceptable, the first heavy note write/query can still spike into multi-second territory.

### Post-fix rerun status (2026-05-03, after read/write membrane + hybrid note retrieval)

These are the latest reruns after the architectural fixes that landed the same day. They supersede the older "where the app is failing miserably" snapshot for the current codebase.

- **Rerun of Run 1 â€” `test_replay_matrix.py`**
  - Historical replay remains intentionally noisy because it compares the current app against older logged behavior, not against a correctness oracle.
  - Latest rerun: kind match **73/100**, tier match **37/72**, rule match **36/76**, response exact match **29/100**, first-line match **30/100**.
  - Read: this run is still useful as a drift detector, but it should no longer be treated as the main quality score for the current app.

- **Rerun of Run 2 â€” `test_replay_matrix_full_throttle.py`**
  - Generated expected-kind pass is now **400/400**.
  - Generated triage is now **398 ok / 2 scope-decision-needed**.
  - Remaining generated break reasons collapsed to only **2 note-query misses**.
  - Structured surfaces improved materially:
    - `expense_query` **62/62**
    - `ledger_query` **10/10**
    - `note_query` **210/210** on kind-pass
  - The earlier failure classes that motivated the architectural fix are no longer present in this run:
    - `did i ever save a note on X` no longer routes as a write
    - `last 4 expenses` no longer logs a new expense
    - `ledger history for maddy/ravi` no longer becomes a note write
    - core `cipla` retrieval failures are no longer in the worst-case list
  - Remaining scope-decision cases are typo-heavy `mpc notes` / `find mpc in my notes`.

- **Rerun of Run 3 â€” `test_note_corpus_stress_200.py`**
  - Plain-note writes stayed at **199/200**
  - Embeddings stayed at **199/200**
  - Query prompts stayed queries at **200/200**
  - Comparable query token-hit is now **176/180**
  - Remaining misses are now much narrower:
    - **4** domain misses on retrieval
    - mostly typo-heavy note queries such as `astronamy`, `nutrishun`, `phliosophy`
  - Important note: correctness improved, but note-query latency increased because the hybrid lexical layer currently does Python-side fuzzy scoring over the corpus.
    - immediate-after-seed note queries: p50 about **126ms**
    - full-corpus note queries: p50 about **347ms**, p95 about **1.29s**
    - queries over **1s**: **24**

### Current status after reruns

1. **The dangerous trust failures are mostly closed in the current mock-backed path.** Read-shaped inputs are no longer freely mutating data, and note retrieval is much less willing to return unrelated notes.
2. **Structured deterministic flows are now genuinely strong in the tested range.** Todo, weight, expense-basic, and ledger-basic queries all held up in the latest 500-case rerun.
3. **The remaining note problems are narrower and more honest.** The app now fails more by abstaining or missing typo-heavy anchors than by confidently doing the wrong thing.
4. **The next bottleneck is latency, not broad routing correctness.** The current lexical+semantic note retrieval is safer, but it is expensive in Python on larger note corpora.

### Independent 510-case probe (2026-05-04, after the 4-fix sweep)

Designed to push out-of-the-box: natural-language paraphrase note retrieval, partial-recall ("the note about X being Y"), typo storms, abstain expectations on absent topics, ambiguous note-vs-write inputs, free-form short and long notes, question-shaped journal entries, code-switched / colloquial language, punctuation edges, numerical edges, fragmentary and adversarial inputs, compound multi-intent submissions, date phrasings, existence/negation queries, comparison/aggregation phrasings, person-specific retrievals, multi-line input, and non-standard query verbs (`dump my notes`, `recall my X`, `walk me through my Y`).

**Headline numbers (510 cases, mock LLM + fake embedding):**
- ok-rate **97%** (up from 83% before the sweep)
- real-danger **1.4%** (7 cases; down from 13% / 64 cases)
- audit-only `notes` growth **0** (eliminated; was 40% / 205 cases)
- kind-mismatch **3%** (down from 16%)
- write-lost **2%** (8 cases)
- broken/exception **0**
- latency p50 13.2 ms · p95 134.8 ms · p99 177.1 ms · max 722 ms

**Strongest categories (zero danger):** typo retrieval (40/40), partial recall (30/30), natural paraphrase (59/60), code-switched (30/30), punctuation edges (25/25), numeric edges (25/25), fragmentary inputs (15/15), multiline input (15/15), compound intents (20/20), existence queries (20/20), comparison queries (20/20), abstain expectations (30/30 — no false retrievals on absent topics), short notes (39/40), question-shaped journal entries (20/20 routed through journal-question clarify).

**Remaining 7 danger cases:** 3 adversarial inputs safely stored as notes (parameterized SQL prevents execution), 2 date-range phrasings (`ledger from december 2025`, `weight from last sunday`), 1 ambiguous noun phrase (`dosa batter ratio`), 1 person-knowledge phrase (`pr sundar position sizing rule`).

**Caveat:** the 510-case run uses the mock LLM, which returns `unknown` for most novel phrasings. With real Qwen, many of the 7 remaining danger cases would likely route correctly via Tier 1 instead of falling to the legacy bridge. The improvement nonetheless reflects real architectural hardening: the membrane catches more, the expense parser is no longer prose-greedy, audit bloat is gone, and journal questions have a UX path.

---

## How to run what exists today

```bash
# SQL safety gate (no DB writes, no LLM)
python test_sql_safety.py              # expect 40 passed, 0 failed

# Tier 0 grammar
python test_orchestrator_tier0.py      # expect 31/31

# Routing memory + memo wiring
python test_routing_memory.py          # expect all checks pass

# Original logs.txt failure regressions
python test_logs_regression.py         # expect all checks pass

# Live activity log regressions (covers every misroute observed in dogfooding)
python test_activity_log_regression.py # expect 25/25

# Page-based CRUD (notes, expenses, ledger, weights, todos)
python test_flask_crud.py              # expect all checks pass

# 200-case historical+variant replay matrix
python test_replay_matrix.py

# 500-case full-throttle mixed stress run
python test_replay_matrix_full_throttle.py

# 200-long-note isolated corpus stress run
python test_note_corpus_stress_200.py

# Independent 510-case out-of-the-box stress (note input/retrieval heavy)
python test_independent_500.py
# Re-classify the resulting JSON with the refined danger model:
python artifacts/independent_500/analyze.py
# Expect: ok ~97%, real-danger ~1%, audit-only growth 0, write-lost ~2%

# Run the Flask app (orchestrator + planner is the live path)
python app.py
# open http://localhost:5000
```

Prereq for everything: `second_brain.db` must exist (run `notebook_1_sqlite.ipynb` once if missing). On startup, `ensure_runtime_schema` runs three idempotent migrations against existing DBs: (1) adds the `user_routing_memory` table; (2) `_migrate_structured_notes_to_captures` moves legacy structured rows off `source_note_id` onto `source_capture_id`; (3) `_purge_audit_notes` deletes orphan `structured_type IN ('query','clarify')` rows from `notes`. All three are safe to run repeatedly.

- 2026-05-06 â€” **Fine-tuned live parser runtime fixed for the local GPU env.** The first Flask dogfood attempt reached the fine-tuned parser path but failed during model load because the `.venv-qwen3-1p7b-1650` stack had drifted into an incompatible mix (`torch`/`torchvision` mismatch first, then `torchao` expecting newer torch APIs such as `torch.utils._pytree.register_constant`). The loader in `second_brain_finetuned_parser.py` was updated to: (1) resolve the cached local snapshot of `unsloth/Qwen3-1.7B-bnb-4bit` when present; and (2) hide `torchao` from `transformers` during model import/load, since this base model is bitsandbytes-quantized and does not need torchao at inference time. Verified outcomes: `FinetunedParserService.warm()` now succeeds, `FinetunedParserService.parse("weight: 75kg")` returns valid JSON, and the full orchestrator path on a temp DB copy successfully handled `weight: 75kg` with `tier="finetuned"`.

- 2026-05-07 â€” **v2 dataset generator landed (Phase 2 steps 3â€“4 of `dataset_v2_plan.md` Â§9).** New file `generate_large_schema_frozen_dataset_v2.py` implements the v2 schema and diversity rules end-to-end: harmonized intent vocabulary, per-pattern Tanglish gating (Pattern C 0% everywhere; Tanglish dates only inside todo-write Pattern B), per-form weighted distribution with scoped 28â€“30% per lane, phrasing-pool expansion to 8â€“17 templates per form with the 35/30/20/15 noun/verb/question/Tanglish-A mix, multi-anchor generation across 5 anchors with every row carrying top-level `anchor_date`, anchor-relative date resolver (canonical relatives, calendar months with most-recent-occurrence semantics, Indian fiscal quarter/year, absolute calendar phrasings), 60/30/10 date-phrase routing, reject pool widening, the four new slices (Â§5.1 adversarial pairs in dedicated `parse_query/adversarial.jsonl`, Â§5.2 bare-nameless at 10%, Â§5.3 typo at 7% on search lanes, Â§5.5 action-shaped clarify ~200/4000 in ledger, Â§5.6 multi-person compare reject ~150/4000 in weight), ledger reason notes dropped (every record `note: null`), and `reference_only/` not generated. Output dir: `synthetic_finetune_dataset_v4_v2_schema/`. v1 generator preserved untouched. `synthetic_dataset_assets.py` got minimal additions â€” `TANGLISH_SINGLE_DATE_KEYS` / `TANGLISH_RANGE_KEYS` constants and a header comment that the ledger-reason pools are retained for v1 only. Verified via `--report` smoke (parse_write 500/lane, parse_query 1000/domain, parse_followup 1000) and a tiny end-to-end smoke (50 rows/lane producing the expected file layout). Form weight calibrations recorded in the plan: weight `multi_person_compare_reject` 2%â†’3% and ledger `action_clarify` 2%â†’4% so the Â§5 explicit row targets land within the 4000-row lane budget. The full v2 generation run was NOT executed â€” it is an explicit user decision. Phase 2 steps 5â€“8 (eval scoring, v3 held-out eval, Colab `Today:` injection, runtime wrapper `Today:` injection) remain pending.

- 2026-05-07 -- **Phase 2 §9 steps 5-8 done; Phase 2 fully complete.** `evaluate_finetune.py` now scores the v2 parse_query disposition / clarify_reason / clarify_options / reason_code with per-row schema routing (presence of `disposition` on a `parse_query` expected -> v2 row; v1 rows score on legacy metrics only); per-row `anchor_date` drives a `Today: <YYYY-MM-DD>` line in the system prompt; GPU-only imports (`unsloth`, `torch`, `peft`) moved inside `evaluate_model()` so the file is `.venv`-importable for offline scoring smokes. New `generate_eval_dataset_v3.py` produces a v2-schema held-out eval set at `eval_finetune_dataset_v3_schema_frozen/`, importing v2 makers + `pick_anchor_iso` so eval rows inherit per-row anchor randomization; `--report` mode supported; de-dups against the v4 training root when present. `colab_finetune_old.py` was modified to inject `Today: <anchor_date>` into the system prompt during chat-template formatting (rows missing `anchor_date` keep historical framing byte-identical), then renamed to `colab_finetune.py` and the previous "later revised" `colab_finetune.py` deleted -- there is now a single Colab training script. `second_brain_finetuned_parser.py` adds `today_injection_enabled()` + `build_system_prompt(today_iso)`; `parse()` injects `Today: <real_today>` at every inference when `SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION` is on (default off so the v1 adapter path stays byte-identical); flag surfaced in `status()`. Verified via three offline smokes at `.tmp/step5_score_smoke.py`, `.tmp/step7_framing_smoke.py`, `.tmp/step8_runtime_smoke.py`.

- 2026-05-07 -- **Phase 3 review pass + asset expansion (post §9 work).** A 100-row dry-run review of `synthetic_finetune_dataset_v4_v2_schema/` surfaced a long list of asset and generator issues, all addressed in two batches plus a corpus expansion. Asset bug fixes in `synthetic_dataset_assets.py`: missing comma in `TANGLISH_SINGLE_DATE_KEYS` (was silently concatenating `naliku` + `kalila` -> `nalikukalila`), `2027-04-31` / `2025-04-31` -> `04-30` for `indha varusam` / `pona varusam`, dropped `INDIA_EXPENSE["work"|"education"]` extends to `INDIA_BUY` (no more `school building fund` / `certificate attestation` / `cowork day pass` as buy items), dropped `_TANGLISH_TRANSPORT` / `_TANGLISH_DINING` / `_TANGLISH_VEHICLE` / `_TANGLISH_LEDGER` (the kasu lists; per user, nobody writes "auto kasu" / "tea kasu" in real Tanglish). Generator fixes in `generate_large_schema_frozen_dataset_v2.py`: `ANCHORS` replaced by `ANCHOR_MONTHS` + `pick_anchor_iso(rng)` so day-of-month is randomized per row (year stays 2026), substring-overlap filter on buy multi-entry (no more `salt` + `Anil salt` co-occurrence), ledger balance perspective fix (templates split into `_NEUTRAL` / `_I_OWE` / `_THEY_OWE` buckets so `tell me X balance` -> `perspective: null`, `how much do i owe X` -> `i_owe_them`, `how much does X owe me` -> `they_owe_me`), `kaatu` / Pattern C purge from all query templates, time-of-day phrasings stripped from query date pools (kept for writes), ledger query templates rewritten away from literal "ledger" word (66% -> 38% usage), `BUY_PREFIX/TRIPLE` Pattern B/C entries dropped (`vaanganum` / `vangikanum` / `kooda` were against §2 spec). Phase 3 asset expansion roughly doubles every major pool with curated, real, India-/global-relevant entries; all extends route through `_extend_unique` with a final `_dedup_inplace` pass. INDIA_NAMES 462->707, GLOBAL_NAMES 170->376, INDIA_NOTE_TOPICS 385->631, GLOBAL_NOTE_TOPICS 180->329, INDIA_BUY 546->1235, GLOBAL_BUY 156->252, INDIA_TODOS 2356->2548, INDIA_TODO_NOUNS 676->795, GLOBAL_TODOS 968->1088, GLOBAL_TODO_NOUNS 209->293, plus per-group expense expansions (groceries 207->421, transport 28->58, dining 30->60, etc.). User regenerated `synthetic_finetune_dataset_v4_v2_schema/` at 100 rows/lane after the fixes. Analysis (`dataset_v2_plan.md` §13.4): 0 schema violations across 1300 rows, 0 regressions across all Phase 1+2 fixes, 154 distinct anchor dates across 1300 rows, 98/98 date resolutions correct (including 4 compare-intent rows correctly using `compare_date_*`), all special slices firing (6 weight rejects, 4 ledger clarifies, 50 adversarial pairs, 100 followups). The dataset is review-clean and ready for full-scale generation + the v2 fine-tune.

- 2026-05-07 -- **`generate_eval_dataset_v3.py` gets a `--total <N>` flag.** Driven by the user wanting a Colab-cheap eval option (50 / 100 cases instead of 500). New helper `derive_counts_from_total(total)` distributes proportionally across the three buckets at the historical 40 / 42 / 18 ratio (writes / queries / followups), with a hard floor of 1 row per lane / domain so every file is represented even at small totals. Concrete behavior: `--total 50` -> 47 rows (4/lane writes, 3/domain queries, 9 followups); `--total 100` -> exactly 100 (8/lane, 7/domain, 18 followups); `--total 500` -> exactly 500 (40/lane, 35/domain, 90 followups, matching the previous historical default). Per-bucket flags (`--write-per-lane`, `--query-per-domain`, `--followup-count`) still win over `--total` when set explicitly, so users can override individual buckets while letting the rest auto-distribute. `--report` now surfaces the resolved per-bucket counts and the `--total` value when set. Verified: a `--total 50` generation into `.tmp/eval_v3_50/` produced 47 cases with 4 rows per write lane, 3 per query domain, and followups spanning 5 of 6 domains (expense missed by chance at this small N). Doc updates: `dataset_v2_plan.md` §9 step 6 entry, `current_state.md` "Next steps" example commands.

- 2026-05-08 -- **Build #19: UX overhaul shipped — chat-style Home, top-right toast overlay, submission queue, comprehensive event_log.** First major iteration after device dogfooding. Tag chips reordered to `ask, todo, expense, note, weight, buy, ledger`. Home redesigned: scrollable feed at top, chip row + input box + Send/Cancel/Copy-logs pinned at bottom (chat-app convention). Removed the `model ✓ · embedder ✓` status row from Home — that's noise on a user-activity surface. Custom Compose `AppToastHost` (top-right anchored `Popup` with slide-in-from-right + fade animations, 2.5 s auto-dismiss, max 4 stacked) replaces system `Toast` entirely; modern Android (11+) blocks programmatic toast positioning so the system widget couldn't do top-right anyway. Submission queue in `HomeViewModel`: tapping Send clears input/chips immediately and appends a `PendingItem` to a list; a single worker coroutine pulls items serially (LLM is single-threaded by design) and the UI shows each pending item as a secondary-colored bubble with a 3-dot pulse animation while processing — user can type the next thing right away. DB bumped to v2: every `created_at` default switched from UTC `datetime('now')` to `datetime('now','localtime')` so timestamps match phone notification time; existing rows are wiped on the v1→v2 upgrade per the pre-1.0 rebuild policy. New `event_log` table + `diag/EventLog.kt` singleton for the comprehensive diagnostic feed (separate from user-facing `activity_log` and per-orchestrator `request_log`): captures app lifecycle, model loads, every orchestrator stage, uncaught crashes via `Thread.setDefaultUncaughtExceptionHandler`. Capped at 2000 rows; oldest 500 auto-archive to dated `event_log_YYYYMMDD.jsonl` files in `getExternalFilesDir("logs")` when exceeded. "Clear all logs" now wipes activity_log + request_log + event_log + archive files AND emits on `AppStatusBus` so Home's recent feed refreshes immediately (the previous "didn't visibly clear" UI bug was a refresh issue, not a delete issue). New files: `AppStatusBus.kt`, `AppStartup.kt`, `diag/EventLog.kt`, `ui/common/AppToastHost.kt`. Heavily modified: `Database.kt`, `SecondBrainApp.kt`, `MainActivity.kt`, `HomeViewModel.kt`, `HomeScreen.kt`, `Tags.kt`, `RequestLog.kt`. Deferred to Phase 3f: per-CRUD toast emissions on Notes/Expenses/Ledger/Weights/Todos/People (~30 one-line additions), Settings UI for `event_log` cap dropdown + Copy event log button. Output: `app-debug.apk` 52.15 MB built 2026-05-08 21:06, BUILD SUCCESSFUL in 32 s. Open issue still parked: model emits `{"data":{...}}` instead of trained `{"records":[...]}` schema — needs dataset/fine-tune output review before deciding to re-finetune vs adapt the orchestrator.

- 2026-05-08 -- **18 builds in: Qwen3 inference working at native CPU speed on Pixel 7; entering UX iteration phase.** After the first APK in build #7, real-device dogfooding surfaced a chain of issues that took builds #8 through #18 to resolve. The full debugging journey is preserved in `android_port.md` "Issues hit during the first build" — the table now has 17 entries plus 2 from the ONNX-export pipeline. The two non-obvious findings worth restating here: (i) **llama.cpp pin `b3938` (Sept 2024) doesn't have Qwen3 architecture support** — landed around April 2025. Bumped to `b6500` (mid-2025), rewrote the JNI back to the newer API surface (`llama_model_load_from_file`, `llama_init_from_model`, `llama_model_get_vocab`, vocab-arg tokenize/detokenize, 2-arg `llama_batch_get_one`). (ii) **AGP debug variant compiles llama.cpp at `-O0` with asserts, making matmul 20-50× slower than expected** — observed as multi-minute hangs on 82-token prefill. Forced `CMAKE_BUILD_TYPE=Release` for the native subtree (separate from APK build type) plus `-march=armv8.2-a+dotprod+fp16` to enable the fast Q4_K_M kernels. After that fix (build #17), prefill on an 82-token prompt is 3.3 s, decode runs at ~10 tok/s, and total request time is 8-11 s for a parser write — exactly the first-principles target. Build #18 added Qwen3 thinking-tag stripping (`<think>...</think>` wrapper) so JSON parses cleanly. Two big things remained open at end-of-day: (a) the model emits `{"data":{...}}` instead of the v2-trained `{"records":[...]}` schema — needs investigation of the actual fine-tune output vs the dataset before deciding to re-finetune or adapt; (b) a list of UX papercuts from real dogfooding (toast positioning, input-at-bottom, IST timestamps, common diagnostic log, queueable submissions) — captured as Phase 3e in the Android tracker.

- 2026-05-08 -- **First debug APK built locally; CPU-only path shipped, Vulkan deferred to phase 3d.** After 3c the v1 code was complete; this entry covers the actual first APK production. NDK 30.0.14904198 + CMake 4.1.2 (whatever Studio's SDK Manager defaulted to on this machine; build.gradle.kts now pins to those exact versions). The build surfaced 9 distinct issues across 7 attempts (full table in `android_port.md`); all fixes now committed so future rebuilds are one-shot. Most consequential decision: `GGML_VULKAN=OFF`. llama.cpp's Vulkan backend builds a host tool `vulkan-shaders-gen` at build time to pre-compile shaders, but cross-compiling for Android with AGP's single-pass externalNativeBuild produces that tool as an arm64 ELF the Windows host can't exec, breaking the shader-gen step. Proper fix is a two-stage build (host pass for the shader-gen tool, then Android arm64 lib linking against pre-generated shaders) — that's queued as Phase 3d. CPU inference of Qwen3-1.7B Q4_K_M on Pixel 7 is acceptable for the parser surface (~5-15 tok/s for ~50-100 token outputs); Settings GPU toggle remains as a no-op until 3d. Other notable fixes worth remembering: (a) `WIN32` is the *target* not the *host* during Android cross-compile, must use `CMAKE_HOST_WIN32` for tooling-path detection; (b) Kotlin `runCatching {}.onFailure {}` infers `Result<T>` from the trailing expression — `Log.i` returns `Int` so we ended up with `Result<Int>` instead of `Result<Unit>`, requires explicit `Unit` as the last expression; (c) bare `return` inside `withContext { ... }` is rejected because suspend-inline lambdas don't permit non-local returns — use `return@withContext` for early exit and lambda last-expression for normal flow; (d) JNI shim was originally written against post-b3938 llama.cpp API (renames around late 2024 / early 2025: `llama_load_model_from_file` → `llama_model_load_from_file`, `llama_new_context_with_model` → `llama_init_from_model`, model-arg → vocab-arg on tokenize/detokenize, 4-arg → 2-arg `llama_batch_get_one`); rewrote `llama_jni.cpp` to match the b3938 API exactly to keep the pin known-good. Local-laptop alternative for ONNX export added: `export_minilm_onnx.py` mirrors the Colab notebook so you can avoid a Colab session entirely. Output: `app-debug.apk` 36.8 MB built 2026-05-08 17:52 from `gradlew.bat --no-daemon assembleDebug`. Next move is dogfooding on Pixel 7: install APK, push 4 model files (GUFF + minilm.onnx + vocab + tokenizer_config), Settings → Load model + Load embedder, Home → tap `ask:` + `buy:` chips → `latest buy list` → Send → Activity log Copy → paste diagnostic block back to drive the next iteration. See `android_port.md` "Issues hit during the first build" for the permanent fixes table.

- 2026-05-08 -- **Android port v1 spec complete (phase 3c shipped same day).** With phases 1, 2, 3a, and 3b already in (LLM packaging, skeleton app, foundation + Home + Activity + Settings, structured screens + clarify resolution), the final piece — on-device sentence embeddings + hybrid note search — landed today. Pivoted from the originally-picked multilingual `paraphrase-multilingual-MiniLM-L12-v2` to English-only `all-MiniLM-L6-v2` because BERT WordPiece is ~150 lines of pure-Kotlin tokenizer vs 300-500 lines of XLM-RoBERTa SentencePiece Unigram Viterbi (or pulling in `ai.djl.huggingface:tokenizers` for +12 MB of native libs and another debug surface). Multilingual swap is documented as a future swap with the existing `MiniLmEncoder.kt` reusable as-is — only the tokenizer + ONNX file change. New artifacts: `colab_export_minilm_onnx.ipynb` (15 cells; exports + optionally int8-quantizes the model, saves `vocab.txt` + a tiny `minilm_tokenizer_config.json`, sanity-tests with cosine), `android/app/src/main/java/com/secondbrain/app/embedding/{WordPieceTokenizer,MiniLmEncoder,EmbeddingsDao}.kt`. Wired in: `Orchestrator.saveNote` fires off encoding on `SupervisorJob + Dispatchers.Default` (per project contract: "indexing can be asynchronous"); `Orchestrator.handle` wrapped in `withContext(Dispatchers.Default)` so the request runs off Main and the encoder's `runBlocking` cannot ANR; `QueryRunner.runNote` rewritten as a hybrid scorer (`0.55 × lex + 0.45 × sem` with abstain at top-score < 0.20); Settings shows model-file presence, load button, embedding count, pending count, and a Re-embed-pending button for backfill. Dependency change: `app/build.gradle.kts` adds `com.microsoft.onnxruntime:onnxruntime-android:1.17.1`. Documentation updated in `android_port.md` (3c marked shipped, file layout updated, known-cuts section refreshed) and `android/README.md` (3c section + multilingual swap recipe). The locked v1 product spec is now fully implemented — next user move is dogfooding on Pixel 7 and pasting Activity-log diagnostic blocks back to drive the next iteration.

- 2026-05-08 -- **Android port begun; Flask retired as the active surface.** User pushed back hard that the Flask app wasn't a faithful product surface and they couldn't see what the v2 fine-tune was actually doing without a real device UI. Pivoted to the original Android-first design captured in this file's "Project Snapshot". Architecture locked across four rounds of clarifying questions: native Kotlin port (no Python/Chaquopy on device), llama.cpp via JNI with Vulkan GPU offload by default + CPU fallback per layer, merged-LoRA Q4_K_M GGUF (single ~1.1 GB file), Compose UI with minSdk 26, arm64-only, ONNX MiniLM via onnxruntime-android for embeddings (deferred to phase 3c), fresh empty DB on first install, Pixel 7 only for testing (no emulator for LLM perf). Locked UX: 7 chip tags (`ask`/`expense`/`ledger`/`weight`/`todo`/`note`/`buy`); ask + at most one domain or exactly one write; auto-convert typed `<tag>:` to chip; chip wins on duplicate (typed text stripped, toast shown). Locked logging: new `request_log` table captures user input + chips + tier + full LLM prompt + raw JSON + every SQL with args/row counts/sample rows + final text + per-stage timings + errors; clipboard format is plain-text blocks separated by `---`; per-section Copy buttons on every domain page; `Clear` wipes both `activity_log` and `request_log` so each troubleshooting round starts clean. Numbered-clarify resolution implemented: parser `disposition=clarify`/`confirm` persists a `pending_actions` row, Home shows a banner, user replies `1`/`2`/`cancel` to resolve without going through the LLM. Phases 1 (GGUF Colab notebook), 2 (skeleton with one-prompt JNI smoke test), 3a (foundation + Home + Activity + Settings), and 3b (all 7 structured screens + clarify resolution) all shipped today. Phase 3c (ONNX MiniLM + hybrid lexical+semantic note search) queued. See `android_port.md` for the full architecture record and phase status. New artifacts: `colab_convert_to_gguf.ipynb`, `android/` subfolder (~34 Kotlin/native source files), `android_port.md`, `android/README.md`.

- 2026-05-07 -- **Kaggle notebooks shipped (`kaggle_finetune.ipynb` + `kaggle_evaluate.ipynb`).** Colab free-tier GPU minutes proved too restrictive to actually run the v2 fine-tune end-to-end, so the user moved to Kaggle (free T4 x2 or P100, 16 GB VRAM, ~30 GPU hours/week). Two notebooks added at the project root, both nbformat 4.5 and validated by `compile()`-ing every code cell:
   - **`kaggle_finetune.ipynb`** -- mirrors `colab_finetune.py` byte-for-byte on the chat-template framing (system prompt + per-row `Today: <anchor_date>`). Drops the `google.colab` Drive mount logic, switches default paths to `/kaggle/input/synthetic-finetune-v4-v2-schema/synthetic_finetune_dataset_v4_v2_schema` (configurable in the CONFIG cell) and `/kaggle/working/unsloth_qwen3_parser_run` for output. Optional `HF_TOKEN` via Kaggle Secrets (commented one-liner). 9 code cells: CONFIG -> install -> imports + GPU info -> helpers -> load model + LoRA -> format dataset -> train -> save -> sanity inference. Output panel exposes the LoRA adapter for download (~50 MB).
   - **`kaggle_evaluate.ipynb`** -- mirrors `evaluate_finetune.py` but converts the argparse CLI into a notebook config cell (`DATASET`, `FINETUNED_MODEL`, `FINETUNED_BASE_MODEL`, `BASE_MODEL`, `LIMIT`, etc.). All helpers (`build_system_prompt`, `safe_json_loads`, `score_prediction` with v2 per-row schema routing, `summarize_rows`, `print_summary`) are **inlined** in the notebook so no source-repo upload is needed. The inference loop is wrapped in `evaluate_one_model(label, ...)` so base + fine-tuned can both be scored in the same kernel without manual cleanup. 8 code cells: CONFIG -> install -> imports + GPU info -> helpers -> load cases -> evaluator function -> run eval -> top failures. Outputs land at `/kaggle/working/eval_run/{base,finetuned}/{predictions.jsonl,summary.json}`.
   - **Honored contracts**: `Today:` injection from per-row `anchor_date` (matches the v2 framing locked in `dataset_v2_plan.md` §13.2 and `finetuning_data_sanity.md`); per-row schema routing on parse_query so v1 eval rows still pass through cleanly; greedy inference (`do_sample=False`, `max_new_tokens=256`, `enable_thinking=False`).
   - Doc updates: `current_state.md` "Next steps" item 3 now says "Queue the v2 fine-tune (Kaggle preferred)" with `colab_finetune.py` retained as fallback; file pointers table gets a new "Kaggle notebooks" row. `dataset_v2_plan.md` §9 step 7 footnote mentions the Kaggle equivalents.

- 2026-05-08 -- **Build #26: Home redesign + drawer trim + auto-add people + activity-log fixes.** Six clustered improvements after dogfooding the build #19 surface. Home rewritten as a 2-page `HorizontalPager`: page 0 is six tiles (Todos / Expenses / Buy / Weights / Notes / Ledger) with a one-line live count under each (`3 today / 8 total`, `₹12,450 this month`, `+₹5,000 owed to you  ·  -₹2,300 you owe`, etc.); page 1 is the existing chat-history feed with pending bubbles and recent activity. Shared bottom `HomeInputBar` and a small two-dot indicator. New `TileSummary` data class on `HomeViewModel` populated by a single `refreshTiles()` IO query and re-fetched on every `AppStatusBus` emit so counts always reflect the latest write. `AppNav` drawer trimmed to four entries (Home, Activity log, People, Settings); the lane composables remain registered as routes so tile clicks navigate cleanly. `WriteRunner.ensurePersonExists()` (called from weight + ledger inserts) now auto-creates the persons row when the parser returns a name we haven't seen and emits an `AppStatusBus` toast (`Added new person: Maddy`) so the user knows it happened. ActivityLogScreen copy bug fixed: `buildClipboard(selectedIds)` snapshots the selection set before the IO hop and uses one batched `IN (?,?,...)` query instead of per-row reads (the previous code raced on selection mutation, occasionally copying everything when the user only had a subset checked). Toolbar reordered for stable layout: All / None / spacer / Refresh / Copy(N) / Clear. Output: `app-debug.apk` 54.7 MB.

- 2026-05-08 -- **Build #27: app icon + first-launch self-name onboarding + per-day note grouping + RAG synth toggle + undo button.** Five items shipped together. (1) Adaptive launcher icon: vector "SB" lettermark on a navy circle (`ic_launcher_background.xml` solid `#1F2A44`, `ic_launcher_foreground.xml` foreground vector, mipmap adaptive XMLs, manifest references). (2) First-launch self-name onboarding: `data/SelfName.kt` persists to `runtime_state` (lowercased on store); `ui/common/SelfNameOnboardingHost` is hoisted at `MainActivity` root above the nav host so the modal overlays whatever screen the user is on; Skip stores `"self"` so the modal doesn't fire again. `WriteRunners.resolveSelf()` rewrites pronoun-style person values (`{self, me, i, myself, mine, myne}`) to the saved name on weight + ledger inserts. Settings gets an editable name field for the same value. (3) Per-day note grouping: `Orchestrator.saveNote()` now checks for an existing `notes` row dated today; first note today inserts a new row prefixed `[HH:MM:SS]`, subsequent same-day notes UPDATE that row appending `\n\n[HH:MM:SS] <text>`. Embedding is re-computed for the whole day's blob (replaces the previous `embeddings` row). (4) RAG synthesis toggle: `parser/NoteSynthSetting.kt` boolean in `runtime_state`, off by default, surfaced as a Settings switch. When on, `QueryRunner.runNote` runs an extra LLM round-trip ("answer in 1-2 sentences using ONLY the notes below") with `maxTokens=96` and prepends the synthesized line above the snippet block; on any failure (timeout, blank output) the snippet block falls through unchanged. `runNote` and `QueryRunner.run` were marked `suspend` to enable the LLM call. (5) **Undo button**: every reversible orchestrator request now returns an `UndoToken` collected through an `UndoBuilder` threaded into `WriteRunner.run` and `Orchestrator.saveNote`. Token records: row deletes for expense / buy_items / todos / weights / ledger; `NoteUndo` (`{noteId, previousContent, wasInsert}`) for either restore-prior-content or delete-row; auto-added person names; tied embedding `source_note_id`s. `HomeState.undo: UndoBanner?` surfaces a 5 s tap-to-revert chip above the input; `Undoer.execute()` runs the rollback in a single transaction and only deletes auto-added persons if no row in `weights` or `ledger` still references the name. PendingActions clarify-resolution inserts are NOT undoable — those are user follow-ups, not fresh submissions. Output: `app-debug.apk` 54.7 MB built 2026-05-08 23:56, BUILD SUCCESSFUL in 25 s. Open issues unchanged: schema-drift re-finetune queued (`data:{}` vs trained `records:[]`), reminder lane training data, day-of-week phrase fluency.

- 2026-05-09 -- **Schema-drift root cause found in trainer + 12 dataset patches + 2 features designed.** Heaviest non-build session of the project. User pasted a 100-activity device dogfood log (`logs.txt`); diagnosis split the failures into model-fixable vs code-fixable buckets with a strong steer from the user that this re-finetune cycle should bundle as much as possible.
   - **Trainer fix in `colab_finetune.py`** (the single most important change in the session). SFTTrainer was running with `dataset_text_field="text"` and no `data_collator` argument, which means loss is computed across the FULL chat template — system prompt + user input + assistant JSON. The JSON output was getting only ~10-15% of the gradient signal, so the model learned generic chat-template tokens well and the strict JSON schema weakly, falling back at inference to the simpler `data:{...}` shape from pre-training. Dataset was always correct (100% of `synthetic_finetune_dataset_v4_v2_schema/` rows use `records:[]`) — the trainer was the bug. Fix: added `from unsloth.chat_templates import train_on_responses_only; trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")` after the `SFTTrainer(...)` call, so loss is masked for everything before the assistant marker. Also flipped `ENABLE_PACKING = False` (packing without completion-only loss leaks gradient across example boundaries) and bumped `MAX_SEQ_LENGTH` 1024 → 1536 to fit the new 12-item record JSON outputs (each record ~70 tokens, so 1024 was truncating past ~13 records). `parser/ShapeAdapter.kt` stays in place as defense-in-depth — early exits when the model already emits `records:[]`, costs nothing.
   - **12 dataset-gap patches in `generate_large_schema_frozen_dataset_v2.py`** mapped 1:1 to user-log failures: (1) `make_buy_write` long-list branch picks N from [4..12] in 12% of accept rows (was capped at 3) — fixes #48/#77/#78/#79 multi-item buy losses; (2) `make_todo_write` long-list 4-8 + new `render_todo_pattern_b_with_person` helper that embeds real person names INSIDE the text field (`prabu son paaka ponum`) so the model stops leaking ledger-style `person_text` into todo schema — fixes #71/#72/#73; (3) `make_expense_write` long-list 4-10 in 12% of rows; (4) trailing-comma augmentation 8% on multi-item buy/todo/expense (dataset previously had ZERO trailing-comma rows, user's `buy: A, B, C,` style was OOD) — fixes #77/#78/#79; (5) `BUY_LIST_BARE` expanded with 13 user phrasings (`buy list`, `list`, `show buy`, `whats on buy`, etc.) and bare-rate bumped 10% → 35% in `make_buy_query` — fixes #81/#82/#96 returning 0 rows; (6) new `bare_name_clarify` form in `make_note_query` (weight 7) trains the model to emit `disposition:"clarify"` for bare names like `prani` instead of silently misclassifying — fixes #65/#93; (7) `EXPENSE_FORM_WEIGHTS` rebalanced (desc 6→18, group 7→12, exclude 2→3) so filter-bearing share rises 21%→43%, plus 30% of desc-form rows now use undated phrasings (`total milk expense`, `expense on petrol`) — fixes #85/#88/#100 returning ₹34607 (everything); (8) `LEDGER_SUMMARY_BARE` expanded with `balance`/`balances`/`ledger summary`/etc. and bare-rate bumped 10%→30% in `make_ledger_query` summary form, with `perspective:null` enforced — fixes #64 hallucinating `perspective:"i_owe_them"`; (9) Tanglish verb branch in `make_buy_write` (~20% of india-mode accept rows) using `BUY_TANGLISH_TRAILING_VERBS` (`vanganum`/`vaanganum`/`kekanum`/`book pannanum`/`vendi irukku`) + `BUY_TANGLISH_PER_ITEM_VERBS` + `BUY_TANGLISH_CONNECTORS` (`kooda`/`appuram`/`mattum`); (10) English day-of-week phrases (`tomorrow`, `weekend`, `next monday`, `this friday`) added to `render_todo_pattern_b_with_person` via new helper `_english_day_phrase_with_date`, plus 30% of person-in-text rows put the time phrase at the FRONT (`tomorrow prabu son paaka ponum`); (11) Buy quantity input aliases (`gms`/`ltr`/`kgs`/`kg`/`packet`) bias 35% on india-mode rows — input only, records keep canonical units; (12) Settle/repay phrasings expanded with Tanglish (`{name} ku settle pannitten`, `kasu kudutiten`, `bakki kudutiten`, `vasooli pannita`) + English (`paid back fully`, `cleared {name} account`, `closed {name} account`).
   - **`synthetic_dataset_assets.py` corpus addition: `_TANGLISH_BUY_ONLY` pool** with user's actual items from logs that have no clean English equivalent: `Manjal`, `kasthuri methi`, `kasthuri manjal`, `Gaza gasa`, `killer nighty`, `kili pachai saree`, `uluntha parupu`, `thuvam paruppu`, `paasi parupu` plus 30+ more (vetrilai, paaku, elakkai, lavangam, pattai, karupatti, panangkalkandu, cotton nighty, rayon kurta, silk saree, salwar set, veshti, thundu, kal urai, ammi, thosai kal, kuzhambu satti, muruku, thattai, sevai, mysorepak, athirasam, vasanai soap, kungumam, sandhanam, vibhuti packet). User explicitly committed to keep typing buy in Tanglish for life.
   - **Smoke verification (500 rows/lane gen)**: records-per-row now extends to 11 buy / 8 todo / 10 expense (was capped at 3); trailing-comma fires on ~4% of all rows (~8% of multi-item rows, on target); todo person-in-text 3.4% of rows; note `bare_name_clarify` 9.4%; buy undated `intent=list` rate 68%; expense filter-bearing share 43%; Tanglish verb fires in 7% of buy rows; ledger summary bare 7.7%; all user-named items confirmed in INDIA_BUY pool.
   - **Reminder lane explicitly deferred** — user agreed it's a separate cycle (needs Android schema edits, new lane in WRITE_LANES, RemindersDao, RemindersScreen, AlarmManager/WorkManager + foreground service for notifications).
   - **Two new feature specs locked, gated by re-finetune validating:** (a) **Ambient nudges V1** — replaces "morning digest" idea per user redirect to a domain-rotating one-at-a-time callout system. App-launch-only trigger for V1, surfaces ONE unsurfaced fact as chat bubble in Home page-1 if last surface >30 min ago, pool refreshes when unsurfaced count <3, six generators (5 deterministic SQL + 1 LLM-driven for note callouts using exclusion-list prompt against already-surfaced note IDs), tap-to-navigate UX, new `nudge_facts` table. Spec saved to `~/.claude/.../memory/ambient_nudges_design.md`. (b) **Query response LLM polish V1** — synthesis layer in `Orchestrator.handle` AFTER `QueryRunner.run` returns template text, passes `(userQuery, templateText)` to the on-device parser model with a "render in 1-2 sentences using ONLY these facts" prompt, falls back to template on failure. ON by default with Settings toggle, chevron expands raw text underneath. Queries only — writes stay snappy. Mirrors existing `NoteSynthSetting` pattern. Spec saved to `~/.claude/.../memory/query_response_polish.md`.
   - **Workflow note:** Colab is the primary fine-tune path now (user clarified — Kaggle only if Colab GPU exhausts). All Android dogfooding waits on the new GGUF landing. After re-finetune validates, the two queued features (~80 lines Kotlin each + a shared `parser/QuerySynth.kt` helper) can ship in the same build cycle.
   - **Action queue for the user:** (1) `python generate_large_schema_frozen_dataset_v2.py --write-count 5000 --query-count 5000 --followup-count 6000` to regenerate the dataset with patches applied; (2) re-train on Colab with the patched `colab_finetune.py`; (3) convert via `colab_convert_to_gguf.ipynb` pointing `ADAPTER_DIR` at the newest output; (4) push GGUF to phone, force-stop, reload model; (5) verify `weight: testperson 50kg` → Activity log Copy → look for `"records":[{...}]` in LLM RAW JSON (not `"data":{...}`); (6) dogfood the bug fixes; (7) plan code work for ambient nudges V1 + query response polish V1.

- 2026-05-09 (later, same day) -- **Round 2 robustness patches: 8 more generator additions + ~360 corpus items.** After the first 12-patch round, user pushed back asking whether the corpus was really robust enough for "in this lifetime" usage and whether we should add Malayalam/Kannada/Telugu support. Ran a corpus depth audit (INDIA_BUY 1288, ~6.9 picks per item at 5k rows — adequate but not luxurious) and a deep schema-gap analysis covering 26 categories of input variation. User confirmed: only Tanglish + English (skip Mal/Kan/Tel because they're distinct languages not dialects, would dilute Tanglish quality without serving real usage), no voice-to-text augmentation (always types), and "Indian context bundle" scope (skip schema-changing yes/no and when-did query intents which need Android updates).
   - **Patch #13 currency notation depth.** `amount_text_and_value` extended from 8 to 16 styles. New: `K_upper` (`5K`), `k_thousand` (`5 thousand`), `rs_dot` (`Rs.5000`), `rs_slash` (`5000/-`), `L_upper` (`5L`), `lakhs`/`crores` plurals.
   - **Patch #14 absolute date format breadth.** New helper `pick_numeric_date_phrase` with 15 numeric/named-month formatters (`15-02-2026`, `15/02/2026`, `15.02.2026`, `15-02-26`, `15/2`, `15th Feb`, `Feb 15`, `15th of Feb`, etc.). Hooked into `pick_write_date_phrase` at 12% probability.
   - **Patch #15 festival/event-relative dates.** `_FESTIVAL_DATES_2026` map with 24 festivals (Pongal/Republic Day/Holi/Tamil New Year/Vishu/Easter/Akshaya Tritiya/Ramzan/Eid/Bakrid/Aadi/Independence Day/Onam/Vinayagar Chaturthi/Ganesh Chaturthi/Navratri/Dussehra/Vijayadashami/Karthigai/Karthigai Deepam/Diwali/Deepavali/Christmas/New Year). Plus 14 personal-event templates (`before exam`, `after wedding`, `before bday`, `before paati function`, `after house warming`, etc.). New `pick_festival_date_phrase` resolves to a date 1-7 days before/after the festival (or random offset for personal events). Falls through cleanly when no festival resolves for an anchor. Hooked at 8% probability.
   - **Patch #16 top-N expense queries.** New `top_n` form added to `EXPENSE_FORM_WEIGHTS` (weight 5). Picks `n ∈ {3, 5, 10}`, renders `top {n} expenses`, `biggest {n} spending`, `highest {n}`, etc. with explicit `limit:n` in output. ~33% of these rows also carry a date qualifier.
   - **Patches #17 + #18 input noise (whitespace, casing, mixed separators).** New shared helper `apply_input_noise(input_text, rng, has_multi_items)` applied at the very end of all 5 write makers. Independent low-probability triggers: 4% double-space, 3% leading/trailing whitespace, 4% random ALL-CAPS or capitalize-mid-sentence on one word, 5% missing-space-between-letter-and-digit (`paasi parupu1kg`), 5% chance for multi-item rows to swap one comma with `;`/` / `/` + `/` & `/` and `. Records output untouched. Trains the model that input noise should be ignored, not interpreted.
   - **Patch #19 quantity fractions and ranges.** Buy maker's quantity-display pipeline now has a `display_qty` shadow alongside `display_unit`. 8% of buy items with kg/g/ml/L units render as `half kg` / `1/2 kg` / `3/4 kg` / `2-3 kg` / `2 to 3 kg` / `~2 kg` / `about 2 kg` in the input. Records keep canonical numeric `quantity_text` + `unit_text`. The qty-unit join logic was updated so non-numeric quantities always get a space (`half kg` not `halfkg`).
   - **Patch #20 corpus expansion: ~360 items.** `_TANGLISH_BUY_PHASE2` adds ~100 more Tanglish-only items across vegetables (chinna vengayam, periya vengayam, vazhakkai, vazhaipoo, kothavarai, siru/mulai/agathi keerai, kothamalli verai), pulses/grains (kollu, ragi, varagu, samai, thinai, kuthiravali, kambu maavu, ragi maavu), snacks (muthusaaram, kara sev, ribbon pakoda, thattai, masal/ulundha/medhu/paruppu vadai, halwa variants, mysorepak, bombay halwa, adhirasam, manoharam), dairy (thayir, moru, panneer, more milagai, ghee dabba), meat/fish (kozhi, naatu kozhi, broiler kozhi, aatu kari, pannri kari, meen variants, nandu, eral, kanavai), ready-mix (rasam mix, sambar mix, idli mix, dosa mix, vatha kuzhambu mix, payasam mix, paal kova), festival items (manjal kayiru, thoranam, kolam podi, vibhuti pottu, sandhanam pottu, deepam ennai, samikku flowers), salt variants (kal uppu, podi uppu, indu uppu). `_BRAND_PRODUCT_COMPOUNDS` adds ~200 brand+product compound entries: dairy (Amul/Aavin/Nandini/Mother Dairy/Heritage/Britannia/Country Delight ghee/curd/butter/paneer), spices (Aachi/Sakthi/MTR/Eastern/Suhana/Catch/MDH/Everest/Ramdev sambar/rasam/chicken/biryani/garam/turmeric/chilli powders), oils (Idhayam gingelly oil, Saffola gold, Fortune sunflower/mustard, Sundrop, Parachute coconut oil), atta (Aashirvaad multigrain/Pillsbury/Patanjali/24 Mantra), rice (India Gate basmati, Daawat, Lal Qilla, Sungold, Ponni, Sona masoori, 1121, 1509), dal (Tata Sampann toor/moong/chana/urad, Patanjali masoor, 24 Mantra organic), snacks (Lays magic masala, Haldiram bhujia, Bikano, Britannia good day/marie gold/bourbon/50-50, Parle G/hide and seek/Monaco, Sunfeast dark fantasy, Cadbury silk/5 star, Nestle kitkat/munch), beverages (Boost, Bournvita, Horlicks, Complan, Pediasure, Tata Tea premium/gold, Brooke Bond red label/taj mahal, Tata coffee, Bru gold/instant, Nescafe classic/sunrise), soaps (Mysore Sandal soap+shampoo, Cinthol confidence, Liril, Pears facewash, Dove conditioner, Lux, Hamam, Margo neem, Medimix hair oil/hand wash, Patanjali kesh kanti, Himalaya neem face pack), detergents (Surf Excel matic/quick wash, Tide plus/bar, Ariel matic, Henko stain champion, Rin bar, Wheel powder, Nirma, Ezee liquid), household (Vim dishwash gel/bar, Pril dish wash, Colin glass cleaner, Lizol floor cleaner, Harpic toilet cleaner, Phenol bottle, Odonil air freshener, Hit insect spray, All Out refill, Good Knight refill, Mortein liquid), toothpaste (Colgate strong teeth/maxfresh/vedshakti, Pepsodent germi check/salt power, Sensodyne fresh mint, Closeup red, Meswak, Anchor white, Patanjali dant kanti, Dabur red), baby (Pampers premium care, Mamy Poko pants, Cerelac wheat apple, Lactogen 1, Nestle Nan Pro), and others (Maggi noodles, Yippee noodles, Top Ramen, Knorr soup, MTR ready meal, iD batter/malabar paratha). All extended via `_extend_unique` to `INDIA_BUY` and split-extended to relevant `INDIA_EXPENSE` groups (groceries / personal_care / household). **Pool sizes after Round 2: INDIA_BUY 1288 → 1550 (+262), INDIA_EXPENSE['groceries'] 421 → 494 (+73), INDIA_EXPENSE['personal_care'] 263 → 288 (+25).**
   - **Smoke verification (800 rows/lane writes + 500/lane queries):** all 16 currency styles firing across expense + ledger; all 5 absolute date formats firing across writes; 53 festival/event-relative phrases across buy + todo + expense; 29/500 expense queries are top-N with explicit `limit ∈ {3,5,10}`; input noise: 233 double-space rows, 172 leading/trailing whitespace, 57 ALL-CAPS, 125 no-space-digit, 86 semicolon, 94 `and` separators; quantity variants: 6 `half`, 9 range-dash, 8 `~N`, 2 `about N`; 102 buy rows mention a known brand; all 15 spot-checked items confirmed in INDIA_BUY pool.
   - **Honest robustness assessment given to the user:** combined with the Round 1 patches and the trainer fix, this re-finetune should land at ~88-92% of natural inputs working correctly. The remaining 8-12% will need either better Kotlin reject/clarify messages OR a small "explainer" LLM call when reject fires (V2 polish) OR new schema lanes for delete/edit operations (a separate re-finetune cycle). No re-finetune gets to 99%; the bullseye is "good enough that bugs are rare and helpful when they happen", not "perfect".

- 2026-05-09 (later, same day) -- **3k smoke + date reweight + production regen at 5k/lane.** User asked for a 3000 rows/lane generation, deep diversity analysis, and a specific check on whether reminder + weekend/weekday identification are handled. Ran 18-category audit on 3k smoke (~22.8k rows): 17 PASS, 2 WARN (numeric date format firing rate slightly low; weight Tanglish density 1% which is acceptable per user's earlier "weight is mostly numeric" call), 1 FAIL (weekend-vs-weekday FILTER queries — schema has no `day_type: weekend|weekday` field; user agreed to defer). Reminder lane verified correctly absent: zero rows with `lane:"reminder"` or `domain:"reminder"`; 123 rows mention "remind me" inside todo/note text only.
   - **Date format reweight per user's actual typing pattern.** User clarified: dominant date form is `<day> <month-abbrev>` (`15 jan`, `1 mar`, `25 dec`, `3 sept`) with no leading zero on day; sometimes `<month> <day>` order; rarely with year; only ~10% in `01-12` numeric form. The previous flat `_NUMERIC_DATE_FORMATS` lambda list weighted numeric forms equally with month-name forms — replaced with two helpers: `_format_month_name_date` (handles 4 sub-shapes: day+abbrev, abbrev+day, day+full, full+day, with mixed lower/Cap and 80/20 abbrev/full split) and `_format_numeric_date` (handles dd-mm and dd-mm-yyyy with `-` / `/` / `.` separators, 30% include year). New `_MONTH_ABBREVS_USER` enumerates user's exact list (jan/feb/mar/apr/may/jun/`july`/aug/`sept`/oct/nov/dec — 4-letter `july` and `sept` per spec). Distribution within absolute-date branch: 85% month-name forms, 15% numeric. Pure-numeric with year is now <0.1% of all writes (matching user's "rarely year"). Firing rate of the absolute-date branch bumped 12% → 18%.
   - **Production regen ran in 61s.** Full 5k/5k/6k generation into `synthetic_finetune_dataset_v4_v2_schema/`: 25k writes, 30k queries, 6k followups, 800 adversarial = **61,800 rows total**. Smoke verification on the production output: every category PASS at scale: long-list 4+ records 526/439/571 (buy/todo/expense, max 12/8/10); Tanglish density buy 13.3% / todo 31.2% / expense 8.5% / ledger 8.9% / weight 0.6% (last is acceptable — weight inputs are mostly numeric); all 8 currency styles fire 200-1500 each; absolute dates `15 jan` 967, `Jan 15` 416, `25 January` 351, numeric short 252, numeric+year 60; relative dates today/yesterday/tomorrow 966, weekend 603, DOW 4742, Tanglish 422, festival 415, personal event 217; input noise all 9 patterns fire ≥50 (double-space 1403, ALL-CAPS 475, semicolon 480, `and` 513, slash 64, `&` 54, `+` 63); quantity variants all 7 fire ≥5 (half 28, range 35, ~N 35, gms 135, ltr 31, packet 263); Tanglish verb branch 332; note bare-name clarify 509; buy undated list 2,234 (47% of buy queries); expense filter-bearing share 38.3% (was 21% pre-patch); ledger settle/repay 715; top-N expense 321; pool exhaustion buy 1,790 unique items used, peak 25× (toothpaste), 87 picked only once. Reminder lane confirmed absent (0/0). Weekend phrase: 603 writes + 183 queries, resolves correctly to Saturday. Weekend-vs-weekday FILTER: 0 rows (deferred — would need new schema field).
   - **Dataset is production-ready for re-finetune.** Action queue: (1) train via patched `colab_finetune.py` on Colab (must verify trainer has `train_on_responses_only` + `packing=False` + `MAX_SEQ_LENGTH=1536`); (2) GGUF convert; (3) push to phone, force-stop, reload; (4) verify `weight: testperson 50kg` shows `"records":[...]` (not `"data":{...}`) in LLM RAW JSON; (5) dogfood. After validation, the two queued features (`ambient nudges V1` + `query response polish V1`) can ship in the same build cycle.

- 2026-05-09 (later) -- **Layer 1 runWeight footgun fix + Layer 2 weight question templates + Layer 3a cross-domain followup rows.** User asked specifically about followup-question handling, suspecting cross-domain hallucination ("Q1: amma weight 50kg, Q2: ask: what is jeevi weight → returned Amma's weight as Jeevi's"). Concrete activity log #105 dissection revealed a different bug stack than user assumed: (a) the Android port doesn't actually pass any prior query context to the parser (every parse call is independent — verified by reading `Orchestrator.handle`, `ParserService.parse`, `ChatTemplate.buildPrompt`), so "followup contamination" is impossible; (b) the actual failure was the model emitting `search_text:null` and no `filters` block for `what is jeevi weight` — it dropped the name entirely; (c) `QueryRunners.runWeight` then silently fell back to "most recent person in weights table" which happened to be Amma (just inserted). User saw Amma's weight returned as Jeevi's and attributed it to followup-context contamination. The bug stack is parser-name-extraction-failure + dangerous-runner-fallback-mask-as-confident-wrong-answer.
   - **Followup dataset audit found a real but separate gap:** 6000/6000 (100 %) of `parse_followup_query` rows are same-domain (context.domain == output.domain). Zero "context discard" rows. Zero `inherit_context: false` rows. Even if Android wired up context-passing, the model would be biased toward over-inheriting and produce Frankenstein cross-domain outputs.
   - **Layer 1 (Kotlin, ships now):** `QueryRunners.runWeight` updated. New helper `resolvePersonForWeight(r, filterPerson, userText, log)` runs when `filters.person_text` is null/"self": tokenizes the user's input text, intersects tokens against the union of (persons table names ∪ distinct persons in weights table), uses the single match, the lexicographically first if multiple match, or falls back to "self" if zero matches. **No more "most recent" fallback** — that was producing confident wrong answers for every parser name-extraction failure. `QueryRunner.run` gained an optional `userText: String = ""` parameter, threaded from `Orchestrator.handle` via `tagged.composed`. `BUILD SUCCESSFUL in 21s`. Will ship in next APK without new training.
   - **Layer 2 (generator):** `WEIGHT_LATEST_TEMPLATES` expanded across noun/verb/question buckets with bare-question shapes user actually types. Noun: `{person} weight`, `weight of {person}`, `{person}'s weight`, `weight {person}`. Verb: `show {person} weight`, `give me {person} weight`, `tell me {person} weight`, `show me {person}'s weight`, `fetch {person} weight`, `pull up / find / look up {person} weight`. Question: `what is {person} weight`, `what's {person} weight`, `whats {person} weight` (no apostrophe), `what is the weight of {person}`, `how much does {person} weigh`, `how much {person} weighs`, `do you know {person} weight`, `can you tell {person} weight`, `{person} weight please`, `{person} weight?`. Smoke verified at 500 queries: 44 hits across new shapes. Fixes the #105 phrasing failure.
   - **Layer 3a (generator):** New helper `_followup_cross_domain(anchor, mode, rng)` picks a context domain + different current domain from {expense, buy, todo, weight, ledger, note} (30 distinct ordered pairs), generates context from `_accept_base_query(make_X_query)` for one domain and input/output for another, returns `{anchor_date, context, input, output}` where `output.task = "parse_query"` (NOT `parse_followup_query`). The implicit signal teaches the model "switch domain → discard prior context". `make_followup` fires this branch on 25 % of rows. Smoke verified at 2000 followup rows: 536/2000 (26.8 %) cross-domain, all 536 with correct `task = "parse_query"` (zero misassignments). Coverage spans all 30 (ctx, cur) pairs with 17-34 rows per pair.
   - **Layer 3b (Android followup wiring) deferred** until after re-finetune validates. Plan: store last accepted query JSON in `runtime_state`, update `ChatTemplate.buildPrompt` to optionally inject `Previous structured query context:\n{ctx}\n\nUser input:\n{text}` (byte-identical to training format), `Orchestrator.handle` reads context for queries (not writes), runner merges `inherit_context` fields when payload `task == parse_followup_query`. ~150 Kotlin lines. Held back so the model isn't context-biased before cross-domain training arrives.
   - **Action queue update:** dataset needs ONE more regen before training to pick up Layer 2 + 3a changes. Same command (`python generate_large_schema_frozen_dataset_v2.py --out-dir synthetic_finetune_dataset_v4_v2_schema --write-count 5000 --query-count 5000 --followup-count 6000`). Then train, convert, push, validate per the existing checklist.

- 2026-05-09 (later) -- **`ParserService.maxTokens` 200 → 512** — required runtime change to fit the long-list outputs the new dataset trains for. Each canonical buy record JSON (`{"item_text":"X","quantity_text":null,"unit_text":null,"date":"YYYY-MM-DD"}`) is ~25 tokens; a 12-item buy output is ~300 tokens of records + ~30-token wrapper ≈ 330 tokens. The previous 200-token cap would silently truncate every long-list output the new fine-tune produces, producing broken JSON that falls through to save-as-note (same failure mode as build-#27 dogfood log #78). 512 leaves headroom for 15-item lists with longer item names. `BUILD SUCCESSFUL` after the change. Will ship in next APK alongside the new GGUF.

- 2026-05-09 (later) -- **Build #28: six in-session UX fixes after dogfood feedback.** All six compile clean in one APK build. Will ship as `app-debug.apk` next time the user runs `assembleDebug`.
   - **#1 Todo tile crash (one-character bug).** `TilesPage` (Home page-0) used route `"todo"` for the Todos tile but `AppNav.kt` only registered the composable as `"todos"`. Tap → `navController.navigate("todo")` threw `IllegalArgumentException: navigation destination 'todo' is not in the navigation graph` and crashed the app. Fixed in `HomeScreen.kt::CompactTilesGrid` by aligning route names. Verified by inspection that all 6 tile routes (`todos`, `expenses`, `buy`, `weights`, `notes`, `ledger`) match what AppNav registers.
   - **#2 Self-name moved from Settings to People page.** Removed the "Your name" field from `SettingsScreen.kt`. New `PeopleScreen.kt` displays an `AssistChip("self")` next to whichever person matches `SelfName.get(db)?.lowercase()`. Each person row has a `MoreVert` 3-dot overflow with three actions: `Set as self` (for non-self rows), `Rename`, `Delete`. The "Set as self" action calls `SelfName.set(db, name)` and emits an AppStatusBus toast (`<Name> is now you (future entries only — past records unchanged)`). Switching self only changes future writes — historical `weights`/`ledger` rows are NOT retroactively renamed (the data layer behavior was already correct; only the UI surface moved). Renaming an active-self person also updates the saved self_name so pronoun resolution stays consistent. The onboarding modal at first launch is unchanged.
   - **#3 Compact 2×3 tile grid at bottom of Home.** Removed `HorizontalPager` entirely — no more page-0 tiles vs page-1 chat swipe. New layout top-to-bottom: `AmbientFactStrip` → `ProcessingBanner` → `UndoChip` → `ChatHistoryPage` (scrollable, takes available space via `Modifier.weight(1f)`) → `CompactTilesGrid` (2 rows × 3 cols, 78dp tall vs old 120dp, smaller icon + tighter padding) → `HomeInputBar`. Tiles are always visible directly above the input. The page indicator dots and `pagerState` import are gone. `ChatHistoryPage` gained a `modifier: Modifier = Modifier` param so the parent can pass `weight(1f)`.
   - **#4 Rotating ambient nudge strip (V0).** New file `AmbientFacts.kt` with `compute()` that runs 6 SQL queries against the DB to produce 6–14 natural-language one-liners: (a) stale weights (people whose latest weight log is >30 days old), (b) long-pending buy items (>7 days open), (c) aging open ledger balances (`Maddy still owes you ₹5,000` / `You still owe Thenna ₹2,000`), (d) pending todo backlog (todos with `date < today-3` still pending), (e) this-month expense total via `ExpensesDao.monthTotal`, (f) headline counts (notes captured, people tracked). Plus a `pickNext(facts, seen)` helper for cycling without repetition. `HomeViewModel` gained `ambientFacts: List<String>` and `ambientCurrent: String?` state fields, a `refreshAmbientFacts()` method that recomputes the pool, and a coroutine that rotates `ambientCurrent` every 8 seconds via `pickNext`. Pool is recomputed on init AND on every `AppStatusBus` event so it's always fresh after writes. `HomeScreen` adds an `AmbientFactStrip(state.ambientCurrent)` Composable at the very top — a thin Surface row with `✦ <fact>` rendered in `labelMedium`. Hidden when `ambientCurrent` is null/blank. **V0 is template-only — no LLM call.** The planned V1 (LLM polish over the same facts + LLM-driven note callout generator with exclusion-list prompt against already-surfaced note IDs) is the existing `~/.claude/.../memory/ambient_nudges_design.md` spec, still deferred until after re-finetune validates.
   - **#5 Notes per-day blob now newest-first.** `Orchestrator.saveNote` flipped from `existingText + "\n\n[HH:MM:SS] $content"` to `"[$now] $content\n\n$existingText"` so the latest entry sits at the top of today's row when the user opens it.
   - **#6 Removed the auto-jump-to-chat-page-on-Send.** The `LaunchedEffect(state.pending.size)` block that animated the pager to page 1 on every Send was disorienting per user feedback. With the layout overhaul (#3 above) the pager is gone anyway, but the explicit removal documented in code prevents accidental re-introduction. Feedback now comes from the always-visible ProcessingBanner (top of viewport) and AppToastHost (top-right corner overlay) regardless of where the user is in the app.
   - **Action queue:** rebuild via `gradlew.bat --no-daemon assembleDebug` (~25-60s incremental) and push the APK. The new APK is independent of the new GGUF — user can install it now and dogfood the UX fixes immediately while waiting for the re-finetune to complete on Colab. The new GGUF can be pushed any time after.

- 2026-05-10 — **Notes-page CRUD fix: per-day grouping + `[HH:MM:SS]` prefix unified across surfaces.** Two user-reported bugs after dogfooding had the same root cause: `NotesDao.add` (called from the `/notes` Notes-page Add button) was a raw `INSERT` that bypassed the per-day grouping + timestamp-prefix logic that lived only inside `Orchestrator.saveNote`. Result: three Notes-page adds today produced three separate rows with no `[HH:MM:SS]` prefix, while three Home-input notes the same day would have correctly appended into one row. Fix extracted the per-day logic into `NotesDao.addForToday(db, content) → NoteSaveResult` (returns `id`, `finalContent`, `previousContent`, `wasInsert` so callers can wire undo + embedding refresh). Both surfaces now delegate: `Orchestrator.saveNote` keeps undo + async embedding handling but lets the DAO own the grouping; `NotesScreen.add()` calls the same DAO and fires its own embedding refresh in `viewModelScope` to mirror Home semantics. The same-day check stays `substr(created_at,1,10) = LocalDate.now().toString()` and Database.kt's `datetime('now','localtime')` defaults make both sides timezone-consistent. Build verified via `gradlew.bat --no-daemon assembleDebug` (54 s, BUILD SUCCESSFUL). Files changed: `data/Daos.kt`, `orchestrator/Orchestrator.kt` (also dropped now-unused `ContentValues` import), `ui/notes/NotesScreen.kt` (added `EmbeddingsDao` + `MiniLmEncoder` imports). Will ship in next APK.

- 2026-05-11 — **Activity-feed deep-linking + ledger-edit direction toggle + 0.6B parser scaffolding + multi-model picker.** Five things shipped together; APK build clean.
   - **Home activity feed clickable.** Each non-deletion row in `Recent` now navigates to its domain screen on tap. Resolver tries three sources in order: (a) orchestrator metadata `target_route` + `target_row_id` (set on every Home submission post this build — flashes the affected row on the destination screen), (b) input-text tag prefix (`expense:` / `buy:` / `todo:` / `weight:` / `ledger:` / `note:` — covers historical Home rows logged with `kind="write"` / `"query"` before this build), (c) `kind` column (covers all page-CRUD adds/edits/toggles + orchestrator `kind="note"`). Deletion entries explicitly non-clickable: case-sensitive `Deleted ` / `Cleared ` prefix on `inputText` (matches every per-screen `logActivity("Deleted X", …)` / `("Cleared X", …)` site; user-typed plain notes starting with lowercase "deleted my…" stay clickable). `kind="settings"` / `"settings_error"` also filtered. Old `ask:` queries logged before this build remain non-clickable because the domain isn't recoverable from text alone — new `ask:` writes carry `target_route` from the parser payload's `domain` so they work. Recent feed cap stayed at 30 (`HomeViewModel.refreshRecent` already used `ActivityLogDao.list(db, limit = 30)`).
   - **Highlight + scroll on destination screens.** New `ui/common/HighlightBus.kt` (single-shot `set(route, id)` / `consume(route)` registry) and `ui/common/Highlight.kt` (`HighlightState` + `consumeOnLaunch` + `backgroundFor` — tertiary-tinted background with a 250 ms fade-in / 600 ms fade-out, scrolls the LazyColumn to the target row). Wired into all six lane screens: `WeightsScreen`, `LedgerScreen`, `ExpensesScreen` (handles its date-grouped header layout), `BuyScreen` + `TodosScreen` via a new `highlightRoute` parameter on the shared `DateGroupedChecklist`, `NotesScreen`. `Orchestrator.handle` now records the target metadata: write writes → first row id from `undo.rowDeletes` filtered by lane→table mapping, query → `domainToRoute(payload.domain)` with no row id, note bypass → `("notes", noteId)`. Two new helpers in `Orchestrator`: `laneToRoute` / `laneToTable` / `domainToRoute`. `OrchestratorResult.metadataJson` now includes `target_route` / `target_row_id` keys when known.
   - **Ledger edit direction toggle.** `LedgerScreen` edit form was missing the `I lent` / `I owe` selection — only the add form had it, so editing an existing entry left direction frozen at whatever it was originally. Added `editDirection` to `LedgerViewModel.S`, seeded from `row.direction` in `startEdit`, persisted via `saveEdit` → `LedgerDao.update`. `LedgerDao.update(...)` signature bumped to take `direction: String` (puts it into the row alongside person / amount / date / note). UI gets a `FilterChip` row matching the add form's styling (`I lent` selects `gave`, `I owe` selects `received`).
   - **Qwen3-0.6B parser scaffolding (separate files; 1.7B path untouched).** Four new files added so the smaller model can be A/B'd against the production 1.7B without disturbing the locked pipeline. (a) `colab_finetune_qwen3_0p6b.py` — duplicate of `colab_finetune.py` with `MODEL_NAME=unsloth/Qwen3-0.6B-unsloth-bnb-4bit`, `LORA_R=8` (16 over-fits 0.6B on 60k rows; matches the proven config in `local_finetune_qwen3_0p6b_gtx1650.py`), `OUTPUT_DIR=…/unsloth_qwen3_0p6b_parser_run`. All 2026-05-09 trainer fixes carried over: `train_on_responses_only`, `packing=False`, `MAX_SEQ_LENGTH=1536`. (b) `colab_convert_to_gguf_qwen3_0p6b.ipynb` — duplicate of the 1.7B convert notebook with `BASE_MODEL_HF=Qwen/Qwen3-0.6B`, output `qwen3-0.6b-parser-q4_k_m.gguf` (~400 MB vs 1.1 GB for 1.7B). Architecture-agnostic merge / convert / quantize steps unchanged. (c) `kaggle_finetune_qwen3_0p6b.ipynb` — Kaggle fallback variant; same 0.6B + r=8 + trainer-fix config. (d) `kaggle_finetune_qwen3_0p6b.py` — `.py` mirror of the Kaggle notebook for terminal-style cells. The 0.6B `.py` also adds an explicit GPU pin via `os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")` placed before any `import torch` / `import unsloth` so Kaggle's "T4 x2" accelerator only exposes one GPU to the runtime (avoids accelerate's `device_map="auto"` silently sharding across both GPUs and the LoRA optimizer-state imbalance that occasionally OOMs the second T4 mid-epoch).
   - **Android multi-model picker so 1.7B and 0.6B coexist on phone.** New `data/ModelRegistry.kt` discovers any `qwen3-<size>-parser-q4_k_m.gguf` under the app's `models/` folder via regex (`Regex("""qwen3-[0-9]+\.[0-9]+b-parser-q4_k_m\.gguf""")`) and remembers the user's selection in `runtime_state` (key `selected_model`, JSON `{"filename": "..."}`). `resolveSelected(db, modelDir)` returns the saved choice if still present → first discovered → null. `AppStartup.kt` now uses `ModelRegistry.resolveSelected(...)` instead of the hardcoded `qwen3-1.7b-parser-q4_k_m.gguf` constant; the load-status toast shows the actual filename. `SettingsViewModel` gains `availableModels: List<String>` + `selectedModel: String?` + `refreshAvailableModels(modelDir)` + `selectModel(modelDir, filename)` (persists choice → `LlamaCpp.forceUnload()` → reloads the new file → re-scans). `SettingsScreen` adds an "Available parser models" section under the existing Model row: one `RadioButton` per discovered GGUF; tap a non-active row to switch in-place. The hardcoded `MODEL_FILENAME` constant in SettingsScreen renamed to `DEFAULT_MODEL_FILENAME` and demoted to an empty-state hint only — once any GGUF is in the folder the registry takes over. Import-help text updated to document that both `qwen3-1.7b-…` and `qwen3-0.6b-…` can coexist. Build verified: `BUILD SUCCESSFUL in 1m 20s`.
   - **Action queue:** (1) train the 0.6B adapter via `kaggle_finetune_qwen3_0p6b.py` or `colab_finetune_qwen3_0p6b.py`; (2) convert to GGUF via `colab_convert_to_gguf_qwen3_0p6b.ipynb`; (3) push `qwen3-0.6b-parser-q4_k_m.gguf` into the app's `models/` folder alongside the existing 1.7B file; (4) Settings → tap the 0.6B radio row to switch; (5) measure tok/s and reliability deltas via `Activity log → Copy logs` (`prefill_us`, `decode_us_total`, `tokens_out` are already captured per request). Expected: ~3× faster decode (~25-30 tok/s vs ~10 tok/s on Pixel 7); reliability drop on multi-record buy/expense (records:[] length ≥ 4) and Tanglish edge cases.

- 2026-05-10 — **Project published to GitHub: https://github.com/humorouslydistracted/second-brain (public).** Followed `C:\Users\myuva\Documents\github_upload_guide.md` end-to-end and modeled README/LICENSE/release format on the reference repo `humorouslydistracted/isaivazhi`. Steps performed:
   1. **Decisions taken** — repo name `second-brain`, public, code-only scope (all datasets / model snapshots / venvs excluded), `gh` CLI installed via winget, release tags use date-based `vYYYY.MM.DD` format (matches the reference repo's latest convention).
   2. **`.gitignore` written** covering: `.venv*/`, `__pycache__/`, `android/build/`, `android/app/build/`, `android/.gradle/`, `android/.cxx/`, `.claude/`, `.tmp/`, `artifacts/`, `*.log`, `logs.txt`, `*.db`, `models/`, `*.gguf`, `*.safetensors`, `*.onnx`, `*.pkl`, `lora_adapter/`, `unsloth_qwen3_parser_run*/`, `unsloth_compiled_cache/`, `finetuned-*/`, `minilm_export/`, `synthetic_finetune_dataset_*/`, `sample_finetune_dataset_*/`, `eval_finetune_dataset_*/`, `synthetic_dataset_assets_copy.py`, `*.apk`, `*.aab`, `releases/`, `.env`, `*.pem`, `*.key`, `PAT`, `PAT.txt`, `*.token`, `_pat.tmp`. Total staged after this: 133 files, 2.21 MB. Sanity check confirmed no sensitive patterns matched.
   3. **`LICENSE` written** — MIT, `Copyright (c) 2026 Yuvaraj M P` (mirrors the reference repo).
   4. **`README.md` written** — sections: tagline, Core, Surfaces, Stack, Getting started (sideload + scoped-storage model push), Building from source (points to `android_port.md` § BUILD GUIDE), Repository layout, Status, License. Modeled on the isaivazhi structure.
   5. **`gh` CLI install** — `winget install --id GitHub.cli --accept-source-agreements --accept-package-agreements --silent`. Installed at `C:\Program Files\GitHub CLI\gh.exe`. Already on PATH for new shells; existing shells must call by full path until restart.
   6. **PAT auth** — user dropped a PAT file at the project root (`PAT`, gitignored). First token returned 401 (likely older one); user regenerated with `repo` scope and `cat PAT | gh auth login --hostname github.com --git-protocol https --with-token` succeeded. Verified token via `curl -s -H "Authorization: Bearer $(cat PAT)" https://api.github.com/user` returned `"login": "humorouslydistracted"` before feeding to gh. `gh auth setup-git` wired the credential helper so plain `git push` uses the same token.
   7. **`git init` + initial commit + push** — `git init`, `git branch -M main`, `gh repo create humorouslydistracted/second-brain --public --source=. --remote=origin --description "..."`, `git add -A`, `git commit -m "Initial commit ..."`, `git push -u origin main`. Push completed cleanly.
   8. **Release** — `gh release create v2026.05.10 android/app/build/outputs/apk/debug/app-debug.apk --title "Build 2026-05-10" --notes-file .tmp/release_notes.md --target main`. APK is 53 MB (build #28 + the 2026-05-10 NotesDao fix). Release URL: https://github.com/humorouslydistracted/second-brain/releases/tag/v2026.05.10.
   - **Future-update happy path** documented in the session: `git add -A; git commit -m "..."; git push` for code; for a new APK release, `gradlew.bat --no-daemon assembleDebug` then `gh release create v$(Get-Date -Format yyyy.MM.dd) "android\app\build\outputs\apk\debug\app-debug.apk" --title "Build $(Get-Date -Format yyyy-MM-dd)" --notes "What changed."`. PAT file stays gitignored, so it'll never push by accident.
   - **One pitfall worth keeping in mind:** the first PAT (Apr-22-dated 40-byte `ghp_…` token) returned `401 Bad credentials` from GitHub itself, not from gh — the file looked structurally fine. Diagnosis was `curl https://api.github.com/user` directly with the token. Likely cause was that the file held an older PAT that had since been revoked or replaced, despite the user believing it was fresh. Always validate a PAT against `/api.github.com/user` before assuming the auth tool is at fault.

