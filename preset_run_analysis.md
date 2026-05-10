# Fine-tuned Parser — First Local Inference Run

**Model:** `unsloth/Qwen3-1.7B-bnb-4bit` + LoRA adapter at `unsloth_qwen3_parser_run-20260506T070456Z-3-002/unsloth_qwen3_parser_run/lora_adapter/`
**Hardware:** GTX 1650 (4 GB), Windows 11, Python 3.10, torch 2.6.0+cu124
**Run:** `python -u infer_finetuned_parser.py --preset` (43 curated prompts, 614 s, 14.3 s/prompt)
**Raw log:** `preset_run.log`

The preset was specifically chosen to cover slices the 100-case Colab eval skipped: ledger writes, weight writes, all `parse_query` lanes, and `parse_followup_query` with prior context.

---

## Headline numbers

| Metric | Score |
|---|---:|
| Valid JSON | **43/43 (100%)** |
| Functionally correct vs spec | **~33/43 (77%)** |
| Soft / partial spec match | 4/43 (9%) |
| Clear failures | 6/43 (14%) |

The schema is solid. Failures are concentrated in a few specific behaviors that were probably under-represented in the 4 000-row training cap.

---

## Strong wins (parser learned these well)

### Ledger writes — all 5 actions + confirm flag

| Input | `action` | `disposition` | Result |
|---|---|---|---|
| `ledger: I owe Arun 500 for room rent` | `add_debt` | accept | ✅ note: "room rent" |
| `ledger: Bala owes me 1200` | `add_credit` | accept | ✅ |
| `ledger: borrowed 8k from appa for rent` | `add_debt` | accept | ✅ amount 8000, note: "rent" |
| `ledger: lent Kiran 900` | `add_credit` | accept | ✅ |
| `ledger: paid Arun back 500` | `repay_debt` | accept | ✅ |
| `ledger: Bala returned 1200` | `collect_credit` | accept | ✅ |
| `ledger: settled with Kiran` | `settle` | accept | ✅ amount: null (per spec) |
| `ledger: gave Maddy 5k` | (provisional `add_credit`) | **confirm** | ✅ `reason_code: ambiguous_direction` |

This is exactly the locked spec: clear directions auto-accept, `gave/received` triggers `confirm + ambiguous_direction`. The "5k" → 5000 conversion also handled.

### Weight writes — self-mapping + multi-entry + context

| Input | Result |
|---|---|
| `weight: 72.4` | `person_text: "self"`, value 72.4, unit kg, note null ✅ |
| `weight: 72.4 before breakfast` | `person_text: "self"`, note: "before breakfast" ✅ |
| `weight: Arun 72.4 before breakfast` | `person_text: "Arun"`, note: "before breakfast" ✅ |
| `weight: mom 64.1, dad 78.3 after walk` | both records, **but second name corrupted to "dada"** (single-token slip) |

The structural piece is right — multi-entry, optional context applied to the right record, kg unit defaulted. The `dad → dada` slip is a single-name corruption.

### Expense queries — date resolution and exclusion

| Input | `intent` | Date range resolved | Filters | Notes |
|---|---|---|---|---|
| `what is my total expense this month` | total | 2026-05-01 → 2026-05-31 | none | ✅ |
| `compare this month and last month` | compare | this: May 2026, **compare: April 2026** | none | ✅ both ranges resolved |
| `what did I spend on groceries in april` | total | 2026-04-01 → 2026-04-30 | group: groceries | ✅ |
| `show my expenses apart from groceries` | list | this month | exclude_group: groceries | ✅ exclusion semantic |
| `indha maasam parachute shampoo expense evalo` | total | this month | description_text: "parachute shampoo" | ✅ Tanglish |

Compare-range resolution is the impressive one — both date ranges came out correctly and intent was `compare`.

### Follow-ups — context inheritance perfect on all 3

| Prior context | Follow-up input | Result |
|---|---|---|
| expense total April 2026 | `of that how much was groceries` | inherits domain/intent/dates, adds `group: groceries`, `inherit_context: true` |
| weight history Arun last 6 months | `only from last month` | inherits domain/intent/person, narrows date to April 2026 |
| ledger list April 2026 | `only Arun` | inherits domain/intent/dates, adds `person_text: "Arun"` |

This is the hardest part of the schema and it landed cleanly on all three.

### Other wins worth noting

- `weight: <name> <kg>` history queries default to last 6 months and `limit: 5` for named persons (matches spec).
- `how much did Arun change since January` → `intent: change`, `date_start: 2026-01-01` ✅.
- `who owes me money` → `perspective: they_owe_me`, `status: open` ✅.
- `how much do I owe Arun` → `perspective: i_owe_them`, `status: open` ✅.
- `show open ledger with Kiran` → `intent: list`, `person_text: "Kiran"`, `status: open` ✅.

---

