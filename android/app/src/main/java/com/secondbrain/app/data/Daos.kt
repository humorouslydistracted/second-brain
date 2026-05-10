package com.secondbrain.app.data

import android.content.ContentValues
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private fun today(): String = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
private fun monthOf(date: String): String = date.take(7)

// ---------------------------------------------------------------------------
// Notes (real user notes only — input_kind='note', structured_type='note')
// ---------------------------------------------------------------------------

data class NoteRow(val id: Long, val content: String, val createdAt: String)

/** Result of a per-day note save: tells the caller what happened so undo
 *  + embedding-refresh can be wired up consistently across surfaces. */
data class NoteSaveResult(
    val id: Long,
    val finalContent: String,
    val previousContent: String?,
    val wasInsert: Boolean,
)

object NotesDao {
    fun list(db: AppDatabase, limit: Int = 200): List<NoteRow> =
        db.readableDatabase.rawQuery(
            """SELECT id, content, created_at FROM notes
               WHERE input_kind='note' AND structured_type='note'
               ORDER BY id DESC LIMIT ?""",
            arrayOf(limit.toString()),
        ).consume { c -> NoteRow(c.getLong(0), c.string("content"), c.string("created_at")) }

    fun count(db: AppDatabase): Long = countWhere(
        db, "notes", "input_kind='note' AND structured_type='note'")

    /** Single source of truth for "save a real user note".
     *  Same-day notes append into one row prefixed `[HH:MM:SS]`, newest at top.
     *  Used by both Home (Orchestrator.saveNote) and the Notes page so the two
     *  surfaces can't drift. */
    fun addForToday(db: AppDatabase, content: String): NoteSaveResult {
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val now = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        val existing = db.readableDatabase.rawQuery(
            """SELECT id, content FROM notes
               WHERE input_kind='note' AND structured_type='note'
                 AND substr(created_at,1,10) = ?
               ORDER BY id DESC LIMIT 1""",
            arrayOf(today),
        ).use { c -> if (c.moveToFirst()) c.getLong(0) to c.getString(1) else null }

        return if (existing != null) {
            val (existingId, existingText) = existing
            val finalContent = "[$now] " + content + "\n\n" + existingText
            db.writableDatabase.update(
                "notes",
                ContentValues().apply { put("content", finalContent) },
                "id=?", arrayOf(existingId.toString()),
            )
            NoteSaveResult(existingId, finalContent, existingText, wasInsert = false)
        } else {
            val finalContent = "[$now] " + content
            val id = db.writableDatabase.insert("notes", null, ContentValues().apply {
                put("content", finalContent); put("input_kind", "note"); put("structured_type", "note")
            })
            NoteSaveResult(id, finalContent, null, wasInsert = true)
        }
    }

    fun update(db: AppDatabase, id: Long, content: String): Int =
        db.writableDatabase.update("notes", ContentValues().apply { put("content", content) },
            "id=?", arrayOf(id.toString()))

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("notes", "id=?", arrayOf(id.toString()))

    fun clearAll(db: AppDatabase): Int =
        db.writableDatabase.delete("notes", "input_kind='note' AND structured_type='note'", null)
}

// ---------------------------------------------------------------------------
// Expenses
// ---------------------------------------------------------------------------

data class ExpenseRow(
    val id: Long, val amount: Double, val description: String,
    val date: String?, val groupName: String?, val createdAt: String,
)

object ExpensesDao {
    fun list(db: AppDatabase, limit: Int = 500): List<ExpenseRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, amount, description, date, group_name, created_at FROM expenses " +
                "ORDER BY COALESCE(date, substr(created_at,1,10)) DESC, id DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).consume { c ->
            ExpenseRow(c.getLong(0), c.getDouble(1), c.string("description"),
                c.stringOrNull("date"), c.stringOrNull("group_name"), c.string("created_at"))
        }
    fun count(db: AppDatabase): Long = countWhere(db, "expenses")

    fun add(db: AppDatabase, amount: Double, description: String, date: String? = null, group: String? = null): Long {
        val d = date ?: today()
        return db.writableDatabase.insert("expenses", null, ContentValues().apply {
            put("amount", amount); put("description", description.trim())
            put("date", d); put("month", monthOf(d))
            put("group_name", group?.trim()?.lowercase()); put("raw_note", description.trim())
        })
    }
    fun update(db: AppDatabase, id: Long, amount: Double, description: String, date: String?, group: String?): Int {
        val d = date ?: today()
        return db.writableDatabase.update("expenses", ContentValues().apply {
            put("amount", amount); put("description", description.trim())
            put("date", d); put("month", monthOf(d))
            put("group_name", group?.trim()?.lowercase())
        }, "id=?", arrayOf(id.toString()))
    }

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("expenses", "id=?", arrayOf(id.toString()))
    fun clearAll(db: AppDatabase): Int = db.writableDatabase.delete("expenses", null, null)

    fun monthTotal(db: AppDatabase, yyyymm: String): Double =
        db.readableDatabase.rawQuery(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE month=?",
            arrayOf(yyyymm),
        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else 0.0 }
}

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

