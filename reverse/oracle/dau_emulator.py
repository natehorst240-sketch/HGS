"""Phase 2: emulate the DAU so HGS grades our guessed response framing.

HGS is the oracle: for each request it sends, we reply with a candidate
response frame built from the KNOWN payload (decoded from a real .HG6). If our
framing/checksum is right, HGS shows "FRAME CHECKED OK" and asks for the next
frame; if wrong, it shows "RETRANSMIT" and repeats the same request. We sweep
FRAMINGS until HGS advances.

This is a skeleton: the request-parsing (`parse_request`) and the exact framing
candidates get filled in from Phase 1's hgs_requests.log. Run it against the
COM4 half of the com0com pair once Phase 1 shows the request shape.

    python dau_emulator.py COM4
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 9600


# --- checksums we can wrap payloads with -----------------------------------
def xor_lrc(b):
    c = 0
    for x in b:
        c ^= x
    return bytes([c & 0xFF])


def sum8(b):
    return bytes([sum(b) & 0xFF])


def crc16_modbus_le(b):
    crc = 0xFFFF
    for x in b:
        crc ^= x
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    crc &= 0xFFFF
    return bytes([crc & 0xFF, crc >> 8])


def crc16_ccitt_be(b, crc=0xFFFF):
    for x in b:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return bytes([crc >> 8, crc & 0xFF])


# Framing candidates to try. Each builds a full response frame around a payload
# chunk and its frame index. Filled/reordered once Phase 1 reveals the shape.
def framing_stx_len_ck_etx(idx, payload, cksum):
    body = bytes([0x02, len(payload) & 0xFF]) + payload
    return body + cksum(body) + bytes([0x03])


def framing_stx_payload_ck_etx(idx, payload, cksum):
    body = bytes([0x02]) + payload
    return body + cksum(body) + bytes([0x03])


FRAMINGS = [
    ("STX,LEN,payload,CRC16MODBUS,ETX", framing_stx_len_ck_etx, crc16_modbus_le),
    ("STX,LEN,payload,XOR,ETX", framing_stx_len_ck_etx, xor_lrc),
    ("STX,LEN,payload,SUM8,ETX", framing_stx_len_ck_etx, sum8),
    ("STX,payload,CRC16CCITT,ETX", framing_stx_payload_ck_etx, crc16_ccitt_be),
]


def parse_request(buf):
    """Return (frame_index, is_request) from an HGS request burst.
    TODO(phase1): implement from the observed request format. For now, treat
    any non-empty burst as 'HGS wants the next frame'."""
    return None, len(buf) > 0


def load_payload_chunks():
    """The data HGS expects, split into per-frame chunks. Wire this to the real
    .HG6 once we know HGS's frame/record size from Phase 1. Placeholder yields
    small chunks so the handshake can be exercised."""
    try:
        with open("../../sample-data/22366_260707_A1.HG6", "rb") as fh:
            data = fh.read()
    except OSError:
        data = bytes(range(256)) * 4
    CHUNK = 128  # TODO(phase1): real per-frame size
    return [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]


def main():
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    chunks = load_payload_chunks()
    print(f"DAU emulator on {PORT} @ {BAUD}. {len(chunks)} payload chunks ready.")
    print("Trying framing:", FRAMINGS[0][0], "(edit FRAMINGS to sweep)")
    name, build, cksum = FRAMINGS[0]

    idx = 0
    buf = bytearray()
    last = time.monotonic()
    while True:
        data = ser.read(256)
        now = time.monotonic()
        if data:
            buf += data
            last = now
            continue
        if buf and now - last > 0.05:
            print("HGS ->", " ".join("%02x" % b for b in buf))
            _, wants = parse_request(bytes(buf))
            buf = bytearray()
            if wants and idx < len(chunks):
                frame = build(idx, chunks[idx], cksum)
                ser.write(frame)
                print(f"  <- sent frame {idx} ({name}): "
                      + " ".join("%02x" % b for b in frame[:16])
                      + (" ..." if len(frame) > 16 else ""))
                idx += 1
        time.sleep(0.005)


if __name__ == "__main__":
    main()
