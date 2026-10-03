#!/usr/bin/env python3
"""Find guest variables in a series of memory snapshots.

Companion to tools/validation/tcp-snapshot.ps1, which dumps a guest memory space
(IWRAM / EWRAM / VRAM / OAM+PAL) at a list of frames from one --tcp run. A screen
only tells you *that* something changed; this tells you *which byte* changed, so a
health counter or a coin counter can be located without guessing from pixels.

Three questions, three tables:

  1. How many offsets change at all, and how often?  (sanity: IWRAM's stack area
     changes in every snapshot, game globals change rarely.)
  2. Which 16-bit words look like a rising counter (the coin counter, whose HUD
     values on the attract demo are 000050 -> 000990 -> 001320 -> 003150, then a
     new level restarting at 000660)?
  3. Which bytes change rarely (2..N distinct values)?  A health byte that goes
     4 -> 3 -> 4 would sit here; this is the priority-F instrument.

Usage
    python tools/validation/snapshot-diff.py --dir logs/routes/snap-demo-iwram
    python tools/validation/snapshot-diff.py --dir logs/routes/snap-demo-iwram \
        --rare-max 8 --top 40 --json logs/routes/snap-demo-iwram/diff.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

FRAME_RE = re.compile(r"f(\d+)\.bin$")


def load(dirpath: str):
    files = sorted(glob.glob(os.path.join(dirpath, "*.bin")), key=lambda p: int(FRAME_RE.search(p).group(1)))
    if not files:
        sys.exit(f"no *.bin snapshots in {dirpath} (run tcp-snapshot.ps1 first)")
    frames, blobs = [], []
    for path in files:
        frames.append(int(FRAME_RE.search(path).group(1)))
        with open(path, "rb") as fh:
            blobs.append(fh.read())
    size = len(blobs[0])
    for path, blob in zip(files, blobs):
        if len(blob) != size:
            sys.exit(f"{path}: {len(blob)} bytes, expected {size} — mixed spaces?")
    return frames, blobs, size


def fmt_series(values, frames, every: int = 1):
    """Render a value series next to its frames, compactly."""
    if every > 1:
        idx = list(range(0, len(values), every))
        if idx[-1] != len(values) - 1:
            idx.append(len(values) - 1)
    else:
        idx = list(range(len(values)))
    return " ".join(f"{frames[i]}:{values[i]}" for i in idx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="snapshot directory produced by tcp-snapshot.ps1")
    ap.add_argument("--rare-max", type=int, default=8, help="max distinct values to call a byte 'rare'")
    ap.add_argument("--rare-min", type=int, default=2, help="min distinct values to call a byte 'rare'")
    ap.add_argument("--top", type=int, default=25, help="rows per table")
    ap.add_argument("--json", help="write the full analysis here")
    ap.add_argument("--series-every", type=int, default=1, help="print only every Nth value of a series")
    ap.add_argument("--small-max", type=int, default=0,
                    help="also list every changing offset whose values never exceed this "
                         "(health meters, heart counts, flags)")
    args = ap.parse_args()

    frames, blobs, size = load(args.dir)
    n = len(blobs)
    print(f"snapshots  : {n}  frames {frames[0]}..{frames[-1]}")
    print(f"space size : {size} bytes ({size/1024:.1f} KiB)")
    print()

    # ---- 1. distinct-value histogram -----------------------------------------
    hist = {1: 0, 2: 0}
    rare, counter16, const_small = [], [], []
    for off in range(size):
        series = [blob[off] for blob in blobs]
        distinct = len(set(series))
        if distinct == 1:
            hist[1] += 1
            if 1 <= series[0] <= 8:
                const_small.append((off, series[0]))
        elif distinct == 2:
            hist[2] += 1
        else:
            hist[distinct] = hist.get(distinct, 0) + 1
        if args.rare_min <= distinct <= args.rare_max:
            rare.append((off, distinct, series))

    changing = size - hist[1]
    print("distinct values per offset")
    print(f"  constant            : {hist[1]:6d}   ({100.0*hist[1]/size:5.1f} %)")
    bucket = sorted(k for k in hist if k >= 2 and k <= 4)
    for k in bucket:
        print(f"  exactly {k} values     : {hist[k]:6d}   ({100.0*hist[k]/size:5.1f} %)")
    more = sum(v for k, v in hist.items() if k >= 5)
    print(f"  5 or more values    : {more:6d}   ({100.0*more/size:5.1f} %)")
    print(f"  -> {changing} of {size} offsets change at all")
    print()

    # ---- 2. 16-bit rising-counter candidates --------------------------------
    for off in range(0, size - 1, 2):
        series = [blob[off] | (blob[off + 1] << 8) for blob in blobs]
        distinct = len(set(series))
        if distinct < 3:
            continue
        if max(series) > 9999 or max(series) == 0:
            continue
        rises = sum(1 for a, b in zip(series, series[1:]) if b >= a)
        frac = rises / max(1, len(series) - 1)
        peak = max(series)
        peak_at = series.index(peak)
        drop_after_peak = peak_at < len(series) - 1 and min(series[peak_at:]) < 0.5 * peak
        score = (1 if frac >= 0.7 else 0) + (1 if drop_after_peak else 0) + (1 if peak > 100 else 0)
        if frac >= 0.6 and peak >= 10:
            counter16.append((score, off, distinct, peak, frac, drop_after_peak, series))
    counter16.sort(key=lambda r: (-r[0], -r[3]))
    print(f"16-bit rising-counter candidates (top {args.top})")
    if not counter16:
        print("  none")
    for score, off, distinct, peak, frac, drop, series in counter16[: args.top]:
        print(f"  0x{off:06X}  distinct={distinct:3d} peak={peak:6d} rising={frac*100:5.1f} %"
              f"{'  DROPS after peak (level change?)' if drop else ''}")
        print(f"      {fmt_series(series, frames, args.series_every)}")
    print()

    # ---- 3. rare byte changes (the health instrument) ------------------------
    rare.sort(key=lambda r: (r[1], -abs(r[2][-1] - r[2][0])))
    print(f"rarely-changing bytes ({args.rare_min}..{args.rare_max} distinct values, top {args.top})")
    print("  offset    distinct  series (frame:value)")
    for off, distinct, series in rare[: args.top]:
        if len(series) > 12 and args.series_every == 1:
            # show the transitions only: what changed and when
            parts = [f"{frames[0]}:{series[0]}"]
            for i in range(1, len(series)):
                if series[i] != series[i - 1]:
                    parts.append(f"{frames[i]}:{series[i]}")
        else:
            parts = fmt_series(series, frames, args.series_every).split()
        print(f"  0x{off:06X}  {distinct:6d}    {' '.join(parts)}")
    if len(rare) > args.top:
        print(f"  ... {len(rare) - args.top} more (raise --top; {len(rare)} rare offsets total)")
    print()

    # ---- 4. constant small values (health candidates that never changed) -----
    print(f"constant bytes with a value in 1..8 : {len(const_small)}")
    if const_small[:8]:
        print("  e.g. " + "  ".join(f"0x{off:06X}={val}" for off, val in const_small[:8]))
    print()

    # ---- 5. small-valued changing offsets (health / heart meter / flags) -----
    small_series = []
    if args.small_max > 0:
        for off in range(size):
            series = [blob[off] for blob in blobs]
            distinct = len(set(series))
            if distinct < 2 or max(series) > args.small_max:
                continue
            small_series.append((off, distinct, max(series), series))
        small_series.sort(key=lambda r: (r[1], r[2]))
        print(f"changing offsets whose values never exceed {args.small_max} "
              f"(health / heart meter / flag candidates, top {args.top})")
        print("  offset    distinct  max   transitions (frame:value)")
        for off, distinct, smax, series in small_series[: args.top]:
            parts = [f"{frames[0]}:{series[0]}"]
            for i in range(1, len(series)):
                if series[i] != series[i - 1]:
                    parts.append(f"{frames[i]}:{series[i]}")
            print(f"  0x{off:06X}  {distinct:6d}  {smax:4d}   {' '.join(parts)}")
        if len(small_series) > args.top:
            print(f"  ... {len(small_series) - args.top} more "
                  f"({len(small_series)} in this class total)")
        print()

    if args.json:
        payload = {
            "dir": args.dir,
            "frames": frames,
            "size": size,
            "histogram": {str(k): v for k, v in sorted(hist.items())},
            "changing_offsets": changing,
            "counter16": [
                {"offset": off, "distinct": d, "peak": peak, "rising_fraction": round(frac, 3),
                 "drops_after_peak": drop, "series": series}
                for _s, off, d, peak, frac, drop, series in counter16[:200]
            ],
            "rare_bytes": [
                {"offset": off, "distinct": d, "series": series} for off, d, series in rare[:500]
            ],
            "constant_small": [{"offset": off, "value": v} for off, v in const_small[:200]],
            "small_series_max": args.small_max,
            "small_series": [
                {"offset": off, "distinct": d, "max": smax, "series": series}
                for off, d, smax, series in small_series
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
