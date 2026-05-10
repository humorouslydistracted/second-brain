package com.secondbrain.app

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * Tiny app-wide bus for transient status messages (toasts) and silent
 * data-refresh triggers.
 *
 * [emit] — shows a toast chip AND triggers a home refresh.
 * [refresh] — silent: triggers a home refresh WITHOUT showing a toast.
 *             Use for high-frequency ops (checkbox toggles) that change
 *             DB state but don't need user-facing confirmation.
 */
object AppStatusBus {
    private val _messages = MutableSharedFlow<String>(
        replay = 0,
        extraBufferCapacity = 16,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val messages: SharedFlow<String> = _messages.asSharedFlow()

    private val _refreshes = MutableSharedFlow<Unit>(
        replay = 0,
        extraBufferCapacity = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val refreshes: SharedFlow<Unit> = _refreshes.asSharedFlow()

    fun emit(text: String) { _messages.tryEmit(text) }

    /** Trigger a data refresh without displaying a toast. */
    fun refresh() { _refreshes.tryEmit(Unit) }
}
