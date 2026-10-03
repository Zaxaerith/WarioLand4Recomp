<#
    regen.ps1 — regenerate cartridge and BIOS translation from verified inputs.

    Gates (all must pass before a single byte is generated):

      1. exactly one *.gba in the project root
      2. its MD5/SHA-1/SHA-256 match docs/ROM_IDENTITY.json
      3. the BIOS dump's SHA-1 matches docs/ROM_IDENTITY.json
      4. reference/gbarecomp is at the pin commit recorded in
         docs/FRAMEWORK_PIN.json

    Outputs (both are ROM/BIOS-derived build artifacts and stay local-only,
    ignored by .gitignore):

        generated/cart/   recompiled_*.cpp, dispatch_table.cpp, symbol_map.cpp, ...
        generated/bios/   bios_recompiled.cpp, bios_dispatch_table.cpp, ...

    Nothing in this script writes outside WORK_ROOT.
#>
[CmdletBinding()]
param(
    [string]$Bios,                     # BIOS dump path; auto-discovered when omitted
    [string]$Generator,                # gba_recompile.exe; defaults to build/framework
    [int]$MaxFunctions = 65536,
    [switch]$SkipBios,
    [switch]$CartOnly,
    # Decomp symbol overlay (names + data extents harvested from the decomp
    # sources). Off by default so the baseline build stays the reference; see
    # docs/VALIDATION.md for the A/B that proves it is behaviour-preserving.
    [switch]$SymbolOverlay
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

# A pinned file's identity is its content, not its line endings. `git hash-object`
# normally normalises CRLF through the checkout's clean filter, but that filter is
# configured per repository and a submodule nested inside reference/gbarecomp can
# resolve it differently, which made the same file hash two ways. Hash the
# LF-normalised bytes explicitly so the check cannot depend on a caller's config.
function Get-NormalizedBlobSha1 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $lf = New-Object System.Collections.Generic.List[byte] ($bytes.Length)
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -eq 13) {
            if ($i + 1 -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }
            $lf.Add(10); continue
        }
        $lf.Add($bytes[$i])
    }
    $body = $lf.ToArray()
    $header = [System.Text.Encoding]::ASCII.GetBytes("blob $($body.Length)`0")
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try { $hash = $sha1.ComputeHash(([byte[]]$header + [byte[]]$body)) } finally { $sha1.Dispose() }
    return (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
}

# ---------------------------------------------------------------- ROM identity
$roms = @(Get-ChildItem -LiteralPath $Root -Filter '*.gba' -File)
if ($roms.Count -ne 1) { Fail "Expected exactly one .gba in $Root, found $($roms.Count)." }
$rom = $roms[0].FullName
$identity = Get-Content -LiteralPath (Join-Path $Root 'docs\ROM_IDENTITY.json') -Raw | ConvertFrom-Json
$want = $identity.rom
$have = [ordered]@{
    md5    = (Get-FileHash $rom -Algorithm MD5).Hash.ToLower()
    sha1   = (Get-FileHash $rom -Algorithm SHA1).Hash.ToLower()
    sha256 = (Get-FileHash $rom -Algorithm SHA256).Hash.ToLower()
}
foreach ($k in @('md5','sha1','sha256')) {
    if ($have[$k] -ne $want.$k) { Fail "ROM $k mismatch: have $($have[$k]), expected $($want.$k). Wrong ROM." }
}
$size = (Get-Item $rom).Length
if ($size -ne $want.size_bytes) { Fail "ROM size mismatch: have $size, expected $($want.size_bytes)." }
Step "ROM verified: $([System.IO.Path]::GetFileName($rom))  sha1=$($have.sha1)  size=$size"

