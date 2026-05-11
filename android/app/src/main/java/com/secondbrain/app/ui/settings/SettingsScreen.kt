package com.secondbrain.app.ui.settings

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.secondbrain.app.AppStatusBus
import com.secondbrain.app.LlamaCpp
import com.secondbrain.app.ui.ThemeSetting
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.ModelRegistry
import com.secondbrain.app.data.NotesDao
import com.secondbrain.app.data.SelfName
import com.secondbrain.app.embedding.EmbeddingsDao
import com.secondbrain.app.embedding.MiniLmEncoder
import com.secondbrain.app.orchestrator.ActivityLogDao
import com.secondbrain.app.orchestrator.RequestLogBuilder
import com.secondbrain.app.orchestrator.RequestLogDao
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

// Default filename used only as a fallback hint in the import-status section
// when no GGUF is present yet. Once any qwen3-*-parser-q4_k_m.gguf is in the
// models dir, [ModelRegistry] takes over and this constant is irrelevant.
private const val DEFAULT_MODEL_FILENAME = "qwen3-1.7b-parser-q4_k_m.gguf"

class SettingsViewModel : ViewModel() {
    data class S(
        val preferGpu: Boolean = true,
        val modelPath: String = "",
        val modelExists: Boolean = false,
        val loaded: Boolean = false,
        val loadMs: Long = 0L,
        val status: String = "",
        // ---- multi-model picker (1.7B vs 0.6B side-by-side) ----
        val availableModels: List<String> = emptyList(),
        val selectedModel: String? = null,
        // ---- embedding model state ----
        val embStatus: String = "",
        val embLoaded: Boolean = false,
        val embFilesPresent: Boolean = false,
        val embeddingCount: Long = 0L,
        val pendingEmbedCount: Int = 0,
        val embedJobRunning: Boolean = false,
    )
    private val _s = MutableStateFlow(S())
    val s = _s.asStateFlow()

    fun init(modelPath: String, exists: Boolean) {
        _s.update { it.copy(modelPath = modelPath, modelExists = exists,
            status = if (exists) "Model file found." else "Push GGUF to: $modelPath") }
    }

    /**
     * Re-scan the models dir for parser GGUFs and refresh the picker state.
     * Called from the Settings composable on first composition + after any
     * import. Cheap (one directory listing); safe to call repeatedly.
     */
    fun refreshAvailableModels(modelDir: File) = viewModelScope.launch {
        val (available, selected) = withContext(Dispatchers.IO) {
            val files = ModelRegistry.discover(modelDir)
            val active = ModelRegistry.resolveSelected(DatabaseHolder.get(), modelDir)
            files.map { it.name } to active?.name
        }
        _s.update { it.copy(availableModels = available, selectedModel = selected) }
    }

    /**
     * Switch to a different parser GGUF. Persists the choice via
     * [ModelRegistry], unloads the currently-loaded model, then loads the
     * new one. The Settings UI re-syncs from runtime singletons after.
     */
    fun selectModel(modelDir: File, filename: String) = viewModelScope.launch {
        val target = File(modelDir, filename)
        if (!target.exists()) {
            _s.update { it.copy(status = "File missing: $filename") }
            return@launch
        }
        withContext(Dispatchers.IO) {
            ModelRegistry.setSelected(DatabaseHolder.get(), filename)
        }
        _s.update { it.copy(selectedModel = filename, status = "Switching to $filename…") }
        // Unload current GGUF so loadModel actually reloads. forceUnload
        // is the only path that releases the native model handle.
        if (LlamaCpp.isLoaded()) LlamaCpp.forceUnload()
        _s.update { it.copy(loaded = false) }
        loadModel(target)
        refreshAvailableModels(modelDir)
    }

    fun toggleGpu() = _s.update { it.copy(preferGpu = !it.preferGpu) }

