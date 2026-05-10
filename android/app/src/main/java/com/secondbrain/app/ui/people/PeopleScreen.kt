package com.secondbrain.app.ui.people

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
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
import com.secondbrain.app.data.PeopleDao
import com.secondbrain.app.data.PersonRow
import com.secondbrain.app.data.SelfName
import com.secondbrain.app.ui.common.SectionHeader
import com.secondbrain.app.ui.common.renderTable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class PeopleViewModel : ViewModel() {
    data class S(
        val rows: List<PersonRow> = emptyList(),
        val total: Long = 0,
        val newName: String = "",
        val editingId: Long? = null,
        val editName: String = "",
        // 2026-05-09: lowercased self name from runtime_state. The marker
        // on each row uses this. Switching self updates this in-place;
        // historical ledger/weight rows remain unchanged.
        val selfName: String? = null,
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }
    fun refresh() = viewModelScope.launch {
        val (rows, total, self) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            Triple(PeopleDao.list(db), PeopleDao.count(db), SelfName.get(db))
        }
        _s.update { it.copy(rows = rows, total = total, selfName = self?.lowercase()) }
    }
    fun setNew(v: String) = _s.update { it.copy(newName = v) }
    fun add() = viewModelScope.launch {
        val n = _s.value.newName.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) { PeopleDao.add(DatabaseHolder.get(), n) }
        _s.update { it.copy(newName = "") }; refresh()
    }
    fun startEdit(row: PersonRow) = _s.update { it.copy(editingId = row.id, editName = row.name) }
    fun setEditName(v: String) = _s.update { it.copy(editName = v) }
    fun cancelEdit() = _s.update { it.copy(editingId = null, editName = "") }
    fun saveEdit(oldName: String) = viewModelScope.launch {
        val n = _s.value.editName.trim().ifBlank { return@launch }
        withContext(Dispatchers.IO) { PeopleDao.rename(DatabaseHolder.get(), oldName, n) }
        // If the renamed person was the active self, update the saved
        // self_name to match (so future "self / I / me" still resolves
        // to the same human).
        if (_s.value.selfName == oldName.trim().lowercase()) {
            withContext(Dispatchers.IO) { SelfName.set(DatabaseHolder.get(), n) }
        }
        cancelEdit(); refresh()
    }
    fun delete(id: Long) = viewModelScope.launch {
        withContext(Dispatchers.IO) { PeopleDao.delete(DatabaseHolder.get(), id) }; refresh()
    }

    /**
     * Switch the active self to the given person. Only updates which name
     * resolves "self / I / me / my / myself" on FUTURE writes — historical
     * rows in `weights`/`ledger` are not retroactively renamed.
     */
    fun setAsSelf(row: PersonRow) = viewModelScope.launch {
        val newSelf = row.name.trim()
        if (newSelf.isEmpty()) return@launch
        withContext(Dispatchers.IO) { SelfName.set(DatabaseHolder.get(), newSelf) }
        AppStatusBus.emit(
            "${newSelf.replaceFirstChar { it.uppercase() }} is now you " +
                "(future entries only — past records unchanged)"
        )
        refresh()
    }
}

@Composable
fun PeopleScreen(vm: PeopleViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "People",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                renderTable(
                    headers = listOf("NAME", "SELF", "ADDED"),
                    rows = state.rows.map {
                        val isSelf = it.name.trim().lowercase() == state.selfName
                        listOf(it.name, if (isSelf) "yes" else "", it.createdAt)
                    },
                )
            },
        )

        // Helper text — explains the 'self' marker so first-time users know
        // what the badge means.
        if (state.rows.isNotEmpty()) {
            Surface(
                color = MaterialTheme.colorScheme.surfaceVariant,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "The person marked 'self' is who 'self', 'I', 'me', 'my', 'myself' " +
                        "resolve to in your inputs. Use the ⋮ menu to switch self. " +
                        "Switching only affects new entries.",
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(8.dp),
                )
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(value = state.newName, onValueChange = vm::setNew,
                label = { Text("Name") }, modifier = Modifier.weight(1f), singleLine = true)
            Button(enabled = state.newName.isNotBlank(), onClick = { vm.add() }) {
                Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add")
            }
        }

        HorizontalDivider()
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(state.rows, key = { it.id }) { r ->
                PersonRowItem(
                    row = r,
                    isSelf = r.name.trim().lowercase() == state.selfName,
                    isEditing = state.editingId == r.id,
                    editName = state.editName,
                    onStartEdit = { vm.startEdit(r) },
                    onSetEditName = vm::setEditName,
                    onCancelEdit = vm::cancelEdit,
                    onSaveEdit = { vm.saveEdit(r.name) },
                    onDelete = { vm.delete(r.id) },
                    onSetAsSelf = { vm.setAsSelf(r) },
                )
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun PersonRowItem(
    row: PersonRow,
    isSelf: Boolean,
    isEditing: Boolean,
    editName: String,
    onStartEdit: () -> Unit,
    onSetEditName: (String) -> Unit,
    onCancelEdit: () -> Unit,
    onSaveEdit: () -> Unit,
    onDelete: () -> Unit,
    onSetAsSelf: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (isEditing) {
            OutlinedTextField(
                value = editName, onValueChange = onSetEditName,
                modifier = Modifier.weight(1f), singleLine = true,
            )
            TextButton(onClick = onSaveEdit) { Text("Save") }
            TextButton(onClick = onCancelEdit) { Text("Cancel") }
        } else {
            Text(
                row.name.replaceFirstChar { it.uppercase() },
                style = MaterialTheme.typography.bodyLarge,
            )
            if (isSelf) {
                Spacer(Modifier.width(8.dp))
                AssistChip(
                    onClick = {},  // chip is purely informational
                    label = { Text("self", style = MaterialTheme.typography.labelSmall) },
                    enabled = false,
                )
            }
            Spacer(Modifier.weight(1f))
            Box {
                IconButton(onClick = { menuOpen = true }) {
                    Icon(Icons.Filled.MoreVert, contentDescription = "More")
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    if (!isSelf) {
                        DropdownMenuItem(
                            text = { Text("Set as self") },
                            onClick = { menuOpen = false; onSetAsSelf() },
                        )
                    } else {
                        DropdownMenuItem(
                            text = { Text("Already self", style = MaterialTheme.typography.bodySmall) },
                            onClick = { menuOpen = false },
                            enabled = false,
                        )
                    }
                    DropdownMenuItem(
                        text = { Text("Rename") },
                        leadingIcon = { Icon(Icons.Filled.Edit, contentDescription = null) },
                        onClick = { menuOpen = false; onStartEdit() },
                    )
                    DropdownMenuItem(
                        text = { Text("Delete") },
                        leadingIcon = { Icon(Icons.Filled.Delete, contentDescription = null) },
                        onClick = { menuOpen = false; onDelete() },
                    )
                }
            }
        }
    }
}
