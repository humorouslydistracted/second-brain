# Fine-Tuning a Local LLM for a Private AI Notes App

A beginner-friendly but serious guide for your exact use case: a note-taking app where the user writes entries like `expense:`, `weight:`, `todo:`, `note:`, and `ledger:`, and a local AI helps convert those notes into structured data and retrieve them later.

---

## 0. The brutally clear version

You are not building a chatbot.

You are building a **personal data engine hidden inside a notes app**.

The LLM should not be the database.  
The LLM should not be the calculator.  
The LLM should not be trusted to remember all notes.  
The LLM should not be trusted to calculate totals, balances, averages, or trends.

The LLM should do this:

```text
messy human note → clean JSON
messy human question → clean query intent JSON
retrieved notes/todos → short natural-language summary
```

Your app code and SQLite should do this:

```text
store data
filter by date
sum expenses
compare months
calculate weight change
calculate ledger balance
retrieve todos/notes
```

If you keep this split clean, your app can become useful. If you expect a tiny mobile LLM to be the full brain, the app will become unreliable.

---

## 1. Your app idea in plain English

You want a normal notes app, but with simple prefixes:

```text
expense: sugar 50, maggi 100, petrol 2000
weight: magesh 62.5, wife 58.4, daughter 12.2
ledger: I owe maddy 5k. maddy owes me 10k
todo: call plumber tomorrow, buy milk, pay EB bill Friday
note: I think local AI notes can work well if it stays private and offline.
```

The app should quietly understand these notes and store useful structured records behind the scenes.

Later, the user can ask:

```text
What is my total expense this month?
Compare this month and last month expense.
How much weight did Magesh lose in the last 6 months?
What pending todo do I have about bike insurance?
Show my notes about privacy-focused apps.
How much does Maddy owe me?
```

The app should answer using exact local data.

---

## 2. The correct architecture

Think of the app as having four parts.

```text
1. User writes note
       ↓
2. LLM/rule parser converts note into structured JSON
       ↓
3. SQLite stores structured data and raw note
       ↓
4. Retrieval/query engine answers later questions
```

More detailed:

```text
Raw note
   ↓
Detect prefix: expense / weight / ledger / todo / note
   ↓
Try simple rule parser first
   ↓
If rule parser is not enough, use fine-tuned local LLM
   ↓
Validate JSON schema
   ↓
Store raw note + structured records in SQLite
   ↓
Update FTS / embedding indexes
   ↓
User asks a question
   ↓
LLM parses question into intent JSON
   ↓
Your app routes intent to SQLite/search/calculation functions
   ↓
App produces exact result
   ↓
Template or LLM writes final natural-language answer
```

Important:

```text
LLM = language interpreter
SQLite = truth
Kotlin/app code = decision-maker
FTS/embeddings = memory/search
```

---

## 3. What fine-tuning can and cannot solve

### Fine-tuning can help with:

```text
expense extraction
weight extraction
ledger direction extraction
todo extraction
note title/summary/topic generation
query-intent parsing
consistent JSON formatting
handling your writing style and typos
```

Examples:

```text
expense: sugar 50
expense: 50 sugar
expense: sugar-50
expense: sugar:50
expense: sugar 50, petrol 2000, gold 300000
```

A fine-tuned model can learn to output:

```json
{
  "section": "expense",
  "records": [
    {"type": "expense", "item": "sugar", "amount": 50, "currency": "INR"},
    {"type": "expense", "item": "petrol", "amount": 2000, "currency": "INR"},
    {"type": "expense", "item": "gold", "amount": 300000, "currency": "INR"}
  ]
}
```

### Fine-tuning alone will not solve:

```text
reliable retrieval of old notes
semantic todo search
exact expense totals
month filtering
weight trends
ledger balances
date calculations
large personal memory
```

Those need SQLite, FTS, embeddings, and app logic.

---

## 4. Why not train the model to calculate totals?

Bad training target:

```json
{
  "input": "expense: sugar 50, petrol 2000. What is total?",
  "output": "The total is ₹2050."
}
```

This teaches the model to imitate calculation. It may work in demos and fail in real life.

Good training target:

```json
{
  "input": "expense: sugar 50, petrol 2000",
  "output": {
    "section": "expense",
    "records": [
      {"type": "expense", "item": "sugar", "amount": 50, "currency": "INR"},
      {"type": "expense", "item": "petrol", "amount": 2000, "currency": "INR"}
    ]
  }
}
```

Then code does:

```text
50 + 2000 = 2050
```

The app should calculate totals with SQLite/Kotlin, not with the LLM.

---

## 5. What exactly should the model learn?

You need two fine-tuned behaviours.

### Behaviour A: note parsing

Input:

```text
expense: sugar 50, maggi 100, petrol 2000
```

Output:

```json
{
  "task": "parse_note",
  "section": "expense",
  "records": [
    {"type": "expense", "item": "sugar", "amount": 50, "currency": "INR"},
    {"type": "expense", "item": "maggi", "amount": 100, "currency": "INR"},
    {"type": "expense", "item": "petrol", "amount": 2000, "currency": "INR"}
  ]
}
```

### Behaviour B: question/query parsing

Input:

```text
compare this month and last month expense
```

Output:

```json
{
  "task": "parse_query",
  "domain": "expense",
  "intent": "compare",
  "metric": "sum",
  "date_expressions": ["this_month", "last_month"],
  "filters": {}
}
```

The model should output an intent, not the final answer.

---

## 6. Prefixes and expected JSON outputs

