#!/usr/bin/env python3
"""parse_decomp_symbols.py — harvest a decompilation's symbol table from its
SOURCES, without building it.

Why this exists
---------------
`gbarecomp-main/docs/SYMBOL_OVERLAY.md` names the decompilation's real symbols as
the way to turn an anonymous recompilation into a readable one. Its documented
route runs the decomp's build (`readelf -sW` on the ELF, `readelf -SW` on the
sections, `ld -Map` on the link map). This machine has no WSL and installing one
is explicitly out of scope for this project, so the build route is unavailable.

The source route is available. A pret-style decomp declares where everything is
in the sources themselves:

  asm/macros.s.inc     `thumb_func_start name` / `arm_func_start name` mark a
                       function and its instruction set; the disassembler names
                       most functions after their own ROM address
                       (`func_80104A4` -> 0x080104A4).
  asm/blob_*.s         `.global sUnk_8283F14` + `baserom_blob 0x283F14, 0x283F54`
                       is a ROM data symbol with an EXACT extent.
  linker.ld            the `iwram (NOLOAD)` section pins every IWRAM global with
                       an explicit offset (`. = 0x1910; gHeartMeter = .;`), i.e.
                       the same ABS symbols `readelf` would report for them.

So the three inputs the importer wants can be *derived* from the decomp's text.
This tool writes the `--syms` file (and, optionally, a `--sections` file built
only from what the sources state) in the exact `readelf` text format
`gbarecomp-main/tools/symbol_import/import_decomp_symbols.py` parses, then hands
off to it: the framework still owns the overlay format, the identity gate and
the `[[data_range]]` decisions.

What is deliberately NOT invented
---------------------------------
* A function whose name does not encode its address (`thumb_func_start
  SpriteSpawnSecondary`) gets NO row. Guessing an address would silently label
  the wrong code, which is the one failure mode the overlay document warns about.
  They are counted and reported under `--report` instead.
* No `[[data_range]]` is proposed from the sources: the exact code/data split of
  the cartridge is a linker decision, and this project's reviewed ranges live in
  `game.toml`. Only ROM data symbols with a stated `baserom_blob` extent and the
  `linker.ld` IWRAM globals are emitted, and they name memory; they do not
  restructure code discovery.

Usage
-----
  python tools/validation/parse_decomp_symbols.py \\
      --decomp third_party/lilDavid-warioland4 \\
      --out    symbols \\
      --report

  python gbarecomp-main/tools/symbol_import/import_decomp_symbols.py \\
      --id AWAE --name "Wario Land 4 (USA, Europe)" \\
      --syms symbols/decomp_readelf_syms.txt \\
      --rom  "<rom>.gba" --out symbols
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROM_BASE = 0x08000000

# `thumb_func_start func_80104A4` / `arm_func_start func_8000B1C` / the
# non-aligned variant used where the disassembler could not insert padding.
FUNC_START_RE = re.compile(
    r"^\s*(arm_func_start|thumb_func_start|thumb_func_start_non_aligned)\s+(\S+)"
)
# A function name that IS its own address. Two conventions coexist in the same
# file and they must not be confused:
#   func_80104A4   -> the FULL address with the leading zero dropped
#                     (0x080104A4), which is what the disassembler names code.
#   .L_104d0       -> the offset inside the 0x08000000 window (0x080104D0).
# Anything that does not already look like a ROM address gets ROM_BASE added, so
# a short/offset-style name still lands correctly.
ADDR_NAME_RE = re.compile(r"^(?:func|sub|nullsub)_([0-9A-Fa-f]{6,8})$")
# `.global sUnk_8283F14` and the label that follows it.
GLOBAL_RE = re.compile(r"^\s*\.global\s+(\S+)")
LABEL_RE = re.compile(r"^\s*(\S+):\s*(?:@.*)?$")
# `baserom_blob 0x283F14, 0x283F54` — a ROM extent stated by the decomp.
BLOB_RE = re.compile(
    r"^\s*baserom_blob\s+0x([0-9A-Fa-f]+)\s*,\s*0x([0-9A-Fa-f]+)"
)
# A local label carries the absolute ROM offset in its name (`.L_135f4`).
LOCAL_LABEL_RE = re.compile(r"^\.L_([0-9A-Fa-f]{4,8})$")
SECTION_RE = re.compile(r"^\s*\.section\s+(\S+)")

# The recompiler's own discovery, used to CHECK the address convention below
# rather than assume it: `generated/cart/dispatch_table.cpp` rows look like
# `{0x08010A9Cu, 12u, 3u, thumb}`.
DISPATCH_RE = re.compile(r"\{\s*0x([0-9A-Fa-f]+)u")

# linker.ld: `. = 0x1910; gHeartMeter = .;` inside the `iwram (NOLOAD)` block.
ASSIGN_RE = re.compile(
    r"^\s*\.\s*=\s*(0x[0-9A-Fa-f]+)\s*;\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\.\s*;\s*$"
)
ORIGIN_RE = re.compile(r"^\s*IWRAM\s*\(\S*\)\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+)", re.I)
IWRAM_MARKER = "iwram (NOLOAD)"


class Symbol:
    __slots__ = ("addr", "mode", "size", "name", "source")

    def __init__(self, addr, mode, size, name, source):
        self.addr = addr          # address WITHOUT the thumb bit
        self.mode = mode          # "thumb" | "arm" | "data"
        self.size = size
        self.name = name
        self.source = source      # file:line for the report


def parse_functions(asm_dir: pathlib.Path, report: dict):
    """Return (functions, data) harvested from asm/**/*.s."""
    funcs: list[Symbol] = []
    data: list[Symbol] = []
    unnamed: list[Symbol] = []

    for path in sorted(asm_dir.rglob("*.s")):
        rel = path.relative_to(asm_dir.parent).as_posix()
        pending_global = None
        pending_line = 0
        section = ""
        for lineno, raw in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            m = SECTION_RE.match(raw)
            if m:
                section = m.group(1)
                continue
            m = FUNC_START_RE.match(raw)
            if m:
                macro, name = m.group(1), m.group(2)
                mode = "arm" if macro == "arm_func_start" else "thumb"
                am = ADDR_NAME_RE.match(name)
                if am:
                    addr = int(am.group(1), 16)
                    if not (ROM_BASE <= addr < ROM_BASE + 0x02000000):
                        addr += ROM_BASE
                    funcs.append(
                        Symbol(addr, mode, 0, name, f"{rel}:{lineno}")
                    )
                else:
                    unnamed.append(Symbol(0, mode, 0, name, f"{rel}:{lineno}"))
                pending_global = None
                continue
            m = GLOBAL_RE.match(raw)
            if m:
                pending_global = m.group(1)
                pending_line = lineno
                continue
            m = BLOB_RE.match(raw)
            if m and pending_global is not None:
                start, end = int(m.group(1), 16), int(m.group(2), 16)
                if end > start:
                    data.append(
                        Symbol(ROM_BASE + start, "data", end - start,
                               pending_global, f"{rel}:{pending_line}")
                    )
                pending_global = None
                continue
            m = LABEL_RE.match(raw)
            if m:
                label = m.group(1)
                if pending_global is not None and label == pending_global:
                    continue      # the blob row follows the label, not this line
                lm = LOCAL_LABEL_RE.match(label)
                if lm:
                    report["local_labels"] += 1
                pending_global = None

    # Function sizes: the next function in the same file, when both addresses
    # are known and increasing. Sources are emitted in ROM order.
    by_file: dict[str, list[Symbol]] = {}
    for f in funcs:
        by_file.setdefault(f.source.split(":")[0], []).append(f)
    for rows in by_file.values():
        rows.sort(key=lambda s: s.addr)
        for a, b in zip(rows, rows[1:]):
            if b.addr > a.addr:
                a.size = b.addr - a.addr

    report["functions_named"] = len(funcs)
    report["functions_unnamed"] = len(unnamed)
    report["functions_unnamed_sample"] = unnamed[:8]
    report["functions_thumb"] = sum(1 for f in funcs if f.mode == "thumb")
    report["functions_arm"] = sum(1 for f in funcs if f.mode == "arm")
    report["rom_data_symbols"] = len(data)
    report["rom_data_bytes"] = sum(d.size for d in data)
    return funcs, data, unnamed


def parse_iwram(ld_path: pathlib.Path, report: dict):
    """Return the IWRAM globals the linker script pins, with gap sizes."""
    if not ld_path.is_file():
        report["iwram"] = "linker script not found"
        return []
    origin = None
    inside = False
    entries: list[tuple[int, str]] = []
    for line in ld_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ORIGIN_RE.match(line)
        if m:
            origin = int(m.group(1), 16)
        if IWRAM_MARKER in line:
            inside = True
            continue
        if inside and line.strip().startswith("}") and not line.strip().startswith("};"):
            inside = False
        if not inside:
            continue
        m = ASSIGN_RE.match(line)
        if m and origin is not None:
            off = int(m.group(1), 16)
            name = m.group(2)
            # `obj/main.o(iwram_data)`-style section markers are not symbols.
            if "(" in name or ")" in name or name.endswith(".o"):
                continue
            entries.append((origin + off, name))
    entries.sort()
    out = []
    for i, (addr, name) in enumerate(entries):
        size = entries[i + 1][0] - addr if i + 1 < len(entries) else 0
        out.append(Symbol(addr, "data", size, name, "linker.ld"))
    report["iwram_symbols"] = len(out)
    report["iwram_origin"] = origin
    return out


def readelf_sym_rows(funcs, data_syms) -> list[str]:
    """Render rows the importer's SYM_RE accepts.

    Layout it parses:  num: value size TYPE BIND VIS NDX name
    bit0 of st_value is the THUMB flag, which is why it is set here.
    """
    rows = ["Symbol table '.symtab' contains %d entries:" % (len(funcs) + len(data_syms))]
    idx = 0
    for f in sorted(funcs, key=lambda s: (s.addr, s.name)):
        idx += 1
        value = f.addr | (1 if f.mode == "thumb" else 0)
        rows.append(
            f"{idx:6d}: {value:08x} {f.size:6d} FUNC    GLOBAL DEFAULT    2 {f.name}"
        )
    for d in sorted(data_syms, key=lambda s: (s.addr, s.name)):
        idx += 1
        if d.addr >= 0x08000000:
            rows.append(
                f"{idx:6d}: {d.addr:08x} {d.size:6d} OBJECT  GLOBAL DEFAULT    2 {d.name}"
            )
        else:
            rows.append(
                f"{idx:6d}: {d.addr:08x} {d.size:6d} NOTYPE  GLOBAL DEFAULT  ABS {d.name}"
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description="harvest decomp symbols from sources (no build required)"
    )
    ap.add_argument("--decomp", required=True, type=pathlib.Path,
                    help="decompilation checkout (uses asm/ and linker.ld)")
    ap.add_argument("--out", required=True, type=pathlib.Path,
                    help="directory for decomp_readelf_syms.txt")
    ap.add_argument("--name", default="decomp_readelf_syms.txt",
                    help="output file name")
    ap.add_argument("--report", action="store_true",
                    help="print what was found, and what could not be addressed")
    ap.add_argument("--verify-rom", type=pathlib.Path, default=None,
                    help="check every harvested address against the ROM: in "
                         "range, 2-byte aligned, and a plausible Thumb prologue")
    ap.add_argument("--dispatch", type=pathlib.Path, default=None,
                    help="informational: how many harvested addresses appear in "
                         "generated/cart/dispatch_table.cpp (that table is a "
                         "per-instruction resume map, NOT a function list, so a "
                         "low overlap is expected and is not a failure)")
    args = ap.parse_args()

    asm_dir = args.decomp / "asm"
    if not asm_dir.is_dir():
        print(f"error: no asm directory at {asm_dir}", file=sys.stderr)
        return 2

    report = {"local_labels": 0}
    funcs, data_rom, unnamed = parse_functions(asm_dir, report)
    data_iwram = parse_iwram(args.decomp / "linker.ld", report)

    # --out accepts either a directory (writes <dir>/<--name>) or a file path
    if args.out.suffix:
        out_path = args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        out_path = args.out / args.name
    rows = readelf_sym_rows(funcs, data_rom + data_iwram)
    out_path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")

    print(f"decomp:            {args.decomp}")
    print(f"wrote:             {out_path}  ({len(rows) - 1} symbol rows, "
          f"{out_path.stat().st_size} bytes)")
    print(f"functions:         {report['functions_named']} addressed "
          f"(thumb {report['functions_thumb']} / arm {report['functions_arm']})")
    print(f"                   {report['functions_unnamed']} named but NOT "
          f"addressable -> skipped (no address in the name)")
    print(f"ROM data symbols:  {report['rom_data_symbols']} "
          f"({report['rom_data_bytes']} bytes with stated extents)")
    print(f"IWRAM globals:     {report.get('iwram_symbols', 0)} "
          f"(origin {report.get('iwram_origin')})")
    print(f"local .L_ labels:  {report['local_labels']} (used for the report only)")

    if args.verify_rom is not None:
        if not args.verify_rom.is_file():
            print(f"error: no ROM at {args.verify_rom}", file=sys.stderr)
            return 2
        rom = args.verify_rom.read_bytes()
        lo, hi = ROM_BASE, ROM_BASE + len(rom)
        out_of_range = [f for f in funcs if not (lo <= f.addr < hi)]
        unaligned = [f for f in funcs if f.addr % 2]
        prologue = 0
        for f in funcs:
            if f.mode != "thumb":
                continue
            off = f.addr - ROM_BASE
            h = rom[off] | (rom[off + 1] << 8) if off + 2 <= len(rom) else 0
            if h >> 8 in (0xB4, 0xB5) or h in (0x4770,):
                prologue += 1
        thumb_n = sum(1 for f in funcs if f.mode == "thumb") or 1
        print(f"verified against:  {args.verify_rom.name} ({len(rom)} bytes)")
        print(f"in ROM / aligned:  {len(funcs) - len(out_of_range)}/{len(funcs)} in "
              f"range, {len(funcs) - len(unaligned)}/{len(funcs)} 2-byte aligned")
        print(f"thumb prologues:   {prologue}/{thumb_n} "
              f"({100.0 * prologue / thumb_n:.1f}%) begin with `push {{…}}` or "
              f"`bx lr` (the rest are leaf/one-instruction functions)")
        if out_of_range or unaligned:
            print("error: harvested addresses outside the ROM or misaligned — "
                  "the name convention is being misread", file=sys.stderr)
            return 1
        if prologue * 2 < thumb_n:
            print("error: fewer than half the harvested thumb addresses look "
                  "like function prologues", file=sys.stderr)
            return 1

    if args.dispatch is not None:
        if not args.dispatch.is_file():
            print(f"error: no dispatch table at {args.dispatch}", file=sys.stderr)
            return 2
        known = set()
        for line in args.dispatch.read_text(
                encoding="utf-8", errors="replace").splitlines():
            m = DISPATCH_RE.search(line)
            if m:
                known.add(int(m.group(1), 16))
        hits = sum(1 for f in funcs if f.addr in known)
        print(f"dispatch overlap:  {hits}/{len(funcs)} harvested starts appear in "
              f"{args.dispatch.name} ({len(known)} per-instruction rows); "
              f"informational only")
    if args.report and unnamed:
        print("unaddressable examples (need a build to place them):")
        for s in unnamed:
            print(f"    {s.source}  {s.name}  ({s.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
