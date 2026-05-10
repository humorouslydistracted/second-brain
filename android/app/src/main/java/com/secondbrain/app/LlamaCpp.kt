package com.secondbrain.app

import android.util.Log
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.Executors

/**
 * Thin Kotlin wrapper over the JNI surface in `llama_jni.cpp`.
 *
 * One model handle per process. All native calls go through a dedicated
 * single-thread dispatcher because the JNI bridge is intentionally
 * non-thread-safe — running two `nativeGenerate` calls concurrently
 * against the same context would corrupt state.
 */
object LlamaCpp {

    private const val TAG = "LlamaCpp"

    init { System.loadLibrary("secondbrain_jni") }

    /**
     * Single dispatcher that owns every native call. Don't replace with
     * Dispatchers.IO — IO is multi-threaded and llama.cpp would race.
     */
    private val nativeDispatcher: CoroutineDispatcher =
        Executors.newSingleThreadExecutor { r ->
            Thread(r, "llama-native").apply { isDaemon = true }
        }.asCoroutineDispatcher()

    @Volatile private var handle: Long = 0L
    @Volatile private var initialized = false

    /** Live read of "is a GGUF currently loaded into memory?". Use this
     *  from any screen instead of caching a stale flag. */
    fun isLoaded(): Boolean = handle != 0L

    private external fun nativeInit()
    private external fun nativeLoadModel(path: String, nGpuLayers: Int, nCtx: Int): Long
    private external fun nativeGenerate(handle: Long, prompt: String, maxTokens: Int): String?
    private external fun nativeFree(handle: Long)
    private external fun nativeAbort()
    private external fun nativeGetLastStats(): String

    /** Idempotent. Loads ggml backends (Vulkan + CPU) into the process. */
    suspend fun init() = withContext(nativeDispatcher) {
        if (!initialized) {
            nativeInit()
            initialized = true
        }
    }

    /**
     * @param modelFile the GGUF on disk (must exist).
     * @param preferGpu when true, attempt full-layer GPU offload (Vulkan).
     *                  llama.cpp falls back to CPU automatically for any
     *                  layer Vulkan can't host. When false, force CPU-only.
     * @param nCtx     KV-cache context size in tokens.
     */
    suspend fun loadModel(
        modelFile: File,
        preferGpu: Boolean = true,
        nCtx: Int = 1024,
    ) = withContext(nativeDispatcher) {
        require(modelFile.exists()) { "Model file not found: ${modelFile.absolutePath}" }
        if (handle != 0L) {
            nativeFree(handle); handle = 0L
        }
        if (!initialized) { nativeInit(); initialized = true }

        // Phase 3c: Vulkan backend disabled at build time (see build.gradle.kts).
        // Even if preferGpu=true, llama.cpp falls back to CPU because no GPU
        // backend is compiled in. This still respects the user-facing toggle —
        // GPU support arrives in Phase 3d after the two-stage build is set up.
        val nGpuLayers = if (preferGpu) -1 else 0
        val started = System.nanoTime()
        handle = nativeLoadModel(modelFile.absolutePath, nGpuLayers, nCtx)
        val elapsedMs = (System.nanoTime() - started) / 1_000_000
        Log.i(TAG, "loadModel ok in ${elapsedMs}ms (preferGpu=$preferGpu, ctx=$nCtx; CPU until Phase 3d)")
        check(handle != 0L) { "nativeLoadModel returned 0 handle" }
    }

    /** Greedy completion. Throws if no model loaded. */
    suspend fun generate(prompt: String, maxTokens: Int = 256): String =
        withContext(nativeDispatcher) {
            check(handle != 0L) { "no model loaded; call loadModel() first" }
            val started = System.nanoTime()
            val out = nativeGenerate(handle, prompt, maxTokens) ?: ""
            val elapsedMs = (System.nanoTime() - started) / 1_000_000
            Log.i(TAG, "generate: ${out.length} chars in ${elapsedMs}ms")
            out
        }

    suspend fun free() = withContext(nativeDispatcher) {
        if (handle != 0L) {
            nativeFree(handle); handle = 0L
        }
    }

    /**
     * Signal an in-flight [generate] call to stop early. The native loop
     * checks the abort flag each token boundary and returns whatever it
     * has accumulated so far. Safe to call from any thread.
     */
    fun abort() {
        nativeAbort()
    }

    /**
     * Snapshot of the most recent (or in-progress) generate run's stats.
     * Safe to call any time, any thread — backed by std::atomics on the
     * native side.
     */
    fun getLastStats(): String = nativeGetLastStats()

    /**
     * **Hard reset** — wipes the loaded model. Used when soft abort
     * doesn't take within a deadline. Next inference will need a model
     * reload (a few hundred ms of mmap remap). Safe to call concurrently
     * with a stuck generate; the native call's `Session*` handle goes
     * away under it, the next decode will fault and the JNI exception
     * propagates as a Java RuntimeException.
     *
     * NOTE: this is a small footgun — if a thread is mid-decode when we
     * free, you'll get an undefined-behavior segfault risk. We accept
     * that tradeoff because the alternative is the user rebooting the
     * phone. Use sparingly, only after soft abort fails.
     */
    suspend fun forceUnload() = withContext(nativeDispatcher) {
        if (handle != 0L) { nativeFree(handle); handle = 0L }
    }
}
