"""Phase 1: capture what HGS transmits when you click download.

Run HGS and this script on the same desktop, connected by a com0com virtual
serial pair (e.g. HGS uses COM3, this script opens COM4). This script only
listens and logs — it never answers — so HGS will send its request frames,
retry, and eventually fail. That's fine: the goal here is to record the exact
request/handshake bytes HGS puts on the wire (= what the download stick must
send to the DAU).

Usage:
    python capture_requests.py COM4          # or whatever the paired port is
    python capture_requests.py COM4 19200    # if you changed the baud

Output: prints each burst as "A  <hex>" (decode_capture.py-compatible) and
writes hgs_requests.log. Ctrl+C to stop.
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
IDLE_FLUSH = 0.05  # group bytes that arrive within 50 ms into one frame


def main():
    ser = serial.Serial(PORT, BAUD, timeout=0.01)
    t0 = time.monotonic()
    log = open("hgs_requests.log", "w")
    print(f"listening on {PORT} @ {BAUD} 8N1 — now click Download in HGS "
          f"(Ctrl+C to stop)")
    buf = bytearray()
    last = time.monotonic()
    total = 0
    try:
        while True:
            data = ser.read(256)
            now = time.monotonic()
            if data:
                buf += data
                last = now
                total += len(data)
            elif buf and now - last > IDLE_FLUSH:
                ms = int((now - t0) * 1000)
                line = "[%8d ms] A  %s" % (ms, " ".join("%02x" % b for b in buf))
                print(line)
                log.write(line + "\n")
                log.flush()
                buf = bytearray()
    except KeyboardInterrupt:
        if buf:
            ms = int((time.monotonic() - t0) * 1000)
            log.write("[%8d ms] A  %s\n" % (ms, " ".join("%02x" % b for b in buf)))
        log.close()
        ser.close()
        print(f"\nstopped. {total} bytes captured -> hgs_requests.log")


if __name__ == "__main__":
    main()
