# Current State â€” Quick Orientation

Short navigation doc. Use this to find your way around. The full reasoning lives in:
- `project_development.md` â€” full development tracker (where + why)
- `finetuning_data_sanity.md` â€” locked v1 lane behavior + frozen training schema
- `dataset_india_context_rulebook.md` â€” synthetic dataset diversity / India-first rules

This doc is a pointer index, not a replacement.

---

## Where we are (one paragraph)

Fully local Android second-brain note-taking app, currently dogfooded as a Flask web app. The baseline live runtime is still the old tier-0 grammar + memoized fast-path + LLM planner, but there is now a **feature-flagged fine-tuned parser path** for tagged lanes (`expense:` / `buy:` / `todo:` / `weight:` / `ledger:` / `ask:`). That path loads the `Qwen3-1.7B` LoRA adapter, validates the frozen v1 JSON schema at runtime, executes deterministic SQLite writes/queries, and persists follow-up query context for later `ask:` refinements. The fine-tune already completed on Colab; eval was paused at 100 of 500 held-out cases when free-tier GPU ran out.

---

## End-to-end target flow

```
user input + chip lane (expense:/todo:/buy:/weight:/ledger:/note:/ask:)
    â”‚
    â–¼
fine-tuned Qwen3-1.7B (LoRA adapter) parses INSIDE that lane
    â”‚  emits strict v1 JSON
    â–¼
parse_write { lane, disposition, reason_code, records[] }
parse_query { domain, intent, date_start, date_end, compare_*, filters, limit, query_text }
parse_followup_query { â€¦, inherit_context: true }
    â”‚
    â–¼
Kotlin / SQLite executes the structured operation
    â”‚
    â–¼
Result rendered in natural language back to the user
```

`note:` is a deterministic app bypass and is **not** sent to the parser for writes. Note retrieval still goes through the parser's query schema.

---

## Fine-tune artifact (use this one)

Path:
```
unsloth_qwen3_parser_run-20260506T070456Z-3-002/
â””â”€â”€ unsloth_qwen3_parser_run/
    â”œâ”€â”€ lora_adapter/                   â† USE THIS (PEFT adapter folder)
    â”‚   â”œâ”€â”€ adapter_config.json
    â”‚   â”œâ”€â”€ adapter_model.safetensors
    â”‚   â”œâ”€â”€ chat_template.jinja
    â”‚   â”œâ”€â”€ tokenizer.json
    â”‚   â””â”€â”€ tokenizer_config.json
    â”œâ”€â”€ lora_adapter_unsloth/           â† Unsloth-merged LoRA (alt format, not preferred)
    â”œâ”€â”€ checkpoint-491/                 â† optional, only useful for resume/debug
    â”œâ”€â”€ converted_dataset/              â† formatted training rows used in this run
    â””â”€â”€ README.md
```

- Base model: `unsloth/Qwen3-1.7B-bnb-4bit`
- Standalone `model-001.safetensors` at the repo root is **not sufficient on its own** for the runtime path; the adapter folder above is what we depend on.

---

## Training dataset used

Path: `synthetic_finetune_dataset_v3_large_india_first/`

| Subdir | Files | Rows | Used in SFT? |
|---|---|---:|---|
| `parse_write/` | expense, buy, todo, weight, ledger | 5 Ã— 4000 = 20000 | âœ… |
| `parse_query/` | note, expense, buy, todo, weight, ledger | 6 Ã— 4000 = 24000 | âœ… |
| `parse_followup_query/` | mixed_followups | 5000 | âœ… |
| `reference_only/` | note_write_reference | 4000 | âŒ excluded |

`reference_only/` was excluded from the actual SFT run as well as the later revised Colab script, because `note:` write behavior is deterministic and app-controlled. Note retrieval stays in `parse_query/note.jsonl`.

Important provenance note: the adapter currently referenced in this file was trained with `colab_finetune_old.py`, not the current `colab_finetune.py`. The current `colab_finetune.py` is a later revised script and should not be treated as the exact historical run config unless a new adapter is trained from it.

