"""Adversarial tests for the SQL safety gate.

Run with:  python test_sql_safety.py

Builds a tiny temp DB so execute_safe can be exercised end-to-end against
both allowed reads and rejected attacks.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

from sql_safety import (
    ALLOWED_TABLES,
    SqlSafetyError,
    execute_safe,
    format_rows,
    open_readonly_connection,
    validate_sql,
)


def _build_temp_db() -> str:
    fd, path = tempfile.mkstemp(prefix="sqlsafe_", suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE expenses (
          id INTEGER PRIMARY KEY,
          amount REAL,
          description TEXT,
          date TEXT,
          month TEXT,
          created_at TEXT
        );
        CREATE TABLE ledger (
          id INTEGER PRIMARY KEY,
          person TEXT,
          amount REAL,
          direction TEXT,
          note TEXT,
          date TEXT,
          created_at TEXT
        );
        CREATE VIEW ledger_balance AS
          SELECT person, SUM(CASE WHEN direction='gave' THEN amount ELSE -amount END) AS balance
          FROM ledger GROUP BY person;
        CREATE TABLE weights (id INTEGER PRIMARY KEY, person TEXT, weight REAL, date TEXT, note TEXT);
        CREATE TABLE todos (id INTEGER PRIMARY KEY, content TEXT, status TEXT, date TEXT);
        CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, content TEXT);
        CREATE TABLE embeddings (id INTEGER PRIMARY KEY, content TEXT);
        CREATE TABLE pending_actions (id INTEGER PRIMARY KEY, prompt TEXT);
        CREATE TABLE user_routing_memory (id INTEGER PRIMARY KEY, input_pattern TEXT);
        CREATE TABLE activity_log (id INTEGER PRIMARY KEY, kind TEXT);

        INSERT INTO expenses(amount,description,date,month,created_at) VALUES
          (500, 'petrol', '2026-04-15', '2026-04', '2026-04-15 09:00:00'),
          (60, 'milk', '2026-05-01', '2026-05', '2026-05-01 09:00:00'),
          (1200, 'groceries', '2026-04-22', '2026-04', '2026-04-22 09:00:00');
        INSERT INTO ledger(person,amount,direction,date) VALUES
          ('maddy', 7000, 'gave', '2026-03-12'),
          ('ravi', 10000, 'received', '2026-04-01');
        INSERT INTO weights(person,weight,date) VALUES
          ('jeevi', 60.1, '2026-04-24'),
          ('prani', 11.5, '2026-05-03');
        INSERT INTO todos(content,status,date) VALUES
          ('renew license', 'pending', '2026-05-01'),
          ('haircut', 'done', '2026-04-20');
        INSERT INTO persons(name) VALUES ('jeevi'),('prani'),('maddy');
        INSERT INTO notes(content) VALUES ('vivekananda note'),('any mention on tamilnad mercentile bank');
        """
    )
    conn.commit()
    conn.close()
    return path


# Each entry: (label, sql, expect_ok)  where expect_ok = should pass safety gate.
CASES = [
    # ---- valid reads ----
    ("plain SELECT expenses",
     "SELECT amount, description FROM expenses WHERE month = ?", True),
    ("SELECT ledger_balance view",
     "SELECT person, balance FROM ledger_balance WHERE balance < 0", True),
    ("aggregate",
     "SELECT SUM(amount) FROM expenses WHERE month = ? AND description NOT LIKE ?", True),
    ("subquery on allowed table",
     "SELECT person, weight FROM weights w "
     "WHERE date = (SELECT MAX(date) FROM weights WHERE person = w.person)", True),
    ("UNION of selects",
     "SELECT person, amount FROM ledger WHERE direction='gave' "
     "UNION ALL SELECT person, amount FROM ledger WHERE direction='received'", True),
    ("WITH cte over allowed tables",
     "WITH t AS (SELECT amount FROM expenses) SELECT SUM(amount) FROM t", True),
    ("trailing semicolon allowed",
     "SELECT 1 FROM persons;", True),

    # ---- rejected: mutating ----
    ("INSERT", "INSERT INTO expenses(amount,description) VALUES (1,'x')", False),
    ("UPDATE", "UPDATE expenses SET amount = 0", False),
    ("DELETE", "DELETE FROM expenses WHERE id = 1", False),
    ("DROP", "DROP TABLE expenses", False),
    ("CREATE", "CREATE TABLE foo (id INT)", False),
    ("ALTER", "ALTER TABLE expenses ADD COLUMN x TEXT", False),
    ("PRAGMA", "PRAGMA table_info(expenses)", False),
    ("ATTACH", "ATTACH DATABASE 'evil.db' AS evil", False),
    ("DETACH", "DETACH DATABASE main", False),

    # ---- rejected: blocked tables ----
    ("notes table blocked", "SELECT * FROM notes", False),
    ("embeddings blocked", "SELECT * FROM embeddings", False),
    ("pending_actions blocked", "SELECT * FROM pending_actions", False),
    ("user_routing_memory blocked", "SELECT * FROM user_routing_memory", False),
    ("activity_log blocked", "SELECT * FROM activity_log", False),
    ("sqlite_master blocked", "SELECT name FROM sqlite_master", False),
    ("schema-qualified main.expenses", "SELECT * FROM main.expenses", False),
    ("blocked table inside subquery",
     "SELECT amount FROM expenses WHERE description IN (SELECT content FROM notes)", False),
    ("blocked table inside UNION",
     "SELECT amount FROM expenses UNION SELECT id FROM notes", False),
    ("blocked table inside WITH",
     "WITH t AS (SELECT id FROM notes) SELECT * FROM t", False),

    # ---- rejected: multi-statement / injection laundering ----
    ("two SELECTs with semicolon",
     "SELECT 1; SELECT 2", False),
    ("SELECT then DROP",
     "SELECT * FROM expenses; DROP TABLE expenses", False),
    ("comment cannot smuggle DROP",
     "SELECT * FROM expenses /* ; DROP TABLE expenses */", True),  # comment is harmless
    ("garbage non-SQL", "NOT_SQL", False),
    ("empty string", "", False),
    ("only whitespace", "   ", False),

    # ---- rejected: malformed ----
    ("table-less SELECT", "SELECT 1", False),
    ("nonexistent allowlisted-style table", "SELECT * FROM unknown_table", False),
]


