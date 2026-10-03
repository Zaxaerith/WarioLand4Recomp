<#
.SYNOPSIS
    Analyse a mid-run frame strip dumped by run-route.ps1 -FrameDumpCount.

.DESCRIPTION
    Reads a directory of `f_%06u.png` frames (the runtime's
    GBARECOMP_FRAMEDUMP_DIR output) and answers the question an end-of-route
    screenshot cannot: WHEN did the screen change, and HOW FAR did the camera
    move.

    For every frame it reports
      * the number of pixels differing from the base frame and their bounding
        box (a Wario-shaped band means the sprite moved; a full-screen diff means
        the camera scrolled), and
      * the horizontal shift of the frame that best matches the base frame over
        a background band -- i.e. the camera displacement in pixels.

    The shift search deliberately ignores the top rows (HUD, static) and the
    bottom rows (status bar / sprite row) so that Wario himself does not bias the
    estimate; see -BandTop/-BandBottom.

.EXAMPLE
    # film 100 frames of the LEFT-hold walk, then measure it
    tools/validation/run-route.ps1 -Tag strip-left -Frames 12160 -Window `
        -InputReplay tests/input/probe-left.keyinput.txt `
        -FrameDumpStart 12040 -FrameDumpCount 100
    tools/validation/frame-strip.ps1 -Dir logs/routes/strip-left-frames -Every 5
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    [int]$Base = -1,               # frame index used as the reference (-1 = first frame in the strip)
    [int]$Every = 5,               # print every Nth frame
    [int]$MaxShift = 80,           # horizontal camera-shift search range, in pixels
    [int]$BandTop = 48,            # background band used for the shift search
    [int]$BandBottom = 112,
    [string]$Csv = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $Dir)) { throw "no such directory: $Dir" }
$files = Get-ChildItem -LiteralPath $Dir -Filter 'f_*.png' | Sort-Object Name
if ($files.Count -eq 0) { throw "no f_*.png frames in $Dir" }

# Frame index is the number in the file name; the strip may not start at 0.
$indices = @()
foreach ($f in $files) {
    if ($f.Name -notmatch '^f_(\d+)\.png$') { throw "unexpected frame name: $($f.Name)" }
    $indices += [int]$Matches[1]
}
if ($Base -lt 0) { $Base = $indices[0] }
$basePos = [Array]::IndexOf($indices, $Base)
if ($basePos -lt 0) { throw "base frame $Base is not in the strip ($($indices[0])..$($indices[-1]))" }

