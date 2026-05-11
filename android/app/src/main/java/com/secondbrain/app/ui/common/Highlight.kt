package com.secondbrain.app.ui.common

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.material3.MaterialTheme
import kotlinx.coroutines.delay

/**
 * Stateful holder for "the row to flash on this screen". Domain screens
 * call [consumeOnLaunch] in a LaunchedEffect once; if the [HighlightBus]
 * has a pending target for the given route, this state goes non-null for
 * ~3 seconds so the row's background can fade in then out.
 */
class HighlightState {
    var rowId by mutableStateOf<Long?>(null)
        private set

    suspend fun set(id: Long, holdMs: Long = 2500) {
        rowId = id
        delay(holdMs)
        rowId = null
    }
}

@Composable
fun rememberHighlightState(): HighlightState = remember { HighlightState() }

/**
 * On first composition, drain the HighlightBus for [route] and trigger the
 * flash. Also scrolls the LazyColumn to the matching row (if [scrollIndex]
 * resolves to a valid index ≥ 0).
 */
@Composable
fun HighlightState.consumeOnLaunch(
    route: String,
    listState: LazyListState? = null,
    scrollIndex: (Long) -> Int = { -1 },
) {
    LaunchedEffect(Unit) {
        val id = HighlightBus.consume(route) ?: return@LaunchedEffect
        // Briefly wait so the LazyList has measured items before we scroll.
        delay(60)
        val idx = scrollIndex(id)
        if (idx >= 0 && listState != null) {
            try { listState.animateScrollToItem(idx) } catch (_: Throwable) {}
        }
        set(id)
    }
}

/**
 * Returns a color suitable for the row background. Smoothly fades back to
 * transparent when the highlight clears.
 */
@Composable
fun HighlightState.backgroundFor(rowId: Long): Color {
    val active = this.rowId == rowId
    val alpha by animateFloatAsState(
        targetValue = if (active) 0.35f else 0f,
        animationSpec = tween(durationMillis = if (active) 250 else 600),
        label = "highlight-alpha",
    )
    return MaterialTheme.colorScheme.tertiary.copy(alpha = alpha)
}
