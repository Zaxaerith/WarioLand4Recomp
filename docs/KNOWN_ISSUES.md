# WarioLand4Recomp — Known issues

Two categories, deliberately separated because the fix location differs:

* **Framework** — a defect in `reference/gbarecomp`. Per §6/§13 of `AGENT_PROMPT.md`
  (the working brief, removed before release) the fix belongs upstream in GBARecomp, not in this repo, and the pinned
  snapshot must stay byte-exact. These are recorded here for the M8 framework
  audit and are worked around only through documented configuration/overrides.
* **Game** — something this repository owns (`game.toml`, `CMakeLists.txt`,
  `src/`, `tools/`).

Status values: `OPEN`, `WORKED AROUND`, `FIXED`.

---

## F1 — Asset resolution has no non-interactive mode

* Category: Framework · Status: **OPEN** (worked around in our runner)
* Where: `reference/gbarecomp/src/runtime/asset_picker.cpp:221-243`
  (`resolve_asset`), called from `src/runtime/runtime.cpp:1386` (BIOS) and
  `:1417` (ROM).

When no path resolves — no `--rom`/`--bios`, no sidecar `rom.cfg`/`bios.cfg`,
and the argv path does not load — the picker opens a **modal Win32 file dialog
and blocks forever**. There is no flag or environment variable that makes it
fail closed with a diagnostic.

Observed: `WarioLand4Recomp.exe --help` and a bare `WarioLand4Recomp.exe` sat at
0.69 s CPU / 77 MB with zero bytes on stdout and stderr indefinitely. gdb on the
blocked main thread:

```text
#16 gbarecomp::resolve_asset(...)
#17 gbarecomp::run_game(int, char**, gbarecomp::RunOptions const&)
#18 main()
  ... DialogBoxIndirectParamW / comdlg32!PrintDlgW / NtUserWaitMessage
```

Impact: any un-attended run (CI, headless validation, a scripted route) hangs
instead of failing. Note the `--help` path reaches asset resolution before it
prints usage.

Workaround (ours): `tools/validation/run-route.ps1` always passes explicit,
correctly-quoted `--rom`/`--bios` **and** seeds `rom.cfg`/`bios.cfg` next to the
executable so a bad argument can never reach the dialog.

Suggested upstream fix: a `GBARECOMP_NO_PICKER`-style switch (or auto-detect a
non-interactive console) that turns the picker fallback into a hard error with a
printed diagnostic.

## F2 — Self-heal compiler path is hardcoded to MSYS2 on Windows

* Category: Framework · Status: **WORKED AROUND** (`GBARECOMP_HEAL_CXX`)
* Where: `reference/gbarecomp/src/runtime/overlay_compile.cpp:66-75`
  (`gxx_path`), used at `:378-386`.

`gxx_path()` returns the literal `C:/msys64/mingw64/bin/g++.exe` on Windows
unless `GBARECOMP_HEAL_CXX` is set, while `gcc_toolchain_available()`
(`overlay_loader.cpp:131-145`) probes **PATH** for `g++`/`gcc`/`cc`/`clang`. On a
machine whose MinGW lives anywhere else the probe says "gcc backend", the
invocation then fails in `CreateProcessA`, `run_process` returns `-1`, and every
miss reports:

```text
self_heal: compile FAILED for 0x08001660 (thumb): gcc exit -1 compiling
  recomp_cache\...\08001660_8142260C_t.c — ... staying on the interpreter bridge this session.
```

with a 0-byte compiler log (the compiler never started).

Impact: on any Windows box without MSYS2 at that exact path, self-heal can never
succeed and coverage can never improve toward FULLY_STATIC.

Workaround (ours): `run-route.ps1` exports `GBARECOMP_HEAL_CXX` pointing at the
MinGW g++ that built the host. Measured effect on the same route:
`healed_native 0 → 23`, `native_calls 0 → 346`, `failed 32 → 9`.

## F3 — [CORRECTED] Shipped BIOS config declares no IWRAM copy — but that is not what we saw

* Category: Framework · Status: **OPEN** (narrowed; the original observation was
  misattributed)
* Evidence: BIOS generation reports `code_copy entries: 0`
  (`reference/gbarecomp/bios/gba_bios.toml`).

**Correction.** This entry originally claimed the `0x03007D18`–`0x03007D90`
misses were the BIOS's IWRAM-resident code. That is wrong, and it is withdrawn:
the shipped `bios/gba_bios.bin` contains **none** of those byte sequences
(exhaustive search), while the cartridge contains them, and the trace shows the
cartridge writing them (`docs/KNOWN_ISSUES.md` F6 / `game.toml`'s high-IWRAM
note). Found by `tools/validation/rom_xref.py` + `match_iwram.py` and settled by
`GBARECOMP_TRACE_ON_DISPATCH_MISS=1`.

What survives as a framework observation is narrower and was *not* triggered by
any route we ran: the BIOS image executes from IWRAM at `0x03007E00`-`0x03007FFC`
in real hardware, and the shipped config declares no `[[code_copy]]` for it, so a
route that enters BIOS RAM code would report misses that this repo's `game.toml`
cannot express (its `[[code_copy]]` sources resolve inside the *cartridge*
image). No such miss has been observed here.

Context: `NOT_STATIC` at release time is normal across the ecosystem — the
shipped Mario Kart Super Circuit release reports `coverage:"NOT_STATIC"`,
`distinct_misses:9`, and `MetroidZeroMissionRecomp/recomp_coverage_BMXE.json`
reports `NOT_STATIC` with 45 misses. See F6 for why this may be unfixable by
configuration in principle.

## F4 — `GBARECOMP_DEMO_INPUT` is Metroid Zero Mission content in the framework

* Category: Framework · Status: **OPEN** (we simply do not use it)
* Where: `reference/gbarecomp/src/runtime/runtime.cpp:3775-3830`.

The framework's scripted-input facility hardcodes an MZM button cycle
(`KEY_START, KEY_A, KEY_A, KEY_DOWN, KEY_A, KEY_RIGHT, KEY_B, KEY_A, KEY_LEFT,
KEY_A, KEY_UP, KEY_B`, 6-frame hold/release) and MZM-specific modes
(`walk`, `campaign`, `campaign-combat`, `campaign-traverse`, `campaign-safe`,
`campaign-clear`), with comments referring to "the loaded save", "Z-Saber" and
"Golem".

Impact: it cannot serve as a generic deterministic acceptance route. This repo's
no-input acceptance route is the game's own attract/demo playback
(`src/demo_input.c`, `DemoInputSubroutine`, `DemoInputRecord`, `DemoInputInit`,
`gDemoInputs`, `gDemoInputLengths`). Recorded so the M8 audit can raise it.

## F5 — Jump-table auto-detector does not recognise the 0x0809540C dispatcher

* Category: Framework · Status: **OPEN** (worked around by a hand-written table)
* Where: `reference/gbarecomp/src/recompile/function_finder.cpp` (jump-table
  detector, `GBARECOMP_JT_REPORT=1` prints one `[jt] base=… site=… bound=…
  want=… got=… -> EMIT|reject|overlap` line per candidate).

Generation reported roughly 95 auto-detected tables with 1,699 targets, but the
report contains **no candidate at base `0x0809540C`** even though the cartridge
dispatches through it at ROM `0x08001518`-`0x0800152E`: the code loads the table
base from a literal (the literal word at ROM `0x08001530` is literally
`0x0809540C`), indexes it, and calls through the entry. The detector's patterns
apparently require a `bx`-style dispatch, so this `ldr rT,[pc,#imm]` /
`ldr rX,[rT]` / `bl` index idiom is invisible to it.

Impact: 21 cartridge PCs (`0x080015CC`-`0x08001686`) stayed uncovered, and every
one of them was a real entry in that table. One hand-written declaration removed
all of them:

```toml
[[jump_table]]
addr = 0x0809540C
stride = 4
count = 36
format = "abs32"
entries_mode = "auto"
```

Evidence for the base/count is recorded in `game.toml`: the
copy loop at `0x08001500` moves `mov r1, #0x24` (36) halfword-aligned pointers
from that literal, the table ends at `0x08095498` (the next word, `0x0809549C`, is
`0xe3e2e1e0`, not a pointer), and entries 34/35 are the two PCs (`0x080014B0`,
`0x08001498`) the runtime independently reported as misses.

Suggested upstream fix: also recognise the `ldr rT,[pc,#imm]; ldr rX,[rT];
bl` / `bx` index idiom, and report candidates whose base is only ever reached
through a literal pool.

## F6 — Dynamically generated RAM code cannot be declared, so coverage never reads FULLY_STATIC

* Category: Framework · Status: **OPEN** (blocks a clean M7 gate for this game)
* Where: coverage reporting `src/runtime/runtime_arm_default_aborts.cpp`
  (`self_heal_write_coverage_json`; `fully_static = g_misses.empty() && healed == 0`
  at :261) and the `[[code_copy]]` contract in `docs/TOML_SCHEMA.md`.

The Wario Land 4 cartridge writes a small code stub onto its own stack and
executes it: the ROM code at `0x0800335E` copies `pop {r4,r5}; pop {r1}; bx r1`
to an address derived from the stack pointer, then `mov r3, sp; add r3, #1` and
`bx r3` (full trace and byte evidence in `game.toml`'s high-IWRAM note).
The runtime does the only correct thing — it interprets the
actual bytes at that address — but the framework offers no way to *declare* such
a range as expected dynamic code:

* `[[code_copy]]` is unusable: it requires a fixed RAM address mirroring fixed
  ROM bytes, and this destination moves with the stack (0x03007D44 in one run,
  0x03007D40 in another). Declaring it made the recompiler emit a *static*
  function for the range; the guest then entered at an interior resume offset,
  skipped the prologue, and returned to an unmapped address (`0xD00C2A00`), so
  the run never finished.
* The result is that a 900-frame route reports `coverage: NOT_STATIC`,
  `distinct_misses: 7` — all seven being these dynamic PCs — with no way to
  distinguish them from a genuine discovery gap in the JSON or the miss
  fragment.

Impact: for any game that executes generated RAM code, `NOT_STATIC` is permanent
and `GBARECOMP_STRICT_STATIC=1` can never pass, even when every statically
knowable PC is covered. Today the honest gate is "no *new* misses, and the
remaining set is exactly this documented dynamic set" — see
`docs/VALIDATION.md`.

Suggested upstream: an `[[exec_ram_range]]` (or per-miss `expected = true`)
declaration that marks such PCs expected-interpreted in the coverage JSON and
lets the strict gate pass with a printed allowance.

Related, and fixable here rather than upstream: because
`fully_static = g_misses.empty() && healed == 0`, a *cached* self-heal also keeps
coverage at `NOT_STATIC`. This repo's 900-frame route reports
`healed_native: 23`, i.e. 23 ROM PCs discovered only at runtime, healed by the
self-heal compiler and now served from `recomp_cache`. Those PCs *are* statically
coverable and should be folded back into `game.toml` — that is the real next
step for M7, and it is tracked as G5.

---

## G1 — `Start-Process -ArgumentList <array>` does not quote

* Category: Game (our tooling) · Status: **FIXED**
* Where: `tools/validation/run-route.ps1`.

`Start-Process -ArgumentList` joins an array with spaces and does not quote
elements, so `--rom ...\Wario Land 4 (USA, Europe).gba` was split at the spaces.
The runtime received a truncated ROM path, fell through to the picker, and hung
in the F1 dialog. Fixed by quoting each argument and passing one command-line
string; the runner also sets `-WorkingDirectory $Root` so `recomp_cache` stays
inside the project rather than writing into the shared parent directory.

## G2 — `generated/bios/codegen_tail_macros.h` is required but not generated

* Category: Game (build integration) · Status: **FIXED**
* Where: `reference/gbarecomp/CMakeLists.txt:400-433` force-includes
  `${GBARECOMP_GENERATED_BIOS_DIR}/codegen_tail_macros.h`.

The framework's hand-written header lives in
`src/runtime/generated_bios/codegen_tail_macros.h` and the in-tree build only
works because it is already there; an out-of-source project that generates BIOS
sources elsewhere fails with
`<command-line>: fatal error: .../generated/bios/codegen_tail_macros.h: No such file or directory`.
`tools/regeneration/regen.ps1` now copies it into `generated/bios/` after BIOS
generation (no framework edit).

## G3 — `SDL2.dll` was not staged next to the executable

* Category: Game (build integration) · Status: **FIXED**
* Where: `CMakeLists.txt`.

`_gba_sdl2_root` was computed only inside `if(NOT GBARECOMP_MINGW_PREFIX_UNIX)`,
so supplying that cache variable on the command line left it empty and the
POST_BUILD `SDL2.dll` copy never ran (the exe then exits `-1073741515` /
`STATUS_DLL_NOT_FOUND`). SDL2 root resolution is now hoisted above the `if`.

## G4 — 32 uncovered PCs kept coverage at NOT_STATIC

* Category: Game (config/discovery) · Status: **FIXED** (kept for the record)
* Where: `game.toml`; earlier proposal file `logs/routes/title-900-misses.toml.frag`.

Three classes were open after M3 (checkpoint 3 of the bring-up log). All three
are now resolved:

1. `0x03000C44` (arm) + `0x03004B28` (thumb) — cartridge code copied into IWRAM
   at boot. **Fixed** with two `[[code_copy]]` + `[[extra_func]]` pairs
   (`0x03000C44`←`0x080000FC`/0x800/arm, `0x03004B28`←`0x080010F4`/0x400/thumb),
   each proven byte-exact with matching boundaries by
   `tools/validation/verify_code_copy.py`. The first is the cartridge's own IRQ
   handler: the setup at ROM `0x080009E0`-`0x080009F4` loads
   `0x040000D4`/`0x080000FC`/`0x03000C44`/`0x80000400` into DMA3 and then stores
   `0x03000C44` into the user-IRQ pointer at `0x03007FFC`.
2. `0x03007D18`–`0x03007D90` — **reclassified**: not a BIOS copy and not a code
   copy at all, but dynamically generated code on the stack. See G5 and F6.
3. `0x08000BF6`, `0x08001498`, `0x080014B0` plus the 21-PC cluster
   `0x080015CC`–`0x08001686` — **Fixed** with
   `[[extra_func]] addr = 0x08000BE8 mode = "thumb"` (the missed `0x08000BF6` is
   an internal branch label 14 bytes into that function) and one
   `[[jump_table]]` at `0x0809540C` that expands to 36 seeds. Ordinary
   branch-walk discovery simply cannot see those entry points; see F5.

Measured effect (`title-900`): `distinct_misses` 32 → 7, `interpreted_insns`
8,123,102 → 507,428, run time ~6.7 s → 3.92 s.

## G5 — Remaining 7 misses are dynamic stack-executed code; 23 ROM PCs are only self-healed

* Category: Game (config/validation) · Status: **OPEN**
* Where: `game.toml`; `logs/routes/title-900-coverage.json`;
  `docs/VALIDATION.md` acceptance rule.

Two distinct populations remain after G4:

1. **7 dynamic PCs** — `0x03007D18`, `0x03007D1C`, `0x03007D30`, `0x03007D34`,
   `0x03007D70`, `0x03007D88`, `0x03007D90` (all thumb, all
   `jump_table_candidate`). These are code the cartridge generates on its stack
   and executes, so no static metadata can describe them; the interpreter is the
   correct and only execution path. Framework-side limitation: F6.
2. **23 healed ROM PCs** — the route reports `healed_native: 23` from
   `recomp_cache`. These are *cartridge ROM* PCs reached only indirectly at
   runtime, compiled by the self-heal backend, and now cached. Because
   `fully_static = g_misses.empty() && healed == 0`, coverage stays
   `NOT_STATIC` even though these are statically coverable. Next step: read the
   self-heal proposals for these PCs (miss fragment / `recomp_cache`) and declare
   them in `game.toml`, so that `healed_native` drops to 0 and the only remaining
   non-static population is the documented dynamic set.

Acceptance consequence: until F6 is addressed upstream, `GBARECOMP_STRICT_STATIC=1`
cannot pass for this game. `docs/VALIDATION.md` therefore states the honest gate:
run the route, require that no *new* miss class appears, and require that the
remaining miss set is exactly the documented dynamic set above.

---

## F7 — `TCP.md` documents execution-control commands that do not exist

`reference/gbarecomp/TCP.md:108-112` lists `pause`, `continue`, `step`,
`run_to_frame`, `run_to_pc`, `run_to_vblank`, `run_to_swi` under "Execution
control". A whole-checkout search (`.cpp/.h/.md/.py/.ps1/.c`) finds
`run_to_frame`/`run_to_pc`/`run_to_vblank`/`run_to_swi` **only** on those two
lines of `TCP.md` (the one other `run_to_pc` hit is an unrelated Python helper
name in `tools/oracle/nba_common.py:21`). The commands that do exist are
`continue`/`resume`, `pause` and `run_status`
(`src/debug/tcp_debug_server.cpp:765-780`, backed by `ctx.resume` at
`src/runtime/runtime.cpp:2552`).

This is a documentation/implementation drift, not a failure on its own, but it
changes how a TCP-driven route must be written, and it cost one 420 s run here:
the `--tcp` core **starts parked** (`src/runtime/runtime.cpp:2463`
`int ctl_state = RS_PAUSED;`, with the frame loop at `:2478-2497` stepping only in
`RS_RUNNING`/`RS_STEP`), so a client that attaches and only polls observes
`frame=0`, `samples_generated=0` and all-zero sound registers forever.

The working shape (used by `tools/validation/audio-probe.ps1`):

```text
attach -> {"cmd":"continue"} -> poll {"cmd":"run_status"} until the wanted
guest frame -> {"cmd":"pause"} -> observation commands
```

---

## G5 — RESOLVED 2026-09-30: the "23 healed ROM PCs" were already covered

Correction to the section above. Its second half (the ROM PCs reported through
`healed_native`) is closed, and the counter it was based on does not mean what it
looked like it meant:

* Every PC in `recomp_cache` is **already in `generated/cart/dispatch_table.cpp`**
  after the `[[jump_table]]`/`[[extra_func]]`/`[[code_copy]]` work — spot-checked
  `0x08000BF6` (line 1172), `0x08001498` (1886), `0x080014B0` (1897),
  `0x080015CC` (2031), `0x08001660` (2102), `0x03000C44` (12), `0x03004B28` (61).
* The runtime consults the static tables **before** the overlay tier
  (`src/armv4t/runtime_arm.cpp:872-889`: `if (entry) { entry->fn(); return; }` …
  "After the static tables miss, consult the runtime-healed native overlays"), so
  those cache entries are not shadowing static code.
* With the cache renamed away, the same route reports `warm_loaded=0
  healed_native=0 native_calls=0` and the **identical** `distinct_misses=7
  interpreted_insns=802940 failed=7`, with byte-identical rendered frames.

So `healed_native`/`native_calls` are *warm-cache* counters, not a coverage gap,
and they only make `fully_static` read false when a warmed cache is present.
Policy adopted: validation routes run with a cold cache (`recomp_cache`
renamed/removed), and a non-zero `healed_native` at a cold start is the signal
that a PC is genuinely uncovered. The runner now has the switch for it:
`tools/validation/run-route.ps1 -ColdCache` points `GBARECOMP_HEAL_CACHE`
(`reference/gbarecomp/src/runtime/overlay_loader.cpp:445`) at an empty
`logs/routes/cache-<tag>/` for that run. Measured: `cc-title-900` (cold) reports
`healed_native=0 native_calls=0 distinct_misses=7 interpreted_insns=802940` while
the warm run of the same route reports `healed_native=201` — same behaviour, and
only the cold counters describe coverage.

---

## G6 — RESOLVED 2026-09-30: gameplay-path cartridge-ROM coverage

Status: **RESOLVED** for the cartridge-ROM class. The 13 dynamic IWRAM PCs below
remain open and belong to F6, not here.

Resolution: the runtime's own proposal (`logs/routes/game-13500-misses.toml.frag`,
75 entries) was reviewed with a new tool, `tools/validation/classify_misses.py`,
against `generated/cart/dispatch_table.cpp`:

* **13 entries rejected** — every `0x03007Dxx` PC is the dynamic stack-stub family
  already explained above; the framework's own "JUMP-TABLE CANDIDATE" comment on
  that run is a false positive, and declaring those addresses is exactly what
  caused the `0xD00C2A00` wild jump.
* **62 entries merged** into `game.toml` as `[[extra_func]]` (mode `thumb`,
  address-only, no invented names), grouped in seven clusters with the review
  evidence in the comments: 7 of them are interior labels of already-generated
  functions (`0x0800FD20`, `0x0806F9D6`), the rest sit 0x1DA-0x526E bytes past the
  nearest dispatch entry, and `find_rom_table.py` showed no sized switch table to
  declare instead (cluster F's 64 candidate slots mostly store the same pointer
  `0x0802ACF8`; cluster B has only one PC present anywhere in the image).

Measured, same traces, same frames, before → after:

