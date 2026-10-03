# baserom.md — required base ROM

This project is a **recompilation**, not a ROM distribution. No ROM, no GBA BIOS and no
ROM-derived generated code is stored in the public repository. The user supplies the
base ROM locally; every generation, build and validation run starts by re-verifying the
bytes below.

## Required input

| item | value |
| --- | --- |
| file | `Wario Land 4 (USA, Europe).gba` in `PROJECT_ROOT` (the only `*.gba` there) |
| region | US / EU |
| game code | `AWAE` |
| internal title | `WARIOLANDE` |
| maker code | `01` |
| software version (`0xBC`) | `0x00` |
| size | 8,388,608 bytes (`0x00800000`), padded with `0xFF` to 8 MiB |
| MD5 | `5fe47355a33e3fabec2a1607af88a404` |
| SHA-1 | `b9fe05a8080e124b67bce6a623234ee3b518a2c1` |
| SHA-256 | `d16c7bf6e62bb84049fff1b387108fbd1e6e2cd38ca994ab5310dd9cbf9ba414` |
| ARM entry point | file offset `0x000` = `0xEA00002E` → `0x080000C0` |
| fixed value (`0x04`) | `0x24FFAE51` |
| header checksum (`0xBD`) | stored `0x00EC`, computed `0xEC` — matches |

`AWAE` is the version lilDavid/warioland4 builds by default (`VERSION=us`); its published
hash file `warioland4_us.md5` expects exactly the MD5 above.

The Japan release (`AWAJ`, MD5 `99c8ad779a16be513a9fdff502b6f5c2`) is **not** the local ROM
and is not covered by this project's gate or by any metadata in `game.toml`.

## How the identity is enforced

| gate | where |
| --- | --- |
| ROM SHA-1 + SHA-256 re-hashed before every route | `tools/validation/run-route.ps1` |
| ROM SHA-1 + SHA-256, CLI/BIOS hashes, framework pin before generation | `tools/regeneration/regen.ps1` |
| full identity audit (ROM/BIOS/decomp/framework/toolchain) | `tools/validation/check-identity.ps1` |
| hard hash check inside the generator | `game.toml` `[identity] sha1 = "b9fe05a8080e124b67bce6a623234ee3b518a2c1"` |
| raw record | `docs/ROM_IDENTITY.json` |

A mismatch aborts before anything is generated; the runtime also re-hashes the ROM it was
launched with and refuses to boot on a different image.

## Save hardware

SRAM, 32,768 bytes, decided from the cartridge image and code — not from a filename:

* ASCII `SRAM_V112` in the ROM at file offset `0x283EF8`;
* `reference/…/lilDavid-warioland4/src/sram.c` declares `sSramVersion[] = "SRAM_V112"` and
  programs `REG_WAITCNT`;
* the runtime independently reports `save=SRAM signature=SRAM_V` at boot.

## BIOS

The GBA BIOS is **not** in this repository. `bios/gba_bios.bin` (16,384 bytes,
SHA-1 `300c20df6731a33952ded8c436f7f186d25d3492`) is a local, git-ignored copy supplied by
the user; the BIOS path is re-hash-checked before generation, the BIOS is recompiled into
local-only generated code, and all BIOS-derived C++ stays out of the repository.

## Decompilation

`lilDavid/warioland4` (MIT), pinned commit `abb7800a8d8fa6d7f7f003627893e06bc2879329`
(submodule `tools/agbcc` at `84d56fc8eb9621afca441e38a1d1ff5afe94be84`). On this machine it
was cloned under `third_party/` (git-ignored, never published) and it is **not required to
build**: the shortest path needs only the ROM, the BIOS, the pinned framework, `game.toml`
and the tracked metadata under `symbols/`. Re-create it with
`git clone https://github.com/lilDavid/warioland4 third_party/lilDavid-warioland4` and
`git -C third_party/lilDavid-warioland4 checkout abb7800a…` when the decompilation text or
the optional `-SymbolOverlay` import is wanted. It is used for names, function boundaries,
code/data split and already verified C implementations — never as an execution oracle, and
its addresses are only imported if it can rebuild a ROM with exactly the hash above.

A second, only partly-licensed reverse-engineering reference exists at
<https://github.com/wario-land/warioland4>. It was never used: any reuse from it would have to be
preceded by checking its actual licence per file, which this project did not do.

## Local-only material (never committed)

ROM, BIOS, saves, `build/`, `generated/`, `recomp_cache/`, debug dumps, traces, test
screenshots. See `.gitignore`.
