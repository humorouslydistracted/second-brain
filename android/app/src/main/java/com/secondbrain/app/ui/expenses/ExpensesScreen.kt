package com.secondbrain.app.ui.expenses

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
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.ExpenseRow
import com.secondbrain.app.data.ExpensesDao
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

class ExpensesViewModel : ViewModel() {
    data class S(
        val rows: List<ExpenseRow> = emptyList(),
        val total: Long = 0,
        val amount: String = "",
        val description: String = "",
        val group: String = "",
        val editingId: Long? = null,
        val editAmount: String = "",
        val editDescription: String = "",
        val editDate: String = "",
        val editGroup: String = "",
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (rows, total) = withContext(Dispatchers.IO) {
            ExpensesDao.list(DatabaseHolder.get()) to ExpensesDao.count(DatabaseHolder.get())
        }
        _s.update { it.copy(rows = rows, total = total) }
    }
    fun setAmount(v: String) = _s.update { it.copy(amount = v) }
    fun setDescription(v: String) = _s.update { it.copy(description = v) }
    fun setGroup(v: String) = _s.update { it.copy(group = v) }

    fun add() = viewModelScope.launch {
        val a = _s.value.amount.toDoubleOrNull() ?: return@launch
        val d = _s.value.description.trim().ifBlank { return@launch }
        val g = _s.value.group.trim().ifBlank { null }
        withContext(Dispatchers.IO) { ExpensesDao.add(DatabaseHolder.get(), a, d, group = g) }
        _s.update { it.copy(amount = "", description = "", group = "") }
        refresh()
        logActivity("Added expense", "Expense added: ₹$a $d", "expense")
    }

    fun startEdit(row: ExpenseRow) = _s.update {
        it.copy(editingId = row.id, editAmount = row.amount.toString(),
            editDescription = row.description, editDate = row.date ?: row.createdAt.take(10),
            editGroup = row.groupName ?: "")
    }
    fun cancelEdit() = _s.update { it.copy(editingId = null) }
    fun setEditAmount(v: String) = _s.update { it.copy(editAmount = v) }
    fun setEditDescription(v: String) = _s.update { it.copy(editDescription = v) }
    fun setEditDate(v: String) = _s.update { it.copy(editDate = v) }
    fun setEditGroup(v: String) = _s.update { it.copy(editGroup = v) }

    fun saveEdit() = viewModelScope.launch {
        val id = _s.value.editingId ?: return@launch
        val a = _s.value.editAmount.toDoubleOrNull() ?: return@launch
        val d = _s.value.editDescription.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) {
            ExpensesDao.update(DatabaseHolder.get(), id, a, d,
                _s.value.editDate.trim().ifBlank { null },
                _s.value.editGroup.trim().ifBlank { null })
        }
        cancelEdit(); refresh()
        logActivity("Edited expense", "Updated expense: ₹$a $d", "expense")
    }

    fun delete(id: Long) = viewModelScope.launch {
        val row = _s.value.rows.firstOrNull { it.id == id }
        withContext(Dispatchers.IO) { ExpensesDao.delete(DatabaseHolder.get(), id) }
        refresh()
        if (row != null)
            logActivity("Deleted expense", "Deleted: ₹${row.amount} ${row.description.take(50)}", "expense")
    }

    fun clearAll() = viewModelScope.launch {
        val count = _s.value.rows.size
        withContext(Dispatchers.IO) { ExpensesDao.clearAll(DatabaseHolder.get()) }
        refresh()
        logActivity("Cleared expenses", "Cleared $count expense${if (count == 1) "" else "s"}", "expense")
    }

    private suspend fun logActivity(input: String, response: String, kind: String) {
        withContext(Dispatchers.IO) {
            ActivityLogDao.insert(DatabaseHolder.get(), input, response, kind, null)
        }
        AppStatusBus.emit(response)
    }
}

@Composable
fun ExpensesScreen(vm: ExpensesViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "Expenses",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                renderTable(
                    headers = listOf("DATE", "AMOUNT", "DESCRIPTION", "GROUP"),
                    rows = state.rows.map {
                        listOf(it.date ?: it.createdAt.take(10),
                            "₹${it.amount}", it.description, it.groupName)
                    },
                )
            },
            onClearAll = { vm.clearAll() },
        )

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value = state.amount, onValueChange = vm::setAmount,
                label = { Text("Amount") }, modifier = Modifier.weight(1f), singleLine = true)
            OutlinedTextField(value = state.description, onValueChange = vm::setDescription,
                label = { Text("Description") }, modifier = Modifier.weight(2f), singleLine = true)
            OutlinedTextField(value = state.group, onValueChange = vm::setGroup,
                label = { Text("Group") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        Button(
            enabled = state.amount.toDoubleOrNull() != null && state.description.isNotBlank(),
            onClick = { vm.add() },
        ) { Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add") }

        HorizontalDivider()

        val grouped = remember(state.rows) {
            state.rows
                .groupBy { it.date ?: it.createdAt.take(10) }
                .entries.sortedByDescending { it.key }
        }

        // Compute the flat LazyList index for a row id (header + items per group).
        val listState = rememberLazyListState()
        val highlight = rememberHighlightState()
        highlight.consumeOnLaunch(
            route = "expenses",
            listState = listState,
            scrollIndex = { id ->
                var i = 0
                var found = -1
                loop@ for ((_, items) in grouped) {
                    i++ // header
                    for (it in items) {
                        if (it.id == id) { found = i; break@loop }
                        i++
                    }
                }
                found
            },
        )

        LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(4.dp)) {
            grouped.forEach { (date, items) ->
                val dayTotal = items.sumOf { it.amount }
                item(key = "hdr-$date") {
                    Row(
                        Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(date, style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.weight(1f))
                        Text("₹${formatAmount(dayTotal)}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary)
                    }
                    HorizontalDivider()
                }
                items(items, key = { it.id }) { r ->
                    val rowBg = highlight.backgroundFor(r.id)
                    if (state.editingId == r.id) {
                        Column(Modifier.fillMaxWidth().background(rowBg).padding(vertical = 4.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                OutlinedTextField(value = state.editAmount, onValueChange = vm::setEditAmount,
                                    label = { Text("Amount") }, singleLine = true, modifier = Modifier.weight(1f))
                                OutlinedTextField(value = state.editDescription, onValueChange = vm::setEditDescription,
                                    label = { Text("Description") }, singleLine = true, modifier = Modifier.weight(2f))
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                OutlinedTextField(value = state.editDate, onValueChange = vm::setEditDate,
                                    label = { Text("Date (yyyy-mm-dd)") }, singleLine = true, modifier = Modifier.weight(1f))
                                OutlinedTextField(value = state.editGroup, onValueChange = vm::setEditGroup,
                                    label = { Text("Group") }, singleLine = true, modifier = Modifier.weight(1f))
                            }
                            Row {
                                TextButton(onClick = { vm.saveEdit() }) { Text("Save") }
                                TextButton(onClick = { vm.cancelEdit() }) { Text("Cancel") }
                            }
                        }
                    } else {
                        Row(Modifier.fillMaxWidth().background(rowBg).padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("₹${formatAmount(r.amount)}", style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.width(80.dp))
                            Column(Modifier.weight(1f)) {
                                Text(r.description, style = MaterialTheme.typography.bodyMedium)
                                if (!r.groupName.isNullOrBlank())
                                    Text(r.groupName, style = MaterialTheme.typography.labelSmall)
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
}

private fun formatAmount(v: Double): String {
    val whole = v.toLong()
    return if (kotlin.math.abs(v - whole) < 0.01) "%,d".format(whole) else "%,.2f".format(v)
}
