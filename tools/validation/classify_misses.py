#!/usr/bin/env python3
"""classify_misses.py - review the runtime's miss set against the dispatch table.

Why this exists
    The runtime writes a proposal file (recomp_master_misses_<ID>.toml.frag) that
    lists every guest PC it had to bridge through the interpreter. That file is a
    *proposal*: PRINCIPLES.md says a human reviews it and merges the genuine ones
    ("Never auto-write game.toml"). This tool is the review aid. It answers, for
    each missed PC:

      * what mode the runtime saw it in (arm/thumb),
      * how many times it was bridged in this run,
      * whether the PC is already a dispatch entry (it never should be),
      * the nearest *preceding* dispatch entry and the byte distance - i.e. is the
        miss an interior label of a known function, or a region no generated
        function covers,
      * whether the PC lies inside a declared [[code_copy]] span or a data range.

    Interior labels are the interesting case: the framework supports declaring
    them ([[extra_func]] emits a dispatch entry with a resume offset, and the
    generator rolls interior resume points up as midfn_aliases), but declaring an
    address that is NOT real code is how the 0x03007D18 stack-stub regression
    happened (see docs/KNOWN_ISSUES.md F6/G6), so nothing here writes a config.

Read-only: it never modifies the ROM, the config or the generated sources.
"""

import argparse
import json
import re
import sys

DISPATCH_RE = re.compile(
    r"\{\s*0x([0-9A-Fa-f]+)u\s*,\s*(\d+)u\s*,\s*(\d+)u\s*,\s*(\w+)\s*\}")


def parse_dispatch(path):
    """Return {addr: (mode, resume, symbol)} from a generated dispatch table."""
    entries = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = DISPATCH_RE.search(line)
            if m:
                addr = int(m.group(1), 16)
                entries[addr] = (int(m.group(2)), int(m.group(3)), m.group(4))
    return entries


def parse_spans(config_path):
    """Collect [[code_copy]] runtime spans and [[data_range]] spans from a TOML.

    Deliberately a line scanner, not a TOML parser: the project must keep working
    without a Python TOML dependency, and the spans are simple key/value pairs.
    """
    copies, data = [], []
    section = None
    cur = {}
    with open(config_path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[[") and line.endswith("]]"):
                if section == "code_copy" and cur:
                    copies.append(cur)
                if section == "data_range" and cur:
                    data.append(cur)
                section = line[2:-2]
                cur = {}
                continue
            if "=" not in line:
                continue
            key, val = (p.strip() for p in line.split("=", 1))
            val = val.strip('"')
            try:
                num = int(val, 0)
            except ValueError:
                num = None
            if section == "code_copy":
                cur[key] = num
            elif section == "data_range":
                cur[key] = num
        if section == "code_copy" and cur:
            copies.append(cur)
        if section == "data_range" and cur:
            data.append(cur)
    return copies, data


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coverage", required=True, help="runtime coverage JSON")
    ap.add_argument("--dispatch", default="generated/cart/dispatch_table.cpp")
    ap.add_argument("--config", default="game.toml")
    ap.add_argument("--max-gap", type=lambda s: int(s, 0), default=0x400,
                    help="distance above which a miss is called a new region")
    ap.add_argument("--detail", action="store_true", help="print every PC")
    args = ap.parse_args()

    entries = parse_dispatch(args.dispatch)
    if not entries:
        sys.exit(f"no dispatch entries parsed from {args.dispatch}")
    addrs = sorted(entries)

    with open(args.coverage, "r", encoding="utf-8") as fh:
        cov = json.load(fh)
    misses = cov.get("misses", [])

    copies, data = parse_spans(args.config)

    def span_of(pc, spans, lo_key, hi_key):
        for s in spans:
            lo, hi = s.get(lo_key), s.get(hi_key)
            if lo is None or hi is None:
                continue
            if lo <= pc < hi + (s.get("size") or 0):
                return s
        return None

    import bisect
    rows = []
    for miss in misses:
        pc = int(miss["pc"], 16) if isinstance(miss["pc"], str) else int(miss["pc"])
        i = bisect.bisect_right(addrs, pc) - 1
        prev = addrs[i] if i >= 0 else None
        gap = pc - prev if prev is not None else None
        kind = "unknown"
        if pc in entries:
            kind = "ALREADY-ENTRY"
        elif miss.get("jump_table_candidate"):
            kind = "jt-candidate"
        elif prev is not None and gap is not None and gap <= args.max_gap:
            kind = "interior-label"
        else:
            kind = "new-region"
        if span_of(pc, copies, "runtime_start", "size"):
            kind += "+code-copy"
        if any(d.get("start") is not None and d.get("end") is not None
               and d["start"] <= pc < d["end"] for d in data):
            kind += "+data-range"
        rows.append((pc, miss.get("mode"), miss.get("bridged", 0),
                     prev, gap, kind, entries.get(prev, (None, None, "?"))[2]))

    rows.sort(key=lambda r: r[0])
    print(f"coverage {cov.get('coverage')}  program {cov.get('program')!r} "
          f"code {cov.get('code')!r}")
    print(f"misses {len(rows)}   dispatch entries {len(entries)}   "
          f"code_copies {len(copies)}   data_ranges {len(data)}")
    print()
    print(f"{'pc':>10} {'mode':<5} {'bridged':>7} {'prev entry':>10} {'gap':>6}  kind")
    for pc, mode, bridged, prev, gap, kind, sym in rows:
        if not args.detail and kind == "interior-label":
            continue
        ps = f"0x{prev:08X}" if prev else "-"
        gs = f"0x{gap:X}" if gap is not None else "-"
        print(f"0x{pc:08X} {mode or '?':<5} {bridged:>7} {ps:>10} {gs:>6}  {kind}")

    from collections import Counter
    print()
    for kind, n in Counter(r[5].split("+")[0] for r in rows).most_common():
        print(f"  {kind:<15} {n}")
    interior = [r for r in rows if r[5] == "interior-label"]
    if interior and not args.detail:
        print(f"\n({len(interior)} interior-label misses hidden; --detail to list them)")


if __name__ == "__main__":
    main()
