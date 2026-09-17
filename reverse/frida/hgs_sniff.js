/*
 * hgs_sniff.js — capture the HGS <-> DAU serial conversation from inside the
 * running Hgs_cpp.exe process, without Wireshark, USBPcap, or admin drivers.
 *
 * How it works: MSCOMM32.OCX (the serial control HGS uses) ultimately moves
 * bytes with the Win32 comm API — CreateFile on \\.\COMx, then ReadFile /
 * WriteFile (usually overlapped). We hook those in kernel32, identify the COM
 * port handle, and log every byte in each direction with a timestamp. This is
 * strictly below the OLE layer, so it sees the real wire bytes both ways.
 *
 * Run:
 *   pip install frida-tools
 *   frida -f "C:\\Program Files (x86)\\HGS\\Bin\\Hgs_cpp.exe" -l hgs_sniff.js -o hgs_serial.log
 * then do ONE normal download in HGS, let it finish, close the app, send the log.
 *
 * TX (PC -> DAU) lines start with ">>", RX (DAU -> PC) with "<<".
 */
'use strict';

// Frida 17 removed Module.findExportByName; resolve kernel32 exports robustly
// across versions.
function imp(name) {
  try {
    if (typeof Module.getGlobalExportByName === 'function') {
      const p = Module.getGlobalExportByName(name);
      if (p && !p.isNull()) return p;
    }
  } catch (e) {}
  try {
    const m = Process.getModuleByName('kernel32.dll');
    const p = m.findExportByName ? m.findExportByName(name) : m.getExportByName(name);
    if (p && !p.isNull()) return p;
  } catch (e) {}
  return null;
}

const comHandles = {};        // handle string -> COM path
const overlappedMap = {};     // OVERLAPPED* -> { handle, buffer } for pending reads
let t0 = null;

function ms() {
  const now = Date.now();
  if (t0 === null) t0 = now;
  return (now - t0);
}

function hex(ptr, len) {
  if (len <= 0) return '';
  const bytes = new Uint8Array(ptr.readByteArray(len));
  let s = '';
  for (let i = 0; i < bytes.length; i++) {
    s += bytes[i].toString(16).padStart(2, '0');
    if (i !== bytes.length - 1) s += ' ';
  }
  return s;
}

function emit(dir, ptr, len) {
  if (len <= 0) return;
  // chunk long buffers so lines stay readable
  const MAX = 32;
  for (let off = 0; off < len; off += MAX) {
    const n = Math.min(MAX, len - off);
    console.log(`[${ms().toString().padStart(8)} ms] ${dir} ${hex(ptr.add(off), n)}`);
  }
}

function isCom(pathStr) {
  if (!pathStr) return false;
  const u = pathStr.toUpperCase();
  return u.indexOf('COM') >= 0;   // matches \\.\COM3, COM3:, etc.
}

function hookCreate(name, wide) {
  const addr = imp(name);
  if (!addr) return;
  Interceptor.attach(addr, {
    onEnter(args) {
      try { this.path = wide ? args[0].readUtf16String() : args[0].readAnsiString(); }
      catch (e) { this.path = null; }
    },
    onLeave(retval) {
      if (isCom(this.path) && !retval.equals(ptr('-1'))) {
        comHandles[retval.toString()] = this.path;
        console.log(`[${ms().toString().padStart(8)} ms] -- OPEN ${this.path} handle=${retval}`);
      }
    }
  });
}

hookCreate('CreateFileW', true);
hookCreate('CreateFileA', false);