# -------------------------------------------------------------- framework pin
$pin = Get-Content -LiteralPath (Join-Path $Root 'docs\FRAMEWORK_PIN.json') -Raw | ConvertFrom-Json
$framework = Join-Path $Root 'reference\gbarecomp'
if (-not (Test-Path (Join-Path $framework 'CMakeLists.txt'))) { Fail "Missing framework checkout at $framework. Run: pwsh tools/regeneration/setup-framework.ps1 (see docs/FRAMEWORK_PIN.json)." }
if (Test-Path (Join-Path $framework '.git')) {
    $safe = "safe.directory=$($framework.Replace('\','/'))"
    $head = (& git -c $safe -C $framework rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) { Fail 'Could not read the framework checkout commit.' }
    $head = $head.Trim()
    $wantCommit = $pin.framework.upstream_commit
    # A checkout may carry a local history (this project's own development tree
    # commits the patch set). The requirement is the pinned upstream commit plus
    # the pinned patch set, so accept either HEAD == upstream or HEAD descending
    # from it, and prove the patch set by file content either way.
    $headDescends = $false
    if ($head -eq $wantCommit) { $headDescends = $true }
    else {
        & git -c $safe -C $framework merge-base --is-ancestor $wantCommit $head 2>$null
        $headDescends = ($LASTEXITCODE -eq 0)
    }
    # The identity is upstream commit + this project's patch set, so verify that
    # the patched files really are the pinned ones. Each patch names its own base
    # (the main checkout, or a submodule nested inside it).
    function Resolve-PatchBase {
        param([string]$AppliesTo)
        $rel = $AppliesTo -replace '/', '\'
        $pinned = ($pin.framework.checkout -replace '/', '\')
        if ($rel -eq $pinned) { return $framework }
        if ($rel.StartsWith($pinned + '\')) { return (Join-Path $framework $rel.Substring($pinned.Length + 1)) }
        return (Join-Path $Root $rel)
    }
    $badPatch = @()
    foreach ($p in $pin.patches) {
        $patchFile = Join-Path $Root ($p.file -replace '/', '\')
        if (-not (Test-Path -LiteralPath $patchFile)) { $badPatch += $p.file; continue }
        $pSha = (Get-FileHash -LiteralPath $patchFile -Algorithm SHA256).Hash.ToLower()
        if ($p.sha256 -and $pSha -ne $p.sha256) { $badPatch += "$($p.file) (sha256 $pSha)"; continue }
        $base = Resolve-PatchBase -AppliesTo $p.applies_to
        foreach ($pair in $p.verify_blob_sha1_prefix.PSObject.Properties) {
            $file = Join-Path $base ($pair.Name -replace '/','\')
            if (-not (Test-Path -LiteralPath $file)) { $badPatch += $pair.Name; continue }
            $blob = Get-NormalizedBlobSha1 -Path $file
            if (-not $blob -or $blob.Substring(0, 12) -ne $pair.Value) { $badPatch += $pair.Name }
        }
    }
    if ($badPatch.Count -gt 0) {
        Fail ("Framework patch set is not applied ($($badPatch.Count) file(s) differ, e.g. $($badPatch[0])). Re-run: pwsh tools/regeneration/setup-framework.ps1 -Force")
    }
    if ($headDescends) { Step "Framework verified: upstream $wantCommit + $($pin.patches.Count) pinned patch(es)" }
    else { Step "Framework verified by content: $($pin.patches.Count) pinned patch(es); local HEAD $head does not descend from upstream $wantCommit" }
} else {
    Step "Framework checkout has no .git; upstream commit and patch hashes not re-verified"
}

# ------------------------------------------------------------------- generator
if (-not $Generator) {
    $Generator = Join-Path $Root 'build\framework\Release\gba_recompile.exe'
    if (-not (Test-Path $Generator)) { $Generator = Join-Path $Root 'build\framework\gba_recompile.exe' }
}
if (-not (Test-Path $Generator)) {
    Fail "gba_recompile.exe not found. Run tools/build-framework.ps1 first."
}
Step "generator: $Generator"

# ----------------------------------------------------------------------- BIOS
if (-not $Bios) {
    $SharedRoot = if ($env:GAME_RECOMP_ROOT) { $env:GAME_RECOMP_ROOT } else { Split-Path -Parent $Root }
    $candidates = @(
        (Join-Path $Root 'bios\gba_bios.bin'),
        (Join-Path $SharedRoot 'gbarecomp-cli-windows-x86_64\gbabios\gba_bios.bin')
    )
    $Bios = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $SkipBios) {
    if (-not $Bios) { Fail 'No BIOS dump found. Pass -Bios <path> or place bios/gba_bios.bin.' }
    $biosSha1 = (Get-FileHash $Bios -Algorithm SHA1).Hash.ToLower()
    if ($biosSha1 -ne $identity.bios.sha1) { Fail "BIOS SHA-1 mismatch: have $biosSha1, expected $($identity.bios.sha1)." }
    Step "BIOS verified: $Bios  sha1=$biosSha1"
}

$config = Join-Path $Root 'game.toml'

# Decomp symbol overlay: the harvested names/data extents are passed as a
# SECOND config after game.toml (game.toml wins conflicts) plus the two TSV
# tables the framework's importer writes. See docs/VALIDATION.md.
$overlayArgs = @()
if ($SymbolOverlay) {
    $overlayToml = Join-Path $Root 'symbols\AWAE_symbols.toml'
    $overlaySyms = Join-Path $Root 'symbols\imported_symbols.tsv'
    $overlayData = Join-Path $Root 'symbols\imported_data_symbols.tsv'
    foreach ($p in @($overlayToml, $overlaySyms, $overlayData)) {
        if (-not (Test-Path -LiteralPath $p)) {
            Fail "Symbol overlay requested but $p is missing. Run: python tools/validation/parse_decomp_symbols.py --decomp third_party/lilDavid-warioland4 --out symbols/decomp_readelf_syms.txt --verify-rom <rom>, then the framework importer (see docs/VALIDATION.md)."
        }
    }
    $overlayArgs = @('--config', $overlayToml, '--symbols', $overlaySyms, '--data-symbols', $overlayData)
    Step "decomp symbol overlay: $overlayToml + $(Split-Path -Leaf $overlaySyms) + $(Split-Path -Leaf $overlayData)"
}

# ----------------------------------------------------------------- cartridge
# Clear the output directory first. The host CMake globs generated/cart/*.cpp
# (CMakeLists.txt:47), so any file the CURRENT inputs do not produce is still
# compiled — measured: a run with -SymbolOverlay leaves data_symbol_map.cpp
# (151,398 B) behind, and the next plain run silently linked it, so the
# "baseline" executable was not the baseline (docs/KNOWN_ISSUES.md G12).
# Regeneration must be a function of its inputs, not of the previous run.
$cartOut = Join-Path $Root 'generated\cart'
if (Test-Path $cartOut) {
    # Enumerate and remove the children: `Remove-Item -LiteralPath <dir>\*` does
    # NOT expand the wildcard (LiteralPath means literal), so that form silently
    # deletes nothing.
    Get-ChildItem -LiteralPath $cartOut -Force | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $cartOut | Out-Null
$cartLog = Join-Path $LogDir 'host-cart-generation.log'
Step "cartridge generation -> $cartOut (output directory cleared)"
& $Generator --rom $rom --config $config --out $cartOut --max-functions $MaxFunctions @overlayArgs *>&1 |
    Tee-Object -FilePath $cartLog
if ($LASTEXITCODE -ne 0) { Fail "Cartridge generation failed (exit $LASTEXITCODE); see $cartLog" }
foreach ($f in @('recompiled.h', 'dispatch_table.cpp')) {
    if (-not (Test-Path (Join-Path $cartOut $f))) { Fail "Cartridge generation produced no $f" }
}
$shards = @(Get-ChildItem -LiteralPath $cartOut -Filter 'recompiled_*.cpp' -File)
if ($shards.Count -lt 1) { Fail 'Cartridge generation produced no recompiled_*.cpp shard' }
Step "cartridge shards: $($shards.Count)  total=$([math]::Round((($shards | Measure-Object Length -Sum).Sum)/1MB,1)) MB"

# ---------------------------------------------------------------------- BIOS
if (-not $SkipBios -and -not $CartOnly) {
    $biosOut = Join-Path $Root 'generated\bios'
    # Same reasoning as the cartridge directory above: clear it so a removed or
    # renamed generator artifact cannot survive into the next link. The two
    # files this step needs (bios_recompiled.cpp from the generator,
    # codegen_tail_macros.h copied in below) are both recreated here.
    if (Test-Path $biosOut) {
        # Enumerate first: -LiteralPath does not expand a `*` wildcard.
        Get-ChildItem -LiteralPath $biosOut -Force | Remove-Item -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $biosOut | Out-Null
    $biosLog = Join-Path $LogDir 'host-bios-generation.log'
    Step "BIOS generation -> $biosOut"
    & $Generator --bios $Bios --config (Join-Path $framework 'bios\gba_bios.toml') --out $biosOut *>&1 |
        Tee-Object -FilePath $biosLog
    if ($LASTEXITCODE -ne 0) { Fail "BIOS generation failed (exit $LASTEXITCODE); see $biosLog" }
    if (-not (Test-Path (Join-Path $biosOut 'bios_recompiled.cpp'))) { Fail 'BIOS generation produced no bios_recompiled.cpp' }
    # The framework force-includes `codegen_tail_macros.h` from whatever
    # directory GBARECOMP_GENERATED_BIOS_DIR points at
    # (reference/gbarecomp/CMakeLists.txt:407-413). That header is
    # hand-written framework source, not generator output, so the standalone
    # in-tree workflow gets it for free while an out-of-tree output directory
    # does not. Copy the pinned copy in rather than teaching the framework a
    # second lookup path (no framework edits - the snapshot stays byte-exact).
    $tailMacros = Join-Path $framework 'src\runtime\generated_bios\codegen_tail_macros.h'
    if (-not (Test-Path $tailMacros)) { Fail "Missing framework header $tailMacros" }
    Copy-Item $tailMacros (Join-Path $biosOut 'codegen_tail_macros.h') -Force
    Step "BIOS translation: bios_recompiled.cpp $((
        [math]::Round((Get-Item (Join-Path $biosOut 'bios_recompiled.cpp')).Length/1MB,1))) MB (+ codegen_tail_macros.h)"
}

Step 'regeneration complete'
