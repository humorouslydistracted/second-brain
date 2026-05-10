package com.secondbrain.app.ui.buy

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
import com.secondbrain.app.data.BuyDao
import com.secondbrain.app.data.BuyRow
import com.secondbrain.app.data.DatabaseHolder
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

class BuyViewModel : ViewModel() {
    data class S(
        val rows: List<BuyRow> = emptyList(),
        val total: Long = 0,
        val composing: String = "",
        val composingQty: String = "",
        val composingUnit: String = "",
        val editingId: Long? = null,
        val editItem: String = "",
        val editQty: String = "",
        val editUnit: String = "",
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (rows, total) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            BuyDao.list(db) to BuyDao.count(db)
        }
        _s.update { it.copy(rows = rows, total = total) }
    }
    fun setCompose(v: String) = _s.update { it.copy(composing = v) }
    fun setComposeQty(v: String) = _s.update { it.copy(composingQty = v) }
    fun setComposeUnit(v: String) = _s.update { it.copy(composingUnit = v) }

    fun add() = viewModelScope.launch {
        val text = _s.value.composing.trim().ifBlank { return@launch }
        val qty = _s.value.composingQty.trim().ifBlank { null }
        val unit = _s.value.composingUnit.trim().ifBlank { null }
        withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get().writableDatabase
            val cv = android.content.ContentValues().apply {
                put("item_text", text); put("quantity_text", qty); put("unit_text", unit)
                put("date", java.time.LocalDate.now().toString()); put("status", "open")
            }
            db.insert("buy_items", null, cv)
        }
        _s.update { it.copy(composing = "", composingQty = "", composingUnit = "") }
        refresh()
        val label = if (qty != null) "$text ($qty${unit?.let { " $it" } ?: ""})" else text
        logActivity("Added buy item", "Buy item added: ${label.take(60)}", "buy")
    }

    fun toggle(row: BuyRow) = viewModelScope.launch {
        val next = if (row.status == "open") "done" else "open"
        withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            BuyDao.setStatus(db, row.id, next)
            ActivityLogDao.insert(db, "Buy item $next", "Marked $next: ${row.itemText.take(60)}", "buy", null)
        }
        refresh()
        AppStatusBus.refresh()
    }

    fun startEdit(row: BuyRow) = _s.update {
        it.copy(editingId = row.id, editItem = row.itemText,
            editQty = row.quantityText ?: "", editUnit = row.unitText ?: "")
    }
    fun cancelEdit() = _s.update { it.copy(editingId = null, editItem = "", editQty = "", editUnit = "") }
    fun setEditItem(v: String) = _s.update { it.copy(editItem = v) }
    fun setEditQty(v: String) = _s.update { it.copy(editQty = v) }
    fun setEditUnit(v: String) = _s.update { it.copy(editUnit = v) }

    fun saveEdit() = viewModelScope.launch {
        val id = _s.value.editingId ?: return@launch
        val text = _s.value.editItem.trim().ifBlank { return@launch }
        val qty = _s.value.editQty.trim().ifBlank { null }
        val unit = _s.value.editUnit.trim().ifBlank { null }
        withContext(Dispatchers.IO) { BuyDao.update(DatabaseHolder.get(), id, text, qty, unit) }
        cancelEdit(); refresh()
        logActivity("Edited buy item", "Updated: ${text.take(60)}", "buy")
    }

    fun delete(id: Long) = viewModelScope.launch {
        val row = _s.value.rows.firstOrNull { it.id == id }
        withContext(Dispatchers.IO) { BuyDao.delete(DatabaseHolder.get(), id) }
        refresh()
        if (row != null) logActivity("Deleted buy item", "Deleted: ${row.itemText.take(60)}", "buy")
    }

    fun clearAll() = viewModelScope.launch {
        val count = _s.value.rows.size
        withContext(Dispatchers.IO) { BuyDao.clearAll(DatabaseHolder.get()) }
        refresh()
        logActivity("Cleared buy list", "Cleared $count buy item${if (count == 1) "" else "s"}", "buy")
    }

    private suspend fun logActivity(input: String, response: String, kind: String) {
        withContext(Dispatchers.IO) {
            ActivityLogDao.insert(DatabaseHolder.get(), input, response, kind, null)
        }
        AppStatusBus.emit(response)
    }
}

private data class BuyChecklistItem(val row: BuyRow) : DatedChecklistItem {
    override val id: Long = row.id
    override val dateKey: String = row.date ?: row.createdAt.take(10)
}

@Composable
fun BuyScreen(vm: BuyViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        SectionHeader(
            title = "Buy list",
            visibleCount = state.rows.size,
            totalCount = state.total.toInt(),
            buildClipboardText = {
                renderTable(
                    headers = listOf("STATUS", "DATE", "ITEM", "QTY", "UNIT"),
                    rows = state.rows.map {
                        listOf(it.status, it.date ?: it.createdAt.take(10),
                            it.itemText, it.quantityText, it.unitText)
                    },
                )
            },
            onClearAll = { vm.clearAll() },
        )

        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(value = state.composing, onValueChange = vm::setCompose,
                label = { Text("Item") }, singleLine = true, modifier = Modifier.weight(2f))
            OutlinedTextField(value = state.composingQty, onValueChange = vm::setComposeQty,
                label = { Text("Qty") }, singleLine = true, modifier = Modifier.weight(1f))
            OutlinedTextField(value = state.composingUnit, onValueChange = vm::setComposeUnit,
                label = { Text("Unit") }, singleLine = true, modifier = Modifier.weight(1f))
        }
        Button(enabled = state.composing.isNotBlank(), onClick = { vm.add() }) {
            Icon(Icons.Filled.Add, contentDescription = null); Spacer(Modifier.width(4.dp)); Text("Add")
        }

        HorizontalDivider()

        val items = state.rows.map { BuyChecklistItem(it) }
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
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        OutlinedTextField(value = state.editItem, onValueChange = vm::setEditItem,
                            label = { Text("Item") }, singleLine = true, modifier = Modifier.weight(2f))
                        OutlinedTextField(value = state.editQty, onValueChange = vm::setEditQty,
                            label = { Text("Qty") }, singleLine = true, modifier = Modifier.weight(1f))
                        OutlinedTextField(value = state.editUnit, onValueChange = vm::setEditUnit,
                            label = { Text("Unit") }, singleLine = true, modifier = Modifier.weight(1f))
                    }
                    Row {
                        TextButton(onClick = { vm.saveEdit() }) { Text("Save") }
                        TextButton(onClick = { vm.cancelEdit() }) { Text("Cancel") }
                    }
                } else {
                    val r = item.row
                    val qty = if (!r.quantityText.isNullOrBlank())
                        " (${r.quantityText}${r.unitText?.let { " $it" } ?: ""})" else ""
                    Text("${r.itemText}$qty", style = MaterialTheme.typography.bodyMedium)
                    Text(r.status, style = MaterialTheme.typography.labelSmall)
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
    }
}
