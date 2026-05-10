package com.secondbrain.app.ui.home

import com.secondbrain.app.data.AppDatabase
import com.secondbrain.app.data.DatabaseHolder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * 2026-05-09: V0 of the planned "ambient nudges" feature.
 *
 * Computes a list of natural-language one-liners from the current DB state:
 *   - stale weights ("Jeevi last weighed 5 days ago")
 *   - long-pending buy items ("salt has been on your buy list for 12 days")
 *   - aging open ledger balances ("Maddy still owes you ₹5,000")
 *   - pending todos backlog ("3 todos from last week still open")
 *   - this-month expense + delta vs last month
 *   - notes + people counts
 *
 * V0 is pure SQL — no LLM call. Strings are templated. The planned V1 (see
 * `~/.claude/.../memory/ambient_nudges_design.md`) adds an LLM polish pass
 * over the same facts plus an LLM-driven note callout generator with an
 * exclusion-list prompt. V0 ships now so the rotating top-bar surface is
 * functional immediately; V1 lands after the re-finetune validates.
 *
 * Caller is HomeViewModel — recomputes on launch, on AppStatusBus events
 * (after every successful write, since data has changed), and on tile
 * refresh. Display side rotates among the returned facts every ~8s.
 */
object AmbientFacts {

    /**
     * Compute a fresh list of facts from the DB. Called from HomeViewModel
     * on a coroutine — must run on Dispatchers.IO.
     *
     * Returns at most ~12 facts to avoid the rotation feeling stale within
     * a single rotation cycle. If the DB is mostly empty, returns a small
     * onboarding list so the top bar isn't blank.
     */
    suspend fun compute(): List<String> = withContext(Dispatchers.IO) {
        val db = DatabaseHolder.get()
        val out = mutableListOf<String>()
        runCatching { out += staleWeights(db) }
        runCatching { out += oldBuyItems(db) }
        runCatching { out += openLedger(db) }
        runCatching { out += overdueTodoContent(db) }
        runCatching { out += expenseDelta(db) }
        runCatching { out += notesFact(db) }
        out.removeAll { it.isBlank() }
        if (out.isEmpty()) {
            out += "Add an expense, todo, or weight — your second brain starts here."
        }
        out.take(14)
    }

    /**
     * Time-aware contextual summary — one composed sentence that is genuinely
     * different in the morning vs afternoon vs evening because it pulls
     * different data for each slot. Refreshed every 15 min so it updates as
     * the day progresses and as you add data.
     *
     *   Morning  (5–11): today's pending todos + open buy items
     *   Afternoon(12–17): today's spend + total pending todos
     *   Evening  (18+) : this-month spend + overdue todos
     */
    suspend fun buildContextualSummary(): String = withContext(Dispatchers.IO) {
        val db = DatabaseHolder.get()
        val hour = java.time.LocalTime.now().hour
        val today = java.time.LocalDate.now().toString()
        val month = today.take(7)
        runCatching {
            val parts = mutableListOf<String>()
            when {
                hour in 5..11 -> {
                    val totalPending = com.secondbrain.app.data.TodosDao.pendingCount(db)
                    if (totalPending > 0) parts += "$totalPending todo${if (totalPending == 1L) "" else "s"} open"
                    val buyOpen = db.readableDatabase.rawQuery(
                        "SELECT COUNT(*) FROM buy_items WHERE status='open'", null,
                    ).use { c -> if (c.moveToFirst()) c.getLong(0) else 0L }
                    if (buyOpen > 0) parts += "$buyOpen item${if (buyOpen == 1L) "" else "s"} to buy"
                }
                hour in 12..17 -> {
                    val todaySpend = db.readableDatabase.rawQuery(
                        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE COALESCE(date,substr(created_at,1,10))=?",
                        arrayOf(today),
                    ).use { c -> if (c.moveToFirst()) c.getDouble(0) else 0.0 }
                    if (todaySpend > 0) parts += "₹${formatRupees(todaySpend)} spent today"
                    val pending = com.secondbrain.app.data.TodosDao.pendingCount(db)
                    if (pending > 0) parts += "$pending todo${if (pending == 1L) "" else "s"} still open"
                }
                else -> {
                    val monthSpend = com.secondbrain.app.data.ExpensesDao.monthTotal(db, month)
                    if (monthSpend > 0) parts += "₹${formatRupees(monthSpend)} this month"
                    val overdueCount = db.readableDatabase.rawQuery(
                        "SELECT COUNT(*) FROM todos WHERE status='pending' AND COALESCE(date,substr(created_at,1,10)) < date('now','-1 days')",
                        null,
                    ).use { c -> if (c.moveToFirst()) c.getLong(0) else 0L }
                    if (overdueCount > 0) parts += "$overdueCount overdue todo${if (overdueCount == 1L) "" else "s"}"
                    val topLedger = db.readableDatabase.rawQuery(
                        "SELECT person, balance FROM ledger_balance WHERE balance != 0 ORDER BY ABS(balance) DESC LIMIT 1",
                        null,
                    ).use { c -> if (c.moveToFirst()) Pair(c.getString(0), c.getDouble(1)) else null }
                    if (topLedger != null) {
                        val p = topLedger.first.replaceFirstChar { it.uppercase() }
                        val bal = topLedger.second
                        parts += if (bal > 0) "$p owes you ₹${formatRupees(bal)}"
                                 else "You owe $p ₹${formatRupees(-bal)}"
                    }
                }
            }
            if (parts.isEmpty()) "All caught up!" else parts.joinToString(" · ")
        }.getOrElse { "" }
    }

