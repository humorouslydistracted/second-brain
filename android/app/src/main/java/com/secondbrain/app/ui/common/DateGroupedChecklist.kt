package com.secondbrain.app.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

/**
 * Reusable list-of-things-with-checkboxes-and-dates layout, used by
 * both the Todos screen and the Buy screen.
 *
 * Behaviour:
 *   - Items are grouped by their `date` field (or created_at fallback).
 *   - Sections are ordered newest-date first (so future dates appear
 *     ABOVE today, which matches the user's mental model of "scroll up
 *     to see future items").
 *   - On first composition the scroll position is computed so that the
 *     section header for "today" (or the most recent past date if no
 *     today rows exist) is at the top of the viewport. User scrolls
 *     UP to see future items.
 *   - Each item has a Checkbox toggle + a delete trash icon.
 *   - A small label per item shows status (open/done) for clarity.
 */
@Composable
fun <T : DatedChecklistItem> DateGroupedChecklist(
    items: List<T>,
    isDone: (T) -> Boolean,
    onToggle: (T) -> Unit,
    onDelete: (Long) -> Unit,
    itemBody: @Composable (T) -> Unit,
    modifier: Modifier = Modifier,
    onEdit: ((Long) -> Unit)? = null,
    /**
     * Route name used to drain [HighlightBus] on first composition. When the
     * route matches, the corresponding item gets a brief background flash and
     * the list scrolls to it. Pass null to disable.
     */
    highlightRoute: String? = null,
) {
    val today = remember { LocalDate.now().toString() }
    val listState = rememberLazyListState()

    // Build the flat row list (header + items) and the index of the
    // first row that's "today or earlier" — that's our default scroll
    // anchor. We only do this work when `items` changes.
    val (flatRows, todayAnchorIndex) = remember(items) {
        val grouped = items
            .groupBy { it.dateKey }
            .toSortedMap(compareByDescending { it })  // future dates first

        val rows = mutableListOf<FlatRow<T>>()
        var anchor = -1
        for ((date, group) in grouped) {
            if (anchor < 0 && date <= today) anchor = rows.size
            rows += FlatRow.Header(date)
            group.forEach { rows += FlatRow.Item(it) }
        }
        if (anchor < 0) anchor = 0  // all rows are future; land at top
        rows to anchor
    }

    val highlight = rememberHighlightState()
    if (highlightRoute != null) {
        highlight.consumeOnLaunch(
            route = highlightRoute,
            listState = listState,
            scrollIndex = { id ->
                flatRows.indexOfFirst { row ->
                    row is FlatRow.Item && row.value.id == id
                }
            },
        )
    }

    LaunchedEffect(items.size, todayAnchorIndex) {
        // Only auto-scroll on initial population (size becomes non-zero
        // after first refresh). Subsequent toggles shouldn't yank the
        // viewport.
        if (items.isNotEmpty() && listState.firstVisibleItemIndex == 0
            && listState.firstVisibleItemScrollOffset == 0
            && todayAnchorIndex > 0
        ) {
            listState.scrollToItem(todayAnchorIndex)
        }
    }

    LazyColumn(
        state = listState,
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        items(flatRows, key = { row ->
            when (row) {
                is FlatRow.Header<*> -> "h-${row.date}"
                is FlatRow.Item -> "i-${row.value.id}"
            }
        }) { row ->
            when (row) {
                is FlatRow.Header<*> -> DateHeader(row.date, isToday = row.date == today)
                is FlatRow.Item -> {
                    val rowBg = highlight.backgroundFor(row.value.id)
                    Row(
                        Modifier.fillMaxWidth().background(rowBg).padding(vertical = 2.dp, horizontal = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = isDone(row.value),
                            onCheckedChange = { onToggle(row.value) },
                        )
                        Column(Modifier.weight(1f)) {
                            itemBody(row.value)
                        }
                        if (onEdit != null) {
                            IconButton(onClick = { onEdit(row.value.id) }) {
                                Icon(Icons.Filled.Edit, contentDescription = "Edit",
                                    modifier = Modifier.size(18.dp))
                            }
                        }
                        IconButton(onClick = { onDelete(row.value.id) }) {
                            Icon(Icons.Filled.Delete, contentDescription = null)
                        }
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
private fun DateHeader(date: String, isToday: Boolean) {
    val label = remember(date, isToday) { describeDate(date, isToday) }
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
    ) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

private fun describeDate(date: String, isToday: Boolean): String {
    if (date.isBlank() || date.length < 10) return date.ifBlank { "(no date)" }
    return runCatching {
        val d = LocalDate.parse(date.take(10))
        val today = LocalDate.now()
        val rel = when (val days = today.until(d, java.time.temporal.ChronoUnit.DAYS).toInt()) {
            0 -> "Today"
            1 -> "Tomorrow"
            -1 -> "Yesterday"
            in 2..6 -> d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.getDefault())
            in -6..-2 -> "Last ${d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.getDefault())}"
            else -> ""
        }
        val absolute = d.format(DateTimeFormatter.ofPattern("EEE, d MMM yyyy"))
        if (rel.isNotEmpty()) "$rel · $absolute" else absolute
    }.getOrElse { date }
}

interface DatedChecklistItem {
    val id: Long
    val dateKey: String
}

private sealed interface FlatRow<out T : DatedChecklistItem> {
    data class Header<T : DatedChecklistItem>(val date: String) : FlatRow<T>
    data class Item<T : DatedChecklistItem>(val value: T) : FlatRow<T>
}