| route | frames | discovered functions | dispatch entries | distinct_misses | cart ROM | interpreted_insns | final frame |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ctrl-idle` | 13,500 | 11,915 → 14,280 | 105,910 → 124,384 | **59 → 13** | 46 → 0 | 4,780,390 → 1,318,122 | **byte-identical** (`6D764ABD…`) |
| `ctrl-right` | 13,500 | " | " | **60 → 13** | 47 → 0 | 6,326,817 → 1,318,122 | **byte-identical** (`6CBFD0C6…`) |
| `boot-120` | 120 | " | " | 0 | 0 | 0 | unchanged |
| `title-900` | 900 | " | " | 7 | 0 | 802,940 | unchanged |

The remaining 13 gameplay misses are exactly the documented dynamic set, so the
"no new miss class" gate applies to gameplay routes again. The two routes now
report the *same* `interpreted_insns` (1,318,122 ≈ 97.6 per frame) because the only
interpreted code left is that input-independent stack stub — previously the
interpreter was also carrying the undiscovered ROM code, which is why the two
routes' counts diverged.

<details><summary>Original report (kept for the record)</summary>

### Gameplay-path coverage: 62 cartridge-ROM PCs were still reached dynamically

Status was **OPEN** (recorded and classified, not yet fixed). First measured when
priority E was reached.

Entering a level exercises code that no boot/title route touches. Counters from
the coverage JSONs (`logs/routes/<tag>-coverage.json`):

| route | frames | distinct_misses | cart ROM | IWRAM | interpreted_insns | healed_native | native_calls | jt regions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `title-900` (cold) | 900 | 7 | 0 | 7 | 802,940 | 0 | 0 | 1 |
| `game-13500` | 13,500 | **75** | **62** | 13 | 7,693,738 | 108 | 115,447 | 12 |
| `ctrl-right` | 13,500 | 60 | 47 | 13 | 6,326,817 | 155 | 193,783 | 8 |
| `ctrl-idle` | 13,500 | 59 | 46 | 13 | 4,780,390 | 201 | 238,808 | 5 |

The 13 IWRAM PCs are the known dynamic stack-stub family (F6/G5), expanded:
`0x03007D0C 0x03007D18 0x03007D1C 0x03007D24 0x03007D2C 0x03007D30 0x03007D34
0x03007D3C 0x03007D4C 0x03007D70 0x03007D84 0x03007D88 0x03007D90`.

The cartridge-ROM PCs are a **new class** that static metadata can cover. Full
`game-13500` set (62, grouped by proximity):

```
0x0800FD90 0x0800FDA4 0x0800FE58 0x0800FE80
0x0801066C 0x0801067C 0x08010692 0x08010730 0x08010738 0x0801073C 0x0801078C
0x080109AE 0x080109BC 0x08010A08 0x08010A28 0x08010A2E 0x08010A30 0x08010A9C
0x08011886 0x080122D8 0x080125A4 0x08012BAC
0x08013894 0x080138C4 0x080138D0 0x08013A20 0x08013A98 0x08013ADE 0x08013B9E
0x08015490 0x08015642 0x08015796 0x08015800 0x080158BA 0x080158DA 0x08015946
0x08015ADC 0x08015B48 0x08015B98 0x08015BA0
0x0802AAB2 0x0802AC24 0x0802ACAC 0x0802ACF8 0x0802AD1E 0x0802ADAE 0x0802AEBC
0x0802AEE6 0x0802AEFC 0x0802AFAA 0x0802B0B8 0x0802B0E2 0x0802B1C0 0x0802B1EC
0x0802B218 0x0802BA2C 0x0802BA36 0x0802BA52 0x0802BA9C
0x0806FA1E 0x0806FA52 0x0806FAF0
```

`ctrl-right` and `ctrl-idle` (identical traces except one line) miss *different*
ROM PCs, so some entry points are reached only on some paths.

What the two biggest clusters look like, per `tools/validation/find_rom_table.py`:

* `0x0802ACAC…0x0802BA9C` — 64 candidate slots in ROM `0x0802AACC…`, most of them
  storing the **same** pointer `0x0802ACF8`: a per-instance record table whose
  behaviour pointers the speculative harvest does not treat as code pointers. Not
  one switch table, so a single `[[jump_table]]` cannot express it.
* `0x0801066C…0x08010A9C` — only ONE of the 14 PCs appears anywhere in the image as
  a 4-byte value (`0x08010A9C` at ROM `0x082DEDD0`, inside a stride-4 pointer table
  whose other entries are not missed), so this cluster cannot be found by scanning
  for its own addresses: it is PC-relative/computed dispatch, or interior labels of
  a mis-bounded function.

Consequences recorded:

* `docs/VALIDATION.md` §2 rule 1 ("no new miss class") is scoped to boot/title
  routes; gameplay routes must report their miss set instead of claiming it empty.
* `GBARECOMP_STRICT_STATIC=1` fails on a gameplay route immediately (on top of F6).
* The framework itself writes a reviewed-by-a-human proposal next to every run:
  `logs/routes/game-13500-misses.toml.frag` (467 lines). It flags the 13-PC IWRAM
  run as a "JUMP-TABLE CANDIDATE", which F6/G5 explain is a false positive —
  another instance of the F5-family detector limit.
* Runtime behaviour is unaffected: every miss is bridged through the interpreter.
  This is a performance and coverage gap, not a behavioural error.

Next: triage the clusters into `game.toml` (prefer one sized `[[jump_table]]` over
per-case `[[extra_func]]`), regenerate, re-run, and record the resulting set.
*(Done — the review chose per-address `[[extra_func]]` because no sized switch
exists for these clusters; see the resolution at the top of this entry.)*

</details>

## G7 — RESOLVED 2026-09-30: the attract/demo path's uncovered cartridge-ROM code

Status: **RESOLVED**. The 164 cartridge-ROM PCs are merged into `game.toml`; the 8
dynamic IWRAM PCs remain open under F6.

Resolution: the review step was made repeatable instead of hand-written — new tool
`tools/validation/merge_miss_fragment.py` reads a runtime fragment, keeps only the
addresses under a requested prefix (default `0x08`, i.e. cartridge ROM), rejects
everything else with a printed reason, and emits address-only `[[extra_func]]`
blocks with a review header. Applied to
`logs/routes/attract-demo-13500-misses.toml.frag`: **164 kept, 8 rejected** (all
`0x03007Dxx`, the dynamic stack-stub family). The 128 `jt-candidate` PCs were
merged per-address because the framework only flags those runs in comments — it
does not size the table, and a wrongly sized `[[jump_table]]` corrupts dispatch
silently.

Measured, same route and frame budget, before → after:

| | before | after |
| --- | --- | --- |
| `distinct_misses` | 172 (164 cart ROM + 8 IWRAM) | **8** (0 cart ROM) |
| `interpreted_insns` | 7,352,561 | **807,560** |
| `jump_table_candidate_regions` | 24 | **1** (the dynamic run) |
| discovered functions | 14,280 | 15,735 |
| final frame | `F03D2A16…` | **byte-identical** `F03D2A16…` |
| full smoke set | PASS | **PASS** (all five routes, frames unchanged) |

Original report (kept for the record):

Status was **OPEN** (recorded and classified, not yet triaged). Found 2026-09-30
while building `tools/validation/smoke.ps1`: a 13,500-frame run with **no host
input at all** leaves the title screen and plays the game's own attract demo, and
that path is far less covered than the scripted gameplay path.

Reproduce:

```powershell
tools/validation/run-route.ps1 -Tag attract-demo-13500 -Frames 13500 -DumpLastFrame
python tools/validation/classify_misses.py --coverage logs/routes/attract-demo-13500-coverage.json
```

Measured: `distinct_misses=172` = **164 cartridge ROM + 8 IWRAM**,
`interpreted_insns=7,352,561`, `jump_table_candidate_regions=24`, 61.4 s. The 8
IWRAM PCs are the usual dynamic stack-stub family (`0x03007D18 0x03007D1C
0x03007D2C 0x03007D30 0x03007D4C 0x03007D70 0x03007D88 0x03007D90`) and must NOT
be declared.

Cartridge-ROM misses by page: `0x08023xxx` 11, `0x08024xxx` 23, `0x08025xxx` 2,
`0x08026xxx` 3, `0x08027xxx` 1, `0x08029xxx` 12, `0x0802Axxx` 8, `0x0802Bxxx` 10,
`0x0802Cxxx` 28, `0x08039xxx` 2, `0x0803Axxx` **31**, `0x0803Exxx` 1,
`0x0806Fxxx` 4, `0x08076xxx` 12, `0x08077xxx` 9, `0x08078xxx` 6, `0x08079xxx` 1.
`classify_misses.py` kinds: 128 `jt-candidate`, 28 `new-region`, 16
`interior-label`.

Why it matters: this is the only route where the host supplies no input at all,
so the brief (§8) prefers it as the deterministic acceptance route — and it is
currently the least covered path in the game. Note the coverage grows as the
self-heal cache warms (the same no-input route reported 150 misses before the
cache held more overlays), so triage must be done against a cold cache.

Next: triage exactly as G6 was done — review
`logs/routes/attract-demo-13500-misses.toml.frag` (172 `[[extra_func]]`
proposals, one false-positive jump-table comment on the dynamic IWRAM run), cover
the real regions, and never declare the 8 dynamic PCs.

---

## F8 — `--tcp` bypasses input replay and the frame bound, and is silent

`--tcp` is not "the normal run plus a debug server": it takes a completely
separate path. Three consequences, all measured here:

1. **The TCP branch returns before the per-frame runner.**
   `src/runtime/runtime.cpp:2445` opens `if (args.tcp_port > 0) { … }`, starts a
   dedicated game thread (`:2468`), runs the server (`:2595`) and **returns at
   `:2611`**. Everything after that point belongs to the normal path — including
   the `GBARECOMP_INPUT_REPLAY` loader at `:3234` and the `--frames`/`--steps`
   bound. So a `--tcp` session ignores input replay entirely.
   *Evidence*: with `GBARECOMP_INPUT_REPLAY` set, a plain run prints
   `input_replay=ENABLED path="…\tests\input\start-press.keyinput.txt" events=2`,
   while the same command plus `--tcp 19971` logs only `save_config`,
   `self_heal_recompile` and `native: tcp_debug_server listening …`
   (`logs/routes/tcpenv.log`). A filmstrip of the recorded input route captured
   the **no-input** frames: `distinct_misses=7 interpreted_insns=802940`
   (the no-input numbers) instead of `title-input-6000`'s
   `10 / 1,012,470`, and the capture differs from the recorded route frame in
   **38,309 / 38,400 pixels**.
2. **`--frames` does not bound a `--tcp` run.** `--frames 400 --tcp 19941` with no
   client attached was still running after 20 s (the core stays parked at frame 0,
   so the bound is never reached); a session started with `--frames 6200` and
   driven `continue → pause → continue` passed **81,000** frames without exiting.
   A client must therefore kill its child (or send `quit`).
3. **`--tcp` also sets `args.quiet = true`** (`:938-945`), which suppresses every
   `if (!args.quiet)` line — `bios_loaded`, `rom_loaded`, `input_replay=…`. A
   `--tcp` log starting at `save_config` is normal, not a failure.

Working command set (verified, all answered in ≤ 5 ms):
`run_status` (answers while running: `frame` 272 at +500 ms, 1333 at +2000 ms),
`continue`/`resume`, `pause`, `screenshot` (`{ok,w,h,data:<hex RGB>}`,
240×160×3 → a 230,437-character line), `quit` (`{"ok":true,"bye":true}`,
`src/debug/tcp_debug_server.cpp:1172`).

Consequence for this repo: a TCP-driven session can only film **no-input** routes
(`tools/validation/tcp-filmstrip.ps1`). Input routes are filmed with the
runtime's own framedump instead — see G8.

---

## G8 — mid-run capture needs `-Window` and present-in-place OFF

The runtime can dump consecutive mid-run frames (`GBARECOMP_FRAMEDUMP_DIR`,
`GBARECOMP_FRAMEDUMP_START`, `GBARECOMP_FRAMEDUMP_COUNT` → `<dir>/f_%06llu.png`,
`src/runtime/runtime.cpp:4092-4114`, quitting by itself once COUNT frames are
written). Getting it to fire took three corrections:

* the dump is inside `if (args.window)` (`:4060-4092`), and a frame-bounded run
  defaults to headless — `:1429` only picks a window when no `--frames`/`--steps`/
  `--tcp` was given. `tools/validation/run-route.ps1 -Window` used to merely omit
  `--no-window`, which stayed headless; it now passes `--window` explicitly.
* present-in-place (the windowed default, `:3655-3666`) presents from a frame hook
  and never enters the per-frame loop that contains the dump, so a capture run
  sets `GBARECOMP_PRESENT_IN_PLACE=0` (the framework's own documented escape
  hatch).
* `GBARECOMP_INPUT_REPLAY` is irrelevant to this (it only matters for the *route*,
  not the dump) but is what makes it useful — the dump is the only way to film an
  input route, because of F8.

Verified: `run-route.ps1 -Tag wdump2 -Frames 240 -Window -FrameDumpStart 100
-FrameDumpCount 6` → `f_000100.png … f_000105.png` (115,433 B each) plus one
stderr line per frame (`framedump f=100 DISPCNT=1002 BG2CNT=0000 BLDCNT=3F5F …`).

---

## G9 — RESOLVED 2026-09-30: the attract demo's deep run uncovers four more cartridge PCs

**Report.** `tools/validation/tcp-filmstrip.ps1 -Tag attract-strip -Frames 20000
-Marks '3000,…,19000' -Port 19961` — a single no-input run of the game's own
attract demo, filmed by TCP screenshots — ended with **15 dispatch misses**
(`logs/routes/attract-strip-coverage.json`): the 11 IWRAM dynamic PCs plus

```text
0x0802A258  0x0802A26E  0x0802A656  0x0802A680   (all mode = thumb)
```

The 13,500-frame attract route had been clean since G7 (8 misses), so this is new
coverage, not a regression: the demo simply had not reached that code yet
(`docs/VALIDATION.md` rule 14).

**Review.** `tools/validation/classify_misses.py --coverage
logs/routes/attract-strip-coverage.json --dispatch generated/cart/dispatch_table.cpp
--config game.toml --detail` reported 133,775 dispatch entries, 2 code copies, 0
data ranges, and for the four PCs:

| pc | mode | bridged | previous dispatch entry | gap | kind |
| --- | --- | --- | --- | --- | --- |
| `0x0802A258` | thumb | 1 | `0x0802A1AE` | `0xAA` | `interior-label` |
| `0x0802A26E` | thumb | 1 | `0x0802A1AE` | `0xC0` | `interior-label` |
| `0x0802A656` | thumb | 20 | `0x0802A5DC` | `0x7A` | `interior-label` |
| `0x0802A680` | thumb | 11 | `0x0802A5DC` | `0xA4` | `interior-label` |

All four are mid-function entry points of functions that are *already* dispatched
— reached by a computed transfer, the same shape as the cluster-A/G labels merged
at G6. None is in the IWRAM stack-stub family (F6), so none is rejected.

**Fix.** Four address-only `[[extra_func]]` blocks appended to `game.toml` with a
review header recording the source route, the classifier output and the
verification rule. No names invented, no framework change.

**Verification.**

| check | before | after |
| --- | --- | --- |
| `extra_func` entries | 229 | **233** |
| discovered functions | 15,735 | **15,740** (arm 49 / thumb 15,691) |
| dispatch entries | — | 124,384 → (regenerated) |
| `attract-deep-19000` misses | 15 (11 + 4 cart) | **11, all dynamic** |
| `left-12139` replay frame | `66787E63…` | `66787E63…` (byte-identical) |
| `smoke.ps1` | PASS | PASS, every recorded frame/counter unchanged |

The rebuilt host is `build/host/WarioLand4Recomp.exe` 25,417,112 B
(`a25fde6b…`). The lesson is the one already written down as rule 14: a route's
frame budget is part of its coverage claim, and the game's own demo is the deepest
witness available.

---

## G10 — a windowed run's live input path can silently change the game state

**Status: OPEN (worked around).** Recorded 2026-09-30.

**Report.** A windowed framedump of the no-input attract demo —
`run-route.ps1 -Tag damage-dump -Frames 19400 -Window -FrameDumpStart 18500
-FrameDumpCount 800` — put the guest in a completely different place than every
other run of the same route at the same guest frame:

```text
damage-dump-frames/f_019000.png   level-1 "B" hall, coin counter 001230   sha256 17EA7DE1…
det-noinput-a-last.png (headless) level-2 beach,    coin counter 000660   sha256 BA51E420…
37,376 of 38,400 pixels differ
```

The two runs also disagree on their own coverage counters —
`interpreted_insns=1,312,902 native_calls=51,582 (11 misses)` versus
`1,317,222 / 135,985 (11 misses)` — so the divergence is visible in the log, but
only if a baseline is being compared.

**Investigation.** Everything else agrees, so the outlier is this one run:

| run | mode | replay | frame 19,000 frame |
| --- | --- | --- | --- |
| `det-noinput-a` / `-b` | headless | none | `BA51E420…` (identical to each other) |
| `attract-deep-19000` | headless | none | `BA51E420…` |
| `win-19000` | windowed framedump | none | `BA51E420…` |
| `win-9000` | windowed framedump | none | equals headless `refdemo-9000` at frame 9,000 |
| `noinput-win-19000` | windowed framedump | `noinput.keyinput.txt` | `BA51E420…` |
| `damage-dump` | windowed framedump | none | `17EA7DE1…` — **the outlier** |

**Cause.** `-Window` opens the runtime's live host-input path (SDL polls the real
keyboard), and this game's attract demo aborts the instant any button is held —
`third_party/lilDavid-warioland4/src/demo_input.c`, `DemoInputPlayback()`:

```c
if (gDemoSequenceIndex >= DEMO_INPUT_SIZE - 2 || gDemoButtonPressTimer == U16_MAX || gButtonsHeld != 0) {
    gButtonsPressed = START_BUTTON;
}
```

so a held key returns the game to the title and re-phases the whole demo (the
outlier sat ~7,600 frames behind). Nothing is logged when this happens: the run
exits 0, `unmapped=0 io_unhandled=0`, and the coverage contract is satisfied. Two
of the three windowed no-replay runs were unaffected, which is exactly what makes
it dangerous — it is not reproducible on demand.

**Workaround (in this repo).** Drive every windowed, supposedly-input-free route
with an explicit replay so the host keyboard is not the input source:

```powershell
tools/validation/run-route.ps1 -Tag noinput-win-19000 -Frames 19100 -Window `
    -InputReplay tests\input\noinput.keyinput.txt `
    -FrameDumpStart 19000 -FrameDumpCount 1     # byte-identical to the headless frame
```

and keep a recorded baseline of `interpreted_insns` / `native_calls` per route
(`tools/validation/smoke.ps1` does this) so a re-phased run is caught.

**Framework suggestion.** Either a `--no-host-input` switch, or one log line when
the window input path is live ("host input: window keyboard active") and one when
a non-idle keyinput value first reaches the guest. The game side cannot detect
this on its own: the demo's abort is indistinguishable from the demo ending.

## F9 — `generated/cart/dispatch_table.cpp` looks like a function list but is a per-instruction resume map

**Status: OPEN (documentation clarity).** Recorded 2026-09-30.

**Report.** The table is the obvious artifact to check a symbol harvest against,
and its header comment invites exactly that: *"Dispatch table: maps recompiled
function addresses to the corresponding generated C function pointer."* It is not
a function list. Measured on the current build:

```text
rows                     133,792        span 0x03000C44 .. 0x08720A4E
struct                   { uint32_t addr; uint8_t thumb; uint8_t resume; void (*fn)(void); }
sample rows              {0x08000A80u, 1u, 1u, gf_tfunc_08000A7C}
                         {0x08000A82u, 1u, 1u, gf_tfunc_08000A7C}   <- one per instruction
first instruction is a Thumb `push` in 2 of 300 sampled rows
```

Every recompiled function occupies a *run* of consecutive rows (one per resume
point) and 15,740 discovered functions share those 133,792 rows. Comparing the
harvest's 3,327 decomp function starts against it gives 970 hits (29.2 %), which
says nothing about correctness: 71 % of the decomp's starts are simply not
individually addressable rows, because the *function start* is encoded by the
first row of the run (`resume=0`), not by an address match.

**Consequence here.** A first version of `tools/validation/parse_decomp_symbols.py`
used the overlap as its correctness gate and would have failed a correct harvest.
It now validates against the ROM instead (`--verify-rom`: every address in range
and 2-byte aligned, ≥ 50 % of Thumb starts opening with `push {…}`/`bx lr`) and
treats the dispatch overlap as informational.

**Framework suggestion.** One line in the generated header ("one row per resume
point; a function start is the first row with `resume=0`") would prevent the
inference. Emitting an explicit `[[function start]]` summary — or having
`gba_recompile` write a `function_list.txt` alongside — would make the obvious
check the correct one.

## G11 — 262 named decomp functions cannot be placed without a build

**Status: OPEN (documented gap, worked around by omission).** Recorded 2026-09-30.

**Report.** The harvest places functions whose *names encode their address*
(`func_XXXXXXXX`). 3,327 of 3,589 named functions do; **262 do not** and are
skipped rather than guessed, because guessing an address would mislabel code:

```text
asm/crt0.s:4                    _start, irq_handler          (arm)
asm/rom_header.s:3              entry_point                  (arm)
asm/m4a_asm.s                   the whole sound driver: SoundMain, SoundMainRAM,
                                m4aSoundVSync, MPlayMain, ply_note, ply_fine, … (63)
