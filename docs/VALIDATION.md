# Validation

What "validated" means in this repository, which commands produce the evidence,
and which claims are deliberately *not* made.

## 1. Doctrine

* **The ROM and a trusted emulator are the behavioural authority.** The
  recompiled C++ is a *derived build artifact*: it is allowed to be wrong, and it
  is proven right by comparison, never by inspection.
* **Evidence is a file with a hash, not an impression.** Every claim in this
  document points at a path under `logs/routes/` or `tests/`.
* **Unverified is stated as unverified** (`build: PASS / title: NOT TESTED`
  rather than an optimistic summary).
* Nothing here is an execution oracle for the decompilation work: the decomp is
  used for symbols and knowledge only. It is not an execution oracle.

## 2. The acceptance gate (honest form)

`GBARECOMP_STRICT_STATIC=1` — abort on the first dispatch miss — is the gate we
*want*, and it is run as a route (`title-strict`). It **cannot pass** while
framework issue F6 stands, because the cartridge generates code on its own stack
and executes it (see `docs/KNOWN_ISSUES.md` F6/G5). After the G6 and G7 triages
this is the *only* remaining reason: with a cold cache the strict gate on a
900-frame title route now aborts at

```text
runtime_arm: STRICT_STATIC dispatch miss for pc=0x03007D1C (thumb) — interpreter and overlay fallback are disabled. Add reviewed static discovery/code-copy metadata and regenerate.
```

i.e. on the dynamic stack stub, not on any undiscovered cartridge code. (Use
`-ColdCache`; with a warm `recomp_cache` the gate can trip on a reloaded overlay
instead, which is G5.) The gate actually applied to a route is therefore:

1. **No new miss class.** The route's miss set must be a subset of the documented
   dynamic set (`0x03007D0C`, `0x03007D18`, `0x03007D1C`, `0x03007D24`,
   `0x03007D2C`, `0x03007D30`, `0x03007D34`, `0x03007D3C`, `0x03007D4C`,
   `0x03007D70`, `0x03007D84`, `0x03007D88`, `0x03007D90` — the cartridge's
   stack-executed stubs, F6). A miss outside that set fails the route. Boot/title
   routes hit the first seven; gameplay routes hit all thirteen. The 62
   cartridge-ROM misses that gameplay used to add were triaged into `game.toml`
   on 2026-09-30 (G6), so this rule covers gameplay again. The deepest route in
   the repo — the no-input attract demo driven to 19,000 frames — hit **four
   further** cartridge PCs (`0x0802A258`, `0x0802A26E`, `0x0802A656`,
   `0x0802A680`, all `interior-label` of already-dispatched functions), which were
   reviewed and merged the same day (G9); that route now reports exactly 11 of
   the 13 dynamic PCs and nothing else.
2. **Determinism.** Two independent processes, each starting from the same
   zeroed save and a cold self-heal cache, must produce identical counters and
   **byte-identical** dumped frames — *and the presentation mode is part of the
   claim*. Measured 2026-09-30 at guest frame 19,000 on the no-input attract demo:
   three headless runs are byte-identical (`ba51e420…`), a **windowed framedump
   run driven by an explicit input replay** is byte-identical to them
   (`noinput-win-19000-frames/f_019000.png`), and two windowed runs without a
   replay also matched — but a third windowed run without a replay
   (`damage-dump`) was on a different demo phase entirely (`17ea7de1…`: the level-1
   "B" hall with 001230 coins instead of the level-2 beach with 000660,
   37,376 / 38,400 pixels different). A window polls the real keyboard, and the
   attract demo aborts the moment any host button is held
   (`DemoInputPlayback(): if (… || gButtonsHeld != 0) { gButtonsPressed =
   START_BUTTON; }`), so a windowed no-input run is **not trustworthy by
   construction**: drive it with `tests/input/noinput.keyinput.txt`
   (`docs/KNOWN_ISSUES.md` G10). The counter pair `interpreted_insns` /
   `native_calls` announces the divergence (1,312,902 / 51,582 on the contaminated
   19,299-frame run versus 1,317,222 / 135,985 on every clean 19,000-frame run).
3. **Behaviour.** The route reaches the screen the catalog expects, and the exit
   log shows `unmapped=0 io_unhandled=0` (no access outside the memory map, no
   unhandled I/O).

A cold self-heal cache is required for (1) and (2): a warmed `recomp_cache`
makes `healed_native`/`native_calls` non-zero without changing behaviour
(`docs/KNOWN_ISSUES.md` G5). `run-route.ps1 -ColdCache` gives a run an empty
cache directory via `GBARECOMP_HEAL_CACHE`. Measured on the same route:
`cc-title-900` (cold) = `healed_native=0 native_calls=0 distinct_misses=7
interpreted_insns=802940`; the warm run = `healed_native=201`, same behaviour and
same frame.

## 3. How to produce the evidence

```powershell
# 1. Regenerate (verifies ROM SHA-1/SHA-256, the BIOS SHA-1 and the pinned
#    framework tree identity before writing anything)
tools/regeneration/regen.ps1

# 2. Build the pinned framework out-of-source, then the host
tools/regeneration/build-framework.ps1
tools/regeneration/build-host.ps1        # -> build/host/WarioLand4Recomp.exe

# 3. Routes
tools/validation/run-route.ps1 -Tag title       -Frames 5400 -DumpLastFrame
tools/validation/run-route.ps1 -Tag title-input -Frames 6000 -DumpLastFrame `
    -InputReplay tests\input\start-press.keyinput.txt
tools/validation/run-route.ps1 -Tag title-strict -Frames 900 -StrictStatic   # expected to FAIL (F6)

# 3b. Gameplay and control (priority E). --input-replay is passed through the
#     environment, not the command line, so it never appears in the printed argv.
tools/validation/run-route.ps1 -Tag game-13500 -Frames 13500 -DumpLastFrame `
    -InputReplay tests\input\gameplay-idle.keyinput.txt
tools/validation/run-route.ps1 -Tag ctrl-right -Frames 13500 -DumpLastFrame `
    -InputReplay tests\input\gameplay-right.keyinput.txt
tools/validation/run-route.ps1 -Tag ctrl-idle  -Frames 13500 -DumpLastFrame `
    -InputReplay tests\input\gameplay-idle.keyinput.txt    # the A/B control
tools/validation/run-route.ps1 -Tag cc-title-900 -Frames 900 -ColdCache        # coverage, not cache

# 4. Compare the A/B frames pixel by pixel (no image library needed):
#    Add-Type -AssemblyName System.Drawing; GetPixel(x,y).ToArgb() over 240x160.

# 4b. Mid-run filmstrip: WHEN did the screen change, not just whether it did.
#     The runtime dumps consecutive frames from inside its windowed per-frame
#     loop, so -Window is required and present-in-place is switched off for you
#     (docs/KNOWN_ISSUES.md G8). --tcp cannot be used here: it returns before the
#     input-replay loader (F8).
tools/validation/run-route.ps1 -Tag strip-left -Frames 12160 -Window `
    -InputReplay tests\input\probe-left.keyinput.txt `
    -FrameDumpStart 12040 -FrameDumpCount 100      # -> logs/routes/strip-left-frames/f_012040.png …
tools/validation/frame-strip.ps1 -Dir logs\routes\strip-left-frames -Every 5

# 4c. Audio (TCP debug server; the framework has no headless audio dump)
tools/validation/audio-probe.ps1 -Tag audio-title -WaitFrame 5300

# 4d. Sparse filmstrip of a NO-INPUT route over TCP (F8: an input route cannot
#     be driven this way). One run, one screenshot per mark:
tools/validation/tcp-filmstrip.ps1 -Tag attract-strip -Frames 20000 `
    -Marks '3000,4500,6000,7500,9000,10500,12000,13500,15000,16500,18000,19000' `
    -Port 19961

# 4e. Cross-mode determinism: the same guest frame must come out byte-identical
#     whether it was produced headless or by the windowed framedump.
tools/validation/run-route.ps1 -Tag left-12139 -Frames 12139 -DumpLastFrame `
    -InputReplay tests\input\probe-left.keyinput.txt      # == logs/routes/strip-left-frames/f_012139.png

# 4f. Guest memory instead of pixels: snapshot IWRAM at a list of frames from ONE
#     run, then diff the series to find the guest's own variables (health, coins).
#     TCP is legal here because the attract demo needs no input (F8).
tools/validation/tcp-snapshot.ps1 -Tag snap-demo -Frames 19000 -First 1000 `
    -Every 500 -Space iwram -Port 19971        # -> logs/routes/snap-demo-iwram/*.bin
python tools/validation/snapshot-diff.py --dir logs/routes/snap-demo-iwram

# 4g. Read the HUD's heart row out of already-captured frames (health, no guessing):
tools/validation/hud-hearts.ps1 -Pattern 'f_*.png' -Dir logs\routes\damage-dump-frames `
    -Csv logs/routes/damage-dump-hearts.csv

# 4h. Named guest variables. The reference decomp's linker script pins every IWRAM
#     global to an explicit offset, so it is a name -> 0x0300xxxx map that needs no
#     decomp build. symbols/iwram_map.tsv is the extracted copy.
python tools/validation/parse_linker_map.py `
    --ld third_party/lilDavid-warioland4/linker.ld --out symbols/iwram_map.tsv
Select-String -Path symbols\iwram_map.tsv -Pattern 'gHeartMeter|gWarioData|gCurrentRoom'

# 4i. Catch the write itself. Arm a watchpoint on a named variable and the runtime
#     aborts at the exact instruction, with the guest frame in the message:
$env:GBARECOMP_ABORT_ON_MEM_WRITE_ADDR      = '0x03001910'   # gHeartMeter.current
$env:GBARECOMP_ABORT_ON_MEM_WRITE_VALUE     = '3'            # only the losing write
$env:GBARECOMP_ABORT_ON_MEM_WRITE_MIN_FRAME = '9000'         # skip the level setup
$env:GBARECOMP_TRACE_DUMP_DEPTH             = '200'
tools/validation/run-route.ps1 -Tag heartloss -Frames 13600
# logs/routes/heartloss.err.log:
#   runtime_trace: mem-write-addr abort pc=0x080135C4 <gf_autojt_080132A8_18+0x10>
#     addr=0x03001910 value=0x00000003 width=1 (vblanks=12561)

# 4j. Read named fields straight out of an existing snapshot series (no new run):
#     offset = address - 0x03000000, e.g. gWarioData.reaction = 0x1898.

# 4k. Decomp symbol overlay WITHOUT a decomp build (no WSL, no readelf). The
#     decomp's asm sources carry the addresses in their own identifiers and its
#     blobs carry the data extents, so the harvest is pure text parsing; the
#     framework's importer then consumes the harvested table unchanged.
python tools/validation/parse_decomp_symbols.py `
    --decomp third_party/lilDavid-warioland4 --out symbols/decomp_readelf_syms.txt `
    --report --verify-rom "Wario Land 4 (USA, Europe).gba" `
    --dispatch generated/cart/dispatch_table.cpp
python "$env:GAME_RECOMP_ROOT\gbarecomp-main\tools\symbol_import\import_decomp_symbols.py" `
    --id AWAE --name "Wario Land 4 (USA, Europe)" `
    --syms symbols/decomp_readelf_syms.txt --rom "Wario Land 4 (USA, Europe).gba" --out symbols
tools/regeneration/regen.ps1 -CartOnly -SymbolOverlay     # game.toml first, overlay second

# 4l. Watchpoint, as parameters (the abort IS the evidence; the exit code is a
#     crash code on purpose). With the overlay the message resolves the field:
#       addr=0x03001910 <gHeartMeter+0x0> value=0x00000003 width=1 (vblanks=12561)
tools/validation/run-route.ps1 -Tag heartloss-ovl -Frames 13600 `
    -AbortMemAddr 0x03001910 -AbortMemValue 3 -AbortMinFrame 9000 -TraceDumpDepth 40

# 4m. Prove an ENUM field by enumeration, not by sampling. Get the value list from
#     the decomp header, then gate one run per value and record "never written" as a
#     result. gWarioData.reaction = 0x03001898, 12 values
#     (include/wario.h:19-33: 0 NORMAL, 1 WATER, 2 FLAMING, 3 FAT, 4 FROZEN,
#      5 ZOMBIE, 6 SNOWMAN, 7 BOUNCY, 8 PUFFY, 9 BAT, 10 FLAT, 11 MASK).
#     Omit -AbortMemValue to catch the first write of ANY value:
tools/validation/run-route.ps1 -Tag reaction-water -Frames 19500 `
    -AbortMemAddr 0x03001898 -AbortMinFrame 9000 -TraceDumpDepth 24
# logs/routes/reaction-water.err.log:
#   runtime_trace: mem-write-addr abort pc=0x08013D10 <gf_tfunc_08013D06+0xA>
#     addr=0x03001898 value=0x00000001 width=1 (vblanks=10063)
# Close the episode with the opposite gate (the first write of 0 after it):
tools/validation/run-route.ps1 -Tag reaction-water-end -Frames 12000 `
    -AbortMemAddr 0x03001898 -AbortMemValue 0 -AbortMinFrame 10063 -TraceDumpDepth 2
# logs/routes/reaction-water-end.err.log:
#   pc=0x08015F9A <gf_autojt_082DECA0_155+0x12> value=0x00000000 (vblanks=10095)
# Then the ten transformation values (logs/probe_reactions.ps1 loops 2..11):
foreach ($v in 2..11) {
    tools/validation/run-route.ps1 -Tag "reaction-v$v" -Frames 19500 `
        -AbortMemAddr 0x03001898 -AbortMemValue $v -AbortMinFrame 9000 -TraceDumpDepth 4
}
# Result: no abort in any of the ten runs => the demo writes only value 1 (WATER).

