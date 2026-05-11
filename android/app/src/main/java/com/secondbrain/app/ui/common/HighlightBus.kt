package com.secondbrain.app.ui.common

/**
 * Tiny single-shot registry used to deep-link from a Home activity row
 * into a domain screen and highlight the affected SQLite row.
 *
 * Usage:
 *   HighlightBus.set("weights", 42)
 *   navController.navigate("weights")
 *   // …inside WeightsScreen…
 *   LaunchedEffect(Unit) { vm.consumePendingHighlight("weights") }
 *
 * The destination consumes the value once and clears it, so a later
 * unrelated navigation to the same screen doesn't re-flash a stale row.
 */
object HighlightBus {
    @Volatile private var route: String? = null
    @Volatile private var id: Long? = null

    fun set(route: String, id: Long) {
        this.route = route
        this.id = id
    }

    /** Returns and clears the highlight only if it matches [forRoute]. */
    fun consume(forRoute: String): Long? {
        if (route == forRoute && id != null) {
            val out = id
            route = null; id = null
            return out
        }
        return null
    }
}
