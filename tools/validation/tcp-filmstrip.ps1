<#
.SYNOPSIS
    Capture PNG frames from ONE `--tcp` runtime run, at a list of guest frames.

.DESCRIPTION
    run-route.ps1 can only dump the LAST frame of a route, so answering "when
    inside this 30,000-frame route did the hearts drop / the room change?" used
    to cost one process launch per observation. The runtime's TCP debug server
    answers {"cmd":"screenshot"} from the latched framebuffer
    (gbarecomp-main/src/debug/tcp_debug_server.cpp:971), so a single run can
    yield a whole film strip.

    Wire protocol (see the framework's TCP.md): one JSON object per line, one
    response line per request. A `--tcp` instance starts PARKED
    (reference/gbarecomp/src/runtime/runtime.cpp:2463 `int ctl_state = RS_PAUSED;`),
    so the first thing sent is {"cmd":"continue"}; the core then free-runs and
    the server stays responsive.

    Implemented commands used here:
      continue    -> {"ok":true,"run":"running"}          (non-blocking)
      run_status  -> {"ok":true,"run":…,"frame":N,…}      (frame_counter at :678)
      pause       -> pauses, then answers run_status
      screenshot  -> {"ok":true,"w":W,"h":H,"data":<hex RGB>}

    NOT implemented in the framework despite TCP.md documenting them:
    run_to_frame / run_to_pc / run_to_vblank / run_to_swi (docs/KNOWN_ISSUES.md F7),
    which is why this script polls run_status instead of asking the server to run
    to a frame.

    Two measured traps:
      * --frames does NOT bound a --tcp run: a session started with --frames 6200
        and driven continue → pause → continue passed 81,000 frames without
        exiting, and a --tcp run with no client attached never leaves frame 0
        (the core starts parked). This tool therefore kills its child after the
        last capture instead of waiting for the frame bound.
      * `pwsh -File … -Marks 13000,14000` delivers the comma list as ONE string,
        so [int[]] binding produces a single mangled mark; -Marks is taken as
        [string[]] and split here.

.EXAMPLE
    pwsh -File tools/validation/tcp-filmstrip.ps1 -Tag strip-title -Frames 6200 `
        -Marks "5300,6000" -InputReplay tests/input/start-press.keyinput.txt
#>
param(
    [string]$Exe,
    [string]$Tag = 'strip',
    [int]$Frames = 30000,
    [string[]]$Marks = @(),
    [string]$InputReplay,
    [string]$SavePath,
    [switch]$KeepSave,
    [int]$Port = 19901,
    [int]$Scale = 1,
    [int]$PollMs = 40,
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RouteDir = Join-Path $Root 'logs\routes'
New-Item -ItemType Directory -Force -Path $RouteDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

if (-not $Exe) { $Exe = Join-Path $Root 'build\host\WarioLand4Recomp.exe' }
if (-not (Test-Path $Exe)) { Fail "Executable not found: $Exe (run tools/regeneration/build-host.ps1)" }
if (-not $Marks -or $Marks.Count -eq 0) { Fail '-Marks is required, e.g. -Marks "13000,14000,15000"' }
# `pwsh -File … -Marks 13000,14000` hands the whole comma list over as ONE string,
# so a [int[]] binding silently yields a single mangled value ("13000,14000") and
# the poll loop then waits for a frame that never arrives. Split it ourselves.
$markList = @($Marks | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } |
              Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ } | Sort-Object -Unique)
if ($markList.Count -eq 0) { Fail '-Marks contained no frame numbers.' }
foreach ($m in $markList) { if ($m -lt 1) { Fail "-Marks value $m is not a frame number." } }

# ------------------------------------------------------------------ verified in
$identity = Get-Content -LiteralPath (Join-Path $Root 'docs\ROM_IDENTITY.json') -Raw | ConvertFrom-Json
$roms = @(Get-ChildItem -LiteralPath $Root -Filter '*.gba' -File)
if ($roms.Count -ne 1) { Fail "Expected exactly one .gba in $Root, found $($roms.Count)." }
$rom = $roms[0].FullName
if ((Get-FileHash $rom -Algorithm SHA256).Hash.ToLower() -ne $identity.rom.sha256) { Fail 'ROM SHA-256 mismatch.' }
$bios = Join-Path $Root 'bios\gba_bios.bin'
if (-not (Test-Path $bios)) { Fail "BIOS dump not found at $bios" }
$config = Join-Path $Root 'game.toml'

# The runtime's ROM/BIOS resolution chain ENDS IN A MODAL FILE DIALOG
# (reference/gbarecomp/src/runtime/asset_picker.cpp:221-243) with no
# non-interactive escape hatch, so seed the picker cache next to the exe and
# quote every argument (see docs/KNOWN_ISSUES.md F1/G1).
$exeDir = Split-Path -Parent $Exe
Set-Content -LiteralPath (Join-Path $exeDir 'rom.cfg')  -Value $rom  -Encoding ASCII
Set-Content -LiteralPath (Join-Path $exeDir 'bios.cfg') -Value $bios -Encoding ASCII

function ConvertTo-QuotedArg([string]$a) {
    if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' }
    return $a
}

# ------------------------------------------------------------ route save isolation
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
# TCP port 0 is invalid here: an explicit port is required so two concurrent
# runs cannot steal each other's debug socket.
$argList = @('--rom', $rom, '--bios', $bios, '--config', $config,
             '--frames', "$Frames", '--no-window',
             '--tcp', "$Port", '--save-path', $SavePath)

# ------------------------------------------------------------------ environment
$saved = @{}
function Set-Env([string]$name, [string]$value) {
    if (-not $saved.ContainsKey($name)) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
    Set-Item -Path "Env:$name" -Value $value
}
Set-Env 'GBARECOMP_COVERAGE_JSON' (Join-Path $RouteDir "$Tag-coverage.json")
Set-Env 'GBARECOMP_MISS_FRAG'     (Join-Path $RouteDir "$Tag-misses.toml.frag")
Set-Env 'GBARECOMP_NO_LAUNCHER'   '1'
Set-Env 'GBARECOMP_HANG_WATCHDOG' '1'
Set-Env 'GBARECOMP_HANG_SECONDS'  '120'
if ($InputReplay) { Set-Env 'GBARECOMP_INPUT_REPLAY' $InputReplay }
# Print the resolved values, not the intent: an input route that silently runs
# without replay is indistinguishable from a route whose input did nothing
# (docs/VALIDATION.md rule 10 — the smoke test had exactly this bug once).
Step ("env GBARECOMP_INPUT_REPLAY='{0}'  COVERAGE_JSON='{1}'" -f $env:GBARECOMP_INPUT_REPLAY, $env:GBARECOMP_COVERAGE_JSON)
$gxx = $null
foreach ($cand in @('g++.exe', 'gcc.exe')) {
    $found = Get-Command $cand -ErrorAction SilentlyContinue
    if ($found) { $gxx = Join-Path (Split-Path -Parent $found.Source) 'g++.exe'; break }
}
if ($gxx -and (Test-Path $gxx)) { Set-Env 'GBARECOMP_HEAL_CXX' ($gxx -replace '\\', '/') }

# ------------------------------------------------------------------------- run
$cmdLine = ($argList | ForEach-Object { ConvertTo-QuotedArg $_ }) -join ' '
Step "$Exe $cmdLine"
$outLog = Join-Path $RouteDir "$Tag.log"
$errLog = Join-Path $RouteDir "$Tag.err.log"
$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $Exe -ArgumentList $cmdLine -NoNewWindow -PassThru `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog

function Connect-Dbg([int]$port, [int]$timeoutMs = 20000) {
    $deadline = (Get-Date).AddMilliseconds($timeoutMs)
    while ((Get-Date) -lt $deadline) {
        try {
            $c = [Net.Sockets.TcpClient]::new()
            $c.Connect('127.0.0.1', $port)
            $c.ReceiveTimeout = 20000
            return $c
        } catch { Start-Sleep -Milliseconds 100 }
    }
    return $null
}

$client = Connect-Dbg $Port
if (-not $client) { $proc.Kill(); Fail "TCP debug server never came up on port $Port (see $errLog)" }
Step "tcp connected on 127.0.0.1:$Port"
$stream = $client.GetStream()
$writer = [IO.StreamWriter]::new($stream); $writer.NewLine = "`n"; $writer.AutoFlush = $true
$reader = [IO.StreamReader]::new($stream)

$script:reqId = 0
function Send-Cmd([string]$cmd) {
    $script:reqId++
    $writer.WriteLine((('{{"cmd":"{0}","id":{1}}}' -f $cmd, $script:reqId)))
    $line = $reader.ReadLine()
    if ($null -eq $line) { throw "tcp: no response to $cmd (runtime exited?)" }
    return ($line | ConvertFrom-Json)
}

function Frame-Now {
    # Deliberately NOT written as `[int](Send-Cmd 'run_status').frame`: the cast
    # binds tighter than the member access, so that form casts the whole
    # PSCustomObject (and silently yields 0 in the polling loop — measured, and
    # the reason the first version of this script spun to its 900 s timeout).
    $st = Send-Cmd 'run_status'
    return [int]$st.frame
}

# Decode {w,h,data:<hex RGB>} straight into a 24bpp BGR bitmap.
function Save-Frame($shot, [string]$out) {
    $w = [int]$shot.w; $h = [int]$shot.h; $hex = $shot.data
    $n = $hex.Length / 2
    $raw = New-Object byte[] $n
    for ($i = 0; $i -lt $n; $i++) { $raw[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }
    $bpp = [int]($n / ($w * $h))
    $bgr = New-Object byte[] ($w * $h * 3)
    for ($p = 0; $p -lt ($w * $h); $p++) {
        $s = $p * $bpp; $d = $p * 3
        $bgr[$d] = $raw[$s + 2]; $bgr[$d + 1] = $raw[$s + 1]; $bgr[$d + 2] = $raw[$s]
    }
    $bmp  = New-Object System.Drawing.Bitmap($w, $h, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $rect = New-Object System.Drawing.Rectangle(0, 0, $w, $h)
    $bd   = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::WriteOnly, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    for ($y = 0; $y -lt $h; $y++) {
        [System.Runtime.InteropServices.Marshal]::Copy($bgr, $y * $w * 3, [IntPtr]::Add($bd.Scan0, $y * $bd.Stride), $w * 3)
    }
    $bmp.UnlockBits($bd)
    $target = $bmp
    if ($Scale -gt 1) {
        $big = New-Object System.Drawing.Bitmap(($w * $Scale), ($h * $Scale))
        $gx = [System.Drawing.Graphics]::FromImage($big)
        $gx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
        $gx.DrawImage($bmp, 0, 0, $w * $Scale, $h * $Scale)
        $gx.Dispose(); $bmp.Dispose(); $target = $big
    }
    $target.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $target.Dispose()
    return @{ w = $w; h = $h; bpp = $bpp }
}

Add-Type -AssemblyName System.Drawing

# The core is parked: start it.
Send-Cmd 'continue' | Out-Null

$captures = @()
try {
    foreach ($mark in $markList) {
        $lastReport = Get-Date
        while ($true) {
            $f = Frame-Now
            if ($f -ge $mark) { break }
            Start-Sleep -Milliseconds $PollMs
            if (((Get-Date) - $lastReport).TotalSeconds -ge 2) {
                Step ("  waiting for frame {0}: now at {1} ({2}s)" -f $mark, $f, [int]$sw.Elapsed.TotalSeconds)
                $lastReport = Get-Date
            }
            if ($sw.Elapsed.TotalSeconds -gt $TimeoutSeconds) { throw "timeout waiting for frame $mark (at $f)" }
            if ($proc.HasExited) { throw "runtime exited before frame $mark (at $f)" }
        }
        $null = Send-Cmd 'pause'
        $frameAt = Frame-Now
        $out = Join-Path $RouteDir ("{0}-f{1}.png" -f $Tag, $mark)
        $info = Save-Frame (Send-Cmd 'screenshot') $out
        $sha = (Get-FileHash $out -Algorithm SHA256).Hash.ToLower()
        Step ("frame {0,6} -> {1}  ({2}x{3})  sha256={4}" -f $frameAt, (Split-Path -Leaf $out), $info.w, $info.h, $sha.Substring(0, 16))
        $captures += [ordered]@{ mark = $mark; frame = $frameAt; file = "logs/routes/$Tag-f$mark.png"; sha256 = $sha }
        Send-Cmd 'continue' | Out-Null
    }
} finally {
    # A TCP session keeps the core running past --frames, so end the session
    # explicitly (`quit` answers {"ok":true,"bye":true}, tcp_debug_server.cpp:1172)
    # and make sure no orphan keeps burning a core.
    try { Send-Cmd 'quit' | Out-Null } catch { }
    try { $client.Close() } catch { }
    if (-not $proc.HasExited) {
        if (-not $proc.WaitForExit(10000)) { $proc.Kill(); Step 'process killed after the last capture' }
    }
}
$sw.Stop()
$exit = if ($proc.HasExited) { $proc.ExitCode } else { -1 }
Step "exit=$exit  elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,1))s"

$result = [ordered]@{
    tag       = $Tag
    frames    = $Frames
    exit_code = $exit
    seconds   = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    input     = $InputReplay
    save_path = $SavePath
    captures  = $captures
}
$resultPath = Join-Path $RouteDir "$Tag-filmstrip.json"
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
Step "filmstrip -> $resultPath"
if (Test-Path (Join-Path $RouteDir "$Tag-coverage.json")) {
    $cov = Get-Content (Join-Path $RouteDir "$Tag-coverage.json") -Raw | ConvertFrom-Json
    Step ("coverage={0} distinct_misses={1} interpreted_insns={2}" -f $cov.coverage, $cov.distinct_misses, $cov.interpreted_insns)
}

foreach ($k in $saved.Keys) {
    if ($null -eq $saved[$k]) { Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue }
    else { Set-Item -Path "Env:$k" -Value $saved[$k] }
}
exit $exit