# 4n. Read a guest value at a frame on an input route. --tcp disables input replay
#     (F8), so there is no read_iwram here - the write watchpoint IS the reader: the
#     abort message carries the value that was written. Field offsets come from
#     include/wario.h:254-288 (struct WarioData at 0x03001898): reaction +0x00,
#     pose +0x01, damageTimer +0x04, xPosition +0x12 = 0x030018AA, yPosition +0x14.
tools/validation/run-route.ps1 -Tag pos-end-x -Frames 20000 `
    -InputReplay tests/input/explore-1.keyinput.txt `
    -AbortMemAddr 0x030018AA -AbortMinFrame 19000 -TraceDumpDepth 4
# logs/routes/pos-end-x.err.log:
#   runtime_trace: mem-write-addr abort pc=0x08013A8E <gf_tfunc_08013A8A+0x4>
#     addr=0x030018AA value=0x000006DE width=2 (vblanks=19000)
# => Wario's xPosition at frame 19000 is 0x06DE. Sampled (logs/routes/pos-12020,
#    pos-13400, pos-15000 and pos-end-x err logs): 1923 @ 12020,
#    1757 @ 13400 (1,400 frames of LEFT), 2337 @ 15000 (1,000 frames of RIGHT+A),
#    1758 @ 19000 - i.e. the first room gives him ~580 raw units (~75 px) of travel.
# Before trusting any "never written" negative, validate the instrument against the
# game's own demo (rule 23): the demo DOES write the same variable.
tools/validation/run-route.ps1 -Tag demo-room -Frames 19000 `
    -AbortMemAddr 0x03000024 -AbortMinFrame 5000 -TraceDumpDepth 8
# logs/routes/demo-room.err.log:
#   pc=0x0806B92C <gf_tfunc_0806B90C+0x20> addr=0x03000024 value=0x00000002 width=1
#     (vblanks=8852)     <- the demo entering room 2
# A bare -AbortMinFrame 0 run aborts during boot instead (pc=0x00000C08, width=4,
# value=0, vblanks=2), so always keep min_frame past the BIOS phase.

# 4o. Observer mode: reads AND input replay in the same run (the real answer to 4n).
#     --tcp-observe attaches a read-only debug server to a WINDOWED run, so
#     GBARECOMP_INPUT_REPLAY still applies and read_iwram/read_ewram/read_vram/
#     read_pal/read_oam become available mid-route (headless runs never service the
#     observer). Start the run, then read frames with tools/validation/observe_read.py
#     (raw snapshots) or tools/validation/observe_trace.py (one CSV line per sample).
$env:GBARECOMP_INPUT_REPLAY = 'tests\input\explore-1.keyinput.txt'
$env:GBARECOMP_NO_LAUNCHER = '1'
$exe = 'build\host\WarioLand4Recomp.exe'
$args = @('--rom','Wario Land 4 (USA, Europe).gba','--bios','bios\gba_bios.bin',
          '--config','game.toml','--frames','17500','--window','--tcp-observe','20011',
          '--save-path','logs\routes\obs-pound.sav')
$p = Start-Process $exe -ArgumentList $args -WorkingDirectory (Get-Location) -PassThru `
     -RedirectStandardOutput logs\routes\obs-pound.out.log `
     -RedirectStandardError  logs\routes\obs-pound.err.log
python tools\validation\observe_trace.py --port 20011 --frames 17500 --every 250 `
    --sprites --out logs\routes\obs-pound-trace.txt --timeout 900
$p.Kill()
# logs/routes/obs-pound.err.log proves the mode:
#   [gbarecomp:runtime] windowed observe TCP on 127.0.0.1:20011 (reads, touch_*,
#     game commands, queued savestates; no step)
# Ignore samples below ~frame 2000: IWRAM is still boot garbage there
# (frame 2 read back wario_x=3957 wario_y=60074 hearts=165).
# 4p. Decode the level's data instead of guessing at it: ROM-only, no run, no config
#     write. The gate first (rule 27), the dump second.
python tools\validation\level_rooms.py --rom "Wario Land 4 (USA, Europe).gba" `
    --check-snapshot logs\routes\obs-explore\obs-explore-iwram-f011601.bin
python tools\validation\level_rooms.py --rom "Wario Land 4 (USA, Europe).gba" `
    --level 0 --room 0
