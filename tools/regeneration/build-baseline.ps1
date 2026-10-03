<#
    build-baseline.ps1 — produce the vanilla generation baseline (baseline A).

    Baseline A is the reference every later, annotated generation is measured
    against (the removed `AGENT_PROMPT.md`, decomp-annotated recomp): the shipped prebuilt CLI
    is run with NO game config and NO symbol overlay, so its discovered function
    set is the tool's unguided opinion about this cartridge.

        baseline/A-vanilla/   CLI generation, configless
        generated/cart/       generator + game.toml (+ symbol overlay) -- baseline B

    Guards: the ROM hashes must match docs/ROM_IDENTITY.json, and the CLI binary
    hashes must match the recorded ones — otherwise the "baseline" is not
    comparable with the numbers recorded for the original bring-up round.
#>
[CmdletBinding()]
param(
    [string]$Cli,                      # prebuilt gbarecomp.exe; auto-discovered when omitted
    [string]$OutDir,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SharedRoot = if ($env:GAME_RECOMP_ROOT) { $env:GAME_RECOMP_ROOT } else { Split-Path -Parent $Root }
if (-not $Cli) { $Cli = Join-Path $SharedRoot 'gbarecomp-cli-windows-x86_64\gbarecomp.exe' }
if (-not $OutDir) { $OutDir = Join-Path $Root 'baseline\A-vanilla' }
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

# Recorded CLI identity. If the tool changes, the baseline numbers stop being
# comparable, so this must be re-derived deliberately rather than silently.
$ExpectedCli = @{
    exe    = '05e26ff754238b545089e774cdd9876f1e99a295012cd490ec863cca60b5f6ae'
    core   = 'b54ff097f3b397ed04943e911a381f1e4be3a9b859a82ce6fc0c379ff99c6d14'
    version = 'gbarecomp 0.2.0'
}

$identity = Get-Content -LiteralPath (Join-Path $Root 'docs\ROM_IDENTITY.json') -Raw | ConvertFrom-Json
$roms = @(Get-ChildItem -LiteralPath $Root -Filter '*.gba' -File)
if ($roms.Count -ne 1) { Fail "Expected exactly one .gba in $Root, found $($roms.Count)." }
$rom = $roms[0].FullName

$romSha = (Get-FileHash $rom -Algorithm SHA256).Hash.ToLower()
if ($romSha -ne $identity.rom.sha256) { Fail "ROM SHA-256 mismatch ($romSha). Wrong ROM." }

if (-not (Test-Path $Cli)) { Fail "CLI not found: $Cli" }
$cliSha = (Get-FileHash $Cli -Algorithm SHA256).Hash.ToLower()
if ($cliSha -ne $ExpectedCli.exe) {
    Fail @"
CLI binary changed.
  have: $cliSha
  want: $($ExpectedCli.exe)
A new tool is a new baseline. Review the new tool, record the new numbers, then
update `$ExpectedCli` in this script deliberately.
"@
}
$core = Join-Path (Split-Path -Parent $Cli) '_internal\gba_recompile-core.exe'
if (Test-Path $core) {
    $coreSha = (Get-FileHash $core -Algorithm SHA256).Hash.ToLower()
    if ($coreSha -ne $ExpectedCli.core) { Fail "CLI core binary changed (have $coreSha, want $($ExpectedCli.core))." }
}

$version = (& $Cli --version) 2>&1 | Select-Object -First 1
if ("$version".Trim() -ne $ExpectedCli.version) { Fail "CLI version changed: '$version' (expected '$($ExpectedCli.version)')." }

Step "ROM   : $rom  sha256=$romSha"
Step "CLI   : $Cli  sha256=$cliSha  version=$version"

if ((Test-Path $OutDir) -and -not $Force) {
    Step "baseline already present at $OutDir (use -Force to regenerate)"
} else {
    if (Test-Path $OutDir) { Remove-Item -LiteralPath $OutDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}
$log = Join-Path $LogDir 'baseline-A-vanilla-generation.log'
Step "generating (no --config, no --symbols) -> $OutDir"
& $Cli build --rom $rom --output $OutDir --force --verbose 2>&1 | Tee-Object -FilePath $log
if ($LASTEXITCODE -ne 0) { Fail "Baseline A generation failed (exit $LASTEXITCODE); see $log" }

# Record the comparable numbers straight out of the log so a later diff does not
# depend on anyone's memory.
$text = Get-Content -LiteralPath $log -Raw
$functions = if ($text -match 'discovered\s+(\d+)\s+functions') { [int]$Matches[1] } else { -1 }
$shards = @(Get-ChildItem -LiteralPath (Join-Path $OutDir 'generated') -Filter 'recompiled_*.cpp' -File -ErrorAction SilentlyContinue)
$bytes = ($shards | Measure-Object -Property Length -Sum).Sum

$summary = [ordered]@{
    baseline          = 'A-vanilla'
    kind              = 'prebuilt CLI 0.2.0, no game.toml, no symbol overlay'
    rom_sha256        = $romSha
    cli_sha256        = $cliSha
    cli_version       = "$version".Trim()
    discovered_functions = $functions
    shards            = $shards.Count
    shard_bytes       = $bytes
    log               = 'logs/baseline-A-vanilla-generation.log'
} | ConvertTo-Json -Depth 4
$summaryPath = Join-Path $Root 'logs\baseline-A-vanilla-summary.json'
Set-Content -LiteralPath $summaryPath -Value $summary -Encoding UTF8
Step "discovered functions: $functions   shards: $($shards.Count)   bytes: $bytes"
Step "summary written to $summaryPath"
