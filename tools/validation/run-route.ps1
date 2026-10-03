<#
    run-route.ps1 — run the host executable along one deterministic route and
    capture the evidence a checkpoint needs.

    Every run is bounded (--frames / --steps), gets no interactive input, and
    writes its stdout/stderr plus a coverage JSON and a miss-proposal fragment
    into logs/routes/. The point is that a claim like "boots" or "reaches the
    title screen" is backed by a bounded, repeatable command rather than a
    screenshot someone remembers seeing.

    Route definitions (frame budget, expected observation) live in
    tests/routes/*.csv and docs/VALIDATION.md; this script just executes one.

    Examples
      # M3 boot smoke: 120 frames, no window, dump the last frame
      tools/validation/run-route.ps1 -Tag boot-120 -Frames 120 -DumpLastFrame

      # Acceptance gate: abort on ANY dispatch miss instead of bridging it
      tools/validation/run-route.ps1 -Tag strict-600 -Frames 600 -StrictStatic

      # Mid-run filmstrip of an input route: 40 consecutive frames from 12050,
      # written as logs/routes/<tag>-frames/f_%06llu.png; the runtime quits by
      # itself once the count is reached (runtime.cpp:4114), so this is bounded
      # even though the frame budget is larger.
      tools/validation/run-route.ps1 -Tag camscroll -Frames 13100 `
          -InputReplay tests\input\gameplay-right.keyinput.txt `
          -FrameDumpStart 12050 -FrameDumpCount 40
#>
[CmdletBinding()]
param(
    [string]$Exe,                     # defaults to build\host\WarioLand4Recomp.exe
    [string]$Tag = 'route',
    [int]$Frames = 600,
    [int]$Steps = 0,                  # CPU steps; only applied when > 0
    [switch]$DumpLastFrame,           # write logs/routes/<tag>-last.png
    [string]$DumpPng,
    [string]$DumpBmp,
    [string]$LoadState,
    [string]$Save,                    # save CHIP override, e.g. sram
    [string]$SavePath,                # explicit save file; overrides per-route isolation
    [switch]$KeepSave,                # keep an existing per-route save instead of zeroing it
    [switch]$ColdCache,               # GBARECOMP_HEAL_CACHE: fresh empty cache for this tag
    [switch]$StrictStatic,            # GBARECOMP_STRICT_STATIC=1 : abort on any miss
    [switch]$AllowLauncher,           # default is GBARECOMP_NO_LAUNCHER=1
    [string]$DemoInput,               # framework demo track (see docs/VALIDATION.md)
    [string]$InputReplay,             # GBARECOMP_INPUT_REPLAY: frame-indexed keyinput trace
    [string]$InputRecord,             # GBARECOMP_INPUT_RECORD: write such a trace
    [int]$FrameDumpStart = 0,         # GBARECOMP_FRAMEDUMP_START: first guest frame to dump
    [int]$FrameDumpCount = 0,         # GBARECOMP_FRAMEDUMP_COUNT: mid-run filmstrip length (0 = off)
    [switch]$Window,                  # default is headless (--no-window)
    [int]$TcpObserve = 0,             # GBARECOMP_TCP_OBSERVE: read-only debug port (G13b)
    [switch]$ForceInterp,             # GBARECOMP_FORCE_INTERP=1 : measure the interpreter path
    [int]$HangSeconds = 120,
    [int]$TimeoutSeconds = 900,
    # Guest-memory watchpoint (docs/VALIDATION.md §3): abort the run at the PC
    # that writes ADDR (optionally only VALUE, only after frame MIN_FRAME) and
    # dump the recent trace. The abort is the EVIDENCE, so it exits non-zero.
    [int]$AbortMemAddr = 0,
    [int]$AbortMemValue = -1,
    [int]$AbortMinFrame = 0,
    [int]$TraceDumpDepth = 0,
    # Branch-PC abort. The runtime fires on the PC of a *branch instruction*
    # (src/armv4t/runtime_arm.cpp:266-279) -- the address of the branch, never
    # its target, so it cannot see a computed jump and it needs the address the
    # instruction actually executes at. For the cartridge's user IRQ handler
    # that is an IWRAM address, not its ROM address: game.toml records the span
    # 0x080000FC..0x080008FB as DMA3-copied to 0x03000C44, so ROM 0x080001XX
    # runs at 0x03000CC0 + (0xXX - 0xFC). Set it to 0 to leave the instrument off.
    [int]$AbortBranchPc = 0
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RouteDir = Join-Path $Root 'logs\routes'
New-Item -ItemType Directory -Force -Path $RouteDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

if (-not $Exe) { $Exe = Join-Path $Root 'build\host\WarioLand4Recomp.exe' }
if (-not (Test-Path $Exe)) { Fail "Executable not found: $Exe (run tools/regeneration/build-host.ps1)" }

# ------------------------------------------------------------------ verified in
$identity = Get-Content -LiteralPath (Join-Path $Root 'docs\ROM_IDENTITY.json') -Raw | ConvertFrom-Json
$roms = @(Get-ChildItem -LiteralPath $Root -Filter '*.gba' -File)
if ($roms.Count -ne 1) { Fail "Expected exactly one .gba in $Root, found $($roms.Count)." }
$rom = $roms[0].FullName
if ((Get-FileHash $rom -Algorithm SHA256).Hash.ToLower() -ne $identity.rom.sha256) { Fail 'ROM SHA-256 mismatch.' }
$bios = Join-Path $Root 'bios\gba_bios.bin'
if (-not (Test-Path $bios)) { Fail "BIOS dump not found at $bios" }

$config = Join-Path $Root 'game.toml'
$coverage = Join-Path $RouteDir "$Tag-coverage.json"
$missFrag = Join-Path $RouteDir "$Tag-misses.toml.frag"
$outLog   = Join-Path $RouteDir "$Tag.log"
$errLog   = Join-Path $RouteDir "$Tag.err.log"

# The runtime resolves ROM/BIOS through a chain that ENDS IN A MODAL WINDOWS FILE
# DIALOG (reference/gbarecomp/src/runtime/asset_picker.cpp:221-243). There is no
# non-interactive escape hatch, so a path that fails to parse hangs the process
# forever with no output. Two defences below: seed the picker cache next to the
# exe, and quote every argument on the way to Start-Process (which joins the
# array with spaces and would otherwise split "Wario Land 4 (USA, Europe).gba").
$exeDir = Split-Path -Parent $Exe
Set-Content -LiteralPath (Join-Path $exeDir 'rom.cfg')  -Value $rom  -Encoding ASCII
Set-Content -LiteralPath (Join-Path $exeDir 'bios.cfg') -Value $bios -Encoding ASCII

function ConvertTo-QuotedArg([string]$a) {
    if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' }
    return $a
}

# ------------------------------------------------------------ route save isolation
# The game FLUSHES SRAM at exit (`save_flushed path="…\saves\wario_land_4_awae.sav"`),
# so with a shared save file one route's final state becomes the next route's
# initial state — measured: two otherwise identical 6000-frame runs diverged only
# because the first wrote the save the second loaded (distinct_misses 7 vs 10).
# Every route therefore gets its OWN save file, pre-filled with 0xFF (an
# unformatted SRAM) unless -KeepSave is given, so every run starts from the same
# bytes and a re-run is comparable with the previous one.
if (-not $SavePath) {
    $SavePath = Join-Path $RouteDir "$Tag.sav"
    if (-not $KeepSave) {
        $blank = [byte[]]::new(32768)
        for ($i = 0; $i -lt $blank.Length; $i++) { $blank[$i] = 0xFF }
        [System.IO.File]::WriteAllBytes($SavePath, $blank)
        Step "save -> $SavePath (zeroed to 0xFF)"
    } else {
        Step "save -> $SavePath (kept)"
    }
}

# --------------------------------------------------------------------- arguments
$argList = @('--rom', $rom, '--bios', $bios, '--config', $config)
if ($Frames -gt 0) { $argList += @('--frames', "$Frames") }
if ($Steps -gt 0) { $argList += @('--steps', "$Steps") }
if ($Window) { $argList += '--window' } else { $argList += '--no-window' }
if ($Save) { $argList += @('--save', $Save) }
if ($SavePath) { $argList += @('--save-path', $SavePath) }
if ($LoadState) { $argList += @('--load-state', $LoadState) }
if ($DumpPng) { $argList += @('--dump-png', $DumpPng) }
elseif ($DumpLastFrame) { $argList += @('--dump-png', (Join-Path $RouteDir "$Tag-last.png")) }
if ($DumpBmp) { $argList += @('--dump-bmp', $DumpBmp) }

# ------------------------------------------------------------------ environment
$saved = @{}
function Set-Env([string]$name, [string]$value) {
    if (-not $saved.ContainsKey($name)) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
    Set-Item -Path "Env:$name" -Value $value
}
Set-Env 'GBARECOMP_COVERAGE_JSON' $coverage
Set-Env 'GBARECOMP_MISS_FRAG' $missFrag
if (-not $AllowLauncher) { Set-Env 'GBARECOMP_NO_LAUNCHER' '1' }
if ($StrictStatic) { Set-Env 'GBARECOMP_STRICT_STATIC' '1' }
if ($ForceInterp) { Set-Env 'GBARECOMP_FORCE_INTERP' '1' }
if ($DemoInput) { Set-Env 'GBARECOMP_DEMO_INPUT' $DemoInput }
if ($InputReplay) { Set-Env 'GBARECOMP_INPUT_REPLAY' $InputReplay }
if ($InputRecord) { Set-Env 'GBARECOMP_INPUT_RECORD' $InputRecord }
Set-Env 'GBARECOMP_HANG_WATCHDOG' '1'
Set-Env 'GBARECOMP_HANG_SECONDS' "$HangSeconds"

# Guest-memory watchpoint. The runtime compares every guest store against this
# address (src/armv4t/runtime_arm.cpp:175-231), prints
#   runtime_trace: mem-write-addr abort pc=… <name+0x…> addr=… value=… width=…
# plus the recent trace, then calls std::abort() — so the process exits with a
# crash code and the EVIDENCE is in <tag>.err.log. With a decomp symbol overlay
# the address is printed as `<gHeartMeter+0x0>` instead of a bare hex value.
if ($AbortMemAddr -ne 0) {
    Set-Env 'GBARECOMP_ABORT_ON_MEM_WRITE_ADDR' ('0x{0:X8}' -f $AbortMemAddr)
    if ($AbortMemValue -ge 0) {
        Set-Env 'GBARECOMP_ABORT_ON_MEM_WRITE_VALUE' ('0x{0:X8}' -f $AbortMemValue)
    }
    if ($AbortMinFrame -gt 0) {
        Set-Env 'GBARECOMP_ABORT_ON_MEM_WRITE_MIN_FRAME' "$AbortMinFrame"
    }
    if ($TraceDumpDepth -gt 0) {
        Set-Env 'GBARECOMP_TRACE_DUMP_DEPTH' "$TraceDumpDepth"
    }
    $valueText = 'any'
    if ($AbortMemValue -ge 0) { $valueText = '0x{0:X8}' -f $AbortMemValue }
    Step ("watchpoint -> addr=0x{0:X8} value={1} min_frame={2} trace_depth={3} (the abort IS the evidence)" -f `
        $AbortMemAddr, $valueText, $AbortMinFrame, $TraceDumpDepth)
}

# Branch-PC abort. This is the ONLY instrument that can prove *which* branch
# instruction executed at a given address, and it is the only way to settle a
# ROM address that is ambiguous between an ARM word and two Thumb halfwords:
# set it to both candidates and see which one fires. Like the watchpoint, the
# abort IS the evidence, so the process exits non-zero on purpose.
if ($AbortBranchPc -ne 0) {
    Set-Env 'GBARECOMP_ABORT_ON_BRANCH_PC' ('0x{0:X8}' -f $AbortBranchPc)
    if ($TraceDumpDepth -gt 0) {
        Set-Env 'GBARECOMP_TRACE_DUMP_DEPTH' "$TraceDumpDepth"
    }
    Step ("branch abort -> pc=0x{0:X8} trace_depth={1} (the abort IS the evidence)" -f `
        $AbortBranchPc, $TraceDumpDepth)
}

# Mid-run filmstrip. The runtime writes <dir>/f_%06llu.png for every presented
# guest frame at or after START, up to COUNT frames, then quits by itself
# (src/runtime/runtime.cpp:4092-4114 `if (++framedump_written >= framedump_max)
# host_quit = true`), so a bounded capture needs no client and no kill.
#
# This is the ONLY way to film an INPUT route: `--tcp` returns at
# src/runtime/runtime.cpp:2611, before the GBARECOMP_INPUT_REPLAY loader at
# :3234, so a --tcp session ignores input replay entirely (and is silent, since
# --tcp also sets args.quiet at :945).
#
# Two more preconditions, both measured:
#   * the dump lives inside `if (args.window)` (runtime.cpp:4060-4092), and a
#     frame-bounded run defaults to headless (runtime.cpp:1429 only picks a
#     window when no --frames/--steps/--tcp was given), so -Window must pass
#     --window explicitly;
#   * present-in-place (the default for windowed play, runtime.cpp:3655-3666)
#     presents from a frame hook and bypasses the per-frame loop that contains
#     the dump, so this sets GBARECOMP_PRESENT_IN_PLACE=0.
$frameDir = $null
if ($FrameDumpCount -gt 0) {
    if (-not $Window) { Fail '-FrameDumpCount needs -Window: the runtime only dumps frames in its windowed per-frame loop (runtime.cpp:4060-4092).' }
    $frameDir = Join-Path $RouteDir "$Tag-frames"
    if (Test-Path $frameDir) { Remove-Item -Recurse -Force $frameDir }
    New-Item -ItemType Directory -Force -Path $frameDir | Out-Null
    $dumpStart = [Math]::Max(0, $FrameDumpStart)
    Set-Env 'GBARECOMP_FRAMEDUMP_DIR' $frameDir
    Set-Env 'GBARECOMP_FRAMEDUMP_START' "$dumpStart"
    Set-Env 'GBARECOMP_FRAMEDUMP_COUNT' "$FrameDumpCount"
    Set-Env 'GBARECOMP_PRESENT_IN_PLACE' '0'
    Step "frame dump -> $frameDir (start=$dumpStart count=$FrameDumpCount, present-in-place OFF)"
}

# -TcpObserve attaches a read-only debug server to a *windowed* run instead of
# replacing the run the way --tcp does (G13b: runtime.cpp:987-992 and :2892-2927).
# The distinction is the whole point of the flag: because the normal game loop
# is still running, GBARECOMP_INPUT_REPLAY still applies, so read_iwram /
# read_ewram / read_vram / read_pal / read_oam are available on a player-driven
# route. --tcp is the opposite: it returns before the replay loader
# (runtime.cpp:2445-2611 vs the loader at :3234) and silently ignores the route.
# Both preconditions below were measured, not assumed.
if ($TcpObserve -ne 0) {
    if ($TcpObserve -lt 1024 -or $TcpObserve -gt 65535) { Fail "-TcpObserve must be a TCP port (1024-65535), got $TcpObserve" }
    if (-not $Window) { Fail '-TcpObserve needs -Window: headless pump_host_input() returns immediately, so the port accepts a connection and never answers (G13b).' }
    if ($Frames -le 0) { Fail '-TcpObserve needs -Frames: an unbounded run cannot be joined to a snapshot schedule, and the observer needs a known final frame.' }
    Set-Env 'GBARECOMP_TCP_OBSERVE' "$TcpObserve"
    Step "read-only observe TCP on 127.0.0.1:$TcpObserve (reads only; input replay stays live)"
}

# The self-heal loader reloads previously compiled overlays from
# recomp_cache/<image_sha1>/<backend>/<os-arch>/ (reference/gbarecomp/src/runtime/
# overlay_loader.cpp:118) and counts those reloads as healed_native, which alone
# is enough to keep coverage at NOT_STATIC even when distinct_misses is 0 (G5).
# A validation run that must distinguish "covered" from "reloaded" points
# GBARECOMP_HEAL_CACHE (overlay_loader.cpp:445) at an empty directory.
if ($ColdCache) {
    $cacheRoot = Join-Path $RouteDir "cache-$Tag"
    if (Test-Path $cacheRoot) { Remove-Item -Recurse -Force $cacheRoot }
    New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null
    Set-Env 'GBARECOMP_HEAL_CACHE' $cacheRoot
    Step "cold heal cache -> $cacheRoot"
}

# The runtime's on-the-fly "self-heal" compiler defaults to the hardcoded MSYS2
# path C:/msys64/mingw64/bin/g++.exe (reference/gbarecomp/src/runtime/overlay_compile.cpp:66-75),
# which does not exist on this machine, so every heal attempt dies with
# "gcc exit -1" and the session stays on the interpreter bridge forever. Point
# it at the same MinGW g++ that built this host via the documented override.
$gxx = $null
foreach ($cand in @('g++.exe', 'gcc.exe')) {
    $found = Get-Command $cand -ErrorAction SilentlyContinue
    if ($found) { $gxx = Join-Path (Split-Path -Parent $found.Source) 'g++.exe'; break }
}
if ($gxx -and (Test-Path $gxx)) {
    Set-Env 'GBARECOMP_HEAL_CXX' ($gxx -replace '\\', '/')
    Step "self-heal compiler -> $gxx"
}

# ------------------------------------------------------------------------- run
$cmdLine = ($argList | ForEach-Object { ConvertTo-QuotedArg $_ }) -join ' '
Step "$Exe $cmdLine"
Step "coverage -> $coverage"
$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $Exe -ArgumentList $cmdLine -NoNewWindow -PassThru `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog
if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    $proc.Kill()
    Step "TIMEOUT after ${TimeoutSeconds}s — process killed (the runtime should have been frame-bounded)"
    $exit = -1
} else {
    $exit = $proc.ExitCode
}
$sw.Stop()

# ---------------------------------------------------------------------- report
$result = [ordered]@{
    tag        = $Tag
    command    = "$Exe $cmdLine"
    frames     = $Frames
    steps      = $Steps
    strict     = [bool]$StrictStatic
    headless   = -not $Window
    tcp_observe = $TcpObserve
    exit_code  = $exit
    seconds    = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    log        = "logs/routes/$Tag.log"
    save_path  = $SavePath
}
if ($frameDir) {
    $dumped = @(Get-ChildItem -Path $frameDir -Filter 'f_*.png' -ErrorAction SilentlyContinue | Sort-Object Name)
    $result.frame_dump_dir   = "logs/routes/$Tag-frames"
    $result.frame_dump_start = [Math]::Max(0, $FrameDumpStart)
    $result.frame_dump_count = $dumped.Count
    if ($dumped.Count -gt 0) {
        $result.frame_dump_first = $dumped[0].Name
        $result.frame_dump_last  = $dumped[-1].Name
    }
    Step "frame dump: $($dumped.Count) png(s) in $frameDir"
}

Step "exit=$exit  elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,1))s"
if (Test-Path $errLog) {
    $errTail = Get-Content $errLog -Tail 25
    if ($errTail) { Step "stderr tail:"; $errTail | ForEach-Object { Write-Host "    $_" } }
}

if (Test-Path $coverage) {
    $cov = Get-Content $coverage -Raw | ConvertFrom-Json
    $result.coverage            = $cov.coverage
    $result.distinct_misses     = $cov.distinct_misses
    $result.interpreted_insns   = $cov.interpreted_insns
    $result.healed_native       = $cov.healed_native
    $result.failed              = $cov.failed
    $result.jump_table_regions  = $cov.jump_table_candidate_regions
    Step ("coverage={0} distinct_misses={1} interpreted_insns={2} healed_native={3} native_calls={4} failed={5} jt_regions={6}" -f `
        $cov.coverage, $cov.distinct_misses, $cov.interpreted_insns, $cov.healed_native, $cov.native_calls, $cov.failed, $cov.jump_table_candidate_regions)
    if ($cov.misses -and $cov.misses.Count -gt 0) {
        Step "first misses:"
        $cov.misses | Select-Object -First 12 | ForEach-Object {
            Write-Host ("    pc={0} mode={1} bridged={2} healed={3} calls={4} jt={5}" -f `
                $_.pc, $_.mode, $_.bridged, $_.healed, $_.native_calls, $_.jump_table_candidate)
        }
    }
} else {
    $result.coverage = 'NO_COVERAGE_FILE'
    Step 'no coverage JSON was written'
}
if (Test-Path $missFrag) { $result.miss_fragment = "logs/routes/$Tag-misses.toml.frag" }

$resultPath = Join-Path $RouteDir "$Tag-result.json"
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
Step "result -> $resultPath"

# ------------------------------------------------------------------- restore env
foreach ($k in $saved.Keys) {
    if ($null -eq $saved[$k]) { Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue }
    else { Set-Item -Path "Env:$k" -Value $saved[$k] }
}

exit $exit