    fun loadModel(file: File) = viewModelScope.launch {
        _s.update { it.copy(status = "Loading model…") }
        val log = RequestLogBuilder(
            userInput = "[Settings] Load model",
            activeChips = emptySet(),
        )
        log.tier("settings_load_model")
        // File presence + size are first-line diagnostics for "Load failed".
        val exists = file.exists()
        val sizeMb = if (exists) file.length() / 1_048_576.0 else 0.0
        log.sql(
            label = "model.file_stat",
            statement = "(File.exists + File.length on ${file.absolutePath})",
            args = emptyList(),
            rowCount = if (exists) 1 else 0,
            sampleRows = listOf(
                mapOf(
                    "path" to file.absolutePath,
                    "exists" to exists.toString(),
                    "size_MB" to "%.1f".format(sizeMb),
                    "preferGpu" to _s.value.preferGpu.toString(),
                )
            ),
        )

        val started = System.nanoTime()
        var thrown: Throwable? = null
        runCatching {
            withContext(Dispatchers.Default) {
                LlamaCpp.loadModel(file, preferGpu = _s.value.preferGpu, nCtx = 1024)
            }
        }.onSuccess {
            val ms = (System.nanoTime() - started) / 1_000_000
            log.timing("native_load_ms", ms)
            val statusLine = "Loaded in ${ms}ms (${if (_s.value.preferGpu) "GPU" else "CPU"})"
            log.final(statusLine)
            _s.update { it.copy(loaded = true, loadMs = ms, status = statusLine) }
        }.onFailure { exc ->
            thrown = exc
            log.timing("native_load_ms", (System.nanoTime() - started) / 1_000_000)
            val errBody = "${exc.javaClass.name}: ${exc.message}\n" +
                exc.stackTraceToString().take(2000)
            log.error(errBody)
            val statusLine = "Load failed: ${exc.message}"
            log.final(statusLine)
            _s.update { it.copy(loaded = false, status = statusLine) }
        }
        persistSettingsEvent(log, thrown == null)
    }

    fun clearLogs(onDone: () -> Unit) = viewModelScope.launch {
        withContext(Dispatchers.IO) { RequestLogDao.clear(DatabaseHolder.get()) }
        // Tell the bus so Home + Activity-log re-fetch and the toast fires.
        AppStatusBus.emit("Cleared all logs (activity + diagnostics + event)")
        onDone()
    }

    /**
     * Copy a list of user-picked files (as content:// URIs) into the
     * app's models dir. Filename is preserved (we read SAF's display
     * name). Returns a status string per file for the UI to surface.
     *
     * This bypasses the Android/data scoped-storage MTP visibility
     * problem entirely — the user picks from anywhere reachable by
     * the system file picker (Downloads, Drive, etc.), and we copy
     * INTO our own app-private external dir.
     */
    fun importFromUris(
        context: Context,
        uris: List<Uri>,
        modelDir: File,
        onDone: (String) -> Unit,
    ) = viewModelScope.launch {
        if (uris.isEmpty()) { onDone("No files selected."); return@launch }
        modelDir.mkdirs()
        val report = StringBuilder()
        withContext(Dispatchers.IO) {
            for (uri in uris) {
                val displayName = queryDisplayName(context, uri) ?: "imported_${System.currentTimeMillis()}"
                val out = File(modelDir, displayName)
                runCatching {
                    context.contentResolver.openInputStream(uri).use { input ->
                        requireNotNull(input) { "could not open $uri" }
                        out.outputStream().use { o -> input.copyTo(o, bufferSize = 64 * 1024) }
                    }
                    report.append("✓ $displayName  (${"%.1f".format(out.length() / 1_048_576.0)} MB)\n")
                }.onFailure { e ->
                    report.append("✗ $displayName  failed: ${e.message}\n")
                }
            }
        }
        onDone(report.toString().trimEnd())
        // Refresh status panels so counts/file presence flip immediately
        refreshEmbeddingStatus(modelDir)
        // Pick whichever GGUF the registry resolves (selected one if still
        // present, else the first discovered) and show its path in the
        // status row. Importing a 0.6B alongside the 1.7B will surface it
        // here without changing the active model.
        val active = ModelRegistry.resolveSelected(DatabaseHolder.get(), modelDir)
        val pathFor = active?.absolutePath
            ?: File(modelDir, DEFAULT_MODEL_FILENAME).absolutePath
        init(pathFor, active != null)
        refreshAvailableModels(modelDir)
    }

    private fun queryDisplayName(context: Context, uri: Uri): String? {
        return runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull()
    }

    // ------------------------------------------------------------
    // Embedding model
    // ------------------------------------------------------------