Your prefixes are:

```text
expense:
weight:
ledger:
todo:
note:
```

Use these prefixes to reduce ambiguity. The prefix is a gift. It means the model does not need to guess the broad category.

---

# Part A — Note Parsing

---

## 7. Expense parsing

### Supported input styles

You want to support:

```text
expense: sugar 50
expense: 50 sugar
expense: sugar-50
expense: sugar:50
expense: sugar ₹50
expense: sugar rs 50
expense: sugar 50, maggi 100, petrol 2000
expense: gold 300000
expense: petrol 2k
expense: fridge 25k
expense: jewellery 3 lakh
expense: bike repair 1.5k
```

### Important number formats

Support amounts like:

```text
5
50
500
5000
50000
300000
3k
5K
1.5k
2 lakh
2 lakhs
3L
3 lacs
₹500
rs 500
500 rupees
```

Normalize them:

```text
5       → 5
50      → 50
500     → 500
5000    → 5000
300000  → 300000
5k      → 5000
1.5k    → 1500
2 lakh  → 200000
3L      → 300000
```

### Expense output schema

Use this JSON shape:

```json
{
  "task": "parse_note",
  "section": "expense",
  "records": [
    {
      "type": "expense",
      "item": "sugar",
      "amount": 50,
      "currency": "INR",
      "date_text": null,
      "confidence": 0.95
    }
  ]
}
```

Fields:

| Field | Meaning |
|---|---|
| `type` | Always `expense` for expense records |
| `item` | What money was spent on |
| `amount` | Normalized numeric amount in rupees |
| `currency` | Usually `INR` |
| `date_text` | `today`, `yesterday`, `last Friday`, etc., if mentioned |
| `confidence` | Model confidence from 0 to 1 |

### Expense examples for training

```json
{
  "input": "expense: sugar 50",
  "output": {
    "task": "parse_note",
    "section": "expense",
    "records": [
      {"type": "expense", "item": "sugar", "amount": 50, "currency": "INR", "date_text": null, "confidence": 0.98}
    ]
  }
}
```

```json
{
  "input": "expense: 50 sugar",
  "output": {
    "task": "parse_note",
    "section": "expense",
    "records": [
      {"type": "expense", "item": "sugar", "amount": 50, "currency": "INR", "date_text": null, "confidence": 0.95}
    ]
  }
}
```

```json
{
  "input": "expense: sugar-50, maggi 100, petrol 2000, gold 300000",
  "output": {
    "task": "parse_note",
    "section": "expense",
    "records": [
      {"type": "expense", "item": "sugar", "amount": 50, "currency": "INR", "date_text": null, "confidence": 0.96},
      {"type": "expense", "item": "maggi", "amount": 100, "currency": "INR", "date_text": null, "confidence": 0.96},
      {"type": "expense", "item": "petrol", "amount": 2000, "currency": "INR", "date_text": null, "confidence": 0.96},
      {"type": "expense", "item": "gold", "amount": 300000, "currency": "INR", "date_text": null, "confidence": 0.96}
    ]
  }
}
```

```json
{
  "input": "expense: spent 2k for petrol and 150 for tea yesterday",
  "output": {
    "task": "parse_note",
    "section": "expense",
    "records": [
      {"type": "expense", "item": "petrol", "amount": 2000, "currency": "INR", "date_text": "yesterday", "confidence": 0.90},
      {"type": "expense", "item": "tea", "amount": 150, "currency": "INR", "date_text": "yesterday", "confidence": 0.90}
    ]
  }
}
```

### What should be done by code, not model

Code should validate:

```text
amount is numeric
amount is positive
amount is within allowed range
currency defaults to INR
k/lakh values are normalized correctly
```

The model can extract `5k`, but your code should be able to normalize it too. Do not make normalization model-only.

---

## 8. Weight parsing

You want to track multiple people:

```text
me
wife
daughter
other named family members
```

Example inputs:

```text
weight: magesh weight 62.5
weight: jagan weight 12.2
weight: magesh 62.5, wife 58.4, daughter 12.2
weight: me 63 today
weight: wife 58kg, child 12.5kg
```

### Weight output schema

```json
{
  "task": "parse_note",
  "section": "weight",
  "records": [
    {
      "type": "weight_log",
      "person_text": "magesh",
      "value": 62.5,
      "unit": "kg",
      "date_text": null,
      "confidence": 0.95
    }
  ]
}
```

Important: output `person_text`, not final `person_id`. Your app should map `person_text` to a canonical person using a people/aliases table.

### Why aliases matter

The same person may appear as:

```text
me
magesh
appa
myself
```

Another person may appear as:

```text
wife
actual name
amma
```

Child may appear as:

```text
daughter
jagan
kid
child
```

Your app needs:

```sql
people(id, canonical_name)
person_aliases(id, person_id, alias)
```

The model should not be responsible for remembering aliases forever. Store aliases in SQLite.

### Weight training example

```json
{
  "input": "weight: magesh weight 62.5, jagan weight 12.2, wife 58.4",
  "output": {
    "task": "parse_note",
    "section": "weight",
    "records": [
      {"type": "weight_log", "person_text": "magesh", "value": 62.5, "unit": "kg", "date_text": null, "confidence": 0.96},
      {"type": "weight_log", "person_text": "jagan", "value": 12.2, "unit": "kg", "date_text": null, "confidence": 0.96},
      {"type": "weight_log", "person_text": "wife", "value": 58.4, "unit": "kg", "date_text": null, "confidence": 0.94}
    ]
  }
}
```

