# Second Brain App — Jupyter Notebook Implementation Guide

## Project Context

Building a fully local, on-device second brain app for Android (Pixel 7). The goal is to dump notes naturally in English and query them conversationally. The system must handle expenses, lending/borrowing, weight tracking, todos, investment notes, and health reference — all stored locally with no cloud dependency.

**Core philosophy:** Dump and forget. The app must retrieve accurately without needing the user to double-check every entry.

**Final target:** Android app (Pixel 7, 8GB RAM) using llama.cpp + Qwen (4-bit quantized) + ONNX MiniLM embeddings + SQLite. These Jupyter notebooks validate all logic before Android development begins.

---

## What These Notebooks Validate

Before building the Android app, we validate:
1. SQL schema correctness and query accuracy
2. Rule-based parser coverage and reliability
3. Qwen parsing quality on ambiguous inputs
4. Vector search relevance for investment and health queries
5. Full end-to-end flow with real queries

**Do not skip ahead.** Each notebook has exit criteria. Only proceed to the next when exit criteria pass.

---

## User's Note-Taking Patterns (Critical Context)

The user dumps notes in free-form English. No fixed structure. Notes are append-only — never edited, only new entries added.

### Expense Pattern
```
petrol 500
500 petrol
tomato 50, groceries 200, petrol 500
groceries 200
bore motor repair 7500
```
- Amount + description, order varies
- Comma-separated multiple entries in one shot
- Date = always timestamp of entry (now), never explicitly mentioned
- Amount is a whole number mostly

### Weight Pattern
```
jeevi 62
62 jeevi
jeevi 65.1 empty stomach
prani 11.3 after lunch
52 jeevi, 12 prani
murugan 65
```
- Name + number, order varies
- Multiple entries comma-separated
- Optional note after number (empty stomach, after lunch, night)
- Date = always timestamp of entry
- Weight can be whole number (52) or decimal (65.1)
- Child weights are small (10–15kg), adult weights are 55–75kg range

### Ledger Pattern
```
gave Maddy 5k
give Maddy 10k
Maddy gave 5k
got 5k from Mani
received 3k from thenna
Maddy returned 6k
lent Ravi 2000
sent Priya 1500
```
- Keywords: gave, give, given, lent, sent → user gave money to them
- Keywords: got, received, returned, paid back → they gave money to user
- Amount always 100+, usually in thousands
- New names can appear anytime (not a fixed list)
- "gift" keyword → expense, NOT ledger

### Todo Pattern
```
update Amit about MCP understanding
complete app development phase 1
order mushroom fried rice
haircut on thursday
call for kadai 2
```
- Free text, no fixed structure
- Comma-separated for multiple todos
- No amount, no person-money pattern

### Investment Notes
- Long-form, paragraph style
- Mix of facts, personal analysis, advice from others (Anand Srinivasan, PR Sundar)
- Stock names, PE ratios, buy/sell decisions
- Goes into vector store for RAG retrieval

### Health Reference
- Structured guide (psoriasis + histamine)
- Foods to avoid and eat
- Goes into vector store for RAG retrieval

---

## Disambiguation Rules (Pre-Parser Logic)

These rules run in order. First match wins.

### Rule 1 — Ledger Detection
Presence of any of these keywords + person name + amount → ledger entry:
- **User gave:** `gave`, `give`, `given`, `lent`, `sent`
- **User received:** `got`, `received`, `returned`, `paid back`
- Exception: if `gift` keyword present → expense, not ledger

Direction logic:
- `gave Maddy 5k` → you gave Maddy (you → them)
- `Maddy gave 5k` → Maddy gave you (them → you)
- `got from Mani` / `received from Mani` → they gave you

### Rule 2 — Weight Detection
Name (known or new) + number where number < 150 and no ledger keyword → weight entry

Known names currently: jeevi, prani, murugan (but new names can appear)
- If new name detected → show confirmation: "New person '[Name]' — log as weight entry? Yes / No"
- Number with decimal strongly suggests weight
- Number < 150 with no description suggests weight