## Clear failures (worth retraining for)

### 1. Reject behavior is not learned in expense and todo lanes

Spec (locked in `finetuning_data_sanity.md`): incomplete inputs must produce `disposition: reject`, `reason_code: incomplete_input`, empty `records`.

| Input | Expected | Actual |
|---|---|---|
| `expense: apples` | reject + incomplete_input | **accept**, amount: null, group: groceries |
| `todo: tomorrow` | reject + incomplete_input | **accept**, text: "tomorrow", date: 2026-05-06 |
| `ledger: Arun 500` | reject (direction missing) | **confirm + ambiguous_direction** (closer to spec but not "reject") |

This is the biggest functional gap. Hypothesis: with `MAX_TRAIN_ROWS = 4000` (capped from a ~49 000 pool), the rare `disposition: reject` rows in expense/todo lanes were probably down-sampled to near-zero. Worth verifying by counting reject rows in the dataset.

### 2. Date filtering on note queries doesn't resolve

| Input | Expected | Actual |
|---|---|---|
| `what did I write yesterday` | `intent: day_bucket`, `date_start = date_end = 2026-05-04` | `intent: search`, dates null, `query_text: "what did I write about yesterday"` |

For non-note domains the model resolves dates correctly; note domain skips the resolution and stuffs the date phrase into `query_text` instead. Suggests the dataset's note query rows lean too heavily on `intent: search` with raw `query_text` and under-cover the `day_bucket` / `latest_bucket` intents with resolved date ranges.

### 3. Domain hallucination on "due this week"

| Input | Expected | Actual |
|---|---|---|
| `what is due this week` | `domain: todo`, `intent: list`, status: open | `domain: "due"` (invalid enum), `intent: total` |

This is the one case in the run where the model produced a domain that isn't in the allowed enum. Probably a spurious lift of "due" from the surface text. Easy to catch in the runtime guardrail (validate `domain` against the allowlist), but should also be addressed by adding more "due X" todo phrasings to training.

### 4. `recent` intent gets mapped to `total`

| Input | Expected | Actual |
|---|---|---|
| `show recent expenses` | `intent: list`, `limit: 10` | `intent: total`, no limit |

Spec says recent = last 10 entries. Model defaults to total-of-this-month. Needs more "recent X" examples in expense_query training.

---

## Soft / partial matches (not failures, but worth noting)

| Input | Spec | Actual | Comment |
|---|---|---|---|
| `show my notes` | `latest_bucket` (today's day bucket) | `intent: search`, `query_text: "my notes"` | search is in the allowed enum, but broad show-my-notes should default to latest_bucket |
| `show my todo list` | should default to `status: open` | `status: null` (returns both) | model under-applies the open-by-default rule |
| `who owes me money` | `intent: open_summary` | `intent: balance` | both are in the allowed enum; balance + perspective + status filter still produces the right answer downstream |
| `show my buy list` | `intent: list` | `intent: latest_day` | both reasonable; spec also says default = today's buy list, so latest_day is arguably fine |

---

## Latency

- **Model load:** 16 s (already-cached base model)
- **Per-prompt generation:** average **14.3 s** on the GTX 1650 with 4-bit weights, no Flash Attention (xformers not installed for 1.7B), `max_new_tokens=256`. The 1650 is sm_75 (Turing) and doesn't support bfloat16, so generation runs in fp16, which is the bottleneck.
- **Total run:** 614 s for 43 prompts.

Pixel 7 / llama.cpp would be a different curve (CPU + GGUF + smaller KV cache), so this latency is not the on-device target — it's just the local-dev iteration speed. Worth converting the adapter to GGUF and running through the existing llama.cpp setup once we want a representative number.

---

## What this changes about next steps

**Before** I'd treated the 91% exact-match write number as the headline. After this run, the priority list shifts:

1. **Re-train with all 49 000 training rows, not the 4 000-row cap** — the gaps in reject behavior, note query intents, and `recent` intent all smell like under-sampling, not architecture issues. The base model handles the schema; it just hasn't seen enough variety on certain rare paths.
2. **Add a runtime domain/intent allowlist guardrail** — `domain: "due"` slipped through; the app code should reject any out-of-enum domain/intent before executing SQL.
3. **Run the full 500-case held-out eval on this same adapter** — same `evaluate_finetune.py`, no `--limit 100`, on the same Colab session that loads the adapter. We finally get real numbers on `parse_query` and `parse_followup_query`.
4. **Wire the parser into the Flask app behind a feature flag** — even with the gaps, this adapter is good enough to dogfood. The reject failures fail safe (data still saved, just with `null` amount), and the runtime guardrail catches bad domains. Real failure logging during dogfooding will surface the cases that actually matter, then we re-train against those.
5. **Latency on Pixel 7** is a separate problem (GGUF conversion + llama.cpp); deferred until product behavior is locked.
