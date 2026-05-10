package com.secondbrain.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.lifecycleScope
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.diag.EventLog
import com.secondbrain.app.ui.SecondBrainTheme
import com.secondbrain.app.ui.ThemeSetting
import com.secondbrain.app.ui.common.AppToastHost
import com.secondbrain.app.ui.common.SelfNameOnboardingHost
import com.secondbrain.app.ui.nav.AppNav
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.info(EventLog.Category.APP, "MainActivity.onCreate")
        ThemeSetting.load(DatabaseHolder.get())
        // Kick the ggml backend init off the UI thread.
        lifecycleScope.launch { LlamaCpp.init() }
        AppStartup.warmOnce(applicationContext)
        setContent {
            SecondBrainTheme {
                AppToastHost {
                    SelfNameOnboardingHost {
                        AppNav()
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        EventLog.info(EventLog.Category.APP, "MainActivity.onDestroy")
        super.onDestroy()
    }
}