asm/sprite_ai/*.s               ~190 Sprite* routines (SpriteAerodent, SpritePencil,
                                SpriteGoldenDiva, SpriteUnknownXX, …)
asm/disasm_wario.s              WarioProcessControls, WarioProcessCollision
asm/disasm_score.s              SpriteSpawnSecondary, ScoreGivePoints, ScoreGiveOrDropCoins
asm/disasm_*.s                  GameScreenDraw, FileSelectSubroutine, PauseScreenSubroutine,
                                StageSelectSubroutine, ItemShopSubroutine, CreditsSubroutine,
                                MinigameSubroutine, BossPause, BackgroundProcessMain, …
```

The decomp's own naming is also WIP: `import_decomp_symbols.py` reports
`names: 0 meaningful, 3327 address-derived placeholders` — i.e. most of what *is*
placed is still `func_XXXXXXXX`, so the overlay's measurable gain this round is
the data side (552 named IWRAM globals, 3,013 named ROM data extents), which is
what the damage work needed.

**Why it is not fixed here.** Placing these names needs the decomp's symbol table,
i.e. a build: the machine has no WSL and the user's instruction (m02667) is not to
install one. `readelf`-style tooling is unavailable for an ARM ELF and the
decomp's own `make` requires `binutils-arm-none-eabi`, agbcc and WSL.

**Options recorded for later.** (a) a constrained identification pass: for each of
the 262 names, search the recompiler's 15,740 discovered functions for a unique
candidate (the decomp file/line order plus the `baserom_blob` neighbours already
give strong ordering constraints); (b) accept the gap and keep the overlay opt-in,
which is what the repo does now (`regen.ps1 -SymbolOverlay`). Option (a) needs its
own validation rule before it can be trusted, because it *is* a guess.

**The inverse gap also exists: an address inside a disassembled region can still
have no function name.** The water reaction is set at ROM `0x08013D10`, which sits
between the labels `.L_13cf0` and `.L_13d20` in
`third_party/lilDavid-warioland4/asm/wario/disasm_normal.s` — the file covers the
address, and the *instruction* is annotated (`:7726 strb r1, [r5, #0]`, pool entry
`:7735 .L_13d24 = gWarioData`), but the enclosing routine is an unnamed block, so
the runtime's own name for it is still the address-derived
`gf_tfunc_08013D06` and the decomp cannot supply a semantic one. Symbol coverage is
therefore partial in both directions, and both are recorded rather than papered
over with an invented name.

## G12 — RESOLVED 2026-09-30: a plain regeneration did not produce a plain build

**Report.** After the Checkpoint-15 overlay A/B, restoring the documented default
build (`regen.ps1 -CartOnly`, then `build-host.ps1`) produced a
**25,529,220**-byte executable — the same size as the overlay build and 145,324
bytes larger than Checkpoint 14's plain build (25,417,112). The generator was not
at fault: `generated/cart` was never cleared, and the host build globs that
directory:

```text
CMakeLists.txt:47  file(GLOB CART_SOURCES CONFIGURE_DEPENDS
                        "${CMAKE_CURRENT_SOURCE_DIR}/generated/cart/*.cpp")
```

so `generated/cart/data_symbol_map.cpp` (151,398 B), produced only when
`-SymbolOverlay` is passed, was still present after a plain regeneration and was
compiled into the "baseline" executable.

**Evidence that only that one file was stale.** All eleven files the baseline
inputs *do* produce were byte-identical to the pre-overlay fingerprints in
`logs/overlay-ab/baseline-files.txt`; only the extra file remained. (The generator
compares content and preserves mtimes when bytes match, so the mixed 21:06/22:28
timestamps in that directory were a red herring.) The overlay's function-name
export is a no-op on code: `imported_symbols.tsv` holds 3,327 *address-derived*
names identical to the recompiler's own placeholders, which is why
`dispatch_table.cpp` and all eight shards are byte-identical with and without the
overlay — the entire delta is the data-name table.

**Fix.** `tools/regeneration/regen.ps1` clears `generated/cart` before cartridge
generation and `generated/bios` before BIOS generation. Both directories are fully
regenerated, and the BIOS step re-copies the hand-written `codegen_tail_macros.h`,
so nothing in them is an input. Verified after the fix: `generated/cart` holds
exactly the eleven baseline files, all identical to the recorded hashes; the
rebuilt executable is 25,417,112 B sha256
`7718edbb688f2a46ded6e0c81d241d3dc80206824be57f57c5b44737c9876662` (the
Checkpoint-14 size again); `smoke.ps1` PASS with boot-120 `f1dd2fdacf2e4263`,
attract-3600 `38be8fce4a34f13e`, title-input-6000 `697534774d47c51f`,
ctrl-idle-13500 `6d764abd8b801016`, save pair `11eb324834a221af`.

**Sharp edge found while fixing it.** `Remove-Item -LiteralPath <dir>\*` does *not*
expand the wildcard (`-LiteralPath` means literal); it silently deletes nothing, so
the first version of this fix looked correct and cleaned nothing. The working form
is to enumerate first:
`Get-ChildItem -LiteralPath $dir -Force | Remove-Item -Recurse -Force`.

**Generalised.** Same failure family as G5 (a warmed heal cache read as coverage)
and G10 (a live input path read as "no input"): *the inputs of a build must be
explicit, and a directory another tool globs is one of those inputs.* Recorded as
`docs/VALIDATION.md` §5 rule 21.





## G13 — a player-driven (input-replay) route has no guest-memory read path (superseded by observer mode, see G13b)

**Symptom.** Every question that needs a *value* from the guest during a route that
takes host input hits the same wall: `--tcp` is the only read channel the runtime
exposes (`read_iwram`/`read_ewram`/`read_vram`), and `--tcp` bypasses
`GBARECOMP_INPUT_REPLAY` entirely (F8), while a frame-bounded non-TCP run is
headless and write-only. So `read_iwram` is unavailable exactly where the
interesting routes are.

**Workaround (in use since Checkpoint 17).** A write watchpoint turns the abort
message into a datum: the runtime aborts on the first write to an address at or
after `GBARECOMP_ABORT_ON_MEM_WRITE_ADDR`/`_MIN_FRAME` and prints the value it
wrote. With the decomp struct offsets (`include/wario.h:254-288`, `struct WarioData`
at `0x03001898`) this reads `gWarioData.xPosition` (`+0x12` = `0x030018AA`),
`yPosition` (`+0x14` = `0x030018AC`), `pose` (`+0x01`), `damageTimer` (`+0x04`), the
hitbox extents (`+0x32..+0x38`), `gHeartMeter.current` (`0x03001910`) and
`gCurrentRoom` (`0x03000024`). Measured example:
`pc=0x08013A8E <gf_tfunc_08013A8A+0x4> addr=0x030018AA value=0x000006DE width=2
(vblanks=19000)`.

**Limits.** One address per run; a value that is not written while the object is
idle produces no abort at all; the datum is the first write at or after
`min_frame`, so a trajectory costs one run per sample. Documented as
`docs/VALIDATION.md` §5 rules 23/24 and §3 item 4n.

**Framework fix that would close this.** Let `--tcp` keep the input-replay path (or
expose the replay file through the debug server, e.g. `{"cmd":"replay","path":...}`)
so a driven route can also be read. Recorded as F8; not attempted, because the
framework checkout is read-only (`AGENT_PROMPT.md` §4).

## G13b — RESOLVED 2026-09-30: observer mode reads an input route without any framework change

**What was found.** The runtime already ships the missing half: `--tcp-observe PORT`
(env `GBARECOMP_TCP_OBSERVE`, `gbarecomp-main/src/runtime/runtime.cpp:987-992`)
attaches a *read-only* `debug::TcpDebugServer` to a **windowed** run
(`runtime.cpp:2892-2927`) instead of replacing the run the way `--tcp` does. stderr
proves it:

```text
[gbarecomp:runtime] windowed observe TCP on 127.0.0.1:20011 (reads, touch_*,
  game commands, queued savestates; no step)
```

Because the normal game loop is still running, `GBARECOMP_INPUT_REPLAY` applies, so
`read_iwram`/`read_ewram`/`read_vram`/`read_pal`/`read_oam` are available on a
player-driven route. Queued savestates are serviced at present boundaries
(`pump_host_input()`, `runtime.cpp:3375-3399`).

**Tools.** `tools/validation/observe_read.py` (snapshot frames to
`<outdir>/<tag>-<space>-f<frame>.bin` + an index JSON) and
`tools/validation/observe_trace.py` (one line per sample: frame, room, Wario
x/y/pose/reaction/damage, hearts, optional live sprite slots) — plus
`tools/validation/iwram_fields.py` to name fields in a snapshot through
`symbols/iwram_map.tsv`.

**Verification.** The observer run replays the same route the headless watchpoints
measured: `xPosition` 2016 / 2016 / 1758 / 1758 at frames 11,601 / 12,002 / 13,001 /
14,002 versus the watchpoint samples 1923 @ 12020, 1757 @ 13400, 2337 @ 15000,
1758 @ 19000. Two hard requirements: the run must be **windowed** (headless
`pump_host_input()` returns immediately, so the port accepts a connection and never
answers) and `--frames` still bounds it. Samples below ~frame 2000 are boot garbage
(frame 2 read back `wario_x=3957 wario_y=60074 hearts=165`).

**Remaining limit.** The observer cannot inject input or step, so a route still has
to be designed up front; only the *reading* became cheap. Documented as
`docs/VALIDATION.md` §5 rule 25 and §3 item 4o.

## G14 — the new-game route is confined to room 0, whose exit switch cannot be pressed (open)

**Symptom.** Priorities F (变身) and G (input-driven room/level transition) both need
Wario somewhere other than the room a new game starts in. Measured, not suspected:

* The new-game route (`explore-1`, `door-1`, `pound-1`, `switch-hunt`, `switch-hunt2`)
  plays **room 0** the whole time (`gCurrentRoom` written `0` at vblank 11,454 by
  `pc=0x0806B92C <gf_tfunc_0806B90C+0x20>`; no later write), while the attract demo
  enters **room 2** through the same loader PC at vblank 8,852.
* Wario's walkable range in that room is ~580 raw units (~75 px): LEFT stops at
  `x=1758`, RIGHT at `x=2337` (rule 24).
* Room 0's whole live sprite set is `PSPRITE_SWITCH` (id 7, class 0x30) at
  (1696,1024) and `PSPRITE_VORTEX` (id 0x29, class 6) at (2016,1024) plus two vortex
  parts — **no transformation class at all** (classes 0x0E…0x15/0x1F/0x27), so F
  变身 cannot be shown here.
* The only exit mechanism is switch → `gSwitchPressed` → grown vortex →
  `gSubGameMode = 6` → `func_80720E8()` (level exit). `gSwitchPressed` (`0x03000C0D`,
  address confirmed against the ROM literal pool at VRom `0x0802B724`) is written by
  exactly one routine: the switch sprite's pose-17 handler `func_802B694`
  (`asm/sprite_ai/disasm_switch.s:210-239`). In this room the switch runs pose
  111 → 113 → 16 (`func_802B5E4` → `func_802B62C` → `func_802B668`) and **no code
  stores pose 17 into it**, while two 20,000-frame hammer routes (A, held-A, DOWN,
  UP, B, jump-slam at both ends of the band) never write the flag.

**Reading (Checkpoint 18).** Room 0 behaves like the level's *goal* room (exit switch +
exit vortex) rather than its entry corridor, and the switch that would open the vortex is
elsewhere in the level — which the route cannot reach.

### G14 update 2026-10-01 — the level data model is decoded; hypothesis (a) is closed

**The data model (decoded, with a self-checked tool).** `tools/validation/level_rooms.py`
reads the ROM only and prints the whole level structure. Its own correctness gate,
`--check-snapshot`, compares the guest's live `gCurrentRoomHeader` (IWRAM `0x03000074`)
against the ROM record and prints `OK … 44/44 bytes identical`, exit 0; the first run of
that gate found two real bugs in the tool, which is the reason it exists.

* `func_806B410` (`asm/disasm_0x06AF4C.s:563-628`) is the loader: a **two-level**
  indirection. `sUnk_878F280` (ROM `0x0878F280`) is a `u32[]` of level blocks indexed by
  `gUnk_3000023`; each block is a flat array of 0x2C-byte `struct RoomHeader` indexed by
  `gCurrentRoom`, and all 44 bytes are copied to IWRAM `0x03000074`.
* `struct RoomHeader` (`include/global_data.h:88-107`) is 0x2C bytes: `tileset u8`,
  `bg0..bg3Param u8`, `pBg0..pBg3Data u32`, `cameraControl u8`, `layer3Scrolling u8`,
  `bgPriorityAlpha u8`, `pHardSpriteData u32`, `pNormalSpriteData u32`, `pSHardSpriteData u32`,
  `raster u8`, `water u8`, `musicVolume u16`.
* **Sprite lists are 3-byte entries `[y, x, spawnId]`, terminated by `FF FF FF`**, with
  `x = xBlock*64 + 32` and `y = yBlock*64 + 64`. (Field order is `[y, x, spawnId]`, *not*
  `[spawn, y, x]` — the self-check caught that.) Both known spawns reproduce the live
  observer's x/y exactly.
* The room count is not stored: it is `(next level block address − this block address)/0x2C`.
  Level 0 = `0x083F4F38`, next block `0x083F5174` ⇒ **13 rooms (0…12)**. Pointer-alignment
  scans are unsound here: halfword-aligned pointers are normal (room 1's `pBg1Data` is
  `0x085994CB`), and a strict word-alignment scan invents only one room.
* **Room 0's whole hard+normal sprite list (0x085991D0) is three entries plus a terminator:**
  `0x08` `PSPRITE_SWITCH` y=15 x=26, `0x11` `PSPRITE_VORTEX` y=15 x=31, `0x14` unknown
  y=19 x=7 (not among the live sprites). In pixels the switch is at x=106 and the vortex at
  x=126, while Wario's measured walkable band is x=110…146 — **the escape switch sits 4 px
  west of the wall the route can reach, which is why the route has never touched it.**
  There is no second vortex and no door sprite in this room.

**The switch is the level's escape switch, and the level exit is switch-gated.**
`func_802B694` (pose 17) sets `gSwitchStates[4] = 2` and `gSwitchPressed = 1`. With
`include/global_data.h:51-65`, `gSwitchStates` is 5 bytes
`{UNUSED, RED, PURPLE, GREEN, ESCAPE} × {OFF, ON, SWITCHING_ON, SWITCHING_OFF}` at
`0x0300002E`, so index 4 is `SWITCH_ESCAPE` and value 2 is `SWITCH_STATE_SWITCHING_ON`.
`third_party/lilDavid-warioland4/src/sprite_ai/vortex.c` gates the vortex on that flag at
four independent places (`vortex.c:202-228`, `:270`, `:301`, `:337`, `:368`), and
`SpriteWarioEnteringVortex` (`vortex.c:437-481`) sets `gSubGameMode = 6` +
`gStageExitType = 2` in the same gate. So room 0 is the **goal** room, and a
room-to-room traversal is a *different* mechanism that no route has reached and whose code
is not yet located.

**Hypothesis (a) — the recorded demo input stream — is CLOSED, with two negatives.**

1. `GBARECOMP_INPUT_RECORD` cannot capture it. The recorder writes
   `bus.io().composed_keyinput()` (`reference/gbarecomp/src/runtime/runtime.cpp:3444-3454`),
   the KEYINPUT register, but `src/demo_input.c` computes buttons into the game's own key
   variables and never writes KEYINPUT — a no-input record is a single `0x03FF` line.
   `tools/validation/demo_input_dump.py` (reads `gDemoInputs` at `0x03002CC8` out of IWRAM)
   is the only way to get the stream.
2. The stream contains no room-0 traversal. `logs/routes/demo-input-stream.csv` reproduces
   exactly from `snap-demo-iwram-f009503.bin`, and that snapshot has `gCurrentRoom = 3`,
   `gCurrentStageID = 0`, `gCurrentRoomHeader[0] = 0x085999F4` = **room 3** of level 0. Our
   player route's snapshots have `gCurrentRoom = 0` and `gCurrentRoomHeader[0] = 0x08598EEC`
   = **room 0** of the *same* stage. The demo therefore never plays the room-0 → room-1
   traversal, so replaying its inputs from our entry frame cannot demonstrate the
   transition. (`snap-demo-iwram-f019007.bin` holds a *different* `gDemoInputs` table —
   demo level 2's — which is why the CSV must be dumped from a snapshot inside demo
   level 1, not near the end of a long run.)

### G14 update 2026-10-01 (b) — the spawn-id table is decoded, and the level turns out to be 13 vortex-linked rooms

**The spawn-id → sprite-type translation is now read, so every sprite in the level has a
name.** `func_801E0EC` (`asm/disasm_sprite.s:1407-1519`) is not a flat table:

```asm
r0 = spawnId                                @ gUnk_3000964 + 2, stride 3
cmp r0, #16 ; bls .L_1e178
sub r0, #1                                 @ small ids: globalID = spawnId - 1
strb r0, [sprite, #0x17]                   @ gSpriteData[].globalID
b   .L_1e1b0
; the >= 17 arm instead:
r1 = spawnId - 17
sprite[0x19] = gUnk_3000544[r1]             @ IWRAM 0x03000544
globalID     = gUnk_3000524[r1]             @ IWRAM 0x03000544 - 0x20
```

Both tables are 32 bytes of IWRAM **rewritten per level** (`asm/disasm_sprite.s:1238`,
`asm/sprite_ai/disasm_bowler.s:685`) and stored in the save file
(`asm/disasm_save_file.s:976/978/1599/1601`), so ids above 16 can only be named from a
guest snapshot of that level. `level_rooms.py --iwram` reads them out of a snapshot and
`--sprite-header` parses `enum PrimarySpriteID` from the decompilation, so no name is
typed into a tool. Cross-checked against two independent live sprites: spawn `0x08` → id
7 = `PSPRITE_SWITCH`, and spawn `0x11` → `gUnk_3000524[0]`, read from
`logs/routes/obs-explore/obs-explore-iwram-f011601.bin` at IWRAM offset 0x524, is `0x29`
= 41 = `PSPRITE_VORTEX`.
> **Correction (same day).** The prose first written for this table named the two
> room-0 sprites from a hand-count of `enum PrimarySpriteID`, and the hand-count was wrong
> by one: the enum has **253 entries (0…252)**, so 20 is `PSPRITE_ROTATING_PLATFORM` and
> 21 is `PSPRITE_ROCK`; 19 is `PSPRITE_SPEAR_MASK_RED`, not the pot sprite. The tool
> parses the enum instead of carrying a name list, so it was right and this text was
> wrong — which is the whole argument for `level_rooms.py --sprite-header`. Spawn `0x14`
> → id 20 = **`PSPRITE_ROTATING_PLATFORM`**, spawn `0x13` → id 19 = **`PSPRITE_SPEAR_MASK_RED`**.

**What the level actually is.** Every one of the 13 rooms is now decoded with names. The
structure is a chain of rooms joined by `PSPRITE_VORTEX` pairs at the seams:

| room | tileset | camera | what is in it |
| --- | --- | --- | --- |
| 0 | 0x50 | 1 | `PSPRITE_SWITCH` x=1696, `PSPRITE_VORTEX` x=2016, `PSPRITE_ROTATING_PLATFORM` x=480 |
| 1 | 0x11 | 1 | vortices x=672 / 1248 / 1760, `PSPRITE_SWITCH` x=224, 3 platforms, 4 `PSPRITE_SPEAR_MASK_RED`, jewel box |
| 2 | 0x11 | 3 | **no sprites at all** |
| 3 | 0x11 | 1 | vortices x=672 / 1248 / 1632, rocks, jewel box |
| 4…10 | 0x11 / 0x47 | 1 or 3 | the same left/right vortex pair, rocks, pots |
| 11 | 0x11 | 1 | no sprites; `pBg0Data` is the sentinel `0x083F2263` |
| 12 | 0x47 | 1 | vortex x=736, 2 platforms, 3 spear masks |

### G14 update 2026-10-01 (c) — three watchpoints: the vortex is the level EXIT, and the demo proves the traversal is a different mechanism

This is the round that turned "we cannot find the input" into "the mechanism we were
looking at is not the one the game uses". All three runs are
`run-route.ps1` guest-memory watchpoints on a 12,000-frame attract-demo run, and the
instrument is **validated on a case known to be positive first** (`docs/VALIDATION.md`
rule 28):

| watch | `-AbortMemAddr` | `-AbortMemValue` | result |
| --- | --- | --- | --- |
| **control** | `0x03000024` `gCurrentRoom` | 3 | **FIRES** — `runtime_trace: mem-write-addr abort pc=0x0806B92C <gf_tfunc_0806B90C+0x20> addr=0x03000024 value=0x00000003 width=1 (vblanks=9205)` |
| room 1 | `0x03000024` | 1 | **never written** (also with no min-frame gate), `exit=0` |
| the switch flag | `0x03000C0D` `gSwitchPressed` | 1 | **never written**, `exit=0` |

**What the control buys.** The positive control fires at exactly the PC already known to
write the room number, so the two `exit=0` runs are real negatives and not a broken
watchpoint.

**The demo's own room timeline** (37 IWRAM snapshots, `logs/routes/snap-demo-iwram/`,
`gCurrentRoom` and `gWarioData` read out of each):

```text
f001036 … f008505   room 0   wario_x=0  wario_y=0  no live sprites   <- stage not loaded yet
f009010             room 2   wario_x=1054                     <-- enters at room 2
f009503  f010012  f010507  f011010  f012505  f013004  f013500  f014005
             rooms  3        4        5        6        7        8        9        10
f014513 … f018009   room 0   wario_x=800                        <- stage end / results
f018500             room 2                                      <- demo loops
```

**Reading — and this is the finding.** The demo crosses **eight** room boundaries
(2→3→…→10) and **`gSwitchPressed` is never set once in 12,000 frames.** Since that flag is
the gate on *every* vortex in the game, the demo's traversal cannot have used a vortex.
So:

* the **switch → `gSwitchPressed` → grown vortex → `gSubGameMode = 6` → `func_80720E8()`**
  chain is the level **exit**, and room 0's switch-plus-vortex pair is the level's goal
  furniture, exactly as it looked;
* **room-to-room traversal is a second, different mechanism** that no route has triggered
  and that is not in the decompilation text;
* the demo **never enters room 1** (nor room 0 after load), so its input stream still
  cannot demonstrate the transition our route is missing — now as a *watchpoint* fact
  rather than an inference from two samples. Hypothesis (a) stays closed, on better
  evidence.

**One live patch, found by the gate.** `level_rooms.py --check-snapshot` on the demo's
f009503 snapshot is a **42/44** match against ROM level-0 room 3, and the two differing
bytes are `pHardSpriteData` (+0x1C): the guest holds `0x0301 9B1C` (**IWRAM**) where the ROM
holds `0x0899 A08`. Everything else — tileset, all four BG pointers, camera, music —
matches, which is independent confirmation that the demo really is in level 0. So the
demo redirects the live room header's hard-sprite list into RAM at runtime; the check
correctly exits 1 on it. A "close enough" reading would have missed this.

**A methodological correction, because the snapshots could have lied.** Every
`snap-demo-iwram` sample shows `gSwitchPressed = 0`, and it would have been easy to
conclude the demo never presses switches. That conclusion would have been **wrong**:
`gSwitchPressed` is a one-frame transient and the samples are 500 frames apart, so a
500-frame interval cannot see it. The watchpoint can, because it sees every write. This
is the same trap as rule 28 in a new form — *a sampled column is not a negative*.

**Cheapest next experiments, in order.** (1) Find what *asks* for the next room. The
loader is `pc=0x0806B92C`; the caller is not in the decomp text, so search the ROM for
the other writers of `0x03000024` and read their callers, the same way the literal-pool
search that confirmed F2 worked. (2) Replay `logs/routes/demo-input-stream.csv` from our
entry frame and watch `gCurrentRoom` with `-AbortMemAddr 0x03000024` and **no** value
filter: the demo's own input is the only known-working traversal, and the abort reports
the exact first write — one run, no guessing. (3) `level_rooms.py` on each room's
`pBg1Data` tile data to see whether x=1696 is solid geometry.


**And the gate is one flag with one writer.** `gSwitchPressed` (`0x03000C0D`) is read in
`sprite_ai/vortex.c` at six places (`:203`, `:228`, `:270`, `:301`, `:337`, `:368`) and is
**written in exactly two places in the whole decompilation**: the switch sprite's pose-17
handler `func_802B694` (`asm/sprite_ai/disasm_switch.s:237`, `mov r1, #1; strb r1, [r0,#0]`
with `.L_2b724 = gSwitchPressed`) and `src/quit.c:21`, which clears it. Every other
occurrence in the tree is a literal-pool reference (`.4byte gSwitchPressed`), not a store.
The same handler hardcodes `gSwitchStates[4] = 2` (`disasm_switch.s:240-242`), and
`include/global_data.h:51-58` is `enum SwitchID { SWITCH_UNUSED, SWITCH_RED,
SWITCH_PURPLE, SWITCH_GREEN, SWITCH_ESCAPE }` — index 4 is `SWITCH_ESCAPE`, value 2 is
`SWITCH_STATE_SWITCHING_ON` (`global_data.h:60-65`).

**Reading — the first hypothesis, later corrected by the watchpoints below.** Since
*every* vortex in the game needs `gSwitchPressed` and *one* routine sets it, the switch is
the level's only vortex gate: room 0's vortex at x=2016 sits **inside** the reachable band
(1758…2337) and would open the instant the switch were pressed. The problem looked like
this much smaller question:

> **Why does Wario stop 62 raw units short of the switch?** The switch is at x=1696 and
> the leftmost x any route has reached is 1758.

The candidates are enumerable: a solid wall just west of the leftmost position; an obstacle
needing a jump/duck never combined with LEFT; a breakable object (the room has a
`PSPRITE_ROTATING_PLATFORM` at x=480); or a **transformation gate** — which would make
priority F 变身 a prerequisite for G rather than something parked behind it. A 20,000-frame
hammer at the left wall with every button combination did not move the boundary, so a pure
input-coverage explanation is already the least likely of the four.

> **Superseded in scope by update (c) below**, which shows the switch is the level *exit*
> and not the traversal at all. The 62-unit question is still the right question *for the
> exit*, and it is now one axis of G rather than the whole of it.

**Cheapest next experiments, in order.** (1) Sample `gSwitchPressed` (0x03000C0D) with
`run-route.ps1 -AbortMemAddr 0x03000C0D -AbortMemValue 1` while pressing LEFT at the
boundary, to confirm it is collision-blocked rather than unreached. (2) Search the ROM
text for the writers of `sprite->pose` (`strb` of 17 at offset 0x14) to find the routine
that arms the switch — still the open question below. (3) `level_rooms.py --level 0` on
each room's `pBg1Data` tile data to see whether x=1696 is inside solid geometry.

**Open question, stated exactly.** The switch's AI runs 111 → 113 → 16 and never reaches
pose 17, so the press must come from *outside* its own AI. Checked and ruled out: the
persistent-sprite restore theory (`gPersistentSpriteData` is `u8[16][64]` at IWRAM
`0x03000564`, and its six `asm/disasm_sprite.s` users treat each byte as a packed
age/flag pair, not a pose), `asm/disasm_sprite.s:689,770` (bitfield masks),
`src/sprite.c:91` (the AI table only), and `asm/sprite_ai/disasm_switch.s:5-102` (init and
reset only). **`disasm_switch.s` has exactly one `mov r1, #17` — line 120, inside
`func_802B5E4`, and it writes the persistent array, not `sprite->pose` (offset 0x14).**
So: *which code stores 17 into a sprite's `pose` for a switch?* The likely owner is the
central Wario-collision handler, which is not in the decompilation text.


**Still not attempted.** Editing `game.toml` to force a different starting room (that would
be a magic-value fix, forbidden by `AGENT_PROMPT.md` §6), and shaping the level with
code-copy metadata (no evidence that it is needed).

**Next instrument needed.** `level_rooms.py` can now name every room of level 0 and every
sprite in it. A watchpoint on `gCurrentRoom` is cheap but has already been run; what is
missing is a way to *see* which code writes it. The ROM is a text corpus: a scan for the
`gCurrentRoom` (0x03000024) literal outside the known writers would narrow the transition
to a few functions.

### G14 update 2026-10-02 (d) — the room-load call chain is now known from the writer up to the state machine

The watchpoint above reported the PC that writes `gCurrentRoom` but not *who asked*. Two new
tools answer that question against the ROM rather than against the decompilation text:
`tools/validation/rom_calls.py` (who branches to X; every Thumb `B`/conditional `B`/`BL`/
Thumb-2 `BL`, ARM `B`/`BL`, `BX Rm`, `BLX Rm`, plus literal-pool xrefs) and
`tools/validation/callchain.py` (the tail-call graph parsed out of `generated/cart/*.cpp`).
Neither is a guess: both gate themselves with `--self-test` against real ROM bytes.

**The chain, top to bottom.** `pc=0x0806B92C` is the *innermost* writer. Walking outward:

```text
gf_tfunc_0801C25A   0x0801C25A..0x0801C268   <- top of stack, reached only indirectly
    0x0801C25A  subs r0, r1, r0
    0x0801C25C  cmp  r5, #0x15
    0x0801C25E  movs r0, #0x00
    0x0801C260  adds r0, #0x30            <- r0 = 48, the room-load call's first argument
    0x0801C262  cmp  r1, #0x8B
    0x0801C264  bls  0x0801C25A            <- bounded spin: loop while r1 <= 139
    0x0801C266  bl   0x0806B410            <-- the one and only caller
  gf_tfunc_0806B410  0x0806B410..0x0806B41C
    0x0806B418  bl   0x0806B864
  gf_tfunc_0806B864  -> 0x0806B8E8 -> 0x0806B8FA -> 0x0806B902 -> 0x0806B90C
  gf_tfunc_0806B90C  ldr r0,[pc,#0x9c] ; strb r1,[r0]     (literal pool holds 0x03000024)
                                                                       <- writes gCurrentRoom
```

Two facts came from the **live trace**, not from static reading: the abort dump's recorded
return addresses were `0x0806B41D` and `0x0801C26B`, and `0x0801C26B` is `0x0801C26A | 1` —
the thumb bit on the return address of the `BL` at `0x0801C266`. That is what identified
`gf_tfunc_0801C25A` as the caller, and `rom_calls.py` then confirmed it is the only one.

**A second entry into the same loader exists** and is used by the demo's own room changes:
`gf_tfunc_0806AF58` and `gf_tfunc_0806AFC8` both `bl 0x0806B3E8` (at `0x0806AF74` and
`0x0806AFD4`), which tail-calls down to `gf_tfunc_0806B410` and from there into the same
loader. So the loader has **two doors** and the one the demo used is not the one the
`gCurrentRoom` watchpoint stopped inside.

**Where the top of the stack lives.** `gf_tfunc_0801C25A` is called by nothing but its own
spin loop, and the literal pool of its module (`0x0801C37C..0x0801C3E8`) is a list of IWRAM
globals: `0x03000074` (**`gCurrentRoomHeader`** — the same constant `level_rooms.py` gates
on), `0x03000022`, `0x03000025`, `0x03000002`, `0x03000003`, `0x03000037`, `0x03000047`,
`0x03001870`, `0x030019F6`, `0x030019F8`. `0x0801C164..0x0801C2D0` is a cluster of 2-to-16
byte accessor thunks (`ldr rN,[pc,#imm]`) plus this call — the shape of a **state-machine
dispatch**, not of hand-written game logic. The caller is therefore reached through a
**computed pointer**, which is why no branch and no literal points at it: a negative from a
branch scan is *not* a negative for a function-pointer target.

**Open question, narrowed to one statement.** *Which computed branch enters
`gf_tfunc_0801C25A`, and what value of `r1` makes its `cmp r1,#0x8B / bls` spin exit?* `r0`
is already known to be `0x30` at the call. The instrument for it does not exist yet: a
watchpoint can name the writer but not the caller, and `GBARECOMP_ABORT_ON_BRANCH_PC`
(`reference/gbarecomp/src/armv4t/runtime_arm.cpp:266-279`) fires on the PC of a *branch
instruction*, not on a branch *target*, so it cannot see a computed jump. The cheapest way
forward is `runtime_trace_copy_recent` through the windowed `--tcp-observe` channel, which
exposes the live trace ring the abort dump already prints.

**A correction this round forced, and it matters for every future ROM reading.** The
`runtime_insn` comments in `generated/cart/*.cpp` are **wrong for 16-bit Thumb BL**:
`recompiled_001.cpp:150100` renders `/* 0806B418 0806b418 T bl.hi 0x0806b41c */` and
`:150112` renders `/* 0806B41A T bl.lo 0x00000000 */`. The generator splits the two
halfwords into two invented pseudo-instructions. The **executed** code is right
(`recompiled_001.cpp:150119-150122` sets `R[15] = (R[14] + 0x448) & ~1` and
`R[14] = 0x0806B41D`, i.e. the real target `0x0806B864`, which `rom_calls.py` agrees with).
So: `runtime_insn` comments are a reliable *instruction* reference and **must not be used to
read a branch target** — `rom_calls.py` is the instrument for that.

**Update 2026-10-03, after G17.** G14 asked which game-mode index makes the new-game route
start a room load. `gf_tfunc_08000244` is the setter that answers it: with argument **1** it
writes mode `9` into `0x03000C3A` and reason `0` into `0x03000C3C`, and reason 0 is entry 0 of
the resume table — the room-load path. So "mode 1" *is* "run the room loader", and the two
IWRAM halfwords are the boundary between the game's mode vocabulary and the coroutine's reason
vocabulary. What G14 still wants — a mode change reachable from **player input** — is not
answered by this; the setter itself has no `B`/`BL` caller and is reached indirectly. See
G17.

**Update 2026-10-03, after G18 — the mode is a dispatch table, and mode 9 is the wrong lead.**
The game mode at `0x03000C3A` is not a plain state word: it is the **index of a 13-entry
function-pointer table at `0x0800020C`** (`gf_tfunc_080001DC`, `ldrsh r0,[r5]` with
`r5 = 0x03000C3A`, `cmps r0,#0xc / bls`, `lsl #2`, base literal, `ldr`, `mov r15,r0`). Entry 0
is the setter itself, so the table re-enters `gf_tfunc_08000244` to apply a mode change. And
the mode that actually runs the room loader is **8**, not 9: entry 8 (`0x080005A0`) calls the
coroutine resume dispatcher `0x0801B8BC` with reason 0. Mode 9 — the setter's argument 1 —
**never occurs** in 20,000 frames, and the negative is validated against a known positive.
On our routes the mode is only ever **0** (frame 287) and **8** (frame 8850).

G14's real question therefore survives this round, sharpened: the room load is reached from
**mode 8**, and mode 8 has exactly one branch caller, `0x0800017A`, which lies inside the
**ARM user IRQ handler** the cartridge DMA-copies to IWRAM at boot (`game.toml` span
`0x080000FC..0x080008FB` → `0x03000C44`, vector `0x03007FFC`). So the next question for G14
is **not** "which mode number" but "what VBlank-IRQ state makes the handler take that branch",
and whether host input can produce it. See G18.


---

## G15 — RESOLVED 2026-10-03: the room-load chain is entered through a 9-entry function-pointer table, not a branch

G14 left one question standing: *which computed branch enters `gf_tfunc_0801C25A`?* The
answer is that **there is no branch**, and there was never going to be one. The chain is
reached through a pointer table indexed at run time.

### The table

Read straight out of the ROM (file offset = address - `0x08000000`):

| address | word | meaning |
|---|---|---|
| `0x0801B8E0` | `0x0801B8E4` | literal: the table's own base address |
| `0x0801B8E4` | `0x0801B908` | entry 0 — the room-load chain top |
| `0x0801B8E8` | `0x0801B934` | entry 1 |
| `0x0801B8EC` | `0x0801B950` | entry 2 |
| `0x0801B8F0` | `0x0801BA4E` | entry 3 |
| `0x0801B8F4` | `0x0801BA98` | entry 4 |
| `0x0801B8F8` | `0x0801BB4C` | entry 5 |
| `0x0801B8FC` | `0x0801BAC0` | entry 6 |
| `0x0801B900` | `0x0801BB30` | entry 7 |
| `0x0801B904` | `0x0801BB44` | entry 8 |

Nine entries, and the count is not a guess: the dispatcher's own bounds check is
`cmps r0,#0x8 / bls`, i.e. it accepts indices 0..8 and the ninth entry is the last one
that can be reached. The dispatch is split across **two** functions, and reading it takes
both of them in full — see G16 for how I got the first one wrong:

```c
/* gf_tfunc_0801B8C2 — read the index and range-check it */
0801B8C2  movs r5,#0x0
0801B8C4  ldr  r0,[r15,#0x14]    ; (0x0801B8C8 & ~3) + 0x14 = 0x0801B8DC = 0x03000C3C
0801B8C6  movs r1,#0x0
0801B8C8  ldrsh r0,[r0,+r1]     ; sign-extended halfword from IWRAM 0x03000C3C  = the INDEX
0801B8CA  cmps r0,#0x8
0801B8CC  bls  0x0801B8D0       ; in range -> tail-call the switch
0801B8CE  b    0x0801BB4C       ; out of range -> default handler

/* gf_tfunc_0801B8D0 — the switch itself */
0801B8D0  movs r0,r0,lsl #2      ; index * 4   -> 4-byte stride
0801B8D2  ldr  r1,[r15,#0xc]     ; (0x0801B8D6 & ~3) + 0x0C = 0x0801B8E0 = 0x0801B8E4  <- BASE
0801B8D4  adds r0,r0,r1
0801B8D6  ldr  r0,[r0]
0801B8D8  mov  r15,r0            ; computed jump
```

So **the index is a halfword in IWRAM at `0x03000C3C`**, not a register parameter, and the
table base comes from a *different* literal load in a *different* function. A state index
therefore selects one of nine handlers, and **entry 0 is the room-load path**. This is the
dispatch shape the `0x0801C164..0x0801C2D0` thunk cluster pointed at in G14.

### The chain, confirmed end to end

From `logs/routes/g15-room3.err.log` (4096 trace events, `#33006840..#33010864`, run with
`-AbortMemAddr 0x03000024 -AbortMemValue 3 -TraceDumpDepth 4096`):

```
gf_tfunc_0801BBEA                     no B/BL caller anywhere
  -> gf_tfunc_0801B8C2                dispatcher, cmps r0,#0x8 / bls
    -> [table 0x0801B8E4, entry 0] gf_tfunc_0801B908
      -> gf_tfunc_0801C1C0            ARM mode; DISPCNT2=0x00009729, IE=0x00002001, IF=1
        -> gf_tfunc_0801C1E6          0x04000050=0xFF, 0x04000054=0x10, 0x03001870=0x10, DISPCNT=0
          -> gf_tfunc_0801C218        DMA1 VRAM fill, then a shared tile-upload helper
            -> gf_tfunc_080746C0      another DMA (0x08400AE8 -> 0x06011000, cnt 0x80001800)
            -> gf_tfunc_0801C22C      three DMA1 ROM->OBJ VRAM copies (0x05000200/40/80)
              -> gf_tfunc_0801C258    2 bytes, tail
                -> gf_tfunc_0801C25A  r0=0x30, cmp r1,#0x8B / bls spin, then bl 0x0806B410
                  -> gf_tfunc_0806B410 -> 0x0806B864 -> 0x0806B8E8 -> 0x0806B8FA
                     -> 0x0806B902 -> gf_tfunc_0806B90C
                        -> mem_w pc=0x0806B92C addr=0x03000024 value=0x00000003
```

