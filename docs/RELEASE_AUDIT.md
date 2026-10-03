# Release audit — what may be published, and whether it can be built

> **RESOLVED AFTER THIS AUDIT — see §10.** The two blockers this audit raised are closed: the framework is
> now cloned from public upstream at a pinned commit and patched by `tools/regeneration/setup-framework.ps1`
> (B1), and `LICENSE` carries the project author's name (W2). The three untracked validation scripts (W1)
> are tracked. Everything below is the state at the audited revision and is kept as the record of what was
> wrong; §6 and §8 describe defects that no longer exist in the working tree.
Adversarial verification of the tracked set (`git ls-files`) against `AGENT_PROMPT.md` §9, plus a buildability check.
Every verdict is backed by the command and its raw output; negative results are included on purpose.
**Audited revision:** `c2c4a8147af652dbe9949b11ce6651ecc7729932` (branch `master`); **86 tracked files**, largest 485,931 B.
**No git remote is configured** (`git remote -v` → empty), so this describes what a clone of this tree would contain; concurrent
teammate edits made tracked bytes drift 2,612,670 → 2,624,570. Treat this as a timestamped snapshot, not a hash-pinned
manifest — the `README.md` / `THIRD_PARTY_NOTICES.md` anchors below were re-verified against the current files.

## 1. Verdict
**Publication boundary: CLEAN.** No ROM, BIOS, save file, build product, generated ROM-derived source,
personal absolute path or credential is tracked. No BLOCKER of that class exists; the search for one is
documented in §3–§5.
**Buildability (as audited): BLOCKER (B1); resolved in §9.** The repository was *source-complete* but **not
buildable by a stranger**: the recompiler generator came only from `reference/gbarecomp`, which is
git-ignored and deliberately not part of the repository, and the pin recorded for it was not obtainable
upstream (§6). This contradicted the README as written — a documentation/scope defect, not a
publication-boundary defect: nothing unsafe would be published as-is. Secondary, non-blocking: **W1** three
untracked validation scripts are cited by tracked docs and would vanish from a clone (§7); **W2** `LICENSE`
still carries an owner placeholder (§8).

## 2. Commands run (all read-only)
`git ls-files`, `git status --short`, `git status --short --ignored`, `git diff --stat`, `git diff --cached --stat`,
`git check-ignore -v`, `git grep -n -I -E`, `git ls-files --error-unmatch`, `Get-Item`/`Get-FileHash`, and
`pwsh -NoProfile -File tools/release/publication-audit.ps1` — run **without** `-Json`, because that flag writes
`logs/release/publication-audit.json`, outside this task's write scope. No `git add`, `git commit`, `git rm`, or
deletion was performed; nothing under `logs/` was deleted.

## 3. Forbidden artifact classes — none tracked

| Probe (`git ls-files`) | Raw result |
| --- | --- |
| Extensions `.gba .bin .rom .sav .elf .o .a .dll .exe` | `(none)` |
| Paths matching `generated\|recomp_\|recompiled\|build/\|dist/` | `(none)` |
| Files over 1 MiB (size ceiling) | `(none)`; max = 485,931 B `reference/tomlplusplus/toml.hpp` |
| Files over 200 KB | 4: `reference/tomlplusplus/toml.hpp` 485,931; `symbols/decomp_readelf_syms.txt` 448,607; `tests/input/g31-hammer.keyinput.txt` 252,228; `docs/PROGRESS.md` 235,396 |

Required artifacts are ignored and **confirmed untracked** — each exits 1 with `did not match any file(s) known
to git`: `"Wario Land 4 (USA, Europe).gba"`, `bios/gba_bios.bin`, `saves/wario_land_4_awae.sav`,
`recomp_coverage_AWAE.json`, `recomp_master_misses_AWAE.toml.frag`. `git check-ignore -v` proves each is excluded by an explicit rule (all exit 0):

```
"Wario Land 4 (USA, Europe).gba" .gitignore:13:*.gba    bios/gba_bios.bin .gitignore:22:/bios/
saves/wario_land_4_awae.sav .gitignore:29:/saves/       generated/build.ps1 .gitignore:33:/generated/
recomp_cache/<shard>.dll .gitignore:35:/recomp_cache/   build/framework/ALL_BUILD.vcxproj .gitignore:38:/build/
logs/g7-merge.toml .gitignore:82:/logs/                 reference/gbarecomp/README.md .gitignore:69:/reference/*
recomp_coverage_AWAE.json .gitignore:92                 recomp_master_misses_AWAE.toml.frag .gitignore:93
```

