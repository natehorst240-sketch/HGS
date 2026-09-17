"""Analyze an hgs_serial.log produced by hgs_sniff.js.

Splits the byte stream into TX/RX events, then tries to auto-detect the frame
structure: repeated leading/trailing sync bytes, length fields, and which
common checksum (XOR/LRC, sum8, sum16, CRC16 variants) reproduces the last
byte(s) of each frame. Prints a structured report to guide the firmware's
dau_protocol.py. No assumptions are hard-coded — it reports what the data says.

Usage: python decode_capture.py hgs_serial.log
"""
from __future__ import annotations

import re
import sys
from collections import Counter

# Accepts Frida logs (>> / <<) and the hardware sniffer (A / B line labels).
LINE = re.compile(r"\]\s*(>>|<<|A|B)\s+([0-9a-fA-F ]+)\s*$")
# Frida already knows direction; the sniffer doesn't, so its A/B map to the two
# streams and the report tells you which is which by content.
DIR = {">>": 0, "A": 0, "<<": 1, "B": 1}


def parse(path):
    streams = ([], [])
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = LINE.search(ln)
            if not m:
                continue
            tag, hexs = m.group(1), m.group(2)
            data = bytes(int(b, 16) for b in hexs.split())
            streams[DIR[tag]].append(data)
    return streams


# --- checksum candidates ----------------------------------------------------
def xor_lrc(b):
    c = 0
    for x in b:
        c ^= x
    return c & 0xFF


def sum8(b):
    return sum(b) & 0xFF


def twos_sum8(b):
    return (-sum(b)) & 0xFF


def sum16_be(b):
    return sum(b) & 0xFFFF


def crc16_ccitt(b, init=0xFFFF):
    crc = init
    for x in b:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc16_modbus(b):
    crc = 0xFFFF
    for x in b:
        crc ^= x
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


CK8 = (("XOR/LRC", xor_lrc), ("SUM8", sum8), ("2COMP_SUM8", twos_sum8))
CK16 = (("CRC16-CCITT", crc16_ccitt), ("CRC16-MODBUS", crc16_modbus), ("SUM16", sum16_be))


def test_checksums(frame):
    """Names of checksums whose value matches a trailing field of the frame.

    Searches over a leading header of h skipped bytes (0..2, e.g. STX/len) and
    a trailing terminator of t bytes (0..2, e.g. ETX), so it finds a checksum
    embedded as  [header][body][checksum][terminator]  not just the last byte.
    """
    hits = []
    n = len(frame)
    for h in range(0, 3):
        for t in range(0, 3):
            # 1-byte checksum at position n-t-1, body = frame[h : n-t-1]
            pos = n - t - 1
            if pos - h >= 1:
                body, ck = frame[h:pos], frame[pos]
                for name, fn in CK8:
                    if fn(body) == ck:
                        hits.append("%s [hdr%d/trl%d]" % (name, h, t))
            # 2-byte checksum at positions n-t-2 .. n-t-1
            pos2 = n - t - 2
            if pos2 - h >= 1:
                body, tail = frame[h:pos2], frame[pos2:pos2 + 2]
                for name, fn in CK16:
                    v = fn(body)
                    if bytes([v >> 8, v & 0xFF]) == tail:
                        hits.append("%s BE [hdr%d/trl%d]" % (name, h, t))
                    if bytes([v & 0xFF, v >> 8]) == tail:
                        hits.append("%s LE [hdr%d/trl%d]" % (name, h, t))
    return hits


def report(tx, rx):
    print("=" * 60)
    print("TX events (PC->DAU): %d   RX events (DAU->PC): %d" % (len(tx), len(rx)))
    print("=" * 60)

    for label, msgs in (("TX (PC->DAU)", tx), ("RX (DAU->PC)", rx)):
        if not msgs:
            continue
        print("\n### %s ###" % label)
        lens = Counter(len(m) for m in msgs)
        print("  frame-length histogram:", dict(sorted(lens.items())))
        firsts = Counter(m[0] for m in msgs if m)
        lasts = Counter(m[-1] for m in msgs if m)
        print("  first byte:", {hex(k): v for k, v in firsts.most_common(5)})
        print("  last  byte:", {hex(k): v for k, v in lasts.most_common(5)})
        print("  first 4 distinct frames:")
        seen = set()
        for m in msgs:
            key = m[:16]
            if key in seen:
                continue
            seen.add(key)
            print("    " + " ".join("%02x" % b for b in m[:24]) + (" ..." if len(m) > 24 else ""))
            if len(seen) >= 4:
                break

    # checksum detection on the RX frames (the ones HGS validates)
    print("\n### checksum detection (RX frames) ###")
    votes = Counter()
    for m in rx:
        for h in test_checksums(m):
            votes[h] += 1
    if votes:
        for name, n in votes.most_common():
            print("  %-34s matched %d/%d frames" % (name, n, len(rx)))
        print("  -> strongest candidate:", votes.most_common(1)[0][0])
    else:
        print("  no common checksum matched a trailing field — frame may not")
        print("  end in a checksum, or the check is length/structure based.")
    print("\nSend this report (and the raw log) back to finish dau_protocol.py.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    tx, rx = parse(sys.argv[1])
    if not tx and not rx:
        print("No TX/RX lines found. Is this an hgs_sniff.js log?")
        sys.exit(1)
    report(tx, rx)
