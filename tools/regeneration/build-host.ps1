<#
    build-host.ps1 — configure and build the playable host executable.

    Wraps the CMake configure/build with the local toolchain so the exact
    command line is recorded rather than remembered. It does not download
    anything: every path it uses must already exist (see docs/FRAMEWORK_PIN.json).

    Output: build\host\WarioLand4Recomp.exe (+ SDL2.dll and the MinGW runtime DLLs)
#>
[CmdletBinding()]
param(
    [string]$Toolchain,                           # MinGW root (gcc/g++ and runtime DLLs); discovered from PATH when omitted
    [string]$Sdl2Root,                            # <sdk>\x86_64-w64-mingw32
    [string]$Generator = 'Ninja',
    [string]$Configuration = 'Release',
    [ValidateSet('dynamic', 'static')]
    [string]$Link = 'dynamic',
    [switch]$Fresh
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Toolchain) {
    if ($env:MINGW_ROOT) { $Toolchain = $env:MINGW_ROOT }
    else {
        $gg = Get-Command g++.exe -ErrorAction SilentlyContinue
        if ($gg) { $Toolchain = Split-Path -Parent (Split-Path -Parent $gg.Source) }
    }
    if (-not $Toolchain) { $Toolchain = 'C:\msys64\mingw64' }
}
$BuildDir = Join-Path $Root 'build\host'
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Step($m) { Write-Host "==> $m" }
function Fail($m) { throw $m }

# --------------------------------------------------------------- preconditions
foreach ($p in @('reference\gbarecomp\CMakeLists.txt', 'reference\tomlplusplus\toml.hpp', 'game.toml', 'src\main.cpp')) {
    if (-not (Test-Path (Join-Path $Root $p))) { Fail "Missing $p" }
}
if (-not (Test-Path (Join-Path $Root 'generated\cart\dispatch_table.cpp')) -or
    -not (Test-Path (Join-Path $Root 'generated\bios\bios_recompiled.cpp'))) {
    Fail 'Generated translations missing. Run tools/regen.ps1 first.'
}

$cmake = (Get-Command cmake.exe -ErrorAction SilentlyContinue).Source
if (-not $cmake) { $cmake = 'C:\Program Files\CMake\bin\cmake.exe' }
if (-not (Test-Path $cmake)) { Fail 'cmake.exe not found on PATH or at C:\Program Files\CMake\bin' }

$gcc = Join-Path $Toolchain 'bin\gcc.exe'
$gxx = Join-Path $Toolchain 'bin\g++.exe'
if (-not (Test-Path $gxx)) { Fail "MinGW g++ not found at $gxx" }

if (-not $Sdl2Root) {
    $candidates = @(
        (Join-Path $Root 'build\deps'),
        (Join-Path $Root '.deps\sdl2\x86_64-w64-mingw32')
    ) + @(Get-ChildItem (Join-Path $Root '..\_sdl2') -Directory -Filter 'SDL2-*' -ErrorAction SilentlyContinue |
          ForEach-Object { Join-Path $_.FullName 'x86_64-w64-mingw32' }) +
      @('C:\msys64\mingw64')
    $Sdl2Root = $candidates | Where-Object { $_ -and (Test-Path (Join-Path $_ 'include\SDL2\SDL.h')) } | Select-Object -First 1
}
if ($Sdl2Root) { Step "SDL2 SDK: $Sdl2Root" } else { Step 'SDL2 SDK not found — the framework will compile host_window as a stub' }

# --------------------------------------------------------------------- configure
if ($Fresh -and (Test-Path $BuildDir)) { Remove-Item -Recurse -Force $BuildDir }

$configureArgs = @(
    '-S', $Root, '-B', $BuildDir, '-G', $Generator,
    "-DCMAKE_BUILD_TYPE=$Configuration",
    "-DCMAKE_C_COMPILER=$gcc",
    "-DCMAKE_CXX_COMPILER=$gxx",
    "-DGBARECOMP_ROOT=$(Join-Path $Root 'reference\gbarecomp')",
    "-DGBARECOMP_TOMLPP_INCLUDE_DIR=$(Join-Path $Root 'reference\tomlplusplus')",
    "-DGBARECOMP_GENERATED_BIOS_DIR=$(Join-Path $Root 'generated\bios')",
    "-DGBARECOMP_MINGW_RUNTIME_BIN=$(Join-Path $Toolchain 'bin')"
)
if ($Sdl2Root) { $configureArgs += "-DGBARECOMP_MINGW_PREFIX_UNIX=$Sdl2Root" }
if ($Link -eq 'static') {
    # Static SDL2 + static C++ runtime: the shipped .exe then has no DLL deps.
    $configureArgs += '-DGBARECOMP_STATIC_RELEASE=ON'
    $configureArgs += '-DCMAKE_EXE_LINKER_FLAGS=-static -static-libgcc -static-libstdc++'
}

$configureLog = Join-Path $LogDir 'host-configure.log'
Step "cmake configure -> $BuildDir"
& $cmake @configureArgs 2>&1 | Tee-Object -FilePath $configureLog
if ($LASTEXITCODE -ne 0) { Fail "Configure failed (exit $LASTEXITCODE); see $configureLog" }

# ------------------------------------------------------------------------- build
$buildLog = Join-Path $LogDir 'host-build.log'
$jobs = [Math]::Max(1, [Environment]::ProcessorCount - 1)
Step "cmake build -j $jobs"
& $cmake --build $BuildDir --target WarioLand4Recomp --parallel $jobs 2>&1 | Tee-Object -FilePath $buildLog
if ($LASTEXITCODE -ne 0) { Fail "Build failed (exit $LASTEXITCODE); see $buildLog" }

# ------------------------------------------------------------------------ report
$exe = Get-ChildItem -Path $BuildDir -Filter 'WarioLand4Recomp.exe' -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $exe) { Fail 'Build reported success but no WarioLand4Recomp.exe was found.' }
$hash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLower()
Step "artifact: $($exe.FullName)"
Step "size:     $($exe.Length) bytes"
Step "sha256:   $hash"
Step "runtime dir contents:"
Get-ChildItem $exe.Directory | Select-Object Length, Name | Format-Table -AutoSize | Out-String | Write-Host
