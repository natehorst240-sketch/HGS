"""Spawn HGS under the serial-sniffer hook (or attach to a running one).

Usage:
    python run_capture.py             # spawn HGS fresh with the hook (default)
    python run_capture.py attach      # attach to an already-running Hgs_cpp.exe
Writes hgs_serial.log next to this script. Ctrl+C to stop.
"""
import os
import sys
import time

import frida

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "hgs_sniff.js")
LOG = os.path.join(HERE, "hgs_serial.log")
HGS_DIR = r"C:\Program Files (x86)\HGS"
HGS_EXE = os.path.join(HGS_DIR, "Hgs_cpp.exe")

mode = sys.argv[1] if len(sys.argv) > 1 else "spawn"
# optional 2nd arg: log filename suffix so multiple attaches don't clash
if len(sys.argv) > 2:
    LOG = os.path.join(HERE, sys.argv[2])
logf = open(LOG, "w", buffering=1)


def on_message(msg, data):
    if msg.get("type") == "error":
        line = "SCRIPT ERROR: %s" % msg.get("stack", msg)
        logf.write(line + "\n")
        print(line)


def on_log(level, text):
    logf.write(text + "\n")
    print(text)


device = frida.get_local_device()
pid = None
if mode == "attach":
    session = frida.attach("Hgs_cpp.exe")
elif mode.isdigit():
    session = device.attach(int(mode))   # attach to a specific PID
else:
    pid = device.spawn([HGS_EXE], cwd=HGS_DIR)
    session = device.attach(pid)

script = session.create_script(open(JS, encoding="utf-8").read())
script.on("message", on_message)
script.set_log_handler(on_log)
script.load()
if pid is not None:
    device.resume(pid)
print("hook active (mode=%s) -> %s" % (mode, LOG))
print("In HGS: Com Settings -> COM3, 1-port, download mode, then click Download.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logf.close()
    session.detach()
    print("stopped.")
