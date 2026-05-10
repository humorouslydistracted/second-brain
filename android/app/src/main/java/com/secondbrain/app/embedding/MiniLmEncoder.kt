package com.secondbrain.app.embedding

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.util.Log
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.LongBuffer
import java.util.concurrent.Executors
import kotlin.math.sqrt

/**
 * On-device sentence embedder.
 *
 * Loads `all-MiniLM-L6-v2` from a sideloaded ONNX file plus a hand-written
 * BERT WordPiece tokenizer. Output is a 384-dim L2-normalized FloatArray
 * — same shape the Python `sentence-transformers` library would produce.
 *
 * Pooling and normalization happen in Kotlin (not in the ONNX graph) so a
 * future tokenizer/model swap doesn't require re-export.
 *
 * Single-thread dispatcher: ONNX Runtime sessions are not safe to call
 * concurrently from arbitrary Kotlin coroutines. All `encode` calls go
 * through [nativeDispatcher].
 */
object MiniLmEncoder {
    private const val TAG = "MiniLmEncoder"
    const val EMBEDDING_DIM = 384

    const val MODEL_FILENAME = "minilm.onnx"
    const val VOCAB_FILENAME = "minilm_vocab.txt"
    const val CONFIG_FILENAME = "minilm_tokenizer_config.json"

    private val nativeDispatcher: CoroutineDispatcher =
        Executors.newSingleThreadExecutor { r ->
            Thread(r, "minilm-native").apply { isDaemon = true }
        }.asCoroutineDispatcher()

    @Volatile private var env: OrtEnvironment? = null
    @Volatile private var session: OrtSession? = null
    @Volatile private var tokenizer: WordPieceTokenizer? = null
    @Volatile private var loaded = false
    @Volatile private var loadError: String? = null

    /** Live read; safe to call from any thread. */
    fun isLoaded(): Boolean = loaded

    fun status(modelDir: File): Status {
        val model = File(modelDir, MODEL_FILENAME)
        val vocab = File(modelDir, VOCAB_FILENAME)
        val cfg = File(modelDir, CONFIG_FILENAME)
        return Status(
            loaded = loaded,
            loadError = loadError,
            modelExists = model.exists(),
            vocabExists = vocab.exists(),
            configExists = cfg.exists(),
            modelPath = model.absolutePath,
        )
    }

    suspend fun load(modelDir: File): Result<Unit> = withContext(nativeDispatcher) {
        if (loaded) return@withContext Result.success(Unit)
        runCatching {
            val model = File(modelDir, MODEL_FILENAME)
            val vocab = File(modelDir, VOCAB_FILENAME)
            val cfg = File(modelDir, CONFIG_FILENAME)
            require(model.exists()) { "missing $model" }
            require(vocab.exists()) { "missing $vocab" }
            require(cfg.exists()) { "missing $cfg" }

            val e = OrtEnvironment.getEnvironment()
            val opts = OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(2)
                setInterOpNumThreads(1)
                setOptimizationLevel(OrtSession.SessionOptions.OptLevel.BASIC_OPT)
            }
            val s = e.createSession(model.absolutePath, opts)
            val tk = WordPieceTokenizer.load(vocab, cfg)

            env = e; session = s; tokenizer = tk
            loaded = true; loadError = null
            Log.i(TAG, "loaded ok: model=${model.length()}B vocab=${vocab.length()}B")
            Unit  // ensure runCatching infers Result<Unit>, not Result<Int> from Log.i
        }.onFailure {
            loaded = false; loadError = it.message ?: it.javaClass.simpleName
            Log.e(TAG, "load failed", it)
        }
    }

    /** Returns null when not loaded. Caller decides fallback (lexical-only). */
    suspend fun encode(text: String): FloatArray? = withContext(nativeDispatcher) {
        if (!loaded) return@withContext null
        val tk = tokenizer ?: return@withContext null
        val s = session ?: return@withContext null
        val e = env ?: return@withContext null

        val encoded = tk.encode(text)
        val seqLen = encoded.ids.size
        val shape = longArrayOf(1L, seqLen.toLong())

        val idsTensor = OnnxTensor.createTensor(e, LongBuffer.wrap(encoded.ids), shape)
        val maskTensor = OnnxTensor.createTensor(e, LongBuffer.wrap(encoded.attentionMask), shape)
        // BERT-family models (incl. all-MiniLM-L6-v2) expose three inputs.
        // `token_type_ids` is the sentence-segment marker; for single
        // sentence embedding it's just an all-zero vector, but the model
        // still requires it as a named input.
        val typeIdsTensor: OnnxTensor? = if (s.inputNames.contains("token_type_ids")) {
            OnnxTensor.createTensor(e, LongBuffer.wrap(LongArray(seqLen)), shape)
        } else null

        try {
            val inputs = buildMap<String, OnnxTensor> {
                put("input_ids", idsTensor)
                put("attention_mask", maskTensor)
                typeIdsTensor?.let { put("token_type_ids", it) }
            }
            s.run(inputs).use { results ->
                // Output 0 is last_hidden_state, shape [1, seq_len, 384]
                val raw = results.get(0).value
                @Suppress("UNCHECKED_CAST")
                val arr = raw as Array<Array<FloatArray>>
                val seq = arr[0]                                  // (seq_len, 384)
                val mask = encoded.attentionMask
                val pooled = FloatArray(EMBEDDING_DIM)
                var validCount = 0f
                for (t in 0 until seqLen) {
                    if (mask[t] == 0L) continue
                    validCount += 1f
                    val tok = seq[t]
                    for (d in 0 until EMBEDDING_DIM) pooled[d] += tok[d]
                }
                if (validCount == 0f) return@withContext null
                for (d in 0 until EMBEDDING_DIM) pooled[d] /= validCount
                l2Normalize(pooled)
                return@withContext pooled
            }
        } finally {
            idsTensor.close(); maskTensor.close(); typeIdsTensor?.close()
        }
    }

    /**
     * Cosine similarity for L2-normalized vectors == dot product. Caller
     * is responsible for ensuring both inputs are L2-normalized (we always
     * are; we normalize in [encode] and store the result verbatim).
     */
    fun cosine(a: FloatArray, b: FloatArray): Float {
        if (a.size != b.size) return 0f
        var s = 0f
        for (i in a.indices) s += a[i] * b[i]
        return s
    }

    private fun l2Normalize(v: FloatArray) {
        var sum = 0.0
        for (f in v) sum += f * f
        val norm = sqrt(sum).toFloat()
        if (norm < 1e-12f) return
        for (i in v.indices) v[i] = v[i] / norm
    }

    data class Status(
        val loaded: Boolean,
        val loadError: String?,
        val modelExists: Boolean,
        val vocabExists: Boolean,
        val configExists: Boolean,
        val modelPath: String,
    )
}