    fun refreshEmbeddingStatus(modelDir: File) = viewModelScope.launch {
        val st = MiniLmEncoder.status(modelDir)
        val (count, pending) = withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            EmbeddingsDao.count(db) to EmbeddingsDao.unembeddedNoteIds(db).size
        }
        _s.update {
            it.copy(
                embFilesPresent = st.modelExists && st.vocabExists && st.configExists,
                embLoaded = st.loaded,
                embStatus = when {
                    st.loaded -> "Loaded."
                    st.loadError != null -> "Load failed: ${st.loadError}"
                    !st.modelExists || !st.vocabExists || !st.configExists ->
                        "Push minilm.onnx + minilm_vocab.txt + minilm_tokenizer_config.json to ${st.modelPath}"
                    else -> "Ready to load."
                },
                embeddingCount = count,
                pendingEmbedCount = pending,
            )
        }
    }

    fun loadEmbedding(modelDir: File) = viewModelScope.launch {
        _s.update { it.copy(embStatus = "Loading embedder…") }
        val log = RequestLogBuilder(
            userInput = "[Settings] Load embedder",
            activeChips = emptySet(),
        )
        log.tier("settings_load_embedder")
        val onnx = File(modelDir, MiniLmEncoder.MODEL_FILENAME)
        val vocab = File(modelDir, MiniLmEncoder.VOCAB_FILENAME)
        val cfg = File(modelDir, MiniLmEncoder.CONFIG_FILENAME)
        log.sql(
            label = "embedder.file_stat",
            statement = "(File.exists + File.length on each of 3 files)",
            args = emptyList(),
            rowCount = listOf(onnx, vocab, cfg).count { it.exists() },
            sampleRows = listOf(
                mapOf("name" to onnx.name, "exists" to onnx.exists().toString(),
                    "size_MB" to "%.2f".format(onnx.length() / 1_048_576.0)),
                mapOf("name" to vocab.name, "exists" to vocab.exists().toString(),
                    "size_KB" to "%.1f".format(vocab.length() / 1024.0)),
                mapOf("name" to cfg.name, "exists" to cfg.exists().toString(),
                    "size_B" to cfg.length().toString()),
            ),
        )
        val started = System.nanoTime()
        val r = MiniLmEncoder.load(modelDir)
        log.timing("native_load_ms", (System.nanoTime() - started) / 1_000_000)
        var thrown: Throwable? = null
        r.onSuccess {
            log.final("Embedder loaded.")
            _s.update { it.copy(embLoaded = true, embStatus = "Embedder loaded.") }
        }.onFailure { exc ->
            thrown = exc
            val errBody = "${exc.javaClass.name}: ${exc.message}\n" +
                exc.stackTraceToString().take(2000)
            log.error(errBody)
            log.final("Embedder failed: ${exc.message}")
            _s.update { it.copy(embLoaded = false, embStatus = "Embedder failed: ${exc.message}") }
        }
        persistSettingsEvent(log, thrown == null)
        refreshEmbeddingStatus(modelDir)
    }

    /**
     * Insert a settings-flavored entry into both activity_log and
     * request_log so the Home and Activity-log Copy-logs buttons see it.
     * Run on IO so we don't block the VM scope on SQLite write.
     */
    private suspend fun persistSettingsEvent(
        log: RequestLogBuilder,
        ok: Boolean,
    ) {
        // Read whichever status field is freshest. loadModel writes `status`,
        // loadEmbedding writes `embStatus` — we just take both and let the
        // user see the relevant one in the activity feed.
        val response = listOfNotNull(
            _s.value.status.takeIf { it.isNotBlank() },
            _s.value.embStatus.takeIf { it.isNotBlank() && it != _s.value.status },
        ).joinToString(" · ")
        withContext(Dispatchers.IO) {
            val db = DatabaseHolder.get()
            val activityId = ActivityLogDao.insert(
                db = db,
                input = log.userInput,
                response = response.ifBlank { if (ok) "ok" else "failed" },
                kind = if (ok) "settings" else "settings_error",
                metadataJson = null,
            )
            log.activityId = activityId
            log.persist(db)
        }
    }

    /**
     * Pull the source-of-truth "loaded" flags from the runtime singletons.
     * Use this whenever the runtime state may have changed without the
     * Settings UI being involved (e.g. AppStartup auto-loaded on launch).
     */
    fun syncLoadedFromRuntime() {
        val llmLoaded = LlamaCpp.isLoaded()
        val embLoaded = MiniLmEncoder.isLoaded()
        _s.update {
            it.copy(
                loaded = llmLoaded,
                embLoaded = embLoaded,
                status = if (llmLoaded && it.status.isBlank()) "Model loaded (auto)." else it.status,
                embStatus = if (embLoaded && it.embStatus.isBlank()) "Embedder loaded (auto)." else it.embStatus,
            )
        }
    }

    /** Compute embeddings for every note that doesn't yet have one. */
    fun reembedAll(modelDir: File) = viewModelScope.launch {
        if (_s.value.embedJobRunning) return@launch
        _s.update { it.copy(embedJobRunning = true, embStatus = "Re-embedding…") }
        try {
            // Make sure model is loaded first
            if (!_s.value.embLoaded) MiniLmEncoder.load(modelDir).getOrThrow()
            val db = DatabaseHolder.get()
            val rows = withContext(Dispatchers.IO) {
                val ids = EmbeddingsDao.unembeddedNoteIds(db)
                ids.mapNotNull { id ->
                    val cur = db.readableDatabase.rawQuery(
                        "SELECT content FROM notes WHERE id=?", arrayOf(id.toString())
                    )
                    val content = cur.use { c ->
                        if (c.moveToFirst()) c.getString(0) else null
                    }
                    if (content != null) id to content else null
                }
            }
            for ((id, content) in rows) {
                val vec = MiniLmEncoder.encode(content) ?: continue
                withContext(Dispatchers.IO) { EmbeddingsDao.put(db, id, content, vec) }
            }
            _s.update { it.copy(embStatus = "Re-embedded ${rows.size} note(s).") }
        } catch (t: Throwable) {
            _s.update { it.copy(embStatus = "Re-embed failed: ${t.message}") }
        } finally {
            _s.update { it.copy(embedJobRunning = false) }
            refreshEmbeddingStatus(modelDir)
        }
    }
}

