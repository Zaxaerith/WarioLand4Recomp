#!/usr/bin/env python3
"""Turn a runtime miss proposal into a reviewed game.toml block.

The runtime writes `recomp_master_misses_<CODE>.toml.frag` on exit: one
`[[extra_func]]` proposal per guest PC that was bridged through the interpreter.
The framework's own docstring says a HUMAN reviews it and merges the genuine
entries; this tool is that review step, made repeatable.

What it does NOT do, deliberately:

  * it never merges `[[jump_table]]` proposals (the framework only flags those in
    comments, and a wrong table silently corrupts dispatch),
  * it never merges an address outside the requested prefix — the dynamic
    stack-stub family lives in IWRAM (`0x03xxxxxx`) and declaring those addresses
    is exactly what made eight functions jump to unmapped `0xD00C2A00`,
  * it never invents names or semantics.

Usage:
    python tools/validation/merge_miss_fragment.py --fragment logs/routes/x-misses.toml.frag
    python tools/validation/merge_miss_fragment.py --fragment … --out logs/merge.toml
    python tools/validation/merge_miss_fragment.py --fragment … --keep-prefix 0x08 --note "…"

The emitted block goes to stdout (or --out); the review summary goes to stderr, so
`>> game.toml` is safe.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BLOCK_RE = re.compile(
    r"\[\[extra_func\]\]\s*\n\s*addr\s*=\s*(0x[0-9A-Fa-f]+)\s*\n\s*mode\s*=\s*\"(\w+)\"",
    re.MULTILINE,
)


def parse(path: Path) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for m in BLOCK_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        entries.append((int(m.group(1), 16), m.group(2)))
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fragment", required=True, type=Path)
    ap.add_argument("--keep-prefix", default="0x08",
                    help="only merge addresses starting with this hex prefix (default 0x08 = cartridge ROM)")
    ap.add_argument("--note", default="", help="short evidence line for the header")
    ap.add_argument("--out", type=Path, help="write here instead of stdout")
    ap.add_argument("--no-header", action="store_true")
    args = ap.parse_args()

    if not args.fragment.is_file():
        print(f"fragment not found: {args.fragment}", file=sys.stderr)
        return 2

    entries = parse(args.fragment)
    pref = args.keep_prefix.lower()
    keep = sorted({a for a, _ in entries if f"0x{a:08X}".lower().startswith(pref)})
    modes = {a: m for a, m in entries}
    rejected = sorted({a for a, _ in entries} - set(keep))

    out = []
    if not args.no_header:
        out.append("")
        out.append(f"# ─── reviewed merge of {len(keep)} [[extra_func]] entries "
                   f"from {args.fragment.name} ───")
        out.append(f"# kept: {len(keep)} (prefix {args.keep_prefix})   "
                   f"rejected: {len(rejected)}")
        if args.note:
            out.append(f"# {args.note}")
        out.append("# Address-only on purpose: no semantic names are invented for unreversed code.")
    for a in keep:
        out.append("[[extra_func]]")
        out.append(f"addr = 0x{a:08X}")
        out.append(f'mode = "{modes.get(a, "thumb")}"')
        out.append("")

    text = "\n".join(out).rstrip() + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    print(f"kept {len(keep)}, rejected {len(rejected)}", file=sys.stderr)
    for a in rejected[:40]:
        print(f"  rejected 0x{a:08X} (outside {args.keep_prefix})", file=sys.stderr)
    if len(rejected) > 40:
        print(f"  … and {len(rejected) - 40} more", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
