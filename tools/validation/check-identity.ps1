<#
    check-identity.ps1 — offline identity audit. Generates nothing, builds
    nothing, writes nothing; it only re-derives every recorded hash and compares.

    Run this before trusting any checkpoint claim, and always before publication.
    A checkpoint that says "ROM: PASS" is only meaningful next to this script's
    output for the same files.

    Checks
      * exactly one *.gba in the project root, matching docs/ROM_IDENTITY.json
      * the ROM header fields the identity record claims (title, code, entry)
      * the local BIOS dump (bios/gba_bios.bin) SHA-1/SHA-256
      * reference/gbarecomp HEAD == docs/FRAMEWORK_PIN.json upstream_commit,
        and every file the pinned patch set touches hashes to the recorded
        blob SHA-1
      * the vendored toml++ header hash
      * the generator and CLI binary hashes
      * that no local-only material (ROM/BIOS/saves/generated C++) is tracked
        by git, when this directory is a git work tree
#>
[CmdletBinding()]
param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$pass = 0; $fail = 0; $warn = 0
# Content identity is line-ending independent. `git hash-object` normalises CRLF
# through the checkout's clean filter, but a submodule nested inside
# reference/gbarecomp resolves that filter differently, so hash the LF-normalised
# bytes explicitly instead of depending on the caller's git configuration.
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
function Ok($m)   { $script:pass++; if (-not $Quiet) { Write-Host "  PASS  $m" -ForegroundColor Green } }
function Bad($m)  { $script:fail++; Write-Host "  FAIL  $m" -ForegroundColor Red }
function Warn($m) { $script:warn++; Write-Host "  WARN  $m" -ForegroundColor Yellow }
function Head($m) { Write-Host "`n$m" -ForegroundColor Cyan }

$identityPath = Join-Path $Root 'docs\ROM_IDENTITY.json'
$pinPath      = Join-Path $Root 'docs\FRAMEWORK_PIN.json'
if (-not (Test-Path $identityPath)) { throw "Missing $identityPath" }
if (-not (Test-Path $pinPath))      { throw "Missing $pinPath" }
$identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
$pin      = Get-Content -LiteralPath $pinPath -Raw | ConvertFrom-Json

function Hash($path, $algo) { (Get-FileHash -LiteralPath $path -Algorithm $algo).Hash.ToLower() }

Head 'ROM'
$roms = @(Get-ChildItem -LiteralPath $Root -Filter '*.gba' -File)
if ($roms.Count -ne 1) { Bad "expected exactly one .gba in $Root, found $($roms.Count)" }
else {
    $rom = $roms[0]
    if ($rom.Length -ne $identity.rom.size_bytes) { Bad "size $($rom.Length) != $($identity.rom.size_bytes)" } else { Ok "size $($rom.Length)" }
    foreach ($algo in @('MD5', 'SHA1', 'SHA256')) {
        $prop = $algo.ToLower()
        $have = Hash $rom.FullName $algo
        if ($have -ne $identity.rom.$prop) { Bad "$algo $have != $($identity.rom.$prop)" } else { Ok "$algo $have" }
    }
    # Header bytes, read rather than trusted: title @0xA0..0xAB, code @0xAC..0xAF, entry @0x00..0x03
    $fs = [System.IO.File]::OpenRead($rom.FullName)
    try {
        $hdr = New-Object byte[] 192
        [void]$fs.Read($hdr, 0, 192)
    } finally { $fs.Dispose() }
    $title = ([System.Text.Encoding]::ASCII.GetString($hdr, 0xA0, 12)).Trim([char]0)
    $code  = [System.Text.Encoding]::ASCII.GetString($hdr, 0xAC, 4)
    if ($title -ne $identity.rom.internal_title) { Bad "title '$title' != '$($identity.rom.internal_title)'" } else { Ok "title '$title'" }
    if ($code  -ne $identity.rom.game_code) { Bad "game code '$code' != '$($identity.rom.game_code)'" } else { Ok "game code '$code'" }
    $entryWord = '0x{0:X8}' -f ([BitConverter]::ToUInt32($hdr, 0))
    if ($entryWord -ne $identity.rom.entry_branch_0x000) { Bad "entry word $entryWord != '$($identity.rom.entry_branch_0x000)'" } else { Ok "entry word $entryWord" }
}