@Composable
fun SettingsScreen(vm: SettingsViewModel = viewModel()) {
    val context = LocalContext.current
    val state by vm.s.collectAsState()

    val embeddingDir = remember {
        File(context.getExternalFilesDir("models")!!.absolutePath)
    }
    // Resolve the currently-selected GGUF from the registry. Recomputed
    // whenever the selected name in state changes (after switching models).
    val modelFile = remember(state.selectedModel) {
        ModelRegistry.resolveSelected(DatabaseHolder.get(), embeddingDir)
            ?: File(embeddingDir, DEFAULT_MODEL_FILENAME)
    }
    LaunchedEffect(Unit) {
        // getExternalFilesDir(...) creates the dir as a side effect — call
        // it explicitly so the user-pickable target exists even before
        // importing anything.
        context.getExternalFilesDir("models")?.also { it.mkdirs() }
        vm.init(modelFile.absolutePath, modelFile.exists())
        vm.refreshAvailableModels(embeddingDir)
        vm.refreshEmbeddingStatus(embeddingDir)
        // Pull live runtime state — auto-load may have already finished
        // before the user navigated to Settings; without this the buttons
        // stay enabled with text "Load model" even though the model is in
        // memory, leading to a redundant tap that queues behind any
        // running generate call (the "stuck on Loading model" symptom).
        vm.syncLoadedFromRuntime()
    }
    // Re-sync on every status-bus event so the buttons disable themselves
    // mid-screen as soon as auto-load completes.
    LaunchedEffect(Unit) {
        AppStatusBus.messages.collect {
            vm.syncLoadedFromRuntime()
            vm.refreshEmbeddingStatus(embeddingDir)
        }
    }

    var importStatus by remember { mutableStateOf<String?>(null) }
    val pickFiles = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris: List<Uri> ->
        if (uris.isNotEmpty()) {
            vm.importFromUris(context, uris, embeddingDir) { report ->
                importStatus = report
                Toast.makeText(context, "Import done", Toast.LENGTH_SHORT).show()
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {

        Text("Model", style = MaterialTheme.typography.titleMedium)
        Text(state.modelPath, style = MaterialTheme.typography.bodySmall)
        Text(state.status, style = MaterialTheme.typography.bodySmall)

        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = state.preferGpu, onCheckedChange = { vm.toggleGpu() })
            Spacer(Modifier.width(8.dp))
            Text(if (state.preferGpu) "GPU (Vulkan, default)" else "CPU only")
        }

        Button(
            enabled = state.modelExists && !state.loaded,
            onClick = { vm.loadModel(modelFile) },
        ) { Text(if (state.loaded) "Loaded ✓" else "Load model") }

        // ---- Multi-model picker ----------------------------------------
        // Surfaces every parser GGUF discovered under models/ (matches
        // qwen3-<size>-parser-q4_k_m.gguf). Tap any non-active row to
        // switch: the registry persists the choice, the current model is
        // unloaded, and the new one is loaded immediately. Lets us A/B
        // 1.7B vs 0.6B for reliability + on-device latency without
        // re-pushing files between runs.
        if (state.availableModels.isNotEmpty()) {
            Text(
                "Available parser models",
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.padding(top = 4.dp),
            )
            state.availableModels.forEach { name ->
                val isActive = name == state.selectedModel
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    RadioButton(
                        selected = isActive,
                        onClick = {
                            if (!isActive) vm.selectModel(embeddingDir, name)
                        },
                    )
                    Column(Modifier.weight(1f)) {
                        Text(name, style = MaterialTheme.typography.bodyMedium)
                        if (isActive) {
                            Text(
                                if (state.loaded) "active · loaded" else "active · not loaded",
                                style = MaterialTheme.typography.labelSmall,
                            )
                        }
                    }
                }
            }
        }

        HorizontalDivider()

        Text("Import model files", style = MaterialTheme.typography.titleMedium)
        Text(
            "Files land in ${embeddingDir.absolutePath}. Pick any " +
                "`qwen3-<size>-parser-q4_k_m.gguf` (e.g. `qwen3-1.7b-...` and/or `qwen3-0.6b-...`), " +
                "`minilm.onnx`, `minilm_vocab.txt`, and `minilm_tokenizer_config.json` from wherever you put them " +
                "(Downloads is fine). Both GGUFs can coexist — switch between them above. Filenames are preserved.",
            style = MaterialTheme.typography.bodySmall,
        )
        Button(onClick = {
            pickFiles.launch(arrayOf("*/*"))
        }) { Text("Import models from device…") }
        importStatus?.let { st ->
            Surface(color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
                Text(st, modifier = Modifier.padding(8.dp), style = MaterialTheme.typography.bodySmall)
            }
        }

        HorizontalDivider()

        Text("Embedding model (note semantic search)", style = MaterialTheme.typography.titleMedium)
        Text(state.embStatus, style = MaterialTheme.typography.bodySmall)
        Text("Embeddings stored: ${state.embeddingCount}  ·  pending: ${state.pendingEmbedCount}",
            style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = state.embFilesPresent && !state.embLoaded,
                onClick = { vm.loadEmbedding(embeddingDir) },
            ) { Text(if (state.embLoaded) "Loaded ✓" else "Load embedder") }
            OutlinedButton(
                enabled = state.embFilesPresent && state.pendingEmbedCount > 0 && !state.embedJobRunning,
                onClick = { vm.reembedAll(embeddingDir) },
            ) { Text(if (state.embedJobRunning) "Re-embedding…" else "Re-embed pending notes") }
        }

        HorizontalDivider()

        // 2026-05-09: Self-name moved out of Settings.
        // Manage it from the People page (via the 3-dot menu on each
        // person row → "Set as self"). Settings is now strictly for
        // model + diagnostics + RAG toggle.

        // RAG synthesis toggle (build #27 #8). Off by default — when on,
        // note queries do an extra LLM round trip to synthesize a 1-2
        // sentence answer over the retrieved snippets. ~10s extra per
        // note query.
        var ragOn by remember {
            mutableStateOf(
                com.secondbrain.app.parser.NoteSynthSetting.isEnabled(DatabaseHolder.get())
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = ragOn,
                onCheckedChange = {
                    ragOn = it
                    com.secondbrain.app.parser.NoteSynthSetting.setEnabled(DatabaseHolder.get(), it)
                    com.secondbrain.app.AppStatusBus.emit(
                        if (it) "Note synthesis: on (slower but synthesized)"
                        else "Note synthesis: off (snippets only, faster)"
                    )
                },
            )
            Spacer(Modifier.width(8.dp))
            Text("Synthesize a sentence on note queries (slower)")
        }

        HorizontalDivider()

        var themeMode by remember { mutableStateOf(ThemeSetting.current.value) }
        Text("Theme", style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ThemeSetting.Mode.entries.forEach { m ->
                FilterChip(
                    selected = themeMode == m,
                    onClick = {
                        themeMode = m
                        ThemeSetting.save(DatabaseHolder.get(), m)
                    },
                    label = { Text(m.name.lowercase().replaceFirstChar { it.uppercase() }) },
                )
            }
        }

        HorizontalDivider()

        Text("Diagnostics", style = MaterialTheme.typography.titleMedium)
        OutlinedButton(onClick = {
            vm.clearLogs {
                Toast.makeText(context, "Activity log + request log cleared.", Toast.LENGTH_SHORT).show()
            }
        }) { Text("Clear all logs (activity + diagnostics)") }
    }
}
