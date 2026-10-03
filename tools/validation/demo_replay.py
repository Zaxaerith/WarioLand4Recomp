#!/usr/bin/env python3
"""Turn the game's own recorded demo input table into a host-input replay.

Why this exists
---------------
`src/demo_input.c` in the reference decomp shows the attract demo writing
`gButtonsHeld` and `gButtonsPressed` *directly*, so `-InputRecord` sees a
header-only file: the demo never writes `REG_KEYINPUT 0x04000130`. The only
record of what the demo pressed is the pair of tables it plays back from,
`gDemoInputs` / `gDemoInputLengths`.

The point of replaying them is not to watch the demo again. `DemoInputPlayback`
gives up as soon as `gButtonsHeld != 0` and forces START instead, so a host
replay of the same buttons *suppresses* the demo's own playback and supplies the
same input instead. If the transformation still happens, host input caused it,
and the attract demo is only the source of the button sequence.

`--anchor` is the vblank at which demo stream frame 0 is played. It is a
measurement, not a constant: `gDemoSequenceIndex` and `gDemoButtonPressTimer`
are readable per frame from an observe dump, and each gives an independent
estimate. See logs/routes/obs-f34/ for the sweep that produced ~8840.

Usage
  demo_replay.py --csv logs/routes/demo-input-stream.csv \\
      --anchor 8840 --out tests/input/f35-demo-water.keyinput.txt
  demo_replay.py --flip-right-to-left --in A.txt --out B.txt
  demo_replay.py --self-test
"""

from __future__ import annotations

import argparse
import sys

HEADER = """# gbarecomp-keyinput-v1
# frame,keyinput_active_low
# Attract-demo input stream replayed as HOST input.
# source : {csv}
# anchor : demo stream frame 0 is played at vblank {anchor}
{note}
"""

FULL = 0x3FF  # REG_KEYINPUT: 10 active-low key bits


def load_rows(csv_path):
    """Read the demo table dump. Returns [(index, held, length, start, end), ...]."""
    rows = []
    with open(csv_path, encoding="utf-8") as fh:
        header = fh.readline()
        if not header.startswith("index,"):
            raise ValueError("unexpected CSV header: %r" % header[:60])
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            rows.append(
                (
                    int(parts[0]),
                    int(parts[1], 0),
                    int(parts[4]),
                    int(parts[5]),
                    int(parts[6]),
                )
            )
    if not rows:
        raise ValueError("no rows in %s" % csv_path)
    for prev, cur in zip(rows, rows[1:]):
        if cur[0] != prev[0] + 1:
            raise ValueError("index gap %d -> %d" % (prev[0], cur[0]))
        if cur[3] != prev[4]:
            raise ValueError(
                "row %d starts at %d but row %d ended at %d"
                % (cur[0], cur[3], prev[0], prev[4])
            )
    return rows


def to_keyinput(rows, anchor, flip_direction=False):
    """(frame, active_low) pairs. active_low = FULL & ~held."""
    out = []
    for _idx, held, _length, start, end in rows:
        if flip_direction:
            # One variable: the direction bit. RIGHT (0x10) becomes LEFT (0x20).
            held = (held & ~0x10) | (0x20 if held & 0x10 else 0)
        # The replay is a change list, so only the frame a press begins matters.
        if not out or out[-1][1] != (FULL & ~held):
            out.append((anchor + start, FULL & ~held))
    # Two changes can land on one frame; keep the last one and stay sorted.
    merged = {}
    for frame, value in out:
        merged[frame] = value
    return [(f, merged[f]) for f in sorted(merged)]


def read_keyinput(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            frame, value = line.split(",")
            rows.append((int(frame), int(value, 0)))
    return rows


def write_keyinput(path, rows, note):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HEADER.format(csv=note["csv"], anchor=note["anchor"], note=note["note"]))
        for frame, value in rows:
            fh.write("%d,0x%04X\n" % (frame, value))


