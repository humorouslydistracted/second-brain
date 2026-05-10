from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, url_for

from second_brain_core import (
    DEFAULT_DB_PATH,
    add_entry_result,
    create_capture_record,
    create_note_record,
    db_connection,
    ensure_activity_log_schema,
    infer_note_domain,
    load_known_persons,
    prune_routing_memory,
    split_todo_items,
    store_note_embedding,
)
from second_brain_mcp_client import call_tool_sync
from second_brain_orchestrator import (
    get_runtime_services,
    handle as orchestrate,
    warm_runtime_services,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SECOND_BRAIN_FINETUNED_PARSER_ENABLED", "1")
os.environ.setdefault("SECOND_BRAIN_SELF_PERSON", "murugan")
DB_PATH = DEFAULT_DB_PATH

app = Flask(__name__)
app.secret_key = "dev-only-not-secret"

if os.path.exists(DB_PATH):
    ensure_activity_log_schema(DB_PATH)


def db():
    return db_connection(DB_PATH)


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_date(value: str | None) -> str:
    raw = (value or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return _today_iso()


def _parse_float(value: str | None) -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _note_feedback(action: str, embedding_status: dict | None) -> str:
    suffix = ""
    if embedding_status and not embedding_status.get("embedded"):
        suffix = " (search index not available)"
    return f"Note {action}{suffix}"


def _count_linked_rows(conn: sqlite3.Connection, column_name: str, source_id: int | None) -> int:
    if not source_id:
        return 0
    total = 0
    for table_name in ("expenses", "ledger", "weights", "todos", "buy_items"):
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table_name} WHERE {column_name} = ?",
            (source_id,),
        ).fetchone()
        total += int(row["c"] if row else 0)
    return total


def _delete_note_embedding(conn: sqlite3.Connection, note_id: int) -> None:
    conn.execute("DELETE FROM embeddings WHERE source_note_id = ?", (note_id,))


def _cleanup_orphan_capture(conn: sqlite3.Connection, capture_id: int | None) -> None:
    if not capture_id:
        return
    if _count_linked_rows(conn, "source_capture_id", capture_id) == 0:
        conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))


def _save_note_text(
    conn: sqlite3.Connection,
    content: str,
    *,
    note_id: int | None = None,
    metadata: dict | None = None,
) -> tuple[int, dict | None]:
    note_text = content.strip()
    domain = infer_note_domain(note_text)
    if note_id is None:
        note_id = create_note_record(
            conn,
            note_text,
            input_kind="note",
            structured_type="note",
            note_domain=domain,
            metadata=metadata,
        )
    else:
        conn.execute(
            """
            UPDATE notes
            SET content = ?,
                input_kind = 'note',
                structured_type = 'note',
                note_domain = ?,
                metadata_json = ?,
                processed_at = ?
            WHERE id = ?
            """,
            (
                note_text,
                domain,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
                datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                note_id,
            ),
        )
    _, embedding_service = get_runtime_services()
    embedding_status = store_note_embedding(
        conn,
        embedding_service,
        note_id,
        note_text,
        domain,
    )
    return note_id, embedding_status


def _person_options(
    conn: sqlite3.Connection,
    *tables: str,
) -> list[dict[str, str]]:
    names = {row["name"] for row in conn.execute("SELECT name FROM persons ORDER BY name").fetchall()}
    for table_name in tables:
        rows = conn.execute(
            f"SELECT DISTINCT person FROM {table_name} WHERE person IS NOT NULL AND person <> '' ORDER BY person"
        ).fetchall()
        names.update(row["person"] for row in rows)
    return [{"name": name} for name in sorted(names)]


def _warm_runtime_models() -> None:
    try:
        result = warm_runtime_services()
        print(f"Runtime warmup complete: {json.dumps(result, ensure_ascii=False)}")
    except Exception as exc:  # pragma: no cover - startup observability only
        print(f"Runtime warmup failed: {exc}")