---

## 9. Ledger parsing

Ledger is the most dangerous section because direction matters.

These two are opposite:

```text
I owe maddy 5k
maddy owes me 5k
```

If your model reverses direction, your app becomes financially misleading.

### Ledger direction names

Use only these directions:

```text
i_owe_them
they_owe_me
```

Do not store vague directions like `borrowed`, `lent`, `credit`, `debit` unless you also convert them to the two clear directions.

### Ledger examples

Input:

```text
ledger: I owe maddy 5k
```

Output:

```json
{
  "task": "parse_note",
  "section": "ledger",
  "records": [
    {
      "type": "ledger_entry",
      "person_text": "maddy",
      "direction": "i_owe_them",
      "amount": 5000,
      "currency": "INR",
      "date_text": null,
      "confidence": 0.92
    }
  ]
}
```

Input:

```text
ledger: maddy owes me 10k
```

Output:

```json
{
  "task": "parse_note",
  "section": "ledger",
  "records": [
    {
      "type": "ledger_entry",
      "person_text": "maddy",
      "direction": "they_owe_me",
      "amount": 10000,
      "currency": "INR",
      "date_text": null,
      "confidence": 0.94
    }
  ]
}
```

Input:

```text
ledger: borrowed 2k from arun, lent 1500 to kumar
```

Output:

```json
{
  "task": "parse_note",
  "section": "ledger",
  "records": [
    {
      "type": "ledger_entry",
      "person_text": "arun",
      "direction": "i_owe_them",
      "amount": 2000,
      "currency": "INR",
      "date_text": null,
      "confidence": 0.90
    },
    {
      "type": "ledger_entry",
      "person_text": "kumar",
      "direction": "they_owe_me",
      "amount": 1500,
      "currency": "INR",
      "date_text": null,
      "confidence": 0.90
    }
  ]
}
```

### Ledger phrases to include in training data

```text
I owe maddy 5k
maddy owes me 10k
maddy owe me 10k
I borrowed 5k from maddy
I took 5k from maddy
I need to return 5k to maddy
I lent maddy 10k
I gave maddy 10k
maddy has to give me 10k
kumar needs to return 1500
arun gave me 2000
I paid back 1000 to maddy
maddy returned 500
```

### Ledger confirmation rule

For ledger, add UI confirmation:

```text
Detected:
- You owe Maddy ₹5,000
- Maddy owes you ₹10,000

Save these ledger entries?
```

This is not optional if you want trust.

---

## 10. Todo parsing

Todos can be single or multiple:

```text
todo: buy milk
todo: call plumber tomorrow, pay EB bill Friday, renew bike insurance
todo: remind me to submit school form next Monday
```

### Todo output schema

```json
{
  "task": "parse_note",
  "section": "todo",
  "records": [
    {
      "type": "todo",
      "text": "call plumber",
      "due_date_text": "tomorrow",
      "priority": null,
      "confidence": 0.93
    }
  ]
}
```

### Todo training example

```json
{
  "input": "todo: call plumber tomorrow, buy milk, pay EB bill Friday",
  "output": {
    "task": "parse_note",
    "section": "todo",
    "records": [
      {"type": "todo", "text": "call plumber", "due_date_text": "tomorrow", "priority": null, "confidence": 0.93},
      {"type": "todo", "text": "buy milk", "due_date_text": null, "priority": null, "confidence": 0.95},
      {"type": "todo", "text": "pay EB bill", "due_date_text": "Friday", "priority": null, "confidence": 0.91}
    ]
  }
}
```

### Date resolution

The model should extract:

```text
tomorrow
Friday
next Monday
this weekend
```

Your app should convert that to actual dates.

Do not ask the model to decide final dates unless necessary.

---

## 11. Note parsing

For `note:`, do not force everything into structured facts. Sometimes a note is just a note.

The useful things to extract are:

```text
title
summary
topics
entities
body
```

### Note output schema

```json
{
  "task": "parse_note",
  "section": "note",
  "records": [
    {
      "type": "note",
      "title": "Offline AI notes app idea",
      "summary": "Idea about a private local AI notes app that understands personal tracking entries.",
      "topics": ["local AI", "notes app", "privacy", "personal tracking"],
      "body": "...original note body...",
      "confidence": 0.90
    }
  ]
}
```

This helps retrieval later because search can look at title, summary, topics, and body.

### Note training example

```json
{
  "input": "note: local AI notes app should work offline and understand expenses, todos, weights, and ledger entries without sending data to cloud.",
  "output": {
    "task": "parse_note",
    "section": "note",
    "records": [
      {
        "type": "note",
        "title": "Offline AI notes app idea",
        "summary": "Idea for a private local AI notes app that understands expenses, todos, weights, and ledger entries offline.",
        "topics": ["offline AI", "notes app", "privacy", "personal tracking"],
        "body": "local AI notes app should work offline and understand expenses, todos, weights, and ledger entries without sending data to cloud.",
        "confidence": 0.90
      }
    ]
  }
}
```

---

# Part B — Query Parsing

---

## 12. Why query parsing is separate

Writing a note and asking a question are different tasks.

Note input:

```text
expense: sugar 50, petrol 2000
```

Question input:

```text
What is my total expense this month?
```

The first should become records.  
The second should become an intent.

---

## 13. Query output schema

Use this:

```json
{
  "task": "parse_query",
  "domain": "expense",
  "intent": "total",
  "metric": "sum",
  "date_expressions": ["this_month"],
  "filters": {},
  "group_by": null,
  "search_query": null,
  "confidence": 0.95
}
```

