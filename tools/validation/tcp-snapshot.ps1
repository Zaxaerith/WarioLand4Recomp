<#
.SYNOPSIS
    Snapshot a guest memory space at a list of frames from ONE `--tcp` run.

.DESCRIPTION
    A screen tells you *that* something changed; guest memory tells you *what*.
    The runtime's TCP debug server exposes the memory spaces directly
    (gbarecomp-main/src/debug/tcp_debug_server.cpp):

        read_iwram  :796   -> {"ok":true,"base":0x03000000,"len":32768,"data":<hex>}
        read_ewram  :801   -> 256 KiB
        read_vram   :791   -> 96 KiB
        read_pal    :786   -> 1 KiB
        read_oam    :781   -> 1 KiB

    All five are served by cmd_read_region() (:144), which REQUIRES an explicit
    "addr" and "len" in the request — {"cmd":"read_iwram"} alone answers
    {"ok":false,"error":"missing addr/len"}. So one long run can yield a whole
    time series of the guest's own variables, which is how a health counter or a
    coin counter gets located without guessing from pixels. Pairs with
    tools/validation/snapshot-diff.py.

    LIMITATION (docs/KNOWN_ISSUES.md F8): `--tcp` returns from main() before the
    input-replay loader runs, so a TCP session can only drive NO-INPUT routes.
    The game's own attract demo is exactly that, and it is the deepest route in
    the repo (19,000 frames = two demo levels), so it is the one to snapshot.

    Two measured traps inherited from tcp-filmstrip.ps1:
      * --frames does NOT bound a --tcp run (the core starts parked and the
        server keeps it running), so the child is killed after the last snapshot.
      * `pwsh -File … -Marks 500,1000` delivers the comma list as ONE string;
        -Marks is [string[]] and is split here. If -Marks is omitted the marks are
        generated from -First/-Every/-Frames.

