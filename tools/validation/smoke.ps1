<#
    smoke.ps1 — one command that answers "did my change break the game?"

    It runs a small fixed set of routes (no host input except the scripted
    traces), and checks three things per route:

      1. the process exited 0 and wrote a coverage JSON,
      2. every dispatch miss is in the documented dynamic set
         (tests/routes/smoke-expectations.json -> allowed_miss_prefix),
      3. the final frame is byte-identical to the recorded one.

    It also runs the persistence round trip (write in one process, load in
    another) because that is the one axis a single run cannot cover.

    Recording: the expectations live in tests/routes/smoke-expectations.json.
    After a change that legitimately alters a frame or a miss count, re-record
    with

        tools/validation/smoke.ps1 -Record

    and review the diff of that file — the smoke test is only as honest as its
    recorded expectations.

    Examples
      tools/validation/smoke.ps1                 # full check (~5 min)
      tools/validation/smoke.ps1 -Quick          # skip the three 13,500-frame routes
      tools/validation/smoke.ps1 -Record         # re-record the expectations
#>
[CmdletBinding()]
param(
    [string]$Exe,
    [switch]$Quick,             # skip the long gameplay route
    [switch]$SkipPersistence,   # skip the save round trip
    [switch]$Record             # write/refresh smoke-expectations.json
)

$ErrorActionPreference = 'Stop'
$Root   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RouteDir = Join-Path $Root 'logs\routes'
New-Item -ItemType Directory -Force -Path $RouteDir | Out-Null
$Runner = Join-Path $PSScriptRoot 'run-route.ps1'
$ExpPath = Join-Path $Root 'tests\routes\smoke-expectations.json'

function Step($m) { Write-Host "==> $m" }

$plan = @(
    [pscustomobject]@{ tag = 'boot-120';         frames = 120;   input = $null;                                     maxMisses = 0;  long = $false }
    [pscustomobject]@{ tag = 'attract-3600';     frames = 3600;  input = $null;                                     maxMisses = 7;  long = $false }
    [pscustomobject]@{ tag = 'title-input-6000'; frames = 6000;  input = 'tests\input\start-press.keyinput.txt';    maxMisses = 10; long = $false }
    [pscustomobject]@{ tag = 'ctrl-idle-13500';  frames = 13500; input = 'tests\input\gameplay-idle.keyinput.txt';  maxMisses = 13; long = $true  }
    # host-walk-13500: the HOST-INPUT level entry. new-game's menu navigation plus a
    # RIGHT hold from frame 12000. Wario is dropped into level-0 room 0 at vblank ~11603
    # and walks from the spawn column to the right wall. This is the case that proves the
    # replay path reaches Wario inside a level and moves him -- which is what the
    # traverse-13500 case below was believed to prove, and does not (round 34).
    [pscustomobject]@{ tag = 'host-walk-13500';  frames = 13500; input = 'tests\input\gameplay-right.keyinput.txt'; maxMisses = 13; long = $true  }
    # traverse-13500: the ATTRACT-DEMO traversal. RETRACTED 2026-10-08 (round 34) -- this
    # route does not demonstrate host input. The demo player gf_tfunc_080103CC overwrites
    # gButtonsHeld (0x03001844) from its own recorded stream: on g31-hammer a LEFT write
    # (0x20) was observed at vblank 9655 while the host replay held RIGHT. Every room
    # change on this route is the demo's. It stays pinned because the frames are stable and
    # deterministic, but its old label ("Wario's hammer at the room-0 switch") was wrong.
    [pscustomobject]@{ tag = 'traverse-13500';   frames = 13500; input = 'tests\input\g31-hammer.keyinput.txt'; maxMisses = 11; long = $true  }
)

$expect = $null
if (-not $Record) {
    if (-not (Test-Path $ExpPath)) { throw "No $ExpPath yet — run: tools/validation/smoke.ps1 -Record" }
    $expect = Get-Content -LiteralPath $ExpPath -Raw | ConvertFrom-Json
}

function Invoke-Route([string]$tag, [int]$frames, [string]$replay, [string]$sav, [switch]$keepSave, [switch]$cold) {
    # NOTE: the parameter must not be called $input — that is a PowerShell automatic
    # variable, and a parameter of that name is silently empty, which made every
    # input route in the first version of this script run with the replay disabled.
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Runner, '-Tag', $tag, '-Frames', "$frames", '-DumpLastFrame')
    if ($Exe)     { $a += @('-Exe', $Exe) }
    if ($replay)  { $a += @('-InputReplay', (Join-Path $Root $replay)) }
    if ($sav)     { $a += @('-SavePath', $sav) }
    if ($keepSave) { $a += '-KeepSave' }
    if ($cold)    { $a += '-ColdCache' }
    $out = & pwsh @a 2>&1
    return ($out -join "`n")
}

function Get-Result([string]$tag) {
    $p = Join-Path $RouteDir "$tag-result.json"
    if (-not (Test-Path $p)) { return $null }
    return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json)
}

function Get-FrameHash([string]$tag) {
    $p = Join-Path $RouteDir "$tag-last.png"
    if (-not (Test-Path $p)) { return $null }
    return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower()
}

$fail = 0
$rows = @()
$recorded = @()