Domains:

```text
expense
weight
ledger
todo
note_search
```

Intents:

```text
total
compare
breakdown
list
average
trend
change
balance
search
search_pending
```

---

## 14. Expense query examples

Input:

```text
What is my total expense this month?
```

Output:

```json
{
  "task": "parse_query",
  "domain": "expense",
  "intent": "total",
  "metric": "sum",
  "date_expressions": ["this_month"],
  "filters": {},
  "group_by": null,
  "search_query": null,
  "confidence": 0.96
}
```

Input:

```text
compare expense between this month and last month
```

Output:

```json
{
  "task": "parse_query",
  "domain": "expense",
  "intent": "compare",
  "metric": "sum",
  "date_expressions": ["this_month", "last_month"],
  "filters": {},
  "group_by": null,
  "search_query": null,
  "confidence": 0.95
}
```

Input:

```text
how much did I spend on petrol in april?
```

Output:

```json
{
  "task": "parse_query",
  "domain": "expense",
  "intent": "total",
  "metric": "sum",
  "date_expressions": ["april"],
  "filters": {"item": "petrol"},
  "group_by": null,
  "search_query": null,
  "confidence": 0.92
}
```

Input:

```text
break down my expense this month
```

Output:

```json
{
  "task": "parse_query",
  "domain": "expense",
  "intent": "breakdown",
  "metric": "sum",
  "date_expressions": ["this_month"],
  "filters": {},
  "group_by": "category",
  "search_query": null,
  "confidence": 0.90
}
```

---

## 15. Weight query examples

Input:

```text
how much weight did magesh lose in last 6 months?
```

Output:

```json
{
  "task": "parse_query",
  "domain": "weight",
  "intent": "change",
  "metric": "difference",
  "date_expressions": ["last_6_months"],
  "filters": {"person_text": "magesh"},
  "group_by": null,
  "search_query": null,
  "confidence": 0.94
}
```

Input:

```text
show jagan weight trend
```

Output:

```json
{
  "task": "parse_query",
  "domain": "weight",
  "intent": "trend",
  "metric": "weight_over_time",
  "date_expressions": [],
  "filters": {"person_text": "jagan"},
  "group_by": null,
  "search_query": null,
  "confidence": 0.91
}
```

---

## 16. Ledger query examples

Input:

```text
how much does maddy owe me?
```

Output:

```json
{
  "task": "parse_query",
  "domain": "ledger",
  "intent": "balance",
  "metric": "net_balance",
  "date_expressions": [],
  "filters": {"person_text": "maddy"},
  "group_by": null,
  "search_query": null,
  "confidence": 0.93
}
```

Input:

```text
show all open ledger with maddy
```

Output:

```json
{
  "task": "parse_query",
  "domain": "ledger",
  "intent": "list",
  "metric": null,
  "date_expressions": [],
  "filters": {"person_text": "maddy", "status": "open"},
  "group_by": null,
  "search_query": null,
  "confidence": 0.90
}
```

---

## 17. Todo retrieval query examples

Input:

```text
show my pending vehicle related tasks
```

Output:

```json
{
  "task": "parse_query",
  "domain": "todo",
  "intent": "search_pending",
  "metric": null,
  "date_expressions": [],
  "filters": {"status": "open"},
  "group_by": null,
  "search_query": "vehicle related tasks bike car scooter insurance service",
  "confidence": 0.88
}
```

Input:

```text
what do I need to do today?
```

Output:

```json
{
  "task": "parse_query",
  "domain": "todo",
  "intent": "list",
  "metric": null,
  "date_expressions": ["today"],
  "filters": {"status": "open"},
  "group_by": null,
  "search_query": null,
  "confidence": 0.93
}
```

---

## 18. Note retrieval query examples

Input:

```text
show my thoughts about privacy focused note app
```

Output:

```json
{
  "task": "parse_query",
  "domain": "note_search",
  "intent": "search",
  "metric": null,
  "date_expressions": [],
  "filters": {"section": "note"},
  "group_by": null,
  "search_query": "privacy focused note app local AI private notes",
  "confidence": 0.90
}
```

Input:

```text
find that idea about offline personal knowledge
```

Output:

```json
{
  "task": "parse_query",
  "domain": "note_search",
  "intent": "search",
  "metric": null,
  "date_expressions": [],
  "filters": {"section": "note"},
  "group_by": null,
  "search_query": "offline personal knowledge local notes memory ideas",
  "confidence": 0.86
}
```

---

# Part C — SQLite and Retrieval

---

## 19. Database tables

### Raw notes

Always store the original note.

