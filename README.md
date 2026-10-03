# WarioLand4Recomp

A static recompilation of **Wario Land 4** (Game Boy Advance, US/EU) for Windows x64.

The Game Boy Advance CPU is an ARM7TDMI. This project translates the cartridge ROM into
C++ at build time and runs the result as an ordinary native x64 program, so the game
plays at native speed with no emulator in the loop. The GBA BIOS is recompiled the same
way and executed as code — it is never stubbed and never HLE'd on the correctness path.

**This repository contains no game code, no ROM and no BIOS.** The ROM is a build input you
supply locally; see [baserom.md](baserom.md) for the exact bytes required.

---

## Experimental Preview

```text
Experimental Preview
Full-game compatibility has not been exhaustively tested.
```

This is the project's own wording, quoted verbatim from the release-phase handoff notes
(§6). Only the behaviour listed under
[Status](#status--what-is-verified) and in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)
has been verified by a bounded, repeatable run. Everything else — later levels, bosses,
the endgame, edge cases, long play sessions — is **untested**, and no completion
percentage is claimed anywhere in this repository.

---

## Status — what is verified

`verified` means a bounded command exists and its evidence is named in
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md). It never means "the whole game works".

| | verified | evidence |
| --- | --- | --- |
| ROM / BIOS identity gate | yes — enforced before every route, build and boot | [baserom.md](baserom.md), [docs/ROM_IDENTITY.json](docs/ROM_IDENTITY.json), `tools/validation/check-identity.ps1` |
| Boot (recompiled BIOS entry path) | yes — 120-frame route | route `boot`, `logs/routes/boot-120-last.png` |
| BIOS logo, intro cutscene | yes — 120 / 720-frame routes | routes `bios-logo`, `intro-cutscene` |
| Attract demo, title, file select | yes | routes `attract` (3,600), `title` (5,400), `title-input` (6,000) |
| New game → difficulty menu → level entry | yes — 8,600-frame route | route `new-game`, `logs/routes/game-8600-last.png` |
| Host input reaches Wario inside a level and moves him | yes — the **only** pinned route that shows this | route `host-walk-13500` (13500 frames, `tests\input\gameplay-right.keyinput.txt`) |
| A / B / DOWN verbs (jump, punch, dash, crouch) | yes — each proved by an A/B frame comparison against a no-input control | routes `verb-jump-12090`, `verb-attack-13475`, `verb-dash-13500`, `verb-crouch-13500`; re-run by `tools/validation/verb-ab.ps1` |
| Taking damage | yes — `gHeartMeter.current` 4 → 3 at vblank 12,561, corroborated by HUD pixels | route `heartloss`, `logs/routes/heart-hud-compare.png` |
| Water reaction (the reaction axis is live) | yes — `gWarioData.reaction` = 1 at vblank 10,063, cleared at 10,095 | routes `reaction-water`, `reaction-water-end`; ten value-gated probes in `reaction-enum` |
| SRAM save → exit → restart → load | partly — the round trip passes as **state visibility**, not as a byte-for-byte match against a known-good save | routes `save-write` (12,000), `save-load` (6,000) |
| Determinism (same build, two processes) | yes — identical counters and byte-identical frames, headless vs windowed | routes `win-9000`, `win-19000`, `left-12139` |
| Dispatch coverage | reported honestly as `NOT_STATIC` — 7–13 **dynamic IWRAM** PCs remain, see [Coverage honesty](#coverage-honesty) | every run's coverage JSON, `recomp_coverage_AWAE.json` |
| Automated smoke route | yes — 7 cases | `tools/validation/smoke.ps1` |
| Audio (music + SFX) | **no** — the mixer output was measured on the attract route only; nothing was verified through a speaker | see [docs/VALIDATION.md](docs/VALIDATION.md) §7 |
| Player-driven room or level transition | **no** — no host-input route has changed the room; the transitions seen so far are the game's own attract demo | routes `explore-1`, `explore-2`, `door-1`, `switch-hunt`, `switch-hunt2`; positive control `demo-room` |
| Transformation (变身) under player control | **no** — none of the ten reaction values was reached by a host route | route `reaction-enum` |
| Completing a level, Boss, endgame | **no** — never run | — |

The full verified / measured-only / unverified matrix, with one evidence pointer per row
and the commands to reproduce them, is [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

---

## Requirements

You need the original cartridge image **and** the GBARecomp generator that performs the
translation. The generator is not vendored here; it is obtained from its public upstream
repository at a pinned commit and then built locally. Setup is one script, and the pinned
identity, the submodule revisions and this project's framework patches are all recorded in
[docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json). See [Build](#build).

| item | value |
| --- | --- |
| base ROM | `Wario Land 4 (USA, Europe).gba`, placed in the project root (the only `*.gba` there) |
| ROM size | 8,388,608 bytes (`0x00800000`, `0xFF`-padded) |
| ROM MD5 | `5fe47355a33e3fabec2a1607af88a404` |
| ROM SHA-1 | `b9fe05a8080e124b67bce6a623234ee3b518a2c1` |
| ROM SHA-256 | `d16c7bf6e62bb84049fff1b387108fbd1e6e2cd38ca994ab5310dd9cbf9ba414` |
| GBA BIOS | `bios/gba_bios.bin`, 16,384 bytes, SHA-1 `300c20df6731a33952ded8c436f7f186d25d3492` |
| save type | SRAM, 32,768 bytes (`SRAM_V112`, verified from the cartridge) |

The Japan release (`AWAJ`) is a different image and is not supported. Any hash mismatch
aborts the run — the project will not boot, generate or build against a ROM it cannot
identify.

Tooling (discovered, not hardcoded to a single location):

* **CMake** 3.20+ and **Ninja** (or the MSVC generator)
* **MinGW-w64 GCC** on `PATH` (GCC 16.1.0 was used here); override with `MINGW_ROOT` or
  `pwsh tools/regeneration/build-host.ps1 -Toolchain <mingw-root>`
* **SDL2 2.32+** development libraries, i.e. a prefix containing
  `x86_64-w64-mingw32/include/SDL2/SDL.h`; discovered from `.deps/sdl2`, from a sibling
  `_sdl2/SDL2-*/` directory next to this project, or from an MSYS2 prefix. Override with
  `build-host.ps1 -Sdl2Root <sdk>`
* **Python** 3.10+ for the validation tooling (standard library only)
* **PowerShell** 7 (`pwsh`) for every script in `tools/`

---

## Build

> **The framework source is fetched from upstream, not vendored here.** A fresh clone has
> no `reference/gbarecomp`; step 1 clones
> [mstan/gbarecomp](https://github.com/mstan/gbarecomp) at the commit pinned in
> [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json), checks out the three submodule
> revisions that commit requires, and applies this project's framework patches from
> `patches/gbarecomp/`. Those patches are small and necessary — they add the codegen tail
> macros the ARM core emits, the keypad-IRQ path, the `SRAM_F_V` save signature and a
> 64 KiB flash-size fix. `docs/FRAMEWORK_PIN.json` records every patch by SHA-256.
>
> Only the ROM and the BIOS are yours to supply; nothing else in the build is
> machine-specific.

```powershell
# 1. clone the framework at its pinned upstream commit, then apply the patches
pwsh tools/regeneration/setup-framework.ps1

# 2. build gba_recompile. regen.ps1 needs it, so this step is not optional
pwsh tools/regeneration/build-framework.ps1

# 3. translate ROM + BIOS into C++ under generated/
pwsh tools/regeneration/regen.ps1

# 4. build the host executable
pwsh tools/regeneration/build-host.ps1

# 5. run the smoke suite
pwsh tools/validation/smoke.ps1
```

Step 1 needs network access the first time; it refuses to run in place of an existing
`reference/gbarecomp` unless you pass `-Force`, and it re-verifies every patched file
against the SHA-1s recorded in `docs/FRAMEWORK_PIN.json`. `-VerifyOnly` re-checks an
existing checkout without touching it, and `-Build` folds steps 1 and 2 into one command.

The executable lands at `build/host/WarioLand4Recomp.exe`, together with the DLLs it needs
(`SDL2.dll` and the MinGW runtime `libgcc_s_seh-1.dll`, `libstdc++-6.dll`,
`libwinpthread-1.dll`).

`regen.ps1` clears `generated/cart` and `generated/bios` before generating, so a plain run
always produces a plain build. Add `-SymbolOverlay` to import decompilation names and data
extents as symbols; that path is behaviour-preserving and is proved by an A/B comparison
in [docs/VALIDATION.md](docs/VALIDATION.md).

`build-host.ps1 -Fresh` configures from scratch; `-Toolchain` and `-Sdl2Root` override the
discovered locations.

### Running it

```powershell
build\host\WarioLand4Recomp.exe --rom "Wario Land 4 (USA, Europe).gba" --bios bios\gba_bios.bin
```

Without `--rom` / `--bios` the runtime falls back to a modal file dialog, which blocks any
unattended run. Always pass both, or drop `rom.cfg` / `bios.cfg` sidecars next to the
executable. This is a framework defect recorded as **F1** in
[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

### Controls

The default bindings match the rest of the recomp ecosystem, so they are the same before
any configuration file exists:

| GBA button | key |
| --- | --- |
| A | `X` |
| B | `Z` |
| L | `C` |
| R | `V` |
| Start | `Enter` |
| Select | `Right Shift` |
| D-pad | arrow keys |
| Fullscreen | `Alt`+`Enter` |
| Pause | `Shift`+`P` |
| Turbo | `Tab` |
| Performance display | `F` |

They are rebindable: the runtime reads `keybinds.ini` (`[player1]`, scancode names) for the
button map and `config.ini` (`[KeyMap]`) for the system hotkeys. Both files are optional
and live next to the runtime's launcher configuration.

### Saves

The runtime uses SRAM. Unless `--save-path` is given, the save file is the ROM path with
its extension replaced by `.sav` — for the standard setup, `Wario Land 4 (USA, Europe).sav`
next to the ROM. The save type itself is never taken from a filename: it is detected from
the cartridge image (`SRAM_V112` at ROM offset `0x283EF8`) and the runtime reports
`save=SRAM signature=SRAM_V` at boot.

### Windowed vs headless

Every route above is headless by default. A **windowed** run reads the real keyboard, and
in this game any host button held during the attract demo re-phases it — so a windowed run
must be driven with an explicit input replay (recorded as **G10** in
[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)). `run-route.ps1` is headless unless `-Window`
is passed; `-Window` plus `-FrameDumpStart`/`-FrameDumpCount` is how mid-run filmstrips are
captured.

---

## How it works

```
Wario Land 4 ROM  ──gba_recompile──▶  generated/cart/*.cpp   (8 shards, one dispatch table)
GBA BIOS         ──gba_recompile──▶  generated/bios/*
                                        │
                                        ▼
   src/main.cpp ──▶ gbarecomp runtime ──▶ WarioLand4Recomp.exe
```

* **Static recompilation, not emulation.** Each ROM function becomes a native function. A
  per-instruction resume table (`generated/cart/dispatch_table.cpp`) keeps hand-written C,
  BL jumps and interrupt returns connected.
* **BIOS is sacred.** SWIs, IRQs and DMA run through recompiled BIOS bytes through the same
  dispatch table. The boot intro is a presentation choice, never a fast-forward.
* **Honest self-healing.** A dispatch miss is never silent. The interpreter may bridge it
  for the rest of the session, but it is logged loudly, recompiled on the fly, and written
  to `recomp_master_misses_AWAE.toml.frag` for review. Misses are never auto-merged into
  `game.toml`; a human reviews them, merges the real ones, regenerates and re-runs.
* **Coverage honesty is load-bearing.** The runtime prints what was interpreted and what
  was native. This project is currently `NOT_STATIC`; that number is reported honestly in
  every run rather than rounded up.

### Coverage honesty

The remaining dispatch misses are 7–13 **dynamic IWRAM addresses** in
`0x03007D0C..0x03007D90` — code the cartridge generates onto its own stack at runtime. With
a cold cache the strict gate aborts on exactly that stub
(`pc=0x03007D1C`, `runtime_arm: STRICT_STATIC dispatch miss …`), not on undiscovered
cartridge code: the 62 cartridge-ROM misses were reviewed and merged. No static declaration
can cover the dynamic ones, which is a framework limitation (**F6**), not a configuration
error. Declaring that address range explicitly was tried and reverted: it made every long
route hang.

---

## Validation

| script | what it does |
| --- | --- |
| `tools/validation/smoke.ps1` | the release gate: boot, attract, title input, controller A/B, save round trip |
| `tools/validation/check-identity.ps1` | ROM / BIOS / decomp / framework / toolchain identity audit |
| `tools/validation/run-route.ps1` | runs one bounded route, verifies the ROM hash first, writes coverage JSON + miss fragment into `logs/routes/` |
| `tools/release/publication-audit.ps1` | the publication boundary: no ROM, no BIOS, no generated code, no personal paths, no secrets |

```powershell
pwsh tools/validation/run-route.ps1 -Tag boot-120 -Frames 120
pwsh tools/validation/run-route.ps1 -Tag new-game -Frames 12000 -InputReplay tests/input/new-game.keyinput.txt
pwsh tools/validation/smoke.ps1 -Quick      # skips the three 13,500-frame routes
pwsh tools/release/publication-audit.ps1 -Json
```

`tools/validation/smoke.ps1` runs a fixed set of seven cases and checks three things per
case: the process exited 0 and wrote a coverage JSON, every dispatch miss is inside the
documented dynamic set, and the final frame is byte-identical to the recorded one. The
recorded expectations live in `tests/routes/smoke-expectations.json`; after a change that
legitimately alters a frame, re-record with `tools/validation/smoke.ps1 -Record` and
**review the diff** instead of hand-editing the file.

The route catalog — frame budget, window mode, extra arguments and the observation each
route must produce — is [tests/routes/routes.csv](tests/routes/routes.csv);
`docs/VALIDATION.md` §4 describes them and §5 carries the numbered rules learned from
failures. Input traces in `tests/input/` are frame-indexed KEYINPUT registers in active-low
form, so a route's inputs are exact and reproducible. Always confirm a replay was actually
loaded: `Select-String -Path logs\routes\<tag>.log -Pattern 'input_replay='` must read
`input_replay=ENABLED path="…" events=N`; `DISABLED` means the trace was dropped and the
run proves nothing.

Windowed runs can also be observed from outside the process (`-Window -Frames N -TcpObserve
<port>`), which is how the coverage questions in `docs/KNOWN_ISSUES.md` were answered.

---

## Repository layout

| path | publishable | contents |
| --- | --- | --- |
| `src/` | yes | the game-specific host layer — `main.cpp`, 18 lines |
| `game.toml` | yes | per-game recompiler configuration: identity gate, code copies, jump table, extra functions |
| `symbols/` | yes | IWRAM symbol map and decomp-derived symbol metadata |
| `tools/regeneration/` | yes | build and regeneration scripts, including `setup-framework.ps1` (framework acquisition) |
| `tools/validation/` | yes | routes, probes, smoke suite |
| `tools/release/` | yes | the publication audit |
| `patches/gbarecomp/` | yes | this project's framework patches, applied by `setup-framework.ps1` and SHA-256-pinned |
| `tests/` | yes | the route table, expectations and input traces |
| `docs/` | yes | identity record, framework pin, progress, known issues, validation rules, compatibility matrix |
| `reference/gbarecomp/` | no | framework checkout created by `setup-framework.ps1` (upstream commit + local patches) |
| `reference/tomlplusplus/toml.hpp` | yes | single vendored MIT header, the only tracked file under `reference/` |
| `third_party/` | no | optional local clone of the decompilation, used as text — not needed for the shortest build, and its `.git` and `tools/agbcc` submodule are not kept |
| `generated/` | no | ROM-derived C++ — regenerate, never commit, never hand-edit |
| `build/`, `logs/`, `recomp_cache/` | no | build trees, run logs, self-heal cache |
| `roms/`, `saves/`, `bios/` | no | the ROM, the save and the BIOS dump |

`generated/` is an artifact, not source. Problems are fixed in the framework,
`game.toml` or the symbol metadata and then regenerated; a hand-edited
`generated/recompiled_*.cpp` is a defect, not a fix.

---

## Known limitations

The short list; every entry is quoted with its evidence in
[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

| id | summary |
| --- | --- |
| **F1** | no non-interactive asset picker; without `--rom`/`--bios` the runtime opens a modal dialog and blocks |
| **F2** | the self-heal compiler is hardcoded to `C:/msys64/mingw64/bin/g++.exe`; set `GBARECOMP_HEAL_CXX` |
| **F6** | dynamic RAM code cannot be declared, so coverage can never read `FULLY_STATIC` |
| **G10** | in a windowed run the live SDL keyboard can silently re-phase the attract demo — always drive a windowed route with an explicit input replay |
| **G11** | 262 named decompilation functions are unplaced because placing them needs a decompilation build (`arm-none-eabi-objdump`/`agbcc`), which this environment does not have |
| **G14** | the player-driven route is confined to room 0, and no host-input route has produced a room change (the game's own demo does traverse room 0 — see G27) |
| **G20** | rooms are linked by a 12-byte exit-record table, and the byte that selects the link index is ordinary writable IWRAM |
| **G21** | every Thumb literal-load offset in this ROM is decoded two different ways — a high-priority open framework question |
| **G23** | the attract demo injects its own button stream into the input buffer by DMA3 from inside the room loader |
| **G24** | 变身 is `gWarioData.reaction` at `0x03001898`, and no host-input route has reached any transforming value |
| **G25** | a fresh save has exactly one world-map node, and the ROM's own graph agrees |
| **G29** | RESOLVED — the framework is no longer a local-only snapshot. It is cloned from `mstan/gbarecomp` at a pinned public commit and patched by `tools/regeneration/setup-framework.ps1`; see [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) and [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json) |
| retraction | route `traverse-13500` demonstrates the **attract demo's** traversal, not host input (round 34, 2026-10-08). It stays pinned because its frames are stable, but it proves nothing about input — `host-walk-13500` is the case that does. |

---

## Licence

This project's own hand-written material is under the **PolyForm Noncommercial License
1.0.0** — see [LICENSE](LICENSE).

It is a recompilation project and is **not** a ROM distribution: the ROM, the BIOS and
all ROM-derived generated code stay local and are not committed, published or redistributed
here. You must supply your own legally obtained cartridge image.

Third-party components (GBARecomp, toml++, SDL2, the MinGW runtime, and the decompilation
used as reference) keep their own licences — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Documentation

| document | contents |
| --- | --- |
| [baserom.md](baserom.md) | the required ROM/BIOS bytes and every identity gate |
| [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) | what is verified, what is measured only, and what is untested — with an evidence pointer per row |
| [docs/ROM_IDENTITY.json](docs/ROM_IDENTITY.json) | the raw identity record |
| [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json) | the pinned framework revision and dependency hashes |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | framework (F) and game (G) issues with evidence |
| [docs/VALIDATION.md](docs/VALIDATION.md) | the validation doctrine, the numbered rules and the evidence index |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | every third-party component, its licence and the notice you must ship |
| [tests/routes/routes.csv](tests/routes/routes.csv) | every registered route and what it must observe |
