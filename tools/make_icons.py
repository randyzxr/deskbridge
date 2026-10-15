"""Render the small geometric DeskBridge application icon using stdlib only."""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parent.parent


def pixels(size):
    result = []
    for y in range(size):
        row = []
        for x in range(size):
            a, b = x * 32 / size, y * 32 / size
            # Two monitors linked by a shared bridge.
            ink = (4 <= a < 14 and 8 <= b < 21 or 18 <= a < 28 and 8 <= b < 21)
            inner = (6 <= a < 12 and 10 <= b < 18 or 20 <= a < 26 and 10 <= b < 18)
            bridge = 13 <= a < 19 and 13 <= b < 16
            feet = 7 <= a < 11 and 21 <= b < 24 or 21 <= a < 25 and 21 <= b < 24
            row.append((79, 224, 187, 255) if (ink and not inner or bridge or feet) else (11, 18, 32, 255))
        result.append(row)
    return result


def png(size):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    raw = b"".join(b"\0" + bytes(channel for pixel in row for channel in pixel) for row in pixels(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "deskbridge.png").write_bytes(png(256))
    entries, content, offset = [], [], 6 + 16 * 4
    for size in (16, 32, 48, 256):
        data = png(size)
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        content.append(data)
        offset += len(data)
    (assets / "deskbridge.ico").write_bytes(struct.pack("<HHH", 0, 1, 4) + b"".join(entries + content))
    chunks = []
    for tag, size in ((b"ic08", 256), (b"ic09", 512)):
        data = png(size)
        chunks.append(tag + struct.pack(">I", len(data) + 8) + data)
    data = b"".join(chunks)
    (assets / "deskbridge.icns").write_bytes(b"icns" + struct.pack(">I", len(data) + 8) + data)


if __name__ == "__main__":
    main()
