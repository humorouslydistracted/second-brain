cmake_minimum_required(VERSION 3.22.1)
project("secondbrain_jni" LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Force Release for the native inference path even if AGP set Debug for
# the APK as a whole. Debug-mode llama.cpp/ggml is 20-50× slower than
# Release on arm64 — empirically observed as multi-minute hangs on
# Pixel 7 prompt prefill (build #14-#16). The Kotlin/Java side stays
# debuggable; only this C++ subtree gets optimized.
if(NOT CMAKE_BUILD_TYPE OR CMAKE_BUILD_TYPE STREQUAL "Debug")
    set(CMAKE_BUILD_TYPE "Release" CACHE STRING "" FORCE)
    message(STATUS "secondbrain_jni: forcing CMAKE_BUILD_TYPE=Release")
endif()
# Make sure the optimizer flags actually land — some toolchains zero out
# CMAKE_CXX_FLAGS_RELEASE on Android cross-compile.
set(CMAKE_C_FLAGS_RELEASE   "-O3 -DNDEBUG" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG" CACHE STRING "" FORCE)
message(STATUS "secondbrain_jni: build type = ${CMAKE_BUILD_TYPE}")

# ----------------------------------------------------------------------------
# Fetch llama.cpp at configure time. Pinned to a known-good commit so a
# silent upstream API break can't bite us. Bump deliberately when needed.
# ----------------------------------------------------------------------------
include(FetchContent)
FetchContent_Declare(
    llama_cpp
    GIT_REPOSITORY https://github.com/ggml-org/llama.cpp.git
    # b3938 (Sept 2024) predates Qwen3 architecture support, which landed
    # in llama.cpp around late April 2025. Bumped to b6500 (~mid-2025)
    # so a Qwen3 GGUF can actually be loaded. The JNI is rewritten to
    # match the newer API (model→vocab split for tokenize/detokenize/eog,
    # 2-arg llama_batch_get_one, etc.) — see llama_jni.cpp.
    GIT_TAG        b6500
    GIT_SHALLOW    TRUE
)

# Suppress llama.cpp's own examples/server/tests; we only want the libs.
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER   OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL           OFF CACHE BOOL "" FORCE)

# Vulkan-on-Android: NDK r26+ ships Vulkan headers and libvulkan, AND a
# matching glslc shader compiler under <ndk>/shader-tools/<host>/. CMake's
# stock FindVulkan looks for glslc on PATH and fails because the NDK's
# glslc isn't on PATH at build time. Point at it explicitly so
# find_package(Vulkan) succeeds in the llama.cpp ggml/Vulkan subproject.
if(ANDROID_NDK)
    # Use CMAKE_HOST_* — when cross-compiling to Android the plain
    # WIN32 / APPLE variables describe the *target* (which is Android),
    # not the build host. The shader-tools binary we need is the host's.
    if(CMAKE_HOST_WIN32)
        set(_glslc_host_dir "windows-x86_64")
        set(_glslc_exe "${ANDROID_NDK}/shader-tools/${_glslc_host_dir}/glslc.exe")
    elseif(CMAKE_HOST_APPLE)
        set(_glslc_host_dir "darwin-x86_64")
        set(_glslc_exe "${ANDROID_NDK}/shader-tools/${_glslc_host_dir}/glslc")
    else()
        set(_glslc_host_dir "linux-x86_64")
        set(_glslc_exe "${ANDROID_NDK}/shader-tools/${_glslc_host_dir}/glslc")
    endif()
    message(STATUS "Looking for NDK glslc at: ${_glslc_exe}")
    if(EXISTS "${_glslc_exe}")
        set(Vulkan_GLSLC_EXECUTABLE "${_glslc_exe}" CACHE FILEPATH "" FORCE)
        message(STATUS "Pointing FindVulkan at NDK glslc: ${_glslc_exe}")
    else()
        message(WARNING "NDK glslc not found at ${_glslc_exe} — Vulkan find_package will likely fail")
    endif()
endif()

FetchContent_MakeAvailable(llama_cpp)

# ----------------------------------------------------------------------------
# Our JNI shim. Tiny — load model, generate a string, free.
# ----------------------------------------------------------------------------
add_library(secondbrain_jni SHARED
    llama_jni.cpp
)

target_link_libraries(secondbrain_jni
    PRIVATE
        llama
        log
        android
)
