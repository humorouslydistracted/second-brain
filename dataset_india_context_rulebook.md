# India-Context Dataset Rule Book

Source-of-truth style guide for large synthetic dataset generation on top of:
- `finetuning_data_sanity.md`
- the frozen shared schema (v2 active; v1 historical)

Status:
- v1 rules built the dataset that produced the current `Qwen3-1.7B` adapter
- v2 amendments below are now active for the **next** dataset generation and the next fine-tune run
- canonical v2 plan lives in `dataset_v2_plan.md`; this rulebook reflects the v2 deltas at the top, with v1 preserved below for historical reference

Current generation stance (v2):
- do not treat large row count as sufficient by itself
- effective diversity must come from both source pools and phrasing/template families
- Tanglish gating is now per-pattern (A/B/C) per lane, not a single boolean
- query phrasing should include a meaningful share of noun-phrase fragments, not only verb-led "show my X" forms
- scoped queries (`ask: <domain>:`) are a primary navigation tool; their share is bumped from <5% to 25–35% per lane
- relative-date resolution is anchored against a `Today: YYYY-MM-DD` line in the system prompt; dataset generation now uses **multiple training anchors** rather than a single fixed anchor
- before large generation, inspect asset/template coverage from `generate_large_schema_frozen_dataset.py --report`

---

## v2 Amendments (active)

These amendments override anything later in this file that conflicts. The body below remains as v1 reference.

The v2 generator that implements these amendments is `generate_large_schema_frozen_dataset_v2.py` (separate from the v1 generator, which is preserved). Output dir: `synthetic_finetune_dataset_v4_v2_schema/`. See `dataset_v2_plan.md` §9 for phasing status.

### v2.1 — Tanglish per-pattern budget (replaces single-boolean Tanglish gating)

Three distinct Tanglish patterns are now tracked separately:
- **Pattern A** — Tamil noun inside an English frame (`kothamalli 50rs`, `vengayam 60`, `expense for vengayam this month`).
- **Pattern B** — English nouns + Tamil verbs / time words / postpositions / dative markers (`car insurance podanum`, `naliku room clean pannanum`, `amma ku recharge pannanum`, `friend kitta bike kudukanum`).
- **Pattern C** — Full Tanglish frame (`indha maasam expense kaatu`, `nethu enna pochu`). **0% across all lanes in v2.** Confirmed unrealistic.

Per-lane, per-pattern budget:

| Lane | Pattern A | Pattern B | Pattern C |
|---|---|---|---|
| expense write | high — Tamil item words common (`vengayam`, `kothamalli`); mixed-script multi-entry OK | 0 | 0 |
| buy write | high — same as expense | 0 | 0 |
| todo write | rare (todo objects mostly English) | ~50% — full blend: verbs (`pannanum`/`kattanum`/`podanum`) + time words (`naliku`) + postpositions (`kitta`/`ku`) + datives (`amma ku`/`friend kitta`) | 0 |
| weight write | 0 | 0 | 0 |
| ledger write | 0 | 0 | 0 |
| ledger reason note | dropped entirely (no reason notes attached to ledger entries in v2) | dropped | dropped |
| weight write context note | English only (`before breakfast`, `after walk`, `empty stomach`) | 0 | 0 |
| note write | excluded from SFT — deterministic bypass | excluded | excluded |
| expense query | medium — Tamil item names inside English (`expense for vengayam this month`) | 0 | 0 |
| buy query | medium — same | 0 | 0 |
| todo query | low — todo objects mostly English | 0 | 0 |
| weight query | 0 | 0 | 0 |
| ledger query | 0 | 0 | 0 |
| note query | medium — Tamil keyword in English frame (`notes about kothamalli`) | 0 | 0 |

Tanglish date phrases (`innaiku`, `nethu`, `naalaiku`, `indha maasam`, `pona maasam`) are Pattern C and **excluded from queries**. They appear only inside todo-write Pattern B contexts (`naliku room clean pannanum`).

