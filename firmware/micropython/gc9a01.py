"""GC9A01 240x240 round LCD driver — MicroPython, ESP32-S3-Touch-LCD-1.28.

No full-screen framebuffer (the board has no PSRAM): the screen is painted by
streaming pixels, and text is rendered through a tiny 1-bit glyph buffer, so
peak RAM is a few hundred bytes regardless of what's drawn. Colors are written
as big-endian RGB565 directly, which avoids the usual framebuf byte-order bug.

Init sequence is ported verbatim from Waveshare's official Arduino demo
(LCD_1in28.cpp) — the values are GC9A01-specific and known-good on this panel.

Pins (fixed by the board): SCK=10 MOSI=11 CS=9 DC=8 RST=14 BL=2.
"""
import framebuf
from machine import Pin, SPI
from time import sleep_ms

WIDTH = 240
HEIGHT = 240

# a few RGB565 colors (big-endian handled at write time)
BLACK = 0x0000
WHITE = 0xFFFF
CYAN = 0x07FF
GREEN = 0x07E0
RED = 0xF800
AMBER = 0xFD20
GREY = 0x8410
DKGREY = 0x2104


class GC9A01:
    def __init__(self, spi=None, sck=10, mosi=11, cs=9, dc=8, rst=14, bl=2,
                 baudrate=40_000_000):
        self.spi = spi or SPI(1, baudrate=baudrate, polarity=0, phase=0,
                              sck=Pin(sck), mosi=Pin(mosi))
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.bl = Pin(bl, Pin.OUT, value=0)
        self._reset()
        self._init_reg()
        self.fill(BLACK)
        self.bl.value(1)                 # backlight on only once something's drawn

    # --- low level ---------------------------------------------------------
    def _reset(self):
        self.rst.value(1); sleep_ms(10)
        self.rst.value(0); sleep_ms(10)
        self.rst.value(1); sleep_ms(120)

    def _cmd(self, c):
        self.dc.value(0); self.cs.value(0)
        self.spi.write(bytes((c,)))
        self.cs.value(1)

    def _d8(self, v):
        self.dc.value(1); self.cs.value(0)
        self.spi.write(bytes((v,)))
        self.cs.value(1)

    def _data(self, buf):
        self.dc.value(1); self.cs.value(0)
        self.spi.write(buf)
        self.cs.value(1)

    def _window(self, x0, y0, x1, y1):
        self._cmd(0x2A)
        self._data(bytes((0x00, x0 & 0xFF, (x1 >> 8) & 0xFF, x1 & 0xFF)))
        self._cmd(0x2B)
        self._data(bytes((0x00, y0 & 0xFF, (y1 >> 8) & 0xFF, y1 & 0xFF)))
        self._cmd(0x2C)

    # --- init (from LCD_1in28.cpp) -----------------------------------------
    def _init_reg(self):
        c, d = self._cmd, self._d8
        c(0xEF)
        c(0xEB); d(0x14)
        c(0xFE); c(0xEF)
        c(0xEB); d(0x14)
        c(0x84); d(0x40)
        c(0x85); d(0xFF)
        c(0x86); d(0xFF)
        c(0x87); d(0xFF)
        c(0x88); d(0x0A)
        c(0x89); d(0x21)
        c(0x8A); d(0x00)
        c(0x8B); d(0x80)
        c(0x8C); d(0x01)
        c(0x8D); d(0x01)
        c(0x8E); d(0xFF)
        c(0x8F); d(0xFF)
        c(0xB6); d(0x00); d(0x20)
        c(0x36); d(0x08)                 # MADCTL: vertical, RGB
        c(0x3A); d(0x05)                 # 16-bit/pixel RGB565
        c(0x90); d(0x08); d(0x08); d(0x08); d(0x08)
        c(0xBD); d(0x06)
        c(0xBC); d(0x00)
        c(0xFF); d(0x60); d(0x01); d(0x04)
        c(0xC3); d(0x13)
        c(0xC4); d(0x13)
        c(0xC9); d(0x22)
        c(0xBE); d(0x11)
        c(0xE1); d(0x10); d(0x0E)
        c(0xDF); d(0x21); d(0x0C); d(0x02)
        c(0xF0); d(0x45); d(0x09); d(0x08); d(0x08); d(0x26); d(0x2A)
        c(0xF1); d(0x43); d(0x70); d(0x72); d(0x36); d(0x37); d(0x6F)
        c(0xF2); d(0x45); d(0x09); d(0x08); d(0x08); d(0x26); d(0x2A)
        c(0xF3); d(0x43); d(0x70); d(0x72); d(0x36); d(0x37); d(0x6F)
        c(0xED); d(0x1B); d(0x0B)
        c(0xAE); d(0x77)
        c(0xCD); d(0x63)
        c(0x70); d(0x07); d(0x07); d(0x04); d(0x0E); d(0x0F); d(0x09); d(0x07); d(0x08); d(0x03)
        c(0xE8); d(0x34)
        c(0x62); d(0x18); d(0x0D); d(0x71); d(0xED); d(0x70); d(0x70)
        d(0x18); d(0x0F); d(0x71); d(0xEF); d(0x70); d(0x70)
        c(0x63); d(0x18); d(0x11); d(0x71); d(0xF1); d(0x70); d(0x70)
        d(0x18); d(0x13); d(0x71); d(0xF3); d(0x70); d(0x70)
        c(0x64); d(0x28); d(0x29); d(0xF1); d(0x01); d(0xF1); d(0x00); d(0x07)
        c(0x66); d(0x3C); d(0x00); d(0xCD); d(0x67); d(0x45); d(0x45); d(0x10); d(0x00); d(0x00); d(0x00)
        c(0x67); d(0x00); d(0x3C); d(0x00); d(0x00); d(0x00); d(0x01); d(0x54); d(0x10); d(0x32); d(0x98)
        c(0x74); d(0x10); d(0x85); d(0x80); d(0x00); d(0x00); d(0x4E); d(0x00)
        c(0x98); d(0x3E); d(0x07)
        c(0x35)
        c(0x21)
        c(0x11); sleep_ms(120)
        c(0x29); sleep_ms(20)

    # --- drawing -----------------------------------------------------------
    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        x1, y1 = x + w - 1, y + h - 1
        self._window(x, y, x1, y1)
        row = bytes((color >> 8, color & 0xFF)) * w
        self.dc.value(1); self.cs.value(0)
        for _ in range(h):
            self.spi.write(row)
        self.cs.value(1)

    def fill(self, color):
        self.fill_rect(0, 0, WIDTH, HEIGHT, color)

    def blit565(self, x, y, w, h, buf):
        """Blit a raw big-endian RGB565 image (w*h*2 bytes) at (x, y)."""
        self._window(x, y, x + w - 1, y + h - 1)
        self.dc.value(1); self.cs.value(0)
        self.spi.write(buf)
        self.cs.value(1)

    def text(self, s, x, y, fg=WHITE, bg=BLACK, scale=2):
        """Render `s` (8x8 built-in font) at (x, y), integer-scaled. Streams
        directly; a 1-bit glyph buffer keeps RAM to bytes, not kilobytes."""
        if not s:
            return
        w = len(s) * 8
        glyph = bytearray(w)                 # 8 rows packed as MONO_VLSB below
        fb = framebuf.FrameBuffer(glyph, w, 8, framebuf.MONO_VLSB)
        fb.fill(0)
        fb.text(s, 0, 0, 1)
        fgb = bytes((fg >> 8, fg & 0xFF))
        bgb = bytes((bg >> 8, bg & 0xFF))
        self._window(x, y, x + w * scale - 1, y + 8 * scale - 1)
        self.dc.value(1); self.cs.value(0)
        line = bytearray(w * scale * 2)
        for row in range(8):
            i = 0
            for col in range(w):
                on = (glyph[col] >> row) & 1
                px = fgb if on else bgb
                for _ in range(scale):
                    line[i] = px[0]; line[i + 1] = px[1]; i += 2
            for _ in range(scale):
                self.spi.write(line)
        self.cs.value(1)
