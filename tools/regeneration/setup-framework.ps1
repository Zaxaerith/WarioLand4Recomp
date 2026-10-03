<#
    setup-framework.ps1 — obtain the exact framework source this project was
    generated, built and validated against, using only public repositories.

    Everything this script does is driven by docs/FRAMEWORK_PIN.json, which is
    the single source of truth for repositories, commits and patches: it is the
    only place a revision is written down, so an unreachable pin cannot hide in
    a second copy of the list.

    Steps

      1. clone https://github.com/mstan/gbarecomp at the pinned upstream commit
      2. clone the three pinned submodules into reference/gbarecomp/external
         (the Android SDL submodule is deliberately left uninitialised)
      3. apply patches/gbarecomp/0*.patch to their pinned bases
      4. verify the patched files against the blob hashes recorded in the pin
      5. optionally build build/framework/Release/gba_recompile.exe

    A checkout that is already present is verified, never silently rebuilt or
    overwritten: remove reference/gbarecomp to start over.

    This script downloads only framework SOURCE, never a ROM, a BIOS or a save.
#>
[CmdletBinding()]
param(
    [string]$Commit,                    # override the pinned upstream commit
    [string]$ReferenceDir,              # override reference/gbarecomp
    [string]$PinFile,                   # override docs/FRAMEWORK_PIN.json
    [switch]$SkipSubmodules,
    [switch]$SkipPatches,
    [switch]$VerifyOnly,                # check an existing checkout by content, download nothing
    [string]$Toolchain,                 # passed through to build-framework.ps1
    [string]$Configuration = 'Release',
    [switch]$Build,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $PinFile)   { $PinFile   = Join-Path $Root 'docs\FRAMEWORK_PIN.json' }
if (-not $ReferenceDir) { $ReferenceDir = Join-Path $Root 'reference\gbarecomp' }
if (-not (Test-Path -LiteralPath $PinFile)) { Fail "Missing $PinFile" }

$pin = Get-Content -LiteralPath $PinFile -Raw | ConvertFrom-Json
if ($pin.schema -ne 2 -or -not $pin.framework.upstream_repository) {
    Fail "$PinFile is not a schema-2 framework pin (expected .framework.upstream_repository)."
}
$upstream = $pin.framework.upstream_repository
$upCommit = if ($Commit) { $Commit } else { $pin.framework.upstream_commit }
$patches = @($pin.patches)

$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$FetchLog = Join-Path $LogDir 'M2-framework-fetch.log'
"setup-framework.ps1  $(Get-Date -Format o)" | Set-Content -LiteralPath $FetchLog
function Log($m) { $m | Tee-Object -FilePath $FetchLog -Append | Out-Null; Write-Host "    $m" }

# --------------------------------------------------------------- git helpers
$script:Git = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $script:Git) { Fail 'git not found in PATH; setup-framework.ps1 needs git.' }

# Long upstream paths (framework + nested submodules) can exceed MAX_PATH on
# Windows; git only raises its own limit when asked.
& $script:Git config --global core.longpaths true 2>&1 | Out-Null

function Invoke-Git {
    # git prints progress on stderr, so never treat stderr output as failure.
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments,
          [switch]$AllowFailure)
    $out = & $script:Git @Arguments 2>&1
    $code = $LASTEXITCODE
    if ($out) { $out | ForEach-Object { Log "git $($_ -replace '\s+$','')" } }
    if ($code -ne 0 -and -not $AllowFailure) {
        Fail "git $($Arguments -join ' ') failed with exit $code (log: $FetchLog)"
    }
    return $code
}

function Ensure-Commit {
    # Fetch `tryRef` into a non-shallow clone and check out `sha`.
    param([string]$Dir, [string]$Url, [string]$Sha, [string]$TryRef)
    $safe = "safe.directory=$($Dir.Replace('\','/'))"
    Invoke-Git -c $safe -C $Dir fetch --depth 1 origin $TryRef
    try {
        Invoke-Git -c $safe -C $Dir -c advice.detachedHead=false checkout --detach $Sha
    } catch {
        Log "shallow fetch of $TryRef did not cover $Sha; using a full history fetch"
        Invoke-Git -c $safe -C $Dir fetch --unshallow origin
        Invoke-Git -c $safe -C $Dir -c advice.detachedHead=false checkout --detach $Sha
    }
    $head = (& $script:Git -c $safe -C $Dir rev-parse HEAD).Trim()
    if ($head -ne $Sha) { Fail "$Dir is at $head, expected $Sha" }
}

