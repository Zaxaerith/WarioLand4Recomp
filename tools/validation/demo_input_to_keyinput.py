#!/usr/bin/env python3
"""Convert the guest's attract-demo input stream into a gbarecomp keyinput file.

`tools/validation/demo_input_dump.py` reads the game's own recorded input out of
an IWRAM snapshot (gDemoInputs / gDemoInputLengths).  That stream is a real
traversal of the level: RIGHT walks, B+RIGHT dashes, A jumps, DOWN/LTR door and
pipe attempts, R rolls.  Feeding it back through GBARECOMP_INPUT_REPLAY drives
the *same* level with *host* input, which is what priority G needs (an
input-driven room transition) and what priority F needs (a traversal we can then
edit to reach a transforming enemy).

Two things must line up for the replay to work:
  * the guest frame at which the level finishes loading in OUR route, versus
  * the guest frame at which it finished loading in the demo.

The demo's timeline is anchored on its level-entry write of gCurrentRoom
(value 2 at vblank 8852, see docs/VALIDATION.md 4n) and its input frame 0 is 13
frames later.  Pass --level-load-frame for our own run and the shift is
computed; --shift overrides it for a manual alignment sweep.

GBA KEYINPUT is active LOW, so a demo entry that held `held` becomes
0x03FF ^ held in the file.

Usage:
  demo_input_to_keyinput.py --csv logs/routes/demo-input-stream.csv \
      --level-load-frame 11470 --out tests/input/demo-route.keyinput.txt
"""
import argparse
import csv
from pathlib import Path

DEMO_LEVEL_LOAD_FRAME = 8852   # demo's gCurrentRoom = 2 write, vblank 8852
DEMO_INPUT_LEAD = 13           # demo input frame 0 sits 13 frames after it
START = "0x03FF"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--level-load-frame", type=int, default=None,
                    help="guest frame at which OUR route loads the room "
                         "(the gCurrentRoom = 2 write)")
    ap.add_argument("--shift", type=int, default=None,
                    help="explicit frame offset (overrides --level-load-frame)")
    ap.add_argument("--prefix-file", default=None,
                    help="keyinput file whose lines before frame 12000 seed the "
                         "menu navigation (copied verbatim)")
    ap.add_argument("--tail-frames", type=int, default=600,
                    help="frames of 'nothing held' appended after the stream")
    args = ap.parse_args()

    if args.shift is not None:
        shift = args.shift
    elif args.level_load_frame is not None:
        # demo: level load at 8852, input entry 0 at 8865 (= +13).
        # ours: level load at L, so input entry 0 must land on L + 13.
        shift = args.level_load_frame + DEMO_INPUT_LEAD
    else:
        raise SystemExit("need --shift or --level-load-frame")

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    if not rows:
        raise SystemExit(f"{args.csv} has no data rows")

    lines = ["# gbarecomp-keyinput-v1", "# frame,keyinput_active_low"]
    lines.append("# Attract-demo input stream replayed as HOST input.")
    lines.append(f"# source : {args.csv} (dumped from gDemoInputs/gDemoInputLengths)")
    lines.append(f"# shift  : +{shift} frames "
                 f"(our level load '{args.level_load_frame}' vs demo '{DEMO_LEVEL_LOAD_FRAME}')")
    lines.append("# The demo's own presses, converted to active-low "
                 "(0x03FF ^ held):")
    for row in rows[:24]:
        lines.append(f"#   [{int(row['index']):3d}] {row['buttons']:<14} "
                     f"{int(row['length']):5d} frames")
    lines.append("#   ...")
    lines.append(f"# demo entries: {len(rows)}, "
                 f"total {sum(int(r['length']) for r in rows)} frames")

    emitted = []
    if args.prefix_file:
        for raw in Path(args.prefix_file).read_text(encoding="utf-8").splitlines():
            if raw.startswith("#") or not raw.strip():
                continue
            frame_s, value = raw.split(",")[0], raw.split(",")[1]
            if int(frame_s) < 12000:
                emitted.append((int(frame_s), value.strip()))
    for row in rows:
        held = int(row["held_active_high"])
        low = 0x03FF ^ held
        start = int(row["start_frame"]) + shift
        # close the previous hold at the start of this one
        emitted.append((start, f"0x{low:04X}"))

    last_end = int(rows[-1]["end_frame"]) + shift
    emitted.append((last_end, START))
    emitted.append((last_end + args.tail_frames, START))

    # de-duplicate consecutive identical values, keep the first frame
    clean = []
    for frame, value in sorted(emitted, key=lambda t: t[0]):
        if clean and clean[-1][1] == value:
            continue
        clean.append((frame, value))

    for frame, value in clean:
        lines.append(f"{frame},{value}")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(clean)} input lines, "
          f"{clean[0][0]}..{clean[-1][0]} frames (shift +{shift})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
