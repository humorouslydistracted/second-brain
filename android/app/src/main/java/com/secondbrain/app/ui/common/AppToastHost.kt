package com.secondbrain.app.ui.common

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import com.secondbrain.app.AppStatusBus
import kotlinx.coroutines.delay
import java.util.UUID

/**
 * Top-right toast host. Wrap your screen content in this and any
 * [AppStatusBus.emit] call will show as a brief animated chip in the
 * upper-right corner.
 *
 * Why this and not Android's [android.widget.Toast]?
 *   - Android 11+ blocks programmatic positioning of system toasts.
 *   - System toasts always render bottom-center.
 *   - A custom Compose overlay lets us control position, animation,
 *     duration, and stacking.
 *
 * Behavior:
 *   - Each emitted message becomes a chip that slides in from the right.
 *   - Chips stack vertically (newest on top). Up to 4 visible at once.
 *   - Each chip auto-dismisses after [TOAST_DURATION_MS] ms.
 *   - Tap-anywhere doesn't dismiss (we want them readable; they go
 *     away quickly enough).
 */
private const val TOAST_DURATION_MS = 2500L
private const val MAX_VISIBLE = 4

@Composable
fun AppToastHost(content: @Composable () -> Unit) {
    val toasts = remember { mutableStateListOf<ToastEntry>() }

    LaunchedEffect(Unit) {
        AppStatusBus.messages.collect { msg ->
            toasts.add(0, ToastEntry(id = UUID.randomUUID().toString(), text = msg))
            // Trim if too many
            while (toasts.size > MAX_VISIBLE) toasts.removeAt(toasts.size - 1)
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        content()
        // Anchor at top-right via a Popup so the overlay isn't constrained
        // by the parent's window insets. Popup itself handles draw order.
        Popup(
            alignment = Alignment.TopEnd,
            properties = PopupProperties(focusable = false, dismissOnClickOutside = false),
        ) {
            Column(
                modifier = Modifier
                    .padding(top = 32.dp, end = 12.dp)
                    .widthIn(max = 320.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                toasts.forEach { entry ->
                    key(entry.id) { ToastChip(entry, onDismiss = { toasts.remove(entry) }) }
                }
            }
        }
    }
}

@Composable
private fun ToastChip(entry: ToastEntry, onDismiss: () -> Unit) {
    var visible by remember { mutableStateOf(true) }

    LaunchedEffect(entry.id) {
        delay(TOAST_DURATION_MS)
        visible = false
        delay(250)  // wait for slide-out animation
        onDismiss()
    }

    AnimatedVisibility(
        visible = visible,
        enter = slideInHorizontally(initialOffsetX = { it }) + fadeIn(),
        exit = slideOutHorizontally(targetOffsetX = { it }) + fadeOut(),
    ) {
        Surface(
            color = MaterialTheme.colorScheme.inverseSurface,
            contentColor = MaterialTheme.colorScheme.inverseOnSurface,
            shape = MaterialTheme.shapes.small,
            tonalElevation = 4.dp,
            shadowElevation = 4.dp,
        ) {
            Text(
                text = entry.text,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

private data class ToastEntry(val id: String, val text: String)
