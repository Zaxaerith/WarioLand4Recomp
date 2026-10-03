<#
    verb-ab.ps1 — priority F evidence: does each gameplay verb button reach the game?

    A single screenshot cannot tell "the button worked" from "the animation phase
    happened to differ", so every verb is measured as an A/B PAIR: the same
    scripted trace, twice, differing by exactly one line of keyinput. Both runs
    use their own isolated save (run-route.ps1) and the same frame budget, so the
    only possible cause of a pixel difference is the verb button itself.

    Transient verbs (jump, punch) need the frame budget to END while the action is
    still on screen — a D-pad hold changes the final position permanently, but a
    punch is over in ~20 frames. Hence a per-verb frame budget, not one shared one.

    Exit code 1 if any verb's frame is byte-identical to its control (that means
    the button did nothing) or if a route failed.

    Examples
      tools/validation/verb-ab.ps1
      tools/validation/verb-ab.ps1 -ReuseControl      # keep existing control PNGs
#>
[CmdletBinding()]
param(
    [string]$Exe,
    [switch]$ReuseControl
)

$ErrorActionPreference = 'Stop'
$Root   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RouteDir = Join-Path $Root 'logs\routes'
$Runner = Join-Path $PSScriptRoot 'run-route.ps1'
New-Item -ItemType Directory -Force -Path $RouteDir | Out-Null

function Step($m) { Write-Host "==> $m" }

# verb routes (tag, frames, trace) and the control each one is compared against
$verbs = @(
    [pscustomobject]@{ verb = 'jump';   tag = 'verb-jump-12090';   frames = 12090
                       input = 'tests\input\verb-jump.keyinput.txt'
                       control = 'ctrl-idle-12090';   controlFrames = 12090; controlInput = 'tests\input\gameplay-idle.keyinput.txt' }
    [pscustomobject]@{ verb = 'attack'; tag = 'verb-attack-13475'; frames = 13475
                       input = 'tests\input\verb-attack.keyinput.txt'
                       control = 'ctrl-idle-13475';   controlFrames = 13475; controlInput = 'tests\input\gameplay-idle.keyinput.txt' }
    [pscustomobject]@{ verb = 'dash';   tag = 'verb-dash-13500';   frames = 13500
                       input = 'tests\input\verb-dash.keyinput.txt'
                       control = 'ctrl-idle-13500';   controlFrames = 13500; controlInput = 'tests\input\gameplay-idle.keyinput.txt' }
    [pscustomobject]@{ verb = 'crouch'; tag = 'verb-crouch-13500'; frames = 13500
                       input = 'tests\input\verb-crouch.keyinput.txt'
                       control = 'ctrl-idle-13500';   controlFrames = 13500; controlInput = 'tests\input\gameplay-idle.keyinput.txt' }
)

function Invoke-Route([string]$tag, [int]$frames, [string]$replay) {
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Runner,
           '-Tag', $tag, '-Frames', "$frames", '-InputReplay', (Join-Path $Root $replay), '-DumpLastFrame')
    if ($Exe) { $a += @('-Exe', $Exe) }
    $out = & pwsh @a 2>&1
    $line = ($out | Select-String -Pattern 'exit=' | Select-Object -First 1)
    $cov  = ($out | Select-String -Pattern 'coverage=' | Select-Object -First 1)
    Write-Host "    $line"
    Write-Host "    $cov"
    # never trust a replay unless the runtime says it enabled it (docs/VALIDATION.md rule 10)
    $log = Join-Path $RouteDir "$tag.log"
    if (Test-Path $log) {
        $replayLine = Select-String -LiteralPath $log -Pattern 'input_replay=ENABLED' | Select-Object -First 1
        if (-not $replayLine) { throw "$tag ran with input_replay DISABLED — the trace was not applied" }
    }
    $res = Get-Content -LiteralPath (Join-Path $RouteDir "$tag-result.json") -Raw | ConvertFrom-Json
    if ($res.exit_code -ne 0) { throw "$tag exit=$($res.exit_code)" }
    return $res
}

function Get-FrameHash([string]$tag) {
    $p = Join-Path $RouteDir "$tag-last.png"
    if (-not (Test-Path $p)) { throw "no frame dump for $tag" }
    return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower()
}

Add-Type -AssemblyName System.Drawing
function Compare-Frame([string]$tagA, [string]$tagB) {
    $a = [System.Drawing.Bitmap]::FromFile((Join-Path $RouteDir "$tagA-last.png"))
    $b = [System.Drawing.Bitmap]::FromFile((Join-Path $RouteDir "$tagB-last.png"))
    $n = 0; $minx = 9999; $maxx = -1; $miny = 9999; $maxy = -1
    for ($y = 0; $y -lt $a.Height; $y++) {
        for ($x = 0; $x -lt $a.Width; $x++) {
            if ($a.GetPixel($x, $y).ToArgb() -ne $b.GetPixel($x, $y).ToArgb()) {
                $n++
                if ($x -lt $minx) { $minx = $x }; if ($x -gt $maxx) { $maxx = $x }
                if ($y -lt $miny) { $miny = $y }; if ($y -gt $maxy) { $maxy = $y }
            }
        }
    }
    $a.Dispose(); $b.Dispose()
    return [pscustomobject]@{ diff = $n; total = 38400; bbox = "x=$minx..$maxx y=$miny..$maxy" }
}

$doneControls = @{}
$fail = 0
$rows = @()

foreach ($v in $verbs) {
    Step "$($v.verb): $($v.tag) ($($v.frames) frames)"
    Invoke-Route $v.tag $v.frames $v.input | Out-Null

    if (-not ($ReuseControl -and $doneControls.ContainsKey($v.control)) -and
        -not (Test-Path (Join-Path $RouteDir "$($v.control)-last.png"))) {
        Step "  control $($v.control) ($($v.controlFrames) frames)"
        Invoke-Route $v.control $v.controlFrames $v.controlInput | Out-Null
    }
    if (-not $doneControls.ContainsKey($v.control)) { $doneControls[$v.control] = $true }

    $d = Compare-Frame $v.tag $v.control
    $status = if ($d.diff -eq 0) { 'FAIL (button had no effect)'; $fail++ ; } else { 'PASS' }
    $rows += [pscustomobject]@{
        verb = $v.verb; route = $v.tag; frames = $v.frames; control = $v.control
        differing_pixels = $d.diff; bbox = $d.bbox; status = $status
    }
}

Write-Host ''
$rows | Format-Table -AutoSize | Out-String -Width 400 | Write-Host

# the two 13,500-frame routes share one control, so state the shared baseline once
$shared = Get-FrameHash 'ctrl-idle-13500'
Write-Host "control frame ctrl-idle-13500 sha256 = $shared"
foreach ($tag in @('ctrl-idle-12090', 'ctrl-idle-13475')) {
    if (Test-Path (Join-Path $RouteDir "$tag-last.png")) {
        Write-Host "control frame $tag sha256 = $(Get-FrameHash $tag)"
    }
}

if ($fail -gt 0) { Step "VERB A/B: $fail verb(s) had no measurable effect"; exit 1 }
Step 'VERB A/B: PASS (every verb button changed the rendered frame)'
exit 0