### Rule 3 — Expense Detection
Number (whole or decimal) + description text, no person-money keyword, no known weight name → expense
- Category auto-tagged:
  - petrol, fastag → transport
  - medicine, medplus, hospital, pharmacy → medical
  - electricity, broadband, bsnl → utility
  - food items (rice, biryani, mutton, chicken, etc.) → food
  - everything else → misc

### Rule 4 — Todo Detection
No amount present, free text → todo
- Parse comma-separated as multiple todos

### Rule 5 — Unknown
Cannot classify → store with type `unknown`, surface in dashboard for manual review

### Ambiguous Zone
Amount between 150–999 with a person name and no action keyword → show confirmation toast before storing

---

## Confirmation Toast Behavior

After every entry, show a one-line confirmation. User glances — if wrong, tap undo. This is not double-checking, it's a 2-second safety net.

Examples:
- `petrol 500` → "₹500 petrol logged under transport"
- `gave Maddy 5k` → "Gave Maddy ₹5,000 logged"
- `jeevi 62` → "Jeevi weight: 62kg logged"
- `update Amit about MCP` → "Todo added: update Amit about MCP"

---

## MCP Tools (6 Total)

MCP provides the LLM with callable tools. Qwen reads the query, picks the right tool, tool hits SQL or vector store.

### Tool 1: `add_entry`
**Triggered by:** Any new note input
**Flow:** Rule-based parser first → if classified, call tool directly. If unknown → Qwen parses → then call tool.
**Backend:** INSERT into appropriate SQLite table
**Must be fast** — rule-based parser handles 80-90% without Qwen

### Tool 2: `query_ledger`
**Triggered by:** "Maddy balance", "who owes me", "Feb spending", "how much on food this month"
**Backend:** SQL SELECT/SUM/aggregation queries
**Examples:**
- "Maddy balance" → `SELECT balance FROM ledger_balance WHERE person = 'maddy'`
- "Feb spending" → `SELECT SUM(amount) FROM expenses WHERE month = '2026-02'`
- "food this month" → `SELECT SUM(amount) FROM expenses WHERE category='food' AND month='2026-05'`

### Tool 3: `update_ledger`
**Triggered by:** "reduce 6k from Maddy", "Maddy returned 3k"
**Backend:** INSERT new row (append-only, never UPDATE). Balance view auto-recomputes.
**Example:** "reduce 6k from Maddy" → INSERT {maddy, 6000, received, today} → balance: 7000-6000=1000

### Tool 4: `get_todos`
**Triggered by:** "pending tasks", "what did I plan", "mark X as done"
**Backend:** SQL filter on todos table

### Tool 5: `search_notes`
**Triggered by:** "What did Anand say about Cipla", "can I eat tomato", "what mistakes in investments"
**Backend:** MiniLM embed query → cosine search over vector store → top 2-3 chunks → Qwen summarizes
**Only slow tool** — acceptable up to 5 seconds

### Tool 6: `list_summary`
**Triggered by:** "show summary", dashboard open
**Backend:** Parallel SQL queries across all tables — pending todos count, ledger balances, latest weights, this month spend

---

## SQLite Schema (All 5 Domains)

### Expenses
```sql
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    description TEXT NOT NULL,
    category TEXT,  -- food | transport | medical | utility | misc
    date TEXT,      -- ISO 8601 full timestamp
    month TEXT,     -- '2026-02' for fast month queries
    raw_note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### Ledger
```sql
CREATE TABLE ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,       -- lowercase, trimmed
    amount REAL NOT NULL,       -- always positive
    direction TEXT NOT NULL,    -- 'gave' | 'received'
    note TEXT,
    date TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE VIEW ledger_balance AS
SELECT
    person,
    SUM(CASE WHEN direction = 'gave' THEN amount ELSE -amount END) AS balance
    -- positive = they owe you, negative = you owe them
