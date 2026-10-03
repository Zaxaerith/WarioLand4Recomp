<#
.SYNOPSIS
    Publication audit for WarioLand4Recomp (priority K, release boundary).

.DESCRIPTION
    Checks the *tracked* file set against the publication boundary: hand-written
    integration only, no ROM / BIOS / save / generated ROM-derived code / build
    output / dumps, and no machine-specific absolute paths or secrets.

    It is deliberately a repeatable script rather than a hand-written checklist:
    the same argument closed G7 (a manual miss-fragment merge became
    tools/validation/merge_miss_fragment.py) and rule 21 in docs/VALIDATION.md -
    "the inputs of a release must be explicit, and a file another tool globs or
    git tracks is one of those inputs".

    Read-only. It never stages, commits, deletes or rewrites anything, and it
    never runs the ROM.

.PARAMETER Root
    Project root. Defaults to the repository this script lives in.

.PARAMETER Json
    Also write a machine-readable result to logs/release/publication-audit.json.

.EXAMPLE
    pwsh tools/release/publication-audit.ps1
#>
[CmdletBinding()]
param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- helpers ----

$script:Fails = 0
$script:Warns = 0
$script:Rows = New-Object System.Collections.Generic.List[object]

function Add-Row {
    param([string]$Rule, [string]$Status, [string]$Detail)
    $script:Rows.Add([pscustomobject]@{ rule = $Rule; status = $Status; detail = $Detail })
    $tag = switch ($Status) { 'PASS' { '  ok  ' } 'WARN' { ' warn ' } default { ' FAIL ' } }
    $colour = switch ($Status) { 'PASS' { 'DarkGray' } 'WARN' { 'Yellow' } default { 'Red' } }
    Write-Host "[$tag] $Rule  $Detail" -ForegroundColor $colour
    switch ($Status) { 'FAIL' { $script:Fails++ } 'WARN' { $script:Warns++ } }
}

function Test-Pass { param([string]$Rule, [string]$Detail) Add-Row $Rule 'PASS' $Detail }
function Test-Warn { param([string]$Rule, [string]$Detail) Add-Row $Rule 'WARN' $Detail }
function Test-Fail { param([string]$Rule, [string]$Detail) Add-Row $Rule 'FAIL' $Detail }

# ------------------------------------------------------------------ setup ----

Write-Host "== WarioLand4Recomp publication audit ==" -ForegroundColor Cyan
Write-Host "root: $Root"

