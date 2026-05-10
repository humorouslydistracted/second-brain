# Dataset v2 Plan

Single source of truth for the next dataset generation and the next fine-tune run. Built from the discussion in this session after analysing `results.txt` failures against the v1 generator (`generate_large_schema_frozen_dataset.py` + `synthetic_dataset_assets.py`) and the v1 schema (`finetuning_data_sanity.md`).

This document **replaces or supersedes** the corresponding sections of:
- `finetuning_data_sanity.md` — schema, intent vocabulary, dispositions
- `dataset_india_context_rulebook.md` — Tanglish budget, template/coverage rules

Once the user approves this plan, those two docs should be updated to reference (or fold in) the relevant parts. The v1 dataset and the current adapter are not retroactively affected — this only governs the v2 dataset and any v2 fine-tune.

---

## 1. Frozen v2 schema

### 1.1 Tasks
Unchanged from v1: `parse_write`, `parse_query`, `parse_followup_query`.

### 1.2 Dispositions

| Task | Allowed dispositions | Default |
|---|---|---|
| `parse_write` | `accept` \| `confirm` \| `reject` | (no default; always set) |
| `parse_query` | `accept` \| `clarify` \| `reject` | `accept` |
| `parse_followup_query` | `accept` | `accept` |

`clarify` and `reject` on `parse_query` are **new in v2**.

### 1.3 Per-domain intents — HARMONIZED

The single biggest v2 change. v1 had four different names for "latest" across domains. v2 collapses to one canonical name per concept.

| Domain | v2 intents |
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
| `day_bucket` (note) | `list` with date_start = date_end | merged |
| `recent` (note) | `list` with date filters | merged |
| `latest_day` (buy) | `list` with date_start = date_end = today | merged |
| `latest_balance` (ledger) | `summary` with `limit=1` ordered by recency | merged |
| `open_summary` (ledger) | `summary` | renamed |
| `settled_list` (ledger) | `search` with `filters.status = "settled"` | merged |

**Domain disambiguation comes from two signals**:
1. The **scoped tag** (`ask: weight: latest`, `ask: notes: latest`) — primary, since the user has confirmed they will lean on this.
2. **Domain words** in the input (`weight`, `expense`, `ledger`, etc.) — secondary fallback when scoped is absent.

### 1.4 Reason codes

`parse_write` rejects (unchanged from v1):
- `incomplete_input`
- `invalid_lane_content`
- `ambiguous_direction` (ledger only)

`parse_query` rejects (new in v2):
- `multi_person_compare_unsupported`

`parse_query` clarify reasons (new in v2):
- `looks_like_action`

### 1.5 Filter shapes

Mostly unchanged from v1; clarifications below.

**expense filters:**
```json
{ "group": str | null,
  "description_text": str | null,
  "exclude_group": str | null,
  "exclude_description_text": str | null }
```

**buy filters:**
```json
{ "status": "open" | "done" | null,
  "item_text": str | null }
```

**todo filters:**
```json
{ "status": "open" | "done" | null,
  "text_match": str | null }
```

**weight filters:**
```json
{ "person_text": str | null }
```

**ledger filters:**
```json
{ "person_text": str | null,
  "perspective": "i_owe_them" | "they_owe_me" | null,
  "status": "open" | "settled" | null }
```

**note filters:** `{}` (no filters; date span goes in date_start/date_end, search text goes in query_text).

**Multi-person compare for weight: NOT supported.** Such queries return a `parse_query` with `disposition: "reject"`, `reason_code: "multi_person_compare_unsupported"`, and all other fields null. Per session lock.

### 1.6 Clarify shape — `parse_query` with `disposition: "clarify"`

