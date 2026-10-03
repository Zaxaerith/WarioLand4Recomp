#!/usr/bin/env python3
"""Trace named guest state over an input-replay route using the windowed observer port.

The runtime's `--tcp-observe PORT` attaches a read-only debug server to a *windowed*
run, so `GBARECOMP_INPUT_REPLAY` keeps working while memory can still be read
(gbarecomp-main/src/runtime/runtime.cpp:2892-2927; documented as the G13 workaround).

This tool samples IWRAM at a fixed guest-frame cadence and prints one line per
sample with the state that priorities F/G need:

  frame  room  wario(x,y)  pose  reaction  hearts  | sprite slots (id:class:status:x,y)

Usage:
  observe_trace.py --port 19995 --frames 17000 [--every 500] [--timeout 400]
                   [--out logs/routes/pound-trace.txt] [--sprites]

Notes
  * the core must be launched with --window --tcp-observe PORT
  * the port appears ~1 s after launch; --connect-timeout waits for it
  * `--every` is a *guest frame* cadence; polling is done through run_status
"""
import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

IWRAM_BASE = 0x03000000
IWRAM_SIZE = 32768
DEFAULT_MAP = Path("symbols/iwram_map.tsv")

# field offsets (see third_party/lilDavid-warioland4/include/wario.h and sprite.h)
WARIO_REACTION = 0x00
WARIO_POSE = 0x01
WARIO_DAMAGE_TIMER = 0x04
WARIO_X = 0x12
WARIO_Y = 0x14
SPRITE_SLOT_SIZE = 0x2C
SPRITE_STATUS = 0x00
SPRITE_Y = 0x08
SPRITE_X = 0x0A
SPRITE_GLOBAL_ID = 0x17
SPRITE_POSE = 0x1C
SPRITE_HEALTH = 0x1D
SPRITE_WARIO_COLLISION = 0x1E


class Client:
    def __init__(self, port, connect_timeout=60.0):
        deadline = time.time() + connect_timeout
        last = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=10.0)
                self.fh = self.sock.makefile("rwb")
                return
            except OSError as exc:  # not listening yet
                last = exc
                time.sleep(0.25)
        raise SystemExit(f"observer port {port} never opened: {last}")

    def cmd(self, name, **kw):
        payload = {"cmd": name}
        payload.update(kw)
        self.fh.write((json.dumps(payload) + "\n").encode())
        self.fh.flush()
        line = self.fh.readline()
        if not line:
            raise SystemExit("observer closed the connection")
        return json.loads(line.decode())

    def close(self):
        try:
            self.fh.close()
            self.sock.close()
        except OSError:
            pass


def load_map(path: Path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                out[parts[1]] = int(parts[0], 16)
    return out


def u8(blob, addr):
    return blob[addr - IWRAM_BASE]


def u16(blob, addr):
    return struct.unpack_from("<H", blob, addr - IWRAM_BASE)[0]


def u32(blob, addr):
    return struct.unpack_from("<I", blob, addr - IWRAM_BASE)[0]


def sprite_line(blob, base, slots=24):
    parts = []
    for i in range(slots):
        a = base + i * SPRITE_SLOT_SIZE
        status = u16(blob, a + SPRITE_STATUS)
        if status == 0:
            continue
        parts.append(
            f"{i}:{u8(blob, a + SPRITE_GLOBAL_ID):02X}"
            f"/c{u8(blob, a + SPRITE_WARIO_COLLISION):02X}"
            f"/p{u8(blob, a + SPRITE_POSE):02X}"
            f"/h{u8(blob, a + SPRITE_HEALTH):02X}"
            f"@({u16(blob, a + SPRITE_X)},{u16(blob, a + SPRITE_Y)})"
        )
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--frames", type=int, required=True, help="stop after this guest frame")
    ap.add_argument("--every", type=int, default=500)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--connect-timeout", type=float, default=60.0)
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--out")
    ap.add_argument("--sprites", action="store_true", help="also print every live sprite slot")
    ap.add_argument("--continue", dest="resume", action="store_true",
                    help="send `continue` first (the observer port does not park the core)")
    args = ap.parse_args()

    names = load_map(Path(args.map))
    need = ["gCurrentRoom", "gWarioData", "gHeartMeter", "gSpriteData"]
    for n in need:
        if n not in names:
            print(f"error: {n} missing from {args.map}", file=sys.stderr)
            return 2

    c = Client(args.port, args.connect_timeout)
    if args.resume:
        c.cmd("continue")

    out_file = open(args.out, "w", encoding="utf-8") if args.out else None
    header = ("frame\troom\twario_x\twario_y\tpose\treaction\tdamage\tpose_name\thearts"
              "\tsprites")
    lines = [header]
    print(header)

    next_mark = 0
    try:
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            st = c.cmd("run_status")
            if not st.get("ok", False):
                time.sleep(0.05)
                continue
            frame = int(st.get("frame", 0))
            if frame < next_mark:
                time.sleep(0.05)
                continue
            r = c.cmd("read_iwram", addr=f"0x{IWRAM_BASE:08X}", len=IWRAM_SIZE)
            if not r.get("ok", False):
                print(f"read_iwram failed: {r}", file=sys.stderr)
                return 3
            blob = bytes.fromhex(r["data"])
            w = names["gWarioData"]
            room = u8(blob, names["gCurrentRoom"])
            wx, wy = u16(blob, w + WARIO_X), u16(blob, w + WARIO_Y)
            pose = u8(blob, w + WARIO_POSE)
            react = u8(blob, w + WARIO_REACTION)
            dmg = u8(blob, w + WARIO_DAMAGE_TIMER)
            hearts = u8(blob, names["gHeartMeter"])
            sprites = sprite_line(blob, names["gSpriteData"]) if args.sprites else ""
            line = (f"{frame}\t{room}\t{wx}\t{wy}\t{pose}\t{react}\t{dmg}\t-\t{hearts}"
                    f"\t{sprites}")
            print(line)
            lines.append(line)
            if out_file:
                out_file.write(line + "\n")
                out_file.flush()
            next_mark += args.every
            if frame >= args.frames:
                break
    finally:
        c.close()
        if out_file:
            out_file.close()
        print(f"({len(lines) - 1} sample(s))", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
