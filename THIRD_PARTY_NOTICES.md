# Third-party notices

WarioLand4Recomp is built on top of several independent projects. This file records every
one of them, its licence, how it is used here, and what you must ship alongside a
redistributed binary.

This project is a **recompilation**, not a ROM distribution. The Game Boy Advance ROM, the
GBA BIOS and all ROM-derived generated code are **not** committed, published or
redistributed by this repository — see [baserom.md](baserom.md).

---

## 1. The licence of this project

GBARecomp, the recompilation framework this project is generated and built with, is licensed
**PolyForm Noncommercial 1.0.0** (see §2). That licence grants a copyright licence only for
*noncommercial purposes* and states that the software "is not covered by your licenses" for
any other use.

This project's own hand-written material is distributed under **PolyForm Noncommercial
1.0.0** as well — see [LICENSE](LICENSE). That choice is the copyright holder's and it
matches the framework it is built with: the practical effect is that neither the framework
nor this project may be used commercially, and a commercial use needs whatever permission
the respective copyright holder grants. Nothing in this file is legal advice, and nothing
here relicenses, or claims to relicense, any third-party component — each one keeps its own
terms, listed below.

> The `LICENSE` file still carries a `<PROJECT OWNER — must be set before any publication>`
> placeholder. Only the copyright holder can fill that in. `tools/release/publication-audit.ps1`
> rule **K8** reports it as a warning until then.

---

## 2. GBARecomp

| | |
| --- | --- |
| Upstream | <https://github.com/mstan/gbarecomp> |
| Licence | PolyForm Noncommercial 1.0.0 |
| Copyright | Copyright (c) 2026 Matthew Stanley |
| Pinned revision | upstream commit `477e3d12dd0920a4961d58ba625ec2afe505c1fb` on `main` ("Merge pull request #21 from mstan/release/discord-signin-0.1.1") |
| Pinned submodules | `external/arm-recomp-core` → `mstan/arm-recomp-core@763b922f4912708d2704e7833f18addfbf8ddf33`; `external/rbengine` → `RetroPortingToolKit/rbengine@2a03e73693acee0fb78076ea058642c931bef12e`; `external/recomp-net` → `RetroPortingToolKit/recomp-net@d3524c6fef49dcfd511d2de7df4ba5a6e7900732` |
| Local modifications | three patches under `patches/gbarecomp/` (14 + 3 + 4 files), recorded by SHA-256 in [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json) |
| Vendored libraries | `external/arm-recomp-core` (MIT, © 2026 Matthew Stanley), `external/rbengine` (MIT, © 2026 retcomm-rbengine contributors), `external/recomp-net` (MIT, © 2026 recomp-net contributors) |
| Also ships | `third_party/MPL-2.0.txt` in the fetched tree — the Mozilla Public License 2.0, for vendored code under that licence |

**How it is obtained.** Nothing from GBARecomp is redistributed here. A fresh clone runs
`pwsh tools/regeneration/setup-framework.ps1`, which clones
<https://github.com/mstan/gbarecomp> at the pinned commit above, checks out the three pinned
submodules, applies this project's patches, and verifies every patched file. The result lands in
`reference/gbarecomp/`, which is git-ignored. The identity of the framework a build actually used
— upstream commit, submodule revisions, patch hashes and the resulting per-file blob SHA-1s — is
recorded in [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json), and
`setup-framework.ps1 -VerifyOnly` re-checks it.

**Why the patches exist.** They are small and functional, not cosmetic: the four
`GBARECOMP_TAIL_*` tail-transfer macros the ARM core emits for this game's code generator profile,
a keypad-IRQ path, the `SRAM_F_V` save signature, a 64 KiB flash device-id fix, an MSVC `clz32`
branch and UTF-8 compile flags for non-ASCII math symbols in the framework's own sources.

**How it is used.** `reference/gbarecomp/` supplies the recompiler `gba_recompile.exe` and the
runtime (`runtime_dispatch`, the dispatch table, the self-heal compiler, the SDL2 window/audio
host and the TCP observer).