FROM ledger
GROUP BY person;
```

### Weights
```sql
CREATE TABLE weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,   -- lowercase, trimmed
    weight REAL NOT NULL,   -- in kg
    date TEXT NOT NULL,     -- ISO 8601
    note TEXT,              -- 'empty stomach', 'after lunch', 'night', etc.
    created_at TEXT DEFAULT (datetime('now'))
);
```

### Todos
```sql
CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    date TEXT,
    status TEXT DEFAULT 'pending',  -- pending | done
    created_at TEXT DEFAULT (datetime('now'))
);
```

### Investments + Vector Store
```sql
CREATE TABLE investment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    event_type TEXT,    -- 'buy' | 'sell' | 'note' | 'advice'
    content TEXT,
    amount REAL,
    date TEXT,
    source TEXT,        -- 'self' | 'anand' | 'pr sundar' | 'other'
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,       -- 'investment' | 'health' | 'general'
    content TEXT NOT NULL,      -- original text chunk
    embedding BLOB NOT NULL,    -- Float32Array serialized
    source TEXT,
    date TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## Seed Data (From User's Actual Notes)

### Ledger Seed
```sql
INSERT INTO ledger (person, amount, direction, note) VALUES
('thenna', 20000, 'gave', 'initial balance'),
('maddy', 7000, 'gave', 'initial balance');
```

### Weight Seed — Jeevi
```sql
INSERT INTO weights (person, weight, date, note) VALUES
('jeevi', 60.1, '2026-04-24', NULL),
('jeevi', 59.1, '2026-02-27', NULL),
('jeevi', 58.7, '2026-02-18', NULL),
('jeevi', 57.2, '2026-01-26', NULL),
('jeevi', 57.8, '2026-01-20', NULL),
('jeevi', 57.9, '2025-12-30', NULL),
('jeevi', 58.7, '2025-12-21', NULL),
('jeevi', 58.1, '2025-12-08', 'night'),
('jeevi', 57.4, '2025-11-27', 'empty stomach');
```

### Weight Seed — Prani
```sql
INSERT INTO weights (person, weight, date, note) VALUES
('prani', 11.3, '2026-04-24', NULL),
('prani', 11.5, '2026-04-09', NULL),
('prani', 11.2, '2026-02-27', NULL),
('prani', 10.9, '2026-02-18', NULL),
('prani', 10.9, '2026-01-26', NULL),
('prani', 10.7, '2026-01-20', NULL),
('prani', 10.4, '2025-12-30', NULL),
('prani', 10.3, '2025-12-21', NULL),
('prani', 10.1, '2025-12-08', 'night');
```

### Weight Seed — Murugan
```sql
INSERT INTO weights (person, weight, date, note) VALUES
('murugan', 65.0, '2026-04-24', NULL),
('murugan', 64.7, '2026-04-09', NULL),
('murugan', 65.7, '2026-02-27', NULL),
('murugan', 65.4, '2026-02-19', NULL),
('murugan', 65.6, '2026-01-26', NULL),
('murugan', 66.1, '2026-01-20', NULL),
('murugan', 65.5, '2025-12-30', NULL),
('murugan', 66.2, '2025-12-21', NULL),
('murugan', 65.8, '2025-12-08', 'night'),
('murugan', 65.5, '2025-11-27', 'empty stomach'),
('murugan', 64.6, '2025-11-22', NULL);
```

### Sample Expenses (From User's Notes)
```sql
-- Feb 2026
INSERT INTO expenses (amount, description, category, date, month) VALUES
(30, 'tea + bonda', 'food', '2026-02-01', '2026-02'),
(184, 'mushroom fried rice', 'food', '2026-02-01', '2026-02'),
(650, 'Tirupathi undiyal', 'misc', '2026-02-01', '2026-02'),
(500, 'Tirupathi zoo ebike', 'misc', '2026-02-01', '2026-02'),
(143, 'Medplus Pampers', 'medical', '2026-02-01', '2026-02'),
(999, 'jeevi dress', 'misc', '2026-02-01', '2026-02'),
(1000, 'petrol', 'transport', '2026-02-01', '2026-02'),
-- Mar 2026
(2000, 'petrol', 'transport', '2026-03-01', '2026-03'),
(839, 'Bombay Ananda bhavan sweet', 'food', '2026-03-01', '2026-03');
```

