"""CST816S capacitive touch driver (Waveshare ESP32-S3-Touch-LCD-1.28 / 25098).

No Adafruit driver ships in the base bundle for this part, and there is no
board-specific CircuitPython build for the 1.28 round board, so this is a
small self-contained one: enough to answer "is the screen touched, and where"
— which is all the download stick needs (touch = the start/abort command,
replacing a physical button).

Board wiring (fixed): I2C 0x15 on IO7(SCL)/IO6(SDA), reset IO13, INT IO5.
Round GC9A01 panel is 240x240.

CST816S register map (single-touch part):
    0x01 GestureID
    0x02 FingerNum         (0 or 1)
    0x03 XposH  (low nibble = x[11:8])
    0x04 XposL          x = ((0x03 & 0x0F) << 8) | 0x04
    0x05 YposH  (low nibble = y[11:8])
    0x06 YposL          y = ((0x05 & 0x0F) << 8) | 0x06
    0xA7 ChipID          0xB5 = CST816S
"""
import time

import board
import busio
import digitalio

ADDR = 0x15
_REG_BASE = 0x01          # read 6 bytes: gesture, fingers, xH, xL, yH, yL
_REG_CHIPID = 0xA7


class Touch:
    """Polled CST816S reader. Safe to call in a tight loop."""

    def __init__(self, i2c=None, scl=None, sda=None, rst=None, irq=None,
                 width=240, height=240):
        if i2c is None:
            i2c = busio.I2C(scl if scl is not None else board.IO7,
                            sda if sda is not None else board.IO6,
                            frequency=400_000)
        self._i2c = i2c
        self._buf = bytearray(6)
        self.width = width
        self.height = height

        pin = rst if rst is not None else getattr(board, "IO13", None)
        self._rst = None
        if pin is not None:
            self._rst = digitalio.DigitalInOut(pin)
            self._rst.switch_to_output(value=True)
            self.reset()

        # INT is a pulse on this part, not a level, so we poll I2C rather than
        # trigger on it. Claim it as an input so nothing else drives the line.
        pin = irq if irq is not None else getattr(board, "IO5", None)
        self._irq = None
        if pin is not None:
            self._irq = digitalio.DigitalInOut(pin)
            self._irq.switch_to_input(pull=digitalio.Pull.UP)

    def reset(self):
        if self._rst is None:
            return
        self._rst.value = False
        time.sleep(0.02)
        self._rst.value = True
        time.sleep(0.06)          # CST816S needs ~50 ms after reset

    def _read(self, reg, buf):
        while not self._i2c.try_lock():
            time.sleep(0)
        try:
            self._i2c.writeto_then_readfrom(ADDR, bytes((reg,)), buf)
            return True
        except OSError:
            return False           # controller idle / NAK -> "no touch"
        finally:
            self._i2c.unlock()

    def chip_id(self):
        """0xB5 for CST816S, for bring-up checks. None if it doesn't answer."""
        b = bytearray(1)
        return b[0] if self._read(_REG_CHIPID, b) else None

    def read(self):
        """(x, y) of the touch point in panel coordinates, else None."""
        if not self._read(_REG_BASE, self._buf):
            return None
        b = self._buf
        if b[1] < 1:               # FingerNum == 0 -> nothing down
            return None
        x = ((b[2] & 0x0F) << 8) | b[3]
        y = ((b[4] & 0x0F) << 8) | b[5]
        if x >= self.width or y >= self.height:
            return None            # implausible -> noise
        return (x, y)

    @property
    def touched(self):
        return self.read() is not None

    def wait_touch(self, timeout=None, poll=0.05):
        """Block until touched. False if it timed out."""
        t0 = time.monotonic()
        while True:
            if self.read() is not None:
                return True
            if timeout is not None and time.monotonic() - t0 > timeout:
                return False
            time.sleep(poll)

    def wait_release(self, poll=0.05, settle=0.15):
        """Block until the screen has been clear for `settle` seconds."""
        clear_since = None
        while True:
            if self.read() is None:
                if clear_since is None:
                    clear_since = time.monotonic()
                elif time.monotonic() - clear_since >= settle:
                    return
            else:
                clear_since = None
            time.sleep(poll)

    def hold_checker(self, hold_s=1.5, interval=0.25):
        """Cheap callable, True once the screen has been held for `hold_s`.
        Rate-limited, so it is safe as dau_protocol's abort_check (called on
        every byte-level poll). A brief tap won't trip it — only a deliberate
        press-and-hold aborts a running download."""
        state = {"last": 0.0, "since": 0.0, "tripped": False}

        def check():
            if state["tripped"]:
                return True
            now = time.monotonic()
            if now - state["last"] < interval:
                return False
            state["last"] = now
            if self.read() is None:
                state["since"] = 0.0
                return False
            if state["since"] == 0.0:
                state["since"] = now
            elif now - state["since"] >= hold_s:
                state["tripped"] = True
            return state["tripped"]

        return check
