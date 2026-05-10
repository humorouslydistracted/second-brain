package com.secondbrain.app.ui.notes

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import com.secondbrain.app.data.NoteRow
import com.secondbrain.app.data.NotesDao
import com.secondbrain.app.embedding.EmbeddingsDao
import com.secondbrain.app.embedding.MiniLmEncoder
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.ui.common.SectionHeader
import com.secondbrain.app.ui.common.renderTable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class NotesViewModel : ViewModel() {
    data class S(
        val rows: List<NoteRow> = emptyList(),
        val total: Long = 0,
        val composing: String = "",
        val editingId: Long? = null,
        val editingText: String = "",
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (rows, total) = withContext(Dispatchers.IO) {
            NotesDao.list(DatabaseHolder.get(), 200) to NotesDao.count(DatabaseHolder.get())
        }
        _s.update { it.copy(rows = rows, total = total) }
    }
    fun setCompose(text: String) = _s.update { it.copy(composing = text) }
    fun add() = viewModelScope.launch {
        val text = _s.value.composing.trim().ifBlank { return@launch }
        val saved = withContext(Dispatchers.IO) {
            NotesDao.addForToday(DatabaseHolder.get(), text)
        }
        _s.update { it.copy(composing = "") }; refresh()
        logActivity("Added note", "Note logged: ${text.take(60)}", "note")
        // Re-embed the whole day's blob so semantic search stays in sync
        // (mirrors Orchestrator.saveNote). Best-effort.
        viewModelScope.launch(Dispatchers.Default) {
            try {
                val vec = MiniLmEncoder.encode(saved.finalContent) ?: return@launch
                EmbeddingsDao.put(DatabaseHolder.get(), saved.id, saved.finalContent, vec)
            } catch (_: Throwable) { /* silent */ }
        }
    }
    fun startEdit(row: NoteRow) = _s.update { it.copy(editingId = row.id, editingText = row.content) }
    fun cancelEdit() = _s.update { it.copy(editingId = null, editingText = "") }
    fun setEditText(text: String) = _s.update { it.copy(editingText = text) }
    fun saveEdit() = viewModelScope.launch {
        val id = _s.value.editingId ?: return@launch
        val text = _s.value.editingText.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) { NotesDao.update(DatabaseHolder.get(), id, text) }
        _s.update { it.copy(editingId = null, editingText = "") }; refresh()
        logActivity("Edited note", "Note updated: ${text.take(60)}", "note")
    }
    fun delete(id: Long) = viewModelScope.launch {
        val row = _s.value.rows.firstOrNull { it.id == id }
        withContext(Dispatchers.IO) { NotesDao.delete(DatabaseHolder.get(), id) }; refresh()
        if (row != null)
            logActivity("Deleted note", "Note deleted: ${row.content.take(60)}", "note")
    }
    fun clearAll() = viewModelScope.launch {
        val count = _s.value.rows.size
        withContext(Dispatchers.IO) { NotesDao.clearAll(DatabaseHolder.get()) }; refresh()
        logActivity("Cleared notes", "Cleared $count note${if (count == 1) "" else "s"}", "note")
    }

    private suspend fun logActivity(input: String, response: String, kind: String) {
        withContext(Dispatchers.IO) {
            ActivityLogDao.insert(DatabaseHolder.get(), input, response, kind, null)
        }
        AppStatusBus.emit(response)
    }
}

@Composable
fun NotesScreen(vm: NotesViewModel = viewModel()) {
    val state by vm.s.collectAsState()

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "Notes",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                renderTable(
                    headers = listOf("ID", "CREATED", "CONTENT"),
                    rows = state.rows.map { listOf(it.id.toString(), it.createdAt, it.content) },
                )
            },
            onClearAll = { vm.clearAll() },
        )

        // Compose box for new notes
        OutlinedTextField(
            value = state.composing,
            onValueChange = vm::setCompose,
            label = { Text("New note") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 2,
            maxLines = 8,
        )
        Row {
            Button(enabled = state.composing.isNotBlank(), onClick = { vm.add() }) {
                Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add")
            }
        }
        HorizontalDivider()

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.rows, key = { it.id }) { row ->
                ElevatedCard {
                    Column(Modifier.fillMaxWidth().padding(10.dp)) {
                        Text(row.createdAt, style = MaterialTheme.typography.labelSmall)
                        if (state.editingId == row.id) {
                            OutlinedTextField(
                                value = state.editingText,
                                onValueChange = vm::setEditText,
                                modifier = Modifier.fillMaxWidth(),
                                minLines = 2, maxLines = 8,
                            )
                            Row {
                                TextButton(onClick = { vm.saveEdit() }) { Text("Save") }
                                TextButton(onClick = { vm.cancelEdit() }) { Text("Cancel") }
                            }
                        } else {
                            Text(row.content, style = MaterialTheme.typography.bodyMedium)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Spacer(Modifier.weight(1f))
                                IconButton(onClick = { vm.startEdit(row) }) {
                                    Icon(Icons.Filled.Edit, contentDescription = "Edit",
                                        modifier = Modifier.size(18.dp))
                                }
                                IconButton(onClick = { vm.delete(row.id) }) {
                                    Icon(Icons.Filled.Delete, contentDescription = "Delete")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