`0x080746C0` is a **shared DMA/tile-upload helper, not room logic** — the same
`gf_tfunc_0801C218` sets up its own DMA first, and only then branches to it.

The trace line that settled the question is `#33010773`:

```
#33010773 dispatch pc=0x0801B908  <gf_autojt_0801B8E4_00+0x0>  r0=0x0801B908  r1=0x0801B8E4
```

`r0` is the resolved target and `r1` is the table base. That pairing is the signature of a
call-by-pointer helper, and it is why no branch scan could ever find this caller.

### One level up is still outside static visibility, until the second table falls out

`gf_tfunc_0801BBEA` has no B/BL caller in ROM or IWRAM and no 32-bit literal pointing at
it (`rom_calls.py --why --target 0x0801BBEA` exits 1; `--xrefs` finds nothing). The
`runtime_trace` record supplies one more link: it reports
`dispatch pc=0x0801BBEA lr=0x0801BBEB`, and the only `BL` in the ROM that can have produced
that link value sits at `0x0801BBE6` and targets `0x08000C14`. So `gf_tfunc_0801BBEA` is
entered **by returning from `0x08000C14`**, not by being called — which puts the next frame
in the very low ROM, near the entry point `0x080000C0`.

### The pattern continues upward: a second table, structurally identical

That `BL` at `0x0801BBE6` lives inside `gf_autojt_0801BBC8_00`, the auto jump table rooted
at `0x0801BBE4` — and `0x0801BBE4` is *itself* an entry of a table at `0x0801BBC8`:

| address | word | meaning |
|---|---|---|
| `0x0801BBC4` | `0x0801BBC8` | literal: this table's own base — the same idiom as `0x0801B8E0` |
| `0x0801BBC8` | `0x0801BBE4` | entry 0 |
| `0x0801BBCC` | `0x0801BBE4` | entry 1 |
| `0x0801BBD0` | `0x0801BBFC` | entry 2 |
| `0x0801BBD4` | `0x0801BBE4` | entry 3 |
| `0x0801BBD8` | `0x0801BBFC` | entry 4 |
| `0x0801BBDC` | `0x0801BBFC` | entry 5 |
| `0x0801BBE0` | `0x0801BBF0` | entry 6 |
| `0x0801BBE4` | `0xF7E54801` | code — the table is 7 words, then the first handler |

Seven entries, and again the count is derived rather than eyeballed: the dispatcher
`gf_tfunc_0801BBA8` is `cmps r0,#0x6 / bhi 0x0801bbfc`. It is the clearer of the two
dispatchers and shows the mechanism in full:

```c
/* 0801BBAA ldr r0,[r15,#0x14] */  g_cpu.R[0] = _v_0801BBAA;   /* table base */
/* 0801BBB0 cmps r0,#0x6 */
/* 0801BBB2 bhi 0x0801bbfc */
/* 0801BBB4 movs r0,r0,lsl #2 */                              /* 4-byte stride */
/* 0801BBB6 ldr r1,[r15,#0xc] */                              /* base literal */
/* 0801BBB8 adds r0,r0,r1 */
/* 0801BBBA ldr r0,[r0] */
/* 0801BBBC mov r15,r0 */                                     /* computed jump */
```

A game mode selects one of seven handlers here and one of nine there, so **the room-load path
is reached through a stack of these tables, not through a branch**. The 7-entry table
collapses to three distinct targets (`0x0801BBE4` x3, `0x0801BBFC` x3, `0x0801BBF0` x1),
which is why the dispatch table has auto-jump-table entries carrying repeat indices.

**Above the tables, static analysis works again.** `gf_tfunc_08000C14` has **27 branch
callers** (`rom_calls.py --target 0x08000C14`), among them `gf_tfunc_080006F6`,
`gf_tfunc_080008DC`, six entries of `gf_autojt_080034D4`, and — notably —
`gf_tfunc_0801C1C0`, which is itself inside the room-load chain below. The layer a branch scan
could not see turns out to be two tables deep, and past it the graph is ordinary.

Still open, and the natural next G step: **which value feeds the table index**, and what
`0x08000C14` does with the 27 reasons it is called. Also unanswered from G14: the `r1` that
makes `gf_tfunc_0801C25A`'s `cmp r1,#0x8B / bls` spin exit. The instrument for the second is
a watchpoint on `0x03000024` **with a value filter** — an unfiltered one aborts at
`vblanks=2` inside the BIOS with no ROM code involved, which is a fact about the instrument
and not about the game.

### What this round cost: I was wrong three separate times about the same instruction

The instruction at `0x0801C228` is `hw1=0xF058`, `hw2=0xFA4A`. I "proved" the generator
wrong with a script reporting *"58,710 candidate sites, ARM formula 2,307 in-ROM, generator
formula 53,490 in-ROM, identical targets: 0"*. The generator was right. What happened:

1. **My hand-decode** used `imm32 = (imm10<<19) | (imm11<<8)`.
2. **My verification script** repeated the identical mistake, and its confident negative
   looked like evidence against the generator.
3. **My conclusion** followed from the script.

The correct offset field is `(S<<24)|(I1<<23)|(I2<<22)|(imm10<<12)|(imm11<<1)` with
`I1 = NOT(J1 XOR S)`, `I2 = NOT(J2 XOR S)` — `imm32 = (imm10<<12)|(imm11<<1)`, seven bits
less than I used. Checked: `(0x058<<12)|(0x24A<<1) = 0x58494`, and
`0x0801C22C + 0x58494 = 0x080746C0`, which is precisely the dispatch the guest recorded, with
bit 0 clear as a Thumb branch requires.

I had a **validated positive** in hand the whole time — `0x0806B418 -> 0x0806B864`, already
gated in `rom_calls.py --self-test` — and did not check the new 32-bit arithmetic against it
before publishing a verdict. That is why `docs/VALIDATION.md` rules 35 and 36 exist, and why
`0x0801C228 -> 0x080746C0` is now a self-test case whose expected target was read out of a
**live trace** rather than out of a decoder.

The `bl.hi` / `bl.lo` comment split is worse here than for 16-bit `BL`: `bl.hi 0x0807422c`
is a plausible-looking *wrong* target (it is `target - lo_offset`) while `bl.lo 0x00000000`
shows nothing at all. G14 said the comments must not be used to read a branch target; for
the `BL` pair they are actively misleading.

### A fourth instance of the same field-width bug, in this file

`rom_calls.py` contained `if 0xD000 <= (hw2 >> 11) <= 0xD7FF:` guarding a separate `BL32`
decode path. `hw2 >> 11` is five bits, so the test is false for every possible halfword and
the branch was **dead code** — and the docstring above it promised a `('BL32?', ...)` result
the function could never produce. The arithmetic below it was correct and is what actually
runs. Removed; the blind spots (no `TBB`/`TBH`, no `BX Rm` target resolution, no run-time
IWRAM pointer table) are now **stated in the docstring** instead of being implied, per rule
32. A dead decoder path and a docstring that describes it are the same defect: both are a
promise no code keeps.

## G16 — RESOLVED 2026-10-03: the game-mode dispatch is a coroutine scheduler, and `0x03000C3C` is a yield slot

G15's own "next step" was to find the value feeding the table index. It is a **halfword in
IWRAM at `0x03000C3C`**, and the code that writes it turns out to be a **stackful coroutine
switcher**, which reframes what the 9-entry table is.

### The index source, established two independent ways

*Static.* `gf_tfunc_0801B8C2` does `ldr r0,[r15,#0x14]`; under the Thumb rule the base is
`(0x0801B8C8 & ~3) + 0x14 = 0x0801B8DC`, and the word there is **`0x03000C3C`**. It then
does `ldrsh r0,[r0,+r1]` with `r1 = 0`, i.e. a sign-extended halfword read from IWRAM.

*Dynamic.* A **value-filtered** watchpoint on `0x03000C3C` aborts at the first write of the
value the IWRAM snapshots already showed:

```
runtime_trace: mem-write-addr abort pc=0x08003BE2 <gf_tfunc_08003BE2+0x0>
               addr=0x03000C3C value=0x00000007 width=2 (vblanks=902)
```

`width=2` is a **`strh`** — exactly the width of the `ldrsh` that consumes it. Both the
writer and the reader are halfword, which is a symmetry a coincidence would not produce.

### The writer is not a setter

```c
08003BE2  strh  r0,[r1]        ; publish the yield reason into the slot whose address is in r1
08003BE4  add  r13,r13,#0x4
08003BE6  ldm  r13!,{r4,r5}    ; pop two saved registers
08003BE8  ldm  r13!,{r0}       ; pop the next resume address
08003BEA  bx   r0              ; and go there
```

That is a **context switch**: publish why you yielded, unwind, and branch to whoever is next.
`0x03000C3C` is therefore a **yield-reason slot**, and the 9-entry table at `0x0801B8E4` is
a **resume table for one coroutine**, indexed by the reason it last yielded with — not a
game-mode switch in the ordinary sense. That explains entry 0 being the room-load path: reason
0 is "the room loader wants to run". The frame is reached through
`gf_tfunc_0800428C` → interworking thunk `0x08003B6A` → `0x08003BE2`; the only branch
target of the switcher is `0x08003BD2 B -> 0x08003BE2` inside `gf_autojt_08003A98_01`.

**The observed value sequence** is now checkable: `0x03000C3C` holds **7** in both IWRAM
snapshots (`iwram-900.bin`, `iwram-title.bin`) and is written 7 at `vblanks=902`; at the
much later moment the G15 trace caught, the dispatch went to entry 0, so the slot held 0.
Attract mode drives the room-loader coroutine from 0 through 7 and back.

### What I got wrong immediately after resolving G15

The G15 write-up attributed the table base `0x0801B8E4` to
`ldr r0,[r15,#0x14]` in `gf_tfunc_0801B8C2`. That instruction loads **`0x03000C3C`**. The
table base is loaded by a *different* instruction, `ldr r1,[r15,#0xc]` at `0x0801B8D2`, in a
*different* function, `gf_tfunc_0801B8D0`. Two adjacent functions, two PC-relative loads, and
I attributed one to the other. The structural conclusion survived — the table is real, the
stride is 4, the bounds check is `#8`, entry 0 is the room-load path — but the causal claim
about which instruction fetched the base was simply wrong, and it was wrong in the direction
that made the finding look tidier than it was.

**Why it happened.** The first dump of `gf_tfunc_0801B8C2` was truncated: the extraction regex
stopped at the first `\n}` in the body, and a `{` ... `}` block inside the function ended at
column 0, so I read 5 instructions and believed I had the function. A second regex then
printed *nothing* on a body that plainly had instruction lines, and I nearly recorded that as
an absence. Both times the right move was to dump the raw text and look at it.

Hence **rules 37 and 38** in `docs/VALIDATION.md`: a pointer-shaped run of words next to code
is not a dispatch table until some instruction loads its base address — adjacency is not a
reference — and a load must be attributed to the instruction that performs it, with the
literal address computed from *that instruction's* PC.

## G17 — RESOLVED 2026-10-03: all nine resume reasons measured, and the mode setter that writes them

G16 named `0x03000C3C` as a yield-reason slot and left the nine reasons unmapped. All nine
are now measured, one bounded run per value, by a **value-filtered** watchpoint
(`run-route.ps1 -AbortMemAddr 0x03000C3C -AbortMemValue <v> -Frames 20000`). Results are in
`logs/routes/resume-sweep.txt` and the per-run `logs/routes/resume-v*.err.log`.

| reason | table entry | publishing PC | frame | width |
|---|---|---|---|---|
| 0 | `0x0801B908` | `0x0800062E` (via `gf_tfunc_08000244`) | 8850 | 2 |
| 1 | `0x0801B934` | `0x08003BE2` (the switcher) | 288 | 2 |
| 2 | `0x0801B950` | `0x080035F2` | 288 | 2 |
| 3 | `0x0801BA4E` | `0x08003BE2` | 290 | 2 |
| 4 | `0x0801BA98` | `0x08003F76` | 445 | 2 |
| 5 | `0x0801BB4C` | `0x08003BE2` | 449 | 2 |
| 6 | `0x0801BAC0` | `0x08004128` | 899 | 2 |
| 7 | `0x0801BB30` | `0x08003BE2` | 902 | 2 |
| 8 | `0x0801BB44` | `0x08004342` | 1139 | 2 |

Two reasons per stage, monotonically rising — the attract demo drives the room-loader
coroutine through 0→1→2→3→4→5→6→7→8 and later back to 0. Every hit is `width=2`, a
`strh`, matching the `ldrsh` that consumes the slot.

### The publishers are three different mechanisms

* **Reasons 1, 3, 5, 7** are published by the coroutine switcher `0x08003BE2` itself, which
  carries the reason in `r0`.
* **Reasons 4, 6, 8** are published by three *separate* increment sites
  (`ldrh r0,[r1] / adds r0,r0,#1 / strh r0,[r1]`) in `gf_tfunc_08003F64`,
  `gf_tfunc_08004120` and `gf_tfunc_08004342`. Each loads the slot through a separate
  `ldr r1,[r15,#…]` that resolves to `0x03000C3C`, and each is guarded by a different
  counter — `cmps r0,#0x33` at `0x08003F6C`, `cmps r1,#0x50` at `0x0800411A`,
  `cmps r1,#0xec` at `0x08004338`.
* **Reason 2** is published by a dedicated three-instruction stub `gf_tfunc_080035F0`
  (`movs r0,#0x2 / strh r0,[r1] / b 0x08003906`). It sets the value directly and does
  **not** pop a frame, so it is not a yield at all.

### What the nine entries actually do

The region `0x0801B908..0x0801BB4C` is 229 halfword rows — one instruction stream, 204 real
instructions — split into nine resume points. Decoded from the generator's instruction
comments with branch targets taken from `rom_calls.bl_targets`:

| reason | first actions |
|---|---|
| 0 | sign-extend a byte from a PC-relative pointer; if zero, `bl 0x08010438` |
| 1 | `bl 0x0801C1B4`, `bl 0x0801D248`; if not ready **`b 0x0801BB4C`** |
| 2 | `bl 0x080102D8`, `bl 0x0801C1B4`; test **bit 3** of a halfword at `0x03001848` |
| 3 | `bl 0x0801C1B4`, `bl 0x0801D2A8`; if not ready **`b 0x0801BB4C`** |
| 4 | `bl 0x0800FFDC`; `ldrsh` a value and `cmps r0,#2`; if different **`b 0x0801BB4C`** |
| 5 | **the common tail** — re-read `0x03000C3C`, `beq 0x0801BB90`, else `bl 0x0806C75C` |
| 6 | `bl 0x080720E8` (the level **exit** function), switch on its result |
| 7 | `bl 0x080743BC`; if zero fall to 5, else **`strh` 2 into the slot** → yield reason 2 |
| 8 | `bl 0x0801D308`, `bl 0x0806C5FC`, then falls into 5 |

**Reason 5 is not a peer of the others.** Reasons 1, 3 and 4 all branch to `0x0801BB4C` and
reason 8 falls straight into it, so it is the shared exit/cleanup handler — which is also
why it is the dispatcher's `b 0x0801bb4c` default. And reason 7's handler publishes reason
2, so there is at least one statically-provable edge in the graph: **7 → 2**.

### The mode setter: `0x03000C3A` and `0x03000C3C` are written together

Chasing reason 0's publisher led to `gf_tfunc_08000244`, and that function is the missing
link between G14 and G16. It switches on its `r0` argument and writes **two adjacent
IWRAM halfwords** — the game mode at `0x03000C3A` and the coroutine's resume reason at
`0x03000C3C`:

| argument | `0x03000C3A` (mode) | `0x03000C3C` (reason) |
|---|---|---|
| 1 | **9** | **0** → table entry 0 → **room load** |
| 2 | 1 | 5 |
| 3 | 12 | 0 |
| 4 | 0 | −1 (invalidates the coroutine; `ldrsh` gives −1, so `cmps r0,#0x8 / bls` falls through to the default) |
| ≥5 | tests bit 7 of the byte at `0x03000020`; if clear, `b 0x08000630` and stores nothing; if set, mode 8 and reason 0 |

So "switch to mode 1" *is* "run the room loader", through one instruction pair, and the
`0x03000C3A`/`0x03000C3C` pair is the boundary between the two vocabularies. Like
`gf_tfunc_0801BB4C`, this setter has **no `B`/`BL` caller anywhere** —
`rom_calls.py --target 0x08000244` reports none — so it too is entered indirectly.

> **Corrected by G18, same day.** What is written above is right about what the code *does*
> and wrong about what *runs*. Argument 1 is never executed on any of our routes: a
> value-filtered watchpoint on `0x03000C3A` for **9** does not fire in 20,000 frames, while
> the identical instrument shape hits the known positive `0x03000C3C = 7` at `vblanks=902`
> on the nose. The room load actually arrives through the **≥5 bit-7 path**, which writes
> **mode 8**; and mode 8's handler is the room loader. See G18.

### Two measurement failures worth recording

**Reason 0's first reading was a false positive, and re-measuring it was still not enough.**
The obvious instrument — a value filter for `0` — also matches the BIOS zeroing IWRAM, and
it fired at `pc=0x00000C08` (a BIOS address) at `width=4`, `vblanks=270`. `-AbortMinFrame
120` did not help, because it skipped the early BIOS write at `vblanks=2` and then aborted
on a *second* one — so the min-frame did not just contaminate the result, it destroyed the
measurement by stopping the run early. Runs at `-AbortMinFrame 400` and `1200` then agree
independently on `vblanks=8850`, and an **unfiltered** watchpoint with `-AbortMinFrame 8000`
reproduces the same PC and value. A filter cannot distinguish a game's write of `0` from a
clear of `0`; only two independent min-frames plus an unfiltered run can.

**Then the decoded value contradicted the guest, and the guest was right.** The instructions
above `0x0800062E` — `movs r2,#4` (`0x2204`), `rsbs r2,r2,#0` (`0x4252`, the data-processing
register group `010000` with opcode `1001`), `adds r0,r2,#0` (`0x1C10`) — compute **−4**, so
the store should write `0xFFFC`, and the runtime's comparison is exact
(`runtime_arm.cpp:213`), so `0xFFFC` could not have matched a filter of `0`. The generated
C++ for the store confirms it traces `(uint32_t)(g_cpu.R[0] & 0xFFFFu)`. Both decodings were
correct; the wrong assumption was that the code *above* it ran. `gf_tfunc_0800062E` is a
one-instruction thunk with **22 branch callers**, and the `dispatch` event immediately before
the write shows `gf_tfunc_08000244` entered with `r0=0x00000000`, `r5=0x03000C3A` — one of
the other 21 paths. Hence **rules 40 and 41** in `docs/VALIDATION.md`.

### Still open

This maps *what* runs when; it does not yet say **what starts the coroutine**. The attract
demo enters room 2 at frame 9010, and the question "how does a room transition get initiated
from player input" is unchanged — it is now a scheduler question rather than a branch
question, but it is not answered. `gf_tfunc_0801C25A`'s `cmp r1,#0x8B / bls` spin exit is
also still unmeasured; the instrument for it is a value-filtered watchpoint.

## G18 — RESOLVED 2026-10-03: the game mode is a 13-entry dispatch table, mode 8 is the room loader, and it is entered from the user IRQ handler

G17's open question was "what enters `gf_tfunc_08000244` with argument 1". The answer is
**nothing does** — and the reason it was being asked is that the room load does not come from
mode 9. It comes from **mode 8**.

### `gf_tfunc_08000244` is reached through a 13-entry game-mode table

`gf_tfunc_08000244` has no `B`/`BL` caller, and the ROM contains **zero** 32-bit pointer
words to `0x08000244` (checked even and odd, so interworking is excluded). The entry is a
**computed branch**. `callchain.py --from 0x08000244` names the hop —
`gf_autojt_0800020C_00` tail-calls it — and that name points at a whole table:

```
0x080001DC  ldr  r1,[r15,#0x20]   ; 0x03000C41   byte counter
0x080001DE  ldrb r0,[r1]
0x080001E0  adds r0,r0,#1
0x080001E2  strb r0,[r1]
0x080001E4  ldr  r1,[r15,#0x1c]   ; 0x03000006   halfword counter
0x080001E6  ldrh r0,[r1]
0x080001E8  adds r0,r0,#1
0x080001EA  strh r0,[r1]
0x080001EC  movs r1,#0
0x080001EE  ldrsh r0,[r5,+r1]    ; <-- INDEX
0x080001F0  cmps r0,#0xc
0x080001F2  bls  0x080001f6
0x080001F4  b    0x08000630       ; out of range
0x080001F6  movs r0,r0,lsl #2
0x080001F8  ldr  r1,[r15,#0xc]    ; TABLE BASE 0x0800020C
0x080001FA  adds r0,r0,r1
0x080001FC  ldr  r0,[r0]
0x080001FE  mov  r15,r0           ; computed branch
```

This is the same five-instruction shape as the 9-entry coroutine table G15 found, one level
up. The table at **`0x0800020C`**, stride 4, 13 entries read from the ROM:

| i | entry | i | entry |
|---|---|---|---|
| 0 | `0x08000240` → **the setter** | 7 | `0x0800058C` |
| 1 | `0x0800037C` | 8 | **`0x080005A0` → the room loader** |
| 2 | `0x080003C0` | 9 | `0x080002D0` |
| 3 | `0x08000548` | 10 | `0x080005DC` |
| 4 | `0x080004CC` | 11 | **`0x08000630` — the exit stub** |
| 5 | `0x0800053A` | 12 | `0x08000618` |
| 6 | `0x0800054E` | | |

**Entry 11 is the same address the out-of-range `b 0x08000630` jumps to**, so "invalid mode"
is a legitimate entry of the table rather than only a guard. That also explains the missing
`_11` in `symbol_map.cpp`: `0x08000630` is an ordinary function, so it was named
`gf_tfunc_08000630`, while the other twelve got `gf_autojt_0800020C_00`..`_10`, `_12`.

**The index is the game mode itself.** The trace settles it — the `dispatch` event at
`0x080001DC` shows `r5=0x03000C3A`, the mode halfword:

```
#1654898 dispatch pc=0x080001DC <gf_tfunc_080001DC+0x0>
             r0=0x00000000 r1=0x00000000 r2=0x03000C3A
             r3=0x03001846 r4=0x03000018 r5=0x03000C3A
```

So the structure is **mode → 13-entry table → per-mode handler**, and **entry 0 is the setter
itself**: the table re-enters `gf_tfunc_08000244` to apply a mode change. The two tables nest:
`0x03000C3A` (game mode) picks a handler, and `0x03000C3C` (coroutine reason) picks a resume
point inside the room-loader coroutine.

### The mode setter at `0x0800073C` is a *conditional* one

`0x03000C3A` is also written by a second routine, which the G17 trace led to:

```
0x08000728  ldr  r0,[r15,#0x44]   ; 0x03001844
0x0800072A  strh r7,[r0]          ; clear
0x0800072C  ldr  r0,[r15,#0x44]   ; 0x03001846
0x0800072E  strh r7,[r0]          ; clear
0x08000730  ldr  r4,[r15,#0x44]   ; 0x03001848
0x08000732  strh r7,[r4]          ; clear (r4 := 0x03001848)
0x08000734  ldr  r0,[r15,#0x44]   ; 0x03000C3C
0x08000736  strh r7,[r0]          ; reason := r7
0x08000738  bl   0x08000954
0x0800073C  ldrh r0,[r4]          ; r0 := [0x03001848]   <-- re-reads the word it just cleared
0x0800073E  movs r5,r5,lsr #16
0x08000740  cmps r0,r5
0x08000742  bne  0x08000784        ; differ -> mode := r7
0x08000744  ldr  r1,[r15,#0x38]   ; 0x03000C3A
0x08000746  movs r0,#0xa          ; equal  -> mode := 10
0x08000748  strh r0,[r1]
0x0800074A  b    0x08000788        ; both paths clear 0x03001844/46/48 and byte 0x0300001E
```

i.e. `mode := (state == expected) ? 10 : r7`, then clear the three state words it just read.
`0x03001848` is the halfword whose **bit 3** reason 2's handler polls, so this routine is what
resets the state the coroutine waits on.

### Mode 8's handler is the room loader

```
0x080005A0  bl   0x0801B8BC        ; <-- run the room-loader coroutine
0x080005A4  cmps r0,#0
0x080005A6  beq  0x08000630
0x080005A8  ldr  r0,[r15,#0x24]   ; 0x03000C35
0x080005AA  ldrb r0,[r0] ; lsl #24 ; asr #24
0x080005B0  cmps r0,#0
0x080005B2  beq  0x08000630
0x080005B4  ldr  r4,[r15,#0x1c]   ; 0x03000C3C
0x080005B6  bl   0x08072B98
0x080005BA  movs r1,#0 ; cmps r0,#0 ; bne 0x080005c6
0x080005C0  movs r5,#1 ; rsbs r5,r5,#0 ; adds r1,r5,#0   ; r1 = -1
0x080005C6  strh r1,[r4]          ; reason := (0x08072B98 returned 0 ? -1 : 0)
0x080005C8  ldr  r1,[r15,#0xc]    ; 0x03000C3A
0x080005CA  movs r0,#0
0x080005CC  b    0x0800062e       ; mode := 0
```

`0x0801B8BC` is the coroutine resume dispatcher G15/G16 mapped: prologue,
`ldrsh` from `0x03000C3C`, `cmps r0,#0x8 / bls`, and the `lsl #2 / ldr / mov r15,r0` block at
`0x0801B8D0` whose base literal is `0x0801B8E4`. So **mode 8 → entry 8 → `0x080005A0` →
coroutine with reason 0 → entry 0 → `0x0801B908`**, the room load.

### The mode values that actually occur, and the negative that is trustworthy

