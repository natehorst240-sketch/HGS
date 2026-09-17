import sys, time, frida
PID=int(sys.argv[1]); REPLY=sys.argv[2] if len(sys.argv)>2 else ""
JS=open("hgs_oracle2.js",encoding="utf-8").read()
log=open("oracle2_events.log","w",buffering=1); tx=[]
def emit(s): print(s,flush=True); log.write(s+"\n")
def on_msg(m,d):
    if m.get("type")=="error": emit("ERR "+str(m.get("stack"))); return
    p=m.get("payload",{})
    if p.get("ev")=="tx":
        a=p.get("ascii",""); tx.append(a)
        v="  <== ACCEPTED" if "TRANSMISSION OK" in a else ("  <== REJECTED/RETRANSMIT (it PROCESSED our bytes!)" if "RETRANSMIT" in a else ("  (request)" if "DOWNLOAD" in a else "  <== NEW TX"))
        emit("TX "+repr(a.strip("."))+v)
    elif p.get("ev")=="delivered": emit("  << delivered %d"%p["n"])
s=frida.attach(PID); sc=s.create_script(JS); sc.on("message",on_msg)
sc.set_log_handler(lambda l,t: emit(t)); sc.load(); emit("oracle2 attached to %d"%PID)
if REPLY:
    while not any("DOWNLOAD" in a for a in tx): time.sleep(0.2)
    time.sleep(0.3); n=sc.exports_sync.inject(REPLY); emit("injected %d bytes + woke receive thread"%n)
try:
    while True: time.sleep(1)
except KeyboardInterrupt: s.detach()