```json
{
  "task": "parse_query",
  "domain": "<domain>",
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

Used for `ask: settle <person>` style action-shaped queries. Runtime renders the menu and converts the chosen option to either a write (settle) or a query (settled list).

### 1.7 Reject shape — `parse_query` with `disposition: "reject"`

```json
{
  "task": "parse_query",
  "domain": "<domain>",
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

---

## 2. Tanglish budget — locked

| Lane | Pattern A (Tamil noun in English) | Pattern B (English noun + Tamil verb / time / postposition / dative) | Pattern C |
|---|---|---|---|
| expense write | high — Tamil item words (`vengayam`, `kothamalli`); mixed-script multi-entry OK | 0 | 0 |
| buy write | high — same as expense | 0 | 0 |
| todo write | rare (todo objects mostly English) | ~50% — full blend: verbs (`pannanum`, `kattanum`, `podanum`) + time (`naliku`) + postpositions (`kitta`, `ku`) + datives (`amma ku`, `friend kitta`) | 0 |
| weight write | 0 | 0 | 0 |
| ledger write | 0 | 0 | 0 |
| ledger reason note | dropped entirely (no reason notes in v2) | dropped | dropped |
| weight write note | English only (`before breakfast`, `after walk`) | 0 | 0 |
| note write | excluded from SFT | excluded | excluded |
| expense query | medium — Tamil item names inside English (`expense for vengayam this month`) | 0 | 0 |
| buy query | medium — same | 0 | 0 |
| todo query | low — todo objects mostly English | 0 | 0 |
| weight query | 0 | 0 | 0 |
| ledger query | 0 | 0 | 0 |
| note query | medium — Tamil keyword in English frame (`notes about kothamalli`) | 0 | 0 |

**Tanglish date phrases** (`innaiku`, `nethu`, `naalaiku`, `indha maasam`, `pona maasam`) are Pattern C and **excluded from queries entirely**. They may appear inside todo-write Pattern B contexts only (`naliku room clean pannanum`).

Concrete generator implication:
- `_TANGLISH_SINGLE_DATES` and Tanglish keys in `RANGE_OPTIONS` are **not used by query generators**.
- They are used **only by todo-write Pattern B** rendering.

---

## 3. Form frequency weights — locked, with scoped revised to 25–35%

Per Q1 the user will lean on scoped queries (`ask: weight: latest`) for disambiguation. So scoped share is bumped from the original 2–5% straw-man to 25–35% per lane. Within scoped, the intent mix should match the unscoped distribution proportionally (i.e., scoped also has high `latest`/`list`/`total` and low `compare`/`change`).

### 3.1 Per-lane query distributions

| Lane | Unscoped distribution | Scoped share |
|---|---|---|
| expense | total 22%, list 18%, today 7%, group 7%, desc 6%, recent 5%, last_month 3%, exclude 2%, compare 1%, history 1% | scoped 28% |
| weight | latest 35%, history 12%, latest_all 8%, trend 6%, date 6%, change 3%, multi_person_compare_reject 3% | scoped 28% |
| ledger | summary 18%, balance 14%, person 11%, who 11%, recent 7%, range 4%, search 3%, latest 2%, action_clarify 4% | scoped 28% |
| buy | list 35%, search 18%, today 7%, date 5%, all 5% | scoped 30% |
| todo | list (open) 28%, today 11%, search 9%, all 7%, due_week 7%, history 4%, done_today 4% | scoped 30% |
| note | search 32%, list (recent/day/range) 24%, latest 11%, list (absolute date) 3% | scoped 30% |

Scoped rows internally use the same intent distribution as unscoped, weighted by the unscoped percentages above. So scoped expense → 30% `total`, 24% `list`, etc.

### 3.2 New intents introduced by Q3 / Q4

- `multi_person_compare_reject` — counted as part of weight's distribution (3%); generates `disposition: reject` rows. The 3% weight (vs the 2% straw-man) was chosen so the §5.6 explicit row target (~150 rows in 4000) is hit naturally inside the lane budget.
- `action_clarify` — counted as part of ledger's distribution (4%); generates `disposition: clarify` rows. The 4% weight was chosen so the §5.5 explicit row target (~200 rows in 4000) is hit naturally.
- `history` for expense — small share (~1%); per Q2, maps to `intent: total`, current month range.

---

## 4. Phrasing pool expansion

### 4.1 Templates per form
Target **10–15 distinct surface templates per form**. v1 had 2–4 in most cases.

### 4.2 Surface-style mix per form (across templates)

- **35% noun-phrase / fragment** style (`pending tasks`, `latest weight`, `today expenses`, `open ledger`)
- **30% verb-led English** (`show my pending tasks`, `what is my latest weight`)
- **20% question-shaped** (`who owes me money`, `what's left to buy`, `what was I going to do`)
- **15% Pattern A / Pattern B** where the lane budget allows (per §2)

### 4.3 Specific over-investment targets

- **High-frequency intents** (`total`, `list`, `latest`, `summary`, `balance`) — 15 templates each.
- **Low-frequency intents** (`compare`, `change`, `exclude`, `history`) — 8–10 templates each.
- **Scoped variants** — every intent gets at least 5 scoped templates so the scoped path is robust outside narrow patterns.

### 4.4 Style examples

Noun-phrase style examples (the share that was missing in v1):
- `pending buy items`, `today expenses`, `latest weight`, `open ledger`, `recent ledger`, `weight history`, `task history`, `what i owe`, `who owes me`, `total spend`, `expense list`, `monthly expense`, `done todos`, `done buy items`, `settled ledgers`.

Question-shaped:
- `who owes me`, `whom do i owe`, `what's pending`, `what did i finish today`, `what's left to buy`, `what's due this week`.

---

## 5. New slices

### 5.1 Adversarial domain pairs (~400 pairs / 800 rows)

Generate pairs of queries with the **same person name** but **different domains**, side by side in the dataset:
- weight ↔ ledger (e.g., `ask: ravi latest weight` paired with `ask: ravi balance`)
- weight ↔ todo (e.g., `ask: ravi latest weight` paired with `ask: call ravi todo`)
- weight ↔ note search (e.g., `ask: ravi latest weight` paired with `ask: notes about ravi`)

This forces the model to attend to the domain word, not the person name.

### 5.2 Bare nameless variants (up to 10% of single-person retrieval lanes)

Currently the self-path is gated on `my` / `en`. These bare variants are not trained:
- weight: `latest weight`, `weight history`, `weight trend`, `weight change`
- expense: `total spent`, `today spending`, `expense list`
- todo: `pending tasks`, `today tasks`
- buy: `pending buy items`, `today buy list`

Map to `person_text: "self"` (weight) or `null` (where person isn't a filter).

### 5.3 Real typo generator (~7% of search query rows)

Lanes covered:
- note search
- expense `description_text` filter
- buy `item_text` filter
- todo `text_match` filter

Transforms (one applied per row):
- vowel swap (a↔o, e↔i)
- adjacent transposition (`philosophy` → `phliosophy`)
- single-letter drop
- double-letter drop (`commontask` → `comontask`)
- phonetic substitution (`ph↔f`, `sh↔ch`, `c↔k`)

Skipping ledger and weight queries (no free-text filter that benefits from typo robustness).

### 5.4 Scoped query coverage
Per §3, scoped is now 25–35% per lane. Generator must produce scoped rows for **every intent** in each domain — not just one or two phrasings.

### 5.5 Action-shaped query clarify (~200 rows)

`ask: settle <person>` and similar action-shaped queries → `disposition: clarify`.

Phrasings to cover:
- `ask: settle ravi`
- `ask: settle ravi amount`
- `ask: clear ravi ledger`
- `ask: settled ravi amount` (past tense — should still clarify, since user intent is ambiguous between "show settled" and "settle now")
- `ask: close ravi balance`
- `ask: pay ravi back`
- `ask: write off ravi`
- `ask: clear ravi account`

Output:
```json
{
  "task": "parse_query",
  "domain": "ledger",
  "disposition": "clarify",
  "clarify_reason": "looks_like_action",
  "clarify_options": ["yes - settle now", "show settled list"],
  "intent": null, ...
}
```

### 5.6 Multi-person compare reject (~150 rows)

Phrasings to cover:
- `ask: compare murugan and jeevi latest weight`
- `ask: ravi vs anand balance`
- `ask: amma vs appa weight history`
- `ask: jeevi and prani weight trend`

Output:
```json
{
  "task": "parse_query",
  "domain": "weight",
  "disposition": "reject",
  "reason_code": "multi_person_compare_unsupported",
  ...
}
```

Counted in weight's distribution (~2%) per §3.

---

## 6. Reject pool widening

Per Q5, reject inputs sample from the **full asset pool** instead of the current 6 hardcoded items per lane.

| Lane | v1 reject pool | v2 reject pool |
|---|---|---|
| expense desc-only reject | 6 hardcoded items | sample from full `INDIA_EXPENSE` + `GLOBAL_EXPENSE` (~500 items) |
| expense amount-only reject | 5 hardcoded amounts | sample from amount-format generator |
| expense invalid-lane reject | 6 hardcoded actions | sample from `INDIA_TODOS` + `GLOBAL_TODOS` |
| buy incomplete reject | 6 hardcoded fragments | sample from time/quantifier/pronoun pool |
| buy invalid-lane reject | 6 hardcoded service items | sample from `INDIA_TODOS` (filtered to service/admin actions) |
| todo incomplete reject | 6 hardcoded fragments | sample from time/qualifier-only pool |
| weight invalid-lane reject | 6 hardcoded items | sample from waist/lb/measurement pool + name without value |
| ledger ambiguous-direction reject | curated | rotated through `INDIA_NAMES` + `GLOBAL_NAMES` with bare amounts |

Total reject share per write lane stays **10–12%** (current).

The same item may appear in both an accept row (with amount) and a reject row (without amount). The rule is structural ("no amount → reject"), not item-specific. Confirmed acceptable.

---

## 7. Anchor-date strategy

Per Q8 → option (b): inject the current date into the prompt template, train with multiple anchors so the model learns to use the prompt's date as the anchor.

### 7.1 Multiple training anchors

Each row in the dataset is generated with one of **several anchor dates** spread across the year:

```
2026-01-15
2026-03-15
2026-05-15
2026-08-15
2026-11-15
```

(Five anchors as a starting point. Could be 7–10 if needed for breadth.)

For each row, all relative date phrases (`today`, `yesterday`, `last month`, `this week`, etc.) resolve **relative to that row's anchor**. The row also stores its anchor in metadata so training can emit it in the prompt.

### 7.2 Prompt template change

Both training and inference prompts gain a `Today: <YYYY-MM-DD>` line in the system message:

```
You are a parser for a tag-first personal data app. Return JSON only...
Today: 2026-05-15
```

At inference, the runtime injects the actual current date.

### 7.3 Date phrase breadth (per Q12)

For each lane that uses dates:
- **60%** use the canonical date phrasings (`today`, `yesterday`, `this month`, `last month`, etc.).
- **30%** pull a **random** key from the full `RANGE_OPTIONS` / `SINGLE_DATE_OPTIONS` pool (so `past 60 days`, `quarter to date`, `april second week`, `current financial year` all get exposure).
- **10%** are absolute calendar dates (`on may 9`, `from april 16 to april 30`).

Tanglish date keys (`innaiku`, `indha maasam`, etc.) are **excluded from queries** per §2; used only in todo-write Pattern B contexts.

---

## 8. Schema diff: v1 → v2

| v1 | v2 | Action |
|---|---|---|
| 4 different "latest" intent names | single `latest` per applicable domain | merge in generator + sanity doc |
| `latest_bucket`, `day_bucket`, `recent` (note) | `latest`, `list` (with date filters) | merge |
| `latest_day` (buy) | `list` (date=today) | merge |
| `latest_balance` (ledger) | `summary` (limit=1) | merge |
| `open_summary` (ledger) | `summary` | rename |
| `settled_list` (ledger) | `search` (status="settled") | merge |
| no `disposition` on parse_query | `accept`/`clarify`/`reject` | add field |
| no `clarify_reason`, `clarify_options` | added | add fields |
| no `reason_code` on parse_query | added | add field |
| `expense history` not mapped | maps to `intent: total`, current month | add form |
| no multi-person compare handling | reject with `multi_person_compare_unsupported` | new slice §5.6 |
| no `looks_like_action` clarify | added | new slice §5.5 |
| 4 hardcoded "latest" patterns per domain | 10–15 templates per form | expand templates |
| Tanglish gated by single bool | per-pattern (A/B/C) gating per lane | gating refactor |
| ledger reason notes attached to write records | dropped | drop field path |
| Tanglish date phrases used in queries | excluded from queries | restrict usage |
| single anchor 2026-05-05 | multiple anchors per dataset, prompt-injected | generator + prompt refactor |
| `o→0` typo | realistic typo module | new module §5.3 |

---

## 9. Implementation phasing

Touch order, with status as of the most recent session:

1. **DONE — `finetuning_data_sanity.md`** — schema sections reflect v2 (intents, dispositions, reason codes, clarify/reject shapes). See "Shared Schema Freeze v2".
2. **DONE — `dataset_india_context_rulebook.md`** — v2 amendments at top cover Tanglish per-pattern budget, scoped share, concision, anchor strategy.
3. **DONE — `synthetic_dataset_assets.py`**:
   - `INDIA_LEDGER_REASONS` / `GLOBAL_LEDGER_REASONS` retained in the file but no longer imported by the v2 generator (per §11 — keeps the diff clean and v1 generator still works).
   - Added `TANGLISH_SINGLE_DATE_KEYS` and `TANGLISH_RANGE_KEYS` constants so the v2 generator can filter Tanglish keys out of query date pools.
   - Tamil item words stay in `INDIA_EXPENSE` / `INDIA_BUY`.
4. **DONE — `generate_large_schema_frozen_dataset_v2.py`** (new file; v1 generator preserved untouched at `generate_large_schema_frozen_dataset.py`):
   - New intent vocabulary (§1.3, §8). v1 names (`latest_bucket`, `day_bucket`, `latest_day`, `latest_balance`, `open_summary`, `settled_list`, note `recent`) collapsed.
   - parse_query disposition handling: `parse_query_accept` / `parse_query_clarify` / `parse_query_reject` builders emit a uniform field set across all dispositions (§1.6, §1.7).
   - Per-lane × per-pattern Tanglish gating (§2). Pattern C is 0% everywhere; Tanglish dates only inside todo-write Pattern B.
   - Per-form weighted distribution (§3) with scoped 28–30% per lane and Pattern A 0–18% per applicable slot.
   - Phrasing pool expansion (§4): 8–17 templates per form, 35/30/20/15 noun/verb/question/Tanglish-A mix.
   - Adversarial slice generator (§5.1) → dedicated `parse_query/adversarial.jsonl` so pairs survive per-lane shuffling.
   - Bare-nameless slice (§5.2) at 10% rate on weight/expense/todo/buy/ledger applicable forms; weight bare maps to `person_text: "self"`.
   - Real typo module (§5.3) at ~7% on note search / expense desc / buy search / todo search; the typo is applied to both input phrase and filter field.
   - Scoped query coverage at 25–35% per lane (§5.4) wired through `SCOPED_SHARE`.
   - Action-shaped clarify (§5.5) — ~200 rows / 4000 ledger lane.
   - Multi-person compare reject (§5.6) — ~150 rows / 4000 weight lane.
   - Reject pool widening (§6) — desc-only / amount-only / invalid-lane samplers draw from the full asset pools (1k+ items each lane).
   - Multi-anchor generation (§7.1) — every row carries a top-level `anchor_date`.
   - Date-phrase routing (§7.3) — 60% canonical / 30% random named-relative / 10% absolute; Tanglish keys filtered out of query pools.
   - Output dir: `synthetic_finetune_dataset_v4_v2_schema/`. `reference_only/` is intentionally not generated.
   - `--report` exposes per-anchor option counts, lane form-weight totals, scoped/Pattern A/B shares, parse_write smoke (500 rows/lane), parse_query smoke (1000/domain), §5 slice projections, typo / bare-nameless smoke, adversarial smoke, and parse_followup smoke.
5. **DONE — `evaluate_finetune.py`** — scores v2 parse_query disposition / clarify_reason / clarify_options / reason_code with per-row schema routing (presence of `disposition` on a `parse_query` expected → v2 row; v1 rows score on legacy metrics only). Per-row `anchor_date` drives a `Today: <YYYY-MM-DD>` line in the system prompt at inference. GPU-only imports (`unsloth`, `torch`, `peft`, `FastLanguageModel`) moved inside `evaluate_model()` so the file is `.venv`-importable for offline scoring.
6. **DONE — `generate_eval_dataset_v3.py`** (new file; `generate_eval_dataset_v2.py` preserved). Imports v2 makers + `pick_anchor_iso` from the v2 generator. Output dir: `eval_finetune_dataset_v3_schema_frozen/`. Each row carries `anchor_date`. `--report` mode supported. De-dups against `synthetic_finetune_dataset_v4_v2_schema/` when present. No coverage-bucket fronting (relies on v2 maker per-form weights + global shuffle). **Configurable size via `--total <N>`** (post-§9 addition): proportional 40% writes / 42% queries / 18% followups distribution with a hard floor of 1 row per lane / domain so every file is represented even at small totals (e.g., `--total 50` → 47 rows with 3-4 per lane / domain; `--total 100` → exactly 100; `--total 500` → exactly 500, matching the historical default). Per-bucket flags (`--write-per-lane`, `--query-per-domain`, `--followup-count`) still override individual buckets when set explicitly.
7. **DONE — `colab_finetune.py`** — `colab_finetune_old.py` was modified to inject `Today: <anchor_date>` into the system prompt during chat-template formatting (rows missing `anchor_date` keep historical framing byte-identical), then renamed to `colab_finetune.py`. The earlier "later revised" `colab_finetune.py` was deleted. There is now a single Colab training script. **Post-§9: Kaggle notebooks shipped** (`kaggle_finetune.ipynb`, `kaggle_evaluate.ipynb`) because Colab free-tier GPU was too restrictive — Kaggle is now the primary fine-tune + eval path. The Kaggle notebooks mirror `colab_finetune.py` and `evaluate_finetune.py` with `/kaggle/input/` + `/kaggle/working/` paths, no Drive mount, optional Kaggle Secrets for `HF_TOKEN`, and inlined helpers (the eval notebook is fully self-contained — no need to upload the source repo).
8. **DONE — `second_brain_finetuned_parser.py`** — adds `today_injection_enabled()` and `build_system_prompt(today_iso)`. `parse()` injects `Today: <real_today>` at every inference when the env flag `SECOND_BRAIN_FINETUNED_PARSER_TODAY_INJECTION` is on. **Default off** so the current v1 adapter path stays byte-identical. Surfaced in `status()`.

After step 4, run `--report` to verify asset/template breadth before generating the full dataset (per the rulebook's review gate). The full v2 generation (`python generate_large_schema_frozen_dataset_v2.py`) is an explicit user decision; a 100/lane review-grade generation was run in this session and analyzed (see §13). The full 4000/lane training run has NOT been executed yet.

---

## 10. Out of scope / explicitly NOT changing

- **Note write reference rows** — still deterministic, still excluded from SFT.
- **Compare for buy / todo / note** — still not supported.
- **Compare for ledger across persons** — still not supported (per Q3 lock).
- **Pattern C** — 0% across all lanes.
- **Note write content** — not part of parser SFT.
- **Foreign currency conversion** — still numeric-only-with-warning per v1 contract.

---

## 11. Open items

Resolved during the v2 generator implementation session:

- ~~Whether to **drop** `INDIA_LEDGER_REASONS` / `GLOBAL_LEDGER_REASONS` from the assets file entirely or just stop using them~~ → **stopped using them.** v2 generator does not import them; v1 generator still does. Kept in the file for historical clarity.
- ~~Whether the `Today:` line should be in the **system message** or in a separate **user-message prefix**~~ → **system message** (per session lock).
- ~~In-place rewrite vs new file for the v2 generator~~ → **new file** (`generate_large_schema_frozen_dataset_v2.py`); v1 generator preserved.
- ~~Adversarial pairs interleaved into per-domain lane files vs dedicated file~~ → **dedicated file** (`parse_query/adversarial.jsonl`) so pairs can't be lost to per-lane shuffling.

Resolved during the v2 review session (§13):

- ~~Anchor count (5 vs 7 vs 10)~~ → kept at 5 anchor *months*, but **day-of-month is now randomized per row** within each anchor month (year fixed at 2026). This widens `Today: <YYYY-MM-DD>` token exposure during training without changing seasonal coverage. `ANCHOR_MONTHS` is now the live driver in the v2 generator; `ANCHORS` is retained as a back-compat list of day=15 representatives.
- ~~Form weight calibration for §5.5 / §5.6 slices~~ → 3% / 4% weights produced 6 multi-person-reject rows and 4 action-clarify rows in the 100-row review generation, both within statistical band. No retune needed at the current row targets.

Still open / revisit later:

- Literal "ledger" word usage in ledger queries is at 38% (down from 66% in pre-review smoke; soft target was ≤30%). Acceptable to user at this level; can be trimmed further by removing more retained "ledger" phrasings, but those are real user wordings.
- Buy and todo list templates have residual hot strings (`"buy list"` 5×/100, `"list open todos"` 4×/100). Could be widened with another 5–8 templates per hot form to drop peak repetition.
- Pattern A surface in queries is lower than `PATTERN_A_SHARE` would suggest, because most query template `tanglish_a` buckets are now empty (the kaatu/Pattern C purge in §13 emptied them). Tamil words still surface naturally through item placeholders (`{desc}`, `{q}`, `{item}`) when the asset pick is a Tamil word. If you want more dedicated Pattern A queries, repopulate the empty `tanglish_a` buckets.

---

## 12. Validation gates before the next training run

Before pushing this dataset to a new fine-tune:

1. `--report` shows asset and template counts at or above v1 levels for every lane.
2. A 1k-row sample from each lane is human-reviewed for: schema correctness, Pattern-A/B presence per the budget, no Pattern C leakage, no Tanglish in disallowed lanes, scoped share roughly matches §3.
3. Held-out eval (v3) is regenerated with the v2 schema and the new prompt-injected anchor.
4. The runtime parser (`second_brain_finetuned_parser.py`) is updated to inject `Today:` and validated against the existing 43-prompt preset.
5. The eval script (`evaluate_finetune.py`) is updated to score the new fields.

Only after all five gates pass do we run the full v2 dataset generation and queue the next Colab fine-tune.

---

## 13. v2 review pass + Phase 3 asset expansion (post-§9 work)

Conducted across multiple sessions after §9 steps 1–8 landed, driven by a 100-row dry-run review of `synthetic_finetune_dataset_v4_v2_schema/`. Two batches of fixes plus an asset-pool expansion, then a fresh 100/lane regeneration that was reviewed clean.

### 13.1 Bug fixes in `synthetic_dataset_assets.py`

- **Missing comma in `TANGLISH_SINGLE_DATE_KEYS`** between `"naliku"` and `"kalila"` was silently concatenating into `"nalikukalila"` → `naliku` and `kalila` were not being filtered from query date pools. Fixed.
- **Invalid Tanglish range dates** `"indha varusam": (..., "2027-04-31")` and `"pona varusam": ("2025-04-31", ...)` (April has 30 days). Fixed to `04-30`.
- **`INDIA_BUY` polluted by service / fee items.** `_extend_unique(INDIA_BUY, INDIA_EXPENSE["work"])` and `_extend_unique(INDIA_BUY, INDIA_EXPENSE["education"])` were pulling in `school building fund`, `tuition fees`, `certificate attestation`, `cowork day pass`, `executive course fee` etc. as valid buy-list items. Both extends dropped. Buy is now extended only from `groceries` / `household` / `personal_care` / `shopping`.
- **Dropped `_TANGLISH_TRANSPORT` / `_TANGLISH_DINING` / `_TANGLISH_VEHICLE` / `_TANGLISH_LEDGER` lists.** Their entries were almost all `<English noun> kasu` (e.g., `auto kasu`, `tea kasu`, `petrol kasu`) which no real Tanglish user writes. Stripping `kasu` left only English; the underlying English items already exist in the corresponding `INDIA_EXPENSE[...]` pools.

### 13.2 Generator fixes in `generate_large_schema_frozen_dataset_v2.py`

- **Anchor randomization.** `ANCHORS` (5 fixed dates, all day=15) replaced by `ANCHOR_MONTHS = [(2026,1),(2026,3),(2026,5),(2026,8),(2026,11)]` + a new `pick_anchor_iso(rng)` helper that randomizes day-of-month per row. Year stays 2026. `ANCHORS` retained as a back-compat list of day=15 representatives. `_ANCHOR_OPTIONS_CACHE` / `_RANDOM_POOL_KEYS_CACHE` / `_ABSOLUTE_KEYS_CACHE` switched from precomputed dicts to lazy.
- **Time-of-day filter for queries.** Added `TIME_OF_DAY_KEYS` set; stripped `this morning` / `this evening` / `tonight` / `last night` / `early morning` / `this afternoon` / `morn` / `eve` / `night` etc. from `SEMANTIC_RANGE_ALIASES["today" | "yesterday"]`, from `query_safe_single_keys()` / `query_safe_range_keys()`, and from the random-pool builder. Writes still use these phrasings via the separate `WRITE_CANONICAL_SINGLE_KEYS` pool, since `expense: tea 20 this evening` is realistic write input.
- **Substring-overlap filter on buy multi-entry.** `make_buy_write` retries up to 25× to avoid a freshly-picked item textually overlapping (substring either way, case-insensitive) any already-chosen item in the same row. Fixes `salt + Anil salt` co-occurrences.
- **Ledger balance perspective fix.** `LEDGER_BALANCE_TEMPLATES` split into `LEDGER_BALANCE_NEUTRAL_TEMPLATES` / `LEDGER_BALANCE_I_OWE_TEMPLATES` / `LEDGER_BALANCE_THEY_OWE_TEMPLATES`. The maker now picks 50/25/25 across them and sets `perspective` to `null / i_owe_them / they_owe_me` to match the rendered phrasing. Was: random perspective regardless of phrasing — `tell me Nethra balance` was wrongly pegged to `i_owe_them`.
- **`kaatu` / Pattern C purge from query templates.** All query template `tanglish_a` buckets purged of `kaatu`, `pannu`, `vaanga vendiya`, `enna vanganum`, `enna seiyanum`, `enna mudichen`, `evlo pochu`, `selavu evalo`, `expense pannen`, `thavira expense`, `illama matha` etc. Pattern A retained only where natural: `note_search` (`notes la {q} irukka`, `{q} pathi notes irukka`) and `buy_search` (`buy list la {item} irukka`, `{item} buy list la irukka`). Empty `tanglish_a: []` falls back to `noun` via `render_template`.
- **Ledger query templates rewritten** away from literal "ledger" word toward natural phrasings (`balance`, `pending`, `owe`, `transactions`, `activity`). Word "ledger" usage dropped from 66% to 38% of ledger queries.
- **Other query template pools widened** by ~30–50% (note / expense / buy / todo).
- **`BUY_PREFIX_PATTERNS` / `BUY_TRIPLE_PATTERNS` Pattern B/C entries** (`vaanganum`, `vangikanum`, `kooda...yum`) removed. Per §2, buy write Pattern B/C share is 0%.
- **`report_assets()`** now reports `v2_anchor_months` + `v2_anchor_day_strategy` and uses one representative anchor per month for the per-anchor option snapshot.

### 13.3 Phase 3 asset pool expansion (≈2× corpora)

Append-only expansion block at the end of `synthetic_dataset_assets.py`. Every addition routes through `_extend_unique` (case-sensitive dedup); a final `_dedup_inplace` pass at the end of the file cleans residual duplicates from any per-group `.extend()` calls.

| Pool | Before | After |
|---|---:|---:|
| INDIA_NAMES | 462 | 707 |
| GLOBAL_NAMES | 170 | 376 |
| INDIA_NOTE_TOPICS | 385 | 631 |
| GLOBAL_NOTE_TOPICS | 180 | 329 |
| INDIA_BUY (after extends) | 546 | 1235 |
| GLOBAL_BUY | 156 | 252 |
| INDIA_TODOS | 2356 | 2548 |
| INDIA_TODO_NOUNS | 676 | 795 |
| GLOBAL_TODOS | 968 | 1088 |
| GLOBAL_TODO_NOUNS | 209 | 293 |

INDIA_EXPENSE per group: groceries 207→421, transport 28→58, dining 30→60, bills 24→50, recharge 87→184, household 109→262, health 34→78, personal_care 112→263, education 32→74, work 34→68, entertainment 29→56, travel 29→57, vehicle 35→68, shopping 40→79, other 34→67.

GLOBAL_EXPENSE per group: each group roughly doubled (groceries 68→122, transport 14→30, dining 14→28, bills 12→24, household 20→39, personal_care 17→34, education 10→23, work 10→25, entertainment 10→23, travel 17→35, vehicle 17→35, shopping 10→25, other 10→25).

Brand × product seeds also expanded: `_INDIA_GROCERY_BRANDS` 10→16, `_INDIA_GROCERY_PRODUCTS` 10→16; `_INDIA_HOUSEHOLD_BRANDS` 8→13, `_INDIA_HOUSEHOLD_PRODUCTS` 7→11; `_INDIA_PERSONAL_CARE_BRANDS` 10→15, `_INDIA_PERSONAL_CARE_PRODUCTS` 8→12; `_INDIA_RECHARGE_PROVIDERS` 9→13, `_INDIA_RECHARGE_TYPES` 7→10; `_INDIA_HEALTH_CONTEXTS` 8→16; `_INDIA_EDU_CONTEXTS` 8→16. Cartesians flow into `INDIA_EXPENSE[...]` and (for grocery/household/personal_care) into `INDIA_BUY` via the existing extend logic.

Tanglish corpora additions:
- `_TANGLISH_GROCERIES` +50 entries (real Tamil words: `vellam puli`, `karuppatti`, `pottukadalai`, `manatakkali vatral`, `araithu vitta sambar mix`, `kollu paruppu`, `ponni rice`, `kuruvai arisi`, `samba arisi` etc.).
- `_TANGLISH_HOUSEHOLD` +25, `_TANGLISH_PERSONAL` +20.
- `_TANGLISH_NOTES` +25 (`kollu rasam recipe note`, `vetrilai paaku list`, `veetu pooja items`, `kuthu vilakku oil refill` etc.).
- `_TANGLISH_TODOS` +52 Pattern-B blends (`amma medicine vaanganum`, `office la file submit pannanum`, `kid ku tuition pay panna`, `bank la kyc submit pannanum` etc.).
- `_TANGLISH_TODO_NOUNS` +24.

No native script (romanized only). No `kasu` suffix on English nouns (re-introducing the dropped Tanglish lists was explicitly avoided).

### 13.4 100-row review generation analysis

A fresh `synthetic_finetune_dataset_v4_v2_schema/` was generated at the v2 generator's defaults (100 rows per parse_write lane × 5, 100 per parse_query domain × 6, 50 adversarial pairs, 100 followup) — 1300 total rows.

**All schema validity checks pass:** 0 violations across `parse_write` / `parse_query` / `parse_followup_query` field sets, dispositions, clarify/reject shapes, `ledger.note=null` invariant.

**All Phase 1 + 2 regression checks remain clean:**
- 0 service/fee leakage in buy accept rows (across 14 sentinel terms).
- 0 substring overlap in buy multi-entry rows.
- 0 Pattern B/C residue (`vaanganum`/`vangikanum`/`kooda`) in buy writes.
- 0 `kaatu` / Pattern C residue across all 7 query files (note / expense / buy / todo / weight / ledger / adversarial) and followups.
- 0 time-of-day phrasings in queries.
- 0 Tanglish date keys leaking into queries.
- 0 ledger balance perspective mismatches (regex-strict on 20 balance rows).

**Anchor coverage:** 154 distinct anchor dates across 1300 rows (max possible ≈ 155). Per-month spread tight: `Jan 267 / Mar 239 / May 264 / Aug 263 / Nov 267`.

**Date resolution:** 98/98 correct across `today` (46/46), `yesterday` (4/4), `last month` (10/10 including 4 compare-intent rows that correctly use `compare_date_*` for the last-month range), `this month / current month` (38/38).

**Special slices firing:**
- 6 weight rejects (`reason_code: multi_person_compare_unsupported`).
- 4 ledger clarifies (`clarify_reason: looks_like_action`, `clarify_options: ["yes - settle now","show settled list"]`).
- 50 adversarial pairs, all weight-anchored, all sharing the same anchor + same person across both inputs.
- 100 followups, all `inherit_context: True`, all carrying valid `context.task=parse_query`, all domain-preserving.

**Asset coverage at n=100 rows/file:** 151 distinct buy items, 139 distinct expense descriptions (group spread covers all 15 groups), 98 distinct ledger person_text, 131 distinct todo text, 92 distinct weight person_text. Note query has 53 distinct `query_text` (only ~54 of the 100 are search-intent rows so the denominator is smaller). Expected to scale linearly with row count.

**Top-template repetition (peaks per 100 rows):**
- buy 5× (`buy list`)
- todo 4× (`list open todos`)
- ledger 3× (`open balance`, `what's outstanding`, `list of creditors`)
- expense 3× (`today's expense list`)
- note 2× (`latest note snippet`)
- weight 2×

Down from pre-Phase-3 peaks of 10× / 6×.

**Ledger word usage:** 38/100 (38%). Acceptable per user direction.

The dataset is review-clean and ready to scale up to a full training run. The 100/lane sample is preserved at `synthetic_finetune_dataset_v4_v2_schema/`. To run a full 4000/lane generation: `python generate_large_schema_frozen_dataset_v2.py --write-count 4000 --query-count 4000 --followup-count 4000` (this is an explicit user decision and has not been executed).

---

## §14 — 2026-05-09 patch round (post Build #27 device dogfood)

After build #27 was dogfooded on Pixel 7 with a 100-activity log
(`logs.txt`), an audit of the actual fine-tune behavior plus the
dataset surfaced one trainer bug and twelve dataset gaps. All twelve
patches landed in `generate_large_schema_frozen_dataset_v2.py` and the
related corpus additions in `synthetic_dataset_assets.py`. The trainer
bug landed in `colab_finetune.py`. **No new generation has been run
yet** — the user will regenerate at full size (5000/lane writes,
5000/lane queries, 6000 followups) before the next fine-tune cycle.

### §14.1 — Trainer fix (the headline)

`colab_finetune.py` was missing completion-only loss masking. SFTTrainer
with `dataset_text_field="text"` and no `data_collator` argument
computes loss across the entire chat template (system + user +
assistant), so the JSON output got only ~10–15% of the gradient
signal. The model learned generic chat-template tokens well and the
strict JSON shape weakly, falling back at inference to the simpler
`{"data":{...}}` pattern from pre-training.

Fixes shipped in `colab_finetune.py`:
- `MAX_SEQ_LENGTH` 1024 → 1536 (room for 12-item record JSON output).
- `ENABLE_PACKING` True → False (packing without completion-only loss
  leaks gradient across example boundaries).
- New call after `SFTTrainer(...)`:
  ```python
  from unsloth.chat_templates import train_on_responses_only
  trainer = train_on_responses_only(
      trainer,
      instruction_part="<|im_start|>user\n",
      response_part="<|im_start|>assistant\n",
  )
  ```

The dataset itself was always correct (100% of rows in
`synthetic_finetune_dataset_v4_v2_schema/` use `records:[]` not
`data:{}`); the trainer was the bug.

### §14.2 — Twelve dataset patches

All mapped 1:1 to a specific failure observed in the device log
(ACTIVITY #44 through #100 in `logs.txt`):

1. **Buy long-list 4-12 items.** `make_buy_write` adds a 12% branch
   picking N from `[4..12]` with declining weights. Was capped at 3.
   Fixes #48 (7-item buy → 1 logged), #77/#78/#79 (multi-item lost to
   broken multi-record JSON shapes).
2. **Todo long-list 4-8 + person-in-text variants.** New helper
   `render_todo_pattern_b_with_person` embeds real person names INSIDE
   the text field (`prabu son paaka ponum`). 25% of pattern-B chunks
   now use it. Trains the model that todo has no separate
   `person_text` slot — fixes the schema leak from #71/#72/#73 where
   the model emitted `data:{person_text:"prabu", action:"set_todo"}`
   bleeding ledger schema into todo.
3. **Expense long-list 4-10 items.** Same shape as buy patch.
4. **Trailing-comma augmentation.** 8% of multi-item buy/todo/expense
   rows append `,` or `, ` to the input. Output unchanged. Dataset
   previously had ZERO trailing-comma rows; user's `buy: A, B, C,`
   habit was OOD. Fixes #77/#78/#79 cascade.
5. **Buy undated bare phrasings.** `BUY_LIST_BARE` expanded from 3 to
   13 phrasings (added `list`, `show buy`, `whats on buy`, `what to
   buy`, `open buy`, etc.). Bare-rate in `make_buy_query` list form
   bumped 10% → 35%. Fixes #81/#82/#96 returning 0 rows because the
   model emitted `date_start=date_end=today` for these phrasings.
6. **Note bare-name clarify rows.** New `bare_name_clarify` form in
   `NOTE_FORM_WEIGHTS` (weight 7). Trains the model to emit
   `disposition:"clarify"` for bare names like `prani` or short
   ambiguous queries. Fixes #65 (`Maddy owe` → todo), #93 (`prani`
   → all todos).
7. **Expense filter null-bias rebalance.** `EXPENSE_FORM_WEIGHTS`
   shifted (desc 6→18, group 7→12, exclude 2→3) so filter-bearing
   share rises 21% → 43%. Plus 30% of desc-form rows now use undated
   phrasings (`total milk expense`, `expense on petrol`). Fixes
   #85/#88/#100 returning ₹34607 (everything).
8. **Ledger bare-balance with `perspective:null`.**
   `LEDGER_SUMMARY_BARE` expanded with `balance`, `balances`, `ledger
   summary`, `ledger`, etc. Bare-rate in summary form bumped 10% →
   30%. `perspective: null` enforced. Fixes #64 hallucinating
   `perspective:"i_owe_them"` for bare `ask: balance`.
9. **Tanglish verb branch in buy.** ~20% of india-mode accept rows
   render input with Tanglish verbs (`vanganum`, `vaanganum`,
   `kekanum`, `book pannanum`, `vendi irukku`) using new pools
   `BUY_TANGLISH_TRAILING_VERBS` / `BUY_TANGLISH_PER_ITEM_VERBS`,
   plus connectors `kooda`/`appuram`/`mattum`. Three input shapes:
   trailing-verb (35%), per-item-verb (20%), bare list (45%, the
   user's most common pattern from logs).
10. **English day-of-week in person-in-text todos.** New helper
    `_english_day_phrase_with_date` adds `tomorrow`, `weekend`,
    `next monday`, `this friday`, etc. as time prefixes. 50% of
    person-in-text rows use English phrase, 50% Tanglish. 30% put
    the date at the FRONT (`tomorrow prabu son paaka ponum`),
    70% at the suffix.
11. **Buy quantity input aliases.** 35% of india-mode rows replace
    canonical units in the displayed input only: `g→gms` (2/3 rate),
    `L→ltr/litre`, `kg→kgs` (occasional), `pack→packet`. Records
    keep canonical units. Matches user inputs like `paasi parupu
    500gms`, `milk 1ltr`.
12. **Settle/repay phrasings.** 25% of india-mode ledger accept
    rows use Tanglish (`{name} ku settle pannitten`, `kasu
    kudutiten`, `bakki kudutiten`, `vasooli pannita`). English
    settle/repay variants also expanded (`paid back fully`,
    `cleared {name} account`, `closed {name} account`, `done with
    {name}`).

### §14.3 — Corpus addition: `_TANGLISH_BUY_ONLY` pool

`synthetic_dataset_assets.py` adds a new `_TANGLISH_BUY_ONLY` list
extended into `INDIA_BUY`, containing the user's actual pure-Tanglish
items from device logs that have no clean English equivalent: `Manjal`,
`kasthuri methi`, `kasthuri manjal`, `Gaza gasa`, `killer nighty`,
`kili pachai saree`, `uluntha parupu`, `thuvam paruppu`, `paasi parupu`
plus 30+ more (vetrilai, paaku, elakkai, lavangam, pattai, karupatti,
panangkalkandu, cotton nighty, rayon kurta, silk saree, salwar set,
veshti, thundu, pavadai, jadai ribbon, thali kayiru, kal urai, ammi,
thosai kal, kuzhambu satti, ulakkai, kuduvai, muruku, thattai, sevai,
mysorepak, athirasam, boondhi laddu, ribbon pakoda, thenkuzhal, milk
peda, halwa packet, vasanai soap, kungumam, sandhanam, vibhuti packet,
agarbathi pack, sambrani cup). Per user direction: they will keep
typing buy in Tanglish for life and will not switch to English
equivalents.

### §14.4 — Smoke verification (500 rows/lane)

After the patches:
- Records-per-row extends to **11** (buy), **8** (todo), **10**
  (expense). Was capped at 3.
- Trailing-comma fires on ~4% of all rows (~8% of multi-item rows).
- Todo person-in-text rows: 3.4% of rows match
  `paaka ponum` / `kitta sollanum` / `ku call pannanum` shapes.
- Note `bare_name_clarify`: 9.4% of note queries are
  clarify-disposition.
- Buy undated `intent=list` rate: 68% of all list rows.
- Expense filter-bearing share: 43.2% (was 21%).
- Tanglish verb fires in ~7% of buy rows.
- All 10 user-named Tanglish items confirmed in `INDIA_BUY` pool.

### §14.5 — Round 2 patches (2026-05-09 same day, after deeper analysis)

After the user pushed back on whether the corpus was really robust enough
for "in this lifetime" usage, a corpus depth audit + schema gap analysis
surfaced 8 more generator additions and a substantial corpus expansion.
Conscious decision to NOT include Malayalam/Kannada/Telugu (user only
writes in Tamil/Tanglish/English). Conscious decision to NOT add
voice-to-text augmentation (user always types).

**Generator additions (8):**

13. **Currency notation depth.** `amount_text_and_value` extended from 8
    to 16 styles. New: `K_upper` (5K), `k_thousand` (5 thousand),
    `rs_dot` (Rs.5000), `rs_slash` (5000/-), `L_upper` (5L),
    `lakhs` (5 lakhs), `crores` (3 crores). Smoke verified all firing
    in expense + ledger writes.

14. **Absolute date format breadth.** New helper
    `pick_numeric_date_phrase` produces 15 numeric/named-month formats
    via lambda formatters: `15-02-2026`, `15/02/2026`, `15.02.2026`,
    `15-02-26`, `15-2`, `15/2`, `15th Feb`, `15 Feb`, `Feb 15`,
    `Feb 15th`, `15th of Feb`, full-month variants. Hooked into
    `pick_write_date_phrase` at 12% probability for any dated write row.

15. **Festival/event-relative dates.** New `_FESTIVAL_DATES_2026` map
    (24 festivals: Pongal, Republic Day, Holi, Tamil New Year, Vishu,
    Easter, Akshaya Tritiya, Ramzan, Eid, Bakrid, Aadi, Independence
    Day, Onam, Vinayagar/Ganesh Chaturthi, Navratri, Dussehra,
    Vijayadashami, Karthigai/Karthigai Deepam, Diwali/Deepavali,
    Christmas, New Year). Plus 14 personal-event templates
    (`before/after exam`, `wedding`, `birthday`, `paati function`,
    `house warming`, `puja`). Helper `pick_festival_date_phrase`
    resolves to a date 1-7 days before/after the festival; falls
    through if the festival has already passed and there's no following
    one. Hooked into `pick_write_date_phrase` at 8% probability.

16. **Top-N expense queries.** New `top_n` form added to
    `EXPENSE_FORM_WEIGHTS` (weight 5). Picks `n ∈ {3, 5, 10}`,
    renders `top {n} expenses`, `biggest {n} spending`, `highest {n}`,
    etc. Output emits explicit `limit: n`. ~33% of these rows also
    carry a date qualifier (`top 3 expenses this month`).

17. **Whitespace + casing augmentation.** New shared helper
    `apply_input_noise(input_text, rng, has_multi_items)` applied at
    the very end of all 5 write makers. Independent low-probability
    triggers: 4% double-space, 3% leading/trailing whitespace, 4%
    random ALL-CAPS or capitalize-mid-sentence on one word, 5%
    missing-space-between-letter-and-digit (`paasi parupu1kg`).
    Records output untouched.

18. **Mixed separator augmentation.** Same helper, 5% chance for
    multi-item rows to swap one comma with `;`, ` / `, ` + `, ` & `,
    or ` and `. Smoke verified all separators firing.

19. **Quantity fractions and ranges.** Buy maker's quantity-display
    pipeline now has a `display_qty` shadow alongside `display_unit`.
    8% of buy items with kg/g/ml/L units render as `half kg`,
    `1/2 kg`, `3/4 kg`, `2-3 kg`, `2 to 3 kg`, `~2 kg`, or
    `about 2 kg` in the input. Records keep canonical numeric
    `quantity_text` + `unit_text`. The qty-unit join logic was
    updated to add a space when the qty is non-numeric (so `half kg`
    stays as two words, not `halfkg`).

20. **Corpus expansion: 100+ Tanglish + 200 brand-product compounds.**
    `_TANGLISH_BUY_PHASE2` adds ~100 items across vegetables (chinna
    vengayam, periya vengayam, vazhakkai, vazhaipoo, kothavarai,
    siru/mulai/agathi keerai), pulses/grains (kollu, ragi, varagu,
    samai, thinai, kambu maavu, ragi maavu), snacks (muthusaaram,
    kara sev, ribbon pakoda, thattai, vadai variants, halwa
    variants), dairy (thayir, moru, panneer, more milagai),
    meat/fish (kozhi, naatu kozhi, aatu kari, meen variants, nandu,
    eral), ready-mix (rasam mix, sambar mix, idli mix, dosa mix,
    payasam mix), festival items (manjal kayiru, kolam podi,
    vibhuti pottu), salt variants (kal uppu, podi uppu, indu uppu).
    `_BRAND_PRODUCT_COMPOUNDS` adds ~200 brand+product entries
    across dairy (Amul, Aavin, Nandini, Mother Dairy, Heritage,
    Britannia, Country Delight), spices (Aachi, Sakthi, MTR,
    Eastern, MDH, Everest, Catch, Suhana, Ramdev), oils (Idhayam,
    Saffola, Fortune, Sundrop, Parachute), atta/flour (Aashirvaad,
    Pillsbury, Patanjali, 24 Mantra), rice (India Gate, Daawat,
    Lal Qilla, Sungold), dal (Tata Sampann, Patanjali, 24 Mantra),
    snacks (Lays, Haldiram, Britannia, Parle, Cadbury, Nestle),
    beverages (Boost, Bournvita, Horlicks, Tata Tea, Brooke Bond,
    Bru, Nescafe), soaps (Mysore Sandal, Cinthol, Liril, Pears,
    Dove, Lux, Hamam, Margo, Medimix, Patanjali, Himalaya),
    detergents (Surf Excel, Tide, Ariel, Henko, Rin, Wheel, Nirma,
    Ezee), household (Vim, Pril, Colin, Lizol, Harpic, Phenol,
    Odonil, Hit, All Out, Good Knight, Mortein), toothpaste
    (Colgate, Pepsodent, Sensodyne, Closeup, Meswak, Anchor,
    Patanjali, Dabur), baby (Pampers, Mamy Poko, Cerelac, Lactogen,
    Nestle Nan Pro), and others (Maggi, Yippee, Top Ramen, Knorr,
    iD, MTR ready meals). All extended via `_extend_unique` to
    `INDIA_BUY` and split-extended to relevant `INDIA_EXPENSE`
    groups (groceries / personal_care / household). Result: pool
    sizes grew INDIA_BUY 1288 → 1550, INDIA_EXPENSE['groceries']
    421 → 494, INDIA_EXPENSE['personal_care'] 263 → 288.

**Smoke verification at 800 rows/lane writes + 500/lane queries:**

- All 16 currency styles firing across expense + ledger
- All 5 absolute date formats firing across writes
- 53 festival/event-relative phrases across buy + todo + expense
- 29/500 expense queries are top-N with explicit `limit ∈ {3,5,10}`
- Input noise: 233 double-space, 172 leading/trailing, 57 ALL-CAPS,
  125 no-space-digit, 86 semicolon, 94 `and` separators
- Quantity variants: 6 `half`, 9 range-dash, 8 `~N`, 2 `about N`
- 102 buy rows mention a known brand (Amul, MTR, Sakthi, Mysore
  Sandal, etc.); all 15 spot-checked items confirmed in INDIA_BUY

**What this re-finetune does NOT include (deliberate):**

- **No Malayalam / Kannada / Telugu coverage.** User confirmed they
  only type in Tanglish + English. Adding 3 more languages would
  dilute Tanglish quality without serving real usage.
- **No voice-to-text augmentation.** User confirmed they always type.
- **No yes/no query intents** (`did i buy milk`) and **no when-did
  query intents** — these need new entries in `QUERY_INTENTS`
  validator + new runner branches in Kotlin. Deferred to a separate
  cycle that bundles the Android changes.
- **No status-change / delete-edit lanes.** Need new lanes in
  schema. Separate cycle.
- **No multi-keyword expense filter** (`milk and bread spend`).
  Needs new `description_text_set` schema field. Separate cycle.

### §14.6 — Date format reweighting (post 3k-smoke deep-analysis)

After the user inspected the 3k smoke and clarified their actual typing
pattern (`1,2,3-9,10-31 followed by space jan,feb,mar,apr,may,jun,july,
sept,oct,nov,dec; it may interchange to month folled by date; rarely
year will come into picture but it might; maybe 10 percent i will use
month in 01-12`), the absolute-date format pool was restructured:

- New helpers `_format_month_name_date` and `_format_numeric_date`
  replace the flat `_NUMERIC_DATE_FORMATS` lambda list.
- `_MONTH_ABBREVS_USER` enumerates the user's exact list (jan/feb/mar/
  apr/may/jun/`july`/aug/`sept`/oct/nov/dec — note the 4-letter
  `july` and `sept` per user's spec).
- Distribution: 85 % `<day> <month-name>` (70 % `<day> <month>`,
  30 % `<month> <day>`); 15 % numeric (`15-02`, `15/02`, `15-02-2026`).
- No leading zero on day. Day spans 1–31 with no zero-padding.
- Mixed lowercase / capitalized name + abbrev / full (~80 % abbrev,
  ~20 % full; ~70 % lowercase, ~30 % capitalized).
- Year present only on ~30 % of numeric forms.
- `pick_write_date_phrase` firing rate bumped 12 % → 18 % so each
  format gets ~150 examples per format at 5k rows/lane.

### §14.7 — Production regeneration (2026-05-09)

Full 5k/lane regeneration ran in 61 s, producing 61,800 rows total:

```
parse_write/{expense,buy,todo,weight,ledger}.jsonl  → 5 × 5000 = 25,000
parse_query/{note,expense,buy,todo,weight,ledger}.jsonl → 6 × 5000 = 30,000
parse_query/adversarial.jsonl                       → 800
parse_followup_query/mixed_followups.jsonl          → 6,000
GRAND TOTAL                                         → 61,800
```

**Production verification — 17/18 PASS, 1 expected DEFER:**

| Check | Result |
|---|---|
| Per-lane disposition health (89-91 % accept, ~10 % reject, +12 % confirm for ledger) | ✅ |
| Long-list 4+ records: buy 526 (max 12), todo 439 (max 8), expense 571 (max 10) | ✅ |
| Tanglish density: buy 13 %, todo 31 %, expense 9 %, ledger 9 % (weight 0.6 %, low but acceptable per user) | ✅ |
| Currency: all 8 styles fire 200-1500 each | ✅ |
| Absolute dates: `15 jan` 967, `Jan 15` 416, `25 January` 351, numeric (with year) 60, numeric short 252 | ✅ |
| Relative dates: today/yesterday/tomorrow 966, weekend 603, DOW 4742, Tanglish 422, festival 415, personal event 217 | ✅ |
| Input noise: double-space 1403, leading/trailing 928, ALL-CAPS 475, no-space-digit 751, all separators ≥ 50 | ✅ |
| Quantity variants: half 28, 1/2 8, range 35, ~N 35, gms 135, ltr 31, packet 263 | ✅ |
| Tanglish verb branch in buy: 332 rows | ✅ |
| Note bare-name clarify: 509 rows | ✅ |
| Buy undated list: 2,234 rows | ✅ |
| Expense filter-bearing share: 38.3 % (was 21 % pre-patch) | ✅ |
| Ledger settle/repay phrasings: 715 rows | ✅ |
| Top-N expense queries: 321 rows | ✅ |
| Pool exhaustion: 1,790 unique buy items used, peak 25× (toothpaste), 87 picked only once | ✅ |
| Reminder lane: 0 rows (correctly absent — deferred) | ✅ |
| Weekend phrase: 603 in writes, 183 in queries; resolves correctly to Saturday | ✅ |
| **Weekend-vs-weekday FILTER queries** | ⚠️ 0 (deferred — needs new schema field, not blocking) |

The dataset is **production-ready** for the next fine-tune cycle.

### §14.8 — Followup dataset cross-domain rows (Layer 3a) + question-shape weight queries (Layer 2)

After the production regen, user reported a hallucination: "I added Amma's
weight; when I asked for Jeevi's weight, it returned Amma's weight."
Concrete log (Activity #105) showed a different bug than the user
suspected. Two-failure stack:

1. **Parser failure**: model emitted `search_text: null` and no `filters`
   block for `ask: what is jeevi weight` — it did not extract "jeevi"
   at all. Dataset has `ask: jeevi weight` (works) but is thin on
   question-shape `what is X weight` / `what's X weight` / `weight of X`
   phrasings.
2. **Runner footgun**: `QueryRunners.runWeight` silently fell back to
   "most recent person in weights table" when filter was null. Most
   recent insert was Amma → returned Amma's weight as "Jeevi's weight".
   Confident wrong answer instead of "couldn't find Jeevi".

This was NOT a followup-context contamination bug. The Android port
doesn't pass prior query context to the parser — every parse call is
independent. But auditing the followup dataset itself surfaced a real
diversity gap: **6000/6000 (100%) of `parse_followup_query` rows are
same-domain**. Zero "context discard" rows. If/when followup
context-passing is wired on Android, the model would be biased toward
over-inheriting and produce Frankenstein cross-domain outputs.

#### Layer 1 — Kotlin runner fix (shipped 2026-05-09)

`QueryRunners.runWeight` now calls a new `resolvePersonForWeight(...)`
helper:
- If `filters.person_text` is set and not "self" → use it (existing path).
- Otherwise look at the original input text. Intersect lower-cased
  tokens against the union of (persons table names ∪ distinct persons
  in weights table). Single match → use it. Multiple matches → take
  the lexicographically first. **Zero matches → fall back to "self"**
  (no more "most recent person" footgun).

`QueryRunner.run` signature gained an optional `userText: String = ""`
parameter, threaded from `Orchestrator.handle` via `tagged.composed`.

Compiles cleanly. Ships in next APK without new training.

#### Layer 2 — question-shape weight templates (generator)

`WEIGHT_LATEST_TEMPLATES` expanded across all three style buckets
(noun / verb / question) with bare-question shapes the user actually
types:

- noun: `{person} weight`, `weight of {person}`, `weight {person}`,
  `{person}'s weight`
- verb: `show {person} weight`, `give me {person} weight`, `tell me
  {person} weight`, `show me {person}'s weight`, `fetch / pull up /
  find / look up {person} weight`
- question: `what is {person} weight`, `what's {person} weight`,
  `whats {person} weight` (no apostrophe — common typing artifact),
  `what is the weight of {person}`, `how much does {person} weigh`,
  `how much {person} weighs`, `do you know {person} weight`, `can you
  tell {person} weight`, `{person} weight please`, `{person} weight?`

Smoke verified at 500 weight queries: 44 hits across the new shapes
(~9 % of weight queries). Enough exposure for the model to learn the
phrasings without crowding out other forms.

#### Layer 3a — cross-domain followup rows (generator)

New helper `_followup_cross_domain(anchor, mode, rng)`:
- Pick a context domain and a different current domain from `{expense,
  buy, todo, weight, ledger, note}` (30 distinct ordered pairs).
- Generate a context from one of the existing query makers
  (`_accept_base_query(make_X_query, ...)`).
- Generate the current input/output from a different domain's maker.
- Return `{anchor_date, context, input, output}` where **`output.task =
  "parse_query"` (NOT `parse_followup_query`)** and the output's domain
  matches the current input's domain. The implicit signal: the prior
  context should be discarded.

`make_followup` fires this branch on 25 % of rows. Smoke verified at
2000 followup rows: 536/2000 (26.8 %) cross-domain, all 536 with
correct `task = "parse_query"` (zero misassignments). Coverage spans
all 30 (ctx_domain, current_domain) pairs with even distribution
(17–34 rows per pair).

#### Layer 3b — Android wiring (DEFERRED until after re-finetune)

Plan when ready:
- Store last accepted query JSON in `runtime_state` on every
  successful `parse_query`.
- `ChatTemplate.buildPrompt` gains optional `context: String? = null`
  parameter. When provided, the user message becomes
  `"Previous structured query context:\n{context}\n\nUser input:\n{text}"`
  (byte-identical to the dataset's training format).
- `Orchestrator.handle` for queries: pull the stored context and pass
  it. For writes: don't pass context.
- New runner branch: when `payload.task == parse_followup_query`,
  merge `inherit_context` fields with current query fields (filters,
  dates, intent overrides).

~150 lines of Kotlin. Held back until the new GGUF (with
cross-domain training) lands and validates — otherwise the model would
inherit too eagerly with no way to discard.