def _start_runtime_warmup() -> None:
    if os.environ.get("SECOND_BRAIN_PREWARM", "1").lower() not in {"1", "true", "yes"}:
        return
    threading.Thread(target=_warm_runtime_models, name="second-brain-warmup", daemon=True).start()


def _format_ms(value: float | int | None) -> str | None:
    if value is None:
        return None
    value = float(value)
    if value >= 1000:
        return f"{value / 1000.0:.2f}s"
    if value >= 100:
        return f"{value:.0f}ms"
    return f"{value:.1f}ms"


def _build_timing_summary(timings: dict | None, limit: int = 4) -> str | None:
    if not timings:
        return None
    numeric = [
        (str(key), float(value))
        for key, value in timings.items()
        if isinstance(value, (int, float))
    ]
    if not numeric:
        return None
    total = None
    for key, value in numeric:
        if key == "orchestrator.total_ms":
            total = value
            break
    stages = [(key, value) for key, value in numeric if key != "orchestrator.total_ms"]
    stages.sort(key=lambda item: item[1], reverse=True)
    parts = []
    if total is not None:
        parts.append(f"total {_format_ms(total)}")
    for key, value in stages[: max(1, limit)]:
        parts.append(f"{key} {_format_ms(value)}")
    return " · ".join(parts) if parts else None


