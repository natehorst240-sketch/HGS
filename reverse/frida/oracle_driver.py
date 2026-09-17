"""Drive the HGS response oracle.

Attaches hgs_oracle.js to a running HGS, waits for HGS to send a request
(DOWNLOAD LOGS ...), then injects a candidate DAU reply and reports how HGS
reacts (its next transmit: TRANSMISSION OK = accepted, RETRANSMIT = rejected).

Usage:
    python oracle_driver.py <pid> "<hex bytes to inject as the reply>"
e.g. python oracle_driver.py 16596 "41 2f 43 20 44 41 54 41 ..."

If no hex is given, it just watches and prints HGS's transmits so you can see
the handshake, without injecting.
"""
import sys
import time

import frida

PID = int(sys.argv[1]) if len(sys.argv) > 1 else None
REPLY = sys.argv[2] if len(sys.argv) > 2 else ""

JS = open("hgs_oracle.js", encoding="utf-8").read()
tx_log = []
_evlog = open("oracle_events.log", "w", buffering=1)


def emit(s):
    print(s, flush=True)
    _evlog.write(s + "\n")


def on_message(msg, data):
    if msg.get("type") == "error":
        print("SCRIPT ERROR:", msg.get("stack"))
        return
    p = msg.get("payload", {})
    if p.get("ev") == "tx":
        asc = p.get("ascii", "")
        tx_log.append(asc)
        verdict = ""
        if "TRANSMISSION OK" in asc:
            verdict = "  <== ACCEPTED (TRANSMISSION OK)"
        elif "RETRANSMIT" in asc:
            verdict = "  <== REJECTED (RETRANSMIT)"
        elif "DOWNLOAD" in asc:
            verdict = "  (request)"
        emit("HGS TX: " + repr(asc.strip(".")) + verdict)
    elif p.get("ev") == "delivered":
        emit("   delivered %d bytes to HGS" % p["n"])


session = frida.attach(PID) if PID else frida.attach("Hgs_cpp.exe")
script = session.create_script(JS)
script.on("message", on_message)
script.set_log_handler(lambda level, text: print(text))
script.load()
print("oracle attached. Start a download in HGS now.")

if REPLY:
    # wait for HGS to open the port + send its request, then inject the reply
    print("will inject reply once HGS transmits a request...")
    seen_request = False
    while not seen_request:
        time.sleep(0.2)
        if any("DOWNLOAD" in a for a in tx_log):
            seen_request = True
    time.sleep(0.3)
    n = script.exports_sync.inject(REPLY)
    print("injected reply (%d bytes). Watching HGS reaction..." % n)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    session.detach()
    print("stopped.")
