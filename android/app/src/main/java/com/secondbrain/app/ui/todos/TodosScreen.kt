package com.secondbrain.app.ui.todos

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.TodoRow
import com.secondbrain.app.data.TodosDao
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.ui.common.DateGroupedChecklist
import com.secondbrain.app.ui.common.DatedChecklistItem
import com.secondbrain.app.ui.common.SectionHeader
import com.secondbrain.app.ui.common.renderTable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class TodosViewModel : ViewModel() {
    data class S(
        val rows: List<TodoRow> = emptyList(),
        val total: Long = 0,
        val pending: Long = 0,
        val composing: String = "",
        val editingId: Long? = null,
        val editContent: String = "",
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (rows, total, pending) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            Triple(TodosDao.list(db), TodosDao.count(db), TodosDao.pendingCount(db))
        }
        _s.update { it.copy(rows = rows, total = total, pending = pending) }
    }

    fun setCompose(v: String) = _s.update { it.copy(composing = v) }

    fun add() = viewModelScope.launch {
        val text = _s.value.composing.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) { TodosDao.add(DatabaseHolder.get(), text) }
        _s.update { it.copy(composing = "") }
        refresh()
        logActivity("Added todo", "Todo added: ${text.take(60)}", "todo")
    }

    fun toggle(row: TodoRow) = viewModelScope.launch {
        val next = if (row.status == "pending") "done" else "pending"
        withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            TodosDao.setStatus(db, row.id, next)
            ActivityLogDao.insert(db, "Todo ${next}", "Marked $next: ${row.content.take(60)}", "todo", null)
        }
        refresh()
        AppStatusBus.refresh()
    }

    fun startEdit(row: TodoRow) = _s.update { it.copy(editingId = row.id, editContent = row.content) }
    fun cancelEdit() = _s.update { it.copy(editingId = null, editContent = "") }
    fun setEditContent(v: String) = _s.update { it.copy(editContent = v) }

    fun saveEdit() = viewModelScope.launch {
        val id = _s.value.editingId ?: return@launch
        val newText = _s.value.editContent.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) { TodosDao.update(DatabaseHolder.get(), id, newText) }
        _s.update { it.copy(editingId = null, editContent = "") }
        refresh()
        logActivity("Edited todo", "Updated: ${newText.take(60)}", "todo")
    }

    fun delete(id: Long) = viewModelScope.launch {
        val row = _s.value.rows.firstOrNull { it.id == id }
        withContext(Dispatchers.IO) { TodosDao.delete(DatabaseHolder.get(), id) }
        refresh()
        if (row != null) logActivity("Deleted todo", "Deleted: ${row.content.take(60)}", "todo")
    }

    fun clearAll() = viewModelScope.launch {
        val count = _s.value.rows.size
        withContext(Dispatchers.IO) { TodosDao.clearAll(DatabaseHolder.get()) }
        refresh()
        logActivity("Cleared todos", "Cleared $count todo${if (count == 1) "" else "s"}", "todo")
    }

    private suspend fun logActivity(input: String, response: String, kind: String) {
        withContext(Dispatchers.IO) {
            ActivityLogDao.insert(DatabaseHolder.get(), input, response, kind, null)
        }
        AppStatusBus.emit(response)
    }
}

private data class TodoChecklistItem(val row: TodoRow) : DatedChecklistItem {
    override val id: Long = row.id
    override val dateKey: String = row.date ?: row.createdAt.take(10)
}

@Composable
fun TodosScreen(vm: TodosViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "Todos (${state.pending} pending)",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                renderTable(
                    headers = listOf("STATUS", "DATE", "CONTENT"),
                    rows = state.rows.map { listOf(it.status, it.date ?: it.createdAt.take(10), it.content) },
                )
            },
            onClearAll = { vm.clearAll() },
        )

        OutlinedTextField(value = state.composing, onValueChange = vm::setCompose,
            label = { Text("New todo") }, modifier = Modifier.fillMaxWidth(), maxLines = 4)
        Button(enabled = state.composing.isNotBlank(), onClick = { vm.add() }) {
            Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add")
        }

        HorizontalDivider()

        val items = state.rows.map { TodoChecklistItem(it) }
        DateGroupedChecklist(
            items = items,
            isDone = { it.row.status == "done" },
            onToggle = { vm.toggle(it.row) },
            onDelete = { vm.delete(it) },
            onEdit = { id ->
                val row = state.rows.firstOrNull { it.id == id } ?: return@DateGroupedChecklist
                if (state.editingId == id) vm.cancelEdit() else vm.startEdit(row)
            },
            itemBody = { item ->
                if (state.editingId == item.id) {
                    OutlinedTextField(
                        value = state.editContent,
                        onValueChange = vm::setEditContent,
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Row {
                        TextButton(onClick = { vm.saveEdit() }) { Text("Save") }
                        TextButton(onClick = { vm.cancelEdit() }) { Text("Cancel") }
                    }
                } else {
                    Text(item.row.content, style = MaterialTheme.typography.bodyMedium)
                    Text(item.row.status, style = MaterialTheme.typography.labelSmall)
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
    }
}