function Get-Repo {
    param([string]$Dir, [string]$Url, [string]$Sha, [string]$TryRef)
    if (Test-Path -LiteralPath (Join-Path $Dir '.git')) {
        $safe = "safe.directory=$($Dir.Replace('\','/'))"
        $head = (& $script:Git -c $safe -C $Dir rev-parse HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and $head.Trim() -eq $Sha) {
            Log "$Dir already at $Sha"
            return
        }
        if (-not $Force) {
            Fail ("$Dir exists but is at $($head -as [string]) and not at $Sha. " +
                  "Remove it and re-run, or pass -Force to fetch the pinned commit in place.")
        }
        Ensure-Commit -Dir $Dir -Url $Url -Sha $Sha -TryRef $TryRef
        return
    }
    if (Test-Path -LiteralPath $Dir) {
        $entries = @(Get-ChildItem -LiteralPath $Dir -Force)
        if ($entries.Count -gt 0) {
            Fail "$Dir exists, is not a git checkout, and is not empty. Move it aside and re-run."
        }
        Remove-Item -LiteralPath $Dir -Force
    }
    $parent = Split-Path -Parent $Dir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $stage = Join-Path $parent ('.setup-' + (Split-Path -Leaf $Dir))
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    Log "cloning $Url"
    Invoke-Git clone --filter=blob:none --no-checkout $Url $stage
    try {
        Invoke-Git -C $stage config core.longpaths true
        Ensure-Commit -Dir $stage -Url $Url -Sha $Sha -TryRef $TryRef
        if (Test-Path -LiteralPath $Dir) { Remove-Item -LiteralPath $Dir -Force }
        Move-Item -LiteralPath $stage -Destination $Dir
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Log "checked out $Sha into $Dir"
}

# --------------------------------------------------------- patch verification
# A pinned file's identity is its content, not its line endings. `git hash-object`
# normally normalises CRLF through the checkout's clean filter, but that filter is
# configured per repository and a submodule nested inside reference/gbarecomp can
# resolve it differently. Hash the LF-normalised bytes explicitly instead.
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

function Resolve-PatchBase {
    # The pin names checkout-relative paths. Redirect the main framework path to
    # -ReferenceDir so the script can prepare a checkout anywhere (a stranger
    # build does exactly that), while a submodule patch stays inside it.
    param([string]$AppliesTo)
    $rel = $AppliesTo -replace '/', '\'
    $pinned = ($pin.framework.checkout -replace '/', '\')
    $out = $ReferenceDir
    if ($rel -eq $pinned) { return (Resolve-Path -LiteralPath $out).Path }
    if ($rel.StartsWith($pinned + '\')) { $out = Join-Path $out $rel.Substring($pinned.Length + 1) }
    else { $out = Join-Path $Root $rel }
    return $out
}

function Test-PatchedTree {
    param([string]$Repo, [hashtable]$Expect)
    if (-not $Expect -or $Expect.Count -eq 0) { return $false }
    $dbg = $env:SETUP_FRAMEWORK_DEBUG
    foreach ($rel in $Expect.Keys) {
        $f = Join-Path $Repo ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $f)) {
            if ($dbg) { Log "  dbg $rel MISSING" }
            return $false
        }
        $sha = Get-NormalizedBlobSha1 -Path $f
        if ($dbg) {
            Log "  dbg $rel have=$(if ($sha) { $sha.Substring(0,12) } else { 'none' }) want=[$($Expect[$rel])] keys=$($Expect.Count) size=$((Get-Item -LiteralPath $f).Length) path=$f"
        }
        if (-not $sha -or $sha.Substring(0, 12) -ne $Expect[$rel]) {
            if ($dbg) { Log "  dbg $rel have=$(if ($sha) { $sha.Substring(0,12) } else { 'none' }) want=$($Expect[$rel])" }
            return $false
        }
    }
    return $true
}

function Assert-PatchedTree {
    param([string]$Repo, [string]$PatchFile, [hashtable]$Expect)
    if (-not $Expect -or $Expect.Count -eq 0) { return }
    $bad = @()
    foreach ($rel in ($Expect.Keys | Sort-Object)) {
        $f = Join-Path $Repo ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $f)) { $bad += "$rel (missing)"; continue }
        $sha = Get-NormalizedBlobSha1 -Path $f
        if (-not $sha -or $sha.Substring(0, 12) -ne $Expect[$rel]) { $bad += "$rel (have $(if ($sha) { $sha.Substring(0,12) } else { 'none' }), want $($Expect[$rel]))" }
    }
    if ($bad.Count -gt 0) {
        Fail ("$PatchFile was applied but the tree does not match the pin:`n  " + ($bad -join "`n  ") +
              "`nRemove the framework checkout and re-run setup.")
    }
    Log "verified $($Expect.Count) patched file(s) from $(Split-Path -Leaf $PatchFile)"
}

