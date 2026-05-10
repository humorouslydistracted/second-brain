package com.secondbrain.app.ui.weights

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
import com.secondbrain.app.data.WeightRow
import com.secondbrain.app.data.WeightsDao
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.ui.common.SectionHeader
import com.secondbrain.app.ui.common.renderTable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class WeightsViewModel : ViewModel() {
    data class S(
        val rows: List<WeightRow> = emptyList(),
        val latest: List<WeightRow> = emptyList(),
        val total: Long = 0,
        val person: String = "",
        val weight: String = "",
        val note: String = "",
        val editingId: Long? = null,
        val editPerson: String = "",
        val editWeight: String = "",
        val editDate: String = "",
        val editNote: String = "",
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (rows, latest, n) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            Triple(WeightsDao.list(db), WeightsDao.latestPerPerson(db), WeightsDao.count(db))
        }
        _s.update { it.copy(rows = rows, latest = latest, total = n) }
    }
    fun setPerson(v: String) = _s.update { it.copy(person = v) }
    fun setWeight(v: String) = _s.update { it.copy(weight = v) }
    fun setNote(v: String) = _s.update { it.copy(note = v) }

    fun add() = viewModelScope.launch {
        val p = _s.value.person.trim().ifBlank { return@launch }
        val w = _s.value.weight.toDoubleOrNull() ?: return@launch
        val n = _s.value.note.trim().ifBlank { null }
        withContext(Dispatchers.IO) { WeightsDao.add(DatabaseHolder.get(), p, w, n) }
        _s.update { it.copy(person = "", weight = "", note = "") }
        refresh()
        logActivity("Logged weight", "Weight logged: ${p.replaceFirstChar { it.uppercase() }} ${w}kg", "weight")
    }

    fun startEdit(row: WeightRow) = _s.update {
        it.copy(editingId = row.id, editPerson = row.person, editWeight = row.weight.toString(),
            editDate = row.date, editNote = row.note ?: "")
    }
    fun cancelEdit() = _s.update { it.copy(editingId = null) }
    fun setEditPerson(v: String) = _s.update { it.copy(editPerson = v) }
    fun setEditWeight(v: String) = _s.update { it.copy(editWeight = v) }
    fun setEditDate(v: String) = _s.update { it.copy(editDate = v) }
    fun setEditNote(v: String) = _s.update { it.copy(editNote = v) }

    fun saveEdit() = viewModelScope.launch {
        val id = _s.value.editingId ?: return@launch
        val p = _s.value.editPerson.trim().ifBlank { return@launch }
        val w = _s.value.editWeight.toDoubleOrNull() ?: return@launch
        val d = _s.value.editDate.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) {
            WeightsDao.update(DatabaseHolder.get(), id, p, w, d,
                _s.value.editNote.trim().ifBlank { null })
        }
        cancelEdit(); refresh()
        logActivity("Edited weight", "Weight updated: ${p.replaceFirstChar { it.uppercase() }} ${w}kg on $d", "weight")
    }

    fun delete(id: Long) = viewModelScope.launch {
        val row = _s.value.rows.firstOrNull { it.id == id }
        withContext(Dispatchers.IO) { WeightsDao.delete(DatabaseHolder.get(), id) }
        refresh()
        if (row != null)
            logActivity("Deleted weight",
                "Deleted: ${row.person.replaceFirstChar { it.uppercase() }} ${row.weight}kg on ${row.date}", "weight")
    }

    fun clearAll() = viewModelScope.launch {
        val count = _s.value.rows.size
        withContext(Dispatchers.IO) { WeightsDao.clearAll(DatabaseHolder.get()) }
        refresh()
        logActivity("Cleared weights", "Cleared $count weight entr${if (count == 1) "y" else "ies"}", "weight")
    }

    private suspend fun logActivity(input: String, response: String, kind: String) {
        withContext(Dispatchers.IO) {
            ActivityLogDao.insert(DatabaseHolder.get(), input, response, kind, null)
        }
        AppStatusBus.emit(response)
    }
}

@Composable
fun WeightsScreen(vm: WeightsViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "Weights",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                val latest = renderTable(
                    headers = listOf("PERSON", "LATEST kg", "ON"),
                    rows = state.latest.map { listOf(it.person, it.weight.toString(), it.date) },
                )
                val all = renderTable(
                    headers = listOf("DATE", "PERSON", "kg", "NOTE"),
                    rows = state.rows.map { listOf(it.date, it.person, it.weight.toString(), it.note) },
                )
                "LATEST PER PERSON:\n$latest\n\nALL ENTRIES:\n$all"
            },
            onClearAll = { vm.clearAll() },
        )

        if (state.latest.isNotEmpty()) {
            Text("Latest", style = MaterialTheme.typography.titleSmall)
            state.latest.forEach { l ->
                Text("${l.person.replaceFirstChar { it.uppercase() }}: ${l.weight}kg on ${l.date}",
                    style = MaterialTheme.typography.bodySmall)
            }
            HorizontalDivider()
        }

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(value = state.person, onValueChange = vm::setPerson,
                label = { Text("Person") }, modifier = Modifier.weight(2f), singleLine = true)
            OutlinedTextField(value = state.weight, onValueChange = vm::setWeight,
                label = { Text("kg") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        OutlinedTextField(value = state.note, onValueChange = vm::setNote,
            label = { Text("Note (optional)") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(
            enabled = state.person.isNotBlank() && state.weight.toDoubleOrNull() != null,
            onClick = { vm.add() },
        ) { Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add") }

        HorizontalDivider()
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(state.rows, key = { it.id }) { r ->
                if (state.editingId == r.id) {
                    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedTextField(value = state.editPerson, onValueChange = vm::setEditPerson,
                                label = { Text("Person") }, singleLine = true, modifier = Modifier.weight(2f))
                            OutlinedTextField(value = state.editWeight, onValueChange = vm::setEditWeight,
                                label = { Text("kg") }, singleLine = true, modifier = Modifier.weight(1f))
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
                    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(r.date, style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(96.dp))
                        Column(Modifier.weight(1f)) {
                            Text("${r.person.replaceFirstChar { it.uppercase() }} - ${r.weight}kg",
                                style = MaterialTheme.typography.bodyMedium)
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
