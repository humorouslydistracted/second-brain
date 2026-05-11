package com.secondbrain.app.ui.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.LedgerBalance
import com.secondbrain.app.data.LedgerDao
import com.secondbrain.app.data.LedgerRow
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.ui.common.SectionHeader
import com.secondbrain.app.ui.common.backgroundFor
import com.secondbrain.app.ui.common.consumeOnLaunch
import com.secondbrain.app.ui.common.rememberHighlightState
import com.secondbrain.app.ui.common.renderTable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs

class LedgerViewModel : ViewModel() {
    data class S(
        val rows: List<LedgerRow> = emptyList(),
        val balances: List<LedgerBalance> = emptyList(),
        val total: Long = 0,
        val person: String = "",
        val amount: String = "",
        val direction: String = "gave",
        val note: String = "",
        val editingId: Long? = null,
        val editPerson: String = "",
        val editAmount: String = "",
        val editDirection: String = "gave",
        val editDate: String = "",
        val editNote: String = "",
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (rows, balances, n) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            Triple(LedgerDao.list(db), LedgerDao.balances(db), LedgerDao.count(db))
        }
        _s.update { it.copy(rows = rows, balances = balances, total = n) }
    }
    fun setPerson(v: String) = _s.update { it.copy(person = v) }
    fun setAmount(v: String) = _s.update { it.copy(amount = v) }
    fun setDirection(v: String) = _s.update { it.copy(direction = v) }
    fun setNote(v: String) = _s.update { it.copy(note = v) }

    fun add() = viewModelScope.launch {
        val p = _s.value.person.trim().ifBlank { return@launch }
        val a = _s.value.amount.toDoubleOrNull() ?: return@launch
        val dir = _s.value.direction
        val n = _s.value.note.trim().ifBlank { null }
        withContext(Dispatchers.IO) { LedgerDao.add(DatabaseHolder.get(), p, a, dir, n) }
        _s.update { it.copy(person = "", amount = "", note = "") }
        refresh()
        val dirText = if (dir == "gave") "gave ₹$a to ${p.replaceFirstChar { it.uppercase() }}"
                     else "received ₹$a from ${p.replaceFirstChar { it.uppercase() }}"
        logActivity("Added ledger entry", "Ledger: You $dirText", "ledger")
    }

    fun startEdit(row: LedgerRow) = _s.update {
        it.copy(editingId = row.id, editPerson = row.person, editAmount = row.amount.toString(),
            editDirection = row.direction,
            editDate = row.date ?: row.createdAt.take(10), editNote = row.note ?: "")
    }
    fun cancelEdit() = _s.update { it.copy(editingId = null) }
    fun setEditPerson(v: String) = _s.update { it.copy(editPerson = v) }
    fun setEditAmount(v: String) = _s.update { it.copy(editAmount = v) }
    fun setEditDirection(v: String) = _s.update { it.copy(editDirection = v) }
    fun setEditDate(v: String) = _s.update { it.copy(editDate = v) }
    fun setEditNote(v: String) = _s.update { it.copy(editNote = v) }

    fun saveEdit() = viewModelScope.launch {
        val id = _s.value.editingId ?: return@launch
        val p = _s.value.editPerson.trim().ifBlank { return@launch }
        val a = _s.value.editAmount.toDoubleOrNull() ?: return@launch
        val dir = _s.value.editDirection
        withContext(Dispatchers.IO) {
            LedgerDao.update(DatabaseHolder.get(), id, p, a, dir,
                _s.value.editDate.trim().ifBlank { null },
                _s.value.editNote.trim().ifBlank { null })
        }
        cancelEdit(); refresh()
        val dirText = if (dir == "gave") "you lent ₹$a to ${p.replaceFirstChar { it.uppercase() }}"
                     else "you borrowed ₹$a from ${p.replaceFirstChar { it.uppercase() }}"
        logActivity("Edited ledger entry",
            "Ledger updated: $dirText", "ledger")
    }

    fun delete(id: Long) = viewModelScope.launch {
        val row = _s.value.rows.firstOrNull { it.id == id }
        withContext(Dispatchers.IO) { LedgerDao.delete(DatabaseHolder.get(), id) }
        refresh()
        if (row != null) {
            val dirText = if (row.direction == "gave") "gave ₹${row.amount} to ${row.person.replaceFirstChar { it.uppercase() }}"
                         else "received ₹${row.amount} from ${row.person.replaceFirstChar { it.uppercase() }}"
            logActivity("Deleted ledger entry", "Deleted: You $dirText", "ledger")
        }
    }

    fun clearAll() = viewModelScope.launch {
        val count = _s.value.rows.size
        withContext(Dispatchers.IO) { LedgerDao.clearAll(DatabaseHolder.get()) }
        refresh()
        logActivity("Cleared ledger", "Cleared $count ledger entr${if (count == 1) "y" else "ies"}", "ledger")
    }

    private suspend fun logActivity(input: String, response: String, kind: String) {
        withContext(Dispatchers.IO) {
            ActivityLogDao.insert(DatabaseHolder.get(), input, response, kind, null)
        }
        AppStatusBus.emit(response)
    }
}