Generator note: the dataset/eval generators now use explicit coverage seeding plus post-generation shuffle/interleaving. The goal is that rare but important slices such as reject cases, note day-bucket/date queries, recent-expense queries, and due-this-week todo queries are always present instead of relying on luck from pure random sampling.

Anchor date for synthetic relative-date resolution: `2026-05-05`.
India:Global ratio target across lanes: **70:30**.

### What the rows look like

`parse_write/expense.jsonl`:
```json
{"input": "expense: 138.34 tea kaasu, 2,145:visiting card print next monday",
 "output": {"task": "parse_write", "lane": "expense", "disposition": "accept", "reason_code": null,
            "records": [{"description": "tea kaasu", "amount": 138.34, "date": "2026-05-11", "group": "dining"},
                        {"description": "visiting card print", "amount": 2145, "date": "2026-05-11", "group": "work"}]}}
```

`parse_query/expense.jsonl` (Tanglish):
```json
{"input": "ask: indha maasam Parachute shampoo expense evalo",
 "output": {"task": "parse_query", "domain": "expense", "intent": "total",
            "date_start": "2026-05-01", "date_end": "2026-05-31",
            "compare_date_start": null, "compare_date_end": null,
            "filters": {"group": null, "description_text": "Parachute shampoo",
                        "exclude_group": null, "exclude_description_text": null},
            "limit": null, "query_text": null}}
```

`parse_followup_query/mixed_followups.jsonl` (carries prior context):
```json
{"context": {"task": "parse_query", "domain": "weight", "intent": "trend", ...},
 "input": "ask: just latest",
 "output": {"task": "parse_followup_query", "domain": "weight", "intent": "latest",
            "filters": {"person_text": "Dileep"}, "inherit_context": true, ...}}
```

Schema details (allowed intents, filter shapes, exclusions) are in `finetuning_data_sanity.md` â†’ "Shared Schema Freeze v1".

---

## Actual training run config (from `colab_finetune_old.py`)

| Field | Value |
|---|---|
| Base | `unsloth/Qwen3-1.7B-bnb-4bit` |
| LoRA r / alpha | 16 / 16 |
| Target modules | q,k,v,o + gate,up,down |
| LR | 2e-4 |
| Epochs | 1 |
| Per-device batch | 8 |
| Grad accum | 2 |
| Max seq len | 1024 |
| Packing | on |
| Training rows | all loaded training rows (`TRAIN_ON_ALL_SAMPLES = True`; no `MAX_TRAIN_ROWS` cap) |
| Internal split | none |
| Seed | 3407 |

Chat-template framing during training:
```
system:    "You are a parser for a tag-first personal data app. Return JSON onlyâ€¦"
user:      <input>          (or context block + "User input:\n<input>" for follow-ups)
assistant: <output JSON, no spaces>
```

For inference we must apply the **same** chat template, with `enable_thinking=False`, `do_sample=False`, and about `256` max new tokens.

`colab_finetune.py` is a later revised script with different Drive paths and different training controls, including `MAX_TRAIN_ROWS = 4000`, `per_device_train_batch_size = 4`, and `gradient_accumulation_steps = 4`. Do not cite that revised file as the source of the current adapter/eval numbers unless a fresh run is produced from it.

`reference_only/` still stays out of parser SFT. Those rows have `reference_behavior`, not parser `output` JSON, and they document deterministic `note:` save behavior rather than the parser tasks (`parse_write`, `parse_query`, `parse_followup_query`). The correct fix path for note-date retrieval gaps is stronger `parse_query/note` coverage, not teaching the model the `reference_only` schema.

---

## Evaluation run done so far

Path: `finetuned-20260506T072627Z-3-001/finetuned/`
- `predictions.jsonl` â€” 100 rows
- `summary.json` â€” aggregated metrics

What was actually evaluated: `--limit 100` of `eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl`. The first 100 ids fall on the **parse_write head only**:

| Lane | Cases | Notes |
|---|---:|---|
| expense | 40 | |
| buy | 40 | |
| todo | 20 | |
| ledger | 0 | not yet evaluated |
| weight | 0 | not yet evaluated |
| parse_query | 0 | not yet evaluated |
| parse_followup_query | 0 | not yet evaluated |

