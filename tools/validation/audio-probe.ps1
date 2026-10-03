<#
    audio-probe.ps1 — M4 audio evidence over the sanctioned TCP debug server.

    The framework has no headless audio dump (only the SDL window consumes mixed
    samples), but `src/debug/tcp_debug_server.cpp` exposes `audio_cap`, a window
    over the ALWAYS-ON capture ring (`gba_audio.h:93`, kCapRingSize = 1<<18
    samples, ~8 s at 32768 Hz), plus `read_io` for the sound registers and
    `audio_state` for the channel/FIFO state. This tool drives a bounded
    headless run, waits until the guest reaches the requested frame (the title
    screen, for M4), then asks the server for the mixed samples and reports
    what the mixer actually produced.

    It never writes guest state and never reads the ROM/BIOS: it reports sample
    statistics only. Output: logs/routes/<tag>-audio.json plus a summary line.

    Example
      tools/validation/audio-probe.ps1 -Tag audio-title -WaitFrame 5300
#>
[CmdletBinding()]
param(
    [string]$Exe,                    # defaults to build\host\WarioLand4Recomp.exe
    [string]$Tag = 'audio-title',
    [int]$Frames = 9000,             # bounded total run length
    [int]$Port = 19842,              # --tcp port (framework default)
    [int]$WaitFrame = 5300,          # guest frame to sample at
    [int]$Count = 4096,              # samples to request (<= 262144)
    [int]$TimeoutSeconds = 420
)

$ErrorActionPreference = 'Stop'
$Root   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$LogDir = Join-Path $Root 'logs\routes'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not $Exe) { $Exe = Join-Path $Root 'build\host\WarioLand4Recomp.exe' }
if (-not (Test-Path -LiteralPath $Exe)) { throw "Executable not found: $Exe" }

$roms = @(Get-ChildItem -LiteralPath $Root -Filter '*.gba' -File)
if ($roms.Count -ne 1) { throw "Expected exactly one ROM in $Root, found $($roms.Count)." }
$Rom  = $roms[0].FullName
$Bios = Join-Path $Root 'bios\gba_bios.bin'
$Cfg  = Join-Path $Root 'game.toml'
foreach ($p in @($Bios, $Cfg)) { if (-not (Test-Path -LiteralPath $p)) { throw "Missing $p" } }

# Never let the asset picker reach its modal dialog (framework issue F1).
$ExeDir = Split-Path -Parent $Exe
Set-Content -LiteralPath (Join-Path $ExeDir 'rom.cfg')  -Value $Rom  -Encoding Ascii
Set-Content -LiteralPath (Join-Path $ExeDir 'bios.cfg') -Value $Bios -Encoding Ascii

# Framework issue F2: the self-heal compiler path is hardcoded to MSYS2.
# Point it at whatever g++ is on PATH instead of a machine-specific literal.
$HealGxx = Get-Command g++.exe -ErrorAction SilentlyContinue
if (-not $HealGxx) { $HealGxx = Get-Command gcc.exe -ErrorAction SilentlyContinue }
if ($HealGxx) { $env:GBARECOMP_HEAL_CXX = ($HealGxx.Source -replace '\\', '/') }

$LogPath = Join-Path $LogDir "$Tag.log"
$ErrPath = Join-Path $LogDir "$Tag.err"

function ConvertTo-QuotedArg([string]$a) {
    if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' }
    return $a
}
$argList = @('--rom', $Rom, '--bios', $Bios, '--config', $Cfg,
             '--frames', "$Frames", '--no-window', '--tcp', "$Port")
$cmdLine = ($argList | ForEach-Object { ConvertTo-QuotedArg $_ }) -join ' '