@Composable
fun LedgerScreen(vm: LedgerViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    val listState = rememberLazyListState()
    val highlight = rememberHighlightState()
    highlight.consumeOnLaunch(
        route = "ledger",
        listState = listState,
        scrollIndex = { id -> state.rows.indexOfFirst { it.id == id } },
    )
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "Ledger",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                val balanceTable = renderTable(
                    headers = listOf("PERSON", "BALANCE"),
                    rows = state.balances.map { listOf(it.person, "₹${it.balance}") },
                )
                val rowsTable = renderTable(
                    headers = listOf("DATE", "PERSON", "DIRECTION", "AMOUNT", "NOTE"),
                    rows = state.rows.map {
                        listOf(it.date ?: it.createdAt.take(10), it.person,
                            it.direction, "₹${it.amount}", it.note)
                    },
                )
                "BALANCES:\n$balanceTable\n\nENTRIES:\n$rowsTable"
            },
            onClearAll = { vm.clearAll() },
        )

        if (state.balances.isNotEmpty()) {
            Text("Balances", style = MaterialTheme.typography.titleSmall)
            state.balances.forEach { b ->
                val txt = when {
                    b.balance > 0 -> "${b.person.replaceFirstChar { it.uppercase() }} owes you ₹${b.balance}"
                    b.balance < 0 -> "You owe ${b.person.replaceFirstChar { it.uppercase() }} ₹${abs(b.balance)}"
                    else -> "${b.person.replaceFirstChar { it.uppercase() }} - settled"
                }
                Text(txt, style = MaterialTheme.typography.bodySmall)
            }
            HorizontalDivider()
        }

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(value = state.person, onValueChange = vm::setPerson,
                label = { Text("Person") }, modifier = Modifier.weight(2f), singleLine = true)
            OutlinedTextField(value = state.amount, onValueChange = vm::setAmount,
                label = { Text("Amount") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(selected = state.direction == "gave", onClick = { vm.setDirection("gave") },
                label = { Text("I gave") })
            FilterChip(selected = state.direction == "received", onClick = { vm.setDirection("received") },
                label = { Text("I received") })
            OutlinedTextField(value = state.note, onValueChange = vm::setNote,
                label = { Text("Note") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        Button(
            enabled = state.person.isNotBlank() && state.amount.toDoubleOrNull() != null,
            onClick = { vm.add() },
        ) { Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add") }

        HorizontalDivider()
        LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(state.rows, key = { it.id }) { r ->
                val rowBg = highlight.backgroundFor(r.id)
                if (state.editingId == r.id) {
                    Column(Modifier.fillMaxWidth().background(rowBg).padding(vertical = 4.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedTextField(value = state.editPerson, onValueChange = vm::setEditPerson,
                                label = { Text("Person") }, singleLine = true, modifier = Modifier.weight(2f))
                            OutlinedTextField(value = state.editAmount, onValueChange = vm::setEditAmount,
                                label = { Text("Amount") }, singleLine = true, modifier = Modifier.weight(1f))
                        }
                        Row(verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            FilterChip(selected = state.editDirection == "gave",
                                onClick = { vm.setEditDirection("gave") },
                                label = { Text("I lent") })
                            FilterChip(selected = state.editDirection == "received",
                                onClick = { vm.setEditDirection("received") },
                                label = { Text("I owe") })
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedTextField(value = state.editDate, onValueChange = vm::setEditDate,
                                label = { Text("Date (yyyy-mm-dd)") }, singleLine = true, modifier = Modifier.weight(1f))
                            OutlinedTextField(value = state.editNote, onValueChange = vm::setEditNote,
                                label = { Text("Note") }, singleLine = true, modifier = Modifier.weight(1f))
                        }
                        Row {
                            TextButton(onClick = { vm.saveEdit() }) { Text("Save") }
                            TextButton(onClick = { vm.cancelEdit() }) { Text("Cancel") }
                        }
                    }
                } else {
                    Row(Modifier.fillMaxWidth().background(rowBg).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(r.date ?: r.createdAt.take(10), style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.width(96.dp))
                        Column(Modifier.weight(1f)) {
                            val entryText = if (r.direction == "gave")
                                "You gave ₹${r.amount} to ${r.person.replaceFirstChar { it.uppercase() }}"
                            else
                                "You received ₹${r.amount} from ${r.person.replaceFirstChar { it.uppercase() }}"
                            Text(entryText, style = MaterialTheme.typography.bodyMedium)
                            if (!r.note.isNullOrBlank())
                                Text(r.note, style = MaterialTheme.typography.labelSmall)
                        }
                        IconButton(onClick = { vm.startEdit(r) }) {
                            Icon(Icons.Filled.Edit, contentDescription = "Edit",
                                modifier = Modifier.size(18.dp))
                        }
                        IconButton(onClick = { vm.delete(r.id) }) {
                            Icon(Icons.Filled.Delete, contentDescription = null)
                        }
                    }
                }
                HorizontalDivider()
            }
        }
    }
}