    private fun staleWeights(db: AppDatabase): List<String> {
        // People whose last weight log is >30 days old.
        return db.readableDatabase.rawQuery(
            """
            SELECT person, CAST(julianday('now') - julianday(MAX(date)) AS INTEGER) AS days_ago
            FROM weights
            GROUP BY person
            HAVING days_ago > 30
            ORDER BY days_ago DESC
            LIMIT 3
            """.trimIndent(), null,
        ).use { c ->
            val rows = mutableListOf<String>()
            while (c.moveToNext()) {
                val person = c.getString(0).replaceFirstChar { it.uppercase() }
                val days = c.getInt(1)
                rows += "$person was last weighed $days days ago"
            }
            rows
        }
    }

    private fun oldBuyItems(db: AppDatabase): List<String> {
        // Open buy items older than 7 days.
        return db.readableDatabase.rawQuery(
            """
            SELECT item_text,
                   CAST(julianday('now') - julianday(COALESCE(date, substr(created_at,1,10))) AS INTEGER) AS days_old
            FROM buy_items
            WHERE status = 'open' AND days_old > 7
            ORDER BY days_old DESC
            LIMIT 3
            """.trimIndent(), null,
        ).use { c ->
            val rows = mutableListOf<String>()
            while (c.moveToNext()) {
                val item = c.getString(0)
                val days = c.getInt(1)
                rows += "$item has been on your buy list for $days days"
            }
            rows
        }
    }

    private fun openLedger(db: AppDatabase): List<String> {
        return db.readableDatabase.rawQuery(
            "SELECT person, balance FROM ledger_balance WHERE balance != 0 ORDER BY ABS(balance) DESC LIMIT 3",
            null,
        ).use { c ->
            val rows = mutableListOf<String>()
            while (c.moveToNext()) {
                val person = c.getString(0).replaceFirstChar { it.uppercase() }
                val balance = c.getDouble(1)
                rows += if (balance > 0)
                    "$person still owes you ₹${formatRupees(balance)}"
                else
                    "You still owe $person ₹${formatRupees(-balance)}"
            }
            rows
        }
    }

    private fun overdueTodoContent(db: AppDatabase): List<String> {
        // Show the actual content of the oldest overdue pending todo (>3 days).
        // One item max — more would be noise. The goal is a concrete reminder
        // of something specific, not a count (count is already in the tile).
        return db.readableDatabase.rawQuery(
            """
            SELECT content,
                   CAST(julianday('now') - julianday(COALESCE(date, substr(created_at,1,10))) AS INTEGER) AS days_old
            FROM todos
            WHERE status = 'pending'
              AND COALESCE(date, substr(created_at,1,10)) < date('now','-3 days')
            ORDER BY days_old DESC
            LIMIT 1
            """.trimIndent(), null,
        ).use { c ->
            if (c.moveToFirst()) {
                val content = c.getString(0).take(60)
                val days = c.getInt(1)
                listOf("Still pending ($days days): $content")
            } else emptyList()
        }
    }

    private fun notesFact(db: AppDatabase): List<String> {
        val count = db.readableDatabase.rawQuery("SELECT COUNT(*) FROM notes", null)
            .use { c -> if (c.moveToFirst()) c.getLong(0) else 0L }
        return if (count > 0) listOf("$count note${if (count == 1L) "" else "s"} saved") else emptyList()
    }

    private fun expenseDelta(db: AppDatabase): List<String> {
        // Compare this month's spending to last month. More useful than just
        // showing the total (which is already on the expense tile).
        val today = java.time.LocalDate.now()
        val thisMonth = today.toString().take(7)
        val lastMonth = today.minusMonths(1).toString().take(7)
        val thisTotal = com.secondbrain.app.data.ExpensesDao.monthTotal(db, thisMonth)
        val lastTotal = com.secondbrain.app.data.ExpensesDao.monthTotal(db, lastMonth)
        if (thisTotal <= 0.0 && lastTotal <= 0.0) return emptyList()
        if (lastTotal <= 0.0) return emptyList()  // no last-month baseline to compare
        val delta = thisTotal - lastTotal
        val sign = if (delta >= 0) "+" else "-"
        val abs = kotlin.math.abs(delta)
        return listOf("₹${formatRupees(abs)} ${if (delta >= 0) "more" else "less"} than last month ($sign₹${formatRupees(abs)})")
    }

    private fun formatRupees(v: Double): String {
        val whole = v.toLong()
        return if (kotlin.math.abs(v - whole) < 0.01) "%,d".format(whole)
               else "%,.2f".format(v)
    }
}