// Robust COM-handle tagging: these serial-only APIs take the port handle as
// arg0 and are called by MSComm on every port open / I/O cycle, so we catch
// the handle even if the port was already open before we attached.
['SetCommState', 'GetCommState', 'SetCommTimeouts', 'PurgeComm',
 'SetupComm', 'ClearCommError', 'EscapeCommFunction'].forEach(function (fn) {
  const a = imp(fn);
  if (!a) return;
  Interceptor.attach(a, {
    onEnter(args) {
      const h = args[0].toString();
      if (!comHandles[h]) {
        comHandles[h] = '(serial handle via ' + fn + ')';
        console.log(`[${ms().toString().padStart(8)} ms] -- serial handle ${args[0]} tagged by ${fn}`);
      }
    }
  });
});

// WriteFile(hFile, lpBuffer, nToWrite, lpWritten, lpOverlapped)
const write = imp('WriteFile');
if (write) Interceptor.attach(write, {
  onEnter(args) {
    if (comHandles[args[0].toString()]) {
      // Outbound content is valid at call time regardless of overlapped I/O.
      emit('>>', args[1], args[2].toInt32());
    }
  }
});

// ReadFile(hFile, lpBuffer, nToRead, lpRead, lpOverlapped)
const read = imp('ReadFile');
if (read) Interceptor.attach(read, {
  onEnter(args) {
    this.handle = args[0];
    this.buffer = args[1];
    this.lpRead = args[3];
    this.overlapped = args[4];
    this.isCom = !!comHandles[args[0].toString()];
  },
  onLeave(retval) {
    if (!this.isCom) return;
    if (!this.overlapped.isNull()) {
      // Overlapped read: bytes arrive later; remember buffer for completion.
      overlappedMap[this.overlapped.toString()] = { handle: this.handle, buffer: this.buffer };
      return;
    }
    // Synchronous read: bytes-read count is filled now.
    let n = 0;
    if (!this.lpRead.isNull()) { try { n = this.lpRead.readU32(); } catch (e) {} }
    emit('<<', this.buffer, n);
  }
});

// --- receive-path observation: how does HGS poll for a reply? ---
// MSComm typically calls ClearCommError to read COMSTAT.cbInQue (bytes waiting)
// and/or WaitCommEvent. Logging these reveals where to inject a fake response.
const cce = imp('ClearCommError');
if (cce) Interceptor.attach(cce, {
  onEnter(args) { this.h = args[0].toString(); this.stat = args[2]; },
  onLeave(retval) {
    if (!comHandles[this.h]) return;
    let inq = -1;
    if (this.stat && !this.stat.isNull()) {
      try { inq = this.stat.add(4).readU32(); } catch (e) {}  // COMSTAT.cbInQue
    }
    console.log(`[${ms().toString().padStart(8)} ms] ~~ ClearCommError cbInQue=${inq}`);
  }
});

const wce = imp('WaitCommEvent');
if (wce) Interceptor.attach(wce, {
  onEnter(args) { this.h = args[0].toString(); },
  onLeave(retval) {
    if (comHandles[this.h])
      console.log(`[${ms().toString().padStart(8)} ms] ~~ WaitCommEvent ret=${retval}`);
  }
});

// Also log ReadFile REQUEST sizes on the COM handle (even when 0 bytes come),
// so we see what response size HGS expects.
const read2 = imp('ReadFile');
if (read2) Interceptor.attach(read2, {
  onEnter(args) {
    if (comHandles[args[0].toString()])
      console.log(`[${ms().toString().padStart(8)} ms] ~~ ReadFile nToRead=${args[2].toInt32()}`);
  }
});

// GetOverlappedResult(hFile, lpOverlapped, lpTransferred, bWait) — completes reads.
const gor = imp('GetOverlappedResult');
if (gor) Interceptor.attach(gor, {
  onEnter(args) {
    this.rec = overlappedMap[args[1].toString()];
    this.lpTransferred = args[2];
  },
  onLeave(retval) {
    if (!this.rec) return;
    let n = 0;
    if (!this.lpTransferred.isNull()) { try { n = this.lpTransferred.readU32(); } catch (e) {} }
    emit('<<', this.rec.buffer, n);
  }
});

console.log('hgs_sniff active — perform a normal download now.');
