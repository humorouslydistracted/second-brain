package com.secondbrain.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import com.secondbrain.app.data.AppDatabase
import kotlinx.coroutines.flow.MutableStateFlow

object ThemeSetting {
    enum class Mode { SYSTEM, LIGHT, DARK }

    val current = MutableStateFlow(Mode.SYSTEM)

    fun load(db: AppDatabase) {
        val v = db.readableDatabase.rawQuery(
            "SELECT value_json FROM runtime_state WHERE key='theme_mode'", null,
        ).use { c -> if (c.moveToFirst()) c.getString(0)?.trim('"') else null }
        current.value = when (v) { "LIGHT" -> Mode.LIGHT; "DARK" -> Mode.DARK; else -> Mode.SYSTEM }
    }

    fun save(db: AppDatabase, mode: Mode) {
        current.value = mode
        db.writableDatabase.execSQL(
            "INSERT OR REPLACE INTO runtime_state(key, value_json, updated_at) VALUES (?, ?, datetime('now','localtime'))",
            arrayOf("theme_mode", "\"${mode.name}\""),
        )
    }
}

@Composable
fun SecondBrainTheme(content: @Composable () -> Unit) {
    val mode by ThemeSetting.current.collectAsState()
    val darkTheme = when (mode) {
        ThemeSetting.Mode.DARK   -> true
        ThemeSetting.Mode.LIGHT  -> false
        ThemeSetting.Mode.SYSTEM -> isSystemInDarkTheme()
    }
    MaterialTheme(
        colorScheme = if (darkTheme) darkColorScheme() else lightColorScheme(),
        content = content,
    )
}
