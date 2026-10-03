#!/usr/bin/env python3
"""Poll Wario + the room's sprite slots over a window of guest frames.

The runtime's `--tcp-observe PORT` (G13b) attaches a read-only debug server to a
*windowed* run, so `GBARECOMP_INPUT_REPLAY` keeps working while IWRAM can be
read.  `observe_trace.py` samples on a fixed cadence; this tool instead walks a
dense frame window, which is what a jump-arc measurement needs.

Usage:
  wario_watch.py --port 20031 --from 11950 --to 12600 --every 10 \
      [--out logs/routes/f51-trace.txt]
"""
import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

IWRAM_BASE = 0x03000000
WARIO = 0x03001898
# symbols/iwram_map.tsv: gSpriteData 0x03000104 (0x420 bytes => 24 slots of 0x2C).
# 0x03001B4C used to be assumed here and is NOT the sprite array -- that region
# holds unrelated IWRAM data, so every slot decode came out as garbage.
SPRITE_SLOTS = 0x03000104
CURRENT_SPRITE = 0x03000A24
SUB_GAME_MODE = 0x03000C3C
STAGE_EXIT_TYPE = 0x03000C3D
SLOT_SIZE = 0x2C
SLOTS = 24

FIELDS = {
    "reaction": 0x00,
    "pose": 0x01,
    "damageTimer": 0x04,
    "xPosition": 0x12,
    "yPosition": 0x14,
    "xVelocity": 0x16,
    "yVelocity": 0x18,
    "hbLeft": 0x32,
    "hbTop": 0x34,
    "hbRight": 0x36,
    "hbBottom": 0x38,
}


class Client:
    def __init__(self, port, connect_timeout=90.0):
        deadline = time.time() + connect_timeout
        last = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=15.0)
                self.fh = self.sock.makefile("rwb")
                return
            except OSError as exc:
                last = exc
                time.sleep(0.2)
        raise SystemExit(f"observer port {port} never opened: {last}")

    def cmd(self, name, **kw):
        payload = {"cmd": name}
        payload.update(kw)
        self.fh.write((json.dumps(payload) + "\n").encode())
        self.fh.flush()
        line = self.fh.readline()
        if not line:
            raise SystemExit(f"observer closed on {name}")
        return json.loads(line)

    def status(self):
        return self.cmd("run_status")

    def iwram(self, addr, length):
        # gbarecomp-main/src/debug/tcp_debug_server.cpp cmd_read_region wants
        # `addr` + `len` (not `length`) and answers {"ok":true,"data":"<hex>"}.
        r = self.cmd("read_iwram", addr=f"0x{addr:08X}", len=length)
        if not r.get("ok"):
            raise SystemExit(f"read_iwram 0x{addr:08X}+{length} failed: {r.get('error')}")
        return bytes.fromhex(r["data"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=20031)
    ap.add_argument("--from", dest="first", type=int, default=11950)
    ap.add_argument("--to", dest="last", type=int, default=12600)
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--sprites", action="store_true", default=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    client = Client(args.port)
    lines = []

    def emit(text):
        lines.append(text)
        print(text, flush=True)

    next_frame = args.first
    deadline = time.time() + 600
    while next_frame <= args.last:
        while time.time() < deadline:
            st = client.status()
            frame = st.get("frame") or st.get("guest_frame") or 0
            if frame >= next_frame:
                break
            if st.get("running") is False:
                break
            time.sleep(0.05)
        else:
            emit(f"# timeout waiting for frame {next_frame}")
            break
        st = client.status()
        frame = st.get("frame") or 0
        w = client.iwram(WARIO, 0x3C)
        vals = {}
        for name, off in FIELDS.items():
            if name in ("reaction", "pose", "damageTimer"):
                vals[name] = w[off]
            else:
                vals[name] = struct.unpack_from("<h", w, off)[0]
        parts = [f"f={frame:6d} x={vals['xPosition']:5d} y={vals['yPosition']:5d}"
                 f" vx={vals['xVelocity']:5d} vy={vals['yVelocity']:5d}"
                 f" pose={vals['pose']:3d} react={vals['reaction']:2d}"
                 f" dmg={vals['damageTimer']:3d}"
                 f" hb=({vals['hbLeft']},{vals['hbTop']},{vals['hbRight']},{vals['hbBottom']})"]
        mode = client.iwram(SUB_GAME_MODE, 2)
        g = client.iwram(0x03000023, 1)
        parts.append(f"room={g[0]} sub={mode[0]} exit={mode[1]}")
        if args.sprites:
            slots = client.iwram(SPRITE_SLOTS, SLOTS * SLOT_SIZE)
            live = []
            for i in range(SLOTS):
                s = slots[i * SLOT_SIZE:(i + 1) * SLOT_SIZE]
                if len(s) < SLOT_SIZE:
                    break
                gid = s[0x17]
                if gid == 0:
                    continue
                sy, sx = struct.unpack_from("<hh", s, 0x08)
                live.append(f"{gid}:p{s[0x1C]}:s{s[0x00]}:wc{s[0x1E]}@{sx},{sy}")
            parts.append("| " + " ".join(live))
        emit(" ".join(parts))
        next_frame += args.every

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