`git status --short --ignored` marks the ROM, `bios/`, `build/`, `generated/`, `logs/`, `recomp_cache/`,
`reference/gbarecomp/`, `saves/` with `!!`. Ignored on-disk bulk that stays out of the release:
`recomp_cache/` 7,526 entries, `build/` 819, `generated/` 147, `logs/` 2,045 files / 51,320,704 B.
**Negative control:** `reference/tomlplusplus/toml.hpp` → `(no ignore rule matched)`, exit 1 — the `!`
negations really work, so no blanket `reference/` ignore swallowed the vendored MIT header.

## 4. Personal absolute paths and secrets — none
A `git grep` for the machine-specific home directory, the account name, `AppData`, a drive-rooted user
profile pattern and `BEGIN PRIVATE KEY` over all 86 tracked files → `(no match, exit 1)`. (The probe is
described rather than reproduced: writing the literal patterns into a published file only reintroduces the
strings it is meant to prove absent. `tools/release/publication-audit.ps1` K4 carries the executable form and
is regenerated with the audit, not quoted here.) The only `D:\`-shaped text documents shared-root paths, which the
audit allowlists (13 paths, all within the reviewed 7-file allowlist). A `git grep` for token/secret/password
returns only self-descriptions, never values: `AGENT_PROMPT.md:518` (the file itself is removed before release) ("token / credential"),
`docs/VALIDATION.md:971` ("two tokens earlier"), `tools/release/publication-audit.ps1:8,212-229` (the audit's
own regex), `README.md:141`, `THIRD_PARTY_NOTICES.md:251`. No base64-like line exists in any tracked file and
no tracked line exceeds 2,000 characters. A hexdump-shape scan hit only `reference/tomlplusplus/toml.hpp`
(sampled `0xFFFFFFFFFFFFFFFFu,` constant tables in MIT third-party code) — not ROM data.

## 5. Publication audit script
`pwsh -NoProfile -File tools/release/publication-audit.ps1` → exit 0.

```
K0 86 tracked files enumerated                   K7  src/main.cpp pins the same SHA-1
K1 all 19 required publishable files tracked     K8  WARN LICENSE still carries the "<PROJECT OWNER ...>" placeholder
K2 no local-only directory or extension          K9  THIRD_PARTY_NOTICES covers 5 pinned dependencies
K3 no tracked file larger than 1 MiB             K10 README states ROM requirement / build entry points / smoke suite / licence
K4a no personal absolute path in tracked text    K11 WARN 5 untracked file(s) not git-ignored — decide before publishing
K4b 13 shared-root paths, all allowlisted        K12 none of the 20 publishable files is hidden by .gitignore
K5 no credential-shaped string                   K6  game.toml and src/main.cpp carry ROM SHA-1 b9fe05a8080e124b67bce6a623234ee3b518a2c1
verdict: PASS   FAIL=0  WARN=2
```

`FAIL=0` is the headline: the machine-checkable publication boundary passes; a re-run at the end of the audit gave the
same `PASS FAIL=0 WARN=2`, with K11 rising 5 → 7 (this report and `docs/COMPATIBILITY.md` appeared mid-audit).

## 6. BLOCKER B1 — not buildable by a stranger
`reference/gbarecomp` is the only source of the generator, and the build hard-fails without it, with no fallback
anywhere in the tracked set:

* `tools/regeneration/build-framework.ps1:42-44` — `Fail "Missing pinned framework snapshot at $Framework. See docs/FRAMEWORK_PIN.json."` (`$Framework` = `reference\gbarecomp`, line 33). Its own comment (lines 13-16) claims "Nothing is downloaded unless a pinned dependency is genuinely absent", but the script contains **no download or clone code at all**.
* `tools/regeneration/build-host.ps1:39` gates on `reference\gbarecomp\CMakeLists.txt`; line 74 passes `-DGBARECOMP_ROOT=…\reference\gbarecomp`.
* `tools/regeneration/regen.ps1:62` — `Fail "Missing framework snapshot at $framework"`; `:81-83` — `Fail "gba_recompile.exe not found. Run tools/build-framework.ps1 first."`
* `CMakeLists.txt:32,37` — `GBARECOMP_ROOT` defaults to `reference/gbarecomp` and errors "See docs/FRAMEWORK_PIN.json for the pinned revision."

The pin cannot be fetched: `docs/FRAMEWORK_PIN.json:19` pins `bcaeae1f881e795f7df29952e71cf0205ac30a87`, and its
own `pin_commit_note` (line 23) says it is *"a locally created content-identity commit (git init in
reference/gbarecomp) … the SHA is not an upstream mstan/gbarecomp commit."* No checkout of that SHA is possible
from `https://github.com/mstan/gbarecomp.git`. Proof there is no acquisition path — this grep matched only
unrelated lines:

```
git grep -n -I -E 'git (clone|fetch|submodule)|Invoke-WebRequest|Invoke-RestMethod|Start-BitsTransfer|DownloadFile|curl |wget |codeload\.github|FetchContent'
docs/FRAMEWORK_PIN.json:46                     (a toml++ codeload URL)
tools/regeneration/build-framework.ps1:66,107  (messages about toml++ FetchContent inside the absent framework)
```

The repository half-admits the gap — `THIRD_PARTY_NOTICES.md:51-52` ("a *local-only* directory: it is git-ignored
and is not part of this repository"), `:59` ("Redistribution of the framework is the framework author's decision"),
`README.md:259` ("pinned GBARecomp snapshot (local only)") — but the build instructions contradict it:
`README.md:63` says "You need the original cartridge image. **Nothing else is downloaded at build time.**",
`README.md:95-97` presents `pwsh tools/regeneration/build-framework.ps1` as build step 1 with no caveat, and
`.gitignore:65` calls reference checkouts "cloned on demand" when nothing clones them.

**Consequence:** a stranger with a legally dumped ROM + BIOS and the full toolchain still cannot produce `gba_recompile.exe`, so the project cannot be regenerated or built from a clone.

**Options (owner's decision, outside this task's write scope):** (1) have the framework author publish a reachable
upstream commit, record that SHA in `docs/FRAMEWORK_PIN.json` and add a clone/checkout step to `build-framework.ps1`;
(2) ship the snapshot if PolyForm Noncommercial 1.0.0 permits redistribution (the notices currently say it does not);
(3) re-scope the claim — state in README that the pinned framework snapshot must be obtained separately, and remove
or qualify the "nothing else is downloaded at build time" sentence.

## 7. W1 — three untracked scripts cited by tracked docs
`git status --short` shows these as `??` (untracked, not ignored), yet tracked docs point readers at them, so
they would vanish from a clone:

| Path | Bytes | SHA-256 (first 16) | Cited by |
| --- | --- | --- | --- |
| `tools/validation/wario_watch.py` | 5,331 | `D6669844FCE21EE7` | `docs/KNOWN_ISSUES.md:3282`, `docs/KNOWN_ISSUES.md:3305`, `docs/VALIDATION.md:1132` |
| `tools/validation/room_probe.py` | 3,928 | `92803BF84ED7ABFC` | `docs/KNOWN_ISSUES.md:3305`, `docs/VALIDATION.md:1133` |
| `tools/validation/gen_vortex_route.py` | 4,102 | `0C49EBEB0710F2D9` | `docs/KNOWN_ISSUES.md:3305` (the route generator the probe names) |

Also untracked: `tests/input/f51-vortex.keyinput.txt` (427 B) and `WarioLand4Recomp_DSH_Handoff_Pivot.md`
(8,239 B) — neither is referenced by any tracked file
(`git grep -n -I -E 'WarioLand4Recomp_DSH_Handoff_Pivot|f51-vortex'` → exit 1), so they are private working
files. Decision needed: either track the three documentation-referenced scripts or remove the doc references.
This is the K11 warning.

## 8. W2 — `LICENSE` owner placeholder
`LICENSE:5` reads `Copyright (c) 2026 <PROJECT OWNER — must be set before any publication>`, reported as K8. No agent
can choose the copyright holder, so this stays a warning until the human owner fills it in before publication.

## 9. Structural notes for the release
* `docs/COMPATIBILITY.md` did not exist on disk when this audit began and is still **untracked** (`??`); release-docs created it mid-audit and `README.md:57` already links it — track it before publishing.
* Markdown link check across all 7 tracked `*.md` files: **0 broken relative links**. Two naive-regex hits (`docs/KNOWN_ISSUES.md:2876`, `docs/KNOWN_ISSUES.md:3194`) are false positives — the C macro text `WarioRequestPose(pose)`.
* `.gitignore:23` re-includes `!tools/**/*.bin`. No such file exists today, but the rule is a latent hole: a dumped binary placed under `tools/` would count as tracked content.
* `logs/` is git-ignored (`.gitignore:82`), so `logs/release/upload-manifest.md` is a local working document: it will **not** be part of a published release, and `git status --short` cannot see it.

---

**Bottom line.** Publishing this tree would not leak a ROM, BIOS, save, build product, personal path or secret —
that boundary is verified clean. The audited build claim was inaccurate; §10 records how it was fixed.

## 10. Resolution (post-audit)

* **B1 — fixed by making the framework reproducible from public upstream.** The framework's real identity was
  established by content comparison, not by trusting the old pin: 22 candidate commits of
  `mstan/gbarecomp` were downloaded and diffed blob-by-blob against the local tree, and
  `477e3d12dd0920a4961d58ba625ec2afe505c1fb` matched with the smallest delta (13 files, all one upstream-only
  test fixture). The local differences — 14 files in the framework, 3 in `arm-recomp-core`, 4 in
  `recomp-net` — are now reviewable patches under `patches/gbarecomp/`, recorded by SHA-256 in
  [docs/FRAMEWORK_PIN.json](FRAMEWORK_PIN.json) (schema 2) together with the three pinned submodule
  revisions. `tools/regeneration/setup-framework.ps1` clones the pinned commit, checks out those submodules,
  applies the patches and verifies every patched file's blob SHA-1; `build-framework.ps1` now points at it,
  and its header no longer describes a download path that did not exist. The old content-identity commit
  `bcaeae1f…` is retired and must not be used again.
* **W1 — closed.** `tools/validation/wario_watch.py`, `room_probe.py` and `gen_vortex_route.py` are tracked.
* **W2 — closed.** `LICENSE:5` now reads `Copyright (c) 2026 Zaxaerith`.
* **Still worth a decision (structural notes above):** `.gitignore:23` re-includes `!tools/**/*.bin`.
* **`AGENT_PROMPT.md` — removed in §11.** It was a tracked agent handoff document whose configuration
  block hard-codes this machine's absolute paths; the final cleanup pass deleted it from the repository
  and from disk after moving its technical content into the tracked documentation.

**Bottom line, updated.** The publication boundary was and remains clean; the buildability claim is no
longer aspirational, because the framework a build uses is now reproducible from a public repository at a
pinned commit plus three patches. Whether a stranger can *finish* the build still depends on their own
toolchain (CMake, Ninja, MinGW-w64 GCC, SDL2) and their own legally dumped ROM and BIOS.

## 11. Final cleanup pass (2026-10, aggressive size reduction)

Before-state of the working directory, measured with `Get-ChildItem -Recurse | Measure-Object Length`
(untracked build output included; the repository itself is `git count-objects -vH` = 4.80 MiB):

| path | size before |
|---|---:|
| `generated/` | 255.48 MiB |
| `logs/` | 171.93 MiB |
| `recomp_cache/` | 113.27 MiB |
| `build/` | 92.73 MiB |
| `third_party/lilDavid-warioland4` | 46.41 MiB |
| `reference/` | 13.58 MiB |
| `.git` | 4.86 MiB |
| `symbols/`, `docs/`, `tools/`, `tests/`, `patches/` | 0.78 / 0.55 / 0.44 / 0.34 / 0.08 MiB |
| total working tree | 708.60 MiB |

Everything above except `.git`, `symbols/`, `docs/`, `tools/`, `tests/`, `patches/` and the
user-supplied ROM/BIOS/save is rebuildable output, and this pass deletes it. See the section below for
what was removed and how the tree was re-verified from scratch.

### What was deleted

| what | why it is safe to delete | regenerated by |
|---|---:|---|
| `generated/` (255.48 MiB) | the recompiled C++/dispatch tables are ROM-derived build output | `tools/regeneration/regen.ps1` |
| `logs/` (171.93 MiB) | traces, dumps, per-route coverage and the local release working documents | any `run-route.ps1` / `smoke.ps1` run |
| `recomp_cache/` (113.27 MiB) | self-heal cache; the runtime recreates it, it is never an input to the build | first run of the host exe |
| `build/` (92.73 MiB) | CMake/MSBuild trees and both executables; the release publishes source, not binaries | `build-framework.ps1` + `build-host.ps1` |
| `reference/gbarecomp/` (9.23 MiB) | the old local framework snapshot; superseded by the public pin | `tools/regeneration/setup-framework.ps1` |
| `third_party/lilDavid-warioland4/.git` (15.32 MiB) | upstream history of a read-only reference clone, re-clonable at the pinned commit | `git clone` + `git checkout abb7800a…` |
| `third_party/lilDavid-warioland4/tools/agbcc` (25.63 MiB) | GPL GCC source submodule; the decomp's own `make` needs WSL + `binutils-arm-none-eabi`, which this environment does not have (G11), so it is never built | `git submodule update --init tools/agbcc` inside a fresh decomp clone |
| `reference/tomlplusplus/*` except `toml.hpp` (3.89 MiB) | upstream repository clone; the framework needs exactly one amalgamated header, which is vendored and SHA-256-pinned | upstream clone if anyone wants the rest |

Kept deliberately: `symbols/*.tsv` and `game.toml` (tracked, already regenerated metadata that the
shortest smoke and the generator consume), the vendored `reference/tomlplusplus/toml.hpp`, and the
decompilation's `asm/`, `src/`, `include/`, `linker.ld` and `LICENSE` — 352 files, 5.46 MiB — which are
the text every `asm/…` and `src/…` citation in `docs/KNOWN_ISSUES.md`, `docs/VALIDATION.md` and
`baserom.md` points at. The decomp is git-ignored, so it is not part of the published tree either way;
deleting the citations' target would have made the tracked evidence index uncheckable.

### Prompt and tooling

* `AGENT_PROMPT.md` is removed from the repository (and deleted on disk): it is an agent handoff template
  whose configuration block hard-codes five absolute paths from this machine. Its technical content lives
  in [README.md](../README.md), [KNOWN_ISSUES.md](KNOWN_ISSUES.md) and [VALIDATION.md](VALIDATION.md), and
  its build instructions were superseded by the reproducible framework setup in §10.
* `tools/validation/{wario_watch,room_probe,gen_vortex_route}.py` are **kept**: they are the instruments
  named by the tracked evidence index in [VALIDATION.md](VALIDATION.md) §6 and are not needed by the
  shortest smoke. Nothing in the build, regen or smoke path imports them.
* `docs/PROGRESS.md` is **removed from the published tree at the owner's request** (it was tracked, 235 KB,
  and is the file §3 and §7 above cite by line number). It was the cross-session engineering log: the
  project's own priorities, the per-round narrative, and the environment inventory for this machine.
  Its durable technical conclusions were already duplicated in [README.md](../README.md),
  [KNOWN_ISSUES.md](KNOWN_ISSUES.md), [VALIDATION.md](VALIDATION.md) and [COMPATIBILITY.md](COMPATIBILITY.md);
  the per-round narrative is deliberately not published. Every tracked file that linked to it now either
  carries the surviving evidence inline or says which round recorded it. The published history starts at a
  single root commit that never contained it, so it is absent from the repository and from its history.
* `WarioLand4Recomp_DSH_Handoff_Pivot.md` (the agent handoff prompt that set the decomp-assisted direction)
  is likewise **never published**, and `AGENT_PROMPT.md`, the earlier working brief, is absent from the
  published history for the same reason.

### Verification after the deletions

With `generated/`, `build/`, `recomp_cache/` and `reference/` all absent, the tree was rebuilt from
scratch and re-tested; the results are recorded in §10 and [COMPATIBILITY.md](COMPATIBILITY.md). The generated translation units came back byte-identical
(SHA-256) to the ones the deleted `generated/` held, which is the strongest statement available that the
ROM-to-C++ step is deterministic given the same framework pin and patches.
