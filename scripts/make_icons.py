#!/usr/bin/env python3
"""Write the app icons (icon-192.png, icon-512.png, icon-maskable-512.png).

Pure standard library (zlib + struct). Run once; the PNGs are committed.
"""
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def png(path, size, pad):
    bg, sun, cloud = (23, 105, 170), (240, 163, 10), (255, 255, 255)
    s = size
    cx, cy = s * 0.5, s * 0.5
    r = s * (0.5 - pad)
    rows = []
    for y in range(s):
        row = bytearray([0])
        for x in range(s):
            px = bg
            # sun
            if (x - s * .62) ** 2 + (y - s * .38) ** 2 <= (s * .15) ** 2:
                px = sun
            # cloud: three circles + base
            for ccx, ccy, cr in ((.36, .60, .13), (.50, .52, .17), (.66, .62, .12)):
                if (x - s * ccx) ** 2 + (y - s * ccy) ** 2 <= (s * cr) ** 2:
                    px = cloud
            if s * .27 <= x <= s * .77 and s * .60 <= y <= s * .73:
                px = cloud
            row += bytes(px)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", s, s, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(os.path.join(ROOT, path), "wb") as fh:
        fh.write(data)


if __name__ == "__main__":
    png("icon-192.png", 192, 0.0)
    png("icon-512.png", 512, 0.0)
    png("icon-maskable-512.png", 512, 0.1)
