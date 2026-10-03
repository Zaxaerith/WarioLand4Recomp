#!/usr/bin/env python3
"""Dump the loaded room header + background geometry from a live observer session.

Why: room 0's exit records say the only in-room door into room 2 is the cell
(x=31, y=12) box, and the attract demo does reach it while a scripted player
route spawns on a diffent floor.  Deciding whether that is a game fact or a
geometry bug needs the *runtime* room header (width/height in pixels, layer
pointers), not the ROM copy the offline dumper uses.

Usage:
  room_probe.py --port 20032 --at 9201 [--out logs/routes/room-probe.txt]
"""
import argparse
import json
import socket
import struct
import sys
import time

ROOM_HEADER = 0x03000074      # symbols/iwram_map.tsv gCurrentRoomHeader (0x2C)
BACKGROUND_INFO = 0x03000054  # gBackgroundInfo (0x20)
ROOM_INDEX = 0x03000023       # gUnk_3000023
CURRENT_ROOM = 0x03000024     # gCurrentRoom
WARIO = 0x03001898


class Client:
    def __init__(self, port, connect_timeout=120.0):
        deadline = time.time() + connect_timeout
        last = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=20.0)
                self.sock.settimeout(20.0)
                self.buf = b""
                self.ident = 0
                return
            except OSError as exc:
                last = exc
                time.sleep(0.2)
        raise SystemExit(f"observer port {port} never opened: {last}")

    def send(self, cmd, **fields):
        self.ident += 1
        payload = {"id": self.ident, "cmd": cmd}
        payload.update(fields)
        self.sock.sendall((json.dumps(payload) + "\n").encode())
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise SystemExit("server closed the connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    def read(self, addr, length):
        r = self.send("read_iwram", addr=f"0x{addr:08X}", len=length)
        if not r.get("ok"):
            raise SystemExit(f"read 0x{addr:08X}+{length} failed: {r.get('error')}")
        return bytes.fromhex(r["data"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--at", type=int, default=0, help="wait for this guest frame first")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    c = Client(args.port)
    while True:
        st = c.send("run_status")
        frame = int(st.get("frame", -1))
        if frame >= args.at:
            break
        if st.get("run") not in (None, "windowed") and frame < 0:
            break
        time.sleep(0.05)
    print(f"frame={frame} run={st.get('run')}")

    idx = c.read(ROOM_INDEX, 1)[0]
    room = c.read(CURRENT_ROOM, 1)[0]
    hdr = c.read(ROOM_HEADER, 0x2C)
    bg = c.read(BACKGROUND_INFO, 0x20)
    w = c.read(WARIO, 0x3C)

    def u16(b, o):
        return struct.unpack_from("<H", b, o)[0]

    print(f"gUnk_3000023 (stage/level index) = {idx}   gCurrentRoom = {room}")
    print("gCurrentRoomHeader @0x03000074:")
    for i in range(0, 0x2C, 4):
        print(f"  +0x{i:02X} = {hdr[i:i+4].hex(' ')}  u32=0x{struct.unpack_from('<I', hdr, i)[0]:08X}")
    print("gBackgroundInfo @0x03000054:")
    for i in range(0, 0x20, 4):
        print(f"  +0x{i:02X} = {bg[i:i+4].hex(' ')}  u32=0x{struct.unpack_from('<I', bg, i)[0]:08X}")
    print(f"  width(cells)={u16(bg,12)} height(cells)={u16(bg,14)}"
          f" -> {u16(bg,12)*64}x{u16(bg,14)*64} px")
    print(f"wario x={struct.unpack_from('<h', w, 0x12)[0]} y={struct.unpack_from('<h', w, 0x14)[0]}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(hdr.hex() + "\n" + bg.hex() + "\n")
        print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
