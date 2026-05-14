"""CRUD regression test for the Flask management pages.

Verifies the new page-level flows:
- Notes page shows only real notes and supports add/edit/delete.
- Expenses/Ledger/Weights/Todos can be added from their own pages.
- Page-based structured adds use captures, not notes.
- Individual delete / clear-all clean up orphan captures.
"""
from __future__ import annotations

import math
import os
import shutil
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))


class _FakeEmbed:
    def status(self):
        return {"available": True, "load_error": None}

    def encode(self, text, perf=None, label="embedding"):
        if not text:
            return None
        vec = [0.0] * 26
        for ch in text.lower():
            if "a" <= ch <= "z":
                vec[ord(ch) - ord("a")] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return None
        return [v / norm for v in vec]


def main() -> int:
    src_db = os.path.join(APP_DIR, "second_brain.db")
    if not os.path.exists(src_db):
        print(f"FAIL: {src_db} not found.")
        return 1

    tmp_dir = os.path.join(APP_DIR, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_db = os.path.join(tmp_dir, "test_flask_crud.db")
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    shutil.copy2(src_db, tmp_db)

    os.environ["SECOND_BRAIN_DB_PATH"] = tmp_db
    for mod in ("second_brain_core", "second_brain_orchestrator", "app"):
        if mod in sys.modules:
            del sys.modules[mod]

    from second_brain_core import create_note_record, db_connection, ensure_runtime_schema

    ensure_runtime_schema(tmp_db)

    import app as app_module

    app_module.get_runtime_services = lambda: (None, _FakeEmbed())
    client = app_module.app.test_client()

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        marker = "PASS" if ok else "FAIL"
        line = f"[{marker}] {label}"
        if detail:
            line += f" -- {detail}"
        print(line)
        if not ok:
            failures.append(label)

    # Seed one structured legacy note to confirm the new notes page hides it.
    with db_connection(tmp_db) as conn:
        create_note_record(
            conn,
            "legacy structured expense source",
            input_kind="note",
            structured_type="expense",
        )
        conn.commit()

    response = client.get("/notes")
    html = response.get_data(as_text=True)
    check("notes page renders", response.status_code == 200)
    check(
        "notes page hides non-note structured rows",
        "legacy structured expense source" not in html,
    )

    response = client.post(
        "/notes/add",
        data={"content": "vivekananda note from editor"},
        follow_redirects=False,
    )
    with db_connection(tmp_db) as conn:
        note_row = conn.execute(
            "SELECT id, content, structured_type FROM notes WHERE structured_type = 'note' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        emb_row = conn.execute(
            "SELECT content FROM embeddings WHERE source_note_id = ?",
            (note_row["id"],),
        ).fetchone()
    check("notes add redirects", response.status_code == 302)
    check(
        "notes add creates a real note row",
        bool(note_row) and note_row["content"] == "vivekananda note from editor",
        f"note={dict(note_row) if note_row else None}",
    )
    check(
        "notes add writes an embedding row",
        bool(emb_row) and emb_row["content"] == "vivekananda note from editor",
        f"embedding={dict(emb_row) if emb_row else None}",
    )

    note_id = int(note_row["id"])
    response = client.post(
        f"/notes/{note_id}/edit",
        data={"content": "vivekananda note edited"},
        follow_redirects=False,
    )
    with db_connection(tmp_db) as conn:
        note_row = conn.execute(
            "SELECT content FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        emb_row = conn.execute(
            "SELECT content FROM embeddings WHERE source_note_id = ?",
            (note_id,),
        ).fetchone()
    check("notes edit redirects", response.status_code == 302)
    check(
        "notes edit updates note text and embedding",
        bool(note_row)
        and note_row["content"] == "vivekananda note edited"
        and emb_row
        and emb_row["content"] == "vivekananda note edited",
    )

    with db_connection(tmp_db) as conn:
        note_count_before_expense = conn.execute(
            "SELECT COUNT(*) AS c FROM notes"
        ).fetchone()["c"]
    response = client.post(
        "/expenses/add",
        data={"description": "petrol", "amount": "500", "date": "2026-05-03"},
        follow_redirects=False,
    )
    with db_connection(tmp_db) as conn:
        expense_row = conn.execute(
            "SELECT id, description, amount, source_capture_id, source_note_id FROM expenses ORDER BY id DESC LIMIT 1"
        ).fetchone()
        note_count_after_expense = conn.execute(
            "SELECT COUNT(*) AS c FROM notes"
        ).fetchone()["c"]
        capture_row = conn.execute(
            "SELECT id, raw_input, capture_type FROM captures WHERE id = ?",
            (expense_row["source_capture_id"],),
        ).fetchone()
    check("expenses add redirects", response.status_code == 302)
    check(
        "expenses add uses captures and does not create a note row",
        bool(expense_row)
        and expense_row["description"] == "petrol"
        and expense_row["source_capture_id"] is not None
        and expense_row["source_note_id"] is None
        and note_count_before_expense == note_count_after_expense
        and capture_row
        and capture_row["capture_type"] == "expense",
        f"expense={dict(expense_row) if expense_row else None} capture={dict(capture_row) if capture_row else None}",
    )

    expense_id = int(expense_row["id"])
    capture_id = int(expense_row["source_capture_id"])
    response = client.post(f"/expenses/{expense_id}/delete", follow_redirects=False)
    with db_connection(tmp_db) as conn:
        expense_row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        capture_row = conn.execute(
            "SELECT id FROM captures WHERE id = ?",
            (capture_id,),
        ).fetchone()
    check("expenses delete redirects", response.status_code == 302)
    check(
        "expenses delete removes the row and its orphan capture",
        expense_row is None and capture_row is None,
    )

    response = client.post(
        "/ledger/add",
        data={
            "person": "maddy",
            "amount": "1500",
            "direction": "gave",
            "date": "2026-05-03",
            "note": "ui add",
        },
        follow_redirects=False,
    )
    with db_connection(tmp_db) as conn:
        ledger_row = conn.execute(
            "SELECT id, person, amount, source_capture_id FROM ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()
        capture_row = conn.execute(
            "SELECT id FROM captures WHERE id = ?",
            (ledger_row["source_capture_id"],),
        ).fetchone()
    check("ledger add redirects", response.status_code == 302)
    check(
        "ledger add creates a capture-linked row",
        bool(ledger_row)
        and ledger_row["person"] == "maddy"
        and abs(float(ledger_row["amount"]) - 1500.0) < 1e-6
        and capture_row is not None,
    )

    ledger_id = int(ledger_row["id"])
    capture_id = int(ledger_row["source_capture_id"])
    response = client.post(f"/ledger/{ledger_id}/delete", follow_redirects=False)
    with db_connection(tmp_db) as conn:
        ledger_row = conn.execute(
            "SELECT id FROM ledger WHERE id = ?",
            (ledger_id,),
        ).fetchone()
        capture_row = conn.execute(
            "SELECT id FROM captures WHERE id = ?",
            (capture_id,),
        ).fetchone()
    check("ledger delete redirects", response.status_code == 302)
    check(
        "ledger delete removes the row and its orphan capture",
        ledger_row is None and capture_row is None,
    )

    response = client.post(
        "/weights/add",
        data={
            "person": "jeevi",
            "weight": "66.2",
            "date": "2026-05-03",
            "note": "editor add",
        },
        follow_redirects=False,
    )
    with db_connection(tmp_db) as conn:
        weight_row = conn.execute(
            "SELECT id, person, weight, source_capture_id FROM weights ORDER BY id DESC LIMIT 1"
        ).fetchone()
        capture_row = conn.execute(
            "SELECT id FROM captures WHERE id = ?",
            (weight_row["source_capture_id"],),
        ).fetchone()
    check("weights add redirects", response.status_code == 302)
    check(
        "weights add creates a capture-linked row",
        bool(weight_row)
        and weight_row["person"] == "jeevi"
        and abs(float(weight_row["weight"]) - 66.2) < 1e-6
        and capture_row is not None,
    )

    weight_id = int(weight_row["id"])
    capture_id = int(weight_row["source_capture_id"])
    response = client.post(f"/weights/{weight_id}/delete", follow_redirects=False)
    with db_connection(tmp_db) as conn:
        weight_row = conn.execute(
            "SELECT id FROM weights WHERE id = ?",
            (weight_id,),
        ).fetchone()
        capture_row = conn.execute(
            "SELECT id FROM captures WHERE id = ?",
            (capture_id,),
        ).fetchone()
    check("weights delete redirects", response.status_code == 302)
    check(
        "weights delete removes the row and its orphan capture",
        weight_row is None and capture_row is None,
    )

    response = client.post(
        "/todos/add",
        data={"content": "buy milk\ncall Amit"},
        follow_redirects=False,
    )
    with db_connection(tmp_db) as conn:
        todo_rows = conn.execute(
            "SELECT id, content, source_capture_id FROM todos ORDER BY id DESC LIMIT 2"
        ).fetchall()
        capture_ids = {row["source_capture_id"] for row in todo_rows}
    todo_texts = {row["content"] for row in todo_rows}
    check("todos add redirects", response.status_code == 302)
    check(
        "todos add splits multiline input and shares one capture",
        len(todo_rows) == 2
        and todo_texts == {"buy milk", "call Amit"}
        and len(capture_ids) == 1,
        f"todos={todo_texts} capture_ids={capture_ids}",
    )

    shared_capture_id = next(iter(capture_ids))
    response = client.post("/todos/clear", follow_redirects=False)
    with db_connection(tmp_db) as conn:
        todo_count = conn.execute("SELECT COUNT(*) AS c FROM todos").fetchone()["c"]
        capture_row = conn.execute(
            "SELECT id FROM captures WHERE id = ?",
            (shared_capture_id,),
        ).fetchone()
    check("todos clear redirects", response.status_code == 302)
    check(
        "todos clear removes all todos and the shared capture",
        todo_count == 0 and capture_row is None,
        f"todo_count={todo_count} capture={capture_row}",
    )

    response = client.post(f"/notes/{note_id}/delete", follow_redirects=False)
    with db_connection(tmp_db) as conn:
        note_row = conn.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
        emb_row = conn.execute(
            "SELECT id FROM embeddings WHERE source_note_id = ?",
            (note_id,),
        ).fetchone()
    check("notes delete redirects", response.status_code == 302)
    check(
        "notes delete removes note and embedding",
        note_row is None and emb_row is None,
    )

    print()
    print("-" * 70)
    if failures:
        print(f"FAILED: {len(failures)} checks")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("PASSED: all CRUD checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