Push-Location $Root
try {
    if (-not (Test-Path -LiteralPath '.git')) {
        Add-Row 'K0' 'FAIL' 'not a git repository - nothing to audit'
        return
    }

    # git ls-files -z: paths with spaces must survive intact.
    $raw = & git ls-files -z
    if ($LASTEXITCODE -ne 0) { Add-Row 'K0' 'FAIL' 'git ls-files failed'; return }
    $tracked = @(($raw -join "`n") -split "`0" | Where-Object { $_ -ne '' })
    $nTracked = $tracked.Count
    Write-Host "tracked files: $nTracked"
    Add-Row 'K0' 'PASS' "$nTracked tracked files enumerated"

    # ------------------------------------------------------ K1 required ------
    $required = @(
        'README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', '.gitignore',
        'baserom.md', 'game.toml', 'CMakeLists.txt',
        'src/main.cpp', 'docs/ROM_IDENTITY.json', 'docs/FRAMEWORK_PIN.json',
        'docs/KNOWN_ISSUES.md', 'docs/VALIDATION.md',
        'tools/regeneration/regen.ps1', 'tools/regeneration/build-host.ps1',
        'tools/validation/run-route.ps1', 'tools/validation/smoke.ps1',
        'tests/routes/routes.csv'
    )
    $missing = @($required | Where-Object { $tracked -notcontains $_ })
    if ($missing.Count -eq 0) {
        Test-Pass 'K1' "all $($required.Count) required publishable files are tracked"
    } else {
        # Say which of them are merely untracked rather than absent: that is the
        # difference between "stage it" and "write it".
        $untrackedOnly = @($missing | Where-Object { Test-Path -LiteralPath $_ })
        $absent = @($missing | Where-Object { -not (Test-Path -LiteralPath $_) })
        $detail = ''
        if ($untrackedOnly.Count) { $detail += "present but not staged: $($untrackedOnly -join ', ')" }
        if ($absent.Count) {
            if ($detail) { $detail += '; ' }
            $detail += "not on disk: $($absent -join ', ')"
        }
        Test-Fail 'K1' $detail
    }

    # ------------------------------------------- K2 forbidden directories ----
    # Everything below is local-only: a checkout, a build tree or a dump must
    # never be published. A single allowlist entry is the one documented exception.
    $allowPrefix = @('reference/tomlplusplus/toml.hpp')
    $forbiddenPrefix = @(
        'build/', 'generated/', 'recomp_generated/', 'recomp_cache/', 'logs/',
        'roms/', 'saves/', 'bios/', 'third_party/', '.deps/', 'dist/',
        'release/', 'out/', 'traces/', 'dumps/'
    )
    $forbiddenExt = @(
        '.gba', '.agb', '.gb', '.gbc', '.sav', '.bin', '.rom', '.o', '.obj',
        '.exe', '.dll', '.lib', '.a', '.pdb', '.ilk', '.png', '.bmp', '.jpg',
        '.log', '.trace', '.jsonl', '.pyc'
    )
    $violations = New-Object System.Collections.Generic.List[string]
    foreach ($f in $tracked) {
        if ($allowPrefix -contains $f) { continue }
        foreach ($p in $forbiddenPrefix) {
            if ($f -like "$p*") { $violations.Add("$f  (forbidden prefix $p)") }
        }
        $ext = [System.IO.Path]::GetExtension($f)
        if ($ext -and $forbiddenExt -contains $ext.ToLowerInvariant()) {
            $violations.Add("$f  (forbidden extension $ext)")
        }
    }
    if ($violations.Count -eq 0) {
        Test-Pass 'K2' "no tracked file sits in a local-only directory or has a local-only extension"
    } else {
        foreach ($v in $violations) { Write-Host "         $v" -ForegroundColor Red }
        Test-Fail 'K2' "$($violations.Count) tracked file(s) inside the local-only boundary"
    }

    # -------------------------------------------- K3 binary blob ceiling ----
    # A hand-written integration file is text. Anything large is ROM-derived or
    # a build artefact that slipped in, whatever its name.
    $big = New-Object System.Collections.Generic.List[string]
    foreach ($f in $tracked) {
        $item = Get-Item -LiteralPath $f -ErrorAction SilentlyContinue
        if ($item -and $item.Length -gt 1048576) { $big.Add("$f  ($($item.Length) bytes)") }
    }
    if ($big.Count -eq 0) {
        Test-Pass 'K3' 'no tracked file exceeds 1 MiB (no ROM blob, no build output)'
    } else {
        foreach ($b in $big) { Write-Host "         $b" -ForegroundColor Red }
        Test-Fail 'K3' "$($big.Count) tracked file(s) over 1 MiB"
    }

    # ---------------------------------------- K4 machine-specific paths -----
    # Release boundary: publishable text must use the placeholder convention
    # (<PROJECT_ROOT>, ${GBARECOMP_ROOT}) instead of a personal path.
    # Two severities, because a personal home directory and a conventional
    # shared toolchain root are not the same defect.
    $textFiles = $tracked | Where-Object {
        [System.IO.Path]::GetExtension($_) -notin @('.png', '.bmp', '.jpg', '.gif', '.exe', '.dll', '.o', '.obj')
    }
    $textLines = foreach ($f in $textFiles) {
        $line = 0
        foreach ($t in (Get-Content -LiteralPath $f -ErrorAction SilentlyContinue)) { [pscustomobject]@{ f = $f; n = $line++; t = $t } }
    }

    # K4a - a personal location. Never acceptable anywhere, no allowlist.
    $personal = [ordered]@{
        'windows-user-profile' = '(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s"''`]'
        'named-install-root'    = '(?i)[A-Z]:[\\/]+myapply[\\/]'
        'unix-home'             = '(?i)/(?:home|Users)/[A-Za-z0-9._-]+/'
    }
    $personalHits = @($textLines | Where-Object { $line = $_; @($personal.GetEnumerator() | Where-Object { $line.t -match $_.Value }) })
    if ($personalHits.Count -eq 0) {
        Test-Pass 'K4a' "no personal absolute path in $($textFiles.Count) tracked text file(s)"
    } else {
        foreach ($h in ($personalHits | Select-Object -First 20)) { Write-Host "         $($h.f):$($h.n)  $($h.t.Trim())" -ForegroundColor Red }
        Test-Fail 'K4a' "$($personalHits.Count) personal absolute path occurrence(s)"
    }

    # K4b - a conventional shared root. Legitimate, but only if every occurrence
    # is a reviewed one: the allowlist is per file, and the reason is written
    # down so a reviewer can disagree with it.
    $sharedRules = [ordered]@{
        'msys64'        = '(?i)[A-Z]:[\\/]+msys64[\\/]'
        'shared-project-root' = '(?i)[A-Z]:[\\/]+Project[\\/]+GameRecomp[\\/]'
    }
    # file -> why an absolute shared root is correct in that file
    $sharedAllow = @{
        'CMakeLists.txt'          = 'documented last-resort SDL2/toolchain search path in the GBARECOMP_MINGW_PREFIX_UNIX list'
        'README.md'               = 'the known-limitations table quotes the framework''s own hardcoded path verbatim as the F2 evidence it tells the reader to expect'
        'docs/KNOWN_ISSUES.md'    = 'quotes the framework''s own hardcoded path verbatim as evidence for F2'
        'tools/regeneration/build-host.ps1' = 'documented toolchain fallback, overridable with -Toolchain'
        'tools/validation/run-route.ps1'    = 'comment quoting the framework source line for F2'
    }
    $unreviewed = New-Object System.Collections.Generic.List[string]
    $reviewed = 0
    foreach ($entry in $textLines) {
        foreach ($rule in $sharedRules.GetEnumerator()) {
            if ($entry.t -match $rule.Value) {
                if ($sharedAllow.ContainsKey($entry.f)) { $reviewed++ }
                else { $unreviewed.Add("$($entry.f):$($entry.n)  [$($rule.Key)]  $($entry.t.Trim())") }
                break
            }
        }
    }
    if ($unreviewed.Count -eq 0) {
        Test-Pass 'K4b' "$reviewed shared-root path(s), all in the reviewed allowlist ($($sharedAllow.Count) files)"
    } else {
        foreach ($h in ($unreviewed | Select-Object -First 20)) { Write-Host "         $h" -ForegroundColor Red }
        Test-Fail 'K4b' "$($unreviewed.Count) unreviewed shared-root path(s)"
    }

    # ------------------------------------------------- K5 secret-ish scan ----
    $secretRules = [ordered]@{
        'credential-assignment' = '(?i)\b(api[_-]?key|secret|password|passwd|access[_-]?token|private[_-]?key)\b\s*[:=]\s*["'']?[A-Za-z0-9/+_-]{12,}'
        'aws-key'               = 'AKIA[0-9A-Z]{16}'
        'github-pat'            = 'gh[pousr]_[A-Za-z0-9]{20,}'
        'openai-key'            = 'sk-[A-Za-z0-9]{20,}'
    }
    $secretHits = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $textLines) {
        foreach ($rule in $secretRules.GetEnumerator()) {
            if ($entry.t -match $rule.Value) { $secretHits.Add("$($entry.f):$($entry.n)  [$($rule.Key)]") }
        }
    }
    if ($secretHits.Count -eq 0) {
        Test-Pass 'K5' 'no credential-shaped string in tracked text'
    } else {
        foreach ($h in $secretHits) { Write-Host "         $h" -ForegroundColor Red }
        Test-Fail 'K5' "$($secretHits.Count) credential-shaped string(s)"
    }

    # ------------------------------------------ K6 identity gate coherence ----
    # The generator's hard hash check must be the ROM we actually gate on;
    # otherwise the repository's own claims disagree.
    try {
        $rom = Get-Content -LiteralPath 'docs/ROM_IDENTITY.json' -Raw | ConvertFrom-Json
        $want = $rom.rom.sha1
        $toml = Get-Content -LiteralPath 'game.toml' -Raw
        if ($toml -match [regex]::Escape($want)) {
            Test-Pass 'K6' "game.toml carries the ROM SHA-1 from docs/ROM_IDENTITY.json ($want)"
        } else {
            Test-Fail 'K6' "game.toml does not carry ROM SHA-1 $want"
        }
        if ($rom.rom.game_code -and (Get-Content -LiteralPath 'src/main.cpp' -Raw) -match [regex]::Escape('b9fe05a8080e124b67bce6a623234ee3b518a2c1')) {
            Test-Pass 'K7' 'src/main.cpp pins the same ROM SHA-1 as the builtin gate'
        } else {
            Test-Warn 'K7' 'src/main.cpp does not pin the ROM SHA-1 (host would fall back to the asset picker)'
        }
    } catch {
        Test-Fail 'K6' "could not read docs/ROM_IDENTITY.json: $_"
    }

    # -------------------------------------------- K8 LICENSE placeholder ----
    # The licence text deliberately carries a placeholder the owner must fill
    # in. This is the one audit result that only the human can close.
    $lic = Get-Content -LiteralPath 'LICENSE' -Raw
    if ($lic -match '(?m)^Copyright \(c\).*<[^>]+>') {
        Test-Warn 'K8' 'LICENSE still carries the "<PROJECT OWNER ...>" placeholder - only the owner can close this'
    } elseif ($lic -match '(?m)^Copyright \(c\)\s*\S') {
        Test-Pass 'K8' 'LICENSE names a copyright holder'
    } else {
        Test-Fail 'K8' 'LICENSE has no recognisable copyright line'
    }

    # ------------------------------------ K9 third-party notices coverage ----
    if (-not (Test-Path -LiteralPath 'THIRD_PARTY_NOTICES.md')) {
        Test-Fail 'K9' 'THIRD_PARTY_NOTICES.md does not exist'
    } elseif ($tracked -notcontains 'THIRD_PARTY_NOTICES.md') {
        Test-Fail 'K9' 'THIRD_PARTY_NOTICES.md is present but not staged'
    } else {
        $n = Get-Content -LiteralPath 'THIRD_PARTY_NOTICES.md' -Raw
        $mustHave = [ordered]@{
            'GBARecomp'        = 'gbarecomp'
            'tomlplusplus'     = 'tomlplusplus'
            'SDL2'             = 'SDL2'
            'lilDavid decomp'  = 'lilDavid'
            'MinGW runtime'    = 'MinGW'
        }
        $absent = @($mustHave.GetEnumerator() | Where-Object { $n -notmatch [regex]::Escape($_.Value) } | ForEach-Object { $_.Key })
        if ($absent.Count -eq 0) {
            Test-Pass 'K9' "THIRD_PARTY_NOTICES.md covers $($mustHave.Count) pinned dependencies"
        } else {
            Test-Fail 'K9' "THIRD_PARTY_NOTICES.md does not mention: $($absent -join ', ')"
        }
    }

    # ------------------------------------------ K10 README required facts ----
    if (-not (Test-Path -LiteralPath 'README.md')) {
        Test-Fail 'K10' 'README.md does not exist'
    } elseif ($tracked -notcontains 'README.md') {
        Test-Fail 'K10' 'README.md is present but not staged'
    } else {
        $r = Get-Content -LiteralPath 'README.md' -Raw
        $need = [ordered]@{
            'ROM requirement'   = 'Wario Land 4 \(USA, Europe\)\.gba'
            'ROM SHA-1'         = 'b9fe05a8080e124b67bce6a623234ee3b518a2c1'
            'regen entry point' = 'regen\.ps1'
            'host build'        = 'build-host\.ps1'
            'smoke suite'       = 'smoke\.ps1'
            'licence'           = 'PolyForm'
            'no ROM in repo'    = 'not (be )?(include|commit|ship|distribut)'
        }
        $absent = @($need.GetEnumerator() | Where-Object { $r -notmatch $_.Value } | ForEach-Object { $_.Key })
        if ($absent.Count -eq 0) {
            Test-Pass 'K10' 'README.md states the ROM requirement, the build entry points, the smoke suite and the licence'
        } else {
            Test-Fail 'K10' "README.md is missing: $($absent -join ', ')"
        }
    }

    # ------------------------------- K11 nothing publishable is untracked ----
    # A hand-written file that exists but is not tracked would silently vanish
    # from the release; this is the G12 lesson applied to git (rule 21).
    $untracked = @(& git ls-files --others --exclude-standard | Where-Object { $_ -ne '' })
    $expectedUntracked = @('recomp_coverage_AWAE.json', 'recomp_master_misses_AWAE.toml.frag')
    $surprising = @($untracked | Where-Object { $expectedUntracked -notcontains $_ })
    if ($surprising.Count -eq 0) {
        Test-Pass 'K11' "untracked-and-unignored files: only the $((@($untracked)).Count) known runtime artefacts"
    } else {
        foreach ($u in $surprising) { Write-Host "         $u" -ForegroundColor Yellow }
        Test-Warn 'K11' "$($surprising.Count) untracked file(s) that are not git-ignored - decide before publishing"
    }

    # --------------------- K12 nothing publishable is HIDDEN by .gitignore ----
    # K11 cannot see a wrongly-ignored file: `ls-files --others
    # --exclude-standard` deliberately omits it, and `git status` says nothing
    # either. This is not hypothetical -- an unanchored `release/` rule in
    # .gitignore excluded tools/release/publication-audit.ps1, the audit script
    # itself, for a whole round. Every publishable file that exists on disk must
    # therefore be *checkable* as well as *tracked*: ask git-ignore directly, and
    # report which of the two very different fixes applies.
    $mustBePublishable = @($required + @('tools/release/publication-audit.ps1')) |
        Sort-Object -Unique
    $presentNotTracked = @($mustBePublishable |
        Where-Object { (Test-Path -LiteralPath $_) -and ($tracked -notcontains $_) })
    $hidden = @()
    foreach ($f in $presentNotTracked) {
        & git check-ignore -q -- $f
        if ($LASTEXITCODE -eq 0) { $hidden += $f }
    }
    if ($hidden.Count -eq 0) {
        Test-Pass 'K12' "none of the $($mustBePublishable.Count) publishable files is hidden by .gitignore"
    } else {
        foreach ($f in $hidden) { Write-Host "         $f" -ForegroundColor Red }
        Test-Fail 'K12' "$($hidden.Count) publishable file(s) are git-ignored: a directory rule is probably unanchored (needs a leading /), so they would never be published and no other check can see them"
    }
} finally {
    Pop-Location
}

# ----------------------------------------------------------------- result ----

$verdict = if ($script:Fails -gt 0) { 'FAIL' } else { 'PASS' }
Write-Host ''
Write-Host ("verdict: {0}   FAIL={1}  WARN={2}" -f $verdict, $script:Fails, $script:Warns) `
    -ForegroundColor $(if ($script:Fails -gt 0) { 'Red' } else { 'Green' })

if ($Json) {
    # Best effort: logs/ is git-ignored and may be read-only in a sandboxed run.
    # A missing report must not turn an audit verdict into a script crash.
    $outDir = Join-Path $Root 'logs\release'
    $outFile = Join-Path $outDir 'publication-audit.json'
    try {
        if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        [pscustomobject]@{
            schema  = 1
            verdict = $verdict
            fails   = $script:Fails
            warns   = $script:Warns
            tracked = @($tracked).Count
            rows    = $script:Rows
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $outFile -Encoding utf8
        Write-Host "json: $outFile"
    } catch {
        Write-Host "json: not written ($($_.Exception.Message))" -ForegroundColor DarkGray
    }
}

if ($verdict -eq 'FAIL') { exit 1 }
exit 0
