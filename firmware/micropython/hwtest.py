"""Milestone-2 hardware bring-up test — run on the ESP32-S3-Touch-LCD-1.28.

Push this + gc9a01.py + cst816.py to the board, then:
    import hwtest        (at the REPL: python -m mpremote connect COM7 run hwtest.py)

Proves: SPI + GC9A01 init (colored fills + text), and CST816S touch (chip id,
live coordinates). Watch the REPL for the printed chip id and touch points,
and the round LCD for the color sweep + text + a dot where you touch.
"""
from time import sleep_ms
import gc9a01 as g
from gc9a01 import GC9A01
from cst816 import CST816

print("init display...")
lcd = GC9A01()
for name, col in (("RED", g.RED), ("GREEN", g.GREEN), ("CYAN", g.CYAN)):
    lcd.fill(col)
    print("  fill", name)
    sleep_ms(400)
lcd.fill(g.BLACK)
lcd.text("HGS STICK", 40, 60, g.CYAN, g.BLACK, 2)
lcd.text("display OK", 44, 100, g.WHITE, g.BLACK, 2)

print("init touch...")
tp = CST816()
cid = tp.chip_id()
print("  CST816 chip id =", hex(cid) if cid is not None else None,
      "(expect 0xb5)")
lcd.text("touch id %s" % (hex(cid) if cid is not None else "None"),
         30, 140, g.AMBER, g.BLACK, 2)

print("touch the screen (Ctrl-C to stop)...")
last = None
while True:
    p = tp.read()
    if p and p != last:
        print("  touch", p)
        lcd.fill_rect(0, 180, 240, 24, g.BLACK)
        lcd.text("x=%3d y=%3d" % p, 40, 182, g.GREEN, g.BLACK, 2)
        last = p
    elif p is None:
        last = None
    sleep_ms(30)