def self_test():
    ok = True

    def check(label, got, want):
        nonlocal ok
        if got == want:
            print("  ok   %s (got %r)" % (label, got))
        else:
            ok = False
            print("  FAIL %s: got %r want %r" % (label, got, want))

    import tempfile
    import os

    tmp = tempfile.mkdtemp()
    csv_path = os.path.join(tmp, "s.csv")
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("index,held_active_high,held_hex,buttons,length,start_frame,end_frame\n")
        fh.write("0,0,0x0000,none,24,0,24\n")
        fh.write("1,16,0x0010,RIGHT,78,24,102\n")
        fh.write("2,0,0x0000,none,10,102,112\n")

    # Detection, not the verdict: a table whose rows do not tile must be rejected.
    check("load_rows tiles", len(load_rows(csv_path)), 3)
    try:
        with open(csv_path, "a", encoding="utf-8") as fh:
            fh.write("3,0,0x0000,none,5,999,1004\n")
        load_rows(csv_path)
        check("load_rows rejects a gap", "accepted", "rejected")
    except ValueError:
        check("load_rows rejects a gap", "rejected", "rejected")
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("index,held_active_high,held_hex,buttons,length,start_frame,end_frame\n")
        fh.write("0,0,0x0000,none,24,0,24\n")
        fh.write("1,16,0x0010,RIGHT,78,24,102\n")
        fh.write("2,0,0x0000,none,10,102,112\n")

    rows = load_rows(csv_path)
    # anchor 1000: frame 1000 nothing (0x3FF), frame 1024 RIGHT (0x03EF),
    # frame 1102 back to nothing (0x03FF). The replay is a change list.
    want = [(1000, 0x3FF), (1024, 0x3EF), (1102, 0x3FF)]
    check("anchor applies", to_keyinput(rows, 1000), want)
    # One variable: the direction bit becomes LEFT (0x20) -> 0x3DF.
    want_l = [(1000, 0x3FF), (1024, 0x3DF), (1102, 0x3FF)]
    check("flip direction", to_keyinput(rows, 1000, True), want_l)
    # A run of identical rows collapses to one change.
    same = [(0, 0, 5, 0, 5), (1, 0, 5, 5, 10)]
    check("collapse identical", to_keyinput(same, 0), [(0, 0x3FF)])

    out = os.path.join(tmp, "r.keyinput.txt")
    write_keyinput(out, to_keyinput(rows, 1000), {"csv": csv_path, "anchor": 1000, "note": ""})
    check("round trip", read_keyinput(out), to_keyinput(rows, 1000))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", help="demo input table dump")
    ap.add_argument("--anchor", type=int, help="vblank at which demo stream frame 0 is played")
    ap.add_argument("--out", help="keyinput replay to write")
    ap.add_argument("--in", dest="src", help="existing keyinput replay to transform")
    ap.add_argument(
        "--flip-right-to-left",
        action="store_true",
        help="replace RIGHT with LEFT in every row (the single-variable control)",
    )
    ap.add_argument("--note", default="", help="extra comment line for the header")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.src:
        rows = read_keyinput(args.src)
        out = []
        for frame, value in rows:
            held = FULL & ~value
            held = (held & ~0x10) | (0x20 if held & 0x10 else 0)
            out.append((frame, FULL & ~held))
        write_keyinput(
            args.out, out, {"csv": args.src, "anchor": "-", "note": args.note or "CONTROL: RIGHT replaced by LEFT in every row."}
        )
        print("wrote %s (%d rows)" % (args.out, len(out)))
        return 0

    if not (args.csv and args.anchor is not None and args.out):
        ap.error("--csv, --anchor and --out are required without --self-test")
    rows = load_rows(args.csv)
    out = to_keyinput(rows, args.anchor)
    write_keyinput(args.out, out, {"csv": args.csv, "anchor": args.anchor, "note": args.note})
    print(
        "wrote %s (%d rows, vblank %d..%d)"
        % (args.out, len(out), out[0][0], out[-1][0])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
