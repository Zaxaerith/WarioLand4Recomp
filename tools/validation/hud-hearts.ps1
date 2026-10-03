<#
.SYNOPSIS
    Read the player's health from captured frames: how many HUD heart slots are filled.

.DESCRIPTION
    The WL4 HUD draws health as a row of 8 hearts at the top-left of the 240x160
    screen over a black background: filled hearts are red/orange, empty ones are
    white. The hearts ANIMATE (they beat), so a raw red-pixel count wobbles with
    the animation phase and is not a health reading — the *structural* quantity is
    how many heart slots contain red at all.

    This tool therefore scans columns x=-X0..-X1 in the band y=-Y0..-Y1, marks a
    column as red when it holds at least -MinColPixels strongly-red pixels, and
    counts runs of consecutive red columns. Each run is one filled heart; the run
    starts are printed so the slot geometry stays visible. The band ends at x=90,
    well left of the coin counter in the top-right, so coins cannot leak in.

    A heart going from red to white between two captures is a DAMAGE event; a
    white slot turning red is a heart/heart-piece pickup. That is what the
    priority-F "受伤" axis needs, and it is stronger evidence than a whole-frame
    pixel diff because it names the quantity that changed.

.EXAMPLE
    pwsh -File tools/validation/hud-hearts.ps1 -Dir logs/routes -Pattern 'heartwatch-f*.png'
#>
param(
    [string]$Dir = 'logs\routes',
    [string]$Pattern = '*.png',
    [string[]]$Files = @(),
    [int]$X0 = 2,
    [int]$X1 = 100,
    [int]$Y0 = 4,
    [int]$Y1 = 22,
    [int]$MinRed = 150,
    [int]$MinGap = 60,
    [int]$MinColPixels = 2,
    [string]$Csv
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$list = if ($Files.Count -gt 0) { $Files | ForEach-Object { (Resolve-Path $_).Path } }
        else { Get-ChildItem -Path (Join-Path $Dir $Pattern) -File | Sort-Object Name | ForEach-Object { $_.FullName } }
if ($list.Count -eq 0) { throw "no PNG matched $Pattern in $Dir" }

$rows = @()
$prevSlots = $null
foreach ($path in $list) {
    $bmp = [System.Drawing.Bitmap]::FromFile($path)
    try {
        $cols = @{}
        $total = 0
        for ($x = $X0; $x -le $X1; $x++) {
            $n = 0
            for ($y = $Y0; $y -le $Y1; $y++) {
                $c = $bmp.GetPixel($x, $y)
                if ($c.R -ge $MinRed -and ($c.R - $c.G) -ge $MinGap -and ($c.R - $c.B) -ge $MinGap) { $n++ }
            }
            $cols[$x] = $n
            $total += $n
        }
    } finally { $bmp.Dispose() }

    # runs of consecutive red columns = filled hearts
    $starts = @()
    $inRun = $false
    for ($x = $X0; $x -le $X1; $x++) {
        if ($cols[$x] -ge $MinColPixels) {
            if (-not $inRun) { $starts += $x; $inRun = $true }
        } else { $inRun = $false }
    }

    $name = Split-Path -Leaf $path
    $flag = ''
    if ($null -ne $prevSlots) {
        $lost = @($prevSlots | Where-Object { $starts -notcontains $_ })
        $gained = @($starts | Where-Object { $prevSlots -notcontains $_ })
        if ($lost.Count -gt 0) { $flag += "  <-- LOST slot(s) $($lost -join ',')" }
        if ($gained.Count -gt 0) { $flag += "  <-- GAINED slot(s) $($gained -join ',')" }
    }
    $prevSlots = $starts
    "{0,-30} filled={1}  slots=[{2}]  red={3}{4}" -f $name, $starts.Count, ($starts -join ','), $total, $flag
    $rows += [pscustomobject]@{ file = $name; filled_hearts = $starts.Count; slot_starts = ($starts -join ','); red_pixels = $total }
}

""
"distinct filled-heart counts across $($rows.Count) frame(s):"
$rows | Group-Object filled_hearts | Sort-Object { [int]$_.Name } | ForEach-Object {
    "  filled={0,2}  x{1}" -f $_.Name, $_.Count
}
if ($Csv) { $rows | Export-Csv -LiteralPath $Csv -NoTypeInformation -Encoding UTF8; "wrote $Csv" }
