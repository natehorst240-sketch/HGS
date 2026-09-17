"""Boot-time mode select (CircuitPython).

Office mode  (USB host present): flash is exposed to the PC as a read/write
             USB drive so the maintainer can copy files off (and update code).
Aircraft mode (no USB host, on battery): CircuitPython code gets write access
             so downloads can be saved.

`supervisor.runtime.usb_connected` reads False very early in boot (before USB
enumerates), so we wait briefly for it to settle before deciding — otherwise a
board plugged into a PC can come up wrongly in aircraft mode and lock the PC
out of the drive.
"""
import storage
import supervisor
import time

usb = False
for _ in range(30):                 # up to ~1.5 s for USB to enumerate
    if supervisor.runtime.usb_connected:
        usb = True
        break
    time.sleep(0.05)

# readonly=True  -> USB host (PC) can write, code cannot   (office mode)
# readonly=False -> code can write, USB host cannot        (aircraft mode)
storage.remount("/", readonly=usb)
