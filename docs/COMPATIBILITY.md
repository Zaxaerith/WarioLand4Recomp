# Compatibility — what is verified, and what is not

```text
Experimental Preview
Full-game compatibility has not been exhaustively tested.
```

This file is the honest matrix behind that sentence. It exists so that no claim in
[README.md](../README.md) has to be taken on trust: every row below names the bounded run
that produced it and the file that holds the evidence.

## How to read this file

| column | meaning |
| --- | --- |
| **axis** | one behaviour a player or a maintainer would care about |
| **state** | `verified` = a bounded, repeatable command exists and it was run; `measured` = data was collected, but the thing a player experiences was not verified; `not verified` = no such command exists |
| **evidence** | the route tag in [tests/routes/routes.csv](../tests/routes/routes.csv), the log/artifact it writes under `logs/routes/` (local-only, git-ignored), or the document that records the measurement |
| **reproduce** | the command. All of them are bounded (a frame budget) and headless; none needs interaction |

Two rules of interpretation:

* **`verified` is scoped to what was run.** "New game is verified" means the scripted
  18-event replay reaches a level and Wario is on screen there. It does not mean any other
  way of starting a game works.
* **`not verified` is not a bug report.** A later level being unverified means nobody has
  run it — not that it is broken. Full levels, bosses, the endgame and long sessions are
  left to real players, which is exactly what the release-phase handoff asks for.

Everything below was measured on the one image in [baserom.md](../baserom.md) (US/EU
`AWAE`), on Windows x64, with the host executable built by
`tools/regeneration/build-host.ps1`. Nothing here was tested on another platform, another
region's ROM, or another toolchain.

---

## 1. Verified

### Identity and build

| axis | state | evidence | reproduce |
| --- | --- | --- | --- |
| ROM identity is re-checked before every route | verified | `docs/ROM_IDENTITY.json`, `baserom.md`; `tools/validation/run-route.ps1` fails with `ROM SHA-256 mismatch.` otherwise | `pwsh tools/validation/run-route.ps1 -Tag boot-120 -Frames 120` |
| ROM + BIOS + decomp + framework + toolchain identity, as one audit | verified | `tools/validation/check-identity.ps1` | `pwsh tools/validation/check-identity.ps1` |
| The runtime refuses to boot a ROM it was not built for | verified | `src/main.cpp` carries `builtin_rom_sha1 = b9fe05a8…`; the runtime re-hashes its input | launch the exe with a different `*.gba` |
| Generation is reproducible from the pinned framework revision | verified | `docs/FRAMEWORK_PIN.json` (schema 2): upstream `mstan/gbarecomp` at `477e3d12dd0920a4961d58ba625ec2afe505c1fb`, three pinned submodules, three local patches with SHA-256s; `setup-framework.ps1 -VerifyOnly` re-checks every patched file's blob SHA-1 | `pwsh tools/regeneration/setup-framework.ps1 -VerifyOnly`, then `pwsh tools/regeneration/regen.ps1` |
| The decompilation symbol overlay changes no behaviour | verified | A/B measurement, `docs/VALIDATION.md` (rule 20); same PC and same vblank with and without names | routes `heartloss` vs `heartloss-ovl`; `pwsh tools/regeneration/regen.ps1 -SymbolOverlay` |

### Boot, title, attract

| axis | state | evidence | reproduce |
| --- | --- | --- | --- |
| The recompiled entry vector runs (120 frames, exits 0, writes coverage) | verified | route `boot`; `logs/routes/boot-120-last.png` | `run-route.ps1 -Tag boot-120 -Frames 120` |
| The recompiled BIOS renders the GAME BOY / Nintendo logo | verified | route `bios-logo` (cold cache: `dispatch_misses=0`) | `run-route.ps1 -Tag bios-logo -Frames 120` |
| The cartridge's own intro scene renders | verified | route `intro-cutscene`, 720 frames | `run-route.ps1 -Tag intro-cutscene -Frames 720` |
| Attract/demo playback with no host input at all | verified | route `attract`, 3,600 frames | `run-route.ps1 -Tag attract -Frames 3600` |
| The demo's camera crosses room boundaries under the game's own control | verified | route `attract-deep-19000` — coin counter climbs `000050 → 000990 → 001320 → 003150` across rooms | `run-route.ps1 -Tag attract-deep-19000 -Frames 19000` |
| Title screen renders and is stable across independent builds | verified | route `title`, 5,400 frames; `logs/routes/tl-5400-last.png` byte-identical across builds | `run-route.ps1 -Tag title -Frames 5400` |
| The title reacts to a scripted START press | verified | route `title-input`, `tests/input/start-press.keyinput.txt` | `run-route.ps1 -Tag title-input-6000 -Frames 6000 -InputReplay tests\input\start-press.keyinput.txt` |

