# Fine-Tuning Data Sanity Spec

Source-of-truth document for synthetic dataset preparation and later real-failure backfill.

Purpose:
- lock task behavior before generating large datasets
- keep labeling consistent across runs
- reduce schema drift and silent assumption changes

Current status:
- v1 schema produced the current `Qwen3-1.7B` adapter at `unsloth_qwen3_parser_run/lora_adapter`
- v2 schema is now active for the **next** dataset generation and the next fine-tune; canonical v2 plan lives in `dataset_v2_plan.md`
- v2 schema freeze is documented in this file under "Shared Schema Freeze v2 (active)" below; v1 freeze is preserved as historical reference
- lane-by-lane behavior locked for the main v1 lanes and retrieval paths still applies in v2 except for the items explicitly amended in the v2 schema section
- the schema-aligned held-out eval set at `eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl` is v1-schema; a v3 held-out set will be produced under v2 schema before the next fine-tune
- the correct adapter path for evaluation is the PEFT folder `unsloth_qwen3_parser_run/lora_adapter`; `lora_adapter_unsloth` is not the right default path for the evaluator's adapter-loading branch
- for backup/download purposes, the artifact to keep is the full `lora_adapter/` directory, not a standalone `.safetensors` file
- the base model name paired with that adapter is `unsloth/Qwen3-1.7B-bnb-4bit`
- write-side evaluation is now strongly validated on v1; v2 introduces new dispositions on `parse_query` (`clarify`, `reject`) and harmonized intents that need fresh eval coverage

General principles:
- behavior is locked here first, then data is generated
- product rules matter more than prompt cleverness
- synthetic data should stay close to real app usage
- runtime can use live context such as current date; dataset generation uses fixed anchors where needed

Working order:
1. lock behavior for each lane/tool here
2. freeze the shared training schema in one pass
3. generate larger synthetic datasets
4. validate fine-tuning quality by task slice, not only broad aggregate score
5. backfill with real failures later

## Shared Schema Freeze v1

Status: locked on 2026-05-06

This is the frozen shared schema for dataset generation.

### Global schema rules

- Query outputs use resolved absolute dates only.
- Use `date_start` / `date_end`, not relative strings like `last_month`.
- `ask:` may optionally carry a query-scope hint such as `auto`, `expense`, `buy`, `todo`, `weight`, `ledger`, or `note`.
- That scope hint is a runtime/UI input hint, not a separate required output field in v1.
- If a non-`auto` query scope is provided, the parsed `domain` should normally match that scope.
- If the chosen query scope and the actual query text strongly conflict, prefer clarification/rejection over silently switching domains.
- `note:` is a deterministic app bypass and is excluded from write-side fine-tuning.
- Note retrieval still remains part of the query schema.
- Do not add confidence scores.
- Do not add separate currency fields in v1.
- Do not add separate merchant/store fields in v1.
- Do not add separate time-of-day fields in v1.
- Preserve user-facing wording closely where lane rules require it.

### Top-level training tasks

Only three top-level tasks should be used for v1:
- `parse_write`
- `parse_query`
- `parse_followup_query`

Training-dataset rule:
- only rows from `parse_write/`, `parse_query/`, and `parse_followup_query/` belong in parser SFT
- `reference_only/` is for deterministic/reference behavior documentation and review, not for parser fine-tuning
- this is especially important for `note:` write behavior, which is intentionally app-controlled and excluded from write-side SFT
- schema-aligned evaluation should now use `eval_finetune_dataset_v2_schema_frozen/heldout_cases.jsonl` by default; `eval_finetune_dataset_v1/heldout_cases.jsonl` is legacy-only

### Write schema

```json
{
  "task": "parse_write",
  "lane": "expense | buy | todo | weight | ledger",
  "disposition": "accept | confirm | reject",
  "reason_code": null,
  "records": []
}
```

Rules:
- `records` may be empty only for `reject`
- `confirm` is used mainly for high-risk ledger phrasings
- `reason_code` is a short machine-friendly string or `null`

Example reason-code patterns:
- `incomplete_input`
- `ambiguous_direction`
- `invalid_lane_content`

### Write record schemas by lane

Expense:

```json
{
  "description": "plum vinegar",
  "amount": 410,
  "date": "2026-05-06",
  "group": "groceries"
}
```

Buy:

```json
{
  "item_text": "dove",
  "quantity_text": "3",
  "unit_text": null,
  "date": "2026-05-06"
}
```

Todo:

```json
{
  "text": "pay EB bill",
  "date": "2026-05-06"
}
```

Weight:

```json
{
  "person_text": "arun",
  "value": 72.4,
  "unit": "kg",
  "date": "2026-05-06",
  "note": "before breakfast"
}
```

Rules:
- nameless/self-style weight writes map to `person_text = "self"`

Ledger:

```json
{
  "person_text": "arun",
  "action": "add_debt | add_credit | repay_debt | collect_credit | settle",
  "amount": 500,
  "date": "2026-05-06",
  "note": "room rent"
}
```

Rules:
- `amount` may be `null` only for `settle`
- `settle` means clear the relationship to zero

### Query schema

```json
{
  "task": "parse_query",
  "domain": "note | expense | buy | todo | weight | ledger",
  "intent": "...",
  "date_start": null,
  "date_end": null,
  "compare_date_start": null,
  "compare_date_end": null,
  "filters": {},
  "limit": null,
  "query_text": null
}
```

Rules:
- `domain` is the canonical parsed query target.
- Optional UI/input scope such as `ask + expense` or literal `ask: expense:` does not require a new output field in v1.
- When a scope hint is present, `domain` should align with it unless the input is invalid or contradictory enough that the app should clarify.
- Plain `ask:` without a scope hint remains valid and should use normal domain detection.
- `compare_date_start` / `compare_date_end` are used only when `intent = "compare"`.

### Follow-up query schema

```json
{
  "task": "parse_followup_query",
  "inherit_context": true,
  "domain": "note | expense | buy | todo | weight | ledger",
  "intent": "...",
  "date_start": null,
  "date_end": null,
  "compare_date_start": null,
  "compare_date_end": null,
  "filters": {},
  "limit": null,
  "query_text": null
}
```

