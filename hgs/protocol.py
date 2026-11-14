"""DAU serial download/upload state machine (skeleton).

This mirrors the *shape* of the protocol visible in the original binary's
status strings:

    DOWNLOADER TO START
    REQUEST FRAME MSG SENT
    FRAME BYTES RECEIVED
    FRAME CHECKED OK
    RETRANSMIT
    WAIT FOR FRAME COMPLETION
    RETRYING DOWNLOADER TO START
    COMPLETED WITH SUCCESS / COMPLETED WITH ABORT

The exact on-wire bytes (frame delimiters, length fields, checksum algorithm,
ACK/NAK codes) are NOT in any accompanying file — they must be recovered from a
serial capture or by disassembling Hgs_cpp.exe. Everything the wire format
touches is marked TODO(protocol).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import serial  # pyserial
except ImportError:  # allow the GUI to run without a serial device present
    serial = None


class State(enum.Enum):
    IDLE = "STAND BY READY"
    START = "DOWNLOADER TO START"
    REQUEST_SENT = "REQUEST FRAME MSG SENT"
    RECEIVING = "FRAME BYTES RECEIVED"
    FRAME_OK = "FRAME CHECKED OK"
    RETRANSMIT = "RETRANSMIT"
    RETRYING = "RETRYING DOWNLOADER TO START"
    # Exact strings from Hgs_cpp.exe (the stick firmware shows the same ones).
    DONE_OK = "COMPLETED WITH SUCCESS"
    DONE_ABORT = "COMPLETED WITH ABORT"
    FAILED = "DOWNLOAD FAILED"   # not an exe string; HGS has no failure text of its own


@dataclass
class SerialParams:
    port: str
    baud: int = 9600
    parity: str = "N"
    bytesize: int = 8
    stopbits: int = 1


# TODO(protocol): confirm real values against a capture.
FRAME_START = 0x02   # placeholder (STX)
FRAME_END = 0x03     # placeholder (ETX)
ACK = 0x06
NAK = 0x15
MAX_RETRIES = 3


def checksum(payload: bytes) -> int:
    """Placeholder checksum. TODO(protocol): replace with the real algorithm
    (the binary references CRC-style 'FRAME CHECKED OK' handling)."""
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF


class Downloader:
    """Drives one download session. GUI subscribes via `on_status`."""

    def __init__(self, params: SerialParams,
                 on_status: Callable[[State, str], None]):
        self.params = params
        self.on_status = on_status
        self._abort = False
        self.state = State.IDLE

    def abort(self) -> None:
        self._abort = True

    def _set(self, state: State, detail: str = "") -> None:
        self.state = state
        self.on_status(state, detail)

    def _open(self):
        if serial is None:
            raise RuntimeError("pyserial not installed")
        return serial.Serial(
            port=self.params.port,
            baudrate=self.params.baud,
            parity=self.params.parity,
            bytesize=self.params.bytesize,
            stopbits=self.params.stopbits,
            timeout=2.0,
        )

    def run(self, log_key: str) -> Optional[bytes]:
        """Download one log. Returns raw bytes (to be parsed by format.py)."""
        self._abort = False
        self._set(State.START, log_key)
        try:
            with self._open() as ser:
                buf = bytearray()
                frame_no = 0
                while not self._abort:
                    self._request_frame(ser, log_key, frame_no)
                    self._set(State.REQUEST_SENT, f"frame {frame_no}")
                    frame = self._read_frame(ser)
                    if frame is None:
                        self._set(State.RETRANSMIT, f"frame {frame_no}")
                        if not self._retry(ser, log_key, frame_no):
                            self._set(State.FAILED)
                            return None
                        continue
                    self._set(State.RECEIVING, f"{len(frame)} bytes")
                    if not self._verify(frame):
                        self._set(State.RETRANSMIT, f"frame {frame_no}")
                        continue
                    self._set(State.FRAME_OK, f"frame {frame_no}")
                    body, last = self._unwrap(frame)
                    buf += body
                    if last:
                        break
                    frame_no += 1
                if self._abort:
                    self._set(State.DONE_ABORT)
                    return None
                self._set(State.DONE_OK, f"{len(buf)} bytes")
                return bytes(buf)
        except Exception as exc:  # surface, never swallow
            self._set(State.FAILED, str(exc))
            return None

    # --- wire-format helpers: all TODO(protocol) ---------------------------
    def _request_frame(self, ser, log_key: str, frame_no: int) -> None:
        # TODO(protocol): real request packet for this log type + frame index.
        ser.write(bytes([FRAME_START, 0x00, frame_no & 0xFF, FRAME_END]))

    def _read_frame(self, ser) -> Optional[bytes]:
        # TODO(protocol): real framing (start byte, length, payload, checksum).
        data = ser.read(256)
        return data or None

    def _verify(self, frame: bytes) -> bool:
        # TODO(protocol): split payload vs trailing checksum and compare.
        if len(frame) < 2:
            return False
        return checksum(frame[:-1]) == frame[-1]

    def _unwrap(self, frame: bytes) -> tuple[bytes, bool]:
        # TODO(protocol): strip framing; detect the "NO MORE DATA" terminator.
        return frame[1:-1], False

    def _retry(self, ser, log_key: str, frame_no: int) -> bool:
        for _ in range(MAX_RETRIES):
            if self._abort:
                return False
            self._request_frame(ser, log_key, frame_no)
            if self._read_frame(ser) is not None:
                return True
        return False
