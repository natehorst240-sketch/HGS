"""DAU download protocol for the HGS Download Stick (MicroPython port).

FULLY REVERSE-ENGINEERED from a live A109 capture (see reverse/PROTOCOL.md).
No guesswork remains — this matches what HGS actually does on the wire. Ported
from the validated CircuitPython version; the ONLY change is time handling:
MicroPython's ticks_ms() is modular, so elapsed time uses ticks_diff(), never
plain subtraction.

Protocol (9600,n,8,1), stop-and-wait, DAU-paced:
  1. downloader -> "DOWNLOAD LOGS" (25-byte space-padded ASCII)
  2. DAU -> one whole record (a .HG record; 92/110/228/503/2817 bytes), then
     pauses waiting for an ack
  3. downloader -> "TRANSMISSION OK" (25-byte space-padded ASCII)
  4. repeat 2-3 until no further record arrives; concatenated records == .HG file

Record boundaries are the idle gap after each record (the DAU won't send the
next record until this one is acked), so we frame by inter-byte idle time.

The uart is an already-configured machine.UART; configure it with a short
timeout (e.g. UART(1, 9600, tx=16, rx=17, timeout=20, rxbuf=4096)) so read()
returns promptly and the idle-gap framing stays responsive.
"""
import time

CMD_DOWNLOAD_LOGS = b"DOWNLOAD LOGS"
CMD_DOWNLOAD_CUMULATIVE = b"DOWNLOAD CUMULATIVE"
CMD_DOWNLOAD_STATUS = b"DOWNLOAD STATUS"
ACK = b"TRANSMISSION OK"

MSG_LEN = 25                 # all control messages are 25 bytes, space-padded
FRAME_IDLE_MS = 60           # gap that marks "record complete, DAU waiting for ack"
END_TIMEOUT_MS = 4000        # no new record this long after an ack => (maybe) done
REQUEST_TIMEOUT_MS = 5000    # wait for the first record before resending request
REQUEST_RETRIES = 6          # ~30 s of retries, like HGS's ~5 s retransmit loop


def pad25(msg):
    """Space-pad an ASCII command/ack to the 25-byte wire size."""
    return (msg + b" " * MSG_LEN)[:MSG_LEN]


class DauDownloader:
    """Drives one download over an already-configured machine.UART.
    `on_status(text)` is called with progress strings for the display."""

    def __init__(self, uart, clock_ms=None, on_status=None, on_progress=None,
                 abort_check=None, first_record_ok=None):
        # clock_ms: callable returning a millisecond tick count; defaults to
        # time.ticks_ms. Injectable so the state machine stays testable.
        # on_progress(records, total_bytes): called after each record, for the
        # UI progress bar / rate / ETA.
        # abort_check(): optional callable polled during reads; return True to
        # stop the download (e.g. the user holding the screen).
        self.uart = uart
        self.now = clock_ms or time.ticks_ms
        self._diff = time.ticks_diff            # wrap-safe elapsed time
        self.on_status = on_status or (lambda s: None)
        self.on_progress = on_progress or (lambda r, b: None)
        self.abort_check = abort_check or (lambda: False)
        # first_record_ok(rec) -> bool: reject a transfer whose first record
        # isn't valid HGS data (e.g. line noise on a floating/disconnected RX).
        self.first_record_ok = first_record_ok or (lambda r: True)
        self._abort = False

    def abort(self):
        self._abort = True

    def _aborting(self):
        if not self._abort and self.abort_check():
            self._abort = True
        return self._abort

    def _send(self, msg):
        self.uart.write(pad25(msg))

    def _read_record(self, first_timeout_ms):
        """Read one record: bytes until the line is idle FRAME_IDLE_MS.
        Returns the record bytes, or b'' if nothing arrived within
        first_timeout_ms (used to detect end-of-transfer)."""
        buf = bytearray()
        # wait for the first byte of the record (or give up -> end of transfer)
        start = self.now()
        while not buf:
            if self._aborting():
                return b""
            chunk = self.uart.read(256)
            if chunk:
                buf += chunk
                break
            if self._diff(self.now(), start) > first_timeout_ms:
                return b""
        # accumulate until the line goes idle (record complete)
        last = self.now()
        while self._diff(self.now(), last) < FRAME_IDLE_MS:
            if self._aborting():
                break
            chunk = self.uart.read(256)
            if chunk:
                buf += chunk
                last = self.now()
        return bytes(buf)

    def download(self, out_file, command=CMD_DOWNLOAD_LOGS):
        """Run the full download, appending each record to out_file.
        Returns total bytes written, or None on abort."""
        self._abort = False
        self.on_status("DOWNLOADER TO START")

        # Send the request and wait for the first record, retransmitting the
        # request (like HGS does ~every 5 s) if the DAU is slow or misses it.
        rec = b""
        for attempt in range(REQUEST_RETRIES):
            if self._abort:
                break
            self._send(command)
            self.on_status("REQUEST FRAME MSG SENT" if attempt == 0
                           else "RETRYING REQUEST (%d)" % (attempt + 1))
            rec = self._read_record(REQUEST_TIMEOUT_MS)
            if rec:
                break

        # Guard against a floating/disconnected RX line reading noise as a
        # "record": if the first record doesn't look like HGS data, bail before
        # writing anything to flash.
        if rec and not self.first_record_ok(rec):
            self.on_status("NO VALID DATA (line noise?)")
            return 0

        total = 0
        records = 0
        while not self._abort and rec:
            out_file.write(rec)
            total += len(rec)
            records += 1
            self._send(ACK)                # "TRANSMISSION OK"
            self.on_status("FRAME %d OK" % records)
            self.on_progress(records, total)
            rec = self._read_record(END_TIMEOUT_MS)
            if not rec and not self._abort:
                # Silence could mean the transfer is done, OR the DAU missed our
                # ack and is still waiting. Nudge once with the ack before ending.
                self._send(ACK)
                rec = self._read_record(END_TIMEOUT_MS)

        if self._abort:
            self.on_status("COMPLETED WITH ABORT")
            return None
        if records == 0:
            self.on_status("NO RESPONSE FROM DAU")
            return 0
        self.on_status("COMPLETED WITH SUCCESS  %d records" % records)
        return total
