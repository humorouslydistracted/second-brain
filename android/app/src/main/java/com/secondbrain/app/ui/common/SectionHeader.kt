package com.secondbrain.app.ui.common

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp

/**
 * Shared header for every list-style screen. The locked spec says each
 * domain page (Expenses / Ledger / Weights / Todos / Notes / People /
 * Dashboard) has its own Copy button that dumps the currently visible
 * rows in plain-text-table format.
 */
@Composable
fun SectionHeader(
    title: String,
    visibleCount: Int,
    totalCount: Int,
    buildClipboardText: () -> String,
    onClearAll: (() -> Unit)? = null,
    extraActions: @Composable RowScope.() -> Unit = {},
) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current

    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text("Showing $visibleCount of $totalCount",
                style = MaterialTheme.typography.bodySmall)
        }
        extraActions()
        TextButton(onClick = {
            val text = buildClipboardText()
            clipboard.setText(AnnotatedString(text))
            Toast.makeText(context, "Copied $visibleCount rows", Toast.LENGTH_SHORT).show()
        }) {
            Icon(Icons.Filled.ContentCopy, contentDescription = null)
            Spacer(Modifier.width(6.dp))
            Text("Copy")
        }
        if (onClearAll != null) {
            TextButton(onClick = onClearAll) {
                Icon(Icons.Filled.DeleteForever, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text("Clear")
            }
        }
    }
}

/** Format a list of column-aligned rows as a plain-text table. */
fun renderTable(headers: List<String>, rows: List<List<String?>>): String {
    if (rows.isEmpty()) return "(empty)"
    val all = listOf(headers) + rows.map { r -> r.map { it ?: "" } }
    val widths = IntArray(headers.size)
    all.forEach { r ->
        r.forEachIndexed { i, c ->
            if (i < widths.size) widths[i] = maxOf(widths[i], c.length)
        }
    }
    fun fmt(r: List<String>): String =
        r.mapIndexed { i, c -> c.padEnd(widths.getOrElse(i) { 0 }) }.joinToString("  ")
    val sep = widths.joinToString("  ") { "-".repeat(it) }
    return buildString {
        appendLine(fmt(headers))
        appendLine(sep)
        rows.forEach { appendLine(fmt(it.map { c -> c ?: "" })) }
    }.trimEnd()
}