def _row_with_meta(row: sqlite3.Row) -> dict:
    item = dict(row)
    meta = None
    if item.get("metadata_json"):
        try:
            meta = json.loads(item["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            meta = None
    item["meta"] = meta
    return item


def log_activity(
    input_text: str,
    response: str,
    kind: str,
    conn: sqlite3.Connection,
    metadata: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activity_log (input_text, response_text, kind, metadata_json) VALUES (?,?,?,?)",
        (
            input_text,
            response,
            kind,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
        ),
    )


def recent_activities(conn: sqlite3.Connection, limit: int = 10):
    return conn.execute(
        "SELECT input_text, response_text, kind, metadata_json, created_at FROM activity_log "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


@app.route("/")
def index():
    with db() as conn:
        feed_rows = recent_activities(conn, limit=10)
    feed = [_row_with_meta(row) for row in feed_rows]
    return render_template("index.html", feed=feed)


@app.route("/note", methods=["POST"])
def note():
    text = request.form.get("text", "").strip()
    if not text:
        return redirect(url_for("index"))

    timings: dict[str, float] = {}
    started = time.perf_counter()
    try:
        response_obj = orchestrate(text)
        timings = dict(response_obj.timings_ms or {})
        timings["app.orchestrate_call_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        response = response_obj.response_text
        kind = response_obj.kind
        metadata = {
            "tier": response_obj.tier,
            "confidence": response_obj.confidence,
            "rule": (response_obj.parsed or {}).get("rule"),
            "note_id": response_obj.note_id,
            "timings_ms": timings,
            "timing_summary": _build_timing_summary(timings),
        }
    except Exception as exc:
        response = f"Orchestrator error: {exc}"
        kind = "unknown"
        timings["app.orchestrate_call_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        metadata = {
            "tier": "error",
            "error": str(exc),
            "timings_ms": timings,
            "timing_summary": _build_timing_summary(timings, limit=2),
        }

    with db() as conn:
        log_activity(text, response, kind, conn, metadata=metadata)
        conn.commit()
    return redirect(url_for("index"))


@app.route("/activity")
def activity():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page - 1) * per_page
    with db() as conn:
        rows = conn.execute(
            "SELECT id, input_text, response_text, kind, metadata_json, created_at FROM activity_log "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) c FROM activity_log").fetchone()["c"]
    items = [_row_with_meta(row) for row in rows]
    return render_template(
        "activity.html",
        rows=items,
        page=page,
        per_page=per_page,
        total=total,
    )


@app.route("/notes")
def notes_page():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, content, note_domain, created_at
            FROM notes
            WHERE structured_type = 'note'
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()
    selected_note_id = request.args.get("selected", type=int)
    selected_note = None
    if rows:
        selected_note = rows[0]
        if selected_note_id is not None:
            selected_note = next((row for row in rows if row["id"] == selected_note_id), rows[0])
    return render_template("notes_editor.html", notes=rows, selected_note=selected_note)


@app.route("/notes/add", methods=["POST"])
def notes_add():
    content = request.form.get("content", "").strip()
    if not content:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("notes_page"))

    with db() as conn:
        note_id, embedding_status = _save_note_text(
            conn,
            content,
            metadata={"origin": "notes_page"},
        )
        response = _note_feedback("saved", embedding_status)
        log_activity(
            "Notes page: add note",
            response,
            "write",
            conn,
            metadata={"origin": "notes_page", "note_id": note_id},
        )
        conn.commit()
    flash(response, "success")
    return redirect(url_for("notes_page", selected=note_id))


@app.route("/notes/<int:note_id>/edit", methods=["POST"])
def notes_edit(note_id: int):
    content = request.form.get("content", "").strip()
    if not content:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("notes_page", selected=note_id))

    with db() as conn:
        row = conn.execute(
            "SELECT id FROM notes WHERE id = ? AND structured_type = 'note'",
            (note_id,),
        ).fetchone()
        if not row:
            flash("Note not found.", "warning")
            return redirect(url_for("notes_page"))
        _, embedding_status = _save_note_text(
            conn,
            content,
            note_id=note_id,
            metadata={"origin": "notes_page", "edited": True},
        )
        response = _note_feedback("updated", embedding_status)
        log_activity(
            f"Notes page: edit note #{note_id}",
            response,
            "write",
            conn,
            metadata={"origin": "notes_page", "note_id": note_id, "action": "edit"},
        )
        conn.commit()
    flash(response, "success")
    return redirect(url_for("notes_page", selected=note_id))


@app.route("/notes/<int:note_id>/delete", methods=["POST"])
def notes_delete(note_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT id, content FROM notes WHERE id = ? AND structured_type = 'note'",
            (note_id,),
        ).fetchone()
        if not row:
            flash("Note not found.", "warning")
            return redirect(url_for("notes_page"))
        _delete_note_embedding(conn, note_id)
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        log_activity(
            f"Notes page: delete note #{note_id}",
            "Note deleted",
            "write",
            conn,
            metadata={"origin": "notes_page", "note_id": note_id, "action": "delete"},
        )
        next_row = conn.execute(
            """
            SELECT id
            FROM notes
            WHERE structured_type = 'note'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        conn.commit()
    flash("Note deleted.", "info")
    if next_row:
        return redirect(url_for("notes_page", selected=next_row["id"]))
    return redirect(url_for("notes_page"))


@app.route("/people")
def people():
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM persons ORDER BY name").fetchall()
    return render_template("people.html", persons=rows)


@app.route("/people/add", methods=["POST"])
def people_add():
    name = request.form.get("name", "").strip().lower()
    if not name:
        return redirect(url_for("people"))

    result = call_tool_sync("manage_persons", {"operation": "ADD_PERSON", "name": name})
    category = "warning" if result.get("is_error") else "success"
    flash(result.get("response_text", "No response"), category)
    return redirect(url_for("people"))


@app.route("/people/<int:pid>/rename", methods=["POST"])
def people_rename(pid: int):
    new_name = request.form.get("new_name", "").strip().lower()
    if not new_name:
        return redirect(url_for("people"))

    with db() as conn:
        row = conn.execute("SELECT name FROM persons WHERE id = ?", (pid,)).fetchone()
    if not row:
        flash("Person not found", "warning")
        return redirect(url_for("people"))

    result = call_tool_sync(
        "manage_persons",
        {
            "operation": "MODIFY_PERSON",
            "old_name": row["name"],
            "new_name": new_name,
        },
    )
    category = "warning" if result.get("is_error") else "success"
    flash(result.get("response_text", "No response"), category)
    return redirect(url_for("people"))


@app.route("/people/<int:pid>/delete", methods=["POST"])
def people_delete(pid: int):
    with db() as conn:
        row = conn.execute("SELECT name FROM persons WHERE id = ?", (pid,)).fetchone()
    if not row:
        flash("Person not found", "warning")
        return redirect(url_for("people"))

    result = call_tool_sync("manage_persons", {"operation": "REMOVE_PERSON", "name": row["name"]})
    category = "warning" if result.get("is_error") else "info"
    flash(result.get("response_text", "No response"), category)
    return redirect(url_for("people"))


@app.route("/dashboard")
def dashboard():
    with db() as conn:
        cursor = conn.cursor()
        balances = cursor.execute(
            "SELECT person, balance FROM ledger_balance ORDER BY ABS(balance) DESC"
        ).fetchall()
        month = datetime.now().strftime("%Y-%m")
        spend = cursor.execute(
            "SELECT SUM(amount) t FROM expenses WHERE month = ?",
            (month,),
        ).fetchone()["t"] or 0
        weights = cursor.execute(
            """
            SELECT w1.person, w1.weight, w1.date FROM weights w1
            WHERE w1.date = (SELECT MAX(w2.date) FROM weights w2 WHERE w2.person = w1.person)
            ORDER BY w1.person
            """
        ).fetchall()
        seen = set()
        latest = []
        for row in weights:
            if row["person"] not in seen:
                seen.add(row["person"])
                latest.append(row)
        todos = cursor.execute(
            "SELECT COUNT(*) c FROM todos WHERE status = 'pending'"
        ).fetchone()["c"]
    return render_template(
        "dashboard.html",
        balances=balances,
        month=month,
        spend=spend,
        weights=latest,
        todos=todos,
    )


@app.route("/expenses")
def expenses_page():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, amount, description, month, date, raw_note, source_capture_id
            FROM expenses
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()
    return render_template("expenses.html", rows=rows, today_iso=_today_iso())


@app.route("/expenses/add", methods=["POST"])
def expenses_add():
    description = request.form.get("description", "").strip()
    amount = _parse_float(request.form.get("amount"))
    date = _normalize_date(request.form.get("date"))
    if not description or amount is None or amount <= 0:
        flash("Enter a valid description and amount.", "warning")
        return redirect(url_for("expenses_page"))

    raw_input = f"{description} {amount:g}"
    with db() as conn:
        capture_id = create_capture_record(
            conn,
            raw_input,
            "expense",
            metadata={"origin": "expenses_page"},
        )
        entry = {
            "type": "expense",
            "amount": amount,
            "description": description,
            "date": date,
            "month": date[:7],
            "raw": raw_input,
            "source_capture_id": capture_id,
        }
        result = add_entry_result(conn, entry)
        log_activity(
            f"Expenses page: {raw_input}",
            result["response_text"],
            "write",
            conn,
            metadata={"origin": "expenses_page", "action": "add", "capture_id": capture_id},
        )
        conn.commit()
    flash(result["response_text"], "success")
    return redirect(url_for("expenses_page"))


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
def expenses_delete(expense_id: int):
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, amount, description, source_capture_id
            FROM expenses
            WHERE id = ?
            """,
            (expense_id,),
        ).fetchone()
        if not row:
            flash("Expense not found.", "warning")
            return redirect(url_for("expenses_page"))
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        _cleanup_orphan_capture(conn, row["source_capture_id"])
        response = f"Deleted expense: {row['description']} ({row['amount']:,.0f})"
        log_activity(
            f"Expenses page: delete expense #{expense_id}",
            response,
            "write",
            conn,
            metadata={"origin": "expenses_page", "action": "delete", "expense_id": expense_id},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("expenses_page"))


@app.route("/expenses/clear", methods=["POST"])
def expenses_clear():
    with db() as conn:
        rows = conn.execute(
            "SELECT source_capture_id FROM expenses"
        ).fetchall()
        if not rows:
            flash("No expenses to clear.", "info")
            return redirect(url_for("expenses_page"))
        capture_ids = {row["source_capture_id"] for row in rows if row["source_capture_id"]}
        count = len(rows)
        conn.execute("DELETE FROM expenses")
        for capture_id in capture_ids:
            _cleanup_orphan_capture(conn, capture_id)
        response = f"Cleared {count} expense entr{'y' if count == 1 else 'ies'}"
        log_activity(
            "Expenses page: clear all",
            response,
            "write",
            conn,
            metadata={"origin": "expenses_page", "action": "clear", "count": count},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("expenses_page"))


@app.route("/ledger")
def ledger_page():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, person, amount, direction, note, date, source_capture_id
            FROM ledger
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()
        persons = _person_options(conn, "ledger")
    return render_template("ledger.html", rows=rows, persons=persons, today_iso=_today_iso())


@app.route("/ledger/add", methods=["POST"])
def ledger_add():
    person = request.form.get("person", "").strip().lower()
    amount = _parse_float(request.form.get("amount"))
    direction = request.form.get("direction", "").strip().lower()
    note = request.form.get("note", "").strip() or None
    date = _normalize_date(request.form.get("date"))
    if not person or amount is None or amount <= 0 or direction not in {"gave", "received"}:
        flash("Enter person, amount, and direction.", "warning")
        return redirect(url_for("ledger_page"))

    with db() as conn:
        persons = load_known_persons(conn)
        raw_input = (
            f"gave {person} {amount:g}"
            if direction == "gave"
            else f"got {amount:g} from {person}"
        )
        capture_id = create_capture_record(
            conn,
            raw_input,
            "ledger",
            metadata={"origin": "ledger_page"},
        )
        entry = {
            "type": "ledger",
            "person": person,
            "amount": amount,
            "direction": direction,
            "date": date,
            "note": note,
            "raw": raw_input,
            "source_capture_id": capture_id,
            "unknown_person": person not in persons,
        }
        result = add_entry_result(conn, entry)
        log_activity(
            f"Ledger page: {raw_input}",
            result["response_text"],
            "write",
            conn,
            metadata={"origin": "ledger_page", "action": "add", "capture_id": capture_id},
        )
        conn.commit()
    flash(result["response_text"], "success")
    return redirect(url_for("ledger_page"))


@app.route("/ledger/<int:ledger_id>/delete", methods=["POST"])
def ledger_delete(ledger_id: int):
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, person, amount, direction, source_capture_id
            FROM ledger
            WHERE id = ?
            """,
            (ledger_id,),
        ).fetchone()
        if not row:
            flash("Ledger entry not found.", "warning")
            return redirect(url_for("ledger_page"))
        conn.execute("DELETE FROM ledger WHERE id = ?", (ledger_id,))
        _cleanup_orphan_capture(conn, row["source_capture_id"])
        response = f"Deleted ledger entry for {row['person'].title()}"
        log_activity(
            f"Ledger page: delete ledger #{ledger_id}",
            response,
            "write",
            conn,
            metadata={"origin": "ledger_page", "action": "delete", "ledger_id": ledger_id},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("ledger_page"))


@app.route("/ledger/clear", methods=["POST"])
def ledger_clear():
    with db() as conn:
        rows = conn.execute(
            "SELECT source_capture_id FROM ledger"
        ).fetchall()
        if not rows:
            flash("No ledger entries to clear.", "info")
            return redirect(url_for("ledger_page"))
        capture_ids = {row["source_capture_id"] for row in rows if row["source_capture_id"]}
        count = len(rows)
        conn.execute("DELETE FROM ledger")
        for capture_id in capture_ids:
            _cleanup_orphan_capture(conn, capture_id)
        response = f"Cleared {count} ledger entr{'y' if count == 1 else 'ies'}"
        log_activity(
            "Ledger page: clear all",
            response,
            "write",
            conn,
            metadata={"origin": "ledger_page", "action": "clear", "count": count},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("ledger_page"))


@app.route("/weights")
def weights_page():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, person, weight, date, note, source_capture_id
            FROM weights
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()
        persons = _person_options(conn, "weights")
    return render_template("weights.html", rows=rows, persons=persons, today_iso=_today_iso())


@app.route("/weights/add", methods=["POST"])
def weights_add():
    person = request.form.get("person", "").strip().lower()
    weight = _parse_float(request.form.get("weight"))
    date = _normalize_date(request.form.get("date"))
    note = request.form.get("note", "").strip() or None
    if not person or weight is None or weight <= 0 or weight >= 150:
        flash("Enter a valid person and weight below 150kg.", "warning")
        return redirect(url_for("weights_page"))

    with db() as conn:
        persons = load_known_persons(conn)
        existing_weight_people = {
            row["person"]
            for row in conn.execute(
                "SELECT DISTINCT person FROM weights WHERE person IS NOT NULL AND person <> ''"
            ).fetchall()
        }
        if person not in persons and person not in existing_weight_people:
            flash("Add the person first in the People page.", "warning")
            return redirect(url_for("weights_page"))
        raw_input = f"{person} weight {weight:g}"
        capture_id = create_capture_record(
            conn,
            raw_input,
            "weight",
            metadata={"origin": "weights_page"},
        )
        entry = {
            "type": "weight",
            "person": person,
            "weight": weight,
            "date": date,
            "note": note,
            "raw": raw_input,
            "source_capture_id": capture_id,
        }
        result = add_entry_result(conn, entry)
        log_activity(
            f"Weights page: {raw_input}",
            result["response_text"],
            "write",
            conn,
            metadata={"origin": "weights_page", "action": "add", "capture_id": capture_id},
        )
        conn.commit()
    flash(result["response_text"], "success")
    return redirect(url_for("weights_page"))


@app.route("/weights/<int:weight_id>/delete", methods=["POST"])
def weights_delete(weight_id: int):
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, person, weight, source_capture_id
            FROM weights
            WHERE id = ?
            """,
            (weight_id,),
        ).fetchone()
        if not row:
            flash("Weight entry not found.", "warning")
            return redirect(url_for("weights_page"))
        conn.execute("DELETE FROM weights WHERE id = ?", (weight_id,))
        _cleanup_orphan_capture(conn, row["source_capture_id"])
        response = f"Deleted weight entry for {row['person'].title()}"
        log_activity(
            f"Weights page: delete weight #{weight_id}",
            response,
            "write",
            conn,
            metadata={"origin": "weights_page", "action": "delete", "weight_id": weight_id},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("weights_page"))


