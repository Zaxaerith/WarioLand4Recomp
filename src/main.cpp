// Wario Land 4 (GBA) — host integration entry point.
//
// This is the entire game-specific host layer: the framework runtime owns the
// window, audio device, input mapping, save handling, launcher UI, debug TCP
// server and the ARM CPU/bus/PPU lifecycle. See
// reference/gbarecomp/src/runtime/runtime.h.
//
// The two builtin values below let a released binary run with no sibling
// game.toml next to it. They MUST equal docs/ROM_IDENTITY.json.

#include "runtime.h"

int main(int argc, char** argv) {
    gbarecomp::RunOptions options;
    options.builtin_game_name = "Wario Land 4";
    options.builtin_rom_sha1 = "b9fe05a8080e124b67bce6a623234ee3b518a2c1";
    return gbarecomp::run_game(argc, argv, options);
}