### Input, gameplay and the control A/Bs

| axis | state | evidence | reproduce |
| --- | --- | --- | --- |
| New game → file select → difficulty → a level is entered | verified | route `new-game`, 8,600 frames, `logs/routes/game-8600-last.png` (Wario inside the golden temple level) | `run-route.ps1 -Tag new-game -Frames 8600 -InputReplay tests\input\new-game.keyinput.txt` |
| **Host input reaches Wario inside a level and moves him** | verified — and this is the only pinned route that shows it | route `host-walk-13500`; Wario spawns at raw `(2016,1279)` at vblank ≈11,603 and holding RIGHT carries him to `x=2337` | `run-route.ps1 -Tag host-walk-13500 -Frames 13500 -InputReplay tests\input\gameplay-right.keyinput.txt` |
| Wario's walkable range in that room, end to end | measured | route `pos-sample`: raw `x` 1923 @12020 → 2337 @15000, i.e. ≈75 px; the LEFT walk is blocked (166 units in 1,400 frames) | `run-route.ps1 -Tag pos-sample -Frames 20000 -InputReplay tests\input\explore-1.keyinput.txt -AbortMemAddr 0x030018AA -AbortMinFrame <frame>` |
| Jump (A) | verified | route `verb-jump-12090` vs `ctrl-idle-12090`: 1,227/38,400 pixels differ, bbox `x=106..133 y=80..151` | `run-route.ps1 -Tag verb-jump -Frames 12090 -InputReplay tests\input\verb-jump.keyinput.txt` |
| Punch (B tapped) | verified | route `verb-attack-13475` vs `ctrl-idle-13475`: 1,706/38,400 pixels differ, bbox `x=98..172 y=111..152` | `run-route.ps1 -Tag verb-attack -Frames 13475 -InputReplay tests\input\verb-attack.keyinput.txt` |
| Dash (B held) | verified | route `verb-dash-13500` vs `ctrl-idle-13500`: 1,238/38,400 differ, bbox `x=107..189 y=118..152` | `run-route.ps1 -Tag verb-dash -Frames 13500 -InputReplay tests\input\verb-dash.keyinput.txt` |
| Crouch (DOWN held) | verified | route `verb-crouch-13500` vs `ctrl-idle-13500`: 716/38,400 differ, bbox `x=106..134 y=81..152` | `run-route.ps1 -Tag verb-crouch -Frames 13500 -InputReplay tests\input\verb-crouch.keyinput.txt` |
| All four verb pairs re-checked in one command | verified | `tools/validation/verb-ab.ps1` | `pwsh tools/validation/verb-ab.ps1` |
| A negative result is kept as a negative (`UP` while walking right is ignored) | verified | route `verb-up-right`: 0 of 38,400 pixels differ from `ctrl-right` | `run-route.ps1 -Tag verb-up-right -Frames 13500 -InputReplay tests\input\verb-up-right.keyinput.txt` |
| Taking damage | verified | route `heartloss` aborts at the writing instruction: `pc=0x080135C4` `addr=0x03001910` (`gHeartMeter`) `value=3` at vblank 12,561; HUD corroboration `logs/routes/heart-hud-compare.png` | `run-route.ps1 -Tag heartloss -Frames 13600 -InputReplay tests\input\gameplay-idle.keyinput.txt -AbortMemAddr 0x03001910 -AbortMemValue 3 -AbortMinFrame 9000 -TraceDumpDepth 200` |
| A reaction value is written and later cleared | verified | routes `reaction-water` (`reaction`=1 at vblank 10,063) and `reaction-water-end` (=0 at 10,095) | `run-route.ps1 -Tag reaction-water -Frames 19500 -AbortMemAddr 0x03001898 -AbortMinFrame 9000` |
| The ten transformation values are absent from the whole demo — proved value by value, not by sampling | verified | route `reaction-enum` (one gated run per value 2..11, no abort in any); `logs/routes/reaction-probe-summary.json` | see `tests/routes/routes.csv` row `reaction-enum` |

