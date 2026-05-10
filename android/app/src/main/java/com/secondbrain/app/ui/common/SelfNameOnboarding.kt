package com.secondbrain.app.ui.common

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.SelfName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * First-launch onboarding modal. Asks the user for the name they want
 * the app to use when resolving "I / me / self" pronouns. Persists to
 * the `runtime_state` table via [SelfName.set].
 *
 * Composable expects to be hoisted at the app root (above the nav host)
 * so it overlays whatever screen the user is on. Returns immediately
 * if a name is already set.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SelfNameOnboardingHost(content: @Composable () -> Unit) {
    var hasName by remember { mutableStateOf<Boolean?>(null) }
    var name by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        val existing = withContext(Dispatchers.IO) { SelfName.get(DatabaseHolder.get()) }
        hasName = !existing.isNullOrBlank()
    }

    content()

    if (hasName == false) {
        AlertDialog(
            onDismissRequest = { /* mandatory: don't allow tap-outside dismiss */ },
            title = { Text("Welcome — what's your name?") },
            text = {
                Column {
                    Text(
                        "Used when you say things like 'my weight', 'I owe Maddy', etc. " +
                            "You can change this later in Settings.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = name,
                        onValueChange = { name = it },
                        label = { Text("Your name") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    enabled = name.trim().isNotBlank(),
                    onClick = {
                        val cleaned = name.trim()
                        scope.launch {
                            withContext(Dispatchers.IO) {
                                SelfName.set(DatabaseHolder.get(), cleaned)
                            }
                            AppStatusBus.emit("Welcome, ${cleaned.replaceFirstChar { it.uppercase() }}!")
                            hasName = true
                        }
                    },
                ) { Text("Save") }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        scope.launch {
                            withContext(Dispatchers.IO) {
                                SelfName.set(DatabaseHolder.get(), "self")
                            }
                            hasName = true
                        }
                    },
                ) { Text("Skip") }
            },
        )
    }
}
