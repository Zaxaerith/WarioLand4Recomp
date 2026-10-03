<#
    build-framework.ps1 — build the pinned GBARecomp framework out-of-source.

    Outputs (all inside WORK_ROOT):

        build/framework/            out-of-source CMake build tree
        build/deps/tomlplusplus     pinned toml++ (vendored if absent)

    Produces the framework tools the game integration needs, chiefly
    `build/framework/Release/gba_recompile.exe`.

    The framework SOURCE is not published with this repository. It is obtained
    from public upstream repositories by tools/regeneration/setup-framework.ps1,
    which clones the commits and applies the patch set recorded in
    docs/FRAMEWORK_PIN.json. This script never downloads anything itself: it
    builds a checkout that setup-framework.ps1 already prepared, and fails with
    an actionable message when that checkout is absent.
#>
[CmdletBinding()]
param(
    [string]$Configuration = 'Release',
    [string]$Toolchain,                                   # e.g. <MINGW_ROOT>
    [string]$Generator,                                   # explicit cmake -G, optional
    [string]$TomlppInclude,                               # override toml++ header dir
    [string]$SharedRoot,                                  # legacy: MSYS/MinGW toolchain root
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$Root    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $SharedRoot) {
    $SharedRoot = if ($env:GAME_RECOMP_ROOT) { $env:GAME_RECOMP_ROOT } else { Split-Path -Parent $Root }
}
$Framework = Join-Path $Root 'reference\gbarecomp'
$Build   = Join-Path $Root 'build\framework'
$DepsToml = Join-Path $Root 'reference\tomlplusplus'
$LogDir  = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

if (-not (Test-Path (Join-Path $Framework 'CMakeLists.txt'))) {
    Fail @"
No framework checkout at $Framework.

The framework source is not published in this repository; obtain it from the
pinned public upstream revision and apply the project patch set:

    pwsh -File tools/regeneration/setup-framework.ps1

Repositories, commits and patches are recorded in docs/FRAMEWORK_PIN.json.
"@
}

# ---- cmake discovery (prefer a real native Windows cmake, not MSYS shims) ----
function Find-CMake {
    $candidates = @(
        'C:\Program Files\CMake\bin\cmake.exe',
        'C:\Program Files (x86)\CMake\bin\cmake.exe'
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    Fail 'cmake.exe not found (looked at Program Files and PATH).'
}
$CMake = Find-CMake

# ---- toml++ resolution: vendored copy first, then an explicit override ----
if (-not $TomlppInclude) {
    if (Test-Path (Join-Path $DepsToml 'toml.hpp')) {
        $TomlppInclude = $DepsToml
    } elseif (Test-Path (Join-Path $Framework 'third_party\tomlpp\toml.hpp')) {
        $TomlppInclude = Join-Path $Framework 'third_party\tomlpp'
    } else {
        Step 'toml++ not found locally; the framework will FetchContent it into the build tree'
        $TomlppInclude = ''
    }
}

$cmakeArgs = @(
    '-S', $Framework,
    '-B', $Build,
    "-DGBARECOMP_TOMLPP_INCLUDE_DIR=$TomlppInclude"
)
if ($TomlppInclude -eq '') { $cmakeArgs = @('-S', $Framework, '-B', $Build) }

if ($Generator) { $cmakeArgs += @('-G', $Generator) }

if ($Toolchain) {
    $gcc = Join-Path $Toolchain 'bin\gcc.exe'
    $gxx = Join-Path $Toolchain 'bin\g++.exe'
    if (-not (Test-Path $gcc)) { Fail "gcc.exe not found under $Toolchain\bin" }
    if (-not (Test-Path $gxx)) { Fail "g++.exe not found under $Toolchain\bin" }
    $cmakeArgs += @(
        "-DCMAKE_C_COMPILER=$gcc",
        "-DCMAKE_CXX_COMPILER=$gxx",
        '-DCMAKE_BUILD_TYPE=' + $Configuration,
        "-DGBARECOMP_MINGW_PREFIX_UNIX=$($Toolchain -replace '\\','/' -replace '^(\w):', '/$1')"
    )
} else {
    $cmakeArgs += @(
        '-DCMAKE_C_COMPILER=cl',
        '-DCMAKE_CXX_COMPILER=cl'
    )
}

if ($Clean -and (Test-Path $Build)) {
    Step "cleaning $Build"
    Remove-Item -LiteralPath $Build -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Build | Out-Null

Step "cmake: $CMake"
Step "framework: $Framework"
Step "build tree: $Build"
Step "toml++: $(if ($TomlppInclude) { $TomlppInclude } else { '(FetchContent into build tree)' })"

$cfgLog = Join-Path $LogDir 'M2-framework-configure.log'
& $CMake @cmakeArgs 2>&1 | Tee-Object -FilePath $cfgLog
if ($LASTEXITCODE -ne 0) { Fail "cmake configure failed (exit $LASTEXITCODE); see $cfgLog" }

Step "building target gba_recompile ($Configuration)"
$buildLog = Join-Path $LogDir 'M2-framework-build.log'
& $CMake --build $Build --config $Configuration --parallel --target gba_recompile 2>&1 |
    Tee-Object -FilePath $buildLog
if ($LASTEXITCODE -ne 0) { Fail "cmake build failed (exit $LASTEXITCODE); see $buildLog" }

$exe = Get-ChildItem -LiteralPath $Build -Recurse -File -Filter 'gba_recompile.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $exe) { Fail "gba_recompile.exe not found under $Build" }
Step "gba_recompile: $($exe.FullName)  ($($exe.Length) bytes)  sha256=$((Get-FileHash $exe.FullName -Algorithm SHA256).Hash)"
