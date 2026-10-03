#!/usr/bin/env python3
"""Print named IWRAM fields out of a snapshot, and follow pointers into the ROM.

Companion to `tools/validation/observe_read.py` (which captures the snapshots)
and `tools/validation/parse_linker_map.py` (which produced symbols/iwram_map.tsv
from the decomp's linker script).

Two things this does that a raw hexdump does not:
  * it names every field, so a screenshot is never the source of truth (see
    docs/VALIDATION.md rule 18);
  * for every word that looks like a ROM pointer it also resolves the pointer
    target against symbols/imported_data_symbols.tsv (produced by the no-WSL
    harvest + the framework importer), so a pointer can be read as
    "<sRoom2NormalSpriteData + 0x40>" instead of "0x0846A2C0".

Usage:
  iwram_fields.py SNAPSHOT.bin --filter 'gWarioData|gCurrentRoom|RoomHeader'
  iwram_fields.py SNAPSHOT.bin --filter RoomHeader --follow --rom 'Wario Land 4.gba'
  iwram_fields.py SNAPSHOT.bin --filter RoomHeader --follow --bytes 64
"""
import argparse
import re
import struct
import sys
from pathlib import Path

IWRAM_BASE = 0x03000000
DEFAULT_MAP = Path("symbols/iwram_map.tsv")
DEFAULT_DATA_SYMS = Path("symbols/imported_data_symbols.tsv")
ROM_BASE = 0x08000000


def load_map(path: Path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            addr = int(parts[0], 16)
            name = parts[1]
            size = int(parts[2], 0) if len(parts) > 2 and parts[2] else 0
            rows.append((addr, name, size))
    rows.sort()
    return rows


def load_data_syms(path: Path):
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            try:
                addr = int(parts[0], 16)
                size = int(parts[2], 0)
            except ValueError:
                continue
            rows.append((addr, parts[1], size, parts[3]))
    rows.sort()
    return rows


def name_for(addr: int, table) -> str:
    best = None
    for base, region, size, name in table:
        if base <= addr and (size == 0 or addr < base + size):
            if best is None or base > best[0]:
                best = (base, name, addr - base)
    if best is None:
        return ""
    base, name, delta = best
    return name if delta == 0 else f"{name}+0x{delta:X}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--data-symbols", default=str(DEFAULT_DATA_SYMS))
    ap.add_argument("--filter", default=".")
    ap.add_argument("--follow", action="store_true",
                    help="for ROM-pointer-looking words, dump the target")
    ap.add_argument("--rom")
    ap.add_argument("--bytes", type=int, default=32,
                    help="bytes to dump per followed pointer")
    ap.add_argument("--all", action="store_true",
                    help="print every symbol, not just non-zero ones")
    args = ap.parse_args()

    blob = Path(args.snapshot).read_bytes()
    if len(blob) < 32768:
        print(f"error: {args.snapshot} is {len(blob)} bytes, expected >= 32768", file=sys.stderr)
        return 2
    rom = Path(args.rom).read_bytes() if args.rom else None

    fields = load_map(Path(args.map))
    data_syms = load_data_syms(Path(args.data_symbols))
    rx = re.compile(args.filter)

    printed = 0
    for addr, name, size in fields:
        if not rx.search(name):
            continue
        off = addr - IWRAM_BASE
        if off < 0 or off >= len(blob):
            continue
        span = max(size, 1)
        raw = blob[off:off + span]
        if not args.all and not any(raw):
            continue
        u8 = raw[0]
        u16 = struct.unpack_from("<H", raw, 0)[0] if len(raw) >= 2 else None
        u32 = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else None
        extra = f" u16={u16}" if u16 is not None else ""
        print(f"0x{addr:08X} {name} (0x{size:X}) u8={u8}{extra} "
              f"u32={u32 if u32 is not None else '-'} raw={raw.hex()}")
        printed += 1
        if not args.follow:
            continue
        for delta in range(0, len(raw) - 3, 2):
            word = struct.unpack_from("<I", raw, delta)[0]
            r32 = struct.unpack_from("<I", raw, delta)[0]
            if not (ROM_BASE <= r32 < ROM_BASE + 0x800000):
                continue
            target = r32 - ROM_BASE
            label = name_for(r32, data_syms)
            print(f"    +0x{delta:02X} -> 0x{r32:08X} {label}")
            if rom is not None and target + args.bytes <= len(rom):
                chunk = rom[target:target + args.bytes]
                hexs = chunk.hex()
                for i in range(0, len(hexs), 32):
                    print(f"        {i:3d}: {hexs[i:i+32]}")
                words = [struct.unpack_from("<I", chunk, i)[0] for i in range(0, len(chunk) - 3, 4)]
                named = [f"0x{w:08X}{'=' + name_for(w, data_syms) if name_for(w, data_syms) else ''}"
                         for w in words]
                print(f"        u32: {' '.join(named)}")
    print(f"({printed} field(s) printed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