---

## Investment Notes Content (For Vector Store)

Chunk and embed the following content into the `embeddings` table with domain='investment':

**Anand Srinivasan Advice (source='anand'):**
- Cipla is highly ethical company, worth investing below PE 23-24
- South Indian Bank new head has track record to turn around, strongly suggests buying
- IndusInd Bank maybe a multi-bagger
- Dr Reddy below 20 PE can consider, strongly suggests buying
- IDFC First bank CEO accepted micro finance as mistake showing integrity, strongly suggests buying
- Hold ITC, buy at dips
- Gold price will increase till 5k dollars
- Buy export-based companies like bajaj auto, pharma
- IT, pharma and auto doing very good business

**PR Sundar Advice (source='pr sundar'):**
- Nifty 50 will not improve for at least 3-4 years
- FD at 7% vs Nifty 50 at loss — to recover need 16-17% next year

**User's Own Analysis (source='self'):**
- Mistakes: Bought Chinese ETF at high, everyone read same news over weekend and jumped in
- Bought ICICI AMC after seeing 87% in one quarter — same mistake, everyone made same call
- Strategy that worked: Split desired amount into 3 parts, invest 1/3 initially
- Lost conviction on AMD, Inoq, Chinese ETF — paid the price
- 48-hour rule for decisions involving more than 50k
- Peter Lynch: PE between 3-6 can hardly fail. Focus on company not stock. Write reasons for buying.
- Peter Lynch: Rule of 72 — divide annual return % by 72 = years to double
- When coming out of recession, sell bank/insurance, invest in retailers and auto

**Current Holdings as of Feb 2026 (source='self'):**
- Gold (hedging), Chinese Tech ETF, South Indian Bank (below book value), Tamilnad Mercantile (below book value)
- IndusInd Bank (distress, turnaround possibility), IDFC First Bank, ICICI AMC, Bajaj Finance (major NBFC)
- Hero Moto Corp (40% stake in Ather), Waaree Energies, Suzlon, Bharti Airtel, ITC, Natco (undervalued pharma)
- Dr Reddy, Sun Pharma, Cipla

**Pharma Allocation Plan (source='self'):**
- 40% Natco (PE 8-9x + GLP-1 exclusivity)
- 25% Dr Reddy (PE 15x + diversification)
- 20% Divi's Labs (CDMO)
- 15% Sun Pharma

---

## Health Reference Content (For Vector Store)

Chunk and embed into `embeddings` table with domain='health':

**Root cause:** Damaged gut lining → leaky gut → immune overreaction + excess histamine → psoriasis

**Foods to AVOID strictly:**
- Nightshades (alkaloids → leaky gut): tomato, brinjal, capsicum, potato
- Dairy (casein → immune trigger): milk, paneer, cheese, ice cream, butter (reduce). Ghee is EXCEPTION — allowed
- Gluten: wheat roti, chapati, maida, puri, parota, bread, rava/sooji
- High histamine: dry fish (karuvaadu), shellfish (prawns, crab), pineapple, grapes, strawberry, spinach, pickles, aged cheese
- Other: refined sugar, refined oils (sunflower, soybean), packaged food, cold water, alcohol, peanuts

**Foods SAFE to eat:**
- Grains: rice, idli, dosa, jowar, bajra, ragi roti
- Dal: moong dal (best), toor dal
- Vegetables: drumstick, cucumber, bitter gourd, south Indian greens except spinach
- Fruits: banana, papaya, mango, watermelon (moderate), amla (daily — best)
- Fats: ghee, coconut oil
- Nuts: almonds (soaked, skin peeled), walnuts, cashews
- Protein: fresh fish, eggs
- Drinks: warm water, warm lemon water (morning), black tea (weak, after breakfast)