Headline metrics on those 100 parse_write cases:

| Metric | Score |
|---|---:|
| valid_json | 100% |
| task_match | 100% |
| lane_match | 100% |
| disposition_match | 100% |
| reason_code_match | 100% |
| record_count_match | 100% |
| amounts_match (40 expense applicable) | 100% |
| write_dates_match | 100% |
| unit_text_match (40 buy applicable) | 100% |
| **exact_match** | **91%** |

The 9 exact-match misses are all expense **`group`** disagreements (e.g. `auto kaasu` â†’ `vehicle` vs gold `transport`; `juice kadai bill` â†’ `bills_utilities` vs gold `dining`; `tenant association fee` â†’ `other` vs gold `bills_utilities`). All other fields perfect.

**What this leaves uncovered (next GPU session):**
- ledger writes (action: `add_debt | add_credit | repay_debt | collect_credit | settle`, amount nullable for settle)
- weight writes (self-mapping for nameless inputs)
- all of `parse_query` (intents, resolved date ranges, filter shapes, exclusion semantics)
- all of `parse_followup_query` (inherit_context, range/filter override behavior)

### Local 43-prompt preset run (covers the gaps above)

Detailed results: `preset_run_analysis.md`. Raw streaming log: `preset_run.log`.

Summary on a curated set covering ledger writes, weight writes, all 6 query domains, and 3 follow-ups (run on local GTX 1650 with the same adapter):

- Valid JSON: **43/43**
- Functionally correct vs spec: **~33/43 (77%)**
- All 5 ledger actions land correctly; `disposition: confirm + ambiguous_direction` fires correctly for `gave/received` phrasings.
- Self-mapping for nameless weight, Tanglish parsing, exclusion semantics (`apart from`), compare-range resolution (`compare this and last month`), and follow-up context inheritance all worked.
- Real gaps surfaced for the next training round: (a) `disposition: reject` for incomplete expense/todo not learned (model accepts with `null` amount instead), (b) date filtering on note queries does not resolve to `date_start/date_end` (gets stuffed into `query_text`), (c) one domain hallucination (`"due"` for `what is due this week`), (d) `recent` mapped to `total` instead of `list+limit`. The earlier `MAX_TRAIN_ROWS=4000` explanation should no longer be trusted here, because the tested adapter came from `colab_finetune_old.py`, which trained on all loaded rows. The root cause is still open: likely data-mix/coverage weakness, one-epoch limits, or later script drift, but not a simple 4k-cap issue.

Latency on the GTX 1650: 14.3 s/prompt average (4-bit, fp16 fallback, no Flash Attention since 1650 is sm_75 / Turing). Not the on-device target â€” Pixel 7 + llama.cpp curve will differ.

---

## How to run the scripts

### Reproduce the historical training run (Colab)
```python
# In a Colab notebook with T4/L4 attached:
%run colab_finetune_old.py
```
Use this when the goal is to reproduce or compare against the adapter lineage currently documented in this file. The important knobs are `DATASET_ROOT`, `OUTPUT_DIR`, and `MODEL_NAME`.

### Revised Colab training script (separate experiment path)
```python
# Later revised script; not the historical 2026-05-06 run
%run colab_finetune.py
```
This script was modified later and adds different defaults, including `MAX_TRAIN_ROWS = 4000`. Treat runs from it as new experiments and record them separately from the current adapter lineage.

### Re-run evaluation (Colab, GPU)
```bash
python evaluate_finetune.py \
  --finetuned-model /content/drive/MyDrive/unsloth_qwen3_parser_run/lora_adapter \
  --finetuned-base-model unsloth/Qwen3-1.7B-bnb-4bit \
  --dataset eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl \
  --output-dir eval_run_outputs
```
Drop `--limit 100` to run the full 500 cases and finally cover query + follow-up slices.

### Local inference

Helper: `infer_finetuned_parser.py` (Unsloth + peft + bitsandbytes 4-bit).

Run it from the dedicated GPU env, not from `.venv` (which is Python 3.14 + CPU-only torch and cannot host Unsloth):