**v2 review pass refinement (post-§9 work):** four Tanglish item lists in `synthetic_dataset_assets.py` were dropped because their entries were almost all `<English noun> kasu` (e.g., `auto kasu`, `tea kasu`, `petrol kasu`, `puncture kasu`) and no real Tanglish user writes them — stripping `kasu` left only English. The dropped lists: `_TANGLISH_TRANSPORT`, `_TANGLISH_DINING`, `_TANGLISH_VEHICLE`, `_TANGLISH_LEDGER`. The underlying English items remain available in their `INDIA_EXPENSE[...]` pools. Tanglish item words that *are* genuinely natural in writing — `_TANGLISH_GROCERIES`, `_TANGLISH_HOUSEHOLD`, `_TANGLISH_PERSONAL`, `_TANGLISH_NOTES`, `_TANGLISH_TODOS`, `_TANGLISH_TODO_NOUNS` — were retained and roughly doubled in the Phase 3 expansion (see `dataset_v2_plan.md` §13.3).

**`kaatu` purge.** All query template `tanglish_a` buckets had `kaatu` (a spoken-only verb form, not used in writing) and other Pattern C phrasings (`enna vanganum`, `vaanga vendiya list`, `enna seiyanum`, `evlo pochu`, `selavu evalo`, `thavira expense`, `illama matha` etc.) removed. Pattern A was retained only where it surfaces naturally — note search (`notes la {q} irukka`, `{q} pathi notes irukka`) and buy search (`buy list la {item} irukka`, `{item} buy list la irukka`) — and Tamil item words still flow into noun-phrase queries via `{desc}` / `{q}` / `{item}` placeholders without explicit Tanglish wrappers.

### v2.2 — Query phrasing concision

Each query form must have a **35% share of noun-phrase / fragment templates** (e.g., `pending tasks`, `latest weight`, `today expenses`, `open ledger`, `who owes me`). The remaining mix is roughly 30% verb-led English, 20% question-shaped, 15% Tanglish patterns where the lane budget allows.

Real users do not consistently say "show me my pending todo list" — they often type `pending tasks`. v1 over-trained on the verb-led form and starved the model of the fragment register.

### v2.3 — Scoped query coverage

`ask: <domain>:` scoped queries are bumped from a few percent (v1) to **25–35% per lane** (v2). Scoped is now the primary navigation tool when intent harmonization (see v2.4) makes domain inference ambiguous.

Scoped rows must cover **every intent** in each domain — not just one or two phrasings. At least 5 scoped templates per intent.

### v2.4 — Intent vocabulary harmonization

The single biggest schema change. v1 had four different intent names for "latest" (`latest_bucket`, `latest_day`, `latest`, `latest_balance`). v2 collapses to one canonical `latest` per applicable domain, with the **scoped tag** disambiguating. See `dataset_v2_plan.md` §1.3 and `finetuning_data_sanity.md` "Shared Schema Freeze v2".

### v2.5 — Anchor-date strategy

v1 used a single fixed anchor (`2026-05-05`). v2 generates against **5 anchor months** spread across the year (`2026-01`, `2026-03`, `2026-05`, `2026-08`, `2026-11`) with **day-of-month randomized per row** (uniform within the month, year fixed at 2026). The earlier 5-fixed-dates design (all on day=15) was revised in the v2 review session to widen `Today: <YYYY-MM-DD>` token exposure during training — the model previously would have only seen 5 distinct date strings. Each row's relative dates still resolve relative to its row anchor; the row anchor is rendered into the system prompt as `Today: YYYY-MM-DD` during training. Inference injects the real current date (gated by env flag in the runtime wrapper).

Date phrase breadth (per lane that uses dates):
- 60% canonical date phrasings (`today`, `yesterday`, `this month`, `last month`)
- 30% random key from the full `RANGE_OPTIONS` / `SINGLE_DATE_OPTIONS` pool (so `past 60 days`, `quarter to date`, `april second week`, `current financial year` get exposure)
- 10% absolute calendar dates (`on may 9`, `from april 16 to april 30`)

Time-of-day phrasings (`this morning`, `this evening`, `tonight`, `last night`, `early morning`, `this afternoon`) are **excluded from query date pools** because no lane supports time-of-day filtering. They remain available as write-side date phrasings (`expense: tea 20 this evening` is a realistic write input).

### v2.6 — Reject pool widening

v1 rejected from a **6-item hardcoded list per lane** (e.g., expense desc-only rejects only used `apples`, `coriander`, `brown chana`, `kothamalli`, `shampoo`, `milk packet`). The model probably memorized these strings.

