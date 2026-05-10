// Minimal JNI bridge: load a GGUF, run one prompt with greedy sampling,
// return the completion. Not thread-safe by design — all calls must come
// from a single dispatcher on the Kotlin side.
//
// API surface (matches LlamaCpp.kt):
//   nativeInit()                                 -> void   (call once at process start)
//   nativeLoadModel(path, nGpuLayers, nCtx)      -> long   (handle, 0 on failure)
//   nativeGenerate(handle, prompt, maxTokens)    -> string (raw completion)
//   nativeFree(handle)                           -> void
//
// `nGpuLayers = -1` means offload all layers to GPU; 0 means CPU-only.
// Errors throw a Java RuntimeException with a useful message.
//
// API target: llama.cpp tag `b6500` (mid-2025). Notes vs the older b3938
// API (which we tried first and abandoned because it predates Qwen3
// support):
//   - tokenize/detokenize/eog now take `const llama_vocab*` instead of
//     `const llama_model*`. Fetch the vocab once via llama_model_get_vocab.
//   - `llama_load_model_from_file` is now `llama_model_load_from_file`.
//   - `llama_new_context_with_model` is now `llama_init_from_model`.
//   - `llama_free_model` is now `llama_model_free`.
//   - `llama_batch_get_one(tokens, n_tokens)` is the new 2-arg form;
//     position is implicit from the context's KV cache state.
//   - `ggml_backend_load_all()` registers all compiled-in backends.

#include <jni.h>
#include <android/log.h>
#include <string>
#include <vector>
#include <cstring>
#include <memory>
#include <atomic>
#include <chrono>
#include <thread>

#include "llama.h"

#define TAG "secondbrain_jni"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

namespace {

struct Session {
    llama_model*       model = nullptr;
    llama_context*     ctx   = nullptr;
    const llama_vocab* vocab = nullptr;
};

// Atomic flag the Kotlin side toggles via nativeAbort() to cancel an
// in-flight generate loop. Single-session app so a global is fine.
static std::atomic<bool> g_abort_flag{false};

/**
 * llama.cpp polls this from inside its inner work loops; returning true
 * tells it to bail out of the current decode. Plain function (not a
 * lambda) so the C function-pointer field assignment is unambiguous —
 * lambdas compile fine here on most ABIs but a real symbol removes any
 * doubt about calling convention or capture state.
 */
static bool secondbrain_abort_callback(void * /*user_data*/) {
    return g_abort_flag.load();
}

// Per-run instrumentation so the Kotlin side (and request_log) sees
// exactly where time went. Reset at the start of each generate(); read
// either while running (live progress) or after (final stats).
struct GenStats {
    std::atomic<int64_t> tokenize_us       {0};   // total time for prompt tokenize
    std::atomic<int64_t> prefill_us        {0};   // first llama_decode (full prompt batch)
    std::atomic<int64_t> decode_us_total   {0};   // sum of every llama_decode after prefill
    std::atomic<int>     decode_calls      {0};
    std::atomic<int>     tokens_out        {0};
    std::atomic<int>     prompt_tokens     {0};
    std::atomic<bool>    aborted           {false};
    std::atomic<bool>    in_flight         {false};
    std::atomic<int64_t> wallclock_start_us{0};   // when generate() entered
};
static GenStats g_stats;

static int64_t now_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

void throw_runtime(JNIEnv* env, const char* msg) {
    jclass cls = env->FindClass("java/lang/RuntimeException");
    if (cls != nullptr) env->ThrowNew(cls, msg);
}

std::string jstring_to_utf8(JNIEnv* env, jstring js) {
    if (js == nullptr) return {};
    const char* cstr = env->GetStringUTFChars(js, nullptr);
    std::string out(cstr ? cstr : "");
    if (cstr) env->ReleaseStringUTFChars(js, cstr);
    return out;
}

} // namespace