**Natural antihistamines:** Amla, turmeric + black pepper, ginger, lemon, onion

---

## Notebook 1 — SQLite Schema + Seed Data

**Goal:** Verify all SQL queries return correct results. No AI involved.

**What to build:**
1. Create SQLite database in memory or file
2. Create all 5 tables + ledger_balance view
3. Insert all seed data from above
4. Run and verify each test query below

**Test queries to verify:**

```python
# 1. Maddy balance — should return 7000 (they owe you)
SELECT balance FROM ledger_balance WHERE person = 'maddy'

# 2. Thenna balance — should return 20000
SELECT balance FROM ledger_balance WHERE person = 'thenna'

# 3. Who owes me money — both Maddy and Thenna
SELECT * FROM ledger_balance WHERE balance > 0

# 4. Jeevi latest weight — should return 60.1, 2026-04-24
SELECT weight, date, note FROM weights WHERE person = 'jeevi' ORDER BY date DESC LIMIT 1

# 5. Prani last 5 weights — in descending order
SELECT weight, date FROM weights WHERE person = 'prani' ORDER BY date DESC LIMIT 5

# 6. Murugan weight trend — all entries
SELECT weight, date FROM weights WHERE person = 'murugan' ORDER BY date ASC

# 7. Feb 2026 total spend
SELECT SUM(amount) FROM expenses WHERE month = '2026-02'

# 8. Transport expenses Feb 2026
SELECT SUM(amount) FROM expenses WHERE category = 'transport' AND month = '2026-02'

# 9. Pending todos
SELECT * FROM todos WHERE status = 'pending'

# 10. Simulate: reduce 6k from Maddy, then check balance
INSERT INTO ledger (person, amount, direction, note) VALUES ('maddy', 6000, 'received', 'test reduction')
SELECT balance FROM ledger_balance WHERE person = 'maddy'  -- should return 1000
```

**Exit criteria:** All 10 queries return correct expected results.

---

## Notebook 2 — Rule-Based Pre-Parser

**Goal:** Classify 80-90% of real user notes without touching any LLM.

**What to build:**
Pure Python regex + keyword logic. No ML, no models.

**Parser function signature:**
```python
def parse_note(text: str, today: str) -> list[dict]:
    """
    Input: raw note text, today's date string
    Output: list of parsed entries (one note can have multiple entries)
    
    Each entry dict:
    {
        'type': 'expense' | 'ledger' | 'weight' | 'todo' | 'unknown',
        'raw': original text,
        # type-specific fields below
    }
    """
```

**Ledger entry format:**
```python
{
    'type': 'ledger',
    'person': 'maddy',          # lowercase, stripped
    'amount': 5000,
    'direction': 'gave',        # 'gave' | 'received'
    'note': None,
    'date': today,
    'raw': 'gave Maddy 5k'
}
```

**Expense entry format:**
```python
{
    'type': 'expense',
    'amount': 500,
    'description': 'petrol',
    'category': 'transport',    # auto-tagged
    'date': today,
    'month': '2026-05',         # derived from today
    'raw': 'petrol 500'
}
```

**Weight entry format:**
```python
{
    'type': 'weight',
    'person': 'jeevi',
    'weight': 62.0,
    'note': 'empty stomach',    # optional context
    'date': today,
    'raw': 'jeevi 62 empty stomach'
}
```

**Todo entry format:**
```python
{
    'type': 'todo',
    'content': 'update Amit about MCP',
    'date': None,
    'raw': 'update Amit about MCP'
}
```

**Amount parsing — handle these formats:**
- `5k` / `5K` → 5000
- `1.5L` / `1.5l` → 150000
- `500` → 500
- `5,000` → 5000