```sql
CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    prefix TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    topics TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

Never throw away the original text.

---

### Expenses

```sql
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    item TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT DEFAULT 'INR',
    category TEXT,
    expense_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(note_id) REFERENCES notes(id)
);
```

---

### People and aliases

```sql
CREATE TABLE people (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL
);
```

```sql
CREATE TABLE person_aliases (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    FOREIGN KEY(person_id) REFERENCES people(id)
);
```

---

### Weight logs

```sql
CREATE TABLE weight_logs (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    weight REAL NOT NULL,
    unit TEXT DEFAULT 'kg',
    logged_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(note_id) REFERENCES notes(id),
    FOREIGN KEY(person_id) REFERENCES people(id)
);
```

---

### Ledger entries

```sql
CREATE TABLE ledger_entries (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    person_text TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT DEFAULT 'INR',
    status TEXT DEFAULT 'open',
    ledger_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(note_id) REFERENCES notes(id)
);
```

Use `direction` values:

```text
i_owe_them
they_owe_me
```

---

### Todos

```sql
CREATE TABLE todos (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    due_date TEXT,
    priority TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(note_id) REFERENCES notes(id)
);
```

---

## 20. FTS for retrieval

Use SQLite FTS for keyword search.

FTS means Full-Text Search. It is much better than doing `LIKE '%bike%'` on every note.

Create FTS tables:

```sql
CREATE VIRTUAL TABLE notes_fts USING fts5(
    title,
    summary,
    topics,
    raw_text,
    content='notes',
    content_rowid='id'
);
```

```sql
CREATE VIRTUAL TABLE todos_fts USING fts5(
    text,
    content='todos',
    content_rowid='id'
);
```

Use FTS for queries like:

```text
bike insurance
privacy note app
school form
vehicle service
```

---

## 21. Embeddings for semantic retrieval

FTS matches words. Embeddings match meaning.

Example:

Stored todo:

```text
renew bike insurance
```

User asks:

```text
vehicle related pending things
```

FTS may fail because `vehicle` is not the same word as `bike`.

Embeddings can help because they understand related meaning.

Recommended retrieval stack:

```text
FTS search
+ embedding search
+ merge results
+ rerank
+ LLM summary
```

For v1, you can start with FTS only. Add embeddings after basic search works.

---

## 22. RAG in your app

RAG means:

```text
retrieve relevant records first
then give only those records to the LLM
then ask the LLM to summarize or answer
```

Bad approach:

```text
Ask the LLM to remember all notes.
```

Good approach:

```text
User asks question
   ↓
App searches SQLite/FTS/embeddings
   ↓
Top 5-20 relevant notes/todos are retrieved
   ↓
LLM answers using only those retrieved items
```

Example:

User:

```text
show me my vehicle related pending tasks
```

Query parser:

```json
{
  "domain": "todo",
  "intent": "search_pending",
  "search_query": "vehicle bike car scooter insurance service",
  "filters": {"status": "open"}
}
```

Retrieval result:

```json
[
  {"text": "renew bike insurance", "status": "open"},
  {"text": "service scooter next week", "status": "open"}
]
```

Final answer:

```text
You have 2 pending vehicle-related tasks:
1. Renew bike insurance
2. Service scooter next week
```

The LLM did not remember the tasks. The app retrieved them.

---

# Part D — Query Routing and SQLite

---

## 23. SQLite does not choose queries

SQLite does not understand the user.

Your app must decide which function to call.

```text
User question
   ↓
LLM query parser
   ↓
intent JSON
   ↓
Kotlin query router
   ↓
SQLite function
   ↓
