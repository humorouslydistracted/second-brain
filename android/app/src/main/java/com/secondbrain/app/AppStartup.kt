package com.secondbrain.app

import android.content.Context
import com.secondbrain.app.data.DatabaseHolder
import com.secondbrain.app.data.ModelRegistry
import com.secondbrain.app.embedding.MiniLmEncoder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Auto-warm hook called once per process from [MainActivity.onCreate].
 *
 * Behavior:
 *   - If the GGUF is present and the LLM is not loaded → load it,
 *     emit toast-friendly status to [AppStatusBus].
 *   - If the 3 ONNX files are present and the embedder is not loaded
 *     → load it, emit status.
 *   - Either step's failure does not block the other.
 *
 * Idempotent: subsequent calls return immediately. State lives in a
 * static AtomicBoolean so config-change recreates of MainActivity
 * don't trigger a second load.
 *
 * No-op when the user hasn't imported model files yet — the app simply
 * stays in the "not loaded" state and the user can use Settings →
 * Import models from device.
 */
object AppStartup {

    private val warmStarted = AtomicBoolean(false)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    fun warmOnce(context: Context) {
        if (!warmStarted.compareAndSet(false, true)) return
        val modelDir = File(context.getExternalFilesDir("models")?.absolutePath ?: return)
        scope.launch { autoLoadLlm(modelDir) }
        scope.launch { autoLoadEmbedder(modelDir) }
    }

    private suspend fun autoLoadLlm(modelDir: File) {
        // Discover GGUFs and pick the user's selection (or first found).
        // Supports running 1.7B and 0.6B side-by-side for A/B comparison.
        val gguf = ModelRegistry.resolveSelected(DatabaseHolder.get(), modelDir)
        if (gguf == null) {
            AppStatusBus.emit("Model file not found — open Settings to import.")
            return
        }
        if (LlamaCpp.isLoaded()) return
        AppStatusBus.emit("Loading ${gguf.name}…")
        val started = System.nanoTime()
        runCatching { LlamaCpp.loadModel(gguf, preferGpu = true, nCtx = 1024) }
            .onSuccess {
                val ms = (System.nanoTime() - started) / 1_000_000
                AppStatusBus.emit("Model loaded in ${ms}ms.")
            }
            .onFailure { exc ->
                AppStatusBus.emit("Model load failed: ${exc.message}")
            }
    }

    private suspend fun autoLoadEmbedder(modelDir: File) {
        val st = MiniLmEncoder.status(modelDir)
        if (!st.modelExists || !st.vocabExists || !st.configExists) {
            AppStatusBus.emit("Embedder files not found — open Settings to import.")
            return
        }
        if (MiniLmEncoder.isLoaded()) return
        AppStatusBus.emit("Loading embedder…")
        val started = System.nanoTime()
        MiniLmEncoder.load(modelDir)
            .onSuccess {
                val ms = (System.nanoTime() - started) / 1_000_000
                AppStatusBus.emit("Embedder loaded in ${ms}ms.")
            }
            .onFailure { exc ->
                AppStatusBus.emit("Embedder load failed: ${exc.message}")
            }
    }
}
