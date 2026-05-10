package com.secondbrain.app.ui.activity

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.orchestrator.ActivityEntry
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.orchestrator.RequestLogDao
import com.secondbrain.app.orchestrator.RequestLogEntry
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ActivityLogViewModel : ViewModel() {
    data class S(
        val rows: List<ActivityEntry> = emptyList(),
        val requestRows: List<RequestLogEntry> = emptyList(),
        val selected: Set<Long> = emptySet(),
        val totalCount: Long = 0,
    )

    private val _s = MutableStateFlow(S())
    val s = _s.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val (a, r, n) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            Triple(
                ActivityLogDao.list(db, limit = 200),
                RequestLogDao.list(db, limit = 200),
                ActivityLogDao.count(db),
            )
        }
        _s.update { it.copy(rows = a, requestRows = r, totalCount = n, selected = emptySet()) }
    }

    fun toggle(id: Long) = _s.update {
        it.copy(selected = if (id in it.selected) it.selected - id else it.selected + id)
    }

    fun selectAll() = _s.update { it.copy(selected = it.rows.map(ActivityEntry::id).toSet()) }
    fun selectNone() = _s.update { it.copy(selected = emptySet()) }

    fun clearAll(onDone: () -> Unit) = viewModelScope.launch {
        withContext(Dispatchers.IO) { RequestLogDao.clear(DatabaseHolder.get()) }
        refresh()
        onDone()
    }

    /**
     * Build the clipboard payload. Strategy:
     *   - if any rows selected, copy ONLY those (matched against
     *     request_log.activity_id where available, else fallback to the
     *     activity_log row text).
     *   - else, copy the entire visible request_log block list.
     */
    /**
     * Build the clipboard payload. Pass an explicit `selectedIds`
     * snapshot taken at click time — avoids any race where the VM
     * state has shifted between checkbox state observation and
     * clipboard build (root cause of the build-25 "selected copy
     * dumps everything" report).
     */
    fun buildClipboard(selectedIds: Set<Long> = _s.value.selected): String {
        val st = _s.value
        if (selectedIds.isEmpty()) {
            return st.requestRows.joinToString("\n---\n") { it.toClipboardBlock() }
        }
        val activityById = st.rows.associateBy { it.id }
        // One DB query, not one per row (was: activityIdFromMetadata
        // re-querying request_log per row — slow and the join could fail
        // intermittently).
        val perActivityReq: Map<Long, List<RequestLogEntry>> = run {
            val ids = st.requestRows.map { it.id }
            if (ids.isEmpty()) emptyMap() else {
                val placeholders = ids.joinToString(",") { "?" }
                DatabaseHolder.get().readableDatabase.rawQuery(
                    "SELECT id, activity_id FROM request_log WHERE id IN ($placeholders)",
                    ids.map { it.toString() }.toTypedArray(),
                ).use { c ->
                    val byReqId = mutableMapOf<Long, Long>()
                    while (c.moveToNext()) {
                        if (!c.isNull(1)) byReqId[c.getLong(0)] = c.getLong(1)
                    }
                    st.requestRows.groupBy { byReqId[it.id] ?: -1L }
                }
            }
        }
        return selectedIds.mapNotNull { id ->
            val a = activityById[id] ?: return@mapNotNull null
            val req = perActivityReq[id]?.firstOrNull()
            buildString {
                appendLine("ACTIVITY #${a.id} @ ${a.createdAt} (${a.kind ?: "?"})")
                appendLine("INPUT:    ${a.inputText}")
                appendLine("RESPONSE: ${a.responseText}")
                if (req != null) { appendLine(); append(req.toClipboardBlock()) }
            }
        }.joinToString("\n---\n")
    }

    private fun activityIdFromMetadata(entry: RequestLogEntry): Long? {
        // RequestLog rows are written with activity_id; we read it back via
        // a lightweight rawQuery to keep this VM self-contained.
        return DatabaseHolder.get().readableDatabase.rawQuery(
            "SELECT activity_id FROM request_log WHERE id=?",
            arrayOf(entry.id.toString()),
        ).use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null }
    }
}

@Composable
fun ActivityLogScreen(vm: ActivityLogViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {

        Text("Activity log — ${state.totalCount} total entries (showing latest 200)",
            style = MaterialTheme.typography.bodySmall)

        // Stable toolbar: positions never shift based on selection state.
        // Left = selection toggles. Right = always-the-same actions
        // (Refresh, Copy, Clear). Copy label changes its number but the
        // BUTTON's position and width stay fixed.
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.selectAll() })  { Text("All") }
            TextButton(onClick = { vm.selectNone() }) { Text("None") }
            Spacer(Modifier.weight(1f))
            IconButton(onClick = { vm.refresh() }) {
                Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
            }
            TextButton(onClick = {
                // Snapshot at click time — passed into buildClipboard
                // so a stale state.selected can't dump "everything".
                val snapshotIds = state.selected
                val n = snapshotIds.size
                clipboard.setText(AnnotatedString(vm.buildClipboard(snapshotIds)))
                val msg = if (n > 0) "Copied $n selected" else "Copied all logs"
                Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
            }) {
                Icon(Icons.Filled.ContentCopy, contentDescription = null)
                Spacer(Modifier.width(4.dp))
                // Always the word "Copy" + a count when applicable.
                // Position never shifts.
                Text(if (state.selected.isEmpty()) "Copy" else "Copy (${state.selected.size})")
            }
            TextButton(onClick = {
                vm.clearAll {
                    Toast.makeText(context, "Logs cleared.", Toast.LENGTH_SHORT).show()
                }
            }) {
                Icon(Icons.Filled.DeleteForever, contentDescription = null)
                Spacer(Modifier.width(4.dp))
                Text("Clear")
            }
        }

        HorizontalDivider()

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(state.rows, key = { it.id }) { row ->
                ElevatedCard {
                    Row(
                        Modifier.fillMaxWidth().padding(8.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Checkbox(
                            checked = row.id in state.selected,
                            onCheckedChange = { vm.toggle(row.id) },
                        )
                        Column(Modifier.weight(1f)) {
                            Text("${row.createdAt} · ${row.kind ?: "?"}",
                                style = MaterialTheme.typography.labelSmall)
                            Text("> ${row.inputText}", style = MaterialTheme.typography.bodyMedium)
                            Text(row.responseText, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
    }
}
