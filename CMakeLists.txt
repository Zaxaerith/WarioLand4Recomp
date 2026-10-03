# ---------------------------------------------------------------------------
# WarioLand4Recomp — host executable.
#
# Shape (deliberately thin, following the framework's own guidance and the
# working sibling integration):
#
#   reference/gbarecomp      pinned, read-only framework source (add_subdirectory)
#   generated/cart           cartridge translation   (tools/regen.ps1, local-only)
#   generated/bios           BIOS translation        (tools/regen.ps1, local-only)
#   src/main.cpp             the entire game-specific host layer
#
# Everything else — window, presentation, audio device, input, save handling,
# launcher, TCP debug server, CPU/bus/PPU lifecycle — is framework code.
#
# Configure example (MinGW + Ninja, matching the sibling projects):
#   cmake -S . -B build/host -G Ninja -DCMAKE_BUILD_TYPE=Release \
#         -DCMAKE_C_COMPILER=<mingw>/gcc.exe -DCMAKE_CXX_COMPILER=<mingw>/g++.exe
#   cmake --build build/host
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.20)
project(WarioLand4Recomp C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# ---------------------------------------------------------------- pinned sources
set(GBARECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/reference/gbarecomp"
    CACHE PATH "Pinned framework checkout")
if(NOT EXISTS "${GBARECOMP_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR
        "Missing framework snapshot at ${GBARECOMP_ROOT}. "
        "See docs/FRAMEWORK_PIN.json for the pinned revision.")
endif()

set(GBARECOMP_TOMLPP_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/reference/tomlplusplus"
    CACHE PATH "Vendored toml++ headers (see docs/FRAMEWORK_PIN.json)")

set(GBARECOMP_GENERATED_BIOS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/generated/bios"
    CACHE PATH "Local BIOS translation")

# ------------------------------------------------------------------- generated
file(GLOB CART_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/generated/cart/*.cpp")
if(NOT CART_SOURCES)
    message(FATAL_ERROR
        "No cartridge translation found in generated/cart. "
        "Run tools/regen.ps1 first (it verifies ROM and framework identity).")
endif()
if(NOT EXISTS "${GBARECOMP_GENERATED_BIOS_DIR}/bios_recompiled.cpp")
    message(FATAL_ERROR
        "No BIOS translation found in ${GBARECOMP_GENERATED_BIOS_DIR}. "
        "Run tools/regen.ps1 first.")
endif()

# ------------------------------------------------------------------------ SDL2
# Soft dependency: the framework compiles host_window.cpp as a stub when SDL2 is
# absent, which is fine for headless work but not for a playable build. We only
# HINT at the SDK root; the framework owns the actual find_path/find_library
# (see reference/gbarecomp/CMakeLists.txt, "SDL2 — soft dependency").
# Resolve the SDK root even when the caller already set
# GBARECOMP_MINGW_PREFIX_UNIX: the same value is later used to stage SDL2.dll
# next to the executable, so it must not stay empty just because the framework's
# cache variable was supplied on the command line.
set(_gba_sdl2_candidates
    "${GBARECOMP_MINGW_PREFIX_UNIX}"
    "$ENV{SDL2_ROOT}"
    "${CMAKE_CURRENT_SOURCE_DIR}/build/deps"
    "${CMAKE_CURRENT_SOURCE_DIR}/.deps/sdl2/x86_64-w64-mingw32"
    "C:/msys64/mingw64"
)
# Sibling shared SDK (the local dependency search order in `AGENT_PROMPT.md` (removed before release)
# prefers an already-present copy over a download).
file(GLOB _gba_sdl2_siblings "${CMAKE_CURRENT_SOURCE_DIR}/../_sdl2/SDL2-*/x86_64-w64-mingw32")
list(APPEND _gba_sdl2_candidates ${_gba_sdl2_siblings})
set(_gba_sdl2_root "")
foreach(_cand IN LISTS _gba_sdl2_candidates)
    if(_cand AND EXISTS "${_cand}/include/SDL2/SDL.h")
        set(_gba_sdl2_root "${_cand}")
        break()
    endif()
endforeach()

if(NOT GBARECOMP_MINGW_PREFIX_UNIX)
    if(_gba_sdl2_root)
        set(GBARECOMP_MINGW_PREFIX_UNIX "${_gba_sdl2_root}" CACHE PATH
            "SDK root used by the framework to locate SDL2" FORCE)
    else()
        message(WARNING
            "WarioLand4Recomp: no SDL2 SDK found (set -DSDL2_ROOT=<...>/x86_64-w64-mingw32). "
            "host_window will compile as a no-op stub.")
    endif()
endif()
if(_gba_sdl2_root)
    message(STATUS "WarioLand4Recomp: SDL2 SDK root ${_gba_sdl2_root}")
endif()

if(NOT GBARECOMP_MINGW_RUNTIME_BIN AND MINGW)
    get_filename_component(_gba_mingw_bin "${CMAKE_CXX_COMPILER}" DIRECTORY)
    set(GBARECOMP_MINGW_RUNTIME_BIN "${_gba_mingw_bin}" CACHE PATH
        "Directory holding libgcc_s_seh-1.dll / libstdc++-6.dll / libwinpthread-1.dll")
endif()

# ------------------------------------------------------------------- framework
add_subdirectory("${GBARECOMP_ROOT}" framework EXCLUDE_FROM_ALL)

# ------------------------------------------------------------------- executable
add_executable(WarioLand4Recomp src/main.cpp ${CART_SOURCES})
target_link_gbarecomp_runtime_stack(WarioLand4Recomp)

# The generated shards are translation output, not hand-maintained code: compile
# them cheaply. -g0 keeps the 70+ MB of shards out of the debug info.
set(_gba_shards ${CART_SOURCES})
list(FILTER _gba_shards INCLUDE REGEX "/recompiled_[0-9]+\\.cpp$")
if(_gba_shards)
    if(MSVC)
        set_source_files_properties(${_gba_shards} PROPERTIES COMPILE_OPTIONS "/O1")
    else()
        set_source_files_properties(${_gba_shards} PROPERTIES COMPILE_OPTIONS "-O1;-g0")
    endif()
endif()

# Development convenience: double-clickable build output with its runtime DLLs.
gbarecomp_stage_mingw_runtime(WarioLand4Recomp)

if(_gba_sdl2_root AND EXISTS "${_gba_sdl2_root}/bin/SDL2.dll")
    add_custom_command(TARGET WarioLand4Recomp POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${_gba_sdl2_root}/bin/SDL2.dll"
            "$<TARGET_FILE_DIR:WarioLand4Recomp>/SDL2.dll"
        VERBATIM)
endif()

list(LENGTH _gba_shards _gba_shard_count)
message(STATUS "WarioLand4Recomp: cartridge shards = ${_gba_shard_count}")