.EXAMPLE
    pwsh -File tools/validation/tcp-snapshot.ps1 -Tag snap-demo -Frames 19000 `
        -First 1000 -Every 1000 -Space iwram -Port 19971
#>
param(
    [string]$Exe,
    [string]$Tag = 'snap',
    [int]$Frames = 19000,
    [int]$First = 1000,
    [int]$Every = 1000,
    [string[]]$Marks = @(),
    [ValidateSet('iwram', 'ewram', 'vram', 'pal', 'oam')]
    [string]$Space = 'iwram',
    [int]$Port = 19901,
    [int]$PollMs = 40,
    [int]$TimeoutSeconds = 900,
    [string]$SavePath,
    [switch]$KeepSave
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RouteDir = Join-Path $Root 'logs\routes'
$SnapDir = Join-Path $RouteDir "$Tag-$Space"
New-Item -ItemType Directory -Force -Path $RouteDir | Out-Null
New-Item -ItemType Directory -Force -Path $SnapDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

if (-not $Exe) { $Exe = Join-Path $Root 'build\host\WarioLand4Recomp.exe' }
if (-not (Test-Path $Exe)) { Fail "Executable not found: $Exe (run tools/regeneration/build-host.ps1)" }

# `pwsh -File … -Marks 500,1000` hands the whole comma list over as ONE string.
if ($Marks -and $Marks.Count -gt 0) {
    $markList = @($Marks | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } |
                  Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ } | Sort-Object -Unique)
} else {
    $markList = @()
    for ($f = $First; $f -le $Frames; $f += $Every) { $markList += $f }
}
if ($markList.Count -eq 0) { Fail 'No marks to capture (check -First/-Every/-Frames or -Marks).' }
foreach ($m in $markList) { if ($m -lt 0) { Fail "-Marks value $m is not a frame number." } }

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
# (asset_picker.cpp:221-243), so seed the picker cache and quote every argument.
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
    }
}

# --------------------------------------------------------------------- arguments
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
            $c.ReceiveTimeout = 30000
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

# The read_* handlers are cmd_read_region() (tcp_debug_server.cpp:144), which
# REQUIRES an explicit "addr" and "len" and answers {"ok":false,"error":"missing
# addr/len"} otherwise — a bare {"cmd":"read_iwram"} does not work. The size caps
# are the ones the handlers pass in (":781-805").
$Spaces = @{
    iwram = @{ cmd = 'read_iwram'; addr = 0x03000000; size = 32768 }
    ewram = @{ cmd = 'read_ewram'; addr = 0x02000000; size = 262144 }
    vram  = @{ cmd = 'read_vram';  addr = 0x06000000; size = 98304 }
    pal   = @{ cmd = 'read_pal';   addr = 0x05000000; size = 1024 }
    oam   = @{ cmd = 'read_oam';   addr = 0x07000000; size = 1024 }
}

$script:reqId = 0
function Send-Cmd([string]$cmd, [hashtable]$fields = @{}) {
    $script:reqId++
    $parts = @(('"cmd":"{0}"' -f $cmd))
    foreach ($k in $fields.Keys) { $parts += ('"{0}":{1}' -f $k, $fields[$k]) }
    $parts += ('"id":{0}' -f $script:reqId)
    $writer.WriteLine('{' + ($parts -join ',') + '}')
    $line = $reader.ReadLine()
    if ($null -eq $line) { throw "tcp: no response to $cmd (runtime exited?)" }
    return ($line | ConvertFrom-Json)
}

function Frame-Now {
    # NOT `[int](Send-Cmd 'run_status').frame`: the cast binds tighter than the
    # member access and silently yields 0 (the bug that once spun this family of
    # tools to its timeout).
    $st = Send-Cmd 'run_status'
    return [int]$st.frame
}

function Read-Space([string]$space) {
    $spec = $Spaces[$space]
    $resp = Send-Cmd $spec.cmd @{ addr = $spec.addr; len = $spec.size }
    if (-not $resp.ok) {
        $why = if ($resp.error) { $resp.error } else { 'ok=false' }
        throw "$($spec.cmd) failed: $why"
    }
    if ([int]$resp.len -ne $spec.size) { Step "  note: asked for $($spec.size) bytes, got $($resp.len)" }
    $hex = $resp.data
    $n = [int]($hex.Length / 2)
    $bytes = New-Object byte[] $n
    for ($i = 0; $i -lt $n; $i++) { $bytes[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }
    return $bytes
}

Send-Cmd 'continue' | Out-Null

$snaps = @()
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
        $bytes = Read-Space $Space
        $file = Join-Path $SnapDir ("{0}-{1}-f{2:D6}.bin" -f $Tag, $Space, $frameAt)
        [System.IO.File]::WriteAllBytes($file, $bytes)
        $sha = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
        Step ("frame {0,6} -> {1}  ({2} bytes)  sha256={3}" -f $frameAt, (Split-Path -Leaf $file), $bytes.Length, $sha.Substring(0, 16))
        $snaps += [ordered]@{ mark = $mark; frame = $frameAt; bytes = $bytes.Length
                              file = "logs/routes/$Tag-$Space/$(Split-Path -Leaf $file)"; sha256 = $sha }
        Send-Cmd 'continue' | Out-Null
    }
} finally {
    try { Send-Cmd 'quit' | Out-Null } catch { }
    try { $client.Close() } catch { }
    if (-not $proc.HasExited) {
        if (-not $proc.WaitForExit(10000)) { $proc.Kill(); Step 'process killed after the last snapshot' }
    }
}
$sw.Stop()
$exit = if ($proc.HasExited) { $proc.ExitCode } else { -1 }
Step "exit=$exit  elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,1))s"

$result = [ordered]@{
    tag        = $Tag
    space      = $Space
    frames     = $Frames
    exit_code  = $exit
    seconds    = [math]::Round($sw.Elapsed.TotalSeconds, 2)
    save_path  = $SavePath
    snap_dir   = "logs/routes/$Tag-$Space"
    snapshots  = $snaps
}
$resultPath = Join-Path $RouteDir "$Tag-snapshots.json"
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding UTF8
Step "snapshots -> $resultPath"
Step "analyse with: python tools/validation/snapshot-diff.py --dir logs/routes/$Tag-$Space --space $Space"

foreach ($k in $saved.Keys) {
    if ($null -eq $saved[$k]) { Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue }
    else { Set-Item -Path "Env:$k" -Value $saved[$k] }
}
exit $exit