**Licence text.** The framework's licence arrives with the clone as `reference/gbarecomp/LICENSE`
(PolyForm Noncommercial 1.0.0), and this project's [LICENSE](LICENSE) carries the same licence text
under this project's own copyright line.

---

## 3. toml++ (tomlplusplus)

| | |
| --- | --- |
| Upstream | <https://github.com/marzer/tomlplusplus> |
| Version | v3.4.0 |
| Licence | MIT |
| Copyright | Copyright (c) Mark Gillard |
| Pinned commit | `30172438cee64926dc41fdd9c11fb3ba5b2ba9de` |
| Upstream archive SHA-256 | `0badb114fa26325320cfbcce28b5953f85942d2a0bb1e4fdd99197497afd2ed5` (the archive the header came from, as recorded in [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json)) |
| Header SHA-256 | `6b5172ad4dd6519aec67b919181fa7a38a2234131e5b2afa232dfe444819783e` (re-hashed from the vendored copy; matches the pin) |
| Version in the file | `toml.hpp` line 3 reads `toml++ v3.4.0`; `TOML_LIB_MAJOR/MINOR/PATCH` = 3/4/0 |

**How it is used.** Parses `game.toml`, the per-game recompiler configuration. This is the
**only third-party source file tracked by this repository**:
`reference/tomlplusplus/toml.hpp`, unmodified, as the single-file amalgamated distribution
the upstream provides. The MIT licence requires the notice to travel with the file; it is
reproduced below in full.

```text
MIT License

Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The single-file header also embeds a UTF-8 decoder derived from Bjoern Hoehrmann's DFA
decoder (<https://bjoern.hoehrmann.de/utf-8/decoder/dfa/>). The vendored copy carries the
attribution comment at `reference/tomlplusplus/toml.hpp:8953-8954` — `Copyright (c) 2008-2009
Bjoern Hoehrmann <bjoern@hoehrmann.de>` — and no separate licence text; its own licence
terms could not be verified from inside the vendored file, so treat the attribution as the
notice and the surrounding header's MIT terms as the licence covering the distribution.

---

## 4. SDL2

| | |
| --- | --- |
| Upstream | <https://github.com/libsdl-org/SDL> |
| Version | 2.32.8 (the `SDL2-2.32.8` development libraries) |
| Licence | zlib (the notice below is `LICENSE.txt` from that distribution) |
| Copyright | Copyright (C) 1997-2025 Sam Lantinga |
| Shipped by this project | `SDL2.dll`, staged next to `build/host/WarioLand4Recomp.exe` by `tools/regeneration/build-host.ps1` |
| Local copy | `<sibling>/_sdl2/SDL2-2.32.8`, whose `.git-hash` records `98d1f3a45aae568ccd6ed5fec179330f47d4d356` |

**How it is used.** The host runtime's window, input, audio and timer host. The build
discovers it from `<project>/.deps/sdl2`, from a **sibling** `_sdl2/SDL2-*/` directory, or
from an MSYS2 prefix — each candidate is probed for
`x86_64-w64-mingw32/include/SDL2/SDL.h`, and the first hit is used. Override it explicitly
with `pwsh tools/regeneration/build-host.ps1 -Sdl2Root <sdk>` (a prefix containing
`x86_64-w64-mingw32`). SDL2 is never modified, and never hardcoded as the only option —
if no prefix is found the framework compiles its window layer as a stub instead of failing.

**If you redistribute the executable** you must ship `SDL2.dll` (staged next to the
executable by the build) **and** this notice, which the zlib licence requires to be kept
unaltered:

```text
Copyright (C) 1997-2025 Sam Lantinga <slouken@libsdl.org>

This software is provided 'as-is', without any express or implied
warranty.  In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would be
   appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