@app.route("/weights/clear", methods=["POST"])
def weights_clear():
    with db() as conn:
        rows = conn.execute(
            "SELECT source_capture_id FROM weights"
        ).fetchall()
        if not rows:
            flash("No weight entries to clear.", "info")
            return redirect(url_for("weights_page"))
        capture_ids = {row["source_capture_id"] for row in rows if row["source_capture_id"]}
        count = len(rows)
        conn.execute("DELETE FROM weights")
        for capture_id in capture_ids:
            _cleanup_orphan_capture(conn, capture_id)
        response = f"Cleared {count} weight entr{'y' if count == 1 else 'ies'}"
        log_activity(
            "Weights page: clear all",
            response,
            "write",
            conn,
            metadata={"origin": "weights_page", "action": "clear", "count": count},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("weights_page"))


@app.route("/todos")
def todos_page():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, content, status, created_at, source_capture_id
            FROM todos
            ORDER BY status, id DESC
            """
        ).fetchall()
    return render_template("todos_manage.html", rows=rows)


@app.route("/todos/add", methods=["POST"])
def todos_add():
    body = request.form.get("content", "").strip()
    items = split_todo_items(body)
    if not items:
        flash("Todo cannot be empty.", "warning")
        return redirect(url_for("todos_page"))

    with db() as conn:
        capture_id = create_capture_record(
            conn,
            body,
            "todo",
            metadata={"origin": "todos_page", "item_count": len(items)},
        )
        for item in items:
            add_entry_result(
                conn,
                {
                    "type": "todo",
                    "content": item,
                    "raw": body,
                    "source_capture_id": capture_id,
                },
            )
        response = (
            f"Added {len(items)} todos"
            if len(items) > 1
            else f"Todo added: {items[0]}"
        )
        log_activity(
            "Todos page: add todo",
            response,
            "write",
            conn,
            metadata={"origin": "todos_page", "action": "add", "capture_id": capture_id, "count": len(items)},
        )
        conn.commit()
    flash(response, "success")
    return redirect(url_for("todos_page"))


@app.route("/todos/<int:tid>/toggle", methods=["POST"])
def todo_toggle(tid: int):
    with db() as conn:
        row = conn.execute("SELECT status FROM todos WHERE id = ?", (tid,)).fetchone()
        if row:
            new_status = "done" if row["status"] == "pending" else "pending"
            conn.execute("UPDATE todos SET status = ? WHERE id = ?", (new_status, tid))
            log_activity(
                f"Todos page: toggle todo #{tid}",
                f"Todo marked {new_status}",
                "write",
                conn,
                metadata={"origin": "todos_page", "action": "toggle", "todo_id": tid, "status": new_status},
            )
            conn.commit()
    return redirect(url_for("todos_page"))


@app.route("/todos/<int:tid>/delete", methods=["POST"])
def todo_delete(tid: int):
    with db() as conn:
        row = conn.execute(
            """
            SELECT id, content, source_capture_id
            FROM todos
            WHERE id = ?
            """,
            (tid,),
        ).fetchone()
        if not row:
            flash("Todo not found.", "warning")
            return redirect(url_for("todos_page"))
        conn.execute("DELETE FROM todos WHERE id = ?", (tid,))
        _cleanup_orphan_capture(conn, row["source_capture_id"])
        response = f"Deleted todo: {row['content']}"
        log_activity(
            f"Todos page: delete todo #{tid}",
            response,
            "write",
            conn,
            metadata={"origin": "todos_page", "action": "delete", "todo_id": tid},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("todos_page"))


@app.route("/todos/clear", methods=["POST"])
def todos_clear():
    with db() as conn:
        rows = conn.execute(
            "SELECT source_capture_id FROM todos"
        ).fetchall()
        if not rows:
            flash("No todos to clear.", "info")
            return redirect(url_for("todos_page"))
        capture_ids = {row["source_capture_id"] for row in rows if row["source_capture_id"]}
        count = len(rows)
        conn.execute("DELETE FROM todos")
        for capture_id in capture_ids:
            _cleanup_orphan_capture(conn, capture_id)
        response = f"Cleared {count} todo entr{'y' if count == 1 else 'ies'}"
        log_activity(
            "Todos page: clear all",
            response,
            "write",
            conn,
            metadata={"origin": "todos_page", "action": "clear", "count": count},
        )
        conn.commit()
    flash(response, "info")
    return redirect(url_for("todos_page"))


@app.route("/settings")
def settings_page():
    return render_template(
        "stub.html",
        title="Settings",
        message="DB backup/restore, model path - coming soon.",
    )


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("=" * 60)
        print(f"Warning: {DB_PATH} not found.")
        print("Run notebook_1_sqlite.ipynb first to create it.")
        print("=" * 60)
    else:
        ensure_activity_log_schema(DB_PATH)
        with db() as conn:
            pruned = prune_routing_memory(conn, days=90)
            conn.commit()
        if pruned:
            print(f"Pruned {pruned} stale routing-memory entries.")
        _start_runtime_warmup()
    app.run(debug=True, use_reloader=False, port=5000)