**Category auto-tagging keywords:**
```python
CATEGORY_RULES = {
    'transport': ['petrol', 'fastag', 'diesel', 'auto', 'cab', 'uber', 'ola', 'bus', 'train'],
    'medical': ['medicine', 'medplus', 'hospital', 'pharmacy', 'doctor', 'clinic', 'pampers', 'nasoclear'],
    'utility': ['electricity', 'broadband', 'bsnl', 'airtel', 'water', 'gas', 'bill'],
    'food': ['biryani', 'rice', 'mutton', 'chicken', 'fish', 'hotel', 'cafe', 'restaurant',
             'tea', 'coffee', 'bonda', 'idly', 'dosa', 'sweet', 'cake', 'milk', 'vegetable',
             'tomato', 'groceries', 'mushroom', 'egg', 'fruit', 'juice'],
}
# Default: misc
```

**Test cases to run (from real notes):**
```python
test_cases = [
    # Clear expense cases
    ("petrol 500", [{'type': 'expense', 'amount': 500, 'category': 'transport'}]),
    ("500 petrol", [{'type': 'expense', 'amount': 500, 'category': 'transport'}]),
    ("tomato 50, groceries 200, petrol 500", 3 expense entries),
    ("bore motor repair 7500", [{'type': 'expense', 'amount': 7500, 'category': 'misc'}]),
    ("780 mutton biryani + lollipop", [{'type': 'expense', 'amount': 780, 'category': 'food'}]),
    
    # Clear ledger cases
    ("gave Maddy 5k", [{'type': 'ledger', 'person': 'maddy', 'amount': 5000, 'direction': 'gave'}]),
    ("give Maddy 10k", [{'type': 'ledger', 'person': 'maddy', 'amount': 10000, 'direction': 'gave'}]),
    ("Maddy gave 5k", [{'type': 'ledger', 'person': 'maddy', 'amount': 5000, 'direction': 'received'}]),
    ("got 5k from Mani", [{'type': 'ledger', 'person': 'mani', 'amount': 5000, 'direction': 'received'}]),
    ("Maddy returned 6k", [{'type': 'ledger', 'person': 'maddy', 'amount': 6000, 'direction': 'received'}]),
    
    # Clear weight cases
    ("jeevi 62", [{'type': 'weight', 'person': 'jeevi', 'weight': 62.0}]),
    ("jeevi 65.1 empty stomach", [{'type': 'weight', 'person': 'jeevi', 'weight': 65.1, 'note': 'empty stomach'}]),
    ("52 jeevi, 12 prani", 2 weight entries),
    ("murugan 65", [{'type': 'weight', 'person': 'murugan', 'weight': 65.0}]),
    
    # Clear todo cases
    ("update Amit about MCP, complete app phase 1", 2 todo entries),
    ("order mushroom fried rice", [{'type': 'todo'}]),
    
    # Edge cases — should go to unknown or show confirmation
    ("Mani 500", ambiguous — person + amount in 150-999 range, no keyword),
    ("gift Maddy 1000", expense not ledger),
    ("Moni sent 10k for groceries", ambiguous — classify and test Qwen in notebook 3),
]
```

**Exit criteria:** At least 85% of clear cases classified correctly. All ambiguous cases correctly flagged as unknown or sent to confirmation flow.

---

## Notebook 3 — Qwen Parser (LLM Fallback)

**Goal:** Handle the 10-15% ambiguous cases the rule-based parser couldn't classify.

**Setup:**
Use `llama-cpp-python` or `transformers` + `ctransformers` to load Qwen locally.
Model: Qwen2.5-4B or Qwen3-4B (4-bit quantized GGUF). Use whichever is available.

```bash
pip install llama-cpp-python
# or
pip install transformers accelerate
```