```

The `SDL2-2.32.8` copy used here ships a single `LICENSE.txt` (the notice above) and no
separate zlib notice; whatever SDL2 itself links (its `x86_64-w64-mingw32/bin` carries
`SDL2.dll` and `sdl2-config`, nothing else) is inside upstream's own binary. This project
vendors no SDL2 dependency separately and copies only `SDL2.dll` next to the executable.

---

## 5. MinGW-w64 GCC runtime

| | |
| --- | --- |
| Toolchain | GCC 16.1.0, `gcc.exe (x86_64-win32-seh-rev0, Built by MinGW-Builds project)` |
| Runtime DLLs staged next to the executable | `libgcc_s_seh-1.dll`, `libstdc++-6.dll`, `libwinpthread-1.dll` |
| Licence | GPLv3 **with the GCC Runtime Library Exception**, and the MinGW-w64 runtime exception for the POSIX/CRT-style runtime |

**How it is used.** Compiles the host executable and supplies its C/C++ runtime. It is
discovered from `PATH` and overridable with `build-host.ps1 -Toolchain`.

**Redistribution.** The GCC Runtime Library Exception and the MinGW-w64 runtime exception
explicitly permit shipping these runtime DLLs with an independent (non-GPL) program without
the whole program becoming GPL. The exception texts ship with the toolchain and must be
included with any redistribution:

| file | licence |
| --- | --- |
| `licenses/gcc/COPYING3` | GNU General Public License v3 |
| `licenses/gcc/COPYING3.LIB` | GNU Lesser General Public License (the file's own title) |
| `licenses/gcc/COPYING.RUNTIME` | GCC Runtime Library Exception (covers `libgcc_s_seh-1.dll`, `libstdc++-6.dll`) |
| `licenses/mingw-w64/COPYING.MinGW-w64-runtime.txt` | MinGW-w64 runtime licensing (covers `libwinpthread-1.dll` and the mingw-w64 runtime) |
| `licenses/mingw-w64/COPYING.MinGW-w64.txt` | MinGW-w64 licensing (headers, libraries, exceptions) |
| `licenses/mingw-w64/COPYING` | MinGW-w64 general notice, with the prominently marked exceptions |
| `licenses/winpthreads/COPYING` | winpthreads |

Each path is relative to the MinGW-w64 installation root (`<toolchain>/licenses/…`). The
exact set of licences an installation ships can differ between MinGW-w64 builds, so list the
directory rather than assuming.

The remaining compiler components (binutils, gdb, gmp, mpfr, mpc, isl, ppl, cloog, expat,
ncurses, readline, zlib, xz, bzip2, sqlite, libffi, libiconv, openssl, make, tcl/tk, python)
are build-time only and are not shipped with the executable.

---

## 6. Wario Land 4 decompilation (reference only)

| | |
| --- | --- |
| Upstream | <https://github.com/lilDavid/warioland4> |
| Licence | MIT |
| Copyright | Copyright (c) 2025 lilDavid |
| Pinned commit | `abb7800a8d8fa6d7f7f003627893e06bc2879329` |
| Submodule | `tools/agbcc` at `84d56fc8eb9621afca441e38a1d1ff5afe94be84` |

```text
MIT License

Copyright (c) 2025 lilDavid

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Verified against the local clone, while it was present.** `git -C third_party/lilDavid-warioland4 remote -v`
reported `https://github.com/lilDavid/warioland4.git` (the upstream URL in the table above),
`rev-parse HEAD` returned `abb7800a8d8fa6d7f7f003627893e06bc2879329`, and
`git submodule status` returned `84d56fc8eb9621afca441e38a1d1ff5afe94be84 tools/agbcc
(release-7-g84d56fc)` — all three matched the pin. The MIT text above is reproduced from that
clone's `LICENSE`. The final size-reduction pass then deleted that clone's `.git` directory and its
`tools/agbcc` submodule checkout, so a fresh `git rev-parse` on this machine can no longer reproduce
those two lines; the pins are recorded here and in [baserom.md](baserom.md) instead, and a re-clone
at the pinned commit restores the identical tree.

