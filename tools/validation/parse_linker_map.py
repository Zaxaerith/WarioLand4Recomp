#!/usr/bin/env python3
"""Turn the reference decomp's linker script into a named guest IWRAM map.

Why this exists
---------------
The recompilation runtime only knows guest *code* addresses; it has no names for
the guest's variables. That makes variable-level validation (is the heart meter
decreasing? which room are we in? did the reaction byte change?) impossible
without guessing from pixels — and pixels lie (see docs/KNOWN_ISSUES.md G10 and
VALIDATION.md rule 12/17).

The reference decomp (third_party/lilDavid-warioland4) never has to be *built*
for this: its `linker.ld` pins every IWRAM global to an explicit offset with an
explicit name, e.g.

    . = 0x1910; gHeartMeter = .;
    . = 0x1898; gWarioData = .;

so the file is a complete name -> 0x0300xxxx map. This script extracts it into a
plain TSV that any validation tool (or a human) can read. Nothing here executes
the decomp; it is metadata, which is exactly the role the brief gives it.

Usage
    python tools/validation/parse_linker_map.py \
        --ld third_party/lilDavid-warioland4/linker.ld \
        --out symbols/iwram_map.tsv

The output columns are: address (hex, guest space), name, gap to the next entry
(bytes, blank when unknown). Rows whose name starts with `obj/` are linker
section markers, not symbols; they are kept because they delimit the anonymous
blocks (e.g. `obj/main.o(iwram_data)` fills 0x0C34..0x1850 and has no per-field
names available).
"""
from __future__ import annotations

import argparse
import re
import sys

ASSIGN_RE = re.compile(r"^\s*\.\s*=\s*(0x[0-9A-Fa-f]+)\s*;\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\.\s*;\s*$")
SECTION_RE = re.compile(r"^\s*\.\s*=\s*(0x[0-9A-Fa-f]+)\s*;\s*(obj/\S+)\s*;\s*$")
IWRAM_MARKER = "iwram (NOLOAD)"

# The IWRAM origin as declared in the MEMORY block of the same file.
ORIGIN_RE = re.compile(r"IWRAM\s*\(rwx\)\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+)")


def parse(path: str):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    origin = None
    for line in lines:
        m = ORIGIN_RE.search(line)
        if m:
            origin = int(m.group(1), 16)
            break
    if origin is None:
        sys.exit(f"{path}: no IWRAM ORIGIN in the MEMORY block")

    entries, in_iwram, depth = [], False, 0
    for line in lines:
        if IWRAM_MARKER in line:
            in_iwram, depth = True, 0
            continue
        if not in_iwram:
            continue
        depth += line.count("{") - line.count("}")
        if depth < 0:
            break  # the iwram section closed
        m = ASSIGN_RE.match(line)
        if m:
            entries.append((int(m.group(1), 16), m.group(2)))
            continue
        m = SECTION_RE.match(line)
        if m:
            entries.append((int(m.group(1), 16), m.group(2)))
    if not entries:
        sys.exit(f"{path}: found no `iwram` section entries")

    # Sizes are not in the script; the gap to the next entry is the honest upper
    # bound and is what a reader needs to pick a plausible width.
    out = []
    for i, (off, name) in enumerate(entries):
        gap = entries[i + 1][0] - off if i + 1 < len(entries) else None
        out.append((origin + off, name, gap))
    return origin, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ld", required=True, help="path to the decomp's linker.ld")
    ap.add_argument("--out", required=True, help="TSV to write")
    ap.add_argument("--origin", type=lambda s: int(s, 0), default=None,
                    help="override the IWRAM origin (default: read from the file)")
    args = ap.parse_args()

    origin, entries = parse(args.ld)
    if args.origin is not None:
        delta = args.origin - origin
        origin = args.origin
        entries = [(a + delta, n, g) for a, n, g in entries]

    named = [e for e in entries if not e[1].startswith("obj/")]
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# guest IWRAM map extracted from the reference decomp's linker script\n")
        fh.write(f"# origin {origin:#010x}; source {args.ld}\n")
        fh.write("# address\tname\tgap_to_next\n")
        for addr, name, gap in entries:
            gap_text = "" if gap is None else f"{gap:#x}"
            fh.write(f"{addr:#010x}\t{name}\t{gap_text}\n")

    span = entries[-1][0] - origin
    print(f"{args.ld}: origin {origin:#010x}, {len(entries)} entries "
          f"({len(named)} named, {len(entries) - len(named)} section markers), "
          f"last entry at +{span:#x}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