**Parser prompt template:**
```
You are a note parser. Extract structured data from the following note.

Note: "{raw_note}"
Today's date: "{today}"

Extract and return JSON only. No explanation. No markdown.

For money/ledger: {"type": "ledger", "person": "", "amount": 0, "direction": "gave|received", "note": ""}
For weight: {"type": "weight", "person": "", "weight": 0.0, "note": ""}
For expense: {"type": "expense", "amount": 0, "description": "", "category": "food|transport|medical|utility|misc"}
For todo: {"type": "todo", "content": ""}
If unclear: {"type": "unknown", "content": ""}

Rules:
- gave/give/given/lent/sent + person = ledger, direction: gave
- got/received/returned/paid back + person = ledger, direction: received  
- gift keyword = expense, not ledger
- weight is a number associated with a person's name, usually below 150
- ledger amounts are usually 100 or more
- direction 'gave' means user gave money to person
- direction 'received' means person gave money to user
```

**Validation after Qwen response:**
```python
def validate_parsed(result: dict) -> bool:
    if result['type'] == 'ledger':
        return (result.get('amount', 0) > 0 and 
                result.get('direction') in ['gave', 'received'] and
                result.get('person', '').strip() != '')
    if result['type'] == 'expense':
        return result.get('amount', 0) > 0
    if result['type'] == 'weight':
        return result.get('weight', 0) > 0 and result.get('person', '').strip() != ''
    return True

# If validation fails → store as unknown, surface in dashboard
```

**Test cases for Qwen (ambiguous ones rule-based failed on):**
```python
ambiguous_cases = [
    "Moni sent 10k for groceries",          # ledger (received) or expense context?
    "Mani 500",                             # person + amount, no keyword
    "iniyan iyar ku money 500",             # gave 500 to iniyan iyar
    "got seetu money 23000",               # received, chit fund
    "paid electricity 3560",               # expense, utility
    "advanced 1000 for mutton biryani",    # expense, food
]
```

**Exit criteria:** Qwen correctly classifies 80%+ of ambiguous cases with valid JSON output.

---

## Notebook 4 — Vector Store + RAG

**Goal:** Semantic search over investment notes and health reference returns relevant results.

**Setup:**
```bash
pip install sentence-transformers
pip install numpy
```

**Model:** `paraphrase-multilingual-MiniLM-L12-v2`
This is the same model planned for Android (ONNX). Use sentence-transformers in Jupyter for validation.

**Chunking strategy:**
- Investment notes: chunk by topic/paragraph, ~200-300 words per chunk
- Health reference: chunk by section (foods to avoid, foods to eat, etc.)
- Each chunk stored as one row in embeddings table with domain tag

**Key chunks to create from investment notes:**
1. Anand advice on Cipla, Dr Reddy, South Indian Bank, IndusInd
2. User's mistakes — Chinese ETF, ICICI AMC timing errors
3. User's strategy — 3-part investment, 48-hour rule, Peter Lynch principles
4. Current holdings list with reasons
5. Pharma allocation plan
6. PE/NIM/CAR/NPA reference numbers

**Key chunks from health reference:**
1. Root cause explanation
2. Foods to avoid — nightshades
3. Foods to avoid — dairy, gluten, histamine
4. Foods safe to eat
5. Natural antihistamines

**Cosine similarity function:**
```python
import numpy as np

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def search_notes(query: str, domain: str, top_k: int = 3):
    query_embedding = model.encode(query)
    results = []
    for row in embeddings_table:
        if row['domain'] == domain:
            sim = cosine_similarity(query_embedding, row['embedding'])
            results.append((sim, row['content']))
    results.sort(reverse=True)
    return results[:top_k]
```

**Test queries:**
```python
search_tests = [
    ("What did Anand say about Cipla", "investment"),
    ("What did Anand say about South Indian Bank", "investment"),
    ("What mistakes did I make in investments", "investment"),
    ("What is my pharma allocation plan", "investment"),
    ("What is the 48 hour rule", "investment"),
    ("Can I eat tomato", "health"),
    ("Can I eat brinjal", "health"),
    ("Can I drink milk", "health"),
    ("What can I eat for snacks", "health"),
    ("What are natural antihistamines", "health"),
]
```