Write-Host "==> $Exe $cmdLine"
$proc = Start-Process -FilePath $Exe -ArgumentList $cmdLine -WorkingDirectory $Root `
                      -RedirectStandardOutput $LogPath -RedirectStandardError $ErrPath -PassThru

$client = $null
$reply  = @{}
try {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    # 1. Attach to the debug server.
    while (-not $client -and (Get-Date) -lt $deadline) {
        try {
            $c = New-Object System.Net.Sockets.TcpClient
            $c.Connect('127.0.0.1', $Port)
            $client = $c
        } catch {
            Start-Sleep -Milliseconds 400
            if ($proc.HasExited) { throw "Run exited early (exit $($proc.ExitCode)); see $ErrPath" }
        }
    }
    if (-not $client) { throw "Debug server on port $Port never accepted a connection." }

    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    function Send-Cmd([string]$json) {
        $writer.WriteLine($json)
        $line = $reader.ReadLine()
        if ($null -eq $line) { throw "Debug server closed the connection." }
        return ($line | ConvertFrom-Json)
    }

    # The `--tcp` core starts PAUSED and only steps frames in RS_RUNNING/RS_STEP
    # (`runtime.cpp:2463 int ctl_state = RS_PAUSED;`, loop at :2478-2497), so
    # nothing runs until we resume. `continue`/resume is NON-BLOCKING
    # (`tcp_debug_server.cpp:765-768`): the game free-runs while we observe.
    $null = Send-Cmd '{"cmd":"continue","id":1}'
    Write-Host "==> resumed (free-run); waiting for guest frame >= $WaitFrame"
    $frame = 0
    $run = '?'
    $polls = 0
    while ((Get-Date) -lt $deadline) {
        $f = Send-Cmd '{"cmd":"run_status","id":1}'
        if ($f.frame) { $frame = [int]$f.frame }
        if ($f.run)   { $run   = "$($f.run)" }
        if ($frame -ge $WaitFrame) { break }
        if ($proc.HasExited) { throw "Run exited before frame $WaitFrame (reached $frame); see $ErrPath" }
        if ($frame -eq 0 -and ($polls % 20) -eq 19) {
            Write-Host "==> still at frame 0 (run=$run parked=$($f.parked) pc=$($f.pc))"
        }
        $polls++
        Start-Sleep -Milliseconds 250
    }
    Write-Host "==> guest frame = $frame (run=$run)"
    # Park at a frame boundary before sampling: snapshots are only valid at the
    # dispatch boundary between step calls, and parking makes the sampled frame
    # and the frame number agree.
    $null = Send-Cmd '{"cmd":"pause","id":1}'

    # read_io answers {"ok":true,"base":N,"len":L,"data":<hex bytes>} - there is no
    # `value` field, so decode `data` as little-endian bytes ourselves.
    function Get-IoValue($r) {
        if ($null -eq $r -or -not $r.data) { return $null }
        $h = "$($r.data)" -replace '^0x', '' -replace '"', ''
        $u = 0
        for ($i = $h.Length - 2; $i -ge 0; $i -= 2) {
            $u = ($u -shl 8) -bor [Convert]::ToInt32($h.Substring($i, 2), 16)
        }
        return $u
    }

    # 2. Sound registers the guest programmed (SOUNDCNT_L/H/X, SOUNDBIAS).
    $soundcnt = @{}
    $rawio    = @{}
    foreach ($kv in @(@{n='SOUNDCNT_L'; a='0x04000080'}, @{n='SOUNDCNT_H'; a='0x04000082'},
                      @{n='SOUNDCNT_X'; a='0x04000084'}, @{n='SOUNDBIAS';  a='0x04000088'},
                      @{n='SOUND1CNT_L';a='0x04000060'})) {
        $r = Send-Cmd ("{`"cmd`":`"read_io`",`"addr`":`"$($kv.a)`",`"len`":2,`"id`":2}")
        $v = Get-IoValue $r
        $rawio[$kv.n] = "$($r.data)"
        if ($null -eq $v) { $soundcnt[$kv.n] = 'n/a' }
        else { $soundcnt[$kv.n] = ('0x{0:X4}={0}' -f $v) }
    }

    # 3. Channel/FIFO state (trimmed: full text goes to the evidence file).
    $state = Send-Cmd '{"cmd":"audio_state","id":3}'

    # 4. Mixed samples + per-channel samples from the always-on capture ring.
    $cap = Send-Cmd ("{`"cmd`":`"audio_cap`",`"count`":$Count,`"id`":4}")

    function ConvertFrom-HexI16([string]$hex) {
        if (-not $hex) { return @() }
        $h = $hex -replace '^0x', '' -replace '"', ''
        # 4 hex chars (2 bytes, little-endian) per i16 sample.
        $n = [int]($h.Length / 4)
        $out = New-Object 'int[]' $n
        for ($i = 0; $i -lt $n; $i++) {
            $lo = [Convert]::ToInt32($h.Substring($i * 4, 2), 16)
            $hi = [Convert]::ToInt32($h.Substring($i * 4 + 2, 2), 16)
            $u = $lo -bor ($hi -shl 8)
            if ($u -ge 32768) { $u -= 65536 }
            $out[$i] = $u
        }
        return $out
    }

    function Measure-Samples([int[]]$s) {
        if ($s.Count -eq 0) { return @{ count = 0; peak = 0; rms = 0.0; nonzero = 0; nonzero_pct = 0.0 } }
        $peak = 0; $sumsq = 0.0; $nz = 0
        foreach ($v in $s) {
            $a = [Math]::Abs($v)
            if ($a -gt $peak) { $peak = $a }
            $sumsq += ([double]$v * $v)
            if ($v -ne 0) { $nz++ }
        }
        return @{
            count       = $s.Count
            peak        = $peak
            rms         = [Math]::Round([Math]::Sqrt($sumsq / $s.Count), 2)
            nonzero     = $nz
            nonzero_pct = [Math]::Round(100.0 * $nz / $s.Count, 2)
        }
    }

    $stats = @{}
    foreach ($k in 'mixed', 'ch1', 'ch2', 'ch3', 'ch4', 'direct_a', 'direct_b') {
        $stats[$k] = Measure-Samples (ConvertFrom-HexI16 $cap.$k)
    }

    $evidence = [ordered]@{
        tag              = $Tag
        frame            = $frame
        requested_frames = $Frames
        sample_rate      = $cap.rate
        captured_first   = $cap.first
        captured_count   = $cap.count
        mixer_head       = $cap.head
        ring_oldest      = $cap.oldest
        sound_control    = $soundcnt
        sound_control_raw= $rawio
        stats            = $stats
        audio_state_raw  = $state
        command          = "$Exe $cmdLine"
        log              = "logs/routes/$Tag.log"
    }
    $jsonPath = Join-Path $LogDir "$Tag-audio.json"
    ($evidence | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    Write-Host "==> SOUNDCNT_L=$($soundcnt.SOUNDCNT_L) SOUNDCNT_H=$($soundcnt.SOUNDCNT_H) SOUNDCNT_X=$($soundcnt.SOUNDCNT_X)"
    Write-Host "==> samples generated (head) = $($cap.head), ring oldest = $($cap.oldest), rate = $($cap.rate)"
    foreach ($k in 'mixed', 'ch1', 'ch2', 'ch3', 'ch4', 'direct_a', 'direct_b') {
        $s = $stats[$k]
        Write-Host ("==> {0,-9} n={1,-6} peak={2,-6} rms={3,-8} nonzero={4} ({5}%)" -f $k, $s.count, $s.peak, $s.rms, $s.nonzero, $s.nonzero_pct)
    }
    if ($stats['mixed'].count -eq 0) {
        Write-Host "==> VERDICT: NO AUDIO CAPTURED (capture ring empty at this frame)"
    } elseif ($stats['mixed'].nonzero -eq 0) {
        Write-Host "==> VERDICT: SILENT (samples captured, but every mixed sample is zero)"
    } else {
        Write-Host "==> VERDICT: NON-SILENT MIXED AUDIO at frame $frame"
    }
    Write-Host "==> evidence -> $jsonPath"
}
finally {
    if ($client) { $client.Close() }
    if ($proc -and -not $proc.HasExited) {
        $proc.WaitForExit(15000) | Out-Null
        if (-not $proc.HasExited) { $proc.Kill() }
    }
}
