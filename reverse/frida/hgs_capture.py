#!/usr/bin/env python3
"""
hgs_capture.py  —  passive serial-protocol capture for HGS (single file).

WHAT IT DOES
  Attaches to an already-running Hgs_cpp.exe and records every byte HGS sends to
  and receives from the DAU over the serial port, with timestamps. It is
  READ-ONLY: it only observes HGS's own serial I/O (below the ActiveX layer).
  It does not change what HGS or the DAU do, install a driver, or touch the
  network. Output goes to the console and to hgs_serial.log next to this file.

WHY
  If run on the laptop that actually talks to the aircraft, one normal download
  captures the complete request+response protocol.

HOW TO RUN
  1) Install the tool (userland, usually no admin):   pip install frida-tools
  2) Start HGS normally and get to the download screen.
  3) In a terminal:                                   python hgs_capture.py
  4) Do one normal download in HGS. Let it finish.
  5) Ctrl+C here. Send hgs_serial.log back.

IF SOMETHING BLOCKS IT
  - "pip install" fails (SSL/proxy)      -> corporate proxy blocking PyPI.
  - "No module named frida"              -> install didn't take.
  - attach fails / access denied         -> endpoint security blocking Frida.
  Any of those is exactly what we're testing for; note which one you hit.
"""
import os
import sys
import time

try:
    import frida
except ImportError:
    sys.exit("frida not installed.  Run:  pip install frida-tools")

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hgs_serial.log")
TARGET = "Hgs_cpp.exe"

# --- in-process hook (Frida JS). Taps the Win32 comm API below MSCOMM32.OCX. ---
JS = r"""
'use strict';
function imp(n){
  try{ if(typeof Module.getGlobalExportByName==='function'){
    var p=Module.getGlobalExportByName(n); if(p&&!p.isNull()) return p; } }catch(e){}
  try{ var m=Process.getModuleByName('kernel32.dll');
    return m.findExportByName ? m.findExportByName(n) : m.getExportByName(n); }catch(e){}
  return null;
}
var com={}, ovl={}, t0=Date.now();
function ms(){ return Date.now()-t0; }
function tag(h,w){ if(!com[h]){ com[h]=w; console.log('['+ms()+' ms] -- '+w+' handle='+h); } }
function emit(dir,ptr,len){
  if(len<=0) return;
  var b=new Uint8Array(ptr.readByteArray(len)), hex='';
  for(var i=0;i<b.length;i++) hex+=('0'+b[i].toString(16)).slice(-2)+' ';
  console.log('['+ms()+' ms] '+dir+' '+hex.trim());
}
['SetCommState','GetCommState','SetCommTimeouts','PurgeComm','SetupComm',
 'ClearCommError','EscapeCommFunction'].forEach(function(fn){
  var a=imp(fn); if(a) Interceptor.attach(a,{onEnter:function(ar){ tag(ar[0].toString(),'serial('+fn+')'); }});
});
[['CreateFileW',true],['CreateFileA',false]].forEach(function(p){
  var a=imp(p[0]); if(!a) return;
  Interceptor.attach(a,{
    onEnter:function(ar){ try{ this.p=p[1]?ar[0].readUtf16String():ar[0].readAnsiString(); }catch(e){ this.p=null; } },
    onLeave:function(rv){ if(this.p && this.p.toUpperCase().indexOf('COM')>=0 && !rv.equals(ptr('-1'))) tag(rv.toString(), this.p); }
  });
});
var wf=imp('WriteFile');
if(wf) Interceptor.attach(wf,{ onEnter:function(a){ if(com[a[0].toString()]) emit('>>', a[1], a[2].toInt32()); } });
var rf=imp('ReadFile');
if(rf) Interceptor.attach(rf,{
  onEnter:function(a){ this.h=a[0].toString(); this.b=a[1]; this.lp=a[3]; this.ov=a[4]; this.isc=!!com[this.h]; },
  onLeave:function(rv){
    if(!this.isc) return;
    if(this.ov && !this.ov.isNull()){ ovl[this.ov.toString()]={b:this.b}; return; }
    var n=0; if(this.lp && !this.lp.isNull()){ try{ n=this.lp.readU32(); }catch(e){} }
    emit('<<', this.b, n);
  }
});
var gor=imp('GetOverlappedResult');
if(gor) Interceptor.attach(gor,{
  onEnter:function(a){ this.rec=ovl[a[1].toString()]; this.lp=a[2]; },
  onLeave:function(rv){ if(!this.rec) return; var n=0; if(this.lp && !this.lp.isNull()){ try{ n=this.lp.readU32(); }catch(e){} } emit('<<', this.rec.b, n); }
});
console.log('hgs_capture active - do a normal download now (>> = to DAU, << = from DAU)');
"""


def main():
    logf = open(LOG, "w", buffering=1)

    def on_log(level, text):
        print(text)
        logf.write(text + "\n")

    def on_message(msg, data):
        if msg.get("type") == "error":
            on_log("error", "SCRIPT ERROR: %s" % msg.get("stack", msg))

    try:
        session = frida.attach(TARGET)
    except frida.ProcessNotFoundError:
        sys.exit("Could not find %s. Start HGS first, then run this." % TARGET)
    except Exception as exc:
        sys.exit("Attach failed (endpoint security may be blocking Frida): %s" % exc)

    script = session.create_script(JS)
    script.on("message", on_message)
    script.set_log_handler(on_log)
    script.load()
    print("attached to %s. Logging to %s. Ctrl+C to stop." % (TARGET, LOG))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logf.close()
        session.detach()
        print("\nstopped. Send hgs_serial.log back.")


if __name__ == "__main__":
    main()