v2 samples reject inputs from the **full asset pool** (e.g., 200+ items rotating through `INDIA_EXPENSE` / `GLOBAL_EXPENSE` for desc-only rejects). The same item may appear in both accept and reject rows; the rejection rule is structural (no amount → reject), not item-specific.

### v2.7 — New slices

Beyond the existing parse_write / parse_query / parse_followup_query / reference_only structure, v2 adds:
- **Adversarial domain pairs** (~400 pairs / 800 rows) — same person across weight/ledger, weight/todo, weight/note search.
- **Bare nameless variants** (~10% of single-person retrieval lanes) — `latest weight`, `expense list`, `pending tasks` without `my`/`en`. Map to `person_text: "self"` where applicable.
- **Real typo module** (~7% of search query rows) — vowel swap, transposition, single-letter drop, double-letter drop, phonetic substitution. Applied to note search, expense desc, buy search, todo search.
- **Action-shaped query clarify** (~200 rows) — `ask: settle <person>` and similar emit `disposition: clarify` with `clarify_reason: "looks_like_action"`.
- **Multi-person compare reject** (~150 rows) — `ask: compare X and Y latest weight` emits `disposition: reject` with `reason_code: "multi_person_compare_unsupported"`.

### v2.8 — Diversity must come from templates, not just assets

v1 expanded asset pools heavily but kept 2–4 surface templates per form. v2 targets **10–15 distinct surface templates per form**. Asset pools are not the bottleneck; templates are.

---

## v1 Reference (preserved below)

The sections below are the original v1 rulebook. Anything that conflicts with v2 above is superseded by v2.

## Core ratio

- Target ratio across all major files:
  - `70%` India-context examples
  - `30%` global-context examples

Interpretation:
- India-context should dominate the item pools, names, brands, chores, bills, transport, and note topics.
- Global examples are useful for generalization, but they are secondary.

Operational rule:
- target the `70/30` ratio inside every major lane, not only in the final dataset aggregate

## Global defaults

- Currency is INR-first.
- Foreign currency may appear rarely in input text, but output amounts remain numeric-only with no conversion.
- Weight unit is `kg` only in v1.
- Buy quantities may use common unit text like:
  - `kg`
  - `g`
  - `ml`
  - `L`
  - `pack`
  - `reams`
  - `bars`
- Date anchor for synthetic relative-date resolution is `2026-05-05`.

## Diversity requirements

The generator must not rely on a small pool repeated thousands of times.

Minimum expectations before the large run:
- Indian names: broad first-name coverage plus kinship/family-role names
- Indian expense pools: broad coverage across all frozen groups
- Buy pools: brand-heavy and item-heavy mixes
- Todo pools: action-style tasks and noun-style reminders
- Ledger reasons: wide everyday settlement/borrowing reasons
- Date phrasing: multiple relative, weekday, named-date, and short-range forms
- Query phrasing: both plain `ask:` and scoped `ask: <domain>:` forms
- Follow-ups: domain-preserving, filter-changing, range-changing, and intent-shifting examples

The generator should vary:
- separators
- order of amount and description
- comma/newline/bullet styles
- direct phrasing and natural-language phrasing
- typo-like search text
- single-entry and multi-entry writes
- default-range and explicit-range queries

Robustness should come from:
- realistic messy positives
- typo-like but plausible query phrasing
- Tanglish/Tamil-in-English phrasing where the user is likely to type that way
- explicit rejects for incomplete or wrong-lane input
- explicit confirms for ambiguous ledger direction

Robustness should not come from absurd positives such as:
- tiny expenses with lakh/crore-scale amounts
- dry grocery items with liquid units
- buy-list accepts that are really todo/bill/service actions
- item/unit pairings a real user would not mean

## Indian-context preference by domain

### Expense

Prefer examples such as:
- groceries:
  - poha
  - little millet
  - jaggery powder
  - curry leaves
  - aavin curd
  - idhayam sesame oil
  - brown chana
- transport:
  - auto fare
  - metro card topup
  - suburban rail pass
  - bus fare
- bills/utilities:
  - EB bill
  - broadband bill
  - LPG refill
  - water tax
  - apartment maintenance