### Persistence

| axis | state | evidence | reproduce |
| --- | --- | --- | --- |
| A save file is created by the game | verified | route `save-write`: `save_flushed` ×6, file 32,768 B with 32,768 non-`0xFF` bytes (62 distinct values) | `run-route.ps1 -Tag save-write -Frames 12000 -InputReplay tests\input\new-game.keyinput.txt -SavePath logs\routes\h-save.sav` |
| A **separate process** loads it and shows it | verified — as state visibility, not as a byte-for-byte match against a known-good save | route `save-load`: `save_loaded 32768/32768`; 1,352/38,400 pixels differ from the same-frame no-save run, entirely in the SAVE A row (`x=40..199 y=11..62`); repeating the run is byte-identical | `run-route.ps1 -Tag save-load -Frames 6000 -InputReplay tests\input\start-press.keyinput.txt -SavePath logs\routes\h-save.sav -KeepSave` |
| Save type comes from the cartridge, not a filename | verified | `SRAM_V112` at ROM offset `0x283EF8`; the runtime reports `save=SRAM signature=SRAM_V` | any route's boot banner |

### Determinism and coverage honesty

| axis | state | evidence | reproduce |
| --- | --- | --- | --- |
| Two independent processes agree byte for byte | verified | `attract-deep-19000` at frame 19,000, three headless runs, identical frame hash `ba51e420…` | `run-route.ps1 -Tag det-noinput-a -Frames 19000 -DumpLastFrame` twice |
| Headless and windowed agree at the same guest frame | verified | routes `win-9000` (frame 9,000) and `win-19000` (frame 19,000) vs the headless frames; route `left-12139` vs windowed `f_012139.png` | `run-route.ps1 -Tag win-19000 -Frames 19100 -Window -FrameDumpStart 19000 -FrameDumpCount 1` |
| A windowed run can be made immune to the live keyboard | verified | route `noinput-win-19000`: `tests/input/noinput.keyinput.txt` is a no-op trace (`0,0x03FF`) that keeps the replay path active | `run-route.ps1 -Tag noinput-win-19000 -Frames 19100 -Window -InputReplay tests\input\noinput.keyinput.txt -FrameDumpStart 19000 -FrameDumpCount 1` |
| Coverage is reported honestly rather than rounded up | verified | every run writes a coverage JSON; the project reports `NOT_STATIC` with the 7–13 dynamic IWRAM PCs in `0x03007D0C..0x03007D90` listed (`recomp_coverage_AWAE.json`) | any route; read the exit banner |
| A green smoke run means those 7 cases still behave | verified — the suite passes as of the release phase: **7/7 PASS** (`boot-120` 0 misses, `attract-3600` 7, `title-input-6000` 10, `ctrl-idle-13500` 13, `host-walk-13500` 13, `traverse-13500` 11, plus the `save-write` → `save-load` round trip) | `logs/release/smoke-full.txt`; expectations in `tests/routes/smoke-expectations.json`; 7 cases, ~5 min (`-Quick` skips the three 13,500-frame ones) | `pwsh tools/validation/smoke.ps1` |

---

## 2. Measured, but not verified

These have numbers attached, and the numbers are real, but they are not the thing a player
would experience.

| axis | what was actually done | why it is not `verified` |
| --- | --- | --- |
| Audio (music + SFX) | the mixer capture ring was read on the no-input attract route (`audio-gameplay-audio.json`, frame 13,067) | no output device was ever used; nothing was listened to, and no route plays gameplay audio under host control |
| Cross-mode capture trust | headless vs windowed frame equality at two frames (9,000 and 19,000) | it proves the capture path does not perturb the guest at those two frames, not that it never can |
| Decompilation symbol coverage | 3,327 of 3,589 named functions placed; 262 unplaced (including the whole `m4a_asm.s` sound driver and ~200 sprite-AI routines); the overlay is opt-in, not the default | placement is a naming aid; it says nothing about whether untested code paths run correctly, and the overlay path is not what ships by default |
| Room/level structure | room 0 is 41×23 cells (2,624×1,472 px), 24 sprite slots of `0x2C` bytes, one tile-attribute gate at `0x0806D3C0` | these are measurements of the map and the changer, not a demonstration that a player can leave the room |

---

## 3. Not verified