extern "C" JNIEXPORT void JNICALL
Java_com_secondbrain_app_LlamaCpp_nativeInit(JNIEnv* /*env*/, jobject /*thiz*/) {
    ggml_backend_load_all();
    llama_backend_init();
    LOGI("backend init done");
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_secondbrain_app_LlamaCpp_nativeLoadModel(
        JNIEnv* env,
        jobject /*thiz*/,
        jstring jPath,
        jint nGpuLayers,
        jint nCtx) {

    std::string path = jstring_to_utf8(env, jPath);
    if (path.empty()) {
        throw_runtime(env, "model path is empty");
        return 0;
    }
    // Hardware sanity log — captured once per load, visible in logcat
    // and useful when comparing devices.
    LOGI("hw: hardware_concurrency=%u  abi=arm64-v8a (build-time)",
         std::thread::hardware_concurrency());
    LOGI("loading model: %s  (n_gpu_layers=%d, n_ctx=%d)", path.c_str(), nGpuLayers, nCtx);

    auto session = std::make_unique<Session>();

    auto mparams = llama_model_default_params();
    mparams.n_gpu_layers = nGpuLayers;        // -1 = all, 0 = CPU only
    mparams.use_mmap     = true;
    mparams.use_mlock    = false;             // mlock can fail on Android due to limits
    session->model = llama_model_load_from_file(path.c_str(), mparams);
    if (session->model == nullptr) {
        std::string msg = "llama_model_load_from_file failed for: " + path;
        LOGE("%s", msg.c_str());
        throw_runtime(env, msg.c_str());
        return 0;
    }
    session->vocab = llama_model_get_vocab(session->model);
    if (session->vocab == nullptr) {
        llama_model_free(session->model);
        throw_runtime(env, "llama_model_get_vocab returned null");
        return 0;
    }

    auto cparams = llama_context_default_params();
    cparams.n_ctx           = nCtx > 0 ? nCtx : 512;
    // n_batch must be >= the largest single batch we ever submit to
    // llama_decode. We submit the full prompt (commonly 80-300 tokens)
    // as one batch, so 512 is a safe upper bound. Reducing this below
    // the prompt size in build #15 caused decode to crash on submit.
    cparams.n_batch         = 512;
    cparams.n_threads       = 4;      // pin to Pixel 7 big cluster
    cparams.n_threads_batch = 4;

    // Wire the abort flag into llama.cpp's internal callback so a Cancel
    // can interrupt work even mid-decode (not just between decodes).
    cparams.abort_callback      = secondbrain_abort_callback;
    cparams.abort_callback_data = nullptr;

    session->ctx = llama_init_from_model(session->model, cparams);
    if (session->ctx == nullptr) {
        llama_model_free(session->model);
        throw_runtime(env, "llama_init_from_model failed");
        return 0;
    }

    // Dump llama.cpp's compiled-in feature flags so we can verify the
    // build picked up dotprod/i8mm/etc. instead of the slow scalar path.
    // Output appears in logcat under tag "secondbrain_jni" once per load.
    {
        const char* sysinfo = llama_print_system_info();
        if (sysinfo) {
            LOGI("llama system info: %s", sysinfo);
        }
    }

    LOGI("model loaded ok");
    return reinterpret_cast<jlong>(session.release());
}

extern "C" JNIEXPORT void JNICALL
Java_com_secondbrain_app_LlamaCpp_nativeFree(
        JNIEnv* /*env*/, jobject /*thiz*/, jlong handle) {
    auto* session = reinterpret_cast<Session*>(handle);
    if (session == nullptr) return;
    if (session->ctx)   llama_free(session->ctx);
    if (session->model) llama_model_free(session->model);
    delete session;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_secondbrain_app_LlamaCpp_nativeGenerate(
        JNIEnv* env,
        jobject /*thiz*/,
        jlong handle,
        jstring jPrompt,
        jint maxTokens) {

    auto* session = reinterpret_cast<Session*>(handle);
    if (session == nullptr || session->ctx == nullptr || session->vocab == nullptr) {
        throw_runtime(env, "invalid session handle");
        return nullptr;
    }
    std::string prompt = jstring_to_utf8(env, jPrompt);

    // ---- reset KV cache ----
    // Each generate() is treated as a stateless call: we never want
    // tokens from a prior submission contributing to this run's KV
    // budget. Without this, after ~5 successful requests at ~130
    // tokens each, the KV cache (n_ctx=512) fills and the next
    // llama_decode bails with rc=1. Observed in device logs as
    // "llama_decode failed (rc=1) at token 0" cascading after
    // several good requests.
    if (auto* mem = llama_get_memory(session->ctx)) {
        llama_memory_clear(mem, /*data=*/true);
    }

    // ---- reset stats for this run ----
    g_stats.tokenize_us.store(0);
    g_stats.prefill_us.store(0);
    g_stats.decode_us_total.store(0);
    g_stats.decode_calls.store(0);
    g_stats.tokens_out.store(0);
    g_stats.prompt_tokens.store(0);
    g_stats.aborted.store(false);
    g_stats.in_flight.store(true);
    g_stats.wallclock_start_us.store(now_us());

    // -------- tokenize (b6500: vocab-based) --------
    auto t_tok_start = now_us();
    int n_prompt = -llama_tokenize(session->vocab,
                                    prompt.c_str(), (int32_t)prompt.size(),
                                    nullptr, 0,
                                    /*add_special=*/true, /*parse_special=*/true);
    std::vector<llama_token> prompt_tokens(n_prompt);
    if (llama_tokenize(session->vocab,
                       prompt.c_str(), (int32_t)prompt.size(),
                       prompt_tokens.data(), (int32_t)prompt_tokens.size(),
                       /*add_special=*/true, /*parse_special=*/true) < 0) {
        g_stats.in_flight.store(false);
        throw_runtime(env, "tokenization failed");
        return nullptr;
    }
    g_stats.tokenize_us.store(now_us() - t_tok_start);
    g_stats.prompt_tokens.store((int)prompt_tokens.size());
    LOGI("tokenize done: %d prompt tokens in %lld us",
         (int)prompt_tokens.size(), (long long)g_stats.tokenize_us.load());

    // -------- sampler: greedy (matches Python `do_sample=False`) --------
    auto sparams = llama_sampler_chain_default_params();
    sparams.no_perf = true;
    llama_sampler* smpl = llama_sampler_chain_init(sparams);
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());

    // -------- decode + sample loop --------
    g_abort_flag.store(false);  // fresh run
    std::string out;
    out.reserve(1024);

    LOGI("generate start: prompt=%d tokens, max_new=%d", (int)prompt_tokens.size(), (int)maxTokens);

    // b6500: 2-arg llama_batch_get_one(tokens, n_tokens). Position is tracked
    // internally by the context's KV cache.
    llama_batch batch = llama_batch_get_one(prompt_tokens.data(),
                                            (int32_t)prompt_tokens.size());

    int generated = 0;
    while (generated < maxTokens) {
        if (g_abort_flag.load()) {
            LOGI("generate aborted by user at %d tokens", generated);
            g_stats.aborted.store(true);
            g_stats.in_flight.store(false);
            llama_sampler_free(smpl);
            // Return whatever we have so far — caller decides what to do.
            return env->NewStringUTF(out.c_str());
        }

        // Time each llama_decode call individually. The FIRST one is
        // prompt prefill (large batch, expensive), every subsequent one
        // is single-token decode. Splitting these out tells us where
        // the wallclock actually goes.
        auto t_dec0 = now_us();
        int dec_rc = llama_decode(session->ctx, batch);
        int64_t dec_us = now_us() - t_dec0;
        if (dec_rc != 0) {
            // If abort fired during the decode (callback returned true),
            // llama.cpp bails out with a non-zero rc. That's not a real
            // error — return what we have so far.
            if (g_abort_flag.load()) {
                LOGI("decode interrupted by abort_callback at %d tokens", generated);
                g_stats.aborted.store(true);
                g_stats.in_flight.store(false);
                llama_sampler_free(smpl);
                return env->NewStringUTF(out.c_str());
            }
            g_stats.in_flight.store(false);
            llama_sampler_free(smpl);
            char msg[128];
            snprintf(msg, sizeof(msg), "llama_decode failed (rc=%d) at token %d", dec_rc, generated);
            throw_runtime(env, msg);
            return nullptr;
        }
        if (g_stats.decode_calls.load() == 0) {
            g_stats.prefill_us.store(dec_us);
            LOGI("prefill done: %d tokens in %lld us (%.1f tok/s)",
                 (int)prompt_tokens.size(), (long long)dec_us,
                 prompt_tokens.size() * 1e6 / std::max<int64_t>(dec_us, 1));
        } else {
            g_stats.decode_us_total.fetch_add(dec_us);
        }
        g_stats.decode_calls.fetch_add(1);

        llama_token next = llama_sampler_sample(smpl, session->ctx, -1);
        if (llama_vocab_is_eog(session->vocab, next)) break;

        char piece[256];
        int  piece_len = llama_token_to_piece(session->vocab, next, piece, sizeof(piece),
                                              /*lstrip=*/0, /*special=*/true);
        if (piece_len < 0) {
            g_stats.in_flight.store(false);
            llama_sampler_free(smpl);
            throw_runtime(env, "llama_token_to_piece failed");
            return nullptr;
        }
        out.append(piece, piece_len);

        // Feed the just-sampled token back as a length-1 batch
        batch = llama_batch_get_one(&next, 1);
        ++generated;
        g_stats.tokens_out.store(generated);

        // Per-16-token decode-rate log: useful in logcat to confirm we
        // ARE decoding (vs spinning). The Kotlin side polls g_stats for
        // live UI updates more frequently.
        if ((generated & 0xF) == 0) {
            int64_t total = g_stats.decode_us_total.load();
            if (total > 0) {
                double tps = (double)generated * 1e6 / (double)total;
                LOGI("decode progress: %d tokens, %.2f tok/s avg", generated, tps);
            }
        }
    }

    int64_t total_us = now_us() - g_stats.wallclock_start_us.load();
    LOGI("generate done: %d tokens, prefill=%lld us, decode_total=%lld us, total=%lld us",
         generated,
         (long long)g_stats.prefill_us.load(),
         (long long)g_stats.decode_us_total.load(),
         (long long)total_us);

    g_stats.in_flight.store(false);
    llama_sampler_free(smpl);
    return env->NewStringUTF(out.c_str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_secondbrain_app_LlamaCpp_nativeAbort(JNIEnv* /*env*/, jobject /*thiz*/) {
    g_abort_flag.store(true);
    LOGI("abort requested");
}

/**
 * Returns a JSON string with the latest run's stats. Safe to call mid-
 * inference (atomics) — Kotlin polls this every 500ms while sending=true
 * to update Home with live progress.
 */
extern "C" JNIEXPORT jstring JNICALL
Java_com_secondbrain_app_LlamaCpp_nativeGetLastStats(JNIEnv* env, jobject /*thiz*/) {
    char buf[512];
    int64_t now = now_us();
    int64_t start = g_stats.wallclock_start_us.load();
    int64_t elapsed = (start > 0) ? (now - start) : 0;
    int n = snprintf(buf, sizeof(buf),
        "{"
        "\"in_flight\":%s,"
        "\"aborted\":%s,"
        "\"prompt_tokens\":%d,"
        "\"tokens_out\":%d,"
        "\"tokenize_us\":%lld,"
        "\"prefill_us\":%lld,"
        "\"decode_us_total\":%lld,"
        "\"decode_calls\":%d,"
        "\"elapsed_us\":%lld,"
        "\"hw_concurrency\":%u,"
        "\"n_threads\":6"
        "}",
        g_stats.in_flight.load() ? "true" : "false",
        g_stats.aborted.load()   ? "true" : "false",
        g_stats.prompt_tokens.load(),
        g_stats.tokens_out.load(),
        (long long)g_stats.tokenize_us.load(),
        (long long)g_stats.prefill_us.load(),
        (long long)g_stats.decode_us_total.load(),
        g_stats.decode_calls.load(),
        (long long)elapsed,
        std::thread::hardware_concurrency()
    );
    (void)n;
    return env->NewStringUTF(buf);
}
