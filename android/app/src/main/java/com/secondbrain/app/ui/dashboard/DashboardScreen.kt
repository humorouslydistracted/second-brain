package com.secondbrain.app.ui.dashboard

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.secondbrain.app.data.*
import com.secondbrain.app.ui.common.SectionHeader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

class DashboardViewModel : ViewModel() {
    data class S(
        val monthSpend: Double = 0.0,
        val monthLabel: String = "",
        val pendingTodos: Long = 0,
        val balances: List<LedgerBalance> = emptyList(),
        val latestWeights: List<WeightRow> = emptyList(),
        val notesCount: Long = 0,
    )
    private val _s = MutableStateFlow(S()); val s = _s.asStateFlow()
    init { refresh() }

    fun refresh() = viewModelScope.launch {
        val month = SimpleDateFormat("yyyy-MM", Locale.US).format(Date())
        val data = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            S(
                monthSpend = ExpensesDao.monthTotal(db, month),
                monthLabel = month,
                pendingTodos = TodosDao.pendingCount(db),
                balances = LedgerDao.balances(db),
                latestWeights = WeightsDao.latestPerPerson(db),
                notesCount = NotesDao.count(db),
            )
        }
        _s.update { data }
    }
}

@Composable
fun DashboardScreen(vm: DashboardViewModel = viewModel()) {
    val state by vm.s.collectAsState()
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {

        SectionHeader(
            title = "Dashboard",
            visibleCount = 1,
            totalCount = 1,
            buildClipboardText = {
                buildString {
                    appendLine("Dashboard snapshot @ ${state.monthLabel}")
                    appendLine("Month spend (${state.monthLabel}): ₹${state.monthSpend}")
                    appendLine("Pending todos: ${state.pendingTodos}")
                    appendLine("Notes total: ${state.notesCount}")
                    appendLine()
                    appendLine("Ledger balances:")
                    if (state.balances.isEmpty()) appendLine("  (none)")
                    state.balances.forEach { b ->
                        val txt = when {
                            b.balance > 0 -> "${b.person} owes you ₹${b.balance}"
                            b.balance < 0 -> "You owe ${b.person} ₹${abs(b.balance)}"
                            else -> "${b.person} - settled"
                        }
                        appendLine("  $txt")
                    }
                    appendLine()
                    appendLine("Latest weights:")
                    if (state.latestWeights.isEmpty()) appendLine("  (none)")
                    state.latestWeights.forEach { w ->
                        appendLine("  ${w.person}: ${w.weight}kg on ${w.date}")
                    }
                }
            },
        )

        ElevatedCard {
            Column(Modifier.fillMaxWidth().padding(12.dp)) {
                Text("This month (${state.monthLabel})", style = MaterialTheme.typography.titleMedium)
                Text("Spend: ₹${state.monthSpend}", style = MaterialTheme.typography.headlineSmall)
                Text("Pending todos: ${state.pendingTodos}", style = MaterialTheme.typography.bodyMedium)
                Text("Notes total: ${state.notesCount}", style = MaterialTheme.typography.bodyMedium)
            }
        }

        ElevatedCard {
            Column(Modifier.fillMaxWidth().padding(12.dp)) {
                Text("Ledger balances", style = MaterialTheme.typography.titleMedium)
                if (state.balances.isEmpty()) Text("(none)", style = MaterialTheme.typography.bodySmall)
                state.balances.forEach { b ->
                    val txt = when {
                        b.balance > 0 -> "${b.person.replaceFirstChar { it.uppercase() }} owes you ₹${b.balance}"
                        b.balance < 0 -> "You owe ${b.person.replaceFirstChar { it.uppercase() }} ₹${abs(b.balance)}"
                        else -> "${b.person.replaceFirstChar { it.uppercase() }} - settled"
                    }
                    Text(txt, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }

        ElevatedCard {
            Column(Modifier.fillMaxWidth().padding(12.dp)) {
                Text("Latest weights", style = MaterialTheme.typography.titleMedium)
                if (state.latestWeights.isEmpty()) Text("(none)", style = MaterialTheme.typography.bodySmall)
                state.latestWeights.forEach { w ->
                    Text("${w.person.replaceFirstChar { it.uppercase() }}: ${w.weight}kg on ${w.date}",
                        style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}