| axis | status | where the evidence gap is recorded |
| --- | --- | --- |
| A player-driven room or level transition | not verified. No host-input route has changed the room. The routine-level negatives are `explore-1` (20,000 frames, `gCurrentRoom` written exactly zero times after frame 12,000), `explore-2` (24,000), `door-1` (17,000), and the instruction-level negatives `switch-hunt` / `switch-hunt2` (20,000 each). The positive control `demo-room` proves the watchpoint works (`pc=0x0806B92C`, value 2, vblank 8,852 — the **demo's** transition) | [docs/VALIDATION.md](VALIDATION.md) §7; [docs/KNOWN_ISSUES.md](KNOWN_ISSUES.md) G14, G20, G23 |
| A transformation (变身) reached by host input | not verified. `gWarioData.reaction` (`0x03001898`) is only ever written with value 1 (WATER) by the demo, and the ten transforming values are absent from all 19,500 frames | [docs/KNOWN_ISSUES.md](KNOWN_ISSUES.md) G24 |
| Completing a level, any Boss, the endgame | not verified — never run. The deepest route is `attract-deep-19000`, and it is the demo playing, not a player | this file; the release-phase handoff leaves full levels to real players |
| Gameplay audio under host control, on a real device | not verified | [docs/VALIDATION.md](VALIDATION.md) §7 |
| Save file byte-for-byte equivalence with a known-good save | not verified. The round trip proves visible state, not byte equality, and there is no cartridge-derived reference save to compare against | [docs/VALIDATION.md](VALIDATION.md) §7 |
| Any other ROM region (the Japan `AWAJ` release) | not supported and not tested. `game.toml` carries no metadata for it | [baserom.md](../baserom.md) |
| Any platform other than Windows x64 | not supported. Every route is a Windows host run; the framework is consumed as pinned | [docs/FRAMEWORK_PIN.json](FRAMEWORK_PIN.json) |
| Any SDL/audio device, fullscreen, gamepad, or touch behaviour | not verified — every route is headless except the framedump runs | [docs/VALIDATION.md](VALIDATION.md) §7 |
| Long sessions (saves over multiple sessions, suspend/resume, self-heal cache reuse across many runs) | not verified. Cache warmth is known to change the counters without changing behaviour (`cc-title-900` cold: `healed_native=0`; warm: `healed_native=201`) | [docs/VALIDATION.md](VALIDATION.md) §2 |

---

## 4. What a green smoke run does and does not mean

`pwsh tools/validation/smoke.ps1` is the release gate, and it is a **regression** gate: it
answers "did this change break the seven cases we know about?".

It checks, per case: exit code 0 plus a coverage JSON; every dispatch miss inside the
documented dynamic set; and a final frame byte-identical to the recorded one.

The last full run is recorded in `logs/release/smoke-full.txt` and reads **SMOKE: PASS** —
all seven cases green, with misses `boot-120` 0, `attract-3600` 7, `title-input-6000` 10,
`ctrl-idle-13500` 13, `host-walk-13500` 13, `traverse-13500` 11, and the persistence round
trip passing. Note that `title-input-6000` reports 10 misses, not the 7 quoted in older
notes; the allowed set is whatever `tests/routes/smoke-expectations.json` records.

It does **not** mean the game is compatible. Untouched by it: every level after the one the
`new-game` replay enters, every Boss, anything a human would do with a controller, audio
through a speaker, and any Windows/display configuration other than the headless default.
The expectations file is evidence — when a frame legitimately changes,
`smoke.ps1 -Record` then **review the diff**; it must never be hand-edited.

## 5. Change log for this matrix

| date | change |
| --- | --- |
| 2026-10-08 (round 34) | route `traverse-13500` was moved from "host input causes the room change" to a retraction: an abort on `0x03001844` (`gButtonsHeld`) caught the attract demo writing LEFT at vblank 9,655 while the replay held RIGHT, and `gf_tfunc_080103CC` is the demo's input player. `host-walk-13500` was added as the case that genuinely shows host input moving Wario. |
| 2026-10-01 (checkpoint 36) | room 0 is traversable — by the game's own demo at vblank 9,201 — and the room changer is `func_806D3C0`, not the previously named function. The open question is the player-driven case, not the mechanism. |
| 2026-09-30 (validation freeze) | audio, cross-mode capture, decomp symbol coverage and save semantics were explicitly moved to "measured, not verified" in [docs/VALIDATION.md](VALIDATION.md) §7. |