data class LedgerRow(
    val id: Long, val person: String, val direction: String,
    val amount: Double, val note: String?, val date: String?, val createdAt: String,
)
data class LedgerBalance(val person: String, val balance: Double)

object LedgerDao {
    fun list(db: AppDatabase, limit: Int = 500): List<LedgerRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, person, direction, amount, note, date, created_at FROM ledger " +
                "ORDER BY COALESCE(date, substr(created_at,1,10)) DESC, id DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).consume { c ->
            LedgerRow(c.getLong(0), c.string("person"), c.string("direction"),
                c.getDouble(3), c.stringOrNull("note"), c.stringOrNull("date"),
                c.string("created_at"))
        }
    fun count(db: AppDatabase): Long = countWhere(db, "ledger")

    fun balances(db: AppDatabase): List<LedgerBalance> =
        db.readableDatabase.rawQuery(
            "SELECT person, balance FROM ledger_balance ORDER BY ABS(balance) DESC, person", null,
        ).consume { c -> LedgerBalance(c.string("person"), c.getDouble(1)) }

    fun add(db: AppDatabase, person: String, amount: Double, direction: String, note: String? = null): Long =
        db.writableDatabase.insert("ledger", null, ContentValues().apply {
            put("person", person.lowercase().trim()); put("amount", amount)
            put("direction", direction); put("note", note); put("date", today())
        })

    fun update(db: AppDatabase, id: Long, person: String, amount: Double, date: String?, note: String?): Int =
        db.writableDatabase.update("ledger", ContentValues().apply {
            put("person", person.lowercase().trim()); put("amount", amount)
            put("date", date ?: today()); put("note", note)
        }, "id=?", arrayOf(id.toString()))

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("ledger", "id=?", arrayOf(id.toString()))
    fun clearAll(db: AppDatabase): Int = db.writableDatabase.delete("ledger", null, null)
}

// ---------------------------------------------------------------------------
// Weights
// ---------------------------------------------------------------------------

data class WeightRow(
    val id: Long, val person: String, val weight: Double,
    val date: String, val note: String?, val createdAt: String,
)

object WeightsDao {
    fun list(db: AppDatabase, limit: Int = 500): List<WeightRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, person, weight, date, note, created_at FROM weights " +
                "ORDER BY date DESC, id DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).consume { c ->
            WeightRow(c.getLong(0), c.string("person"), c.getDouble(2),
                c.string("date"), c.stringOrNull("note"), c.string("created_at"))
        }
    fun count(db: AppDatabase): Long = countWhere(db, "weights")

    fun latestPerPerson(db: AppDatabase): List<WeightRow> =
        db.readableDatabase.rawQuery(
            """SELECT w1.id, w1.person, w1.weight, w1.date, w1.note, w1.created_at
               FROM weights w1 WHERE w1.id = (
                 SELECT w2.id FROM weights w2 WHERE w2.person=w1.person
                 ORDER BY date DESC, id DESC LIMIT 1
               ) ORDER BY w1.person""", null,
        ).consume { c ->
            WeightRow(c.getLong(0), c.string("person"), c.getDouble(2),
                c.string("date"), c.stringOrNull("note"), c.string("created_at"))
        }

    fun add(db: AppDatabase, person: String, weight: Double, note: String? = null): Long =
        db.writableDatabase.insert("weights", null, ContentValues().apply {
            put("person", person.lowercase().trim()); put("weight", weight)
            put("date", today()); put("note", note)
        })

    fun update(db: AppDatabase, id: Long, person: String, weight: Double, date: String, note: String?): Int =
        db.writableDatabase.update("weights", ContentValues().apply {
            put("person", person.lowercase().trim()); put("weight", weight)
            put("date", date); put("note", note)
        }, "id=?", arrayOf(id.toString()))

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("weights", "id=?", arrayOf(id.toString()))
    fun clearAll(db: AppDatabase): Int = db.writableDatabase.delete("weights", null, null)
}

// ---------------------------------------------------------------------------
// Todos
// ---------------------------------------------------------------------------

data class TodoRow(
    val id: Long, val content: String, val status: String,
    val date: String?, val createdAt: String,
)