result
```

Example:

User:

```text
What is my total expense this month?
```

LLM:

```json
{
  "domain": "expense",
  "intent": "total",
  "date_expressions": ["this_month"]
}
```

Kotlin router:

```kotlin
when (query.domain) {
    "expense" -> handleExpenseQuery(query)
    "weight" -> handleWeightQuery(query)
    "todo" -> handleTodoQuery(query)
    "ledger" -> handleLedgerQuery(query)
    "note_search" -> handleNoteSearchQuery(query)
}
```

Expense router:

```kotlin
when (query.intent) {
    "total" -> expenseRepository.sumExpenses(range, filters)
    "compare" -> expenseRepository.compareExpenses(ranges, filters)
    "breakdown" -> expenseRepository.breakdownByCategory(range)
    "list" -> expenseRepository.listExpenses(range, filters)
    "average" -> expenseRepository.averageDailyExpense(range)
}
```

---

## 24. Example SQL functions

### Total expense

```sql
SELECT COALESCE(SUM(amount), 0)
FROM expenses
WHERE expense_date BETWEEN :startDate AND :endDate;
```

### Expense by item

```sql
SELECT COALESCE(SUM(amount), 0)
FROM expenses
WHERE expense_date BETWEEN :startDate AND :endDate
AND item LIKE :item;
```

### Expense breakdown by category

```sql
SELECT category, SUM(amount) AS total
FROM expenses
WHERE expense_date BETWEEN :startDate AND :endDate
GROUP BY category
ORDER BY total DESC;
```

### Weight change

```sql
SELECT logged_date, weight
FROM weight_logs
WHERE person_id = :personId
AND logged_date BETWEEN :startDate AND :endDate
ORDER BY logged_date ASC;
```

Then Kotlin calculates:

```text
latest_weight - first_weight
```

### Ledger balance

For a person:

```sql
SELECT direction, SUM(amount) AS total
FROM ledger_entries
WHERE person_text = :person
AND status = 'open'
GROUP BY direction;
```

Then Kotlin calculates:

```text
net = they_owe_me_total - i_owe_them_total
```

If net is positive:

```text
They owe me ₹X
```

If net is negative:

```text
I owe them ₹X
```

---

# Part E — Final Answers

---

## 25. Do you need to fine-tune final answers?

Not at first.

Use templates.

Example result:

```json
{
  "intent": "expense_total",
  "range_label": "May 2026 so far",
  "total": 1150,
  "currency": "INR"
}
```

Template:

```text
You have spent ₹1,150 so far in May 2026.
```

For comparison:

```json
{
  "range_1_label": "May 2026 so far",
  "range_1_total": 1150,
  "range_2_label": "April 2026",
  "range_2_total": 4200,
  "difference": -3050,
  "percentage_change": -72.6
}
```

Template:

```text
You spent ₹1,150 so far in May 2026, compared with ₹4,200 in April 2026. That is ₹3,050 less, a 72.6% decrease.
```

This is safer than asking the LLM to rewrite numbers.

Use the LLM for final answer only when:

```text
summarizing notes
explaining retrieved todos
turning a long result into a short paragraph
```

Even then, pass exact data and tell it:

```text
Do not change numbers. Do not invent facts. Use only the provided data.
```

---

# Part F — Fine-Tuning Plan

---

## 26. Which model should you fine-tune?

For mobile use, start small.

Suggested starting models:

```text
Qwen3-0.6B-Instruct
Qwen2.5-0.5B-Instruct
```

Stretch model:

```text
Qwen3-1.7B-Instruct
```

Do not start with 3B, 4B, 7B. You are new to fine-tuning. Starting too big is how you waste time.

---

## 27. LoRA and QLoRA in simple words

Full fine-tuning means changing the entire model. That needs a lot of GPU memory.

LoRA means:

```text
Keep the main model mostly frozen.
Train small extra adapter layers.
```

QLoRA means:

```text
Load the main model in 4-bit quantized form.
Train small LoRA adapters on top.
```

For your case:

```text
Use LoRA/QLoRA, not full fine-tuning.
```

---

## 28. Training hardware

Your GTX 1650 laptop may be useful for tiny tests, but it is limited.

Better path:

```text
Google Colab for training
Pixel 7 only for inference/testing
```

Start with free Colab if available. Move to paid only after your dataset and script are ready.

---

## 29. Dataset format

Use JSONL.

Each line is one training example.

Example:

```jsonl
{"messages":[{"role":"system","content":"You are a local notes app parser. Return only valid JSON."},{"role":"user","content":"expense: sugar 50"},{"role":"assistant","content":"{\"task\":\"parse_note\",\"section\":\"expense\",\"records\":[{\"type\":\"expense\",\"item\":\"sugar\",\"amount\":50,\"currency\":\"INR\",\"date_text\":null,\"confidence\":0.98}]}"}]}
{"messages":[{"role":"system","content":"You are a local notes app parser. Return only valid JSON."},{"role":"user","content":"ledger: I owe maddy 5k"},{"role":"assistant","content":"{\"task\":\"parse_note\",\"section\":\"ledger\",\"records\":[{\"type\":\"ledger_entry\",\"person_text\":\"maddy\",\"direction\":\"i_owe_them\",\"amount\":5000,\"currency\":\"INR\",\"date_text\":null,\"confidence\":0.92}]}"}]}
```

This format works well with chat/instruct fine-tuning tools.

---

## 30. Dataset size targets

For your prefix-based app:

| Capability | Minimum | Better |
|---|---:|---:|
| Expense extraction | 300-500 | 2,000+ |
| Weight extraction | 200-500 | 1,000+ |
| Ledger extraction | 500-1,000 | 3,000+ |
| Todo extraction | 300-500 | 2,000+ |
| Note title/summary/topics | 300-500 | 1,500+ |
| Query parsing | 500-1,000 | 3,000+ |

Start small:

```text
500 to 1,000 examples total
```

Then test. Then add more examples where the model fails.

Do not generate 50,000 examples first. That is fake progress.

---

## 31. Synthetic data generation strategy

Ask Codex to generate scripts that produce variations.

### Expense variation dimensions

Items:

```text
sugar
milk
rice
petrol
maggi
gold
school fee
bike service
medicine
vegetables
```

Amount formats:

```text
50
500
5000
5k
1.5k
2 lakh
300000
₹500
rs 500
```

Input patterns:

```text
{item} {amount}
{amount} {item}
{item}-{amount}
{item}:{amount}
spent {amount} for {item}
paid {amount} for {item}
```

Multiple entries:

```text
expense: sugar 50, milk 60, petrol 2000
expense: 50 sugar, 60 milk, 2000 petrol
expense: sugar-50, milk:60, petrol 2k
```

### Weight variation dimensions

People:

```text
magesh
me
wife
daughter
jagan
child
```

Patterns:

```text
{person} weight {value}
{person} {value}
{person} is {value}
{person} {value}kg
```

### Ledger variation dimensions

Direction patterns:

```text
I owe {person} {amount}
{person} owes me {amount}
I borrowed {amount} from {person}
I lent {person} {amount}
{person} has to give me {amount}
I need to return {amount} to {person}
```

### Todo variation dimensions

```text
call plumber tomorrow
buy milk
pay EB bill Friday
renew bike insurance
submit school form next Monday
```

### Note variation dimensions

Use short and long paragraphs with topics:

```text
privacy
local AI
finance
health
family
app ideas
work thoughts
```

---

## 32. Do not train only synthetic data

Synthetic data is useful but limited.

You need real examples from your typing style:

```text
totel
wieght
indiidual
entires
onth
borrow list
owe me
maddy owe me
```

Your real spelling mistakes matter. Add them.

Best training data comes from:

```text
synthetic examples
+ manually written examples
+ real app failures corrected by you
```

---

## 33. Train/test split

Do not test on examples the model has already seen.

Split data:

```text
80% train
10% validation
10% test
```

Example:

```text
1,000 examples
800 train
100 validation
100 test
```

Test set should include ugly real examples.

---

## 34. Evaluation metrics

Do not evaluate by “it looks good”.

Use strict checks.

### JSON validity

```text
Can the output be parsed as JSON?
```

Target:

```text
> 98%
```

### Schema validity

```text
Does it contain required fields?
```

### Record accuracy

For expense:

```text
correct item
correct amount
correct number of records
```

### Ledger direction accuracy

This must be very high.

```text
I owe them vs they owe me
```

Target:

```text
> 99% for common patterns
```

If ledger direction is uncertain, ask for confirmation.

### Query intent accuracy

Check:

```text
correct domain
correct intent
correct date expressions
correct filters
```

---

## 35. First training configuration

For a tiny model:

```text
Model: Qwen3-0.6B-Instruct or Qwen2.5-0.5B-Instruct
Method: LoRA
Max sequence length: 512
Batch size: 1 or 2
Gradient accumulation: 8 or 16
LoRA rank: 8 or 16
Learning rate: around 2e-4 as a starting point
Epochs: 2-4
```

For 1.7B:

```text
Model: Qwen3-1.7B-Instruct
Method: QLoRA
Max sequence length: 512
Batch size: 1
Gradient accumulation: 16
LoRA rank: 8
Epochs: 2-3
```

Do not chase perfect settings early. Get a full training/evaluation loop working first.

---

## 36. Training workflow

### Step 1: Define schemas

Do not train until your JSON schema is stable.

### Step 2: Generate 500 examples

Include all prefixes.

### Step 3: Test base model with prompting

Before fine-tuning, try prompt-only extraction.

### Step 4: Fine-tune tiny model

Use LoRA.

### Step 5: Evaluate on held-out test set

Measure JSON validity and field accuracy.

### Step 6: Collect failures

Examples:

```text
wrong amount
wrong ledger direction
missed second entry
invalid JSON
wrong section
```

### Step 7: Add corrected failures to dataset

This is where the model actually improves.

### Step 8: Retrain

Repeat.

This loop matters more than the first training run.

---

# Part G — Prompts

---

## 37. System prompt for note parsing

Use something like:

```text
You are a parser for a private local notes app.
Return only valid JSON.
Do not explain.
Do not calculate totals.
Extract records from the user's note.
Supported sections: expense, weight, ledger, todo, note.
Use INR when currency is missing.
Use kg when weight unit is missing.
Preserve the user's meaning.
If uncertain, include lower confidence.
```

---

## 38. System prompt for query parsing

```text
You are a query parser for a private local notes app.
Return only valid JSON.
Do not answer the user.
Do not calculate numbers.
Convert the user's question into a query intent.
Supported domains: expense, weight, ledger, todo, note_search.
Supported intents: total, compare, breakdown, list, average, trend, change, balance, search, search_pending.
Use date expressions like this_month, last_month, april, today, last_6_months.
```

---

## 39. System prompt for final answer from retrieved data

```text
You write short final answers for a local notes app.
Use only the provided data.
Do not invent facts.
Do not change numbers.
If data is incomplete, say so clearly.
Keep the answer simple.
```

Use this only after your app has already retrieved/computed the result.

---

# Part H — JSON Reliability

---

## 40. Fine-tuning alone is not enough

Even a fine-tuned model may output invalid JSON.

Use layers:

```text
1. Good prompt
2. Fine-tuning
3. JSON schema validation
4. Retry/repair if invalid
5. Grammar/constrained decoding if runtime supports it
```

If using llama.cpp or similar runtimes, look into grammar-constrained JSON output.

But remember: grammar only constrains shape. The prompt must still describe the meaning of fields.

---

## 41. App-side validation

After the model outputs JSON, validate it.

Example checks:

```text
Is JSON parseable?
Does task exist?
Does section exist?
Is records an array?
For expense: item and amount exist?
For ledger: direction is one of allowed values?
For weight: value is numeric?
```

If invalid:

```text
retry once with correction prompt
or fall back to manual confirmation
```

---

# Part I — MVP Build Plan

---

## 42. Version 1 scope

Do not build everything at once.

V1 should support:

```text
expense extraction
weight extraction
ledger extraction with confirmation
todo extraction
note storage with title/summary/topics
expense total query
expense compare query
weight change query
ledger balance query
todo keyword search
note keyword search
```

Do not start with:

```text
advanced embeddings
MCP
complex agents
voice input
charts
cloud sync
multi-device conflict resolution
```

Those are later.

---

## 43. MVP pipeline

```text
User writes prefixed note
   ↓