Rules:
- follow-up queries inherit prior context unless explicitly overridden
- follow-up outputs should still emit the fully resolved current query shape
- if a scoped query lane is active at runtime, follow-up parsing should keep that scope unless the user explicitly changes it
- `compare_date_start` / `compare_date_end` should be carried forward when the active context is a compare query unless the follow-up explicitly changes the comparison range

### Allowed query intents by domain

Note:
- `recent`
- `search`
- `latest_bucket`
- `day_bucket`

Expense:
- `total`
- `list`
- `compare`

Buy:
- `list`
- `search`
- `latest_day`

Todo:
- `list`
- `search`
- `history`

Weight:
- `latest`
- `history`
- `trend`
- `change`
- `latest_all`

Ledger:
- `balance`
- `list`
- `open_summary`
- `settled_list`
- `latest_balance`

### Expected filter shapes by domain

Note filters:

```json
{}
```

Use `query_text` plus date range for note retrieval in v1.

Expense filters:

```json
{
  "group": null,
  "description_text": null,
  "exclude_group": null,
  "exclude_description_text": null
}
```

Buy filters:

```json
{
  "status": "open | done | null",
  "item_text": null
}
```

Todo filters:

```json
{
  "status": "open | done | null",
  "text_match": null
}
```

Weight filters:

```json
{
  "person_text": null
}
```

Ledger filters:

```json
{
  "person_text": null,
  "perspective": "i_owe_them | they_owe_me | null",
  "status": "open | settled | null"
}
```

### Explicit exclusions from schema v1

Do not include these in v1:
- note write schema
- confidence fields
- separate currency fields
- merchant/store/location fields
- separate clock-time fields
- recurrence fields
- priority fields
- generic free-form category systems outside the locked lane behavior

### Transition note

`sample_finetune_dataset_v1/` was created before this schema freeze.
Treat it as illustrative only.
Large-scale generation should follow this frozen schema, not the older sample shapes.

## Shared Schema Freeze v2 (active for next training run)

Status: locked in this session; supersedes v1 for the next dataset generation and the next fine-tune.

The v1 frozen schema above produced the current adapter. v2 amendments below address concrete failures observed in `results.txt` (intent-name confusion across domains, missing dispositions on `parse_query`, untrained scoped-query share, and absent multi-person / action-shaped query handling). Anything not amended below is inherited from v1.

Canonical generator plan: `dataset_v2_plan.md`. This section is the schema-only summary that downstream training/eval/runtime code should target.

### v2 — Tasks

Unchanged from v1: `parse_write`, `parse_query`, `parse_followup_query`.

### v2 — Dispositions per task

| Task | Allowed dispositions | Default |
|---|---|---|
| `parse_write` | `accept` \| `confirm` \| `reject` | (no default; always set) |
| `parse_query` | `accept` \| `clarify` \| `reject` | `accept` |
| `parse_followup_query` | `accept` | `accept` |

`clarify` and `reject` on `parse_query` are **new in v2**.

### v2 — Per-domain intents (HARMONIZED)

The single biggest schema change. v1 had four distinct names for "latest" across domains (`latest_bucket`, `latest_day`, `latest`, `latest_balance`). v2 collapses to one canonical `latest`; the **scoped tag** in the input (`ask: weight: latest`, `ask: notes: latest`) and/or domain words in the input disambiguate.

| Domain | v2 allowed intents |
|---|---|
| expense | `total`, `list`, `compare` |
| buy | `list`, `search` |
| todo | `list`, `history`, `search` |
| weight | `latest`, `history`, `trend`, `change`, `latest_all` |
| ledger | `summary`, `list`, `balance`, `search` |
| note | `latest`, `list`, `search` |

Folded mappings (v1 → v2):

| v1 intent | v2 intent | Notes |
|---|---|---|
| `latest_bucket` (note) | `latest` | merged |
| `day_bucket` (note) | `list` with `date_start = date_end` | merged |
| `recent` (note) | `list` with date filters | merged |
| `latest_day` (buy) | `list` with `date_start = date_end = today` | merged |
| `latest_balance` (ledger) | `summary` with `limit=1` (most recent activity) | merged |
| `open_summary` (ledger) | `summary` | renamed |
| `settled_list` (ledger) | `search` with `filters.status = "settled"` | merged |

### v2 — New `parse_query` reason codes

`parse_query` rejects:
- `multi_person_compare_unsupported` — emitted for queries like `compare murugan and jeevi latest weight`. Multi-entity compare is intentionally not supported in v2.

`parse_query` clarify reasons:
- `looks_like_action` — emitted for queries like `ask: settle <person>`, `ask: clear <person> ledger`, `ask: pay <person> back`. The parser cannot decide between "show settled list" and "settle now" without a confirmation step.

### v2 — `parse_query` clarify shape

```json
{
  "task": "parse_query",
  "domain": "ledger",
  "disposition": "clarify",
  "clarify_reason": "looks_like_action",
  "clarify_options": ["yes - settle now", "show settled list"],
  "intent": null,
  "filters": null,
  "date_start": null,
  "date_end": null,
  "compare_date_start": null,
  "compare_date_end": null,
  "limit": null,
  "query_text": null,
  "reason_code": null
}
```

### v2 — `parse_query` reject shape

```json
{
  "task": "parse_query",
  "domain": "weight",
  "disposition": "reject",
  "reason_code": "multi_person_compare_unsupported",
  "intent": null,
  "filters": null,
  "date_start": null,
  "date_end": null,
  "compare_date_start": null,
  "compare_date_end": null,
  "limit": null,
  "query_text": null,
  "clarify_reason": null,
  "clarify_options": null
}
```

### v2 — `parse_query` accept shape (canonical)

Same as v1, plus the always-present `disposition: "accept"`, plus optional `clarify_reason: null` / `clarify_options: null` / `reason_code: null` to keep the field set uniform across dispositions.

### v2 — Filter shapes per domain

Unchanged from v1 except for the explicit decision that **multi-person filters are not introduced**: weight stays `{"person_text": str | null}` (single-valued), ledger stays single-person. Multi-entity compare is rejected at the schema level (see `multi_person_compare_unsupported`).