| mode | written by | value | frame |
|---|---|---|---|
| 0 | `0x08000786` (`mode := r7`) | 0 | 287 |
| 8 | `0x080002BA` (setter's ≥5 bit-7 path) | 8 | 8850 |
| 9 | — | **never** | — |

**Mode 9 never happens.** `-AbortMemAddr 0x03000C3A -AbortMemValue 9 -Frames 20000` does not
fire. That negative is only worth something because the identical instrument shape was
validated against a **known positive** first: `0x03000C3C = 7` aborts at
`pc=0x08003BE2 <gf_tfunc_08003BE2+0x0> value=0x00000007 (vblanks=902)`, exactly the frame
`logs/routes/resume-sweep.txt` predicts. Both snapshots (`iwram-900.bin`, `iwram-title.bin`)
agree: `0x03000C3A = 0`, `0x03000C3C = 7`.

The frame-8850 hit is worth one more correction. G17's deep trace recorded the setter entered
with `r0=0x00000000` and read that as "not argument 1", then left the value unexplained. It
is explained: **with `r0=0` all four `cmps` fail**, control reaches `0x080002A8`, the bit-7
test on `0x03000020` passes, and the routine writes **8** and reason 0. The one call, the
`r0=0` in the trace, the mode-8 write at frame 8850 and last round's reason-0 write at frame
8850 are all the same event. `0x03000C41 = 100` and `0x03000006 = 612` in both snapshots are
the two counters `0x080001DC` bumps, so the mode dispatcher has been running.

### RETRACTED 2026-10-04 (G19): it is **not** entered from the user IRQ handler

Every sentence in the section above about `0x0800017A` is wrong, and so is the G14 update that
repeated it. The call site never existed. `rom_calls.py` printed exactly one hit —
`0x0800017A B -> 0x080005A0 gf_afunc_080000F0+0x8A` — and that line is the only place the claim
ever was.

**The defect.** `rom_calls.scan` walks every *halfword* and decodes Thumb, because that is how it
finds a call site without an instruction-boundary map. In an ARM region that is not a weaker
decoder, it is a wrong one: the walk reaches the upper halfword of every ARM word, and an ARM
data-processing word has `hw1 >> 11 == 0x1C`, which is exactly the 16-bit unconditional-`B`
opcode. `0x08000178` holds the ARM word `0xE2110C01` — `tst r1,#0x100` (opcode `0b1000`, rotate
`0xC`, imm8 `0x01`) — and its upper halfword `0xE211` decodes as `B 0x080005A0`. The target
matched to the byte. This is a **class** of false positive, not one.

**Two of G18's supporting claims were false for a related reason.** G18 reported that
`0x08000100..0x080001CB` has "no dispatch-table row and no symbol at all". It has plenty: the span
*is* compiled, at its **IWRAM** addresses — `gf_afunc_03000C44`, `gf_afunc_03000C58`,
`gf_afunc_03000CF4` in `symbol_map.cpp`, with dispatch rows `0x03000C44..0x03000CEC`. Only the
ROM addresses lack rows, because the ROM side is declared a `[[code_copy]]` blob. A region the
tooling has no rows *for* is not a region with no code; you have to look at the address the code
actually runs from.

**What the handler really is.** Read from the generated C++, which is the only source carrying
instruction comments for the blob (`generated/cart/recompiled_005.cpp:17`,
`generated/cart/recompiled_002.cpp:17`):

```
03000C44  A mov  r3,#0x4000000    ; REG_IE
03000C48  A add  r3,r3,#0x200     ; REG_IF
03000C4C  A ldr  r2,[r3]
03000C50  A and  r1,r2,r2,lsr #16
03000C54  A ands r0,r1,#0x2000
03000C58  A bne 0x03000c58        ; spin until the VBlank bit clears
03000C5C  A mov  r2,#0
03000C60  A ands r0,r1,#0x1
03000C64  A bne 0x03000cf4        ; ...one 4-byte slot per enable bit...
03000CC0  A ands r0,r1,#0x100
03000CC4  A bne 0x03000cf4
03000CF4        mem_w addr=0x04000202 value=1   ; REG_IF |= the bit, acknowledge
```

It is a **VBlank-IRQ source demultiplexer**: it waits out the VBlank bit, then walks the
interrupt-enable bits `0x0001`…`0x1000`, accumulating four bytes per source into `r2` and jumping
to the shared `REG_IF` acknowledge at `0x03000CF4`. The trace confirms it runs and does exactly
that — `logs/routes/g15-room3.err.log:1812-1814`, `r0=0x04000000` (REG_IE), `r3=0x04000200`
(REG_IF), then `mem_w addr=0x04000202 value=1`. It never mentions `0x080005A0`.

**The corrected answer.** With the scanner fixed, `rom_calls.py --target 0x080005A0` reports
**no `B`/`BL` caller at all**. The mode-8 handler is reached *only* by the computed branch
`mov r15,r0` at `0x080001FE` in the 13-entry game-mode dispatcher — which is what G18's
*structure* already said, and what its IRQ narrative contradicted.

### G19 — the guard on entering room-load mode is a single flag byte

`logs/routes/g18-mode-late.err.log` caught the mode-8 write with `lr=0x0800B43B`, i.e. issued
from `gf_tfunc_0800B43A` — not from an IRQ handler, and via a **tail call**, which is why the
scanner's "no `B`/`BL` caller" for `gf_tfunc_08000244` was itself a false *negative* on the same
target family and has to be read as "no direct call", never as "no caller".

The setter reaches mode 8 through its `r0 == 0` fall-through, and the condition guarding it is
five instructions:

```
080002A8  T ldr  r0,[r15,#0x18]    ; literal 0x080002C4 = 0x03000020
080002AA  T ldrb r1,[r0]           ; r1 = gUnk_3000020
080002AC  T movs r0,#0x80
080002AE  T ands r0,r0,r1
080002B0  T cmps r0,#0x0
080002B2  T bne  0x080002b6        ; -> mode 8, reason 0
080002B4  T b    0x08000630        ; otherwise: do nothing at all
080002B6  T ldr  r1,[r15,#0x10]    ; literal 0x080002C8 = 0x03000C3A
080002B8  T movs r0,#0x8
080002BA  T strh r0,[r1]           ; the measured store
080002BC  T ldr  r1,[r15,#0xc]     ; literal 0x080002CC = 0x03000C3C
080002BE  T movs r0,#0x0
080002C0  T b    0x0800062e
```

Literal addresses are computed from each `ldr`'s **own** PC, `(addr+4) & ~3` + imm, per rule 38:
`0x080002AC + 0x18 = 0x080002C4`, `0x080002BA + 0x10 = 0x080002C8`, `0x080002C0 + 0x0C = 0x080002CC`.
The pool at `0x080002C4` reads `0x03000020`, `0x03000C3A`, `0x03000C3C` — which cross-checks the
two addresses G18 had already attributed correctly.

**`0x03000020` is not a pointer.** `symbols/iwram_map.tsv` names it `gUnk_3000020`, one byte, two
bytes below `gCurrentPassage` and immediately above `gDisableSoftReset` (`0x0300001E`). The
`ldrb r1,[r0]` is the compiler spelling of `ldrb r1, [0x03000020]`, keeping the address in a
register. So the whole condition on room loading is:

> **`gUnk_3000020 & 0x80`**

One flag byte, next to `gCurrentPassage` (`0x03000002`) and `gCurrentStageNumber` (`0x03000003`).
This is the first *input-shaped* candidate the mode machinery has produced: it is a byte with a
single bit, in the same block as the passage and stage numbers, and it is the only thing standing
between the observed world and mode 8.

### G19 — the whole room-change chain, end to end

Watching `gUnk_3000020` (with `-AbortMinFrame 400`, because the BIOS clear at `pc=0x00000C08`
marches IWRAM in 4-byte steps and lands on it at vblank 270 — the instrument trap, hit for the
fourth time) found the writer:

```
runtime_trace: mem-write-addr abort pc=0x08072B0C <gf_tfunc_08072B04+0x8>
  addr=0x03000020 value=0x00000080 width=1 (vblanks=8850)
```

and `gf_tfunc_08072B04` is a **set-bit**, not a store — which is why the value filter sees exactly
`0x80` and why `orrs` rather than `movs` matters:

```
08072B04  ldr  r0,[r15,#0x18]   ; 0x03000020
08072B06  ldrb r1,[r0]
08072B08  movs r2,#0x80
08072B0A  orrs r1,r1,r2
08072B0C  strb r1,[r0]          ; gUnk_3000020 |= 0x80
08072B0E  add  r13,r13,#0x4     ; pop {r14} -- a leaf
```

`rom_calls.py` gives the ladder exactly, and the loop closes on itself:

```
gf_tfunc_08072964  --BNE--> gf_tfunc_08072A26        (back edge, at 0x080729E4)
gf_tfunc_08072A26  --B----> gf_tfunc_08072B04        (0x08072A8E, sets the flag)
gf_tfunc_08072A26  --BNE--> gf_tfunc_08072AFC        (0x08072A56)
gf_tfunc_08072AFC  --BNE--> gf_tfunc_08072B04        (0x08072AFE, sets the flag)
gf_tfunc_08072B74  --B----> ... 0x08072B7C BL--> gf_tfunc_08072964   (the loop)
gf_tfunc_080005A4  --BL----> gf_tfunc_08072B98       (the level EXIT, from mode 8's handler)
```

`callchain.py --from 0x08072964` reports **no caller in the graph**, and `--xrefs` finds no 32-bit
literal holding it, so the ladder's head is entered by a computed branch. The trace settles it
(`logs/routes/g19-chain.err.log`, 4096-event dump, `r0=0x00000002` — **a room index**):

```
#31489369 call     0x08006260  r0=0x00000001                  <- state 1
#31489370 dispatch 0x08072B74
#31489372 mem_w    0x08072B7A  addr=0x03001894 value=2         <- requested room
#31489373 call     0x08072B80  r0=0x00000002 r1=0x03001894
#31489374 dispatch 0x08072964  r0=0x00000002 lr=0x08072B81     <- loop back-edge
```

So the full chain, every link measured:

```
state 1 -> gf_tfunc_08006260 -> gf_tfunc_08072B74(1) -> [0x03001894] = 2
        -> gf_tfunc_08072B80 -> gf_tfunc_08072964(2)
        -> gf_tfunc_08072A26 -> gf_tfunc_08072B04 -> gUnk_3000020 |= 0x80
        -> gf_tfunc_08000244(r0=0) -> mode 8, reason 0
        -> table[8] = 0x080005A0 -> coroutine entry 0 = gf_tfunc_0801B908  ** ROOM LOAD **
```

`room = 2` is the attract demo's own transition — Checkpoint 24 timed it at frame 9010, room 0
into room 2 — so this chain is the mechanism the demo walks, and the first time it has been
named end to end. Note `gf_tfunc_08006258/260` has **no `B`/`BL` caller either**: it is itself a
jump-table dispatcher, entered by computed branch, with `gf_autojt_08005F40_07` (0x0800622C) in
the trace one dispatch earlier.

### Still open

The chain is closed and **the head of it is a number, not a button**: `gf_tfunc_080072B74` is
handed the state `1` and turns it into "go to room 2". So G14's question is now one step smaller
and much sharper: **what sets that state to 1**, and is it reachable from a joypad? Nothing here
is a player action yet — every route measured leaves the mode at 0 or 8 — but the whole
mechanism is now known, and the attract demo proves it runs. `gf_tfunc_0801C25A`'s
`cmp r1,#0x8B / bls` spin exit is still unmeasured.

## G20 — OPEN: rooms are linked by a 12-byte exit-record table, and the index that picks the link is a writable IWRAM byte

G19 left one question standing: the ladder's head is the *state number* `1`, and nothing measured
yet was a player action. Two things were needed. First, an input experiment that could fail.
Second — and this is what the round actually turned up — the data structure the game uses to
decide *which room* a transition goes to, which turns out to be a plain ROM table with a
writable index in IWRAM.

### The input experiment, and why its result is a negative worth having

`tests/input/probe-hop-right.keyinput.txt` is 917 rows spanning frames 5300 → 29978, holding
RIGHT essentially throughout (last value `0x03EF`, and `0x03FF & ~0x03EF = 0x10` = RIGHT, the
replay being active-low). Run for 30,000 frames watching `gCurrentRoom` (`0x03000024`) it
aborted at **vblank 11454**, and the 22 events before the write are the known room-change
teardown byte for byte — `0x030000FE/FF/00/01` at `gf_tfunc_0806B864+0x60..0x6A`, then
`0x03000028`, `0x03000025`, `0x0300003E`, `0x0300003A`, `0x0300003C`, then `gSwitchStates[0..4]`
at `0x03000032,31,30,2F,2E`, then `0x03000046`, then:

```
runtime_trace: mem-write-addr abort pc=0x0806B92C <gf_tfunc_0806B90C+0x20>
  addr=0x03000024 value=0x00000000 width=1 (vblanks=11454)
#38564132 ... r0=0x00000000 r1=0x03000024 r3=0x083F2F88 lr=0x0806B41D
```

This is the first room-change event ever produced under host input, and on its face it looks
like the deliverable. **It is not, and the single-variable control says so.**
`tests/input/g20-ctl-noRIGHT.keyinput.txt` is the same 919 rows with `0x10` OR'd into every
value — identical in every respect except the RIGHT bit (901 rows actually changed). It aborts
at **the same frame, from the same PC, with the same value**. So the event is input-independent,
and the reason is visible in the data below: this is the **level load**, not a traversal.

### The exit-record table

`gf_tfunc_0806B90C` is the function that writes `gCurrentRoom`, and its arithmetic is the
structure:

```
0806B910  ldr  r1,=0x0878F21C    ; stage -> record base
0806B912  ldr  r0,=0x03000023    ; gUnk_3000023
0806B914  ldrb r0,[r0]
0806B916  movs r0,r0,lsl #2
0806B918  adds r0,r0,r1
0806B91A  ldr  r3,[r0]           ; r3 = stage record base
0806B91C  ldr  r0,=0x03000025    ; gUnk_3000025   <-- the index
0806B91E  ldrb r1,[r0]
0806B920  movs r0,r1,lsl #1
0806B922  adds r0,r0,r1          ; 3 * index
0806B924  movs r0,r0,lsl #2      ; 12 * index
0806B926  adds r3,r3,r0          ; r3 = &record[index]
0806B928  ldr  r1,=0x03000024
0806B92A  ldrb r0,[r3,#0x1]
0806B92C  strb r0,[r1]           ; gCurrentRoom = record[1]
0806B92E  ldr  r1,=0x03000027
0806B930  ldrb r0,[r3,#0x9]
0806B932  strb r0,[r1]           ; and record[9]
```

`r3 = *(u32*)(0x0878F21C + 4*stage) + 12*[0x03000025]`, and the trace agrees:
`r3=0x083F2F88` with `*(0x0878F21C) = 0x083F2F88`. So the 4-byte table at **`0x0878F21C`** is a
stage → base-pointer table (`0x083F2F88, 0x083F30F0, 0x083F3240, … 0x083F4F38, 0x083F5174,
0x083F5384`), each base addressing an array of **12-byte exit records**, and
**`gUnk_3000025` (`0x03000025`) is the one writable byte that decides which record is used.**

Stage 0's records, read straight out of the ROM at `0x083F2F88`:

```
idx 0: 01 00 1F 1F 10 10 00 00 00 13 A0 02   type 01 = LEVEL ENTRY  -> room 0
idx 1: 02 00 28 28 04 06 18 E0 00 13 00 00
idx 2: 02 01 00 00 03 05 17 20 00 25 00 00   -> room 1,  x = 0x0000  (left seam)
idx 3: 02 01 21 21 08 0A 04 E0 00 25 00 00   -> room 1,  x = 0x2121  (right seam)
idx 4: 02 02 00 00 0C 0E 03 20 00 25 00 00   -> room 2,  left
idx 5: 02 02 21 21 0B 0C 06 E0 00 25 00 00   -> room 2,  right
...
```

`[0]` is the type (`01` the level entry, `02` a room link), `[1]` the destination room, `[2]`/`[3]`
the **x1/x2 cell box**, `[4]`/`[5]` the **y1/y2 cell box**, `[6]` the index to load next, `[9]` a
follow-up index. **Index 0 is the level entry** — which is why the frame-11454 event wrote room 0 and
why RIGHT made no difference to it. A type-2 record is the door *into* room `[1]dest`, not out of the
room you happen to be standing in; record 3 has `dest = 1`, so it is **room 1's** door, and its
`[6]next = 0x04` means "stepping on it loads record 4 (room 2)" — the same transition the attract demo
makes at frame 9010. See the corrected room-0 analysis further down in this section.

### The scanner that picks the record

Twelve references reach `0x03000025`. Exactly two of the referencing functions also reference
`gCurrentRoom`, and one of those two is the whole answer — `gf_tfunc_0806DE8C`:

```
0806DE8C  stm  r13!,{r4,r5,r6,r7,r14}
0806DE8E  movs r2,r0,lsl #16       ; arg0 -> cell
0806DE90  movs r3,r1,lsl #16       ; arg1 -> cell
0806DE92  ldr  r0,=0x03000C3C     ; gSubReason
0806DE96  ldrsh r1,[r0,+r4]
0806DE9A  cmps r1,#0x2
0806DE9C  bne  0x0806df34         ; <-- the gate: reason must be 2
0806DE9E  movs r5,r2,lsr #22
0806DEA0  movs r2,r3,lsr #22
0806DEA2  ldr  r1,=0x0878F21C
0806DEA4  ldr  r0,=0x03000023
0806DEA6  ldrb r0,[r0]
0806DEAC  ldr  r4,[r0,r1]         ; stage record base
0806DEAE  b    0x0806df2e
0806DEBC  movs r6,#0x0
0806DEBE  cmps r0,#0x1 / 0806DEC0 beq 0x0806DED0
0806DEC2  cmps r0,#0x3 / 0806DEC4 beq 0x0806DED0
0806DEC6  cmps r0,#0x4 / 0806DEC8 beq 0x0806DED0
0806DECA  cmps r0,#0x5 / 0806DECC bne 0x0806df2c     ; only types 1, 3, 4, 5
0806DECE  movs r6,#0x1
0806DED0  ldr  r1,=0x03000024
0806DED2  ldrb r0,[r4,#0x1]
0806DED4  ldrb r1,[r1]
0806DED6  cmps r0,r1
0806DED8  bne  0x0806df2c         ; record[1] must be the room we are in
0806DEDA  ldrb r0,[r4,#0x2] ; cmps r0,r2 ; bhi 0x0806df2c
0806DEE0  ldrb r0,[r4,#0x3] ; cmps r2,r0 ; bhi 0x0806df2c
0806DEE6  ldrb r0,[r4,#0x4] ; cmps r0,r5 ; bhi 0x0806df2c
0806DEEC  ldrb r0,[r4,#0x5] ; cmps r5,r0 ; bhi 0x0806df2c   ; ...inside the box
0806DEF2  ldr  r1,=0x03000025
0806DEF4  ldrb r0,[r4,#0x6]
0806DEF6  strb r0,[r1]            ; *** gUnk_3000025 := record[6] ***
0806DEF8  movs r0,#0x3
0806DEFA  strh r0,[r7]            ; gSubReason := 3
0806DF16  ldr  r1,=0x03000C37     ; only for type 5
0806DF18  movs r0,#0x1
0806DF1A  strb r0,[r1]
0806DF2C  adds r4,r4,#0xc         ; next record
0806DF2E  ldrb r0,[r4] ; cmps r0,#0 ; bne 0x0806debc
0806DF34  ldm  r13!,{r4,r5,r6,r7} ; ...return
```

So the whole traversal rule fits in one paragraph: **each frame, while `gSubReason == 2`, walk the
current stage's exit records; take one whose type is 1, 3, 4 or 5, whose `[1]` is the room Wario
is in, and whose `[2]..[5]` bounding box contains his cell; write that record's `[6]` into
`0x03000025` and set the reason to 3.** The room load then reads the index G19 traced, and
reason 3 is the coroutine resume point that performs it.

### The axis order, settled from the caller and not from plausibility — RESOLVED 2026-10-07

This was flagged above as the one detail that had to come from the caller rather than from reading
the record data, and it is now settled that way.

`rom_calls.py --target 0x0806DE8C --why` reports **exactly one** call site: `0x0801BAAE BL` inside
`gf_tfunc_0801BA9C`.

```
0801BA9C  ldr  r0,=0x03000C3C ; ldrsh r0,[r0] ; cmps r0,#0x2 ; bne 0x0801BB4C   ; the same gate
0801BAA6  ldr  r0,=0x03001892 ; ldrh r0,[r0]        ; arg0
0801BAAA  ldr  r1,=0x03001890 ; ldrh r1,[r1]        ; arg1
0801BAAE  bl   0x0806DAB2                          ; -> gf_tfunc_0806DE8C(arg0, arg1)
```

`gf_tfunc_0801BA9C` has **no entry in any pointer table and no B/BL or tail caller**, which looked
like a contradiction until the resume table was located (below): it is reached by falling through
out of reason 4's one-instruction resume stub.

What makes it decisive is who writes the two argument cells. Each has exactly five literal
references, and three of the five are copies out of Wario's own record:

```
08013556  ldr  r2,=0x03001890 ; ldr r1,=0x030018D4 gWarioDataCopy
0801355A  ldrh r0,[r1,#0x12] ; 0801355C  strh r0,[r2]                  ; 0x03001890 := gWarioData.xPosition
0801355E  ldr  r2,=0x03001892 ; 08013560  ldrh r0,[r1,#0x14] ; subs r0,r0,#0x80
08013590  strh r0,[r2]                                              ; 0x03001892 := gWarioData.yPosition - 0x80
```

and the `+0x12`/`+0x14` offsets are themselves confirmed from the ROM's own room loader rather than
assumed:

```
0806BA3E  movs r1,r1,lsl #6        ; record[2] << 6
0806BA42  ldrsb r0,[r3,+r0] ; adds r0,#0x8 ; movs r0,r0,lsl #2
0806BA4A  strh r1,[r4,#0x12]       ; gWarioData.xPosition
0806BA4C  movs r1,r2,lsl #6
0806BA50  ldrsb r0,[r3,+r0] ; movs r0,r0,lsl #2 ; adds r1,r1,r0 ; subs r1,r1,#0x1
0806BA58  strh r1,[r4,#0x14]       ; gWarioData.yPosition
```

So `arg0 = *(u16*)0x03001892 = y - 0x80` and `arg1 = *(u16*)0x03001890 = x`, which makes `r5 =
arg0 >> 6` the **y** cell and `r2 = arg1 >> 6` the **x** cell — therefore **`record[2]/[3]` bounds x
and `record[4]/[5]` bounds y**, the reading the record data suggested. Room 0's right exit (record 3,
`02 01 21 21 08 0A 04 E0 00 25 00 00`) therefore needs **x cell exactly 0x21 = 33, i.e.
x ∈ [2112, 2175]**, with **y ∈ [640, 832]**.

`symbols/iwram_map.tsv` has no name for either cell; both are `gUnk_3001890` / `gUnk_3001892`,
size `0x2`, sitting between `0x0300188e gUnk_300188E` and `0x03001894 obj/demo_input.o(iwram_data)`.

### The gate is PULSED, not shut — this corrects the previous version of this section

The previous text concluded from five IWRAM snapshots that the gate was shut across the whole
crossing window. **That conclusion was wrong, and it was wrong because snapshots sample and the
gate is a pulse.** `logs/routes/obs-g20-exit/` shows `reason=0` at frames 11,500 / 12,000 /
13,001 / 14,001 / 15,501 — but that only says the gate was shut at those five instants. A
value-filtered watchpoint with `-AbortMinFrame 6000`, which fires on the *recurrence* rather than
on a sampled instant, aborts **inside** the crossing window:

```
runtime_trace: mem-write-addr abort pc=0x08079AD4 <gf_tfunc_08079AD0+0x4>
  addr=0x03000C3C value=0x00000002 width=2 (vblanks=8915)
```

So reason 2 is re-entered while Wario is walking. There are **at least two publishers**, and
neither is reason-specific code:

```
08079AD0  ldr  r1,=0x03000C3C ; movs r0,#0x2 ; strh r0,[r1]      ; reason := 2
08079AEC  ldr  r1,=0x03000C3C ; movs r0,#0x3 ; b 0x08079fba      ; and reason := 3
```

`gf_tfunc_080919B0`, the publisher seen at vblank 5,429, is a **generic setter** — `strh r0,[r1]`
and a call to `0x080009C2` — reached by a tail branch from seven sites inside one generated
function: `0x08091898` (`movs r0,#5`), `0x080918E6` (`movs r0,#3`, the traversal), `0x080918F8`
(`movs r0,#4`), `0x08091952` (`movs r0,#6`), and `0x0809182C` / `0x0809197E` / `0x0809199A`, which
all do `ldrh r0,[r1] / adds r0,#1` and therefore **advance the reason as a tick counter**.
**There is no `movs r0,#0x2` anywhere in that function**: reason 2 arrives through the increment
sites, not as a literal request.

### The scanner cannot be what drives room 0's exits — three independent reasons

The resolution that matters most is not a timing detail. The scanner `gf_tfunc_0806DE8C` accepts
record **types 1, 3, 4 and 5 only** — its type test at `0x0806DEBE..0x0806DECC` rejects anything
that is not one of those four — and **room 0's left and right exits are type `02`**. The scanner
walks straight past them. On top of that, its inputs are stale:

* `rom_calls.py --xrefs --target 0x03001890` and `--target 0x03001892` give exactly **five**
  literal references each. Three of them (`0x0801354C`, `0x080137C2`, `0x08016830`) copy
  Wario's position into those cells, and **all three begin by storing `4` into `gSubReason`**
  (`movs r0,#4 / strh r0,[r1]`, then the two `strh`s into `0x03001890` / `0x03001892`). They are
  arms of a reaction dispatch — one of them clears `gCurrentCarriedSprite`, another sets
  `gCurrentWarioEffect` to 5 — **not** a per-frame position feed.
* Measured, with a plain address watch over the whole 30,000-frame RIGHT-hold route and
  `-AbortMinFrame 3000`: **`0x03001890` is never written at all.** Its only write in the entire
  run is the boot zero-fill, at vblank 2, `pc=0x00000C08`, `width=4`. A 13,000-frame run with
  `-AbortMinFrame 11400` likewise never fires. So in this route the scanner's x argument is 0
  forever and no bounding box can ever be satisfied.
* And the index it would write is never written either: a plain address watch on `0x03000025`
  over the same 30,000 frames aborts exactly once, at the level-load teardown —
  `pc=0x0806B8E6 <gf_tfunc_0806B864+0x82> addr=0x03000025 value=0x00000000 width=1 (vblanks=11454)`.

**This is a much better-posed question than the gate was.** The mechanism that walks room 0's
type-`02` exits has not been found, and it is not this scanner. See **G22**.

### What does gate the level-re-entry path

`gf_tfunc_08000518` does look like a traversal request — it writes the exit index and sets the
reason — but decoding the block above it shows it is not one:

```
080004D6  ldr  r2,=0x03000C35 gUnk_30000C35
080004DA  ldrsb r1,[r2]         ; the selector, read SIGNED
080004DC  cmps r1,#0x2
080004DE  beq  0x08000500       ; mode 2 -> the block below
080004E4  cmps r1,#0x1 / beq 0x080004F6      ; mode 1 -> reason := 2
080004F0  cmps r1,#0x3 / beq 0x08000534      ; mode 3 -> another path
080004E8  b    0x08000630       ; anything else -> bail

08000500  ldr  r0,=0x03000022 ; ldrb r1,[r0] ; cmps r1,#0x0 ; beq 0x08000518
08000518  ldr  r0,=0x03000025 ; strb r1,[r0]        ; exit index := r1
0800051C  ldr  r1,=0x03000C3A ; movs r0,#0x1 ; strh r0,[r1]
08000522  ldr  r1,=0x03000C3C ; movs r0,#0x15 ; b 0x0800062E   ; reason := 21
```

**`ldrb r1,[r0]` at `0x08000502` destroys the incoming `r1`,** so the value stored into
`0x03000025` at `0x0800051A` is not the caller's argument at all — it is `[0x03000022]`, which the
`beq` has just proven is **zero**. So this path writes **exit index 0**, and index 0 is the LEVEL
ENTRY record. It is a **level re-entry request, not a door traversal** — and the reason it asks
for, `0x15` = **21**, lies outside the nine reasons the earlier resume sweep covered.

Its gate is healthy: `0x03000022`'s only write after frame 3,000 is the level-load clear at
vblank 11,453 (`pc=0x0801C1FE <gf_tfunc_0801C1E6+0x18>`, value 0, width 1), so the byte is 0
throughout the walk and the `beq` would be taken. The gate that is **not** taken is the mode
selector: `0x03000C35`'s first write after frame 3,000 is `0` at vblank 5,419, from
`pc=0x08090C58 <gf_tfunc_08090C20+0x38>` with `r1=0x04000052` and `r4=0x040000D4` (`REG_DMA3SAD`)
in registers — the mode-8 setup — and mode 0 falls through to the `bail` branch.