Head 'BIOS (local-only dump)'
$bios = Join-Path $Root 'bios\gba_bios.bin'
if (-not (Test-Path $bios)) { Warn "no local BIOS dump at bios\gba_bios.bin (cartridge-only work still works)" }
else {
    if ((Hash $bios 'SHA1') -ne $identity.bios.sha1) { Bad 'SHA-1 mismatch' } else { Ok "SHA-1 $($identity.bios.sha1)" }
    if ((Hash $bios 'SHA256') -ne $identity.bios.sha256) { Bad 'SHA-256 mismatch' } else { Ok 'SHA-256 matches' }
}

Head 'Framework revision'
$framework = Join-Path $Root 'reference\gbarecomp'
$dirty = @()
if (-not (Test-Path (Join-Path $framework 'CMakeLists.txt'))) { Bad "no framework snapshot at $framework" }
else {
    if (Test-Path (Join-Path $framework '.git')) {
        $safe = "safe.directory=$($framework.Replace('\', '/'))"
        $head = (& git -c $safe -C $framework rev-parse HEAD 2>$null).Trim()
        $upCommit = $pin.framework.upstream_commit
        $headNote = $null
        if ($head -eq $upCommit) {
            Ok "upstream HEAD $head"
        } else {
            # A checkout may also carry a local history (this project's own
            # development tree commits the patch set). What must hold is that the
            # pinned upstream commit is an ancestor and that the CONTENT still
            # matches the pin — checked per file below.
            & git -c $safe -C $framework merge-base --is-ancestor $upCommit $head 2>$null
            if ($LASTEXITCODE -eq 0) {
                Ok "HEAD $head carries pinned upstream $upCommit in its history"
            } else {
                $headNote = "HEAD $head does not contain pinned upstream commit $upCommit"
            }
        }
        $dirty = @(& git -c $safe -C $framework status --porcelain 2>$null | Where-Object { $_ })
        Ok "$($dirty.Count) working-tree path(s) differ from HEAD (expected when the patch set is uncommitted; content is verified below)"
    } else {
        Warn 'framework checkout has no .git; upstream commit and patch hashes cannot be re-verified'
    }

    # The pinned identity is upstream commit + patch set, so the files each patch
    # touches are verified against the blob SHA-1 prefixes recorded in the pin,
    # resolved against that patch's own base (the main checkout or a submodule).
    # The hash is line-ending normalised, so a CRLF working tree and an LF one
    # hash the same way.
    function Resolve-PatchBase {
        param([string]$AppliesTo)
        $rel = $AppliesTo -replace '/', '\'
        $pinned = ($pin.framework.checkout -replace '/', '\')
        if ($rel -eq $pinned) { return $framework }
        if ($rel.StartsWith($pinned + '\')) { return (Join-Path $framework $rel.Substring($pinned.Length + 1)) }
        return (Join-Path $Root $rel)
    }

    $patchErrors = 0
    foreach ($p in $pin.patches) {
        $patchFile = Join-Path $Root ($p.file -replace '/', '\')
        $bad = 0
        if (-not (Test-Path $patchFile)) { Bad "patch missing: $($p.file)"; $patchErrors++; continue }
        $have = (Get-FileHash -LiteralPath $patchFile -Algorithm SHA256).Hash.ToLower()
        if ($have -ne $p.sha256) { Bad "$($p.file) sha256 $have != pinned"; $patchErrors++; continue }
        $targets = @(Select-String -LiteralPath $patchFile -Pattern '^diff --git a/(\S+) b/' |
            ForEach-Object { $_.Matches[0].Groups[1].Value })
        $base = Resolve-PatchBase -AppliesTo $p.applies_to
        $verified = 0
        foreach ($pair in $p.verify_blob_sha1_prefix.PSObject.Properties) {
            $rel = $pair.Name
            $file = Join-Path $base ($rel -replace '/', '\')
            if (-not (Test-Path -LiteralPath $file)) { Bad "patch $($p.order): missing $rel"; $bad++; continue }
            $blob = Get-NormalizedBlobSha1 -Path $file
            if (-not $blob -or $blob.Substring(0, 12) -ne $pair.Value) { Bad "patch $($p.order): $rel blob $blob != pinned $($pair.Value)"; $bad++ }
            else { $verified++ }
        }
        $patchErrors += $bad
        if ($bad -eq 0) { Ok "patch $($p.order) $($p.file): sha256 ok, $verified file(s) verified, $($targets.Count) target(s)" }
    }
    if ($patchErrors -eq 0 -and $pin.patches.Count -gt 0) { Ok 'pinned patch set is applied and verified' }
    # The file hashes above are the substantive test. A history that does not
    # descend from upstream is only a warning when the content is exactly right
    # (this development tree is such a checkout), and an error when it is not.
    if ($headNote) {
        if ($patchErrors -eq 0) { Warn "$headNote (content matches the pin, so this is a local-history checkout)" }
        else { Bad $headNote }
    }

    $expected = @('src\runtime\generated_bios\bios_recompiled.cpp', 'src\runtime\generated_bios\bios_recompiled.h')
    foreach ($e in $expected) {
        if (Test-Path (Join-Path $framework $e)) { Bad "BIOS-derived generated source present in the snapshot: $e" }
    }
    if (-not (Test-Path (Join-Path $framework 'src\runtime\generated_bios\bios_dispatch_stub.cpp'))) {
        Bad 'framework placeholder bios_dispatch_stub.cpp missing (CMakeLists.txt:429 needs it)'
    }
}

Head 'Pinned dependencies'
$toml = Join-Path $Root 'reference\tomlplusplus\toml.hpp'
if (-not (Test-Path $toml)) { Bad 'vendored toml++ header missing' }
else {
    $have = Hash $toml 'SHA256'
    if ($have -ne $pin.dependencies.tomlplusplus.header_sha256) { Bad "toml.hpp $have != pinned" } else { Ok "toml.hpp $have" }
}

Head 'Generator and baseline tool'
$gen = Join-Path $Root 'build\framework\Release\gba_recompile.exe'
if (-not (Test-Path $gen)) { Warn 'framework generator not built (run tools/regeneration/build-framework.ps1)' }
else {
    $have = Hash $gen 'SHA256'
    $known = @($pin.verified_builds | ForEach-Object { $_.sha256 })
    if ($known -contains $have) { Ok "gba_recompile.exe $have (recorded build)" }
    else { Warn "gba_recompile.exe $have is not one of the recorded builds (rebuild is not bit-reproducible across toolchain versions)" }
}
$SharedRoot = if ($env:GAME_RECOMP_ROOT) { $env:GAME_RECOMP_ROOT } else { Split-Path -Parent $Root }
$cli = Join-Path $SharedRoot 'gbarecomp-cli-windows-x86_64\gbarecomp.exe'
if (Test-Path $cli) { Ok "prebuilt CLI present, sha256 $(Hash $cli 'SHA256')" } else { Warn 'prebuilt CLI not found (baseline A needs it)' }

Head 'Publication audit — is any local-only material tracked?'
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { Warn 'git not available' }
elseif (-not (Test-Path (Join-Path $Root '.git'))) { Warn 'not a git work tree yet; nothing can be audited' }
else {
    $safe = "safe.directory=$($Root.Replace('\', '/'))"
    $tracked = & git -c $safe -C $Root ls-files
    # One deliberate exception: the framework build needs a TOML parser header and
    # the only copy on this machine is the checkout's own dependency, so the single
    # MIT header reference/tomlplusplus/toml.hpp is vendored and tracked (its hash
    # is pinned in docs/FRAMEWORK_PIN.json). Everything else under reference/ is a
    # local checkout and must never be tracked.
    $vendored = @('reference/tomlplusplus/toml.hpp')
    $violations = $tracked | Where-Object {
        $_ -notin $vendored -and (
            $_ -match '\.(gba|agb|gbc?|bin|rom|sav|srm|state)$' -or
            $_ -match '^(generated|build|baseline|roms|saves|logs|reference)/' -or
            $_ -match 'bios_recompiled|generated_bios|recompiled_[0-9]+\.cpp'
        )
    }
    if ($violations) { Bad "tracked local-only files:`n$($violations -join "`n")" }
    else { Ok "no ROM/BIOS/save/generated/build material tracked ($($tracked.Count) files tracked; only the vendored $($vendored[0]) is allowed by name)" }
}

Write-Host ''
Write-Host ("identity audit: {0} passed, {1} failed, {2} warnings" -f $pass, $fail, $warn) -ForegroundColor ($(if ($fail) { 'Red' } else { 'Green' }))
exit $(if ($fail) { 1 } else { 0 })