```powershell
# one-time setup (Python 3.10, CUDA 12.4 torch, Unsloth, peft, bitsandbytes)
# follow the install order at the top of requirements_local_qwen3_finetuned_windows.txt
py -3.10 -m venv .venv-qwen3-1p7b-1650
.\.venv-qwen3-1p7b-1650\Scripts\Activate.ps1
# â€¦ then the 8-step install in that requirements file â€¦

# run
python infer_finetuned_parser.py --preset       # 45 curated prompts covering uncovered slices
python infer_finetuned_parser.py                # interactive REPL
python infer_finetuned_parser.py --prompt "expense: tomato 40, bus fare 18 yesterday"
```

Driver/CUDA matching:
- This machine has driver 555.99 (CUDA 12.5) â†’ use **cu124** torch wheels (cu128 will load but fail).
- Other machines: see the cu124/cu128/cu121 guide at the top of `requirements_local_qwen3_finetuned_windows.txt`.

Why a separate env (don't merge into `.venv`):
- Unsloth and bitsandbytes have no Python 3.14 wheels.
- CUDA torch can't coexist with the CPU-only torch already in `.venv`.
- The Flask `.venv` should stay light and fast.

### Live parser integration in the Flask app

The feature-flagged runtime path is now wired in:
- parser runtime wrapper: `second_brain_finetuned_parser.py`
- orchestrator hook: `second_brain_orchestrator.py`
- DB/runtime support: `second_brain_core.py`

What the live path currently does:
- `note:` still stays deterministic and bypasses the parser.
- Tagged writes (`expense:` / `buy:` / `todo:` / `weight:` / `ledger:`) hit the fine-tuned parser first.
- Tagged queries (`ask:`) hit the fine-tuned parser first and save the structured query context in `runtime_state`, so short follow-ups such as `ask: only tea` can inherit the prior query.
- Runtime guardrails reject invalid parser payloads, out-of-shape enums, and impossible follow-up-without-context cases before they reach SQL.
- New storage support added for this path: `buy_items` table, `runtime_state` table, and `expenses.group_name`.

To dogfood it locally, run the Flask app from the dedicated GPU env:

```powershell
.\.venv-qwen3-1p7b-1650\Scripts\Activate.ps1
python -m pip install -r requirements_local_qwen3_finetuned_windows.txt
$env:SECOND_BRAIN_FINETUNED_PARSER_ENABLED='1'
$env:SECOND_BRAIN_SELF_PERSON='jeevi'   # optional, but recommended for nameless `weight:` writes
python app.py
```

Runtime compatibility note for this machine:
- The parser loader now prefers the cached local snapshot of `unsloth/Qwen3-1.7B-bnb-4bit` when it exists.
- The `transformers` backend now hides `torchao` during model load, because the cached base model is a bitsandbytes 4-bit model and the installed `torchao` package in `.venv-qwen3-1p7b-1650` is not compatible with the torch 2.6 CUDA stack used here.
- This fixes the earlier live-app error that mentioned `Unsloth: torch==2.10.0 requires torchvision>=0.25.0` and the follow-on `torch.utils._pytree.register_constant` failure.
- Verified live path: `weight: 75kg` now loads the adapter and routes through the fine-tuned parser successfully in the orchestrator.

Optional runtime overrides:
- `SECOND_BRAIN_FINETUNED_PARSER_ADAPTER` â€” custom adapter folder path
- `SECOND_BRAIN_FINETUNED_PARSER_BASE_MODEL` â€” custom base model
- `SECOND_BRAIN_FINETUNED_PARSER_MAX_SEQ_LENGTH`
- `SECOND_BRAIN_FINETUNED_PARSER_MAX_NEW_TOKENS`

If the app is launched from the normal `.venv` instead of the GPU env, the fine-tuned parser path will not load successfully because Unsloth / CUDA torch are not installed there.

---

## v2 dataset / fine-tune progress (in flight)

Canonical plan: `dataset_v2_plan.md`. Schema target: `finetuning_data_sanity.md` -> "Shared Schema Freeze v2".

Phase 2 (per `dataset_v2_plan.md` §9) — **all 8 steps done**:
- Steps 1-2 (doc updates) - done.
- Step 3 (`synthetic_dataset_assets.py` Tanglish key constants + drop ledger-reason imports from v2 path) - done.
- Step 4 (v2 generator `generate_large_schema_frozen_dataset_v2.py`) - done.
- Step 5 (`evaluate_finetune.py` v2 schema scoring + per-row `Today: <anchor_date>` injection at inference; per-row schema routing keeps v1 eval files working) - done.
- Step 6 (`generate_eval_dataset_v3.py` new file; output `eval_finetune_dataset_v3_schema_frozen/`; uses `pick_anchor_iso` so eval rows inherit per-row anchor randomization) - done.
- Step 7 (`colab_finetune.py` injects `Today: <anchor_date>` during chat-template formatting; v1 rows without `anchor_date` keep historical framing byte-identical). The previous "later revised" `colab_finetune.py` was deleted; the historical-config script (formerly `colab_finetune_old.py`) was renamed to `colab_finetune.py`. There is now a single Colab training script - done.
- Step 8 (`second_brain_finetuned_parser.py` injects `Today: <real_today>` at every inference, gated by `SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION` env flag, default off so the v1 adapter path is unchanged) - done.

Phase 3 (review pass + asset expansion, post §9 — see `dataset_v2_plan.md` §13):
- `synthetic_dataset_assets.py` bug fixes: missing comma in `TANGLISH_SINGLE_DATE_KEYS`, `04-31` -> `04-30` in two Tanglish range entries, dropped `INDIA_EXPENSE["work"|"education"]` extends to `INDIA_BUY` (no more `school building fund` / `certificate attestation` / `cowork day pass` in buy accept rows), dropped `_TANGLISH_TRANSPORT` / `_TANGLISH_DINING` / `_TANGLISH_VEHICLE` / `_TANGLISH_LEDGER` (the kasu lists).
- v2 generator additions: anchor day-of-month randomization per row (year stays 2026), substring-overlap filter on buy multi-entry, ledger balance perspective fix (templates split into NEUTRAL / I_OWE / THEY_OWE buckets), `kaatu` / Pattern C purge from all query templates, time-of-day phrasings stripped from query date pools (kept for writes), ledger query templates rewritten away from literal "ledger" word, BUY_PREFIX/TRIPLE Pattern B/C entries dropped, other query template pools widened ~30-50%.
- Asset pool expansion (~2x): names 462+170 -> 707+376; note topics 385+180 -> 631+329; INDIA_BUY 546 -> 1235; expense per-group roughly doubled or +50% (small groups doubled, big groups bumped); todos / todo_nouns +120-200 each; Tanglish notes / todos / groceries / household / personal_care also expanded; brand x product seeds widened. All extends route through `_extend_unique` plus a final `_dedup_inplace` pass.
- A 100/lane review generation was produced and analyzed clean: 0 schema violations across 1300 rows, 0 regressions across all Phase 1 + 2 fixes, 154 distinct anchor dates across 1300 rows, 98/98 date resolutions correct, all special slices firing as designed.

The v1 generator (`generate_large_schema_frozen_dataset.py`) and the v3 dataset on disk (`synthetic_finetune_dataset_v3_large_india_first/`) remain unchanged. The current Qwen3-1.7B adapter still consumes v1 / v3 and is unchanged.

Current state on disk:
- `synthetic_finetune_dataset_v4_v2_schema/` is the **100/lane review generation** (1300 rows total; clean per `dataset_v2_plan.md` §13.4). The full 4000/lane training run has NOT been executed.

To run the full v2 generation when ready: `python generate_large_schema_frozen_dataset_v2.py --write-count 4000 --query-count 4000 --followup-count 4000` (writes back to `synthetic_finetune_dataset_v4_v2_schema/`).
To regenerate the v3 held-out eval set: `python generate_eval_dataset_v3.py` (writes `eval_finetune_dataset_v3_schema_frozen/`).

---

## Next steps (in priority order)

1. **Generate the full-scale v4 dataset.** `python generate_large_schema_frozen_dataset_v2.py --write-count 4000 --query-count 4000 --followup-count 4000`. ~5 min. Will overwrite the current 100/lane review sample. The dataset content / generator behavior is locked in by Phase 3.
2. **Generate the v3 held-out eval set.** Configurable size via `--total <N>` so you can pick a smaller eval if Colab GPU budget is tight: `python generate_eval_dataset_v3.py --total 50` (47 rows, 3-4 per lane / domain), `--total 100` (exactly 100), `--total 500` (exactly 500, matches the historical default). The split is 40% writes / 42% queries / 18% followups with a hard floor of 1 row per lane / domain so every file is represented at any total. Per-bucket flags (`--write-per-lane`, `--query-per-domain`, `--followup-count`) still override individual buckets. De-dups against the v4 training root.
3. **Queue the v2 fine-tune (Kaggle preferred).** Colab free-tier GPU is too restrictive for this run; the primary path is now Kaggle. Use `kaggle_finetune.ipynb` (pre-built, runs out of the box on a Kaggle T4 / P100 kernel — upload the v4 dataset as a Kaggle dataset, attach to the kernel, click Run all). The chat-template framing change (`Today: <anchor_date>` in the system message) is automatic in the notebook and is now the contract for any v2-trained adapter — match it at inference. Local fallback: `colab_finetune.py` is still maintained and runs on Colab T4/L4 if needed.
4. **Run full v3 eval against the new adapter.** Two paths:
   - **Kaggle**: `kaggle_evaluate.ipynb` — attach the eval dataset + the saved-version output of `kaggle_finetune.ipynb` as inputs, run all cells. Smoke first with `LIMIT = 20`.
   - **Local / Colab**: `python evaluate_finetune.py --dataset eval_finetune_dataset_v3_schema_frozen/heldout_cases.jsonl --finetuned-model <new adapter> --finetuned-base-model unsloth/Qwen3-1.7B-bnb-4bit`.

   Either way, you get real numbers on `disposition_match` / `clarify_reason_match` / `clarify_options_match` / `reason_code_match` plus the existing per-lane metrics.
5. **Flip the runtime `Today:` injection on for the new adapter.** `SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION=1`. Confirm `status()` reports `today_injection_enabled: true`.
6. **Dogfood the integrated parser path** with the v2 adapter. Run the Flask app from `.venv-qwen3-1p7b-1650`, turn on `SECOND_BRAIN_FINETUNED_PARSER_ENABLED=1`, collect real failures from tagged inputs.
7. **Latency / deployment.** Once parser behavior is stable, move to GGUF / llama.cpp / Android-oriented latency work.
8. **Optional 0.6B A/B test.** Train the smaller model via `kaggle_finetune_qwen3_0p6b.py` (or the Colab `.py` / Kaggle `.ipynb` variants), convert via `colab_convert_to_gguf_qwen3_0p6b.ipynb`, push the resulting `qwen3-0.6b-parser-q4_k_m.gguf` into the phone's models dir alongside the 1.7B file. Settings now lists both — switch via radio rows. Compare reliability + tok/s using existing `Activity log → Copy logs` per-request stats (`prefill_us`, `decode_us_total`, `tokens_out`). Expected: ~3× faster decode (~25-30 tok/s vs ~10 tok/s on Pixel 7); reliability drop on multi-record outputs and Tanglish.

Optional follow-ups deferred to v3 plan (only if real failures show them):
- Trim ledger literal-"ledger" word usage further (currently 38%, soft target was ≤30%).
- Widen buy / todo list templates (peak repeat 5× / 4× per 100 rows).
- Repopulate empty query-template `tanglish_a` buckets if Pattern A surface in queries proves too low.

---

## File pointers (quick reference)

| Concern | File / folder |
|---|---|
| Project tracker (long) | `project_development.md` |
| Lane behavior + frozen schema | `finetuning_data_sanity.md` |
| Synthetic dataset rules | `dataset_india_context_rulebook.md` |
| Live web app | `app.py`, `templates/`, `static/` |
| Orchestrator (tier 0 + planner + tier 1) | `second_brain_orchestrator.py` |
| Shared parser/SQL/RAG/LLM logic | `second_brain_core.py` |
| Fine-tuned parser runtime wrapper | `second_brain_finetuned_parser.py` |
| Read-only SQL safety gate | `sql_safety.py` |
| MCP server / client | `second_brain_mcp_server.py`, `second_brain_mcp_client.py` |
| Local DB | `second_brain.db` |
| GGUF + embedding cache | `models/` |
| Colab training script | `colab_finetune.py` (historical-config script + `Today: <anchor_date>` injection; previously named `colab_finetune_old.py`. The earlier "later revised" `colab_finetune.py` was deleted in the Phase 2 §9 step 7 work.) Local / Colab fallback only — Kaggle is the primary fine-tune path. |
| Kaggle notebooks (primary fine-tune path) | `kaggle_finetune.ipynb` (mirrors `colab_finetune.py` with `/kaggle/input/` + `/kaggle/working/` paths and no Drive mount), `kaggle_evaluate.ipynb` (mirrors `evaluate_finetune.py` CLI with a notebook config cell + inlined v2-schema scoring helpers). Both validate as nbformat 4.5 and are runnable out of the box on a T4 / P100 kernel after editing the CONFIG cell. |
| Eval script | `evaluate_finetune.py` (v2 schema scoring + per-row `Today:` injection from `anchor_date`) |
| Held-out eval set (v1 schema, legacy) | `eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl` |
| Held-out eval set (v2 schema) | `eval_finetune_dataset_v3_schema_frozen/heldout_cases.jsonl` (regenerate via `generate_eval_dataset_v3.py`) |
| Dataset generators (v1) | `generate_large_schema_frozen_dataset.py`, `generate_eval_dataset_v2.py`, `synthetic_dataset_assets.py` (asset file is shared between v1 and v2) |
| Dataset generator (v2) | `generate_large_schema_frozen_dataset_v2.py` (writes `synthetic_finetune_dataset_v4_v2_schema/`); `generate_eval_dataset_v3.py` for the v2-schema eval set |
| Local 0.6B path (laptop) | `local_finetune_qwen3_0p6b_gtx1650.py`, `local_evaluate_qwen3_0p6b_gtx1650.py`, `create_local_qwen3_0p6b_env.ps1`, `requirements_local_qwen3_0p6b_windows.txt` |
| 0.6B fine-tune scaffolding (Colab/Kaggle, A/B vs 1.7B) | `colab_finetune_qwen3_0p6b.py` (LORA_R=8, output `unsloth_qwen3_0p6b_parser_run/`), `colab_convert_to_gguf_qwen3_0p6b.ipynb` (BASE_MODEL_HF=`Qwen/Qwen3-0.6B`, output `qwen3-0.6b-parser-q4_k_m.gguf` ~400 MB), `kaggle_finetune_qwen3_0p6b.ipynb` + `kaggle_finetune_qwen3_0p6b.py` (the .py mirror also pins `CUDA_VISIBLE_DEVICES=0` before `import torch` so Kaggle T4 x2 only exposes one GPU). All four carry the 2026-05-09 trainer fixes (`train_on_responses_only`, `packing=False`, `MAX_SEQ_LENGTH=1536`). The 1.7B pipeline is untouched; both GGUFs can coexist on phone. |
| Android multi-model picker | `android/app/src/main/java/com/secondbrain/app/data/ModelRegistry.kt` (auto-discovers `qwen3-<size>-parser-q4_k_m.gguf` in the app's models dir, persists user's choice to `runtime_state` key `selected_model`). `AppStartup.kt` + `SettingsScreen.kt` consume it — Settings gets one radio row per discovered GGUF; tap to switch (force-unloads current, loads selected). |
| Stress harnesses | `test_independent_500.py`, `test_replay_matrix*.py`, `test_note_corpus_stress_200.py` |
| Regression suites | `test_orchestrator_tier0.py`, `test_routing_memory.py`, `test_logs_regression.py`, `test_activity_log_regression.py`, `test_flask_crud.py`, `test_sql_safety.py` |


