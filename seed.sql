-- Second Brain — schema + seed data
-- Run order: schema → views → seed inserts

-- ============================================================
-- SCHEMA
-- ============================================================

DROP VIEW IF EXISTS ledger_balance;
DROP TABLE IF EXISTS persons;
DROP TABLE IF EXISTS captures;
DROP TABLE IF EXISTS runtime_state;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS expenses;
DROP TABLE IF EXISTS ledger;
DROP TABLE IF EXISTS weights;
DROP TABLE IF EXISTS todos;
DROP TABLE IF EXISTS buy_items;
DROP TABLE IF EXISTS investment_events;
DROP TABLE IF EXISTS embeddings;
DROP TABLE IF EXISTS activity_log;
DROP TABLE IF EXISTS user_routing_memory;

-- Persistent log of every input + response. Powers the home feed (last 10)
-- and the dedicated /activity page (full history with pagination).
CREATE TABLE activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    kind TEXT,        -- 'query' | 'write' | 'person_command' | 'unknown' | 'memo' | 'clarification'
    metadata_json TEXT,  -- {tier, confidence, rule, ...} for parse-readback toast
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Single source of truth for known people, used by weights and ledger.
-- Managed via chat commands ADD_PERSON / REMOVE_PERSON / MODIFY_PERSON only.
CREATE TABLE persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,        -- lowercase, trimmed
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_input TEXT NOT NULL,
    capture_type TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    input_kind TEXT NOT NULL DEFAULT 'note',
    structured_type TEXT,
    note_domain TEXT,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    processed_at TEXT
);

CREATE TABLE buy_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_text TEXT NOT NULL,
    quantity_text TEXT,
    unit_text TEXT,
    date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
    raw_note TEXT,
    source_note_id INTEGER,
    source_capture_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    description TEXT NOT NULL,
    date TEXT,
    month TEXT,
    group_name TEXT,
    raw_note TEXT,
    source_note_id INTEGER,
    source_capture_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,
    amount REAL NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('gave','received')),
    note TEXT,
    date TEXT,
    source_note_id INTEGER,
    source_capture_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE VIEW ledger_balance AS
SELECT person,
       SUM(CASE WHEN direction='gave' THEN amount ELSE -amount END) AS balance
FROM ledger
GROUP BY person;

CREATE TABLE weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT NOT NULL,
    weight REAL NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    source_note_id INTEGER,
    source_capture_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    date TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','done')),
    source_note_id INTEGER,
    source_capture_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE investment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    event_type TEXT,
    content TEXT,
    amount REAL,
    date TEXT,
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    source TEXT,
    date TEXT,
    source_note_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Memoized routing decisions, populated by orchestrator clarify resolutions.
-- Looked up between Tier 0 and Tier 1 — repeated inputs skip the LLM entirely.
-- Pruned: rows with last_used > 90 days are dropped on app open.
CREATE TABLE user_routing_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_pattern TEXT NOT NULL UNIQUE,    -- normalize(input): lowercase, whitespace-collapsed
    resolved_tool TEXT NOT NULL,
    resolved_args_json TEXT,
    hit_count INTEGER DEFAULT 1,
    last_used TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_routing_pattern ON user_routing_memory(input_pattern);

CREATE TABLE runtime_state (
    state_key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- SEED — PERSONS (the whitelist)
-- ============================================================
INSERT INTO persons (name) VALUES
('jeevi'), ('prani'), ('murugan'), ('maddy'), ('thenna');

-- ============================================================
-- SEED — LEDGER
-- ============================================================
INSERT INTO ledger (person, amount, direction, note, date) VALUES
('thenna', 20000, 'gave', 'initial balance', '2026-01-01'),
('maddy',   7000, 'gave', 'initial balance', '2026-01-01');

-- ============================================================
-- SEED — WEIGHTS
-- ============================================================
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

-- ============================================================
-- SEED — EXPENSES
-- ============================================================
INSERT INTO expenses (amount, description, date, month) VALUES
(30,   'tea + bonda',               '2026-02-01', '2026-02'),
(184,  'mushroom fried rice',       '2026-02-01', '2026-02'),
(650,  'Tirupathi undiyal',         '2026-02-01', '2026-02'),
(500,  'Tirupathi zoo ebike',       '2026-02-01', '2026-02'),
(143,  'Medplus Pampers',           '2026-02-01', '2026-02'),
(999,  'jeevi dress',               '2026-02-01', '2026-02'),
(1000, 'petrol',                    '2026-02-01', '2026-02'),
(2000, 'petrol',                    '2026-03-01', '2026-03'),
(839,  'Bombay Ananda bhavan sweet','2026-03-01', '2026-03');

-- ============================================================
-- SEED — TODOS (a couple, for query 9)
-- ============================================================
INSERT INTO todos (content, status) VALUES
('update Amit about MCP understanding', 'pending'),
('complete app development phase 1',    'pending'),
('haircut on thursday',                 'done');