### Still open

* **The type-`02` traversal mechanism is unidentified (now G22).** `gf_tfunc_0806DE8C` skips type
  `02`; the player-facing room links are all type `02`; nothing in 30,000 frames of a RIGHT hold
  writes `0x03000025` except the level-load teardown.
* **The mode selector `0x03000C35` never reaches 2 in that route.** A value-filtered watch for `2`
  over the same 30,000 frames is the test; whatever is supposed to set it to 2 is the next lead.
* Drive the crossing deliberately and watch for a **new** `gCurrentRoom` value — the acceptance
  test is a transition to a room we were not in, with the single-variable control showing the
  same route without RIGHT does not do it.
* Record types 3, 4 and 5 are accepted by the scanner but do not appear in the first five
  stage-0 records; what they mean is unexamined.
* Reasons outside 0–8 exist. `0x15` = 21 is requested by the level re-entry path, so the resume
  table's nine entries are not the whole reason space.

## G21 — OPEN, high priority: every Thumb literal-load offset in this ROM is decoded two different ways, and the two of our own tools agree with each other

This is not a tool bug report. It is an unresolved disagreement between the cartridge image and
the recompiled code, recorded here because it was found and because its consequences are large
enough that pretending it is settled would be worse than leaving it open.

**The observation.** The ROM contains 13,118 Thumb `ldr rX,[r15,#imm]` sites. At **every one of
them** the immediate printed in the generated C++ disagrees with the imm8 the image encodes. The
relationship is exact and universal: **comment = ROM imm8 × 4.** Not 13,117 of 13,118 — all of
them, and always by the same factor.

Worked example, the mode setter G16–G19 spent three rounds on:

```
ROM 0x08000278 : 02 49            -> halfword 0x4902, imm8 = 0x02
strict ARMv4T  : Align(PC,4)+imm8 = 0x0800027C + 2 = 0x0800027E  -> the word there is 0x80084902
x4 convention  : 0x0800027C + 8   = 0x08000284                   -> the word there is 0x03000C3A
```

`0x03000C3A` is `gSubGameMode`, and the pool's other word at `0x08000288` is `0x03000C3C`,
`gSubReason` — the two addresses the entire mode/reason chain of G16–G20 runs on. The strict
reading lands on an *unaligned halfword address holding a non-pointer*, which is not something a
shipping game can execute; the ×4 reading lands exactly on the literals the surrounding code
obviously means. `gf_tfunc_0806B90C` is the same story: ROM halfword `0x4827` (imm8 `0x27`) versus
the C++'s `#0x9c`, pool `0x0806B9AC` = `0x03000046`, which the trace confirms
(`mem_w pc=0x0806B90E addr=0x03000046`).

**The running guest agrees with the ×4 reading.** `generated/cart/recompiled_000.cpp:1315` emits
`uint32_t _base_08000278 = 0x0800027Cu & ~3u; _off_08000278 = 0x00000008u;`, and the live trace
shows the guest storing to `0x03000C3A` exactly as that predicts. So the recomp is internally
consistent with the ×4 convention, and the game demonstrably runs.

**Why it is still open.** Because two artefacts disagreeing with a third, when two of the three
are ours, is not a two-against-one vote (rule 46). The three statements on the table are:

1. the generator's comment is right and the ROM image does not encode what the hardware reads;
2. both decoders are wrong and **every literal load in the build reads the wrong word**;
3. the ROM is right and the mismatch is in how the image is being read.

(2) would invalidate the build. Nothing so far distinguishes them, because everything measured
has been measured *through* the ×4 convention. The third-party decomp was consulted as an
independent arbiter and contains **neither** a `0x03000c3a` literal **nor** any disassembly of
`0x08000278`, so it did not arbitrate. **This is why nothing in G16–G20 was re-run on the basis
of the ×4 reading**: the round's structural results — the 12-byte record array, the exit index,
the stage table, the mode/reason chain — come from reading the ROM's *data* plus addresses the
trace confirms were executed, and all of those hold under either reading.

**Handled, not swept under the rug.** `tools/validation/func_dump.py` (new this round) prints a
`!! G21:` line at *every* site where the two encodings disagree, rather than silently choosing
one, and its self-test asserts that the disagreement is **detected** — never which side is right.
A self-test that encoded the open question as its expected value would convert the question into
a fact the moment it was written down. Its two address checks are pinned to the guest instead:
`0x0806B90C → 0x03000046` and `0x0806B928 → 0x03000024` are both values the trace shows the CPU
actually holding, so the tool is checked against the artefact that runs.

**What would settle it.** A source of truth outside this project: a disassembly of `0x08000278`
from a toolchain that implements ARMv4T literally, or a hardware reading of the literal pool. The
machine has no WSL and installs none, and `arm-none-eabi-objdump` is absent, so both are
currently unavailable. Until one exists, this stays open.

## G22 — RESOLVED 2026-10-08: the room change is triggered by the player's HAMMER at the room-0 switch, and `gSwitchPressed` is the whole of it

**Round 31 closed the acceptance test.** The traversal is not requested by Start, and the last
missing byte is not missing at all:

```
g31-room  (tests/input/g31-hammer.keyinput.txt, 30000 frames, RIGHT held, A held frames 12000-12250)
ABORT pc=0x0806B92C <gf_tfunc_0806B90C+0x20> addr=0x03000024 value=0x00000002 r3=0x083F312C
```

`gCurrentRoom 0 → 2`, written by the room loader, caused by **host input**, with a single-variable
control (`probe-hop-right`, identical but for the 250 frames of A) that never produces the write.
Axis G's acceptance test is met.

The mechanism is `gSwitchPressed 0x03000C0D`, and **the reference decomp
`third_party/lilDavid-warioland4` is on disk and names every variable involved.**

* `func_802B694` (`asm/sprite_ai/disasm_switch.s:210`) is the only writer of `gSwitchPressed`. It
  is reached only from `SpriteSwitch` **pose 17**, an *armed* pose. Both intro paths end at pose 16,
  which has **no dispatch arm at all**.
* `SpriteWarioEnteringVortex` (`src/sprite_ai/vortex.c`) sets `gSubGameMode 0x03000C3C := 6` once
  `gCollectedKeyzer != 1`, and `GameScreenSubroutine` case 6 (`src/game_screen.c:110`) calls the
  stage-end handler. **The vortex requests the traversal; the switch lets it happen.**
* Pose 17 is armed by Wario's **hammer (button A)** at the switch. That is the only player input
  in the chain.

Four rounds have now established the shape of a room transition — the 12-byte record array at
`0x0878F21C + 12*index`, the writable index at `0x03000025`, and the loader `gf_tfunc_0806B90C`
that consumes it — and all three describe the **room 0 → room 2** link the attract demo performs at
frame 9010. Rounds 27–30 searched for the missing *write*; round 31 established that the write was
never missing, and the route had simply never put the player in front of the switch with the button
that arms it.

**The candidate is dead, on its own decode.** `gf_tfunc_0806DE8C` gates on `gSubReason == 2`, then
tests the record's type against 1, 3, 4 and 5:

```
0806DEBE  cmps r0,#0x1 / 0806DEC0 beq 0x0806DED0
0806DEC2  cmps r0,#0x3 / 0806DEC4 beq 0x0806DED0
0806DEC6  cmps r0,#0x4 / 0806DEC8 beq 0x0806DED0
0806DECA  cmps r0,#0x5 / 0806DECC bne 0x0806DF2C     ; <-- type 02 falls straight through
```

Every player-facing link in stage 0 is **type `02`** — the left and right exits of rooms 0 through
7 are all `02`, and only record 0 (the level entry) is `01`. The scanner is structurally incapable
of selecting any of them.

**Its inputs cannot fire either.** The scanner's two arguments come from `0x03001890` and
`0x03001892`, which the axis-order work in G20 established are Wario's `x` and `y - 0x80`. Those
two cells have exactly five literal references each, three of which copy Wario's position in, and
all three sites open with `movs r0,#4 / strh r0,[0x03000C3C]` — they are arms of a *reaction*
dispatch, entered when an action sets the coroutine to reason 4, not a per-frame position feed.
Measured: a plain address watch on `0x03001890` over the whole 30,000-frame RIGHT-hold route with
`-AbortMinFrame 3000` never aborts. Its only write in the run is the boot zero-fill at vblank 2,
`pc=0x00000C08`, `width=4`. So in that route the scanner sees `x = 0` and cannot match a box.

**And nothing asks for a transition.** A plain address watch on `0x03000025` over the same
30,000 frames aborts exactly once, at the level-load teardown:
`pc=0x0806B8E6 <gf_tfunc_0806B864+0x82> addr=0x03000025 value=0x00000000 width=1 (vblanks=11454)`.
No traversal index is ever requested, so the mechanism that would write one is never reached.

**What the other twelve references to `0x03000025` turned out to be.** There are twelve, and this
round decoded the interesting ones:

* `gf_tfunc_0806DE8C` (`0x0806DE70`, `0x0806DF24`) — the scanner, two writes of `record[6]`.
* `gf_tfunc_0806B90C` (`0x0806B998`) — the loader, which **reads** the index.
* `gf_tfunc_08000518` (`0x08000518`) — writes `[0x03000022]`, which is provably **0** on the path
  that reaches it, i.e. **exit index 0**, the level-entry record. A level re-entry request, not a
  traversal. Its gate, `[0x03000022] == 0`, is satisfied throughout the walk.
* `gf_tfunc_08072B74` / `gf_tfunc_08072964` / `gf_tfunc_08072B24` / `gf_tfunc_08072AAC` /
  `gf_tfunc_08072B68` — the **attract demo**, see G23.
* `gf_tfunc_0801C32E+0x72`, `gf_tfunc_0806FF2C+0x8`, `gf_tfunc_080732C8+0x14`,
  `gf_tfunc_08073744+0x12` — all **read** it, in the mode dispatcher and in the input/DMA helpers.

So the twelve references contain **exactly two** writers, and neither can select a type-`02` link.

### Round 29 — the trigger, the gate, and the missing write

**The traversal trigger is `gf_tfunc_0801C2D0`, and it fires on host input.** It claims a
"transition in progress" latch and, if three conditions hold, opens a 1000-frame global gate:

```
0801C2C0  r4 = (s8)[r5]                  ; r5 = 0x03000C3F, the in-progress latch
0801C2C4  if != 0 -> bail
0801C2D0  [0x03000C3F] := 1
0801C2D8  gWarioPauseTimer (0x030019F6) := 0
0801C2DC  gDisableWario    (0x030019F8) := 0
0801C2DE  if gHasTemporarySave (0x03000012) != 0 -> bail
0801C2E6  if gUnk_3000025    (0x03000025) != 0 -> bail    ; a link is ALREADY pending
0801C2F0  gTimerState (0x03000047) := 0
0801C2F8  if gCurrentPassage (0x03000002) == 0 and gCurrentStageNumber (0x03000003) == 2 -> bail
0801C304  if gCurrentStageNumber == 4 -> bail
0801C30E  gWarioPauseTimer := 0x3E8      ; *** 1000 ***
0801C310  gDisableWario := 1             ; *** input locked ***
```

Note `0x0801C2E6`'s polarity: a **non-zero** exit index makes the trigger *bail*. This function
**starts** a transition; the pending index is what makes one unnecessary.

Measured in `g22-disable` (30,000 frames, RIGHT held, watch `0x030019F8 == 1` from frame 2000), it
fires at **vblank 11457**:

```
mem_w pc=0x0801C2D2 addr=0x03000C3F value=0x00000001   ; latch claimed
mem_w pc=0x0801C2F0 addr=0x03000047 value=0x00000000   ; both bail conditions passed
mem_w pc=0x0801C30E addr=0x030019F6 value=0x000003E8   ; gWarioPauseTimer := 1000
mem_w pc=0x0801C310 addr=0x030019F8 value=0x00000001   ; gDisableWario := 1
```

11457 is three frames after the level load at 11454, so this is the **level-entry** transition.
Its tail is register setup (`BG2CNT := 0x3E41`, `BG1CNT := 0x5F00`) plus a call to
`gf_tfunc_0801BC0D`, which is an **OAM sprite-DMA** routine, not the room load.

**The 1000-frame pause is a global logic gate, not a delay.** `gf_tfunc_0801BA18` decrements it, and
**eight** sites early-out while it is non-zero: `0x0801B964`, `0x0801D14A`, `0x0801D69E`,
`0x0806FA64`, `0x08070EDC`, `0x08070EEC`, `0x0807493A`, and the `gf_tfunc_0801BA5C` chain. The one
sitting in the exit-record region (`0x0806FA64`) turns out to be the heart-meter HUD updater.

**After the gate opens, nothing asks for a traversal.** Two plain address watches over the live
window, both on the RIGHT-hold route:

| tag | watchpoint | result |
|---|---|---|
| `g22-roomany` | `0x03000024` (`gCurrentRoom`), any write, `min_frame 12000` | `exit=0`, **never written** |
| `g22-exitidx` | `0x03000025`, any write, `min_frame 12500` | `exit=0`, **never written** |

So the chain terminates in a precisely named gap: the trigger fires, the gate opens, Wario walks,
and the single instruction group that would write a non-zero exit index is never executed.

**The complete writer census of `0x03000025` is now closed** — six writers, six readers, all twelve
literal references attributed to the instruction that performs the load. Only one writer can emit a
non-zero value, and it is the scanner.

**The mode-byte path is structurally unreachable, and this is provable without running anything.**
`0x080887EA` is the only site in the ROM that can write the traversal selector `0x03000C35 = 2`. It
is handler #7 of the 8-way table at `0x080886A8`, indexed by `gUnk_3004770 0x03004770` (bounds ≤ 7).
That byte has exactly **three** literal references — one read, two writers:

* `gf_tfunc_080871E6` is **not** a setter but a room-script **initialiser**: its entry is
  `movs r2,#0x0 / strh r2,[r0]` and `0x08087246` writes that `r2` unconditionally every call.
* `gf_autojt_080875B8_04` at `0x0808774E` is
  `ldrh r0,[r5] / adds r0,r0,#4 / movs r1,#0xff / ands r0,r0,r1 / strh r0,[r5]`
  — `state = (state + 4) & 0xFF`. A **+4 increment**, not the masked rotate the raw sequence
  suggests at a glance.

**Therefore `gUnk_3004770` is always a multiple of 4, so only handlers #0 and #4 can ever run**, and
neither requests anything: **#0** is a bare tick (`ldrh r0,[r1] / adds r0,#1 / b 0x08088816`) and
**#4** is a frame counter (increments `[0x03004790]`, and past `0x1E` increments a second counter).
Handler #7 cannot run, so the whole `0x03000C35` → reason-21 path is dead for host input. The
runtime probe only confirms it: `g22-state7`, 30,000 frames, `0x03004770 == 7`, `exit=0`, no abort.

**Also found this round.** A **second** coroutine dispatcher, `gf_tfunc_0801BBA8`, reads the same
`gSubReason 0x03000C3C` and computes a branch through a table at ROM **`0x0801BBC8`** (reasons 0, 1,
3 → `0x0801BBE4`; reasons 2, 4, 5 and anything above 6 → `0x0801BBFC`; reason 6 → `0x0801BBF0`). Both
of its reachable targets (`0x0801BEA9`, `0x0801BC0D`) are **OAM sprite-DMA** routines, so the outer
nine-entry table at `0x0801B8E4` is not the only reason dispatch. And `0x03000C37` — inside
`obj/main.o(iwram_data)`, which is why it has no symbol — is set to 1 by the scanner **only when the
matched record's type is 5**, and read signed by `gf_tfunc_080003E4`, which turns it into reason 7.

### Round 30 — `0x03001848` is the joypad word, and the button was Start

**The census came first.** `0x03001848` has 106 literal-load sites; walking each load
forward for a `strh`/`strb` through the loaded register gives **10 candidate stores**, and
exactly two of them set bit `0x8`:

* `gf_tfunc_080102F8` — `if (gDemoSequenceIndex <= 0xFD) -> the recording arm; else
  [0x03001848] := 8`.
* `gf_tfunc_08010380` — `if (gDemoSequenceIndex > 0xFD)`, `if (gDemoButtonPressTimer ==
  0xFFFF)` or `if ([0x03001844] == 0)` → `[0x03001848] := 8`.

Both live in the attract demo's **input recorder and input player**, alongside
`gDemoInputs 0x03002CC8`, `gDemoInputLengths 0x03002EC8`, `gDemoSequenceIndex 0x030030C8`,
`gDemoButtonsPressed 0x030030CC`. The player's ordinary arm writes the whole edge word at
`0x080103D8..0x080103E2` with `eors r0,r0,r1 / ands r0,r0,r1` — the GBA keyinput idiom.

**`REG_KEYINPUT 0x04000130` has exactly one literal-load site**, `0x08000956`, so
`gf_tfunc_08000954` is the single point at which host input enters the game:

```
08000956  ldr r0,=0x04000130 ; ldrh r0,[r0]        ; raw, ACTIVE LOW
0800095A  ldr r2,=0x000003FF ; bics r1,r1,r0       ; HELD = 0x3FF & ~raw
08000962  ldr r3,=0x03001846 ; ldrh r2,[r3]
08000966  adds r0,r1,#0x0   ; bics r0,r0,r2       ; PRESSED = HELD & ~prevHELD
0800096A  strh r0,[r4]                            ; -> 0x03001848
0800096C  strh r1,[r0]                            ; 0x03001844 := HELD
08000970  strh r1,[r3]                            ; 0x03001846 := prevHELD
```

Three previously anonymous IWRAM words are named: `0x03001844` held, `0x03001846` previous
held, `0x03001848` pressed-this-frame. On the keyinput register bit `0x8` is **Start**
(`0x01` A, `0x02` B, `0x04` Select, `0x08` Start, `0x10` Right); four other sites test the
constant `0x9` — A or Start, the menu confirm pair — at `0x08003942`, `0x08005BE2`,
`0x08006440`, `0x0800B192`.

**Every replay in `tests/input/` holds Right and taps A.** `probe-hop-right.keyinput.txt`
is 449 rows of `0x03EE` (A + Right), 452 of `0x03EF` (Right), and exactly **one** Start row
(`0x03F7`) at frame 5300, before any level. The requester's button was never pressed inside
a level.

**Two replays, one changed variable each.** `tests/input/g30-start-tap.keyinput.txt` swaps
only the tapped bit, `A (0x01) -> Start (0x08)`; it mashes Start 449 times and the game
bounces back to the title screen (`interpreted_insns=1307982`). 
`tests/input/g30-start-once.keyinput.txt` holds Right continuously and taps **Start for one
frame at 12600**, after the level load at 11454 and after the 1000-frame
`gWarioPauseTimer` gate expires.

| probe | tag | result |
|---|---|---|
| `0x03001848 == 8`, min 12000 | `g30-start8` | **ABORT** `pc=0x0800096A <gf_tfunc_08000954+0x16> addr=0x03001848 value=0x00000008`, `r1=0x18` held / `r2=0x10` prev / `r0=0x08` edge |
| `0x03001848 == 8`, RIGHT only (control) | `g30-flag1848`, `obs-g30-flag` | 2 writes, both 0; 13 snapshots over 17,500 frames all `bit3=False` |
| any write to `gSubReason 0x03000C3C` | `g30-once-reason` | **ABORT** `pc=0x0801B9D6 <gf_tfunc_0801B9D0+0x6> value=0x00000003` |
| `gSubReason == 2` | `g30-once-reason2` | **ABORT** `pc=0x0801B948 <gf_tfunc_0801B942+0x6> value=0x00000002` |
| `gSubReason == 4` / `== 7` | `g30-once-reason4`, `g30-start-reason7` | `exit=0`, never fires |
| any write to `gCurrentRoom 0x03000024` | `g30-once-room` | `exit=0`, never fires |

**The dispatch had been read backwards.** The ROM is:

```
0801B974  ldrb r0,[0x0300001B gUnk_300001B] ; cmps r0,#0 / beq 0x0801b9d0
0801B97C  ldrb r0,[0x03001894 obj/demo_input.o] ; cmps r0,#0 / bne 0x0801b9d0
0801B984  gTimerState 0x03000047 ; if == 1 -> 0x0801b99a
0801B98C  (gCurrentRoom 0x03000024 | gSwitchStates[1] 0x0300002F) ; if != 0 -> skip
0801B99A  gSubReason 0x03000C3C := 7 ; [0x0300001A] := 1
0801B9D0  gSubReason := gSubReason + 1 ; [0x03000C35] := 1 ; bl 0x0806B9E2
```

Because `0x0300001B == 0`, the observed arm is the second one: reason 2 → 3, mode selector
1, and **`bl 0x0806B9E2` — inside the room loader `gf_tfunc_0806B90C`**. Mode 1 then reaches
`gf_tfunc_080004CC` at `0x080004F6`, which sets `gSubReason := 2`, and `gf_tfunc_0801B942`
increments it once more. Before this round `gSubReason` was **never written at all** after
frame 12500 in 30,000 frames of Right-hold.

### Round 31 — the switch, the hammer, and the room change (RESOLVED)

**The experiment.** `tests/input/g31-hammer.keyinput.txt` is `probe-hop-right`'s RIGHT-hold plus
**A held for frames 12,000–12,250**. The reasoning is one line long and was three rounds late:
`probe-hop-right`'s 449 A-frames are frames 5,300–5,749, and Wario is still ~1,000 pixels from the
switch when they end — he arrives around frame 11,600. The hammer was never swung *at* anything.

**What it produced**, in order (`-TraceDumpDepth 2048`, watchpoint on `gSwitchPressed`):

```
#65640379 dispatch pc=0x08072B74 <gf_tfunc_08072B74+0x0> r0=0x1 r1=0x1 r3=0x03000C3C lr=0x08006261
#65640381 mem_w    pc=0x08072B7A addr=0x03001894 value=0x00000002
#65640383 dispatch pc=0x08072964 <gf_tfunc_08072964+0x0>
#65640395 mem_w    pc=0x0807299C addr=0x03000002 value=1   gCurrentPassage
#65640397 mem_w    pc=0x080729AA addr=0x03000025 value=5   ★ the exit-record index
#65640398 mem_w    pc=0x080729C4 addr=0x03000004 value=1   gCurrentStageID
#65640401 mem_w    pc=0x08072A28 addr=0x03000C35 value=0   gPauseFlag
#65640403 mem_w    pc=0x08072A30 addr=0x03000C0D value=0   gSwitchPressed cleared
```

`lr=0x08006261` ties the entry point back to `gf_tfunc_08006258/260`, the instruction this goal
opened on in round 27. The round-29 chain ("state 1 → `gf_tfunc_08006260` → `gf_tfunc_08072B74(1)`")
**is** the switch-press chain, and it fires. The room write then follows, after the usual teardown
(`gf_tfunc_0806B864` zeroes `0x030000F8..0x03000101` and `0x03000028`; `gf_tfunc_0806B8E8` zeroes
`0x0300003E/3A/3C`; `gf_tfunc_0806B8FA` zeroes `gSwitchStates[0..4]` at `0x0300002E..0x03000032`),
at `gf_tfunc_0806B90C+0x20`.

**The controls, which are the part that makes it a result:**

| tag | replay | watchpoint | outcome |
|---|---|---|---|
| `g31-switchp` | RIGHT only | any write `0x03000C0D`, min 11,500 | `exit=0` — never written |
| `g31-mode6` | RIGHT only | `0x03000C3C == 6`, min 11,500 | `exit=0` — never reached |
| `g31-hammer` | **+ A** | any write `0x03000C0D`, min 11,500 | **ABORT** |
| `g31-room` | **+ A** | any write `0x03000024`, min 11,500 | **ABORT**, `value=0x00000002` |

One changed variable, two opposite outcomes.

**`gUnk_300001B 0x0300001B` — the byte four rounds were chasing — is dead code for this path.**
`g31-unk1b` (any write, `min_frame 0`) aborts at `pc=0x00002D68` → `pc=0x00002D6C`, with
`r3=0x0300000C` and `r2=0x78`: a **boot-time 16-byte-stride block clear** running from `0x0300000C`
across the head of the IWRAM variable bank. The byte is only ever *cleared*, never set. The
round-30 reading — "the traversal needs `0x0300001B != 0`" — was true of the reason-7 arm of
`gf_tfunc_0801B958` and irrelevant to the traversal, because that function is not what requests it.

### Vocabulary this round invalidated

`third_party/lilDavid-warioland4/src/main.c:29-41` fixes the `obj/main.o(iwram_data)` blob:

* **`0x03000C3C` is `gSubGameMode`, not a "reason".** The 9-entry resume table at `0x0801B8E4` is
  the `switch (gSubGameMode)` of `GameScreenSubroutine` (`src/game_screen.c:30`). Round 30's
  "reason 7" is `case 7:` = `BossPause()`. The exit scanner `func_806DE8C` lives in `case 4:`
  **guarded by `if (gSubGameMode == 2)`** — unreachable from inside its own case, which is why
  the scanner was never the answer.
* **`0x03000C35` is `gPauseFlag`,** not a mode selector; every write catalogued for it in rounds
  27–28 was a pause-flag write.
* **`0x03001848` is `gButtonsPressed`** — confirmed a second time, independently, by
  `src/game_screen.c:60`: `CHECK_KEYS_ALL(gButtonsPressed, START_BUTTON)`.

All three are now in `symbols/iwram_map.tsv`, which previously carried only the opaque
`obj/main.o(iwram_data)` blob row for the whole region.

### Round 32 — the traversal is two hops, not one, and it is now a permanent smoke case

The round-31 evidence was a single correct line and a sentence built on top of it that was
correct only by accident:

```
pc=0x0806B92C <gf_tfunc_0806B90C+0x20> addr=0x03000024 value=0x00000002
```

`-AbortMemAddr` stops at the **first** hit. Enumerating the variable afterwards:

| probe | filter | first hit |
|---|---|---|
| `g32-roomw-first` | any value, `min_frame 0` | `pc=0x00000C08 addr=0x03000024 value=0` — the native IWRAM block clear (event #102,629) |
| `g32-room-zero` | value `0`, `min_frame 100` | `pc=0x00000C08 addr=0x03000024 value=0` — the **same** clear runs twice (event #1,436,019) |
| `g32-roomw-6000` | any value, `min_frame 6000` | `pc=0x0806B92C addr=0x03000024 value=0x00000002 r3=0x083F2FB8` |
| `g32-room-v2` | value `2` | the same event #31,513,451 |
| `g32-room-v6` | value `6` | `pc=0x0806B92C addr=0x03000024 value=0x00000006 r3=0x083F3018` (event #44,171,311) |

**So `gCurrentRoom`'s complete writer census is two instructions**: the framework's IWRAM clear
(`pc=0x00000C08`, twice, always `0`) and `gf_tfunc_0806B90C+0x20` in the room loader, which is a
**byte** write (`aux=0x1`, `r0` = destination room) and **never runs at the level load** — the
room is still `0` from the boot clear when the level starts. In the hammer route it runs **twice**:
`2` (`r3=0x083F2FB8`) then `6` (`r3=0x083F3018`).

IWRAM snapshots (`--tcp-observe`, 14 captures at frames 11,402 … 11,800, plus three more at
11,802 / 12,402 / 13,200) show the settled state:

```
gCurrentRoom=6  gUnk_3000025=12  0x03000026=2 (exit type)  0x03000027=37 (record[9])
gSubGameMode 0x03000C3C: 2 at frames 11,402-11,800, 17 at 12,402 and 13,200
```

The two hops differ in how they enter the teardown, both with `lr=0x0806B41D`
(`gf_tfunc_0806B410+0xD`):

* hop 1 enters `gf_tfunc_0806B864` at **`+0x56`**, clearing `0x030000F8..0x03000101` and `0x03000028`;
* hop 2 enters it at **`+0x0`**, clearing `0x03000021 gUnk_3000021`, `0x03000048 gStageExitType`,
  `0x0300001A`, `0x030000D1..0x030000D5`, `0x03000044`, `0x0300002C`, `0x030037BE`.

Same function, two entry points — the wrapper decides how much to tear down.

**`traverse-13500` is now a permanent `smoke.ps1` case** (13500 frames,
`tests/input/g31-hammer.keyinput.txt`, `maxMisses 11`, frame
`0ede141ee9f87511cbbae128200dafdc39d485fde13e71a7977bf17cdc7bcec8`). The re-record moved nothing
else: `tests/routes/smoke-expectations.json` differs only by the timestamp and the new entry, and
the four pre-existing hashes and miss counts are byte-identical. `smoke.ps1` was **6/6** here; round
34 added `host-walk-13500` and it is **7/7** now. `-Quick` skips the three 13,500-frame routes.

### Still open

* **`gf_tfunc_0806DE8C` is still never reached.** Its type test accepts 1/3/4/5 while room 0's
  links are type `02`, and its one caller is guarded by a condition its own dispatcher forbids.
  Unchanged; it is simply not the mechanism this game uses for a vortex traversal.
* **`gUnk_300001B 0x0300001B`** has 11 readers and one writer — a boot-time block clear. It is
  inert. Nothing depends on it and nothing needs to.
* **The demo's room-0 → room-2 at frame 9,010 is still unexplained as a *mechanism*.** We now know
  the player path; we do not know what the demo does to trigger it, and the demo never sets
  `gSwitchPressed` (round 29: `gSwitchStates[4] = 0`, `gSwitchPressed = 0` throughout).
* **What does `0x080884D0` return?** The mode dispatcher bails immediately when it returns 0.
* The **`gMainGameMode 0x03000C3A` / `gSubGameMode 0x03000C3C` pairing** described in G17 is now
  named, but the *reason space* is still larger than the nine resume slots.

### Round 33 correction — it is FIVE hops, and the table above was the reason they were missed

**The "two hops" conclusion above is wrong.** It came from two value-filtered probes (values `2`
and `6`), which can only ever find those two values (VALIDATION rule 55). A whole-IWRAM sweep at
500-frame intervals on the *same* replay and the *same* build gives the actual timeline:

| frame | `gCurrentRoom` | `gUnk_3000025` | `gSubGameMode` | Wario pose | Wario x,y | live sprites |
|---|---|---|---|---|---|---|
| 6,000 – 8,501 | 0 | 0 | 17 | 0 | 0, 0 | 0 |
| 9,000 | **2** | 4 | 2 | 0 | 974, 959 | 0 |
| 9,502 | **3** | 6 | 2 | 4 (FALLING) | 986, 562 | 6 |
| 10,001 | **4** | 8 | 2 | 2 (STANDING) | 1573, 895 | 0 |
| 10,502 | **5** | 10 | 2 | 0 | 563, 703 | 4 |
| 11,001 | **6** | 12 | 1 | 0 | 168, 1855 | 1 |
| 11,500 | 6 | 12 | 2 | 35 | 1336, 1279 | 2 |
| 12,000 – 13,500 | 6 | 12 | **17** | 7 (CRAWLING) | 344, 575 (frozen) | 2 |

**Six rooms, five transitions: 0 → 2 → 3 → 4 → 5 → 6**, `gUnk_3000025` advancing 4 → 6 → 8 → 10 →
12. Rooms 3, 4 and 5 are real rooms the route *played through* — Wario falls, lands, stands and
keeps walking between each exit, and the live sprite table is repopulated each time (six sprites in
room 3, four in room 5, one in room 6, `gSubGameMode` dipping to 1 mid-flight at frame 11,001).

Two things follow that the old text got wrong:

1. **This is a traversal, not a stage exit that happens to change rooms.** It ends at frame ~12,000
   with `gSubGameMode` 2 → 17 and Wario frozen in pose 7 — the *end* of the walk is a mode change,
   not the mechanism of the walk.
2. **`gSpriteData`'s stride is 0x2C, measured.** `24 × 0x2C = 0x420` does not span the 0x520 gap to
   `gUnk_3000524 0x03000524`, so the header was not evidence. Decoding the same snapshot at 0x2C /
   0x30 / 0x38 / 0x40 settles it (rule 56): 0x2C gives six live sprites with sane fields; the other
   three give `status=0x0031`, `x=4096`, `globalID=0`, or silently drop half the sprites.

`traverse-13500` stays the pinned smoke case — the replay, the frames, the hash and the miss count
are unchanged; only this description of what those frames do was wrong.

### Round 34 retraction — it is not host input at all: the attract demo is driving `g31-hammer`

The round-33 table above is a *measurement* and stands. What it was read as — a player walking a
route because of the buttons in the replay file — is **false**, and G23 predicted it would be. This
round established it three ways.

**1. The writer.** `gButtonsHeld` is `0x03001844`. A single-shot watchpoint on that address,
value-filtered to `0x20` (LEFT), on `tests/input/g31-hammer.keyinput.txt` with a **continuously
held RIGHT** in the replay:

```
runtime_trace: mem-write-addr abort pc=0x080103D6 <gf_tfunc_080103CC+0xA>
    addr=0x03001844 value=0x00000020 width=2 (vblanks=9655)
```

**LEFT was written into the joypad word by `gf_tfunc_080103CC` while the host replay held RIGHT.**
That function is the attract-demo input player — it is the ROM form of
`third_party/lilDavid-warioland4/src/demo_input.c:34-48`, which writes `gButtonsHeld` /
`gButtonsPressed` directly and never reads `REG_KEYINPUT`.

**2. The correlation.** `logs/routes/obs-f37b/` — 23 IWRAM snapshots of the same route, decoded with
the demo's own state variables (`gDemoSequenceIndex 0x030030C8`, `gDemoInputs 0x03002CC8`,
`gDemoInputLengths 0x03002EC8`) alongside the joypad words:

| frame | room | `gButtonsHeld` | `gDemoState` | `gDemoSequenceIndex` | `gDemoInputs[idx]` | `gDemoInputLengths[idx]` |
|---|---|---|---|---|---|---|
| 8,002 | 0 | `0000` | 0 | 0 | `0000` | 0 |
| 9,000 | 2 | `0010` | 2 | 3 | `0010` | 99 |
| 9,200 | 2 | `0000` | 2 | 11 | `0010` | 55 |
| 9,402 | 3 | `0000` | 2 | 21 | `0000` | 19 |
| 9,800 | 4 | `0110` | 2 | 44 | `0110` | 97 |
| 10,002 | 4 | `0000` | 2 | 48 | `0000` | 31 |
| 10,802 | 5 | `0100` (UP) | 2 | 91 | `0100` | 24 |
| 12,202 | 6 | `0011` | 0 | 134 | `0020` (LEFT) | 118 |

`gButtonsHeld` equals the demo's own stream word in 15 of 16 samples, **including the samples where
it flatly contradicts the host's held RIGHT** (frames 9,200 / 10,002 / 10,202) and the samples where
the demo injects UP (10,802) or LEFT (12,202). The lengths match
`logs/routes/demo-input-stream.csv` exactly (index 3 → RIGHT, 99 frames; index 11 → RIGHT, 55).

**3. The consequence for G22's headline.** G22 resolved the room change as "the player's HAMMER at
the room-0 switch". The room-0 switch write (`gSwitchPressed`, round 31) was only ever observed at
**or after vblank 11,500**, while this route's level entry is at **vblank 8,852** and its first room
change is immediately after. The hammer cannot be what causes a change that happens before the
hammer exists. The hammer was incidental.

**What survives.** The frames, the replay, the frame hash and the miss count are unchanged and the
case stays pinned — but the case now says what it actually demonstrates: **the attract demo's
traversal of block `0x083F2F88`, rooms 0 → 2 → 3 → 4 → 5 → 6.** It is a good determinism pin and a
poor input pin. A **new** case, `host-walk-13500`, pins the thing `traverse-13500` was assumed to
pin: host input reaching Wario inside a level and moving him.

**The 变身 result on this route is the demo's too.** `f37-react` aborts on
`pc=0x08013D10 <gf_tfunc_08013D06+0xA> addr=0x03001898 value=0x00000001 (vblanks=10063)` — the same
vblank as the pure attract run `f33-attract`. G24's "the transformation is reachable in the guest"
therefore still holds, but **no part of it was ever produced by a host replay**, and G24's own table
had been reading `g31-hammer` as host evidence.

## G23 — OPEN: the attract demo injects its own button stream into the input buffer by DMA3 from inside the room loader

This is the finding that removes a whole class of tempting but invalid evidence, so it is recorded
separately from G22 even though the two share a chain.

**`0x03001894` is `obj/demo_input.o(iwram_data)`** according to the cartridge's own symbol table —
it is not an anonymous IWRAM byte, it is the demo input object's state. The G19 chain, which was
the ladder's head for three rounds, is the demo's, end to end:

```
08072B74  stm r13!,{r14} / ldr r1,=0x03001894 / movs r0,#0x2 / strb r0,[r1]
          bl 0x08071B80 / ldm r13!,{r0} / bx r0          ; that is the whole function
```

`gf_tfunc_08072B74` sets the demo's state byte to 2 and does nothing else. It reads no joypad.
`gf_tfunc_08072964`, on state 2, then re-arms **DMA3**:

```
08072A50  ldr  r1,=0x040000D4          ; REG_DMA3SAD
         ldr  <src> = *(u32*)(0x0878F5F4 + 4*r8)
         str  0x03002CC8 gDemoInputs  ; SAD+4
08072A7C  REG_DMA3CNT = (*(u16*)(0x0840084C + 2*r8) >> 1) | 0x80000000
```

**The attract demo's recorded button stream is DMA'd into the input buffer, and the code that
arms it is the room loader itself.** That is why the demo can walk and cross rooms with no player
present, and it is why the demo's room 0 → room 2 transition at frame 9,010 is not evidence for
axis G: the demo supplies the input that causes it.

`gf_tfunc_08072B24` closes the loop from the other side — it clears `gUnk_3000020`'s bit 7, then
indexes a byte table at `0x0840092C` by that frame counter, and **if `0x03000025 != 0` writes
Wario's position directly** out of a **second** exit table at ROM `0x0840086C` (stride 12,
`ldrh r1,[r0,#0x4] / strh r1,[r2,#0x12]` and `ldrh r0,[r0,#0x6] / strh r0,[r2,#0x14]`, with
`r2 = 0x03001898 gWarioData`). So there are two exit tables, the ROM one the player path uses and
the `0x0840086C` one the demo drives.

Supporting objects resolved from `obj/demo_input.o` code: `0x030030C8 gDemoSequenceIndex`,
`0x03002CC8 gDemoInputs`, `0x03002EC8 gDemoInputLengths`, `0x030030CC gDemoButtonsPressed`,
`0x030030CA gDemoButtonPressTimer`.

**Consequence for the ladder.** No attract-mode transition may be cited as input-driven, and the
demo's recorded stream is a second, hidden source of input competing with the host replay. Host
input does demonstrably reach Wario — the RIGHT hold moves him from the spawn point to x = 2337 —
so the replay path is live; but any experiment that runs long enough to enter attract mode has to
establish that the demo was not also driving.

### Closed: the three joypad words are named, from the decomp's own declarations

`0x03001844`, `0x03001846` and `0x03001848` are a **12-byte gap** in `symbols/iwram_map.tsv` — the
first symbol after them is `0x03001850 gUnk_3001850`. The gap is explained by `linker.ld:147-148`:

```
. = 0x0c34; obj/main.o(iwram_data);
          obj/init_helpers.o(iwram_data);        <- no . = anchor, so it is dropped by the extractor
```

and its contents are named by `third_party/lilDavid-warioland4/src/init_helpers.c:8-10`, in
declaration order:

| address | symbol | size | writer |
|---|---|---|---|
| `0x03001844` | `gButtonsHeld` | 2 | `0x08000956` (`strh`) and `gf_tfunc_080103CC` (the demo player) |
| `0x03001846` | `gButtonsHeldCopy` | 2 | `0x08000956` |
| `0x03001848` | `gButtonsPressed` | 2 | `0x08000956` (`HELD & ~prevHELD`) |

`src/init_helpers.c:23-24` is the C form of the ROM writer measured two rounds ago:

```c
gButtonsPressed  = keys & ~gButtonsHeldCopy;
gButtonsHeldCopy = gButtonsHeld = keys;
```

which independently pins the **order** — the ROM site writes `0x03001848` first from
`HELD & ~prevHELD`, then `0x03001844 = HELD`, then `0x03001846 = prevHELD`. The three names come from
`include/input.h:9-11`. `0x03001894` stays `obj/demo_input.o(iwram_data)`: the decomp has no name for
that byte either, only the object it belongs to.

**The extractor's blind spot is the finding, not the three names.** An entry in `linker.ld` with no
`. =` anchor of its own is silently dropped rather than reported as unplaced, so a 12-byte IWRAM
object region can be absent from the map with no error (rule 32). Until the extractor reports
unplaced regions, treat a gap in `symbols/iwram_map.tsv` as "unknown", never as "unused".

### Related: the reason space is larger than nine

Adding a dated addendum to G17's sweep. The nine-entry resume table at ROM `0x0801B8E4` is real and
its entries match the sweep exactly (`0x0801B908, 0x0801B934, 0x0801B950, 0x0801BA4E, 0x0801BA98,
0x0801BB4C, 0x0801BAC0, 0x0801BB30, 0x0801BB44`, keyed by the `0x03000C3C` literal stored at
`0x0801B8DC`), but it is not the whole reason space: `gf_tfunc_08000518` requests **reason 0x15 =
21**. The sweep covered 0–8 and found exactly nine publishers; reasons above 8 exist and have not
been swept.

One structural detail from the same table is worth keeping, because it explains an otherwise
baffling search result: **entry 4 is `0x0801BA98`, a one-instruction stub (`bl 0x0800FA9C`) that
falls through into `0x0801BA9C`.** `gf_tfunc_0801BA9C` therefore has no table entry, no `B`/`BL`
caller and no tail caller — and is still executed. "No caller and not in any table" is not the same
as "not called" (rule 44).


## G24 — OPEN: 变身 is `gWarioData.reaction` at `0x03001898`, its ROM writer is `gf_tfunc_08013D06+0xA`, and no host route has reached it yet

Axis F is the last large untouched deliverable, and until this round "变身" was a word in a progress
report with no address attached. It has one now, and the mechanism is fully named even though the
route is not.

### What the byte is

`third_party/lilDavid-warioland4/include/wario.h:11`

```c
#define WarioRequestPose(pose) (sWarioPoseRequestFuncTable[gWarioData.reaction](pose))
```

**The reaction byte selects Wario's entire pose-handler table.** That is what 变身 *is* in this game —
not a flag on a side effect, but a dispatch index. `include/wario.h:16-29` `enum WarioReaction`:
0 NORMAL, 1 WATER, 2 FLAMING, 3 FAT, 4 FROZEN, 5 ZOMBIE, 6 SNOWMAN, 7 BOUNCY, 8 PUFFY, 9 BAT,
10 FLAT, 11 MASK, 12 COUNT.

`struct WarioData` (`include/wario.h:254-288`) is **0x3C bytes** and `gWarioData` is `0x03001898`, so
the byte is `0x03001898 + 0x00`. The level-load initialiser confirms the size independently: the ROM
routine at `0x0801C516` calls memmove(`0x03001898`, ROM `0x082DD0A8`, `0x3C`).

Both reaction tables were read out of the ROM (offsets `0x2DECA0` and `0x2DEC70`, 12 pointers each,
`asm/blob_0x283F14-0x3529A8.s:4934-4942`):

```
sWarioPoseRequestFuncTable                    sWarioPoseHandlerTable
  0 NORMAL  -> 0x08012BAD                      0 -> 0x080104A5
  1 WATER   -> 0x08016615                      1 -> 0x08015CF9
  2 FLAMING -> 0x08017ADD                      2 -> 0x080176ED
  3 FAT     -> 0x08018371                      3 -> 0x08017FB1
  4 FROZEN  -> 0x08018845                      4 -> 0x08018759
  5 ZOMBIE  -> 0x08018F71                      5 -> 0x08018B89
  6 SNOWMAN -> 0x0801996D                      6 -> 0x080193F5
  7 BOUNCY  -> 0x0801A091                      7 -> 0x08019DDD
  8 PUFFY   -> 0x0801A6E1                      8 -> 0x0801A509
  9 BAT     -> 0x0801ABCD                      9 -> 0x0801A941
 10 FLAT    -> 0x0801B281                     10 -> 0x0801AF4D
 11 MASK    -> 0x0801B6A9                     11 -> 0x0801B5D1
```

### Who writes it

A `grep` census of `third_party/lilDavid-warioland4` for `.reaction =` gives exactly **two** write
sites, both in `src/sprite_collision.c`: the macro at line 16, and `gWarioData.reaction = 0` at line
1109 (reverting `REACTION_PUFFY`). Every other occurrence is a read. `src/sprite_collision.c:13-19`:

```c
#define SpriteCollisionTransformWario(react)                                   \
{                                                                              \
    if (!WarioCheckReaction(react)) {                                          \
        gWarioData.reaction = react;                                           \
        WarioRequestPose(0);                                                   \
    }                                                                          \
}
```

**A transformation requires an enemy or hazard collision. Nothing else can do it** (rule 50).

The runtime site is **`pc=0x08013D10` = `gf_tfunc_08013D06+0xA`**, and the function is the switch that
applies a reaction, not one reaction's helper:

```
08013D06  T  adds   r1, r0, #0x0
08013D08  T  movs   r0, #0xff
08013D0A  T  ands   r1, r1, r0
08013D0C  T  cmps   r1, #0x1
08013D0E  T  bne    0x08013d3e        ; other reactions have their own arm
08013D10  T  strb   r1, [r5]          ; <-- gWarioData.reaction = 1   (r5 = 0x03001898)
08013D12  T  ldrb   r0, [r5, #0x1]    ; gWarioData.pose
08013D14  T  cmps   r0, #0x1c
```

### The one runtime observation, and its blind spot

| tag | replay | watchpoint | result |
|---|---|---|---|
| `f33-attract` | attract demo (no input), 30000 frames | any write `0x03001898`, `min_frame 9000` | **ABORT** `pc=0x08013D10 addr=0x03001898 value=0x00000001 width=1 (vblanks=10063)` — **`REACTION_WATER`** |
| `f37-react` | `tests/input/g31-hammer.keyinput.txt`, 12600 frames | value `1`, `min_frame 8300` | ABORT, same PC, **same vblank 10063** — and G22's round-34 retraction shows the demo was driving, so **this is not independent host evidence** |
| `f33-demo2` | `logs/routes/demo-host.keyinput.txt`, 26000 frames | any write `0x03001898`, `min_frame 12000` | `exit=0` — never written |

**The transformation is reachable in the guest. No host route has produced it yet.** The `f33-demo2`
negative is *not* evidence that the input path cannot do it, for two reasons that must travel with
it:

* **The alignment is wrong, not the buttons.** `tools/validation/demo_input_to_keyinput.py` shifts
  the demo's 255-entry recorded stream (`logs/routes/demo-input-stream.csv`, 5525 frames) onto our
  level-load frame. Our level loads into **room 0** at vblank 11453; the demo's stream begins after
  it has already reached **room 2**. Same stream, different world state, so the walk diverges
  immediately and never meets the hazard.
* **The attract demo does not use the host's register.** A 10200-frame attract run with
  `-InputRecord` produced a **header-only, zero-row file**: the demo synthesises its own buttons and
  never writes `REG_KEYINPUT 0x04000130`. That re-confirms G23's point and is also why the recorded
  demo stream is the only way to copy what it does.

The first hit must also be distinguished from the initialiser: a `min_frame` at or below the level
load aborts on the `0x082DD0A8` memmove (`value=0x00000200`, i.e. `reaction=0, pose=2`) and reports
a "reaction write" that is a table copy. Rule 50's other half.

### Where the route has to go

The host's level and the demo's level are the **same block**, `0x083F2F88`, and they enter it at
**different records**. That was the misalignment all along: the host enters at record 0 (room 0),
the demo enters at record 4 (room 2) — and the demo **never plays rooms 0 or 1**.

`gf_tfunc_0806B90C` indexes the **exit-record** table at `0x0878F21C` and hands the room loader
`r3 = base + 12 * gUnk_3000025`. `tools/validation/level_rooms.py` reads the **room-header** table
`sUnk_878F280` at `0x0878F280` instead. These are two different arrays and both are stage-indexed;
`level_rooms.py --level 0` is still the right *room* (its `gCurrentRoomHeader` gate compares IWRAM
`0x03000074` against ROM `0x083F4F38`, 44/44 bytes identical). What the exit-record table adds is the
one thing the room dump cannot give: **where a room's exits are and which way they lead.**

Record layout is `[0]type [1]dest [2]x1 [3]x2 [4]y1 [5]y2 [6]next [7]s8 dx [8]s8 dy [9]a9
[10..11]u16`, and `[2]..[5]` are a **box in 64-px cells**, not two independent coordinates. The box is
the door *into* room `dest`; touching it loads record `[6]next`.

```
 idx  type dest   x1   x2 |   y1   y2 | next   dx   dy
   0     1    0   31   31 |   16   16 |     0    0    0   <- level entry -> room 0 (spawn 2016)
   1     2    0   40   40 |    4    6 |    24    0    0   <- ROOM 0 door A -> room 11
  22     2    0   12   12 |    2    2 |     0    0    0   <- ROOM 0 door B -> back to record 0
   4     2    2    0    0 |   12   14 |     3   32    0   <- the demo enters room 2 here (8852)
   3     2    1   33   33 |    8   10 |     4  -32    0   <- room 1's door, NOT room 0's
   8     2    4    0    0 |   12   14 |     7   32    0
```

> **Correction (round 35).** An earlier version of this section claimed "room 0's right exit is record
> 3, gated to rows `c4=8 … c5=10`". That was wrong on both counts: record 3's `dest` is **1**, so its
> box belongs to **room 1**, and the only two boxes whose `dest` is 0 are record 1 (cell `x 40`, rows
> 4–6) and record 22 (cell `x 12`, row 2). Both are 832 / 1088 px **above** Wario's floor, so room 0
> has no walkable exit at all.

The tester is `func_806DDE4(r0 = cellX, r1 = cellY)` (`asm/disasm_bg_clip.s:461-549`). It returns 0
unless `gSubGameMode == 2`, takes **cells, not pixels**, and walks the record table from
`base = sUnk_878F21C[gUnk_3000023]` (`0x0878F21C`, 24 level pointers) at 12 bytes per record:

```asm
.L_6de12: cmp r0,#2 ; bne .L_6de7c          ; TYPE 2 (door) only
          ldrb r0,[r2,#1] ; ldrb r1,[gCurrentRoom] ; cmp ; bne   ; dest-room filter
          ldrb r0,[r2,#2] ; cmp r0,r3 ; bhi    ; x1 <= r4
          ldrb r0,[r2,#3] ; cmp r3,r0 ; bhi    ; r4 <= x2
          ldrb r0,[r2,#4] ; cmp r0,r4 ; bhi    ; y1 <= r5
          ldrb r0,[r2,#5] ; cmp r4,r0 ; bhi    ; r5 <= y2
          ldrb r0,[r2,#6] ; strb r0,[gUnk_3000025]   ; next record index
          mov r0,#3 ; strh r0,[gSubGameMode]        ; 3 = room transition
          bl func_806DFD8 ; bl func_806DF3C ; (next==0 => gStageExitType = 6)
```

Its only caller is the per-frame background hazard scanner `func_806FD74`
(`asm/disasm_0x06EC50.s:2393`, call sites `:2525,2534`), which derives the cell from Wario itself:
`ldrsh r0,[gWarioData,#0x36]; asr r0,#17; ldrh r2,[gWarioData,#0x12]; asr r0,#6`.
**The exit test and the water hazard are the same per-frame pass** — which is why the water trigger
was found at all.

**Room 0 has no exit Wario can walk to, but it does have height.** Measured on the host route
(`logs/routes/obs-f39/`, `gameplay-right`, 30 IWRAM marks):

* the level does not start until **vblank ≈ 11,603** — everything before that is the level map;
* Wario spawns at **x = 2016, y = 1279**, pose 2 (STANDING). One cell is 64 units, so that is cell
  31 — which is exactly what record 0's `c2=c3=31` specifies;
* the room's live sprites are `gid 7 @ (1696,1024)` — `PSPRITE_SWITCH`, decoded independently from
  the room header — and **three sprites at x = 2016, y = 1024** — `PSPRITE_VORTEX` plus the two parts
  it spawns as children in `SPOSE_INIT` (`src/sprite_ai/vortex.c:147-181`). They reach pose 24
  (`SPOSE_IDLE`, which clears `disableWarioCollisionTimer`, making them Wario-collidable) **at
  vblank 11,801 with no player action**, because `gSwitchPressed` is already set from persistent
  sprite data. The room header also lists a third spawn, an unnamed `0x14` at (480,1280) — Wario's
  own row;
* holding RIGHT moves Wario to **x = 2337** by vblank 12,201 and he stays there to 14,002.

So he walks past the old (mis-read) exit and stops at the far wall. Round 35 closed the height
question: **holding A+RIGHT together lifts him off the spawn floor.** `tests/input/f49-runjump`
(200 marks, every 10 frames from 11,950) has him standing at `(2337, 1279)` until frame 12,551 and at
**`(2337, 1087)`** from then on — a ledge **192 px (3 cells) above the spawn floor**, reached by running
into the wall and jumping, and it holds him there indefinitely. The "the next route must climb"
prediction was right; the route that climbs is *run + jump*, not *walk + jump*.

The room's only other way out is the vortex: `gid 41 @ (2016, 1024)`, pose 24 `SPOSE_IDLE`
(`src/sprite_ai/vortex.c:246-248` — touching it runs `VortexFinishStage()`, which spawns
`PSPRITE_WARIO_ENTERING_VORTEX`, calls `AutosaveStageClear()` and sets a 16.7 s pause). From the
spawn floor the maximum jump apex is **232 px (y 1279 → 1047)**, which is **23 px short** of the
vortex's y = 1024; `VortexSetCommonProperties` gives it `hitbox Up = 4, Down = 0, Left = Right = 4`,
so the overlap box is a thin slab at the sprite's own y. From the new ledge (y = 1087) the same jump
apex (y ≈ 855) clears it comfortably — the open question is the 321 px horizontal gap between the
ledge at x = 2337 and the vortex at x = 2016.

One trap worth recording: `tests/input/f50-vortex` set its second phase to `0x03BE`, which I read as
"A + LEFT". `0x3FF & ~(A|LEFT)` is `0x3DE`; `0x03BE` clears bits 0, 1 and 5, i.e. **A + B + LEFT** —
so that run spent its whole second phase holding the hammer against the wall and ended in pose 51
(`WPOSE_NORMAL_LOOKING_UP`). **Compute the active-low mask from the bit table, never by hand.**

Two cautions carried forward: `tools/validation/level_rooms.py`'s spawn-id decoding is wrong for ids
above 16 (runtime `globalID` 41 where the level byte is `0x11` = 17), so any gid list is a
**runtime measurement**, not a level-decode. And `enum PrimarySpriteID` (`include/sprite.h:10`) has no
explicit values, so gids have no trustworthy names yet.

### The menu navigation is not optional

Two replays built from a *truncated* navigation (START plus three A taps, then gameplay input from
frame 7,600) **never enter a level at all** — `gSubGameMode` walks 22 → 24 → 2 and Wario stays
parked at (0,0) in pose 27, which is the level map, not gameplay. The RIGHT taps at 8,200 / 8,600
and the last three A taps at 9,000 / 10,000 / 11,000 are what confirm the file-select entry and the
level-map selection. **Every new route copies all 18 rows of `tests/input/new-game.keyinput.txt`
verbatim and only appends gameplay input from frame 12,000.**

### The four host routes that have now failed

| tag | replay | frames | watchpoint | result |
|---|---|---|---|---|
| `f36-right` | `gameplay-right` | 30000 | any write `0x03001898`, min 8000 | ABORT vblanks 8077 `pc=0x0800C706` value 0 — the level-start clear |
| `f36r2` | `gameplay-right` | 40000 | any write, min 8100 | ABORT vblanks 8239, same clear |
| `f36r3` | `gameplay-right` | 40000 | value `1`, min 8100 | `exit=0` — no transformation |
| `f36-room4` | `gameplay-right` | 40000 | `0x03000024` value 4 | `exit=0` — never reaches room 4 |
### The host routes measured this round

| tag | replay | frames | watchpoint | result |
|---|---|---|---|---|
| `f36-right` | `gameplay-right` | 30000 | any write `0x03001898`, min 8000 | ABORT vblanks 8077 `pc=0x0800C706` value 0 — the level-start clear |
| `f36r2` | `gameplay-right` | 40000 | any write, min 8100 | ABORT vblanks 8239, same clear |
| `f36r3` | `gameplay-right` | 40000 | value `1`, min 8100 | `exit=0` — no transformation |
| `f36-room4` | `gameplay-right` | 40000 | `0x03000024` value 4 | `exit=0` — never reaches room 4 |
| `f40-jump` | new nav + 18 A taps at the spawn column, 12100–15500 | 16000 | value `1`, min 11700 | `exit=0` — jumping in place at x = 2016 does not reach the vortex hitbox either |
| `f42-jump` | A **tapped** 8 frames every 30 from 12000 | 13500 | — | apex y 1216 — **63 px**. A tap and a hold are different mechanics |
| `f43-holdA` | A **held** from 12000 | 12500 | — | apex y 1047 at 12029 (232 px), lands 12054, **no re-jump while held**; vortex at y 1024 never fires |
| `f49-runjump` | **A+RIGHT** held from 12000 | 14000 | — | leaves the spawn floor: `(2016,1279) → (2025,1183) → (2109,1057) → (2261,1087) → (2337,1087)` — a **ledge 192 px up** |
| `f50-vortex` | A+RIGHT then `0x03BE` | 14400 | — | **mask error**: `0x03BE` is A**+B**+LEFT, not A+LEFT. Ends stuck at the wall in pose 51 |
| `f51-leftjump` | A+RIGHT 400f, LEFT 400f, A+LEFT | 14500 | — | LEFT walks him **off** the ledge; back on the floor at the x = 1758 wall |
| `f46/f47` | 200-frame d-pad holds on the world map | 12000 | — | `gCurrentStageID` / `gUnk_3000023` never leave 0 — see G25 |

The value filter is mandatory: an unfiltered `-AbortMemAddr 0x03001898` on any host route aborts on
the level-start clear at `pc=0x0800C706`, and `-AbortMinFrame` alone is not enough.

The active-low masks, computed rather than guessed: `A = 0x3FE`, `B = 0x3FD`, `A+RIGHT = 0x3EE`,
`A+LEFT = 0x3DE`, `LEFT = 0x3DF`, `RIGHT = 0x3EF`, `UP = 0x3BF`, `DOWN = 0x37F`, none = `0x3FF`.

### Still open

* **The route itself.** Reaching the water hazard under host input needs a climb out of room 0 first.
  Round 35 measured the climb — see `f49`/`f51` in the table above and "Room 0 has no exit Wario can
  walk to, but it does have height" above — but the only object in room 0 worth reaching is the
  vortex, 63 px above the new ledge and 321 px to its left.
* **Name the gids.** `globalID` 7, 41, 163, 165, 179, 21, 42, 43, 130, 132, 135, 141 are measured but
  unnamed; the enum's implicit numbering cannot be relied on.
* **Whether room 0 contains a hazard tile at all.** `0x03007DF0`, the word `gf_tfunc_0806DC80` writes
  the scanned tile id into, reads 0 in 197 of 206 IWRAM samples of `f49`; the remaining values
  (`0x0000043F` = 1087, Wario's own ledge height; `0x01014863`; `0x007E0C0C`) look like a scratch word
  rather than a tile id, so the address needs to be re-confirmed on this route before it can be used
  as a per-tile witness.

## G25 — OPEN: a fresh save has exactly one world-map node, and the ROM's own graph proves it

Round 35's goal was a host-input 变身. The only reachable transformation is the background water
hazard, and water only exists in rooms 1, 2, 3, 6 and 9 of `0x083F2F88` — so the route had to change
levels, which means the world map. The map is a dead end on a fresh file, and the ROM says so.

**`func_807B544` (`asm/disasm_map_screen.s:964-1231`) is the only thing that moves the cursor**, and it
indexes a ROM graph with two constants recovered directly from the disassembly:

```asm
	lsl	r3, r5, #2            ; dir * 4           (r5 = 0 L, 1 R, 2 U, 3 D)
	ldrb	r4, [r7, #0]         ; r7 = gCurrentPassage  (the current node)
	lsl	r1, r4, #4 ; add r1, r3, r1
	ldrb	r2, [r8, #0]         ; r8 = gUnk_3003C95 (the area)
	lsl	r0, r2, #3 ; sub r0, r0, r2 ; lsl r0, r0, #4      ; area * 112
	add	r1, r0, r1 ; add r1, sl ; ldr r0, [r1]      ; sl = sUnk_86392D0
	cmp	r0, #7 ; bne .L_7b5f6 ; b .L_7b738          ; 7 == BLOCKED
```

and on success (`.L_7b5fc`) the *new* node id comes from a **second** table, `sUnk_863926C`, at
`dir*112 + area*112 + node*16`. So `sUnk_86392D0` is an availability mask, not the graph itself.

Dumping `sUnk_86392D0` (`0x086392D0`) as 7 areas × 7 nodes × {L,R,U,D}:

```
area 0  node 0 L,R,U,D = (7, 7, 7, 7)      <- the start node: NO exits at all
        node 1 = (0, 2, 2, 0)   node 2 = (6, 1, 6, 1)   node 3 = (4, 6, 6, 4)
        node 4 = (3, 0, 3, 0)   node 5 = (7, 7, 7, 0)   node 6 = (3, 2, 7, 7)
area 1  node 0 = (4, 1, 7, 7)   (every other node matches area 0)
area 2  node 0 = (4, 1, 5, 7)
area 3  node 0 = (7, 9, 10, 14) ... (the first area whose neighbour ids exceed 7)
area 4  node 0 = (0, 1, 0, 1)
areas 5, 6 = not graphs (the table ends)
```

**Node 0 of area 0 has no neighbour in any direction, so the cursor cannot move, and `7` is not an
artefact of my decode** — areas 3 and 4 return ids up to 41, areas 0–2 return 0–6, and `7` appears
exactly where a direction is unavailable. Measured on three separate runs (`obs-f46`, `obs-f47`,
`obs-f48`), `gCurrentPassage == 1536` while the map is up (low byte 0, i.e. node 0) and
`gCurrentStageNumber == 6` (stale); after A the pair resets to 0/0 and `gUnk_3003C94 = 3`,
`gUnk_3003C99 = 1`. The d-pad edges *do* register — `gUnk_3003C44` cycles 3 → 0 → 2 → 1 → 3 across
RIGHT/DOWN/LEFT/UP taps (`func_807B544` sets `gUnk_3003C44 = 2/1/3/0` for LEFT/UP/RIGHT/DOWN) — and
then `.L_7b738` runs, which is `gUnk_3004A30 = 1000; return 0`.

Two corollaries worth keeping:

* **One node means the level list cannot be walked on a fresh save.** A route that wants another level
  needs a save with progress, not a longer d-pad hold. `func_8084E10` (the other mover, in
  `disasm_passage_screen.s`) needs a key **held for more than 10 frames** via `gUnk_3003C54` — but it
  is called from `gSubGameMode 35`, not from the map, so it was never the blocker.
* **A seeded save skips the map entirely.** `-SavePath logs/routes/seed.sav` plus the full 18-row nav
  goes `gSubGameMode 0 @ 11452 → 2 @ 11500` and stays in the level to 14301, with host d-pad input
  reaching Wario. The save is the game's own format: 12-byte header
  `af 13 9e d1 50 ec 61 2e 30 31 00 00`, then ASCII `AGBWarioLand-USver00` at 0x0C repeated at 0x40
  (two slots). **`run-route.ps1` does not zero `-SavePath`** (`:121-129` only clears the per-route
  default), so a seeded file persists across runs.

Still open: whether the area index `gUnk_3003C95` can be non-zero from save data alone, which is the
only remaining way to open the map without a progress save.

## G26 — PARTLY RETRACTED (see G27): the 变身 mechanism is intact, but "room reachability" is not the blocker it was said to be

> **2026-10-01 — the "### The first blocker" section and the live-sprite list below are superseded by
> G27.** Room 0 is traversable: the guest room changer `func_806D3C0` was observed firing on the attract
> demo at vblank 9201, so the missing ingredient is a scripted route onto the demo's entry floor, not an
> unreachable door; and the sprite list was decoded against the wrong IWRAM base. The transformation
> mechanism analysis in this entry still stands and is still the right target for Axis F.

**Axis F is re-scoped.** It is not "manufacture a transformation with host input". It is: *prove that
the original game's transformation path can be triggered, runs, and restores correctly in the recomp,
through real guest logic.* Host input may only drive the player input that reaches a trigger; it may
never write `gWarioData.reaction`, a pose, a sprite field, or any other guest memory. A button that
forces a transformation is a **TEST-ONLY** diagnostic and can never be an Axis F completion
condition.

### The mechanism, read out of the decomp rather than out of a trace

`include/wario.h:11` is the whole trick:

```c
#define WarioRequestPose(pose) (sWarioPoseRequestFuncTable[gWarioData.reaction](pose))
```

`gWarioData.reaction` is not a flag beside the pose machinery — it *is* the pose machinery's index.
`enum WarioReaction` (`include/wario.h:16-30`) runs 0 NORMAL, 1 WATER, 2 FLAMING, 3 FAT, 4 FROZEN,
5 ZOMBIE, 6 SNOWMAN, 7 BOUNCY, 8 PUFFY, 9 BAT, 10 FLAT, 11 MASK, 12 COUNT, and the two 12-entry
tables at ROM `0x2DEC70` (handler) / `0x2DECA0` (request) select the per-reaction code. The chain is
therefore uniform for all eleven transformations:

```
sprite hitbox overlaps Wario
  -> SpriteCollisionProcess() -> switch (gSpriteData[slot].warioCollision)   sprite_collision.c:948
  -> one case per reaction -> SpriteCollisionTransformWarioXxx()              sprite_collision.c:193-241
  -> macro: if (!WarioCheckReaction(react)) { gWarioData.reaction = react; WarioRequestPose(0); }
                                                                            sprite_collision.c:13-19
  -> gWarioData.reaction (IWRAM 0x03001898, struct WarioData size 0x3C)
  -> WarioRequestPose(0) dispatches through sWarioPoseRequestFuncTable[reaction]
  -> that reaction's pose handler animates and controls the transformed Wario (asm/wario/disasm_*.s)
  -> the same handler clears reaction back to REACTION_NORMAL -> NORMAL's pose handler restores him
```

Only ten `warioCollision` values set a reaction: `0x0E` Flaming, `0x13` Bat, `0x1F` Flat, `0x14`
Frozen (`func_801EBCC`), `0x12` Snowman (`func_801EC74`), `0x27` Puffy (`func_801EC30`), `0x10`
(`func_801ECB8`), `0x11` (`func_801ECFC`), `0x15` (`func_8020C78`), `0x0A` (`func_80211E0`). `0x4A`
(`SpriteCollisionMaybeTransformWarioBubble`) does **not** set one, and `0x6` (`func_8021720`) is the
collectable/enterable class used by coins, keyzer, treasure and the vortex — the vortex is an exit,
not a 变身. No `src/**/*.c` file contains the literal of any reaction-setting value, so every value
is written by its own sprite type's property setter.

### The one transformation chosen, and its real trigger

**FLAMING (`REACTION_FLAMING` = 2)**, because its trigger sprite is static and room-placed: its
`warioCollision` is live from spawn, with no AI state to wait for. Five setters write `0x0E`
(`asm/sprite_ai/disasm_{aerodent,chandelier,kaentsubo,pig_head_statue}.s`) — aerodent:4369,
chandelier:19, kaentsubo:1377, kaentsubo:1694, pig_head_statue:249.

**The real trigger is `PSPRITE_KAENTSUBO`** (`include/sprite.h:33`, a cave spider): it writes
`warioCollision = 0x0E` unconditionally, so **Wario becomes a fire Wario simply by walking into a
kaentsubo**. `sprite_collision.c:1127-1133` gates it on `(gWarioData.reaction == 0) &&
(gWarioData.damageTimer == 0)`, which is the game's own "only if not already transformed" rule and
needs no modification. The chandelier's setter
(`asm/sprite_ai/disasm_chandelier.s:4-56`, `func_8069734`) is the readable template: `mov r0, #14 /
strb r0, [r1, #30]` then `hitboxExtentUp=96, hitboxExtentDown=192, hitboxExtentLeft=48,
hitboxExtentRight=44` — contact is trivial once you are in the room.

Level 0 contains a kaentsubo in exactly two rooms, both on the hard sprite list, both at block
(15,10) = pixel (992, 704): **room 7** (`VORTEX(8,10) KAENTSUBO(15,10) JEWEL_SW(16,10)
VORTEX(20,10)`) and **room 9** (`TOTSUMEN(7,10) KAENTSUBO(15,10) JEWEL_NW(16,10)
TOTSUMEN(25,10)`). Spawn-id names for ids > 16 come from `gUnk_3000524 0x03000524` read out of a
retained snapshot (`logs/routes/obs-f44/f44nav-iwram-f011902.bin`), not from the level byte — the
byte only distinguishes 16 sprites, which is why an earlier entry-room census was unreliable.

### The first blocker

**Level 0 room 0 — the only room the 18-row nav reaches — has no reaction source at all** (SWITCH,
VORTEX, ROCK), and its two doors are 832 px and 1088 px above the spawn floor at y = 1279, while the
measured maximum climb is **192 px** (`f49-runjump`: A+RIGHT held carries Wario 2016,1279 →
2025,1183 → 2109,1057 → 2189,1062 → 2261,1087 → 2333,1087 and holds him on the ledge; a plain 8-frame
A tap is 63 px, a held A is 232 px). With G25 — a fresh save's world map has exactly one node — rooms
7 and 9 are unreachable, so no real kaentsubo can be touched.

So the blocker is **room reachability**, not the transformation mechanism. The mechanism is already
understood, is pure guest code, and needs no patch: the missing ingredient is a way into room 7 or
room 9. The next round does exactly one thing — decode level 0's remaining door records so a door
inside the reachable height band exists, or seed a save that resumes in a room containing a kaentsubo
— and then drive FLAMING with host input and record the enter/exit with a watchpoint on
`0x03001898`.

Not worth re-deriving: tile 0x50 water exists in rooms 1/2/3/6/9 (tileset 17) and is the WATER
hazard, but Wario's own pose handlers will not survive it unless the swimming path is also correct,
so FLAMING is the cheaper first transformation to close.

## G27 — RESOLVED 2026-10-01: room 0 *is* traversable, the room changer is `func_806D3C0`, and two measurement errors were corrected

**The transition function was mis-attributed.** `func_806DDE4` is not the frame-level room changer;
`func_806D3C0` is (`asm/disasm_block.s:4-136`). Per frame it computes
`r9 = (xPosition) >> 6` and `r8 = (yPosition) >> 6` from `gWarioData` offsets 18 and 20 (no `-0x80`
bias), fetches one tile attribute into `r7`, then accepts the first record of
`sUnk_878F21C[gUnk_3000023]` with `[1] == gCurrentRoom`, `[2] <= r9 <= [3]`, `[4] <= r8 <= [5]`
(`disasm_block.s:70-77`) **and** `(r7 - 2) & 0xFFFF <= 5` — the tile attribute must land in `[2, 7]`
(`disasm_block.s:78-86`). On a hit it writes `0x80` into `gUnk_300004C[2]` and encodes the record
index as `gUnk_300004C[1] = index / 10`, `[2] |= index % 10` (`disasm_block.s:108-119`), so the same
function also feeds the "records discovered" display. The trigger is therefore a **cell rectangle**,
not a height band: G26's "doors are 832/1088 px above the floor" was an observation about two records,
not the mechanism, and it did not prove room 0 was dead.

**Room 0 was observed switching rooms.** With the attract demo running and **no host input**
(`run-route.ps1 -Tag attr-roomchange -Frames 10000 -Window -TcpObserve 20032`, sampled by
`tools/validation/wario_watch.py --from 8300 --to 9200 --every 10`), `gSubGameMode` steps **2 → 3** at
vblank **9201** with Wario at `(1974, 831)`: `x>>6 = 30…31`, `y>>6 = 12…13`, `gCurrentRoom = 0`,
matching row 5 of `0x083F2F88` (`type=2 dest=2 x=31..31 y=11..12`). The demo walks the room's upper
floor at `y = 959` from `x ≈ 293`, is bounced by a sprite at `x = 910`, jumps onto the `y = 831`
platform and enters the door. So the guest code that links rooms is intact in the recomp.

**Open, low priority (G28 candidate): entry-floor asymmetry.** A scripted `new-game` route drops
Wario on the **lower** floor at `(2016, 1279)`, where no reachable record box exists (best measured
climb on that floor: `y = 1087`), while the demo's entry is the upper floor at `y = 959`. Which
`type 1` record / `u16` tile coordinate (`u16 = tile_x | tile_y << 6`; level 0 record 0 = `672` =
tile (32, 10); level 1 record 0 = `651` = tile (27, 10)) governs the scripted entry is **not yet
settled**. This is not a mechanism failure and it does not block the release.

**Measurement error corrected — sprite array base.** The "live sprite list" in G26 used base
`0x03001B4C`, which is not the array (that region holds unrelated IWRAM data, so every slot decoded as
garbage). The array is **`gSpriteData = 0x03000104`** (`symbols/iwram_map.tsv`, `0x420` bytes =
24 × `0x2C`). Read correctly, room 0's live sprites are `7 PSPRITE_SWITCH` @ (1696, 1024),
`41 PSPRITE_VORTEX` @ (2016, 1024) status `139`, its children `165`/`163`, and `179`.

**Measurement error corrected — observer protocol.** `read_iwram` on the `--tcp-observe` server takes
`len=` (not `length=`) with `addr="0x%08X"` and answers `{"ok":true,"data":"<hex>"}`; a wrong field name
silently returns a short payload and every later index read throws. See VALIDATION rule 62.

**Round 36 smoke result (2026-10-01, `logs/release/smoke-full.txt`): 7/7 PASS.** `boot-120` 0 misses ·
`attract-3600` 7 · `title-input-6000` 10 · `ctrl-idle-13500` 13 · `host-walk-13500` 13 ·
`traverse-13500` 11 · save-write/load round trip PASS, 18,000 frames, expectation
`11eb324834a221af`. Every pre-existing frame hash is unchanged from the last recorded baseline
(`f1dd2fdacf2e4263`, `38be8fce4a34f13e`, `697534774d47c51f`, `6d764abd8b801016`), so the documentation
work in this round is behaviour-preserving. Note that `title-input-6000` now records **10** misses where
older notes said 7; the smoke suite compares each case against
`tests/routes/smoke-expectations.json` and passed, so the current numbers are the authoritative ones.

## G29 — RESOLVED (was a release blocker, documentation): a fresh clone could not build, because the pinned framework snapshot was local-only and no script obtained it

**Resolution (see the "Resolution" block at the end of this section).** The project no longer depends on
a locally created commit: `docs/FRAMEWORK_PIN.json` (schema 2) now records the **public upstream**
repository `https://github.com/mstan/gbarecomp.git` at commit
`477e3d12dd0920a4961d58ba625ec2afe505c1fb`, the three submodule revisions that commit requires, and this
project's own framework changes as three reviewable patches under `patches/gbarecomp/`. A new script,
`tools/regeneration/setup-framework.ps1`, clones the pinned commit, checks out the submodules, applies the
patches and verifies every patched file. The text below is the original audit finding, kept as the record
of what was wrong and why.

This was the headline finding of the adversarial publication audit
([docs/RELEASE_AUDIT.md](RELEASE_AUDIT.md), BLOCKER B1). It was **not** a publication-boundary defect —
nothing forbidden is tracked — but the repository as published was not buildable by a stranger.

**The chain, verified by reading the scripts and grepping the tracked set:**

* `tools/regeneration/build-framework.ps1:42-44` throws
  `Missing pinned framework snapshot at $Framework. See docs/FRAMEWORK_PIN.json.` — and its own header
  comment (`:13-16`) claims "Nothing is downloaded unless a pinned dependency is genuinely absent"
  although the script contains no download, clone or fetch code at all.
* `tools/regeneration/build-host.ps1:39` gates on `reference\gbarecomp\CMakeLists.txt`;
  `tools/regeneration/regen.ps1:62` and `:81-83` also `Fail`; `CMakeLists.txt:32,37` require
  `GBARECOMP_ROOT`.
* `docs/FRAMEWORK_PIN.json:19` pins `bcaeae1f881e795f7df29952e71cf0205ac30a87`, and that file's own
  `pin_commit_note` (line 23) states the SHA is **a locally created content-identity commit**
  (`git init` inside `reference/gbarecomp`), so it has no upstream equivalent and cannot be
  cloned or checked out either.
* No fallback exists anywhere in the tracked set:
  `git grep -n -I -E 'git (clone|fetch|submodule)|Invoke-WebRequest|Invoke-RestMethod|Start-BitsTransfer|DownloadFile|curl |wget |codeload\.github|FetchContent'`
  matched only an unrelated toml++ URL and two toml++ `FetchContent` messages inside the absent
  framework.
* `reference/gbarecomp` is excluded by `.gitignore:69:/reference/*`, and
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) §framework already states that the snapshot is a
  local-only directory, that it is not part of this repository, and that redistributing it is the
  framework author's decision.

**Wording that was wrong and has been corrected.** `README.md` previously said "You need the original
cartridge image. Nothing else is downloaded at build time." and presented `build-framework.ps1` as
step 1 of the build with no caveat.

**Options, in the order the project prefers them:** (1) the framework author publishes a reachable
upstream commit, that SHA replaces the local one in `docs/FRAMEWORK_PIN.json`, and
`build-framework.ps1` gains a real clone/checkout step; (2) ship the snapshot if PolyForm
Noncommercial 1.0.0 permits redistributing it; (3) keep the snapshot unshipped and describe the
release as **source-complete, framework supplied separately**, which is what the README now does.
Until one of these lands, the release must not be described as buildable by a stranger.

**Resolution — option (1), delivered.** Which upstream commit the local snapshot actually was, and
every local modification to it, were established by content comparison rather than by trusting the old
pin: 22 candidate upstream commits were downloaded and diffed blob-by-blob against the local tree, and
`477e3d12dd0920a4961d58ba625ec2afe505c1fb` matched with the smallest delta (13 files). The local tree
differs from that commit in **14 files** (12 modified, 2 added), plus **3 files** in `arm-recomp-core`
and **4 files** in `recomp-net`. Those differences are now data, not an opaque snapshot:

* `patches/gbarecomp/01-gbarecomp.patch` — 14 files: `/utf-8` and forced `codegen_tail_macros.h`
  include in `CMakeLists.txt`; seven `[[extra_func]]` entries in `bios/gba_bios.toml`; the four
  `GBARECOMP_TAIL_*` tail-transfer macros in `src/armv4t/runtime_arm.h` and
  `src/runtime/overlay_runtime_arm.h`; `GbaIo::check_key_irq()`; the `SRAM_F_V` save signature; the
  64 KiB flash device-id fix and the debug hooks in `gba_save.cpp`/`runtime.cpp`; the MSVC `clz32`
  branch; the empty-RAM dispatch guard; and the regenerable
  `generated_bios/bios_dispatch_table.cpp` row for `bios_halt_cont_034C`.
* `patches/gbarecomp/02-arm-recomp-core.patch` — 3 files, the `GBARECOMP_TAIL_*` emitters.
* `patches/gbarecomp/03-recomp-net.patch` — 4 files (Discord/Linux websocket fallback).

`tools/regeneration/setup-framework.ps1` performs: clone `mstan/gbarecomp` → checkout the pinned
commit → clone the three pinned submodules by absolute URL → apply the three patches → verify each
patched file's git blob SHA-1 against `docs/FRAMEWORK_PIN.json`. It is idempotent, re-verifiable with
`-VerifyOnly`, and refuses to overwrite an existing checkout without `-Force`. `build-framework.ps1`
now points at it instead of failing, and its header no longer claims a download path it did not have.

One subtlety worth keeping: the patches are recorded with LF line endings while a Windows clone
materialises CRLF, so `setup-framework.ps1` normalises each patch target to LF before applying and
compares blobs with `git hash-object`, which applies the same clean filter either way.

**Related, smaller:** `tools/validation/wario_watch.py`, `tools/validation/room_probe.py` and
`tools/validation/gen_vortex_route.py` are cited by tracked documents and were untracked, so they would
have vanished from a clone (audit warning K11). `LICENSE:5` carried the placeholder
`<PROJECT OWNER — must be set before any publication>`, which only the human owner can close (audit
warning K8) — that placeholder is now replaced with the project author's name, `Zaxaerith`.

**Room geometry, measured live.** `tools/validation/room_probe.py` dumps the loaded
`gCurrentRoomHeader` (`0x03000074`) and `gBackgroundInfo` (`0x03000054`). Room 0 at frame 12500:
tileset `0x50`, bg0/bg1/bg2/bg3 = `0x08598EEC`/`0x085991DC`/`0x08599454`/`0x085FA6D0`,
`+0x18 = 0x00070101`, `+0x1C`/`+0x20` = `0x085991D0` (hard and normal identical), shard `+0x24 =
0x08599448`; width **41 cells**, height **23 cells** → **2624 × 1472 px**. This agrees with the earlier
boundary inference, so existing coordinate work stands.
