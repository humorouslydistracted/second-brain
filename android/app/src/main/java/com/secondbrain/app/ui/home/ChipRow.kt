package com.secondbrain.app.ui.home

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.secondbrain.app.orchestrator.Tag

/**
 * The 7 toggleable chips above the input box. Locked decisions:
 *   - taps go through Tags.toggleChip (mutual exclusion among writes,
 *     ask + at most one domain).
 */
@Composable
fun ChipRow(
    active: Set<Tag>,
    onTap: (Tag) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        Tag.entries.forEach { tag ->
            FilterChip(
                selected = tag in active,
                onClick = { onTap(tag) },
                label = { Text(tag.tagWithColon) },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}