def _check_params_rejection() -> tuple[int, int]:
    db_path = _build_temp_db()
    try:
        # Bad param types must raise SqlSafetyError
        bad_cases = [
            ([{"x": 1}], "dict param"),
            ([[1, 2]], "list param"),
            ([object()], "object param"),
        ]
        passed = 0
        for params, label in bad_cases:
            try:
                execute_safe(
                    "SELECT * FROM expenses WHERE id = ?",
                    params=params,
                    db_path=db_path,
                )
                print(f"FAIL [param-{label}]: should have raised SqlSafetyError")
            except SqlSafetyError:
                passed += 1
                print(f"  ok  [param-{label}] correctly rejected")
        return passed, len(bad_cases)
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _check_ro_connection() -> tuple[int, int]:
    db_path = _build_temp_db()
    try:
        ro = open_readonly_connection(db_path)
        try:
            ro.execute("INSERT INTO expenses(amount,description) VALUES (9, 'x')")
            print("FAIL [ro-conn]: write succeeded on read-only connection")
            return 0, 1
        except sqlite3.OperationalError:
            print("  ok  [ro-conn] write correctly rejected")
            return 1, 1
        finally:
            ro.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _check_row_cap() -> tuple[int, int]:
    db_path = _build_temp_db()
    try:
        # Cap forced low so we can prove truncation.
        result = execute_safe(
            "SELECT id FROM expenses ORDER BY id",
            db_path=db_path,
            row_cap=2,
        )
        if len(result.rows) == 2:
            print("  ok  [row-cap] cap honored")
            return 1, 1
        print(f"FAIL [row-cap] expected 2 rows, got {len(result.rows)}")
        return 0, 1
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _check_format_rows() -> tuple[int, int]:
    db_path = _build_temp_db()
    try:
        empty = execute_safe(
            "SELECT id FROM expenses WHERE id < 0",
            db_path=db_path,
        )
        single = execute_safe(
            "SELECT SUM(amount) FROM expenses",
            db_path=db_path,
        )
        many = execute_safe(
            "SELECT id, amount FROM expenses ORDER BY id",
            db_path=db_path,
        )
        ok = (
            "No matching" in format_rows(empty)
            and format_rows(single).strip().startswith(("17", "1760"))  # 500+60+1200=1760
            and " | " in format_rows(many)
        )
        if ok:
            print("  ok  [format] formatting branches behave")
            return 1, 1
        print("FAIL [format]")
        print(" empty:", format_rows(empty))
        print(" single:", format_rows(single))
        print(" many:", format_rows(many))
        return 0, 1
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def main() -> int:
    passed = 0
    failed = 0
    for label, sql, expect_ok in CASES:
        result = validate_sql(sql)
        ok = result.ok
        if ok == expect_ok:
            passed += 1
            print(f"  ok  [{label}] -> {('accept' if ok else 'reject')}"
                  + (f"  ({result.reason})" if not ok else ""))
        else:
            failed += 1
            print(f"FAIL [{label}] expected={expect_ok} got={ok} reason={result.reason}")

    p, t = _check_params_rejection(); passed += p; failed += (t - p)
    p, t = _check_ro_connection(); passed += p; failed += (t - p)
    p, t = _check_row_cap(); passed += p; failed += (t - p)
    p, t = _check_format_rows(); passed += p; failed += (t - p)

    print(f"\n{passed} passed, {failed} failed (allowlist={sorted(ALLOWED_TABLES)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
