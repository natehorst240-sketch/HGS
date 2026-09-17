"""Boot-time mode select (CircuitPython).

Office mode  (USB host present): flash is exposed to the PC as a read-only-
             to-code USB drive, so the maintainer just copies files off.
Aircraft mode (no USB host, running on battery): code gets write access to
             the flash so downloads can be stored.
"""
import storage
import supervisor

if supervisor.runtime.usb_connected:
    # PC plugged in: present files to the host; code must not write.
    storage.remount("/", readonly=True)
else:
    # On battery at the aircraft: allow the downloader to write files.
    storage.remount("/", readonly=False)
