package com.secondbrain.app

import android.app.Application
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.diag.EventLog
import kotlin.system.exitProcess

class SecondBrainApp : Application() {
    override fun onCreate() {
        super.onCreate()
        DatabaseHolder.init(this)
        EventLog.bindExternalDir(this)
        EventLog.info(EventLog.Category.APP, "Application.onCreate")

        // Capture every uncaught Kotlin/Java exception into the diagnostic
        // event_log so the user can paste a full crash report. We DO let
        // the process die afterward — Android will then restart the
        // activity normally.
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            runCatching {
                EventLog.throwable(
                    EventLog.Category.CRASH,
                    "uncaught exception on thread '${thread.name}'",
                    throwable,
                )
            }
            // Defer to the prior handler (the platform default kills us).
            previous?.uncaughtException(thread, throwable)
                ?: exitProcess(2)
        }
    }
}