### v2 — Ledger reason note

Dropped entirely in v2. `parse_write` ledger records no longer carry an attached reason note. The `note` field on a ledger record is `null` always. v1 attached values from `INDIA_LEDGER_REASONS` / `GLOBAL_LEDGER_REASONS`; this is removed for v2.

### v2 — `expense history` mapping

Per the `current_state.md` retrieval contract, `expense history` resolves to:
- `intent: "total"`
- `date_start` / `date_end` = current month (resolved against the row's anchor)

This was unmapped in v1; v2 makes it explicit.

### v2 — Anchor-date strategy and prompt template

v1 used a single fixed dataset anchor `2026-05-05`. v2 generates each row against one of **5 anchor months** spread across the year (`2026-01`, `2026-03`, `2026-05`, `2026-08`, `2026-11`) with **day-of-month randomized per row** (uniform within the actual length of the chosen month, year fixed at 2026). All relative-date phrases in the row resolve relative to that row's anchor. Per-row day randomization (rather than 5 fixed dates all on day=15) widens `Today: <YYYY-MM-DD>` token exposure during training so the model doesn't only ever see five distinct date strings.

The chat-template system message in v2 includes a new `Today: YYYY-MM-DD` line, separated from the rest of the system prompt by a blank line:

```
You are a parser for a tag-first personal data app. Return JSON only...
Follow the schema shown by the examples exactly.

Today: 2026-05-23
```

At training time, `Today:` carries the row's anchor. At inference time, the runtime injects the real current date. The model learns "use the date in the prompt as the anchor for relative resolution".

This change in the chat-template is part of the v2 schema contract: any v2-trained adapter must be served with a `Today:` line in the system prompt. The runtime wrapper (`second_brain_finetuned_parser.py`) gates this injection behind the env flag `SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION` so the v1 adapter (which was not trained with `Today:`) keeps its historical framing.

### v2 — Schema diff (v1 → v2)

| v1 | v2 | Action |
|---|---|---|
| 4 different "latest" intent names across domains | single `latest` per applicable domain | rename in generator + all training rows |
| `latest_bucket`, `day_bucket`, `recent` (note) | `latest`, `list` with date filters | merge |
| `latest_day` (buy) | `list` with date=today | merge |
| `latest_balance` (ledger) | `summary` with `limit=1` | merge |
| `open_summary` (ledger) | `summary` | rename |
| `settled_list` (ledger) | `search` with `status="settled"` | merge |
| no `disposition` on `parse_query` | `accept` \| `clarify` \| `reject` | add field |
| no `clarify_reason`, `clarify_options` | added | add fields |
| no `reason_code` on `parse_query` | added | add field |
| `expense history` not mapped | maps to `intent: "total"`, current month | add form |
| no multi-person compare handling | reject with `multi_person_compare_unsupported` | new slice |
| no `looks_like_action` clarify | added | new slice |
| ledger `note` field carries reason text | always `null` | drop |
| single anchor `2026-05-05` | 5 anchors with `Today:` injected into system prompt | generator + prompt refactor |

### v2 — Out of scope (explicitly NOT changed)

- Note write reference rows — still deterministic, still excluded from SFT.
- Compare for buy / todo / note — still not supported.
- Compare for ledger across persons — still not supported.
- Foreign currency conversion — still numeric-only-with-warning per v1.
- Filter shapes per domain — still single-valued (no multi-person filters).
- The deterministic `note:` write bypass — unchanged.

## Expense

Status: locked on 2026-05-05

### Scope

`expense:` is for money spent by the user.

Included:
- goods
- services
- fares
- bills
- recharges
- subscriptions
- parking
- tickets
- rent
- EMI
- loan repayment
- donation
- tips
- insurance
- similar everyday spend events

Excluded in v1:
- refunds
- reversals
- money received back
- gain/income style entries

These should move to a separate future lane.

### Valid input behavior

- `expense:` accepts single-entry and multi-entry inputs.
- Mixed expense types in one line are valid.
- If a phrase has one shared total and cannot be split cleanly, keep it as one expense.
- Example: `expense: fruits and snacks 300`

### Multi-entry behavior

- One line may contain multiple expense records.
- A single trailing date phrase applies to all records in that line.
- Mixed-category same-line entries are valid.

Examples the dataset must cover heavily:
- `maggi 50`
- `50 maggi`
- `maggi-50`
- `50-maggi`
- `maggi:50`
- `50:maggi`

Also cover:
- comma-separated entries
- natural-language mixed entries
- multiple services in one line
- multiple categories in one line

### Core normalization behavior

- Save the main spend subject and amount.
- Remove filler phrasing.
- Merchant, store, and place are secondary.
- Preserve user-facing shorthand when it is how the spend is naturally referred to.

Example:
- input: `expense: paid 410 for plum vinegar at lotus mart`
- normalized core meaning: `plum vinegar` + `410`

Examples of shorthand preservation:
- `parachute 300` stays textually `parachute`
- `xerox 30` stays textually `xerox`

Behavioral expectation:
- shorthand/brand/common-name entries should still be grouped intelligently

### Incomplete input behavior

Reject immediately if the expense is incomplete.

Examples:
- `expense: apples`
- `expense: 250`

Expected app behavior:
- do not save a partial expense
- ask for proper expense input
- show one or two examples

### Date behavior

- If no date is given, use today's date automatically.
- If a date phrase is given, resolve it immediately and save the actual calendar date.
- Do not store unresolved relative date text for later resolution.

Synthetic dataset rule:
- use anchor date `2026-05-05`

Examples under that anchor:
- `today` -> `2026-05-05`
- `yesterday` -> `2026-05-04`
- `last sunday` -> `2026-05-03`

Runtime rule:
- use the live current date at runtime, not the dataset anchor

### Amount behavior

Default currency behavior:
- app is INR-first
- if user writes a foreign currency like `USD 20`, save numeric amount `20`
- show a warning that the app saves INR-only amounts
- do not auto-convert currencies in v1

Supported amount styles:
- plain numbers
- `Rs 50`
- `rs 50`
- comma numbers like `1,250`
- decimals like `100.50`
- Indian compact forms like `1.5L`, `1.5Cr`, `2 lakh`, `3 crore`, `1.25 lakh crore`

Locked conversions:
- `1.5L = 150000`
- `1.5Cr = 15000000`
- `2 lakh = 200000`
- `3 crore = 30000000`
- `1.25 lakh crore = 12500000000000`

Scale expectation:
- support at least up to `10 crore`
- support larger values when written in valid Indian large-number wording

### Grouping behavior

Grouping is required and should always be attempted.

Allowed expense groups:
- `groceries`
- `transport`
- `dining`
- `bills_utilities`
- `recharge_subscription`
- `household`
- `health`
- `personal_care`
- `education`
- `work`
- `entertainment`
- `travel`
- `vehicle`
- `shopping`
- `other`

Group notes:
- `petrol`, `diesel`, EV charging, car insurance, and related spends go under `vehicle`
- if the item is unclear, fall back to `other`
- grouping is inferred helper truth, not user-provided truth

### Dataset coverage expectations

Target distribution:
- `70%` India-relevant
- `30%` global

India-heavy examples should include:
- groceries
- recharge/top-up
- Jio/Airtel-like spends
- electricity/internet bills
- bus/train/auto/cab fares
- petrol/diesel
- parking
- tickets
- subscriptions
- household items
- personal care items
- rent
- EMI
- loan repayment
- donation
- tips

Diversity rule:
- stay within real expense behavior
- do not drift into unrelated domains

### Notes for later phases

- grouping quality will depend on larger synthetic coverage plus real-failure backfill
- merchant/location can be added later as optional metadata if it proves useful
- refund/income/gain should become a separate lane rather than overloading `expense:`

## Buy

Status: locked on 2026-05-05

### Scope

`buy:` is a shopping / procurement checklist lane.

Primary purpose:
- things to buy later
- mostly item-oriented entries
- mostly noun phrases, not action phrases

This lane is intentionally lighter than `expense:`.

Examples that belong here:
- groceries
- household items
- personal care items
- stationery
- electronics accessories
- brand-heavy shopping entries

Examples:
- `buy: milk, curd, onions`
- `buy: dove 3, parachute, surf excel`
- `buy: hdmi cable, printer ink, raincoat`

Excluded from `buy:`:
- action tasks
- appointments
- service requests
- bill payments
- reminder-style non-item actions

These belong in `todo:`.

Examples that should be treated as `todo:` instead:
- `pay EB bill`
- `renew license`
- `book dentist appointment`
- `call AC service`
- `do haircut`

### Parsing strategy

- `buy:` should be parsed by the LLM, not by a rule-first parser.
- Deterministic validation may still run after parsing.
- The target behavior is still narrow and lightweight; this is not a heavy analytics domain.

### Valid input behavior

- `buy:` accepts single-entry and multi-entry inputs.
- Quantities and units are allowed but optional.
- Brand-heavy wording is normal and should be preserved as written.
- Grocery and non-grocery item entries are both valid.
- Mixed natural-language shopping phrases should normalize into item entries.

Examples:
- `buy: coriander`
- `buy: tomatoes 2kg`
- `buy: dove 3`
- `buy: notebook 3, tape, batteries 4`
- `buy: need to get coconut milk and painter's tape`

### Core normalization behavior

- Save item entries as checklist items.
- Preserve the user-facing item/brand wording where possible.
- Normalize away filler/action lead-ins.

Examples:
- `buy: need to get coconut milk and painter's tape`
  -> `coconut milk`, `painter's tape`
- `buy: pick up turmeric powder, eggs and floor cleaner`
  -> `turmeric powder`, `eggs`, `floor cleaner`

Brand-heavy examples should stay textually close to user input:
- `parachute`
- `dove`
- `lux`
- `surf excel`

### Quantity and unit behavior

- Quantity is optional.
- Unit is optional.
- Item-only entries are valid.
- Quantity-only or time-only entries are invalid.

Examples of valid entries:
- `curd`
- `rice 10 kg`
- `batteries 4`
- `soap 3 bars`
- `dove 3`

Examples of invalid entries:
- `buy: 2kg`
- `buy: tomorrow`
- `buy: one more`

Expected app behavior on invalid input:
- reject immediately
- do not save a partial buy item
- ask for proper buy input

### Date behavior

- If no date is given, use today's date automatically.
- If a date phrase is given, resolve it immediately and save the actual calendar date.
- A single trailing date phrase applies to all items in that line.

Synthetic dataset rule:
- use anchor date `2026-05-05`

Examples under that anchor:
- `buy: curd, detergent tomorrow`
  -> both items resolve to `2026-05-06`

Runtime rule:
- use the live current date at runtime, not the dataset anchor

### Grouping behavior

- No category/group inference is needed for `buy:` in v1.
- Raw item text is enough.

### Checklist lifecycle

- `buy:` should behave like a checklist with open/done state.
- User can later mark some or all items as bought.
- This is one of the main reasons to keep `buy:` separate from `expense:`.

### Retrieval expectations

- Retrieval should stay simple in v1.
- Default retrieval intent is open buy-list viewing, not analytics/history.

Examples:
- `what do I need to buy`
- `show my buy list`

Default behavior:
- show today's buy list first

If the user explicitly asks for another day/range:
- show that day/range instead

If the user asks for the "last buy list" and nothing exists for today:
- falling back to the most recent earlier buy list is acceptable

### Dataset coverage expectations

Target distribution:
- `70%` India-relevant
- `30%` global

Coverage expectations:
- groceries
- household items
- personal care items
- stationery
- electronics accessories
- brand-heavy Indian shopping language
- optional quantities and units
- natural-language shopping phrasings

Diversity rule:
- stay within real buy-list behavior
- do not drift into service/action-task territory

## Todo

Status: locked on 2026-05-05

### Scope

`todo:` is the action / reminder / checklist lane.

Primary purpose:
- actions to perform
- reminders to handle
- appointments to book
- bills to pay
- forms to submit
- general personal tasks

Examples that belong here:
- `pay EB bill`
- `renew license`
- `book dentist appointment`
- `call plumber`
- `submit PF form`

Valid todo entries can be:
- action phrases
- reminder-like phrases
- noun-like reminders

Examples of valid noun-like reminders:
- `passport renewal`
- `broadband bill`
- `mom birthday gift`

### Boundary against `buy:`

- `todo:` is mostly action phrases and reminders.
- `buy:` is mostly noun phrases/items to acquire later.
- If the user uses `todo:` for buy-list-like entries, accept them as todos rather than rejecting them.

Example:
- `todo: milk, curd, onions`
  -> treat as todo entries, do not reject just because `buy:` exists

### Parsing behavior

- `todo:` accepts single-entry and multi-entry inputs.
- Multi-entry input may be comma-separated, multiline, or bullet-list shaped.
- If a single trailing date phrase appears at the end, it applies to all entries in that line.
- Date phrases should be resolved immediately to actual calendar dates.

### Save-as-given text behavior

- Todos should preserve user wording closely.
- Do not aggressively normalize todo text.
- Save todo text essentially as the user gave it.

Examples:
- `need to call the electrician`
- `remember to pay the broadband bill`

Time phrases:
- do not create a separate structured time field in v1
- if the user includes time wording, keep it inside the saved todo text
- the important structured behavior is open/done state and due-date handling

### Date behavior

- If no date/time is given, default to today's date.
- If a date phrase is given, resolve it immediately and save the actual calendar date.
- Time-specific wording may remain inside the todo text itself.

Synthetic dataset rule:
- use anchor date `2026-05-05`

Runtime rule:
- use the live current date at runtime, not the dataset anchor

### Incomplete input behavior

Reject immediately if the input has no meaningful task content.

Examples:
- `todo: tomorrow`
- `todo: 4pm`
- `todo: later`
- `todo: urgent`

Expected app behavior:
- do not save a partial todo
- ask for proper todo input
- show one or two examples

### Recurrence and extra metadata

- No recurring-task support in v1.
- No priority/importance inference in v1.
- No category/group inference in v1.
- Todo state is only:
  - `open`
  - `done`

### Retrieval expectations

- Default broad retrieval should show only open tasks.
- If the user explicitly asks for all todos, show both open and done items.
- Retrieval should support both pending/open and closed views when explicitly requested.

Examples:
- `what do I need to do today`
- `show pending tasks`
- `show my todo list`
- `show all todos`

Default behavior:
- broad todo-list requests return open items first
- done items appear only when explicitly requested

### Dataset coverage expectations

Target distribution:
- `70%` India-relevant
- `30%` global

Coverage expectations:
- bills and payments
- office/admin chores
- appointments
- household tasks
- phone calls
- document renewals
- reminder-like noun phrases
- multiline and bullet-style task entry
- task lines with shared trailing dates

Diversity rule:
- stay within real task/reminder behavior
- do not drift into heavy scheduling or calendar-app complexity

## Weight

Status: locked on 2026-05-05

### Scope

`weight:` is for body weight only.

Included:
- named body-weight entries
- self/default-person body-weight entries
- optional short context notes such as meal state or activity state

Excluded in v1:
- non-weight body measurements
- waist/chest/other measurement tracking
- non-kg units

### Core behavior

- Multi-entry input is allowed.
- Name and weight are the main priority.
- Optional context such as `before breakfast`, `after walk`, or `empty stomach` may be preserved.
- Default unit is `kg`.
- Only `kg` is supported in v1.

Examples of valid entries:
- `weight: Arun 72.4`
- `weight: Meera 58.2 before breakfast`
- `weight: mom 64.1, dad 78.3 after walk`

Examples of invalid measurement-domain entries:
- `weight: waist 34`

### Person/name behavior

- Unknown names are allowed and should create a new person entry if not already present.
- Household-style names such as `mom` and `dad` are valid.

Nameless/self behavior:
- If no explicit name is present, map the entry to `self`.
- `self` is the dataset/runtime placeholder for the default person.
- UI/app code can later map `self` to the chosen real person record.

Examples:
- `weight: 72.4` -> map to `self`
- `weight: self 72.4` -> map to `self`
- `my weight 72.4` -> map to `self`

### Date behavior

- If no date is given, use today's date automatically.
- If a date phrase is given, resolve it immediately and save the actual calendar date.
- A single trailing date phrase applies to all entries in that line.

Synthetic dataset rule:
- use anchor date `2026-05-05`

Runtime rule:
- use the live current date at runtime, not the dataset anchor

### Context-note behavior

- Context notes are optional.
- They can be preserved as short note-like text attached to the weight entry.
- Context should not dominate parsing; name and numeric weight remain the primary fields.

Examples:
- `before breakfast`
- `after dinner`
- `empty stomach`
- `after walk`

### Validation behavior

Reject incomplete or ambiguous entries.

Examples to reject:
- `weight: Arun`
- `weight: before breakfast`

Special case:
- a bare numeric weight like `weight: 72.4` is valid in v1 only because it maps to `self`

### Retrieval expectations

Supported query behaviors:
- latest
- history/list
- change over time
- trend

Default person behavior in queries:
- nameless self-style queries should use the default person / `self`

Examples:
- `what is my latest weight`
- `show my weight trend`

Default retrieval windows:
- `history` with no explicit range -> last 6 months
- `trend` with no explicit range -> last 6 months
- `change` with explicit range should compare the requested starting point to the latest value

Example:
- `show Meera weight history` -> default to last 6 months
- `show Arun trend` -> default to last 6 months
- `how much did Arun change since January` -> compare January value to latest

### Dataset coverage expectations

Target distribution:
- `70%` India-relevant
- `30%` global

Coverage expectations:
- named entries
- self/default-person entries
- multi-person same-line entries
- optional meal/activity context
- date phrases
- history/latest/change/trend queries

Diversity rule:
- keep the lane narrow and clean
- do not drift into generic health-tracker complexity

## Ledger

Status: locked on 2026-05-06

### Scope

`ledger:` tracks money owed between you and one other person.

Core meaning:
- either you owe someone
- or someone owes you

This is person-to-person debt tracking.

### Core direction behavior

These direction styles are valid and should be supported:
- `I owe Arun 500`
- `Arun owes me 500`
- `borrowed 500 from Arun`
- `lent Arun 500`

Interpretation requirement:
- the parser must identify direction clearly enough to update the correct side of the relationship

### Ambiguous phrasing behavior

`gave` / `received` style phrasing is supported, but always higher risk.

Examples:
- `gave Arun 500`
- `received 500 from Arun`

Rule:
- support these phrasings
- always confirm them unless the surrounding wording removes ambiguity completely

### Settlements and partial repayments

Settlements and partial repayments are mandatory in v1.

Examples that must be supported:
- `Arun returned 500`
- `I paid Arun back 500`
- `settled with Arun`
- `cleared Bala`

Settlement rule:
- `settled with Arun` means clear the relationship to zero immediately
- this applies even if multiple prior entries exist
- settlement does not require an explicit amount

Partial repayment rule:
- partial-repayment style phrases should reduce the existing balance in the correct direction

### Multi-entry behavior

- Multi-entry input is allowed.
- A single trailing date phrase applies to all entries in that line.

Examples:
- `ledger: I owe Arun 500, Bala owes me 1200`
- `ledger: borrowed 300 from Dev, lent Kiran 900`
- `ledger: I owe Arun 500, Bala owes me 1200 yesterday`

### Date behavior

- If no date is given, use today's date automatically.
- If a date phrase is given, resolve it immediately and save the actual calendar date.

Synthetic dataset rule:
- use anchor date `2026-05-05`

Runtime rule:
- use the live current date at runtime, not the dataset anchor

### Person/name behavior

- Unknown names are allowed.
- If the person is not already present, create a new person entry automatically.

### Amount behavior

Ledger amount parsing should match `expense:` behavior.

Supported amount styles:
- plain numbers
- `Rs 500`
- `rs 500`
- comma numbers like `1,250`
- decimals like `100.50`
- `5k`
- `1.5L`
- `2 crore`
- other valid Indian large-number forms already accepted by `expense:`

Default currency behavior:
- assume INR
- if user writes foreign currency, save numeric amount as-is
- show a warning that the app saves INR-only amounts
- do not auto-convert currencies in v1

### Reason/note behavior

- Reason text is optional.
- If present, it can be preserved as note-like context attached to the ledger entry.
- Reason must not be required for a valid ledger write.

Examples:
- `I owe Arun 500 for room rent`
- `Bala owes me 1200 from train tickets`

### Validation and rejection behavior

Reject incomplete or direction-ambiguous entries.

Examples to reject:
- `ledger: Arun 500`
- `ledger: gave 500`
- `ledger: settled`
- `ledger: return 500`

Reason:
- person or direction is missing or ambiguous

### Confirmation policy

Auto-save only very clear ledger writes.
Confirm ambiguous ones.

Clear entries:
- explicit `I owe X`
- explicit `X owes me`
- clear `borrowed from X`
- clear `lent X`
- clear repayment phrases with unmistakable direction

Confirmation-worthy entries:
- `gave X`
- `received from X`
- anything else where direction is not obviously safe

### Retrieval expectations

Broad ledger retrieval:
- default broad retrieval should show full transaction history

Examples:
- `show my ledger`
- `ledger summary`

Person-specific retrieval:
- `show Arun ledger` should return both:
  - current summary/balance
  - recent entries with dates

### Must-have ledger queries

These are required:
- `how much do I owe Arun`
- `how much does Bala owe me`
- `who owes me money`
- `whom do I owe`
- `show open ledger with Kiran`

Okay-to-have:
- `recent ledger entries`

Additional supported forms:
- `ledger from last month`

### Dataset coverage expectations

Target distribution:
- `70%` India-relevant
- `30%` global

Coverage expectations:
- clear owe/owed phrasing
- borrowed/lent phrasing
- gave/received ambiguity cases
- partial repayments
- settlements/clear-to-zero cases
- multi-entry lines
- date phrases
- person-specific summary queries
- open-ledger queries

Diversity rule:
- keep the lane focused on personal debt semantics
- do not drift into generic business accounting or group expense settlement systems

## Note

Status: locked on 2026-05-06

### Scope

`note:` is the plain real-note lane.

Primary purpose:
- save free text as a real note
- no structured parsing
- no reinterpretation

`note:` is a hard override.

If the user chooses `note:`, nothing inside it should override that choice.

Examples:
- `note: expense: milk 40`
- `note: todo: call plumber`

Both must still be saved as plain notes.

### Text preservation behavior

- Preserve note text near-exactly as written.
- Keep punctuation, casing, line breaks, and paragraph breaks as much as possible.
- Do not normalize or simplify note text.
- Do not resolve date phrases inside note text.

Examples:
- copied snippets
- rough thoughts
- long-form writing
- meeting notes
- journal-like paragraphs

All of these are valid.

### Multi-line behavior

- Multi-line `note:` input should be stored as one note payload.
- `note:` should never be auto-split into multiple notes.

### Empty/minimal input behavior

- Reject `note:` with no content.
- Very short content is still valid if content exists.

Examples:
- `note:` -> reject
- `note: 1` -> valid

### Same-day append behavior

- Multiple `note:` submissions on the same day should append into one same-day note bucket.
- The user concept is one big note sheet for that date rather than one separate note row per submission.

Implication for dataset/runtime behavior:
- each `note:` submission is still captured as user input
- but the saved note content for that date should append rather than create a brand-new standalone note for every submission

### Structured-content mistake behavior

- If the user accidentally writes shopping-list-like or task-like text under `note:`, still save it as a note.
- Do not auto-convert it to `buy:` or `todo:`.
- The user can clean it up later in the notes UI if needed.

### Metadata generation

- No title generation in v1
- No summary generation in v1
- No topic extraction in v1

### Retrieval membership

- `note:` content belongs to the general searchable note pool.
- It should be searchable both lexically and semantically.
- Retrieval behavior itself will be locked separately in the retrieval section.

### Dataset coverage expectations

Coverage expectations:
- single-line short notes
- long-form paragraphs
- multiline notes
- notes containing structured-looking text
- very short valid notes
- repeated same-day note submissions

Diversity rule:
- treat `note:` as the broadest and least opinionated lane
- preserve user text rather than trying to improve it

## Retrieval - Notes

Status: locked on 2026-05-06

### Retrieval scope

For v1, note-like retrieval should search plain real notes only.

Current v1 rule:
- search `note:` content
- do not expand to future note-like lanes by default yet

This can be widened later if `journal:`, `idea:`, `watch:`, or `work:` become active product lanes.

### Broad note retrieval behavior

If the user asks broad note-style queries such as:
- `show my notes`
- `what have I written recently`

Default behavior:
- show today's note bucket first if available
- otherwise show the most recent earlier day's note bucket
- one day bucket is enough by default unless the user explicitly asks for a specific date/range

### Content matching behavior

- note retrieval should be typo-tolerant and approximate-match friendly by default
- lexical and semantic retrieval are both expected

Examples:
- `cocnut oil`
- `locl models`

### Output shape

Preferred output:
- short summary first
- then all relevant snippets

If retrieval confidence is weak:
- show raw snippets only
- do not synthesize a confident summary

### Date filtering behavior

Date filtering applies to note retrieval.

Examples:
- `what did I write yesterday`
- `show notes from last week`

These should filter notes by the requested date/day/range.

### Same-day bucket retrieval behavior

Because multiple `note:` writes append into one same-day bucket:
- retrieval should return the relevant snippet(s) from that day bucket by default
- the whole day bucket may be shown when the user asks broadly for that day's notes

Rule:
- retrieval granularity depends on the query
- topical query -> relevant snippets
- broad day/date query -> that day's note bucket view

### Multi-hit behavior

If multiple relevant note matches exist:
- return all relevant snippets
- include a short summary when confidence is good

Do not aggressively truncate to top 3 or top 5 by default if multiple relevant snippets exist.

### "Latest note" behavior

Because notes append by day:
- `show my latest note` means the latest day bucket with note content
- if nothing exists for today, use the most recent earlier day with notes

### Dataset coverage expectations

Coverage expectations:
- broad note-list queries
- topical note search queries
- typo/approximate-match note search
- date-filtered note search
- latest-note queries
- same-day bucket retrieval
- multiple relevant snippet retrieval

## Retrieval - Expense

Status: locked on 2026-05-06

### Broad default behavior

Broad expense retrieval defaults to the current month.

Examples:
- `show my expenses`
- `expense summary`

Default output:
- current month total
- plus recent expense list
- recent list should default to the last 5 expenses in this broad-summary case

### Total queries

If the user asks:
- `what is my total expense`

Default range:
- current month

If the user asks a date-specific form:
- use the requested date/day/month/range

### Today queries

Examples:
- `what did I spend today`
- `show today expense`

Default output:
- today's expenses
- plus today's total

### Must-have expense query behaviors

These are all required in v1:
- `what is my total expense this month`
- `compare this month and last month`
- `what did I spend on groceries in april`
- `show my expenses apart from groceries`
- `what did I spend on tomato this month`
- `show recent expenses`
- `expense from yesterday`

### Item-query matching behavior

For item-specific queries:
- exact item text match is preferred
- approximate lexical match is allowed
- if a close lexical correction is used, the app should show a toast/notice similar to a search-engine correction

Example:
- user asks for `tamato`
- app may show results for `tomato` with a correction hint

Out of scope in v1:
- broad semantic brand-to-product reinterpretation such as mapping `parachute` to `coconut oil`

### Group-query behavior

Grouping should be trusted enough for retrieval in v1.

Examples:
- `what did I spend on groceries this month`
- `expense apart from groceries`

Supported exclusion semantics:
- `apart from`
- `except`
- `excluding`

These should be treated as first-class expense query behaviors.

### Recent-expense behavior

`recent expenses` means:
- last 10 entries

### Output shape

For broad expense retrieval like `show my expenses`:
- return total + list

List formatting:
- group list output by date

Example shape:
- `2026-05-06`
  - `tomato 40`
  - `jio recharge 239`
  - `bus fare 18`

### Close-match behavior

If no exact item exists but a close lexical match exists:
- show the close match results
- show a correction toast/notice

Do not silently pretend it was an exact match.

### Foreign currency retrieval behavior

- foreign-currency entries that were saved numerically should be treated as stored numeric amounts during retrieval

### Group display behavior

- expense retrieval may show the inferred group in results
- description + amount + date remain the core fields

### Broad history behavior

If the user asks:
- `show my expense history`

Default behavior:
- current month history only

If the user explicitly asks for another range:
- use that requested range instead

### Follow-up inheritance behavior

This is critical.

If a previous expense query established domain/range/filter context, a follow-up should inherit it unless explicitly overridden.

Example:
- `what is my total expense last month`
- follow-up: `of that how much was groceries`

Expected follow-up behavior:
- same expense domain
- same last-month date range
- add `groceries` filter

### Dataset coverage expectations

Coverage expectations:
- broad current-month summary queries
- today queries
- item-specific queries
- group-specific queries
- exclusion queries
- comparison queries
- recent-entry queries
- grouped-by-date list outputs
- follow-up inherited-filter queries

## Retrieval - Todo

Status: locked on 2026-05-06

### Broad default behavior

Broad todo retrieval defaults to open tasks only.

Examples:
- `show my todo list`
- `show my tasks`

Default behavior:
- return only open tasks

### Today/task-date behavior

Examples:
- `what do I need to do today`
- `show today tasks`

Default behavior:
- only today's open tasks

### Pending/open behavior

Examples:
- `show pending tasks`

Meaning:
- open tasks only

### All-todos behavior

Examples:
- `show all todos`

Default behavior:
- include both open and done tasks
- show open tasks first
- show done tasks after open tasks

### History behavior

Examples:
- `show my task history`

Default behavior:
- last 10 tasks
- include both open and done items in this history view

### Due/range behavior

Examples:
- `what is due this week`

Default behavior:
- open tasks only for the requested period

### Done/completed retrieval

Done/closed retrieval by date must be supported.

Examples:
- `what did I finish today`

### Output formatting

Todo retrieval output should be grouped by date.

Broad list formatting:
- group tasks by date
- when both states are shown, open tasks come first and done tasks follow

### Noun-like todo search

Noun-like todo search should work the same way as action-like todo search.

Examples:
- `show mom birthday gift`
- `show passport renewal`

### Approximate matching behavior

Todo retrieval should allow approximate lexical matching.

Examples:
- `broadbnd bill`
- `eletrician`

### Date filtering behavior

Date filtering fully applies to todo retrieval.

Examples:
- `show tasks from yesterday`
- `what were my todos last week`

### "Latest task" behavior

`show my latest task` means:
- latest task for today if available
- otherwise latest task from the most recent earlier day

### Follow-up inheritance behavior

Follow-up inheritance is important for todo retrieval.

Example:
- `show pending tasks for today`
- follow-up: `show only done ones`

Expected follow-up behavior:
- inherit todo domain
- inherit the prior date/range context unless overridden
- switch the requested task-state filter as asked

### Separation from `buy:`

Todo retrieval and buy-list retrieval remain separate.

Example:
- `show my buy items`

Rule:
- do not include `buy:` lane content in `todo:` retrieval by default

### Dataset coverage expectations

Coverage expectations:
- broad open-task list queries
- today-task queries
- pending/open queries
- all-todos queries
- history queries
- done/completed queries
- noun-like reminder search
- approximate lexical todo search
- date-filtered todo retrieval
- follow-up state-switch queries

## Retrieval - Weight

Status: locked on 2026-05-06

### Default self-person behavior

Self-style weight retrieval should use the default/self person automatically.

Examples:
- `what is my latest weight`
- `show my weight history`
- `show my weight trend`

### Latest-weight behavior

`show my latest weight` should return:
- latest value
- plus date

Do not add extra comparison/trend text by default for this specific query form.

### History behavior

If the user asks:
- `show my weight history`

Default range:
- last 6 months

If the user asks for a named person like:
- `show Arun weight history`

Default output:
- last 5 entries
- with date

### Trend behavior

If the user asks:
- `show my weight trend`

Default output:
- short increase/decrease summary
- plus supporting entries

If no person name is given:
- use self/default person automatically

### Change-over-time behavior

Examples:
- `how much did Arun change since January`

Meaning:
- compare the requested starting point to the latest value

### Date filtering behavior

Date filtering fully applies to weight retrieval.

Examples:
- `weight from yesterday`
- `show weights last week`

### Broad multi-person behavior

If the user asks:
- `show latest weights`

Meaning:
- latest weight for all known people

Broad family-like vague query behavior:
- reject vague family-style phrases like `show family weights`
- do not silently map them to all people

### Context-note display behavior

Optional context notes may be shown inline next to the weight entry.

Examples:
- `before breakfast`
- `after walk`

### Same-day duplicate behavior

If multiple entries exist for the same person on the same day:
- keep only the latest one for retrieval output

### Name matching behavior

Do not silently approximate person names in weight retrieval.

If a name is close but not exact:
- ask for confirmation before using it
- if no confirmation path is taken, reject rather than auto-correct

Examples:
- `Aurn`
- `Meer`

### Follow-up inheritance behavior

Follow-up inheritance is important for weight retrieval.

Example:
- `show Arun weight history`
- follow-up: `only from last month`

Expected follow-up behavior:
- inherit weight domain
- inherit person
- apply the new requested date/range refinement

### Dataset coverage expectations

Coverage expectations:
- self latest-weight queries
- self history queries
- named-person history queries
- self/named trend queries
- change-since-date queries
- date-filtered queries
- latest-all-people queries
- follow-up refined-range queries

## Retrieval - Ledger

Status: locked on 2026-05-06

### Broad default behavior

Broad ledger retrieval should default to open balances only.

Examples:
- `show my ledger`
- `ledger summary`

Default behavior:
- show open balances only
- newest-relevant information first

### Person-specific default behavior

Examples:
- `show Arun ledger`

Default behavior:
- summary/current balance
- plus recent entries with date

### Balance-query behavior

Examples:
- `how much do I owe Arun`
- `how much does Bala owe me`

Default behavior:
- current balance only

### Open-balance direction queries

Examples:
- `who owes me money`
- `whom do I owe`

Default behavior:
- list all matching people with open balances in that direction

### Open-ledger-with-person behavior

Examples:
- `show open ledger with Kiran`

Default behavior:
- balance
- plus recent entries

### Recent-history behavior

Examples:
- `recent ledger entries`

Default range:
- last 10 entries

### Date-filtered ledger behavior

Examples:
- `ledger from last month`

Default behavior:
- current balance
- plus filtered history for the requested date/range

### Settled-ledger retrieval

Examples:
- `show settled ledgers`

Rule:
- settled-ledger retrieval is needed in v1

### Latest-ledger behavior

Examples:
- `show latest ledger`

Meaning:
- most recently changed person balance

### Output formatting

For broad history outputs:
- group entries by date
- order should be newest first

### Approximate person-name behavior

If the person name is not found but close names exist:
- show closest names
- ask for confirmation
- reject if no confirmation response is received

Do not silently auto-correct person names in ledger retrieval.

### No-open-balance behavior

If the person exists but there is no open balance:
- say `no open ledger found`

### Follow-up inheritance behavior

Follow-up inheritance is important for ledger retrieval.

Examples:
- `how much do I owe Arun`
- follow-up: `show entries for that`

Expected behavior:
- inherit person/domain context
- switch from balance view to entries/history view

Examples:
- `show my ledger from last month`
- follow-up: `only Arun`

Expected behavior:
- inherit date/range context
- apply the person filter refinement

### Dataset coverage expectations

Coverage expectations:
- broad open-balance queries
- person-specific summary + entries queries
- owe/owed balance queries
- who-owes-me / whom-do-I-owe queries
- open-ledger-with-person queries
- recent ledger queries
- date-filtered ledger queries
- settled-ledger queries
- latest-ledger queries
- no-match / close-name confirmation cases
- no-open-balance cases
- follow-up refinement queries