- recharge/subscription:
  - Jio topup
  - Airtel recharge
  - DTH recharge
- dining:
  - filter coffee
  - curd rice
  - veg meals
  - tea
- vehicle:
  - petrol
  - diesel
  - parking
  - car insurance
  - puncture repair
- work:
  - xerox
  - courier charge

### Buy

Prefer examples such as:
- aavin curd
- idli rice
- hing
- poha
- surf excel
- dove
- lux
- scrub pad
- floor cleaner
- steel lunch box
- sink strainer
- asafoetida
- green tea jasmine

Quantity realism matters:
- herbs/leaves like `kothamalli`, `puthina`, `karuveppilai` should usually be bare items or small count-like entries, not `ml` / `L`
- spices like `kadugu`, `jeeragam`, `milagu` should strongly prefer gram-style quantities
- vegetables like `vengayam`, `thakkali` should prefer `g` / `kg`
- liquid/cleaning items like `phenyl`, `hand wash`, `oil` should prefer `ml` / `L`
- avoid exaggerated count values for ordinary retail items unless the item itself clearly implies bulk packaging

### Todo

Prefer Indian everyday/admin/reminder contexts such as:
- pay EB bill
- renew gas connection papers
- submit hostel reimbursement
- book train tatkal
- renew library card
- send rent receipt to admin
- refill asthma prescription
- scan passport
- pay newspaper vendor

### Weight

Prefer Indian names and family-role names such as:
- Kavya
- Kabir
- Noor
- Leela
- Zoya
- Vihaan
- Isha
- amma
- appa
- chitti
- anna

Global names remain useful, but should be secondary.

### Ledger

Prefer personal-debt examples with Indian-style person naming and everyday reasons such as:
- rent share
- train tickets
- dinner bill
- pharmacy pickup
- advance for booking
- UPI transfer follow-up

### Notes

Prefer note topics like:
- inverter noise
- metro recharge
- monsoon water storage
- seed trays
- EB meter reading
- terrace cleaning
- local model latency
- pantry stock
- festival shopping list fragment

## Allowed Indian large-number behavior

The dataset should actively cover:
- `5k`
- `12,500`
- `1.5L`
- `2 lakh`
- `3 crore`
- `1.25 lakh crore`

Use these more often in `expense:` and `ledger:` than in other lanes.

## Query-scope behavior

The dataset should include both:
- plain `ask:`
- scoped query hints such as:
  - `ask: expense:`
  - `ask: buy:`
  - `ask: todo:`
  - `ask: weight:`
  - `ask: ledger:`
  - `ask: note:`

Interpretation:
- scoped `ask` is an input-side narrowing hint
- output schema still emits the canonical parsed `domain`

Coverage expectation:
- include a healthy mix of plain `ask:` and scoped `ask: <domain>:` examples for every active retrieval domain

## Diversity guardrails

Do:
- vary item/amount ordering
- vary separators
- vary single-entry and multi-entry writes
- vary direct and natural-language phrasing
- vary date phrasings
- vary scoped and unscoped query forms
- vary note-search paraphrases
- vary follow-up intent shifts such as:
  - total -> list
  - open -> done
  - history -> latest
  - summary -> person-filtered view

Do not:
- drift into business accounting
- drift into medical advice
- overuse foreign items/brands relative to Indian ones
- overuse rare units or non-kg weight units
- reintroduce note-write training examples into `parse_write/`
- let one tiny source pool create the illusion of dataset scale

## Quality target for the first large dataset

- schema-consistent
- India-first
- enough breadth to stress:
  - group inference for expense
  - quantity parsing for buy
  - open/done and date handling for todo
  - self/default handling for weight
  - direction / settlement / repayment for ledger
  - note retrieval with typo-tolerant query text
  - follow-up inheritance across all active retrieval domains

Review gate before generation:
- inspect the generator asset/template report
- confirm pool sizes and coverage feel materially broader than the sample-review generator
- only then run the full 29k-row generation

After generation:
- if very large requested counts exceed the true unique phrasing space for a lane, soft uniqueness with controlled repeats is acceptable
- repeated rows are more acceptable in `reference_only/` than in core training lanes
- `reference_only/` is intentionally not part of SFT parser training; it exists for review/reference behavior only, especially deterministic `note:` save behavior