# ------------------------------------------------------------------ step 1+2
Step "framework pin: $upstream @ $upCommit"
Step "checkout: $ReferenceDir"
if ($VerifyOnly) {
    # What identifies a usable framework tree is its CONTENT, not the commit it
    # happens to sit on: the pinned upstream commit plus every pinned patch has
    # one fixed set of file blobs. Verify those first, so an equivalent tree is
    # accepted even when it carries a local history.
    if (-not (Test-Path -LiteralPath (Join-Path $ReferenceDir 'CMakeLists.txt'))) {
        Fail "$ReferenceDir is not a framework checkout (no CMakeLists.txt)."
    }
    $unverified = 0
    foreach ($p in ($patches | Sort-Object order)) {
        $base = Resolve-PatchBase -AppliesTo $p.applies_to
        $expect = @{}
        if ($p.verify_blob_sha1_prefix) {
            foreach ($kv in $p.verify_blob_sha1_prefix.PSObject.Properties) { $expect[$kv.Name] = $kv.Value }
        }
        if ($expect.Count -eq 0) { continue }
        if (Test-PatchedTree -Repo $base -Expect $expect) {
            Log "verified $($expect.Count) patched file(s) from $(Split-Path -Leaf $p.file)"
        } else {
            $unverified++
            Log "NOT at the pinned state: $($p.file) target files differ"
        }
    }
    $head = $null
    if (Test-Path -LiteralPath (Join-Path $ReferenceDir '.git')) {
        $safe = "safe.directory=$($ReferenceDir.Replace('\','/'))"
        $head = (& $script:Git -c $safe -C $ReferenceDir rev-parse HEAD 2>$null)
        if ($LASTEXITCODE -ne 0) { $head = $null } else { $head = $head.Trim() }
    }
    if ($unverified -eq 0) {
        if ($head -eq $upCommit) {
            Step "verified: $ReferenceDir @ $head (pinned commit + $($patches.Count) patch(es))"
        } else {
            Step ("verified: $ReferenceDir matches the pinned patch set" +
                  $(if ($head) { " (local HEAD $head, not $upCommit — the tree is what matters)" } else { ' (no git history; content verified)' }))
        }
    } else {
        Fail ("$ReferenceDir does not match the pinned framework state ($unverified patch set(s) unmatch). " +
              "Run: pwsh tools/regeneration/setup-framework.ps1 -Force")
    }
} else {
    Get-Repo -Dir $ReferenceDir -Url $upstream -Sha $upCommit -TryRef $upCommit

    if (-not $SkipSubmodules) {
        foreach ($sm in @($pin.submodules)) {
            $dir = Join-Path $ReferenceDir ($sm.path -replace '/', '\')
            Step "submodule $($sm.path) @ $($sm.commit.Substring(0,12))"
            Get-Repo -Dir $dir -Url $sm.repository -Sha $sm.commit -TryRef $sm.commit
        }
        foreach ($sm in @($pin.submodules_not_initialised)) {
            $dir = Join-Path $ReferenceDir ($sm.path -replace '/', '\')
            if (Test-Path -LiteralPath $dir) {
                $n = @(Get-ChildItem -LiteralPath $dir -Force).Count
                if ($n -eq 0) { Remove-Item -LiteralPath $dir -Force }
            }
            Log "left $($sm.path) uninitialised ($($sm.reason))"
        }
    } else {
        Step 'submodules skipped (-SkipSubmodules)'
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ReferenceDir 'CMakeLists.txt'))) {
    Fail "$ReferenceDir\CMakeLists.txt is missing; the framework checkout is incomplete."
}

# --------------------------------------------------------------- patch helpers
# The published patches are LF (they were generated from LF-normalised trees).
# `git apply` patches the WORKING TREE, and with core.autocrlf=true — the
# Windows default, and the setting this project's own checkouts use — a fresh
# clone materialises CRLF. The patch context then never matches and every file
# fails, even though the checkout is exactly the pinned revision. Normalise the
# files a patch touches before applying it; the git index is untouched, so the
# tree still compares equal to the pinned commit.
function Get-PatchTargets {
    param([string]$PatchFile)
    (Select-String -LiteralPath $PatchFile -Pattern '^diff --git a/(\S+) b/' -Encoding utf8 |
        ForEach-Object { $_.Matches[0].Groups[1].Value })
}

function ConvertTo-LfTree {
    param([string]$Repo, [string[]]$RelativePaths)
    $converted = 0
    foreach ($rel in $RelativePaths) {
        $f = Join-Path $Repo ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $bytes = [System.IO.File]::ReadAllBytes($f)
        if ($bytes.Length -eq 0) { continue }
        $hasCr = $false
        foreach ($b in $bytes) { if ($b -eq 13) { $hasCr = $true; break } }
        if (-not $hasCr) { continue }
        $out = New-Object byte[] $bytes.Length
        $n = 0
        for ($i = 0; $i -lt $bytes.Length; $i++) {
            if ($bytes[$i] -eq 13 -and $i + 1 -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }
            $out[$n] = $bytes[$i]; $n++
        }
        [System.IO.File]::WriteAllBytes($f, $out[0..($n - 1)])
        $converted++
    }
    if ($converted -gt 0) { Log "normalised $converted file(s) to LF for patching" }
}

# -------------------------------------------------------------------- step 3+4
if (-not $SkipPatches) {
    foreach ($p in ($patches | Sort-Object order)) {
        $patchPath = Join-Path $Root ($p.file -replace '/', '\')
        if (-not (Test-Path -LiteralPath $patchPath)) { Fail "Missing patch $($p.file)" }
        $sha = (Get-FileHash -LiteralPath $patchPath -Algorithm SHA256).Hash.ToLower()
        if ($p.sha256 -and $sha -ne $p.sha256) {
            Fail "$($p.file) sha256 mismatch: have $sha, pin says $($p.sha256)"
        }
        $base = Resolve-PatchBase -AppliesTo $p.applies_to
        $safe = "safe.directory=$($base.Replace('\','/'))"
        $expect = @{}
        if ($p.verify_blob_sha1_prefix) {
            foreach ($kv in $p.verify_blob_sha1_prefix.PSObject.Properties) { $expect[$kv.Name] = $kv.Value }
        }
        Step "patch $($p.file) -> $($p.applies_to)"
        if (Test-PatchedTree -Repo $base -Expect $expect) {
            Log "already applied ($($expect.Count) file(s) match the pin)"
            continue
        }
        $check = Invoke-Git -c $safe -C $base apply --check $patchPath -AllowFailure
        if ($check -ne 0) {
            # A CRLF working tree is the normal Windows case: patches are LF.
            ConvertTo-LfTree -Repo $base -RelativePaths @(Get-PatchTargets -PatchFile $patchPath)
            $check = Invoke-Git -c $safe -C $base apply --check $patchPath -AllowFailure
        }
        if ($check -ne 0) {
            Fail ("$($p.file) does not apply to $($p.applies_to) even after normalising line endings. " +
                  "The checkout is not the pinned revision, or the patch is stale. Inspect $FetchLog.")
        }
        Invoke-Git -c $safe -C $base apply --whitespace=nowarn $patchPath
        Log 'applied'
        Assert-PatchedTree -Repo $base -PatchFile $p.file -Expect $expect
    }
} else {
    Step 'patches skipped (-SkipPatches)'
}

$head = (& $script:Git -c "safe.directory=$($ReferenceDir.Replace('\','/'))" -C $ReferenceDir rev-parse HEAD).Trim()
Step "framework ready: $ReferenceDir @ $head"
Step "identity: $($pin.framework.identity)"

# ---------------------------------------------------------------------- step 5
if ($Build) {
    $bf = Join-Path $PSScriptRoot 'build-framework.ps1'
    $buildArgs = @{ Configuration = $Configuration }
    if ($Toolchain) { $buildArgs['Toolchain'] = $Toolchain }
    Step "building the generator: $bf"
    & $bf @buildArgs
    if ($LASTEXITCODE -ne 0) { Fail "build-framework.ps1 failed with exit $LASTEXITCODE" }
} else {
    Step 'next: tools/regeneration/build-framework.ps1  (add -Build to do it here)'
}