# gate:  OK  gCurrentRoomHeader (IWRAM 0x03000074) vs ROM room 0 (0x083F4F38):
#             44/44 bytes identical
# dump:  room 0 @ 0x083F4F38  tileset=0x50 ... sprites@0x085991D0
#          [0] y=15 x=26 spawn=0x07 PSPRITE_SWITCH  (1696,1024)
#          [1] y=15 x=31 spawn=0x29 PSPRITE_VORTEX  (2016,1024)
#          [2] y=19 x=07 spawn=0x14 ?                (480,1280)
# Unknown spawn ids print as "?" on purpose: spawnId -> sprite type is resolved in
# code, not in a flat ROM table (searched; 28 noise hits, no table).
```

Each route writes `logs/routes/<tag>.log`, `<tag>.err.log`,
`<tag>-result.json`, `<tag>-coverage.json`, `<tag>-misses.toml.frag` (only when
there are misses) and, with `-DumpLastFrame`, `<tag>-last.png`.

## 4. Route catalog

The machine-readable catalog is [`tests/routes/routes.csv`](../tests/routes/routes.csv).
Its `expected_observation` column is the acceptance statement for the row.

| route | frames | what it proves |
| --- | --- | --- |
| `boot` | 120 | the recompiled entry vector runs; coverage is written |
| `bios-logo` | 120 | the recompiled LLE BIOS drives the PPU; `FULLY_STATIC` |
| `intro-cutscene` | 720 | cartridge code (not BIOS) renders |
| `attract` | 3600 | the game's own attract/demo playback, no host input |
| `title` | 5400 | the title screen (M4) |
| `title-input` | 6000 | a scripted START press is consumed and leaves the title (M4 input) |
| `title-strict` | 900 | the strict gate; currently FAILS by design (F6) |
| `game-8600` | 8600 | the file-select screen, difficulty menu, and a level being entered (D/E) |
| `game-13500` | 13500 | gameplay: HUD, hearts, timer, coin counter, enemies (E) |
| `ctrl-right` / `ctrl-idle` | 13500 | the A/B pair that proves the D-pad moves Wario (E) |
| `persistence` | 3600 | save round trip, run as the verified `save-write` → `save-load` pair (H) |
| `save-write` | 12000 | the game writes a save: `save_flushed` ×6 and the file stops being all 0xFF (H) |
| `save-load` | 6000 | a separate process loads it: SAVE A reads "Hall of Hieroglyphs" (H) |
| `attract-demo-13500` | 13500 | no host input at all — the game plays its own attract demo; covered since the G7 triage (172 misses → 8, all dynamic) |
| `verb-jump` | 12090 | A is consumed: Wario is airborne when the route ends (F) |
| `verb-attack` | 13475 | B tapped at 13450: Wario punches, impact burst visible (F) |
| `verb-dash` | 13500 | B held from 12050: Wario dashes right (F) |
| `verb-crouch` | 13500 | DOWN held from 12050: Wario crouches (F) |
| `verb-up-idle` | 13500 | UP held while standing still: Wario's pose changes, the room does not (G probe) |
| `verb-down-right` | 13500 | DOWN tapped while walking right: pose change only (G probe) |
| `verb-up-right` | 13500 | UP tapped while walking right is ignored — byte-identical to `ctrl-right` (G probe) |
| `strip-left` | 12160 | mid-run filmstrip of the LEFT walk: the camera moves 3 px and stops (`logs/routes/strip-left-frames/`) |
| `left-12139` | 12139 | cross-mode determinism: the headless frame equals the windowed framedump frame byte for byte |
| `attract-deep-19000` | 19000 | the game's own demo run deep: two demo levels, several rooms, coin counter 000050 → 003150; 11 misses, all dynamic |
| `snap-demo` | 19000 | guest-memory series: 37 IWRAM snapshots every 500 frames over the same demo (`tcp-snapshot.ps1` + `snapshot-diff.py`) |
| `heartwatch` | 19000 | 43 TCP screenshots every 250 frames from 8,500: the HUD's red-pixel total never steps down inside a level |
| `damage-dump` | 19400 | 800 consecutive windowed frames (18,500–19,299) analysed frame by frame for a health change |
| `win-9000` / `win-19000` | 9100 / 19100 | windowed framedump of one frame, byte-compared against the headless reference at the same guest frame |
| `noinput-win-19000` | 19100 | the same windowed capture driven by `tests/input/noinput.keyinput.txt`: identical to headless, which is why windowed runs must be replay-driven (G10) |
| `heartloss` | 13600 | the same demo route with a write watchpoint on `gHeartMeter.current`: the runtime aborts at `pc=0x080135C4` with `value=3` at vblank 12,561 — priority F 受伤, caught at the instruction |
| `heartloss-ovl` | 13600 | the same abort with the decomp symbol overlay loaded: the message resolves the field name (`<gHeartMeter+0x0>`) at the same PC and vblank |
| `reaction-water` | 19500 | write watchpoint on `gWarioData.reaction` with **no** value gate after frame 9,000: aborts at `pc=0x08013D10` with `value=1` at vblank 10,063 — the first time the reaction axis moved (priority F) |
| `reaction-water-end` | 12000 | the opposite gate (`value=0` after vblank 10,063): the episode ends 32 vblanks later at `pc=0x08015F9A` |
| `reaction-enum` | 19500 ×10 | one gated run per transformation value (2…11): the attract demo never writes any of them (priority F 变身, now enumerated) |
| `reaction-water-frames` | 10100 | 22 consecutive windowed frames spanning the episode; `f_010064.png` is Wario in the water |

The four `verb-*` rows are the priority-F A/B set: each is compared against the
same trace at the same frame budget with the verb line removed (`ctrl-idle-12090`,
`ctrl-idle-13475`, `ctrl-idle-13500`). `tools/validation/verb-ab.ps1` re-runs all
of them and fails if any verb's frame is byte-identical to its control (measured
2026-09-30: 1,227 / 1,706 / 1,238 / 716 differing pixels of 38,400).

The three `verb-up/down-*` rows are the priority-G door probes, and they are
negative results kept on purpose: pressing UP or DOWN changes nothing but Wario's
own sprite band (631 px for `verb-up-idle` bbox x=107..134 y=118..151; 424 px for
`verb-down-right` bbox x=187..208 y=118..151), and UP while walking right is
*fully* ignored (0 px). No camera move and no room change, so a host-input room
transition has not been produced yet.

The reaction rows are the priority-F pair that finally moved: an any-value
watchpoint proves the axis is live and names the instruction, the opposite gate
brackets the episode, and the ten transformation values are then each disproved in
turn. Reproduce with `logs/probe_reactions.ps1` (see rule 22 and §3 item 4m); the
images are in `logs/routes/reaction-water-frames-frames/`.

`attract-deep-19000` is the single most informative route the repo has: with no
host input at all it goes title → demo level 1 (a green/purple hall marked "B",
then an underground room with a golden chest and the coin counter at 003150) →
title → demo level 2 (a beach level). Reading the strip frames is the cheapest
way to see what the game does *without* us: `logs/routes/attract-strip-f9000.png`,
`-f10500`, `-f12000`, `-f13500`, `-f19000`. The coin counter alone proves the demo
crosses rooms and collects things (`000050` at 9,000 frames, `000990`, `001320`,
`003150`). What it has *not* shown in any sampled frame is a heart change — four
hearts in all twelve captures — so priority F's damage axis is still open.

Three capture paths now exist, and 2026-09-30 settled how they relate: a headless
run, a windowed framedump run (`-Window`, present-in-place off) and a TCP
screenshot all agree byte for byte at the same guest frame, *provided the windowed
run is replay-driven*. `win-9000-frames/f_009000.png` equals `refdemo-9000-last.png`
and `win-19000-frames/f_019000.png` equals `det-noinput-a-last.png`; the
replay-driven rerun `noinput-win-19000-frames/f_019000.png` equals it too. The one
dissenting run (`damage-dump`) was a window with a live keyboard and no replay, and
it sat on a different demo phase — see rules 15–17 and G10.

## 5. Rules learned from failures (each cost at least one run)

1. **Per-route save isolation.** The game flushes SRAM at exit, so a shared save
   file makes one route's final state the next route's initial state. Measured:
   two otherwise identical 6000-frame runs differed (`distinct_misses` 7 vs 10)
   because the first had written the save the second loaded. `run-route.ps1` now
   gives every tag its own save, zeroed to 0xFF first.
2. **Cold self-heal cache** (see §2).
3. **Never let the asset picker run.** Resolution ends in a modal Windows file
   dialog with no non-interactive escape (`asset_picker.cpp:221-243`); a bad path
   hangs with no output. The runner pre-seeds `rom.cfg`/`bios.cfg` next to the
   executable and `-AllowLauncher` is off by default.
4. **`GBARECOMP_HEAL_CXX`.** The self-heal compiler defaults to a hardcoded
   MSYS2 path that does not exist here; without the override every heal fails
   with `gcc exit -1` and the run silently stays on the interpreter.
5. **`--tcp` starts parked.** Send `{"cmd":"continue"}` before observing, or
   `frame` stays 0 forever (`docs/KNOWN_ISSUES.md` F7).
6. **Correct script path.** `tools/validation/` and `tools/regeneration/` both
   hold `.ps1` files; invoking a missing one only prints PowerShell help and the
   next route silently reuses the previous executable.
7. **Frame budgets must actually reach the screen under test.** The title screen
   appears at ~5400 frames; the original 900-frame "title" route only reached the
   intro cutscene. Gameplay needs ~8600 frames to enter a level.
8. **A held button needs an A/B pair, not a screenshot.** Two traces that differ by
   exactly one line (`gameplay-right` holds RIGHT from frame 12000, `gameplay-idle`
   holds nothing) isolate the input's effect: 1,196 of 38,400 pixels differ, in
   Wario's band. A single run cannot distinguish "input worked" from "animation
   phase".
9. **PowerShell resolves aliases before functions.** A helper named `Diff` is
   silently replaced by the built-in `diff` → `Compare-Object`; rename it
   (`Compare-Frame`). Likewise `"$tag: text"` is a parse error — `$tag:` reads as a
   scope qualifier; write `"${tag}: text"`.
10. **Never name a parameter `$input`.** It is a PowerShell automatic variable, so
    `function Invoke-Route(..., [string]$input, ...)` takes an empty value and the
    caller's `-InputReplay` is dropped without an error: the first version of
    `tools/validation/smoke.ps1` ran its input routes with
    `input_replay=DISABLED` and recorded title-screen frames as the baseline for
    gameplay routes. Always grep a finished run's log for
    `input_replay=ENABLED … events=N` before trusting its frame.
11. **A transient verb needs the capture frame inside the action.** A D-pad hold
    moves Wario permanently, so any end frame shows it; a jump or a punch is over
    in tens of frames, so `verb-jump` stops at 12,090 (40 frames after the press,
    Wario airborne) and `verb-attack` at 13,475 (25 frames after the tap). Measure
    the same trace against a control at the *same* frame budget — two idle frames
    1,385 apart differ by 653 pixels purely from the game's own animation, which is
    the same order of magnitude as a verb's effect.
12. **A raw differing-pixel count cannot separate a camera pan from a sprite
    move.** The background is dense: a **1-pixel** global shift changes ~47 % of
    the 38,400 pixels, so `strip-left` at frame 12,139 reports 23,254 differing
    pixels while the camera actually moved only **3 px** (and stopped). Always
    report the horizontal shift next to the pixel count —
    `tools/validation/frame-strip.ps1` computes it over a background band with the
    HUD and the sprite row excluded. Also: the runtime's own framedump only runs
    inside the windowed per-frame loop, so a capture route needs `-Window` and
    present-in-place off (`docs/KNOWN_ISSUES.md` G8), and `--tcp` cannot drive an
    input route at all (F8).
13. **PowerShell parameters are type-constrained, and lookups are
    case-insensitive.** `frame-strip.ps1` declared `[int]$Base` and then assigned
    the reference *pixel buffer* to `$base` — the same variable — which fails with
    `Cannot convert "System.Byte[]" to "System.Int32"` at the assignment, not at
    the use. Name buffers distinctly. (Same family as rules 9 and 10: the failure
    is silent or misleading, and only shows up in a later run.)
14. **A route's frame budget is part of its coverage claim.** The attract demo was
    "clean" at 13,500 frames (8 misses) and uncovered four more cartridge PCs when
    driven to 19,000 — the demo simply had not reached that code yet. So a pass on
    a short route never licenses the long one: re-check the miss set whenever a
    route is lengthened, and prefer the longest route the game offers (the demo) as
    the coverage witness. Equally, a *new* miss on a longer run is not
    automatically a regression — it is unreviewed coverage, and the fix is the
    usual one (classify, then merge address-only metadata, then regenerate and
    re-verify byte-identical frames on the replay routes).
15. **A windowed run must be replay-driven.** `-Window` opens the live host input
    path (SDL polls the real keyboard), and the attract demo aborts as soon as any
    button is held, so a windowed run that is *supposed* to see no input can drift
    into an entirely different demo phase without a single line in the log. One of
    three windowed no-replay runs diverged this way (G10). Pass
    `-InputReplay tests\input\noinput.keyinput.txt` for any windowed route that
    should see nothing, and compare the coverage counters against the recorded
    baseline — that is what catches it.
16. **A TCP capture's frame is the frame the server reports, not the mark.**
    `tcp-filmstrip.ps1` polls `run_status` every 40 ms while the core free-runs at
    ~560 fps, so the capture lands 8–38 frames *past* the mark
    (`-Marks '120,300,600,880'` captured at 158 / 330 / 608 / 900). Quote the
    reported frame in every claim, and never compare a TCP capture with a normal
    run frame-for-frame.
17. **Health is the red-pixel total, not the number of heart slots.** The HUD
    hearts animate (they beat), so counting runs of red columns splits a filled
    heart into two runs and reported up to 13 "hearts" on a five-heart frame. The
    stable quantity is the total red pixels in the band
    (`hud-hearts.ps1 -X0 2 -X1 100 -Y0 4 -Y1 22`): 167 stayed constant for 367
    consecutive frames of the demo, which is what "no damage" looks like. **And on
    2026-09-30 that total turned out to be a proxy, not a measurement**: the band
    also contains the red/yellow heart *gauge* bar under the row, so the totals
    (120…179) do not track the heart count — the demo goes 4 → 3 → 5 → 4 → 3 hearts
    over totals 120 → 179 → 161. Read the variable.
18. **Prefer the named guest variable to any pixel measurement.** `gHeartMeter`
    (`0x03001910`) answers "how much health" exactly, `gWarioData.reaction`
    (`0x03001898`) answers "which transformation", and the watchpoint answers "which
    instruction did it, on which frame". The pixels then only corroborate (4 hearts
    at 12,258 → 3 at 12,758). Pixels are for what has no name yet — the first
    version of the HUD reader cost a day of chasing a 15-frame fade that was a
    screen transition, not damage. The map itself must still be *validated* against
    memory evidence before it is trusted (see §6, the snapshot cross-check).
19. **A decomp name is an address claim only when the name encodes one — and the
    two conventions in `asm/` differ.** In `third_party/lilDavid-warioland4`, a
    `func_` name carries the FULL ROM address with the leading zero dropped
    (`func_80104A4` = `0x080104A4`, `func_8000A84` = `0x08000A84`) while a `.L_`
    label carries the offset inside the 0x08000000 window (`.L_104d0` =
    `0x080104D0`). The first harvest added the base to both and emitted
    `0x10000A85`. Validate such a table against the **ROM's own bytes** (7 of 10
    harvested Thumb starts open with `push {…}`/`bx lr`), never against
    `generated/cart/dispatch_table.cpp`: that file is a **per-instruction resume
    map** (133,792 rows of `{addr, thumb, resume, fn}`, of which only 2 of 300
    sampled rows start with a `push`), so a low overlap means nothing and a
    "50 % of addresses must be known code" assertion is unfalsifiable.
20. **Names must not change behaviour.** A symbol overlay is metadata: the
    acceptance test is the same routes producing byte-identical frames and the
    same miss/interp counters, with the *only* change in the logs. Measured on the
    harvested overlay (`-SymbolOverlay`): discovered functions 15,740 → 15,740,
    dispatch rows 133,792 → 133,792, `smoke.ps1` PASS with every recorded frame
    unchanged, and the watchpoint message gains the field name
    (`addr=0x03001910 <gHeartMeter+0x0>`) while keeping the same PC and vblank
    (12,561). The decomp's own naming is WIP: `import_decomp_symbols.py` reported
    `names: 0 meaningful, 3327 address-derived placeholders`, so the real gain is
    the 552 named IWRAM globals and 3,013 named ROM data extents — and 262
    *meaningful* function names cannot be placed at all without a build (§7).

21. **A generation input is opt-in only if the output directory is cleared.** The
    host build globs the generated directory
    (`CMakeLists.txt:47 file(GLOB CART_SOURCES CONFIGURE_DEPENDS
    "generated/cart/*.cpp")`), so any file an earlier, differently-configured
    regeneration left behind is still compiled. Measured (G12):
    `regen.ps1 -CartOnly -SymbolOverlay` writes
    `generated/cart/data_symbol_map.cpp` (151,398 B); the following plain
    `regen.ps1 -CartOnly` did not remove it, so the "baseline" executable still
    contained the overlay's data names (25,529,220 B instead of 25,417,112 B).
    `regen.ps1` now clears `generated/cart` and `generated/bios` before generating.
    Two consequences for every future A/B: compare the artifact *set*, not just the
    files you expect to differ; and remember that
    `Remove-Item -LiteralPath <dir>\*` expands nothing (`-LiteralPath` is literal) —
    enumerate first with `Get-ChildItem -LiteralPath <dir> -Force | Remove-Item
    -Recurse -Force`, which is the form that actually deletes.

22. **Prove an enum by enumeration, not by sampling.** A field whose value space is
    known from a decomp header is falsifiable one value at a time: gate
    `GBARECOMP_ABORT_ON_MEM_WRITE_VALUE` on each value in turn and treat "the run
    completed 19,500 frames without aborting" as a *result*, not as a missing
    measurement. Measured on `gWarioData.reaction` (`0x03001898`, width 1): an
    any-value watchpoint after frame 9,000 aborts at
    `pc=0x08013D10 <gf_tfunc_08013D06+0xA> value=0x00000001 (vblanks=10063)`, i.e.
    the field is *not* rewritten every frame, and all ten transformation values
    (2..11) are absent from the entire attract demo — 1 = `REACTION_WATER` is the
    only reaction the demo reaches. Compare with the earlier 37-sample snapshot
    series, which showed the same 0 and could not distinguish "absent" from
    "shorter than the sampling interval". Pair each finding with the decomp's own
    instruction where one exists (here `asm/wario/disasm_normal.s:7726
    strb r1,[r5,#0]`, pool entry `.L_13d24` = `gWarioData`), and with a second run
    that uses the opposite gate to get the end of the episode (vblank 10,095).

23. **Validate the instrument before believing a negative.** "The variable was never
    written" only means something if a write *is* what the event looks like.
    Measured (routes `explore-1`/`explore-2`): a 24,000-frame player-driven route
    never writes `gCurrentRoom` (`0x03000024`) after frame 12,000 — but that is a
    statement about room transitions only because the game's own attract demo
    *does* write it: `demo-room` aborts at
    `pc=0x0806B92C <gf_tfunc_0806B90C+0x20> addr=0x03000024 value=0x00000002 width=1
    (vblanks=8852)` — the demo entering room 2. The same family
    (`func_806B864`) appeared in the static scan of stores to `gCurrentRoom`
    (`asm/disasm_0x06AF4C.s:1229-1235`). Two traps found while getting there: a
    bare `-AbortMinFrame 0` watchpoint aborts during boot
    (`pc=0x00000C08 addr=0x03000024 value=0 width=4 (vblanks=2)`, the BIOS phase
    clearing IWRAM), and a "who writes this IWRAM symbol" scan built on
    `.4byte <symbol>` pool entries produces plausible-looking false positives
    whenever a register is reloaded from a *different* pool entry before the store
    (the sprite-AI hits, values 2/17, are that artefact).

24. **Reading a guest value at a frame on an input route: the write watchpoint is the
    only channel.** `--tcp` disables `GBARECOMP_INPUT_REPLAY` (F8), so
    `read_iwram` is unavailable exactly where the interesting routes are. A write
    watchpoint turns the abort message into a datum: set
    `--abort-mem-addr <field>` and `--abort-min-frame <F>`; the runtime aborts on the
    first write at or after F and prints the value it wrote. Field offsets come from
    the decomp struct (`third_party/lilDavid-warioland4/include/wario.h:254-288`
    `struct WarioData`, base `0x03001898`): reaction `+0x00`, pose `+0x01`,
    damageTimer `+0x04`, horizontalDirection `+0x0E`, xPosition `+0x12` =
    `0x030018AA`, yPosition `+0x14` = `0x030018AC`, xVelocity `+0x16`, yVelocity
    `+0x18`, hitbox left/top/right/bottom `+0x32/+0x34/+0x36/+0x38`.
    Measured on `tests/input/explore-1.keyinput.txt` (the write is
    `pc=0x08013A8E <gf_tfunc_08013A8A+0x4> addr=0x030018AA width=2`):
    xPosition = 1923 @ 12020, 1757 @ 13400 (after 1,400 frames of LEFT), 2337 @
    15000 (after 1,000 frames of RIGHT with A taps), 1758 @ 19000. So Wario's whole
    walkable range in the level's first room is ~580 raw units, and the LEFT/RIGHT
    asymmetry (166 units for 1,400 frames vs 580 for 1,000) is a *blocked* walk, not
    a slow one. The raw unit is ~1/8 px (cross-check: the 580 units correspond to the
    ~75 px sprite translation measured from the `ctrl-right`/`ctrl-idle` A/B bbox
    `(107,118)-(209,152)`); conversions are for reading, never for a gate. Caveats:
    the datum is the value at `min_frame` (or the first later write), a field that is
    not written while the object is idle yields *no* abort (which is itself the
    finding), and boot writes must be excluded with `min_frame` (rule 23).

25. **An input route can be read: `--tcp-observe` (observer mode) is the read channel
    that survives `GBARECOMP_INPUT_REPLAY`.** `--tcp` is unusable here because it
    replaces the whole run (F8); `--tcp-observe PORT` instead attaches a read-only
    `debug::TcpDebugServer` to a *windowed* run
    (`gbarecomp-main/src/runtime/runtime.cpp:2892-2927`) and prints
    `[gbarecomp:runtime] windowed observe TCP on 127.0.0.1:<port> (reads, touch_*,
    game commands, queued savestates; no step)`. Measured: the observer run replays
    the same route as the headless watchpoint runs (xPosition 2016 / 2016 / 1758 /
    1758 at frames 11,601 / 12,002 / 13,001 / 14,002 vs the watchpoint samples
    1923 @ 12020, 1757 @ 13400, 2337 @ 15000, 1758 @ 19000). Two hard requirements:
    the run must be windowed (headless `pump_host_input` returns immediately, so the
    port accepts a connection and never answers) and `--frames` still bounds it.
    Ignore samples below ~frame 2000 — IWRAM is boot garbage before that (frame 2
    read back `wario_x=3957 wario_y=60074 hearts=165`). This closes G13 in practice
    without touching the read-only framework.

26. **Validate an IWRAM address against the ROM's literal pool before trusting a
    watchpoint there.** `symbols/iwram_map.tsv` comes from the decomp's `linker.ld`,
    so a wrong address would make every "never written" negative meaningless. The
    ROM settles it: the 4-byte little-endian constant `0D 0C 00 03` (0x03000C0D,
    `gSwitchPressed`) appears at VRom `0x0802B724` — exactly the pool label
    `.L_2b724` that `asm/sprite_ai/disasm_switch.s:237-239` loads before
    `strb r1, [r0, #0]`, the only `gSwitchPressed = 1` store in the decomp. So the
    address is confirmed by cartridge bytes, not by a name (rule 19). Measured
    negatives with that address: routes `switch-hunt` (20,000 frames, LEFT into the
    switch then A/DOWN/UP/B jump-slam cycles) and `switch-hunt2` (the same with A
    *held* for variable-height jumps) both finish with `exit=0` and **no write to
    0x03000C0D after frame 12,000**.

27. **A tool that decodes the guest's data must be gated against the guest, or its first
    output will be believed.** `tools/validation/level_rooms.py` decodes the level →
    room → sprite structure straight out of the ROM. Its own gate,
    `--check-snapshot <iwram.bin>`, compares the guest's live `gCurrentRoomHeader`
    (IWRAM `0x03000074`) against the ROM's `struct RoomHeader` record and prints
    `OK … 44/44 bytes identical`, exit 0. That gate earned its place on its first run: it
    caught the sprite field order (the triples are `[y, x, spawnId]`, **not**
    `[spawn, y, x]`) and it caught two unsound room-count heuristics (a
    pointer-alignment scan that invented rooms 11–15, and a stricter word-alignment scan
    that reported a single room). The real bound is
    `(next level block address − this block address)/0x2C` = 13 rooms for level 0, and
    BG/sprite pointers inside a header are halfword-aligned, so alignment cannot
    discriminate. *A decoder with no oracle is a hypothesis generator, not evidence.*

28. **A negative needs the instrument validated on a case that is known to be positive —
    and the "positive" must be the same kind of case.** Validating on the game's own
    attract demo is not enough when the demo plays a different part of the level. The
    demo's recorded input stream looked like the obvious lead for the missing room
    transition (G14), and it is dead for a reason only a byte-level check would find:
    `gDemoInputs` is read from IWRAM (not from KEYINPUT — `src/demo_input.c` never writes
    the register, so `GBARECOMP_INPUT_RECORD` would have captured a single `0x03FF` line),
    the CSV reproduces from `snap-demo-iwram-f009503.bin`, and *that snapshot has
    `gCurrentRoom = 3`* while the player route sits in `gCurrentRoom = 0` of the same
    stage (`gCurrentStageID = 0` in both). The demo never performs the traversal under
    investigation. **Check that the validated-positive case exercises the same variable,
    at the same value, on the same data — otherwise the validation transfers nothing.**

29. **A publication boundary is a checkable rule, not a checklist.**
    `tools/release/publication-audit.ps1` turns §9 of the working brief
    (`AGENT_PROMPT.md`, removed before release) into eleven rules
    (K0–K11) over `git ls-files`: the required files are tracked, nothing tracked sits in
    a local-only directory or carries a local-only extension, no tracked file exceeds
    1 MiB, no personal absolute path, no credential-shaped string, `game.toml` and
    `src/main.cpp` agree with `docs/ROM_IDENTITY.json`, the licence names a holder, and
    the notices name every pinned dependency. Two refinements came from running it: a
    **personal** path (a Windows user-profile or Unix-home directory) and a
    **conventional shared root** (a toolchain install directory, the project's own root)
    are different defects, so K4a fails on the first and K4b allows the second only
    through a per-file allowlist whose reason is written down; and
    a failure must say *present but not staged* versus *not on disk*, because the fix is
    `git add` versus writing the file. Repeatable beats remembered — the same argument
    that replaced the G7 hand-merge with `merge_miss_fragment.py`.
    **The audit is self-applying, and it proved it on its own rule:** the first
    paragraph written here documented K4a using a literal user-profile path as its example,
    and the next audit run failed `K4a` on this file. A rule that is only enforced in other
    people's files is not enforced; the text had to be reworded to describe the pattern
    instead of quoting it.

30. **A wrongly-ignored file is the one failure nothing reports.** Rule 29's audit reads
    the *tracked* set, so it cannot see a file that `.gitignore` hides, and neither can
    `git status` — `ls-files --others --exclude-standard` omits ignored paths on purpose.
    That is not hypothetical: an unanchored `release/` rule in `.gitignore` matched
    `tools/release/` at any depth and excluded **`tools/release/publication-audit.ps1` —
    the audit script itself** for a whole round, while every other rule still passed.
    Two changes followed. `.gitignore` now anchors every local-only **directory** pattern
    to the repository root with a leading `/` (the same reason `/reference/*` is anchored,
    already noted in that file), and the audit grew **K12**, which asks `git check-ignore`
    about every publishable file that exists but is not tracked and fails if the answer is
    "ignored" — because the two situations look identical and need opposite fixes
    (`git add` versus anchoring the pattern). *Anchor a pattern to the depth you mean; an
    ignore rule is a publication decision, and a sloppy one is silent.*

31. **A decoder path nobody exercises is invisible — test the instruction, not the
    function.** Writing `if top == 0x1C:` inside a branch decoder looks like coverage and
    tests nothing, because the suite only ever fed it `BL`. The field-width bug behind it is
    the same one that had already been made twice in the same file: `top = hw1 >> 11` is
    **five** bits, and a mask written for a sixteen-bit halfword is false for every possible
    input, so the comparison succeeds zero times and silently disables the whole path.
    Three distinct instances, all in `tools/validation/rom_calls.py`, none of them visible to
    a self-test that feeds the decoder the instructions it already handles:
    - `scan()` scanned `max_addr=0x03008000`, which is *below* `ROM_BASE`, so it read
      **zero bytes** and printed a confident `no B/BL/BLX in the ROM targets any of them`;
    - `scan()`'s Thumb pre-filter compared `hw1 >> 11` against `0xE000 <= top <= 0xE7FF`;
    - `bl_targets()`'s 16-bit `B` test compared the same 5-bit `top` against
      `0xE000 <= top <= 0xE7FF` — the **unreachable branch inside the decoder itself**.
    The fix in each case is a self-test that feeds the decoder the specific instruction the
    path claims to handle (`0xE7FE` = `b #-4`, `0xDAFD` = `bge #-6`), not a review of the
    arithmetic. *Coverage of a decoder is measured by the instructions it has been fed, not
    by the branches you can see.*

32. **A scanner's negative is only as good as the branch classes it implements.** "No caller
    found" silently means "no caller among the branch kinds I decode". The G14 scan reported
    `no B/BL in the scanned ranges targets 0x0806AF58` — while the caller was a plain 16-bit
    `B`. The same gap hides `BX Rm` / `BLX Rm` (5-bit opcode `0b01000`), which are the
    *only* trace a function reached through a pointer table leaves: no branch points at it
    and no literal in the ROM holds it. The ROM contains 421 `BLX Rm` and 2,826 `BX Rm` call
    sites, so this is not a corner case. `rom_calls.py` now decodes both and labels them
    `BXREG`/`BLXREG`, reports them under `--indirect`, and — when nothing branches directly —
    **says what that does and does not establish** instead of printing an empty result.
    *A negative must state its own blind spot; an empty result with no caveat reads as an
    answer.*

33. **A generated disassembly comment is evidence about the generator, not about the
    instruction.** `generated/cart/recompiled_001.cpp:150100` renders a 16-bit Thumb `BL` as
    two invented pseudo-instructions — `/* 0806B418 0806b418 T bl.hi 0x0806b41c */` and
    `/* 0806B41A T bl.lo 0x00000000 */` — because the generator splits the halfword pair.
    The emitted code is correct (`recompiled_001.cpp:150119-150122` computes
    `(R[14] + 0x448) & ~1` and stores `0x0806B41D`), and `rom_calls.py` independently
    decodes the same bytes to the same target `0x0806B864`, so the **comment is wrong, not
    the code**. Anything derived from those comments — including a hand-typed call chain —
    inherits the error. *Read a branch target from the ROM bytes, never from a comment
    printed next to them.*

34. **A graph walk needs one key type, not two.** `callchain.py`'s first version keyed the
    half of the graph by function *name* and the half by *address*, so every hop after the
    first came back empty and the tool cheerfully reported a two-function chain where there
    were five. Names and addresses are not interchangeable even when the name *encodes* the
    address: `gf_tfunc_0806B410` and `gf_autojt_0806AFFC_07` are the same field with and
    without an index suffix. *Convert once, at the boundary, and assert the conversion.*

35. **A formula used to accuse a tool must itself be checked against a case the tool is
    known to get right.** I concluded that the code generator decoded `0x0801C228` wrongly,
    on the strength of a script that agreed with my hand-decode and not with the generator.
    The script and the hand-decode shared one error — `imm32 = (imm10<<19)|(imm11<<8)`
    instead of `(imm10<<12)|(imm11<<1)` — so their agreement was not corroboration, it was
    one mistake counted twice. Meanwhile `0x0806B418 -> 0x0806B864` was already a *gated
    positive* in `rom_calls.py --self-test`; running the new arithmetic past it would have
    taken thirty seconds and would have refuted the whole conclusion. *Before publishing a
    "tool X is wrong", re-derive one case where X is known to be right, using X's own
    output rather than your own arithmetic.* Two decoders that share an author share a bug.

36. **When a guest can be asked, ask it — and put the answer in the test.** The G15 chain
    was closed by `runtime_trace` events from a live run, not by static decoding. So the
    expected target for `0x0801C228` is now `0x080746C0` in `--self-test`, taken from a
    dispatch event captured at runtime, which makes that case a comparison of the decoder
    against the *CPU* rather than against itself. Rule 27 gates a decoder against the guest;
    this is the receipt. A trace is a recording, so it must be committed (or cited by log
    path) — otherwise the gate is only as reproducible as the run that produced it.
37. **A pointer-shaped run of words next to code is not a dispatch table until an
    instruction loads its base address.** In G15 I read nine consecutive ROM words
    (`0x0801B8E4`) that begin with `0x0801B908`, concluded "9-entry function-pointer
    table, entry 0 is the room-load path", and only later found that the base is fetched
    by `ldr r1,[r15,#0xc]` at `0x0801B8D2` — in a *different* function, one page below the
    one whose `ldr` I had credited. The conclusion happened to survive, but adjacency in a
    literal pool is a hypothesis, not a reference. The test that settles it is one
    instruction: does some load produce this address, and does the stride in that code
    match the element size?
38. **Attribute a load to the instruction that performs it, and compute its literal
    address from that instruction's own PC.** The Thumb base is `(PC + 4) & ~3`, so two
    PC-relative loads four bytes apart in the same pool resolve to different words. My
    G15 write-up said `ldr r0,[r15,#0x14]` in `gf_tfunc_0801B8C2` fetched the table base
    `0x0801B8E4`; it fetches `0x03000C3C`, an IWRAM address, and is the *index* source.
    This is the same family as rule 33 (a generated comment is evidence about the
    generator) and rule 35: a disassembly comment names the instruction, not the
    function, and the function's first literal is not the instruction's literal.
39. **A truncated extraction is a silent false negative; print a count and check it.** The
    body of `gf_tfunc_0801B8C2` was pulled with a regex that stopped at the first
    column-0 `}`, which an inner block produced — I read 5 instructions of a 6-instruction
    function and believed I had all of them, and the error pointed *towards* a tidy
    conclusion. A second regex printed nothing on a body that plainly had instruction
    lines. Any extraction whose output you then interpret should print how many items it
    found, and a zero on non-empty input is a quoting failure until proven otherwise
    (rule 29's neighbour, from the other side).
40. **In PowerShell an array splat binds positionally; only a hashtable splat binds by
    name.** `& .\run-route.ps1 @rargs` with `$rargs = @("-Tag",$tag,"-Frames",20000,…)`
    passed `-Tag` as the *value* of the first parameter, `$tag` as the value of the
    second, and `-Frames` as the value of the third — surfacing as
    `无法处理参数 'Frames' 上的自变量转换。无法将值 "-Frames" 转换为类型 "System.Int32"`.
    I produced nine clean `MISS` lines from nine routes that never ran, and I had
    already "fixed" this once by renaming `$args` (also an automatic variable) to
    `$rargs`, which changed nothing, because the name was never the fault. The tell is
    that the error names a *parameter* while complaining about a *switch-shaped* value;
    that is positional binding, not a type problem. Splat a hashtable
    (`@{ Tag = $tag; Frames = 20000 }`). The general form of rule 32: a driver that
    reports success for work it did not do will manufacture a negative, and a negative
    that comes from a driver rather than from the guest is not evidence.
41. **A shared tail entry is a function of its inputs, not of whatever code sits above
    it in the listing.** `gf_tfunc_0800062E` is a one-instruction thunk, `strh r0,[r1]`,
    and `rom_calls.py` finds **22 branch callers**. The instructions physically above it
    read `movs r2,#4 / rsbs r2,r2,#0 / adds r0,r2,#0`, which compute −4, so the store
    should have written `0xFFFC`; the guest reported `0x00000000`. Both readings are
    correct — the write came from one of the other 21 callers, entered with `r0 = 0`.
    Attributing a store to the arithmetic printed above it is the same mistake as rule 38
    (attributing a load to the instruction above it) and the same mistake as the G15
    literal-pool error, in a third disguise. What settles it is not a better decode, both
    decodes were right; it is `rom_calls.py --target <tail>` plus the register state in
    the `dispatch` event immediately preceding the `mem_w`. If a thunk has more than one
    caller, adjacency proves nothing about its data flow.
42. **A name from a nearest-lower lookup is evidence about the table, not about the code.**
    `rom_calls --why` labelled the call site `0x0800017A` as
    `gf_afunc_080000F0+0x8A`, and `enclosing()` really does compute the nearest dispatch row
    at or below the address — but that row's function is a **single ARM instruction**
    (`b 0x080000C0`) and has no rows of its own, so a label 0x8A bytes "into" it cannot be
    its body. There were in fact **no dispatch rows at all** for `0x08000100..0x080001CB`, and
    the real reason (the span is DMA3-copied to IWRAM and installed as the user IRQ vector,
    declared in `game.toml` as a blob rather than as code) was sitting in the project files
    already. Before repeating a `+0xNN` owner label, read the function the offset points
    into and check it is that long. Rule 38's neighbour: a resolved *where* is not a resolved
    *what*. The general form of rule 32 — an instrument's own naming, echoed back as a
    finding, is a hypothesis, and the cheapest way to test it is to open the thing it names.
43. **A halfword walk is a wrong decoder, not a weak one, in a region it does not own.**
    `rom_calls.py` walks every *halfword* and decodes Thumb, because that is how it finds a call
    site without an instruction-boundary map. In an ARM region that is not a weakness, it is a
    false-positive generator: the walk reaches the upper halfword of every ARM word, and an ARM
    data-processing word has `hw1 >> 11 == 0x1C`, which is exactly the 16-bit
    unconditional-`B` opcode. `0x08000178` holds `0xE2110C01` = `tst r1,#0x100`; its upper
    halfword `0xE211` decoded as `B 0x080005A0` and the target matched to the byte. It was
    published as the **sole** caller of the room-loader mode, and an entire round was built on
    it. Three corollaries, each paid for:
      * **Uniqueness is the most dangerous thing a scanner can print.** A long list gets
        checked; a single hit gets believed. When a scanner returns exactly one caller,
        the first duty is to falsify it, not to write it up.
      * **A region with no dispatch rows is not a region with no code.** The blob at
        `0x080000FC` has no ROM rows precisely *because* it was DMA3-copied to
        `0x03000C44` and compiled **there** — rows `gf_afunc_03000C44/03000C58/03000CF4` exist
        at the IWRAM addresses. Look up the address the code *runs from*, not the address it
        was stored at.
      * **Gate a decoder against the address space it is used in,** not only against the
        instruction it decodes. A decoder correct on every Thumb word can be wrong on every
        ARM word, and a self-test over known Thumb cases cannot see it.
    The fix is to make the tool read its own ground truth: the dispatch table's second field is
    the per-function instruction stride (`0u` ARM, `1u` Thumb), and a stride-0 row marks a
    **4-byte** ARM instruction, so the guard range must be 4 bytes wide or it does not even cover
    the upper halfword it exists to hide. With that, `--target 0x080005A0` reports **no** `B`/`BL`
    caller, which is the truth: the handler is reached only through the 13-entry game-mode table.
    And the *suppression* needs its own test — covering too little leaves false positives,
    covering too much silently hides real ones, so the tool asserts that no derived ARM range
    contains an address the dispatch table labels Thumb. A guard added to silence one false
    positive must be pinned on both sides or it will trade the first error for a slower one.
44. **"No `B`/`BL` caller" is a statement about direct calls only, and the trace contradicts it
    by construction.** `rom_calls` reports no branch caller for `gf_tfunc_08000244`, but the
    runtime trace at the mode-8 store shows `lr=0x0800B43B` — issued from `gf_tfunc_0800B43A` by
    a **tail call**, which leaves `lr` untouched and is therefore invisible to a branch scan by
    design. A negative from a scanner and a positive from the guest are not a contradiction to
    be resolved by picking one; they are two different questions, and the guest's answer is the
    one that runs. Say which kind of caller was searched for. (Rule 32 again, from the other
    side: a negative whose instrument cannot see the case is not an absence.)

45. **A normalisation that is right for one query mode is wrong for another, and the wrong one
    fails silently.** `rom_calls` masked every `--target` with `& ~1`, because Thumb code
    addresses are halfword-addressed and a branch target must be matched at `addr` and `addr|1`.
    Applied to `--xrefs` — which searches for 32-bit *literals* — the same mask turned a request
    for `0x03000025` into a search for `0x03000024`, a different one-byte IWRAM field three
    bytes away. The answer was not an error. It was a clean, confident "no references", printed
    by the same code that, one option earlier, had correctly answered `--target 0x080005A0` with
    a precise negative. **A mask is a statement about what the caller is asking for, so it belongs
    to the query mode, not to the argument parser** — `parse_targets(spec, *, align=…)` now takes
    the mode explicitly and the self-test pins both branches against the same input. The second
    half of the rule is the generalisation: `--why` and `--xrefs` are not redundant spellings.
    `--xrefs` *selects* literal-reference mode and **replaces** the branch scan, so passing both
    silently drops the scan that `--why` appears to promise. Two options that sound additive
    deserve to be read in the source before they are believed to compose.

46. **When your own two tools agree and the artefact disagrees, that is three findings, not one
    — and the majority is not a tiebreaker.** Every one of the 13,118 Thumb `ldr rX,[r15,#imm]`
    sites in this ROM is decoded two ways: the generated C++ and `thumb_dump.py` print an
    immediate that is **exactly 4×** the imm8 the cartridge image encodes, and the strict ARMv4T
    reading `Align(PC,4) + imm8` lands on a halfword address holding a non-pointer
    (`0x08000278` → `0x0800027E` → `0x80084902`). The running guest agrees with the ×4 reading,
    so the ×4 convention is what the recomp executes. That does **not** make the disagreement go
    away, and the temptation is to record "two of our tools agree, so the ROM is odd". The three
    statements that are actually on the table are: (a) the generator's comment is right and the
    ROM image does not encode what the hardware would read; (b) both decoders are wrong and the
    recomp is loading constants from the wrong words; (c) the ROM is correct, and the mismatch is
    in how the image is read. They have very different consequences — (b) invalidates every
    literal load in the build. **Resolve it with an artefact outside the project, or leave it
    open and label it open.** The third-party decomp was consulted for that purpose and contains
    neither `0x03000c3a` nor an `08000278` disassembly, so it did not arbitrate; the finding
    stayed open rather than being closed by a vote among three artefacts, two of which are ours.
    The tool records the ambiguity at every site instead of picking a side (`func_dump.py` prints
    a `!! G21` line wherever the two encodings disagree), and its self-test asserts *detection*,
    never the verdict — a self-test that encodes an open question as its expected value converts
    the question into a fact the moment it is written down.

47. **A negative built from sampled snapshots is a duty-cycle claim wearing an absence's clothes.**
    Five mid-run IWRAM reads of `gSubReason` — frames 11,500 / 12,000 / 13,001 / 14,001 / 15,501 —
    all showed `0`, and the previous version of G20 published that as *"the gate is shut across the
    whole crossing window"*. It is shut **at those five instants** and nothing more. The gate is a
    pulse: the same address takes the value `2` at vblank 5,429 and again at vblank **8,915**, from
    two different publishers (`gf_tfunc_080919B0`, a generic setter reached by tail branch from
    seven sites, and `gf_tfunc_08079AD0`). 8,915 is inside the window the snapshots called shut.
    The fix is not more care with the snapshots; it is the **instrument**. A value-filtered
    watchpoint with a min-frame fires on the *recurrence*; a snapshot can only ever report the
    value where it landed. Whenever the claim is about a quantity that changes over time, ask
    which of the two the instrument can actually see, and prefer the one that fires on the thing
    you claim is absent. This is rule 32 again from the sampling side — a negative whose instrument
    cannot see the case is not an absence — and the cheapest way to tell them apart is to re-run
    the *identical* instrument shape against a case the instrument is known to catch. The value-2
    watch was controlled that way: the same address, same filter shape, value `0`, aborts at
    vblank 5,419, so the filter is demonstrably armed.

48. **Before calling a block "a request API with argument *N*", check whether it reloads *N*.**
    `gf_tfunc_08000500` reads a gate byte with `ldrb r1,[r0]` — **into the very register that
    carried the argument in** — and the block it conditionally reaches, `gf_tfunc_08000518`, then
    stores that register into the exit index `0x03000025`. Read at the call site it is a
    "go to transition *r1*" request. Read past the load, the value being stored is `[0x03000022]`,
    which the preceding `cmps r1,#0x0 / beq` has just proven is **zero** — so the path writes exit
    index **0**, and index 0 is the level-entry record. It is a level re-entry, not a traversal.
    The register-reload is three instructions away from the call site and invisible to a
    signature-based reading, so the two interpretations differ completely while looking identical
    at the call. Argument-passing conventions are a property of the *callee*, established by
    reading the callee, and the cheapest test is: **does any instruction between the entry and the
    use write the register you think is carrying the value?**

49. **Establish what else is driving the input before citing attract-mode behaviour as
    input-driven.** The attract demo is not a passive recording played back by a playerless
    driver; it **DMA-feeds its own recorded button stream into the input buffer from inside the
    room loader**. `0x03001894` is `obj/demo_input.o(iwram_data)` by the cartridge's own symbols;
    `gf_tfunc_08072B74` sets that state byte to 2 and does nothing else; `gf_tfunc_08072964`, while
    it is 2, re-arms DMA3 with `*(u32*)(0x0878F5F4 + 4*r8)` → `REG_DMA3SAD`, destination
    `0x03002CC8 gDemoInputs`, count `(*(u16*)(0x0840084C + 2*r8) >> 1) | 0x80000000`. So the demo's
    room 0 → room 2 crossing at frame 9,010 is caused by the demo's own input, and citing it as
    evidence that transitions respond to input is citing the game's own scripted path. The
    supporting tell was already in hand and unheeded: `logs/routes/demo-input-stream.csv` ends at
    frame **5,525**, long before 9,010 — the button stream demonstrably stops while the transition
    still happens, which is only explicable if something else supplies input. **A game that can
    inject input has two input sources at once, and a replay experiment has to establish which one
    is live at the moment of the transition.** Here host input does reach Wario (RIGHT moves him
    from spawn to x = 2337), so the replay path is live — but only for routes short enough, or
    early enough, that the demo is not also running.

50. **Enumerate every writer of a variable before spending a route on it.** A runtime watchpoint
    costs ~90 seconds of wall clock and tells you what happened; a writer census costs one `grep` of
    the literal and tells you what *can* happen, which is strictly more information. In round 29 the
    state index `gUnk_3004770` had exactly three literal references — one read and two writes — and
    the two writes were `movs r2,#0 / … strh r2` inside a function whose entry is
    `movs r2,#0x0 / strh r2,[r0]` (an initialiser, not a setter) and
    `ldrh / adds #4 / ands #0xFF / strh` (a **+4 increment**, not the masked rotate the instruction
    sequence looks like at a glance). Two reads of the code therefore prove the index is always a
    multiple of 4, so only handlers #0 and #4 of its 8-way table are reachable — and only handler #7
    contains the write axis G needed. The structural proof cost seconds; the confirming route cost
    92 s and returned exactly what arithmetic had already established. **Classify a variable's
    writers first; run the probe only to measure, never to discover.** When the census comes back
    with one writer, read that writer before counting it — a function that zeroes at entry and then
    stores the same register is an initialiser wearing a setter's clothes, and `adds #4` before an
    `ands #0xFF` is an increment, not a rotate.


51. **A bit in a guest variable names a hardware button only after you read the register's
    layout — and the two buttons most likely to be confused are adjacent.** Round 30 spent
    three rounds proving that `gUnk_3004770`'s only reachable handlers were inert, that the
    traversal selector `0x03000C35` could never be set to 2, that the scanner's inputs were
    never filled and that the room index was never written — all correct, and all downstream
    of one fact nobody had checked: **every input replay in `tests/input/` holds RIGHT and taps
    A**. `gf_tfunc_0801B958` requests the traversal when **bit `0x8`** of `0x03001848` is set,
    and on the GBA keyinput register bit `0x8` is **Start** (`0x01` A, `0x02` B, `0x04` Select,
    `0x08` Start, `0x10` Right). A and Start are one bit apart, the replays tapped A, and the
    gap looked like missing code for three rounds. Two facts settle it cheaply, and both are
    one census each: **`REG_KEYINPUT 0x04000130` has exactly one literal-load site**
    (`0x08000956`), so `gf_tfunc_08000954` is the single place input enters the game and its
    stores give the three words their meaning — `0x03001844` held, `0x03001846` previous held,
    `0x03001848` `held & ~prev` pressed edges; and **the mask constant in that same function is
    `0x000003FF`**, which is the keyinput width and so fixes the numbering. The reading is then
    cross-checked against unrelated code: four sites test the literal `0x9` (A **or** Start —
    the menu confirm pair) and two test `0x40` (Up). *When a guest bit selects behaviour, read
    the producer's own constants before assuming the platform's, and print the bit histogram of
    the replay you are about to believe — a replay that exercises a different button than the
    code under test is a control that agrees with itself for the wrong reason.* Corollary: a
    button-mash replay is not a safer version of a single-tap replay, it is a different route —
    449 Start taps drove the game back to the title screen (`interpreted_insns=1307982`), which
    is the same counter value as a genuine title route and would have read as success.

52. **A flag that is never written names a state you have not reached, not a code path you have
    not found.** `gSwitchPressed 0x03000C0D` was never written in 30,000 frames of RIGHT-hold,
    which reads like missing code and is not: its only writer is `func_802B694`, reachable only
    from `SpriteSwitch` **pose 17** — an *armed* pose that nothing inside the switch machine ever
    enters (both intro paths end at pose 16, which has no dispatch arm at all). The blocker was a
    pose, and poses are entered by the player's position, not by the player. *When a flag's write
    census comes back with exactly one caller, read that caller's dispatcher and ask which of its
    arms the player can reach — the gap is a state, not a statement.* Corollary for replays: **a
    button must be held at the moment the player reaches the object that reacts to it.** The 449
    frames of A in `probe-hop-right` are frames 5300–5749; Wario is still ~1,000 pixels from the
    switch, which he reaches around frame 11,600. The hammer was never swung *at* anything.
    Holding the same button for 250 frames starting at frame 12,000 is the single changed variable
    that produced the room change, so the control and the treatment differ by one thing and nothing
    else.

53. **A first-write watchpoint reports the first hop of a chain, not where the chain ends.** The
    round-31 acceptance evidence was a clean, correct line —
    `pc=0x0806B92C <gf_tfunc_0806B90C+0x20> addr=0x03000024 value=0x00000002` — and the report
    it produced said "room 0 → 2". Enumerating the variable afterwards showed the route takes
    **two** hops at that one instruction: `value=2` with `r3=0x083F2FB8`, then `value=6` with
    `r3=0x083F3018`, and IWRAM snapshots show `gCurrentRoom` stably **6** from frame 11,402 to
    13,200. `-AbortMemAddr X` stops at the first hit, which is the definition of a *first* hit and
    never claims to be the last. *When the evidence you are about to publish is "the first time X
    happened", run the instrument that can see the second and third time before writing the
    sentence — one extra value-filtered run is cheaper than a corrected report.* Corollary: a
    write-point value is not the variable's value; compare it against a snapshot before believing
    a transition chain.

54. **A `[switch]` parameter takes no value; `-Switch $true` does not error, it binds `$true` to
    the next positional parameter.** `run-route.ps1`'s first positional parameter is
    `[string]$Exe`, so `-Window $true` produced `Executable not found: True` — an error three
    layers from the mistake, pointing at a build artefact rather than at a command line. `-Window`
    is `[switch]` at `tools/validation/run-route.ps1:50`; `-Window $true` was a memory of a
    different script's convention. *A parameter that accepted the value would have been a lie and
    this one was worse: it accepted the value and put it somewhere else.* Corollary: when an
    argument-parsing failure names a *file* or a *path* that you did not pass, suspect the value
    two tokens earlier.

55. **A value-filtered watchpoint enumerates the values you guessed, not the values that happen.**
    Round 32 counted the room transitions on the hammer route by watching `gCurrentRoom` with no
    filter (which reports only the *first* hit, rule 53) and then with filters for the two values
    the first hit suggested. Two hits, so "two hops", and that went into `KNOWN_ISSUES.md` as a
    finding. Round 33's IWRAM sweep at 500-frame intervals shows the route is
    **room 0 → 2 → 3 → 4 → 5 → 6**, six rooms, five transitions — rooms 3, 4 and 5 were never a
    candidate because nobody guessed them. *Two different filters on the same variable produced two
    different, each internally consistent, and one of them was published.* The instrument that does
    not have this failure mode is a periodic whole-state sample (here `observe_read.py --marks`),
    because it reports the timeline rather than the set of hits. Corollary: a hop count is a claim
    about *every* write, and a filter can only ever support a claim about the values in the filter.

56. **A struct size read out of a header is a claim about the header; measure the stride against the
    live table.** `struct PrimarySpriteData` is 0x2C in `include/sprite.h:432-463`, but
    24 × 0x2C = 0x420 does not span the 0x520 gap from `gSpriteData 0x03000104` to
    `gUnk_3000524 0x03000524`, so the header was not evidence either way. Decoding the same snapshot
    at strides 0x2C / 0x30 / 0x38 / 0x40 settles it: 0x2C yields six live sprites with sensible
    `status`/`globalID`/`pose`/`xPosition`; 0x30 and 0x38 report `status=0x0031`, `x=4096`,
    `globalID=0`, and two *different* decodings of the *same* slot count as live; 0x40 drops half
    the real sprites. *A decoder that is wrong for your data does not error, it reports a plausible
    table* — print the count (rule 39) and check that a slot you can name appears in one stride and
    not in the others.

57. **A replay file is not evidence that the host drove the input; watch the joypad word's writer.**
    Round 33 published G22's resolution — "the room change is triggered by the player's HAMMER at
    the room-0 switch" — from a run whose `-InputReplay` file held RIGHT plus A. In round 34 a
    watchpoint on `gButtonsHeld 0x03001844` value-filtered to `0x20` aborted at
    `pc=0x080103D6 <gf_tfunc_080103CC+0xA> (vblanks=9655)` on that very route: **LEFT, written by
    the attract-demo input player, while the replay held RIGHT.** Twenty-three IWRAM snapshots then
    showed `gButtonsHeld` tracking the demo's own `gDemoInputs[gDemoSequenceIndex]` in 15 of 16
    samples, including samples where it contradicted the host. Nothing about the run was wrong; the
    *attribution* was. The whole traversal, and the 变身 at vblank 10,063, are the demo's.
    *Corollaries.* (a) This is rule 49 restated after it was already written and still got violated:
    knowing the demo competes is not the same as proving, per run, that it won. (b) The cheapest
    proof is one watchpoint on the joypad word with a value that **contradicts** what the replay
    says — a matching value proves nothing. (c) A route that runs long enough to enter attract mode
    is suspect by default; the host's own input must be shown to reach the guest on that run.
    (d) `interpreted_insns` is not a behaviour fingerprint: `ctrl-idle-13500` and the new
    `host-walk-13500` both report 13 misses / 1318122 instructions and have different frame hashes.

58. **A measured world-geometry fact is worth more than another input guess.** Four host replays
    (walking right, holding right, A-tapping in place, A+right from the spawn column) all failed to
    produce 变身, and all four failed for the same reason that was measurable in one sweep: the
    exit record for room 0 is gated to rows `c4=8 … c5=10` while Wario stands at y = 1279. A fifth
    blind input attempt would have failed the same way. *When a route keeps missing, stop adding
    buttons and decode the geometry* — here the 12-byte exit records at
    `r3 = base + 12 * gUnk_3000025` turned "I need to get to room 4" into "I need to climb out of a
    y-gated corridor first", which is a solvable problem and a different one from the one being
    attacked.

59. **A field offset is only an offset inside its struct; resolve the struct before grepping for
    it.** Searching the decomp's `asm/` for `strb rX, [rY, #30]` produced 500+ hits and no answer,
    because byte `0x1E` of `PrimarySpriteData` is `warioCollision` (`include/sprite.h:432-463`) while
    byte `0x1E` of `WarioData` is something else entirely. The productive form of the same search is
    *pair every write with the immediate that precedes it* and then read one setter in full: only
    the `asm/sprite_ai/*` files are `PrimarySpriteData`, and
    `asm/sprite_ai/disasm_chandelier.s:4-56` (`func_8069734`, the chandelier's `SetCommonProperties`)
    states the whole pattern in five lines —
    ```asm
    mov r0, #14
    strb r0, [r1, #30]   @ gCurrentSprite.warioCollision = 0x0E (FLAMING)
    ```
    Unconditional, at spawn, with `hitboxExtentUp=96, hitboxExtentDown=192, hitboxExtentLeft=48,
    hitboxExtentRight=44`. *One settler read end-to-end beats five hundred grep hits.*

60. **Compute an encoded input mask from its bit table; never type it.** The `tests/input` replays
    carry `keyinput_active_low`, and `0x3FF & ~(A | LEFT)` is `0x3DE`, not the `0x3BE` I wrote by
    hand — so the "A+LEFT" run was really A+B+LEFT and its negative was a fact about the wrong
    button. Bits are `bit0 A, bit1 B, bit2 SELECT, bit3 START, bit4 RIGHT, bit5 LEFT, bit6 UP,
    bit7 DOWN`; release to `0x3FF`. *If a replay row's mask cannot be reproduced from the table in one
    multiplication, delete the run — a mis-encoded row is an unrepeatable experiment.*

61. **A directory listing without `-Recurse` is evidence that the top level is empty, not that the
    directory is.** `Get-ChildItem asm -File` returned a 59-file top level and I concluded
    `asm/wario/` did not exist; it does, with `disasm_flaming.s`, `disasm_fat.s`, `disasm_zombie.s`,
    `disasm_snowman.s`, `disasm_bouncy.s`, `disasm_puffy.s`, `disasm_bat.s`, `disasm_flat.s`,
    `disasm_frozen.s`, `disasm_mask.s`, `disasm_normal.s` and `disasm_swimming.s`, plus 67 files
    under `asm/sprite_ai/`. Every one of the questions an hour of tracing was trying to answer had
    an answer in there. *Ask for the paths, and check `asm/`, `src/` and `include/` as directories —
    a negative derived from a file-only listing is the most expensive kind of wrong.*

62. **A debug-protocol field name that the server ignores returns a short payload, not an error.**
    `read_iwram` on the `--tcp-observe` server wants `len=` (`gbarecomp-main/src/debug/tcp_debug_server.cpp`,
    client reference `tools/validation/observe_read.py:40-59`); passing `length=` instead yielded a reply
    that decoded to one byte, and every later `data[offset]` read raised `IndexError: index out of range`
    — which looked like a corrupt guest, not a bad request. Addresses go in as `addr="0x%08X"` and the
    reply is `{"ok":true,"data":"<hex>"}`. *Check `reply["ok"]` and assert the payload length before
    indexing it; a wrong field name is silent.*

63. **Read a live IWRAM structure from its symbol address, never from a remembered offset.** The
    "live sprite list" quoted in `docs/KNOWN_ISSUES.md` G26 was read from `0x03001B4C`, which is not
    the sprite array — every slot decoded as garbage and three conclusions were drawn from it.
    `symbols/iwram_map.tsv` has `gSpriteData 0x03000104` (`0x420` bytes = 24 × `0x2C`), `gWarioData
    0x03001898`, `gCurrentRoomHeader 0x03000074`, `gBackgroundInfo 0x03000054`, `gCurrentRoom
    0x03000024` (and `gUnk_3000023 0x03000023` is the *level* index, not the room). *Grep the map
    file for the symbol; if it is absent, say "unknown" instead of reusing a number from a note.*

64. **Decode a record table from the symbol the code actually loads, and read the whole loop before
    naming the mechanism.** The room changer was attributed to `func_806DDE4` for several rounds
    because that function resembles a bounds check; `asm/disasm_block.s:4-136` shows `func_806D3C0`
    is what runs per frame, using `x >> 6` / `y >> 6` against the record's `[2..5]` plus a tile
    attribute that must be in `[2, 7]`. *Name the caller, then the callee's exact predicate: a
    plausible-looking function next door is not the mechanism.*

65. **`distinct_misses` is a discovery counter, not a behavioural fingerprint, so a smoke route's
    exact miss count can move without anything having regressed.** `title-input-6000` is recorded at
    10 misses, and the executable rebuilt from an empty tree reported **12** on two consecutive runs.
    The two extra PCs are not noise: `0x08000C68` and `0x08000C76` (both Thumb) are bridged 655 times
    each, and the coverage log names them —
    `bridged 0x08000C68 (thumb) x655 near gf_tfunc_08000C5C`, with `healed=False` on both. They fall
    outside the allowed prefix `0x03007D`, so `smoke.ps1`'s "misses outside the dynamic set" check fails
    while the route's frame PNG stays byte-identical (`697534774d47c51f`) across 10-miss and 12-miss
    runs, and boot / attract / save-load keep their recorded hashes. *For reproducibility claims use the
    frame hash; treat the miss count as an observation about the self-heal race and the interpreter's
    bridge list, and re-record the expectations (or widen the ceiling) before treating a miss-count
    mismatch as a defect.*

## 6. Evidence index (2026-09-30)

| claim | evidence |
| ROM identity, decomp eligibility | `docs/ROM_IDENTITY.json` |
| generation A (vanilla) | `logs/M1-vanilla-generation.log` (11,806 functions) |
| generation B (annotated) | `logs/host-cart-generation.log` (11,915 functions, 1 jump table, 2 code copies) |
| host library / exe built | `logs/M1-vanilla-library-build.log`, `build/host/WarioLand4Recomp.exe` |
| M3 boot, BIOS logo | `logs/routes/boot-120-last.png` (`FULLY_STATIC`, misses 0) |
| M4 title | `logs/routes/tl-5400-last.png` |
| M4 audio | `logs/routes/audio-title-audio.json` (98.73 % non-zero mixed samples) |
| M4 input | `logs/routes/title-input-last.png` (file-select screen after START) |
| determinism | `logs/routes/det-a-last.png` == `det-b-last.png`, `det-a-result.json` == `det-b-result.json` (counters) |
| cold-cache equivalence | `logs/routes/cachetest-900-result.json`, `logs/routes/cc-title-900-result.json` (`healed_native=0`) |
| coverage contract | `logs/routes/title-900-coverage.json` |
| gameplay + D-pad control (E) | `logs/routes/game-13500-last.png`, `ctrl-right-last.png` vs `ctrl-idle-last.png` (1,196 px differ) |
| replay determinism | `logs/routes/ctrl-idle-last.png` == `game-13500-last.png` (0 px differ, independent processes) |
| generation reproducibility (A) | two independent `gba_recompile` runs → 11 byte-identical files (the per-file SHA-256s are recorded in the bring-up round that produced them; the current pin's regenerated output is confirmed byte-identical in `docs/RELEASE_AUDIT.md` §10) |
| framework build reproducibility | `build/framework/Release/gba_recompile.exe` SHA-256 `A9D792EF…` == `docs/FRAMEWORK_PIN.json` |
| gameplay-path triage (G6) | `logs/routes/ctrl-idle-coverage.json` (misses 59 → 13, cart-ROM 0), `ctrl-right-coverage.json`; both frames byte-identical to the pre-triage run |
| smoke baseline (I) | `tests/routes/smoke-expectations.json`; `tools/validation/smoke.ps1` passes it end to end |
| attract-demo gap (G7) | `tools/validation/run-route.ps1 -Tag attract-demo-13500 -Frames 13500` → 172 misses before, **8 after** the triage, frame byte-identical, `smoke.ps1` still PASS |
| gameplay verbs (F) | `tools/validation/verb-ab.ps1` → jump 1,227 px, attack 1,706 px, dash 1,238 px, crouch 716 px all differ from their same-frame controls; frames `logs/routes/verb-*-last.png`, magnified pair `logs/routes/verb-crouch-compare.png` |
| persistence round trip (H) | `logs/routes/h-save.sav` (32,768 non-0xFF bytes, sha256 `2476EE2E…`), `logs/routes/save-write.log` (`save_flushed` ×6), `logs/routes/save-load.log` (`save_loaded 32768/32768`), `logs/routes/save-load-last.png` vs `title-input-last.png` (1,352 px differ, bbox = the SAVE A row) |
| mid-run capture (G tooling) | `logs/routes/strip-left-frames/f_012040.png … f_012139.png` (100 consecutive frames) + `tools/validation/frame-strip.ps1` → camera shift 0→3 px between frames 12,040 and 12,045, then constant through 12,139 |
| gameplay audio (G) | `logs/routes/audio-gameplay-audio.json` — guest frame 13,067: `SOUNDCNT_L=0xFF77 SOUNDCNT_H=0x210E SOUNDCNT_X=0x008F`, mixed 99.29 % non-zero (peak 8,736, rms 3,440.23 of 4,096 samples), Direct Sound A/B 97.39 %/97.58 % non-zero, DMA1/DMA2 182,731 runs feeding both FIFOs |
| door probes (G, negative) | `logs/routes/verb-up-idle-last.png` (631 px, Wario band only), `verb-down-right-last.png` (424 px, Wario band only), `verb-up-right-last.png` (0 px vs `ctrl-right-last.png`) |
| framework gaps found by the filmstrip work | `docs/KNOWN_ISSUES.md` F8 (`--tcp` bypasses input replay and the frame bound) and G8 (mid-run capture needs `-Window` and present-in-place off) |
| attract-demo deep run (G/I) | `tools/validation/tcp-filmstrip.ps1 -Tag attract-strip` → 12 captures, `logs/routes/attract-strip-f{3000,4500,6000,7500,9000,10500,12000,13500,15000,16500,18000,19000}.png` + `logs/routes/attract-strip-filmstrip.json`; frame `19013` shows demo level 2 (beach) |
| attract-demo deep-run triage (G9) | `logs/routes/attract-strip-coverage.json` (15 misses: 11 IWRAM + 4 cart-ROM `0x0802A258/0x0802A26E/0x0802A656/0x0802A680`, all `interior-label`) → merged into `game.toml`; `logs/routes/attract-deep-19000-coverage.json` = **11 misses, all dynamic** |
| cross-mode determinism (capture path is faithful) | `logs/routes/left-12139-last.png` sha256 `66787E63…` == `logs/routes/strip-left-frames/f_012139.png` (headless vs windowed framedump) |
| the merge is behaviour-preserving | `logs/routes/left-12139b-last.png` == `left-12139-last.png`; `smoke.ps1` PASS with every recorded frame/counter unchanged after the rebuild |
| guest-memory observability | `tools/validation/tcp-snapshot.ps1` → 37 IWRAM snapshots over the demo (`logs/routes/snap-demo-iwram/*.bin`, frames 1036…19007); `snapshot-diff.py` → 8,718 offsets change, 24,050 constant; the standout non-stack signal is u16 `0x000026` = 0 → 9474 (frame 9010) → 4866 (14513) → 514 (18500), i.e. it steps exactly at the demo's level changes |
| HUD health readout | `tools/validation/hud-hearts.ps1` → red totals 0 on the title, 120/143/167/161/130 across the demo's rooms (`logs/routes/hud-hearts-compare.png` shows the rows magnified); 43-capture `heartwatch` never steps down by a whole heart inside a level |
| mid-run health series | `logs/routes/damage-dump-hearts.csv` (800 consecutive frames 18,500–19,299): red total 167 for 367 consecutive frames, one 15-frame fade to 0 at 18,899–18,916 (a screen transition), then 167 again — no damage event |
| cross-mode determinism, extended | `logs/routes/win-9000-frames/f_009000.png` == `refdemo-9000-last.png` (`0643f179…`), `logs/routes/win-19000-frames/f_019000.png` == `det-noinput-a-last.png` (`ba51e420…`), `logs/routes/noinput-win-19000-frames/f_019000.png` == the same headless frame — headless, windowed and replay-driven windowed all agree at the same guest frame |
| the windowed capture path can be contaminated (G10) | `logs/routes/damage-dump-frames/f_019000.png` (`17ea7de1…`, level-1 hall 001230) versus the same-mode rerun `logs/routes/win-19000-frames/f_019000.png` (`ba51e420…`, level-2 beach 000660); counters 1,312,902 / 51,582 versus 1,317,222 / 135,985 |
| named guest IWRAM map | `symbols/iwram_map.tsv` — 554 entries (552 named) from `third_party/lilDavid-warioland4/linker.ld`, extracted by `tools/validation/parse_linker_map.py`; validated against the snapshot series rather than trusted (`0x0024` climbs 2→10 then resets, `0x0026` falls 9474→514) |
| damage caught at instruction level (F) | `logs/routes/heartloss.err.log`: `runtime_trace: mem-write-addr abort pc=0x080135C4 <gf_autojt_080132A8_18+0x10> addr=0x03001910 value=0x00000003 width=1 (vblanks=12561)` — `gHeartMeter.current` written 3 at guest frame 12,561; the instruction is `strb r0, [r1, #0]` in `asm/wario/disasm_normal.s` `.L_135b4`, where `r1` is loaded from the pool entry `.L_135f4: .4byte gHeartMeter` |
| health before/after (F) | `logs/routes/heart-hud-compare.png` (magnified heart row and gauge: 4 hearts at 12,258 → 3 at 12,758 → 3 at 13,005 → 5 at 13,508) and `gHeartMeter` in the snapshot series: 4 (9,010) → 3 (13,004) → 5 (13,500) → 4 (18,500) → 3 (19,007) |
| 变身 axis was a named negative by sampling | the same 37 snapshots: `gWarioData.reaction` (`0x03001898`) is `REACTION_NORMAL` (0) in every sample while `pose` (`0x1899`) moves through 0/4/7/22/28/37 — superseded by the value-gated enumeration below, which is falsifiable at 1-frame resolution instead of 500 |
| decomp symbol harvest without a build | `symbols/decomp_readelf_syms.txt` (6,892 rows, 448,607 bytes) from `tools/validation/parse_decomp_symbols.py`: 3,327 addressed functions (thumb 3,326 / arm 1), 3,013 ROM data symbols covering 7,212,776 bytes, 552 IWRAM globals, 35,653 `.L_` labels; `--verify-rom` → 3,327/3,327 in range and 2-byte aligned, **2,335/3,326 (70.2 %) open with `push {…}`/`bx lr`** |
| overlay accepted by the framework's importer | `symbols/AWAE_symbols.toml` (673 B, `[identity] sha1` only), `imported_symbols.tsv` (3,327), `imported_data_symbols.tsv` (3,565), `function_boundaries.tsv` (136,467 B); importer log: `3327 FUNC, 3565 data`, `data ranges: 0 coalesced`, `rom: sha1=b9fe05a8… size=0x00800000` |
| the overlay is behaviour-preserving (rule 20) | `tools/regeneration/regen.ps1 -CartOnly -SymbolOverlay` → `discovered 15740`, `TOTAL emitted 15740`, 8 shards, dispatch rows 133,792 (all identical to the baseline); rebuilt exe 25,529,220 B sha256 `16fbeef4…`; `smoke.ps1` PASS with boot-120 `f1dd2fdacf2e4263`, attract-3600 `38be8fce4a34f13e`, title-input-6000 `697534774d47c51f`, ctrl-idle-13500 `6d764abd8b801016`, save pair `11eb324834a221af` |
| the overlay is visible where it matters | `generated/cart/data_symbol_map.cpp:177 {0x03001910u, 0x4u, "gHeartMeter"}`; `logs/routes/heartloss-ovl.err.log`: `mem-write-addr abort pc=0x080135C4 <gf_autojt_080132A8_18+0x10> addr=0x03001910 <gHeartMeter+0x0> value=0x00000003 width=1 (vblanks=12561)` — same PC and vblank as the un-annotated run |
| reaction axis is live (F) | `logs/routes/reaction-water.err.log`: `runtime_trace: mem-write-addr abort pc=0x08013D10 <gf_tfunc_08013D06+0xA> addr=0x03001898 value=0x00000001 width=1 (vblanks=10063)` → `REACTION_WATER`; the instruction is `asm/wario/disasm_normal.s:7726 strb r1, [r5, #0]` with the pool entry `.L_13d24 (line 7735) = gWarioData`, guarded by `gUnk_3001918+2` bit 7 and `func_806DAC0(gWarioData.unk_14, gWarioData.unk_12) & 0xFF == 1`, and the `pc=0x0806DAC0` events earlier in the trace are that helper |
| the water episode, bracketed | `logs/routes/reaction-water-end.err.log`: `pc=0x08015F9A <gf_autojt_082DECA0_155+0x12> value=0x00000000 (vblanks=10095)` — 32 vblanks after it was set; the clearing code is a different routine |
| 变身 proved absent from the demo, value by value (F) | `logs/probe_reactions.ps1` gates each of values 2…11 with `-AbortMemValue` for 19,500 frames: **no abort in any of the ten runs** (`logs/routes/reaction-probe-summary.json`); only 1 = `REACTION_WATER` occurs. Full value list from `third_party/lilDavid-warioland4/include/wario.h:19-33` |
| the reaction is visible | `logs/routes/reaction-water-frames-frames/f_010045.png … f_010066.png` (22 consecutive frames across the episode); `f_010064.png` shows Wario in the water on the demo's instruction screen |
| observer mode works on an input route (G13 fix) | `logs/routes/obs-pound.err.log` = `[gbarecomp:runtime] windowed observe TCP on 127.0.0.1:20011 (reads, touch_*, game commands, queued savestates; no step)`; `tools/validation/observe_trace.py` → 71 samples in `logs/routes/obs-pound-trace.txt`; the earlier `tools/validation/observe_read.py` capture `logs/routes/obs-explore/obs-explore-iwram-f{011601,012002,013001,014002}.bin` (32,768 B each) reads the same route the headless watchpoints measured |
| room 0 decoded from live memory | `logs/decode_wario.py logs/routes/obs-explore/obs-explore-iwram-f011601.bin`: `gCurrentRoomHeader` (0x03000074) = tileset 0x50, pBg0 0x08598EEC, pNormalSpriteData 0x085991D0, water 0xFF, musicVolume 0x100; room sprite table at `gUnk_3000964` (0x03000964) = `[0] y=15 x=26 spawn=0x08`, `[1] y=15 x=31 spawn=0x11`, `[2] y=19 x=7 spawn=0x14`, terminated by 0xFF; live `gSpriteData` (0x03000104) = `PSPRITE_SWITCH` id 7 @ (1696,1024) and `PSPRITE_VORTEX` id 0x29 @ (2016,1024) + two vortex parts — positions reproduce `(yBlock<<6)+64`, `(xBlock<<6)+32` exactly (`asm/disasm_sprite.s func_801E0EC`) |
| the gate chain is understood (G) | `gSwitchPressed` (0x03000C0D) has exactly one writer in the decomp — `asm/sprite_ai/disasm_switch.s:237-239` inside `func_802B694`, the switch sprite's pose-17 handler; the vortex (`src/sprite_ai/vortex.c:202/227/242`) only leaves `SPOSE_18` when that flag is set, and entering the grown vortex sets `gSubGameMode = 6` (`vortex.c:465` / `:511`) → `src/game_screen.c:134 func_80720E8()` = level exit |
| the switch cannot be pressed from the reachable room (G, negative) | `logs/routes/switch-hunt.err.log` and `logs/routes/switch-hunt2.err.log`: 20,000-frame routes that walk into the switch and hammer A / held-A / DOWN / UP / B / jump-slam at both ends of the band finish `exit=0` with **no write to 0x03000C0D after frame 12,000**; the switch sprite runs pose 111 → 113 → 16 (`func_802B5E4` → `func_802B62C` → `func_802B668`) and this room never reaches pose 17 |
| the room-0 sprite classes (F) | the same trace: live `warioCollision` values are 0x30 (switch) and 6 (vortex + parts) — none of the transformation classes 0x0E/0x0F/0x10/0x11/0x12/0x13/0x14/0x15/0x1F/0x27 — so priority F 变身 cannot be demonstrated in this room |
| the gSwitchPressed address is a ROM-level fact | `logs/find_switch_literal.py`: the 4-byte constant `0D 0C 00 03` occurs 25 times in the ROM and at VRom `0x0802B724`, which is the pool label `.L_2b724` loaded by the one `strb r1, [r0, #0]` in `func_802B694` (rule 26) |
| the room changer is `func_806D3C0`, not `func_806DDE4` | `third_party/lilDavid-warioland4/asm/disasm_block.s:4-136`: per frame `r9 = xPosition >> 6`, `r8 = yPosition >> 6`, accept a record with `[1] == gCurrentRoom`, `[2] <= r9 <= [3]`, `[4] <= r8 <= [5]` **and** `(r7 - 2) <= 5` (`:70-86`), then encode the index as `gUnk_300004C[1] = index/10`, `[2] |= index%10` (`:108-119`) |
| the guest room changer fires — observed, no host input | `tools/validation/run-route.ps1 -Tag attr-roomchange -Frames 10000 -Window -TcpObserve 20032` + `tools/validation/wario_watch.py --port 20032 --from 8300 --to 9200 --every 10 --out logs/routes/attr-room-trace.txt`: at vblank **9201** Wario is at `(1974, 831)` (`x>>6 = 30…31`, `y>>6 = 12…13`), `gCurrentRoom = 0`, `gSubGameMode` **2 → 3**, matching row 5 of `0x083F2F88` (`type=2 dest=2 x=31..31 y=11..12`); the demo walks the upper floor `y = 959` from `x ≈ 293`, is bounced by a sprite at `x = 910`, and enters the door from the `y = 831` platform |
| room 0 geometry, from the live guest | `tools/validation/room_probe.py --port 20033 --at 12500` (`run-route.ps1 -Tag room-probe -InputReplay tests/input/f43-holdA.keyinput.txt -Frames 14000 -Window -TcpObserve 20033`): `gCurrentRoomHeader` `0x03000074` = tileset `0x50`, pBg0..pBg3 `0x08598EEC`/`0x085991DC`/`0x08599454`/`0x085FA6D0`, `+0x18 = 0x00070101`, `+0x1C`/`+0x20` = `0x085991D0`, `+0x24 = 0x08599448`; `gBackgroundInfo` `0x03000054` width **41** height **23** cells → **2624 × 1472 px** |
| the sprite array base (rule 63) | `symbols/iwram_map.tsv` → `0x03000104 gSpriteData 0x420` = 24 × `0x2C`; read from there, room 0's live sprites are `7 PSPRITE_SWITCH` @ (1696,1024), `41 PSPRITE_VORTEX` @ (2016,1024) status `139`, children `165`/`163`, and `179`. The base `0x03001B4C` used for the G26 "live sprite" claim is **not** the array |
| the exit-record table is a base-pointer table | `third_party/lilDavid-warioland4/asm/blob_0x78EBF0-0x78F5A4.s:59-62` (`baserom_blob 0x78F21C, 0x78F280`) + `docs/KNOWN_ISSUES.md` G20's trace `*(0x0878F21C) = 0x083F2F88`; level 0's 30 records re-dumped from the ROM at file offset `0x3F2F88` (`ROM_BASE = 0x08000000`, `tools/validation/rom_calls.py:28`), and the `type 1` `u16` is the entry tile: level 0 record 0 `u16 = 672` = tile (32,10), level 1 record 0 `u16 = 651` = tile (27,10) |

## 7. Not verified

* **Gameplay: what is still open** — a level is entered, the D-pad moves Wario
  (`game-8600`, `game-13500`, `ctrl-right` vs `ctrl-idle`), A/B/DOWN are all
  consumed (`verb-jump`, `verb-attack`, `verb-dash`, `verb-crouch`, re-run by
  `tools/validation/verb-ab.ps1`), and as of 2026-09-30 **damage is
  demonstrated**: `gHeartMeter.current` (`0x03001910`) goes 4 → 3 at guest frame
  12,561, written by `strb r0, [r1, #0]` at `0x080135C4`
  (`asm/wario/disasm_normal.s`, block `.L_135b4`), with
  `logs/routes/heart-hud-compare.png` as the pixel corroboration. **The reaction
  axis is live but the demo only reaches water**: `gWarioData.reaction`
  (`0x03001898`) is written `1` (`REACTION_WATER`) at vblank 10,063 by
  `strb r1, [r5, #0]` at `0x08013D10`, and back to `0` at vblank 10,095 — and the
  ten *transformation* values (FLAMING/FAT/FROZEN/ZOMBIE/SNOWMAN/BOUNCY/PUFFY/BAT/
  FLAT/MASK) are absent from the whole 19,500-frame demo, proved by one gated run
  per value rather than by sampling. **Still not** demonstrated: a transformation,
  a *player-driven* room or level transition, and completing a level. As of
  2026-09-30 the reason is measured rather than suspected: the new-game route plays
  **room 0**, whose entire live sprite set is a `PSPRITE_SWITCH` (id 7, class 0x30)
  and a dormant `PSPRITE_VORTEX` (id 0x29, class 6) — **no sprite carries any
  transformation class at all** — while Wario's walkable range in that room is ~580
  raw units (rules 24-26). The room's only exit mechanism is switch → `gSwitchPressed`
  → vortex → `gSubGameMode = 6`, and two 20,000-frame hammer routes (`switch-hunt`,
  `switch-hunt2`) never write `0x03000C0D`: the switch runs pose 111 → 113 → 16 and
  this room never reaches pose 17, the only pose that presses it. The class map in
  the evidence index says which sprite would have to be reached for each
  transformation. Priorities F and G therefore remain partly open: F only for 变身,
  G only for the input-driven half. Worth recording that every
  pixel-level instrument tried first reported "no damage" — the demo's HUD total,
  the 800-frame window, and the snapshot histogram all missed it. What found it was
  the decomp-sourced IWRAM map plus a write watchpoint (rules 17-18), and the same
  instrument is what named the water reaction (rule 22). The room-decode round added
  the missing half of that instrument: `--tcp-observe` makes an input route readable
  at any frame (rule 25), so the next negative does not have to be bought with one
  process per question.
* **Capture-mode trust** — headless, windowed (replay-driven) and TCP captures
  agree at the same guest frame, but only the replay-driven window is safe: one
  windowed no-replay run (`damage-dump`) silently sat on a different demo phase
  (G10). The mid-run health series therefore describes that other phase (level 1,
  not level 2), which is a valid observation but not the same run as the TCP
  heartwatch series it was compared with.
* **Decomp symbol coverage is partial by construction** — the harvest places
  3,327 of the 3,589 named functions; **262 named functions carry no address in
  their name** and are skipped rather than guessed (`_start`, `irq_handler`,
  `entry_point`, the whole `m4a_asm.s` sound driver, `WarioProcessControls`,
  `SpriteAerodent` and ~200 sprite-AI routines). Placing them needs either a
  decomp build (ruled out here: the machine has no WSL and installs none) or a
  constrained identification pass against the recompiler's own discovered set.
  The overlay is therefore opt-in (`regen.ps1 -SymbolOverlay`), not the default.
* **Level transitions observed indirectly** — the scripted new-game route shows a
  visibly different room at frame 8,600 (golden temple) than at 13,500 (lilac
  stone), and the game's own demo (`attract-strip`, frames 9,000 → 13,500) walks
  across several rooms while the coin counter climbs 000050 → 003150. Both show
  the game's *own* transitions working; no route has shown a transition *caused
  by* host input, which is what priority G asks for.
* **Gameplay audio** is measured only on the no-input attract route
  (`audio-gameplay-audio.json`, frame 13,067), because the TCP debug server cannot
  drive an input route (F8). The evidence is the mixer capture ring, not a
  speaker.
* **Gameplay-path static coverage** — the 62 cartridge-ROM misses that entering a
  level used to add are covered as of 2026-09-30 (`docs/KNOWN_ISSUES.md` G6); what
  remains on every route is the 13-PC dynamic stack-stub set, which no static
  metadata can express (F6). `GBARECOMP_STRICT_STATIC=1` therefore still fails.
* **Persistence (H)** — the round trip passes (write in one process, load in
  another, and the loaded state visible on the file-select screen), but it is
  verified by *state visibility*, not by a byte-for-byte comparison against a
  known-good save, and the save *type* still comes only from the runtime's own
  signature detection (`SRAM_V` @ `0x283EF8`) rather than a cartridge-database
  cross-check.
* **The decomp-annotated A/B** (§4 of the brief) — blocked: no
  `arm-none-eabi-objdump`, no WSL in this environment, and the decomp has not
  been rebuilt, so no symbol addresses exist to import.
* **Windows/audio output on a real device** — every route here is headless; audio
  is verified through the mixer capture ring, not through speakers.

## 8. Smoke test (one command)

```powershell
tools/validation/smoke.ps1            # full check, ~4 min
tools/validation/smoke.ps1 -Quick     # skip the three 13,500-frame routes
tools/validation/smoke.ps1 -Record    # re-record the baseline (review the diff!)
```

It runs a fixed route set (`boot-120`, `attract-3600`, `title-input-6000`,
`ctrl-idle-13500`, `host-walk-13500`, `traverse-13500`) plus the persistence round
trip, and fails the run if any route exits non-zero, misses outside the documented
dynamic set (`tests/routes/smoke-expectations.json` → `miss_allowed_prefix`),
exceeds its recorded miss budget, or produces a different final frame. The
expectations file is evidence: when a change legitimately alters a frame or a miss
count, re-record and review that diff — never edit it by hand.

`host-walk-13500` and `traverse-13500` are **not** interchangeable, and the pair is
deliberate: the first is the only pinned case where **host input** reaches Wario
inside a level and moves him, the second is a deterministic pin on the **attract
demo's** traversal and demonstrates nothing about input (rule 57, `docs/KNOWN_ISSUES.md`
G22). Before trusting any scripted run, confirm the input actually reached the guest:

```powershell
Select-String -Path logs\routes\<tag>.log -Pattern 'input_replay='
# expect: input_replay=ENABLED path="…" events=N   (DISABLED means the trace was dropped)
```