# ------------------------------------------------------------------- routes
foreach ($r in $plan) {
    if ($Quick -and $r.long) { Step "skip $($r.tag) (-Quick)"; continue }
    Step "route $($r.tag) ($($r.frames) frames)"
    Invoke-Route $r.tag $r.frames $r.input $null | Out-Null
    $res = Get-Result $r.tag
    $covPath = Join-Path $RouteDir "$($r.tag)-coverage.json"
    $cov = $null
    if (Test-Path $covPath) { $cov = Get-Content -LiteralPath $covPath -Raw | ConvertFrom-Json }
    $hash = Get-FrameHash $r.tag

    $problems = @()
    if ($null -eq $res) { $problems += 'no result JSON' }
    elseif ($res.exit_code -ne 0) { $problems += "exit=$($res.exit_code)" }
    if ($null -eq $cov) { $problems += 'no coverage JSON' }
    else {
        $allowed = if ($expect) { $expect.miss_allowed_prefix } else { '0x03007D' }
        $stray = @($cov.misses | Where-Object { $_.pc -notlike "$allowed*" })
        if ($stray.Count -gt 0) {
            $problems += "misses outside the dynamic set: $(($stray | ForEach-Object { $_.pc }) -join ', ')"
        }
        if ($cov.distinct_misses -gt $r.maxMisses) { $problems += "distinct_misses=$($cov.distinct_misses) > $($r.maxMisses)" }
    }
    if ($hash -and $expect) {
        $want = ($expect.routes | Where-Object { $_.tag -eq $r.tag }).frame_sha256
        if ($want -and $want -ne $hash) { $problems += "frame changed: $want -> $hash" }
    }
    if (-not $hash) { $problems += 'no frame dump' }

    $status = if ($problems.Count -eq 0) { 'PASS' } else { 'FAIL'; }
    if ($problems.Count -gt 0) { $fail++ }
    $rows += [pscustomobject]@{
        route = $r.tag; frames = $r.frames; status = $status
        misses = if ($cov) { $cov.distinct_misses } else { '-' }
        interp = if ($cov) { $cov.interpreted_insns } else { '-' }
        frame  = if ($hash) { $hash.Substring(0,16) } else { '-' }
        detail = ($problems -join '; ')
    }
    $recorded += [pscustomobject]@{
        tag = $r.tag; frames = $r.frames; input = $r.input
        max_misses = $r.maxMisses; frame_sha256 = $hash
        observed_misses = if ($cov) { $cov.distinct_misses } else { $null }
        observed_interpreted_insns = if ($cov) { $cov.interpreted_insns } else { $null }
    }
}

# -------------------------------------------------------------- persistence
$persist = $null
if (-not $SkipPersistence) {
    Step 'persistence round trip (write → exit → load)'
    $sav = Join-Path $RouteDir 'smoke-save.sav'
    if (Test-Path $sav) { Remove-Item -Force $sav }
    $writeInput = 'tests\input\new-game.keyinput.txt'
    $loadInput  = 'tests\input\start-press.keyinput.txt'
    Invoke-Route 'smoke-save-write' 12000 $writeInput $sav | Out-Null
    $writeLog = Get-Content -LiteralPath (Join-Path $RouteDir 'smoke-save-write.log') -Raw -ErrorAction SilentlyContinue
    $bytes = if (Test-Path $sav) { [System.IO.File]::ReadAllBytes($sav) } else { @() }
    $erased = 0; foreach ($b in $bytes) { if ($b -eq 0xFF) { $erased++ } }

    Invoke-Route 'smoke-save-load' 6000 $loadInput $sav -keepSave | Out-Null
    $loadLog = Get-Content -LiteralPath (Join-Path $RouteDir 'smoke-save-load.log') -Raw -ErrorAction SilentlyContinue
    $loadHash = Get-FrameHash 'smoke-save-load'

    $problems = @()
    if ($bytes.Count -ne 32768) { $problems += "save is $($bytes.Count) bytes, expected 32768" }
    elseif ($erased -eq $bytes.Count) { $problems += 'save is still all 0xFF — nothing was written' }
    if ($writeLog -notmatch 'save_flushed') { $problems += 'no save_flushed in the write run' }
    if ($loadLog -notmatch 'save_loaded') { $problems += 'no save_loaded in the load run' }
    if ($expect -and $expect.persistence.load_frame_sha256 -and $loadHash -ne $expect.persistence.load_frame_sha256) {
        $problems += "loaded frame changed: $($expect.persistence.load_frame_sha256) -> $loadHash"
    }
    if ($problems.Count -gt 0) { $fail++ }
    $rows += [pscustomobject]@{
        route = 'save-write/load'; frames = 18000
        status = if ($problems.Count -eq 0) { 'PASS' } else { 'FAIL' }
        misses = '-'; interp = '-'
        frame = if ($loadHash) { $loadHash.Substring(0,16) } else { '-' }
        detail = ($problems -join '; ')
    }
    $persist = [pscustomobject]@{
        write_tag = 'smoke-save-write'; write_frames = 12000; write_input = $writeInput
        load_tag = 'smoke-save-load';   load_frames = 6000;   load_input = $loadInput
        save_bytes = $bytes.Count; non_erased_bytes = ($bytes.Count - $erased)
        load_frame_sha256 = $loadHash
    }
}

# --------------------------------------------------------------------- report
Write-Host ''
$rows | Format-Table -AutoSize | Out-String -Width 400 | Write-Host

if ($Record) {
    $doc = [ordered]@{
        format = 1
        note = 'Recorded by tools/validation/smoke.ps1 -Record. Frame hashes are byte-exact expectations: a legitimate change must re-record and be reviewed.'
        recorded_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        miss_allowed_prefix = '0x03007D'
        routes = $recorded
        persistence = $persist
    }
    ($doc | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $ExpPath -Encoding UTF8
    Step "recorded -> $ExpPath"
}

if ($fail -gt 0) { Step "SMOKE: $fail check(s) FAILED"; exit 1 }
Step 'SMOKE: PASS'
exit 0
