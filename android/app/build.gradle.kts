plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.secondbrain.app"
    compileSdk = 34
    ndkVersion = "30.0.14904198"

    defaultConfig {
        applicationId = "com.secondbrain.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-phase2"

        // arm64 only — Pixel 7 is arm64. Keeps APK lean (~10 MB native code).
        ndk {
            abiFilters += "arm64-v8a"
        }

        externalNativeBuild {
            cmake {
                arguments += listOf(
                    "-DANDROID_STL=c++_shared",
                    // GPU offload deferred to Phase 3d. The Vulkan backend
                    // requires a two-stage build (host vulkan-shaders-gen,
                    // then Android arm64 lib) which clashes with AGP's
                    // single-pass externalNativeBuild. CPU-only ships now.
                    "-DGGML_VULKAN=OFF",
                    "-DGGML_OPENMP=OFF",
                    "-DLLAMA_BUILD_TESTS=OFF",
                    "-DLLAMA_BUILD_EXAMPLES=OFF",
                    "-DLLAMA_BUILD_SERVER=OFF",
                    "-DLLAMA_CURL=OFF",
                    // ⚠ CRITICAL ⚠ — without this the inference path
                    // is unusably slow. AGP's debug variant passes
                    // CMAKE_BUILD_TYPE=Debug to CMake, which compiles
                    // llama.cpp/ggml at -O0 with assert()s on every
                    // matmul. Empirically this is 20-50× slower than
                    // -O3 and was the root cause of the "stuck on
                    // decoding for 100+ s on an 82-token prompt"
                    // observation in build #14/16. Forcing Release
                    // here keeps the Kotlin/Java side debuggable
                    // while making the C++ inference path run at
                    // proper speed.
                    "-DCMAKE_BUILD_TYPE=Release",
                )
                // Match cppFlags to the build-type override above and
                // enable Pixel 7's Tensor G2 fast Q4_K_M kernels.
                // armv8.2-a+dotprod+fp16 is the safe baseline for Pixel
                // 7 (Tensor G2 supports up to armv8.6 with i8mm, but
                // dotprod alone gives the big Q4_K_M speedup).
                cppFlags += listOf(
                    "-std=c++17",
                    "-O3",
                    "-DNDEBUG",
                    "-march=armv8.2-a+dotprod+fp16",
                )
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "4.1.2"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        debug {
            // Don't strip native libs in debug so we can attach lldb if needed.
            isJniDebuggable = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures {
        compose = true
    }

    packaging {
        resources.excludes += setOf(
            "META-INF/AL2.0",
            "META-INF/LGPL2.1",
        )
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.02"))
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("androidx.navigation:navigation-compose:2.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("org.json:json:20240303")
    // Phase 3c: on-device sentence embeddings (all-MiniLM-L6-v2). The
    // tokenizer is hand-written Kotlin so we avoid HF tokenizers' Rust JNI
    // and the +12 MB APK cost that comes with it.
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.17.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