# One compiled helper: PowerShell's per-pixel loops are ~100x too slow for
# 38,400-pixel comparisons across a hundred frames.
if (-not ('FrameStrip' -as [type])) {
    # `-ReferencedAssemblies 'System.Drawing'` is not enough on .NET 10: Bitmap is
    # type-forwarded to System.Drawing.Common and its IImage lives in
    # System.Private.Windows.GdiPlus, so hand Add-Type the real assembly paths
    # (CS1069 / CS0012 otherwise).
    Add-Type -AssemblyName System.Drawing
    $rt = [System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()
    $refs = @([System.Drawing.Bitmap].Assembly.Location)
    # System.Drawing*.dll (Bitmap/Rectangle/ImageLockMode) + the Windows-only
    # implementation assemblies (IImage, IRawData, GdiPlus).
    $refs += (Get-ChildItem -LiteralPath $rt -Filter 'System.Drawing*.dll' | ForEach-Object { $_.FullName })
    $refs += (Get-ChildItem -LiteralPath $rt -Filter 'System.Private.Windows.*.dll' | ForEach-Object { $_.FullName })
    $refs = $refs | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique
    Add-Type -ReferencedAssemblies $refs -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class FrameStrip
{
    public static byte[] Load(string path)
    {
        using (var b = new Bitmap(path))
        {
            var r = new Rectangle(0, 0, b.Width, b.Height);
            var d = b.LockBits(r, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try
            {
                var buf = new byte[d.Stride * d.Height];
                Marshal.Copy(d.Scan0, buf, 0, buf.Length);
                return buf;
            }
            finally { b.UnlockBits(d); }
        }
    }

    // {count, minx, maxx, miny, maxy}; bbox is {-1,-1,-1,-1} when nothing differs.
    public static int[] Diff(byte[] a, byte[] b, int w, int h)
    {
        int n = 0, minx = int.MaxValue, maxx = -1, miny = int.MaxValue, maxy = -1;
        for (int y = 0; y < h; y++)
        {
            int row = y * w * 4;
            for (int x = 0; x < w; x++)
            {
                int o = row + x * 4;
                if (a[o] != b[o] || a[o + 1] != b[o + 1] || a[o + 2] != b[o + 2])
                {
                    n++;
                    if (x < minx) minx = x;
                    if (x > maxx) maxx = x;
                    if (y < miny) miny = y;
                    if (y > maxy) maxy = y;
                }
            }
        }
        if (n == 0) return new int[] { 0, -1, -1, -1, -1 };
        return new int[] { n, minx, maxx, miny, maxy };
    }

    // Best horizontal displacement of `b` against `a` over rows [y0,y1].
    // Returns {shift, matched, total}: `b` shifted by `shift` reproduces `a`.
    public static int[] BestShift(byte[] a, byte[] b, int w, int h, int y0, int y1, int maxShift)
    {
        int bestShift = 0, bestMatch = -1, total = 0;
        if (y0 < 0) y0 = 0;
        if (y1 > h) y1 = h;
        for (int s = -maxShift; s <= maxShift; s++)
        {
            int match = 0, seen = 0;
            for (int y = y0; y < y1; y++)
            {
                int row = y * w * 4;
                for (int x = 0; x < w; x++)
                {
                    int sx = x + s;
                    if (sx < 0 || sx >= w) continue;
                    int oa = row + x * 4, ob = row + sx * 4;
                    seen++;
                    if (a[oa] == b[ob] && a[oa + 1] == b[ob + 1] && a[oa + 2] == b[ob + 2]) match++;
                }
            }
            if (match > bestMatch) { bestMatch = match; bestShift = s; total = seen; }
        }
        return new int[] { bestShift, bestMatch, total };
    }

    public static int Width(string path) { using (var b = new Bitmap(path)) { return b.Width; } }
    public static int Height(string path) { using (var b = new Bitmap(path)) { return b.Height; } }
}
'@
}

$w = [FrameStrip]::Width($files[0].FullName)
$h = [FrameStrip]::Height($files[0].FullName)
# NOTE: `$Base` is an [int] parameter, and PowerShell variables are
# case-insensitive -- assigning the pixel buffer to `$base` would be the same
# variable and fail with "cannot convert Byte[] to Int32". Keep them distinct.
$baseBuf = [FrameStrip]::Load($files[$basePos].FullName)

Write-Host ("strip: {0} frames f_{1:D6}..f_{2:D6}  ({3}x{4})  base = f_{5:D6}" -f `
    $files.Count, $indices[0], $indices[-1], $w, $h, $Base)
Write-Host ("band for the shift search: rows {0}..{1}, shifts -{2}..{2}" -f $BandTop, ($BandBottom - 1), $MaxShift)
Write-Host ''
Write-Host ("{0,-9} {1,8}  {2,-24} {3,7}  {4}" -f 'frame', 'diff_px', 'bbox', 'camera', 'shift_match')

$rows = @()
$firstChange = -1
for ($i = 0; $i -lt $files.Count; $i++) {
    $cur = [FrameStrip]::Load($files[$i].FullName)
    $d = [FrameStrip]::Diff($baseBuf, $cur, $w, $h)
    $bbox = if ($d[0] -eq 0) { '-' } else { "x=$($d[1])..$($d[2]) y=$($d[3])..$($d[4])" }
    if ($d[0] -gt 0 -and $firstChange -lt 0) { $firstChange = $indices[$i] }

    $shift = ''; $ratio = ''
    if ($i -eq 0 -or ($i % $Every) -eq 0) {
        $s = [FrameStrip]::BestShift($baseBuf, $cur, $w, $h, $BandTop, $BandBottom, $MaxShift)
        $shift = "$($s[0])"
        $ratio = ('{0:P1}' -f ($s[1] / [double]$s[2]))
    }
    $rows += [pscustomobject]@{
        frame = $indices[$i]; diff_px = $d[0]; bbox = $bbox; camera = $shift; match = $ratio
    }
    if ($i -eq 0 -or ($i % $Every) -eq 0) {
        Write-Host ("{0,-9} {1,8}  {2,-24} {3,7}  {4}" -f $indices[$i], $d[0], $bbox, $shift, $ratio)
    }
}

Write-Host ''
if ($firstChange -lt 0) {
    Write-Host "no frame differs from the base -- nothing moved in this window."
} else {
    Write-Host ("first frame differing from f_{0:D6} (the base is also included): f_{1:D6}" -f $Base, $firstChange)
}
$last = $rows[-1]
Write-Host ("last frame f_{0:D6}: diff={1} px  bbox={2}  camera shift={3} ({4} of band pixels match)" -f `
        $last.frame, $last.diff_px, $last.bbox, $last.camera, $last.match)

if ($Csv) {
    $rows | Export-Csv -NoTypeInformation -Encoding utf8 -Path $Csv
    Write-Host "wrote $Csv"
}