**Exit criteria:** Top result is clearly relevant for all 10 test queries. No hallucination — answers come from stored chunks only.

---

## Notebook 5 — Full End-to-End Flow

**Goal:** Wire everything together and test 10 real queries.

**Full flow:**
```
Raw input
    ↓
Rule-based pre-parser (Notebook 2 logic)
    ↓
Classified? 
    Yes → call appropriate SQL tool directly
    No → send to Qwen (Notebook 3 logic) → Qwen classifies → call tool
    ↓
Tool execution:
    - Ledger/expense/weight/todo → SQLite query (Notebook 1 schema)
    - search_notes → vector search (Notebook 4 logic)
    ↓
Format response → print result
```

**10 real test queries:**
```python
test_queries = [
    # Structured SQL queries
    ("Maddy balance", "query_ledger", "₹7,000 — Maddy owes you"),
    ("Who owes me money", "query_ledger", "Maddy: ₹7,000, Thenna: ₹20,000"),
    ("Jeevi latest weight", "query_ledger", "60.1 kg on Apr 24, 2026"),
    ("How much did I spend in February", "query_ledger", "sum of all Feb 2026 expenses"),
    ("How much did I spend on petrol", "query_ledger", "sum of transport category"),
    ("Pending todos", "get_todos", "list of pending items"),
    
    # Write operations
    ("gave Mani 2000", "add_entry", "Gave Mani ₹2,000 logged"),
    ("petrol 500, groceries 300", "add_entry", "2 expenses logged"),
    
    # RAG queries
    ("What did Anand say about Cipla", "search_notes", "relevant Anand advice chunk"),
    ("Can I eat tomato", "search_notes", "No — nightshade, damages gut lining"),
]
```

**Measure for each query:**
- Correct tool selected? (yes/no)
- Correct result returned? (yes/no)
- Latency in ms

**Exit criteria:** 9/10 queries correct. Latency for SQL queries < 500ms. RAG query < 5 seconds.

---

## Important Design Decisions

1. **Append-only ledger** — never UPDATE, always INSERT. Balance derived from view.
2. **Structured queries never go through RAG** — Maddy balance is SQL, not vector search.
3. **LLM is formatter, not source of truth** — SQL and vector store are authoritative.
4. **Rule-based parser first** — Qwen only sees ambiguous inputs.
5. **Date always = now** — never ask user for date, auto-capture timestamp.
6. **Month column precomputed** — stored as '2026-02' for fast month-based queries.
7. **Unknown entries stored, not dropped** — surfaced in dashboard for manual review.
8. **New person in weight** — show confirmation before storing.
9. **Confirmation toast on every entry** — 2-second safety net, not double-checking.
10. **Embedding and LLM never run simultaneously** — queue to avoid RAM pressure on Android.

---

## Python Dependencies

```bash
pip install sqlite3          # built-in
pip install sentence-transformers
pip install numpy
pip install llama-cpp-python  # for Qwen
# or
pip install transformers accelerate torch
```

---

## File Structure for Notebooks

```
second-brain-notebooks/
├── notebook_1_sqlite.ipynb
├── notebook_2_preparser.ipynb
├── notebook_3_qwen_parser.ipynb
├── notebook_4_vector_store.ipynb
├── notebook_5_end_to_end.ipynb
└── data/
    └── seed.sql
```

---

## What Success Looks Like

After all 5 notebooks pass exit criteria:
- SQL schema is proven correct with real data
- Rule-based parser handles 85%+ of real note patterns
- Qwen handles remaining ambiguous cases reliably
- Vector search returns relevant results for investment and health queries
- Full end-to-end flow works for all 10 real test queries

At this point, porting to Android is mechanical — same logic, different runtime (Java/Kotlin + llama.cpp JNI + ONNX Runtime + NanoHTTPD).
