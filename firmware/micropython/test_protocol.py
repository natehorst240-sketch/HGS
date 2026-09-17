"""Milestone-3 logic test — runs on the board, no DAU/serial hardware needed.

    python -m mpremote connect COM7 run test_protocol.py

Feeds DauDownloader a FakeUart that plays back records stop-and-wait (one record
per ack, exactly like the DAU), driven by a fake clock, and checks that the
reassembled stream equals the concatenated records. Proves the MicroPython
port's framing + ack loop are intact. (End-to-end over real RS-232 still waits
on the MAX3232 + a DAU or serial peer.)
"""
import io
import dau_protocol as dp


class FakeUart:
    """Stop-and-wait DAU emulator: each write (request or ack) arms exactly one
    record, delivered whole on the next read; then the 'line' goes idle."""

    def __init__(self, records):
        self.records = list(records)
        self.sent = []
        self._armed = False

    def write(self, b):
        self.sent.append(bytes(b))
        self._armed = True

    def read(self, n):
        if self._armed and self.records:
            self._armed = False
            return self.records.pop(0)
        return None


def make_clock(step_ms=100):
    t = [0]

    def clock():
        t[0] += step_ms
        return t[0]

    return clock


def run():
    records = [
        b"R0:" + b"A" * 89,       # 92-byte-ish record
        b"R1:" + b"B" * 107,      # 110
        b"R2:" + b"C" * 225,      # 228
    ]
    expected = b"".join(records)

    uart = FakeUart(records)
    out = io.BytesIO()
    statuses = []
    dl = dp.DauDownloader(uart, clock_ms=make_clock(),
                          on_status=lambda s: statuses.append(s))
    total = dl.download(out, command=dp.CMD_DOWNLOAD_LOGS)

    got = out.getvalue()
    ok = (total == len(expected)) and (got == expected)
    print("records delivered:", 3, "reassembled:", total, "bytes")
    print("first request:", uart.sent[0])
    print("acks sent:", sum(1 for m in uart.sent if m.startswith(dp.ACK)))
    print("final status:", statuses[-1])
    print("byte-for-byte match:", got == expected)
    print("RESULT:", "PASS" if ok else "FAIL")
    return ok


run()