**How it is used, and how it is not.** The clone lives under `third_party/` — git-ignored,
never published, never redistributed by this repository. It is **not needed for the shortest
build**: the recompiler consumes the tracked metadata in `symbols/` and `game.toml`. When present
it is used as *text*: function names, function boundaries, the code/data split, the IWRAM linker
map, and already-verified C implementations, which the optional `-SymbolOverlay` import reads into
`generated/`. It is **never** used as an execution oracle, and its addresses are only imported after
the ROM identity gate passes. This project does not redistribute decompiled code.

`tools/agbcc` is a historical GCC-derived ARM compiler that ships inside that
decompilation. It was never built or executed here — no decompilation toolchain
(`arm-none-eabi-objdump`, `agbcc`) is available in this environment — and its 25.6 MiB checkout was
deleted in the size-reduction pass; it is mentioned only for completeness of the pin.

---

## 7. The game itself

Wario Land 4 is © Nintendo / Nintendo Software Planning & Development. This project
contains none of its code, art, music, text or other content, and redistributes no part of
it. It requires that you supply your own legally obtained copy of the cartridge; see
[baserom.md](baserom.md) for the exact image the build gate accepts.

The repository is a from-scratch recompilation of the machine code into new C++: the
generated translation is produced locally from the user's own ROM by `tools/regeneration/regen.ps1`
and is never committed.

---

## 8. Generated and fetched material

| material | status |
| --- | --- |
| `generated/cart/*.cpp`, `generated/bios/*` | ROM- and BIOS-derived generated C++. Local only, git-ignored, regenerated on demand. Never hand-edited. |
| `recomp_cache/` | the self-heal compiler's cache. Local only. |
| `build/` | build trees and the executable. Local only. |
| `logs/` | run logs, coverage reports, miss fragments, observer traces. Local only. |
| `saves/`, `roms/`, `bios/` | your save file, your ROM, your BIOS dump. Local only. |

None of the above is a dependency of the source tree: the build regenerates them from the
pinned framework, the pinned decompilation and your own ROM.

---

## 9. Verifying the notices

`tools/release/publication-audit.ps1` checks that this file exists, that it names every
pinned dependency (rule **K9**), and that nothing publishable violates the boundary in
[README.md](README.md) — no ROM, no BIOS, no generated code, no personal paths, no secrets.

```powershell
pwsh tools/release/publication-audit.ps1 -Json
```

### How each claim above was checked

| claim | checked against |
| --- | --- |
| toml++ version and MIT text | `reference/tomlplusplus/toml.hpp` (lines 3–40) and `reference/tomlplusplus/LICENSE` |
| toml++ header hash | SHA-256 of the vendored header, compared with the value in [docs/FRAMEWORK_PIN.json](docs/FRAMEWORK_PIN.json) |
| framework pin, tree, size, upstream URL | `git -C reference/gbarecomp rev-parse HEAD` / `log -1`, `git ls-files \| Measure-Object -Line` (568), and `docs/FRAMEWORK_PIN.json` |
| vendored framework library licences | `reference/gbarecomp/external/{arm-recomp-core,rbengine,recomp-net}/LICENSE`, `reference/gbarecomp/third_party/MPL-2.0.txt` |
| SDL2 version and zlib text | `x86_64-w64-mingw32/include/SDL2/SDL_version.h` (`SDL_MAJOR_VERSION` 2, `SDL_MINOR_VERSION` 32), the `SDL2-2.32.8` distribution name for the patch level, `LICENSE.txt` for the notice; `SDL2.dll` present in `build/host` |
| MinGW licence locations | `gcc --version` and a listing of the toolchain's `licenses/` tree |
| decompilation pin and MIT text | as in §6 above |

Claims that could **not** be verified from material in this workspace: the licence of the
embedded Bjoern Hoehrmann UTF-8 decoder (§3), and the upstream commit identity of a
framework snapshot that has no `.git` of its own (§2, which is why the local pin exists).