object TodosDao {
    fun list(db: AppDatabase, limit: Int = 500): List<TodoRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, content, status, date, created_at FROM todos " +
                "ORDER BY (CASE WHEN status='pending' THEN 0 ELSE 1 END), " +
                "COALESCE(date, substr(created_at,1,10)) DESC, id DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).consume { c ->
            TodoRow(c.getLong(0), c.string("content"), c.string("status"),
                c.stringOrNull("date"), c.string("created_at"))
        }
    fun count(db: AppDatabase): Long = countWhere(db, "todos")
    fun pendingCount(db: AppDatabase): Long = countWhere(db, "todos", "status='pending'")

    fun add(db: AppDatabase, content: String, date: String? = null): Long =
        db.writableDatabase.insert("todos", null, ContentValues().apply {
            put("content", content.trim()); put("date", date)
            put("status", "pending")
        })

    fun setStatus(db: AppDatabase, id: Long, status: String): Int =
        db.writableDatabase.update("todos", ContentValues().apply { put("status", status) },
            "id=?", arrayOf(id.toString()))

    fun update(db: AppDatabase, id: Long, content: String): Int =
        db.writableDatabase.update("todos", ContentValues().apply { put("content", content.trim()) },
            "id=?", arrayOf(id.toString()))

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("todos", "id=?", arrayOf(id.toString()))
    fun clearAll(db: AppDatabase): Int = db.writableDatabase.delete("todos", null, null)
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------

data class PersonRow(val id: Long, val name: String, val createdAt: String)

object PeopleDao {
    fun list(db: AppDatabase): List<PersonRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, name, created_at FROM persons ORDER BY name", null,
        ).consume { c -> PersonRow(c.getLong(0), c.string("name"), c.string("created_at")) }
    fun count(db: AppDatabase): Long = countWhere(db, "persons")

    fun add(db: AppDatabase, name: String): Long =
        db.writableDatabase.insertWithOnConflict(
            "persons", null, ContentValues().apply { put("name", name.lowercase().trim()) },
            android.database.sqlite.SQLiteDatabase.CONFLICT_IGNORE)

    fun rename(db: AppDatabase, oldName: String, newName: String): Int {
        val w = db.writableDatabase
        val o = oldName.lowercase().trim(); val n = newName.lowercase().trim()
        w.beginTransaction()
        try {
            val r = w.update("persons", ContentValues().apply { put("name", n) },
                "name=?", arrayOf(o))
            // Cascade: ledger.person + weights.person
            w.update("ledger",  ContentValues().apply { put("person", n) },
                "person=?", arrayOf(o))
            w.update("weights", ContentValues().apply { put("person", n) },
                "person=?", arrayOf(o))
            w.setTransactionSuccessful()
            return r
        } finally { w.endTransaction() }
    }

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("persons", "id=?", arrayOf(id.toString()))
}

// ---------------------------------------------------------------------------
// Buy items (read-only here; orchestrator handles writes)
// ---------------------------------------------------------------------------

data class BuyRow(
    val id: Long, val itemText: String, val quantityText: String?, val unitText: String?,
    val status: String, val date: String?, val createdAt: String,
)

object BuyDao {
    fun list(db: AppDatabase, limit: Int = 500): List<BuyRow> =
        db.readableDatabase.rawQuery(
            "SELECT id, item_text, quantity_text, unit_text, status, date, created_at " +
                "FROM buy_items ORDER BY (CASE WHEN status='open' THEN 0 ELSE 1 END), " +
                "COALESCE(date, substr(created_at,1,10)) DESC, id DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).consume { c ->
            BuyRow(c.getLong(0), c.string("item_text"),
                c.stringOrNull("quantity_text"), c.stringOrNull("unit_text"),
                c.string("status"), c.stringOrNull("date"), c.string("created_at"))
        }
    fun count(db: AppDatabase): Long = countWhere(db, "buy_items")
    fun setStatus(db: AppDatabase, id: Long, status: String): Int =
        db.writableDatabase.update("buy_items", ContentValues().apply { put("status", status) },
            "id=?", arrayOf(id.toString()))
    fun update(db: AppDatabase, id: Long, itemText: String, qty: String?, unit: String?): Int =
        db.writableDatabase.update("buy_items", ContentValues().apply {
            put("item_text", itemText.trim())
            if (!qty.isNullOrBlank()) put("quantity_text", qty.trim()) else putNull("quantity_text")
            if (!unit.isNullOrBlank()) put("unit_text", unit.trim()) else putNull("unit_text")
        }, "id=?", arrayOf(id.toString()))

    fun delete(db: AppDatabase, id: Long): Int =
        db.writableDatabase.delete("buy_items", "id=?", arrayOf(id.toString()))
    fun clearAll(db: AppDatabase): Int = db.writableDatabase.delete("buy_items", null, null)
}

// ---------------------------------------------------------------------------

private fun countWhere(db: AppDatabase, table: String, where: String? = null): Long {
    val sql = if (where == null) "SELECT COUNT(*) FROM $table"
              else "SELECT COUNT(*) FROM $table WHERE $where"
    return db.readableDatabase.rawQuery(sql, null).use {
        if (it.moveToFirst()) it.getLong(0) else 0L
    }
}
