"""CST816S capacitive touch driver — MicroPython, ESP32-S3-Touch-LCD-1.28.

Ported from Waveshare's Arduino CST816S demo. I2C addr 0x15 on SDA=6/SCL=7,
reset=13, INT=5 (pulsed, so we poll rather than trigger on it).

Read reg 0x01 for 6 bytes: gesture, points, xH/xL, yH/yL.
    x = ((buf[2] & 0x0F) << 8) | buf[3]
    y = ((buf[4] & 0x0F) << 8) | buf[5]
Chip version at reg 0xA7 (0xB5 = CST816S).
"""
from machine import Pin, I2C
from time import sleep_ms, ticks_ms, ticks_diff

ADDR = 0x15


class CST816:
    def __init__(self, i2c=None, scl=7, sda=6, rst=13, irq=5,
                 width=240, height=240):
        self.i2c = i2c or I2C(0, scl=Pin(scl), sda=Pin(sda), freq=400_000)
        self.width = width
        self.height = height
        self._buf = bytearray(6)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.irq = Pin(irq, Pin.IN, Pin.PULL_UP)
        self.reset()

    def reset(self):
        self.rst.value(1); sleep_ms(50)
        self.rst.value(0); sleep_ms(5)
        self.rst.value(1); sleep_ms(50)

    def chip_id(self):
        try:
            return self.i2c.readfrom_mem(ADDR, 0xA7, 1)[0]
        except OSError:
            return None

    def read(self):
        """(x, y) of the touch point, else None."""
        try:
            self.i2c.readfrom_mem_into(ADDR, 0x01, self._buf)
        except OSError:
            return None
        b = self._buf
        if b[1] < 1:                         # no finger down
            return None
        x = ((b[2] & 0x0F) << 8) | b[3]
        y = ((b[4] & 0x0F) << 8) | b[5]
        if x >= self.width or y >= self.height:
            return None
        return (x, y)

    @property
    def touched(self):
        return self.read() is not None

    def wait_touch(self, timeout_ms=None, poll_ms=50):
        t0 = ticks_ms()
        while True:
            if self.read() is not None:
                return True
            if timeout_ms is not None and ticks_diff(ticks_ms(), t0) > timeout_ms:
                return False
            sleep_ms(poll_ms)

    def wait_release(self, poll_ms=50, settle_ms=150):
        clear_since = None
        while True:
            if self.read() is None:
                if clear_since is None:
                    clear_since = ticks_ms()
                elif ticks_diff(ticks_ms(), clear_since) >= settle_ms:
                    return
            else:
                clear_since = None
            sleep_ms(poll_ms)

    def hold_checker(self, hold_ms=1500, interval_ms=250):
        """Callable that returns True once the screen has been held for
        `hold_ms`. Rate-limited, safe as dau_protocol's abort_check. A brief
        tap won't trip it."""
        state = {"last": 0, "since": 0, "tripped": False}

        def check():
            if state["tripped"]:
                return True
            now = ticks_ms()
            if ticks_diff(now, state["last"]) < interval_ms:
                return False
            state["last"] = now
            if self.read() is None:
                state["since"] = 0
                return False
            if state["since"] == 0:
                state["since"] = now
            elif ticks_diff(now, state["since"]) >= hold_ms:
                state["tripped"] = True
            return state["tripped"]

        return check