Save raw note immediately
   ↓
Parse note using rules or model
   ↓
Validate JSON
   ↓
Show confirmation for ledger / low-confidence entries
   ↓
Store structured records
   ↓
Update FTS
```

Question flow:

```text
User asks question
   ↓
Parse query intent
   ↓
Route to function
   ↓
SQLite/FTS retrieves/calculates
   ↓
Template answer
   ↓
Optional LLM summary
```

---

## 44. Rule parser before LLM

For very simple patterns, do not use the LLM.

Examples rule parser can handle:

```text
expense: sugar 50
expense: 50 sugar
expense: sugar-50
expense: sugar:50
weight: magesh 62.5
```

This saves battery and improves reliability.

Use LLM for messy cases:

```text
expense: spent around 2k for petrol and 350 for snacks
ledger: I need to return 5k to maddy and kumar has to give me 2k
note: long paragraph that needs title and topics
```

---

## 45. Confirmation rules

Ask confirmation when:

```text
ledger direction is involved
confidence is low
amount is unusually high
person alias is unknown
multiple interpretations are possible
```

Example:

```text
Detected: You owe Maddy ₹5,000. Save?
```

This builds user trust.

---

# Part J — Questions You Should Answer Before Coding

You asked me not to assume even simple behaviour. These are the questions you should answer and give to Codex before implementing.

## Expense questions

1. Will `expense:` always mean money spent by you?
2. Will refunds be entered under `expense:` or a separate prefix like `refund:`?
3. Should `gold 300000` be treated as expense, investment, or both?
4. Do you want categories like food, transport, health, education, gold, household?
5. Should the model auto-categorize expenses, or should category be optional?
6. Should amount be stored as integer rupees or paise?
7. Do you need support for decimals like `petrol 1050.50`?
8. Do you need support for multiple currencies, or only INR?
9. If no date is mentioned, should the date be note creation date?
10. Should `this month` mean from month start to today, or full calendar month?

## Weight questions

1. What are the canonical people you want to track?
2. What aliases refer to each person?
3. Should unknown person names be auto-created or require confirmation?
4. Is default unit always kg?
5. Should weight entries allow notes like `after dinner`, `morning`, `fasting`?
6. Should the app track height/BMI later, or only weight?

## Ledger questions

1. Do you want only open balances or full historical ledger?
2. How will repayments be entered?
3. Should `I paid maddy 1000` reduce what you owe Maddy?
4. Should `maddy returned 500` reduce what Maddy owes you?
5. Should ledger entries require confirmation always?
6. Should person aliases apply to ledger too?
7. Should ledger support partial settlement and closed status?

## Todo questions

1. Should todos support due dates?
2. Should todos support reminders/notifications?
3. Should todos support priority?
4. Should todos support recurring tasks?
5. How will you mark todos completed?
6. Should completed todos appear in search by default?

## Note questions

1. Should `note:` always generate title/summary/topics?
2. Should long notes be chunked for retrieval?
3. Should note summaries be editable by user?
4. Should topics be auto-generated or user-controlled?
5. Should private/sensitive notes be excluded from AI processing?

## AI/privacy questions

1. Will all inference be local on-device?
2. Are you okay using Colab/cloud only for training synthetic/general examples?
3. Will real personal notes ever be used in cloud training?
4. Do you need an option to disable AI for a note?
5. Should model outputs be stored for debugging?

## Retrieval questions

1. Should search prioritize exact keyword match or semantic meaning?
2. Should recent notes rank higher?
3. Should todo search only show open todos by default?
4. Should note search include todos/expenses/ledger too, or only `note:` entries?
5. Should the app show sources for answers?

---

# Part K — What to Ask Codex to Build First

---

## 46. First Codex task

Ask Codex:

```text
Create a Python script that generates synthetic JSONL training data for my local AI notes app.
It should generate examples for expense, weight, ledger, todo, note, and query parsing.
Use the schemas in this Markdown file.
Include typos, amount formats like k/lakh, multiple entries, and natural language variations.
Output train.jsonl, valid.jsonl, and test.jsonl.
```

---

## 47. Second Codex task

```text
Create a Python evaluator that reads model outputs and checks:
1. valid JSON
2. required fields
3. correct number of records
4. correct expense amounts
5. correct ledger direction
6. correct query domain and intent
```

---

## 48. Third Codex task

```text
Create a minimal fine-tuning notebook using Unsloth or Hugging Face TRL for Qwen3-0.6B-Instruct or Qwen2.5-0.5B-Instruct using LoRA.
The dataset is JSONL chat format with system/user/assistant messages.
Save the LoRA adapter after training.
```

---

## 49. Fourth Codex task

```text
Create an inference script that loads the base model + LoRA adapter and tests it on 50 sample notes/questions.
Print model output, parsed JSON, and validation status.
```

---

# Part L — What Success Looks Like

---

## 50. Minimum acceptable results

Before integrating into Android, aim for:

```text
JSON validity: > 98%
Expense amount accuracy: > 95%
Weight person/value accuracy: > 95%
Ledger direction accuracy: > 98% on common examples
Todo extraction accuracy: > 90%
Query intent accuracy: > 90%
```

If ledger direction is below 98%, do not silently save ledger entries.

---

## 51. Final mental model

A 15-year-old version:

Imagine your app is a school office.

The user writes messy notes on paper.

The LLM is the clerk who reads the paper and fills forms:

```text
expense form
weight form
ledger form
todo form
note form
```

SQLite is the filing cabinet.

FTS/embeddings are the search system that finds old files.

Kotlin code is the accountant who adds numbers correctly.

The final answer is the receptionist who explains the result politely.

Do not ask the clerk to remember every paper.  
Do not ask the clerk to be the accountant.  
Do not ask the clerk to be the filing cabinet.  
Make the clerk good at filling forms.

That is what fine-tuning is for.

---

## 52. Practical next step

Do this next:

```text
1. Finalize JSON schemas.
2. Generate 500 synthetic examples.
3. Add 100 examples manually in your real typing style.
4. Test prompt-only model first.
5. Fine-tune Qwen3-0.6B or Qwen2.5-0.5B.
6. Evaluate strictly.
7. Add failure cases.
8. Repeat.
```

Do not start by building a huge training pipeline. Start by proving the schema and evaluation.

---

## 53. References to study later

These are useful areas to learn after the first prototype:

```text
LoRA and QLoRA fine-tuning
Hugging Face TRL SFTTrainer
Unsloth fine-tuning notebooks
SQLite FTS5
local embeddings
RAG
llama.cpp grammar-constrained JSON output
Android on-device inference
GGUF quantization
```

Do not try to learn all of them before starting. Build the smallest working loop first.
