/*
 * hgs_oracle.js — make HGS grade candidate DAU responses.
 *
 * Injects bytes into HGS's serial receive path (so it thinks the DAU replied)
 * and reports HGS's outgoing bytes back to the driver, so we can tell whether
 * HGS accepted the frame (it transmits "TRANSMISSION OK ...") or rejected it
 * ("RETRANSMIT ..."). Driven over RPC from oracle_driver.py.
 *
 * Injection points (from the live receive-path trace):
 *   ClearCommError -> report COMSTAT.cbInQue = bytes we want to deliver
 *   ReadFile       -> hand HGS those bytes
 *   WaitCommEvent  -> signal EV_RXCHAR so an event-driven read fires
 */
'use strict';

function imp(name) {
  try { if (typeof Module.getGlobalExportByName === 'function') {
    const p = Module.getGlobalExportByName(name); if (p && !p.isNull()) return p; } } catch (e) {}
  try { const m = Process.getModuleByName('kernel32.dll');
    return m.findExportByName ? m.findExportByName(name) : m.getExportByName(name); } catch (e) {}
  return null;
}

const comHandles = {};
let injectQueue = [];      // bytes still to hand to HGS
let t0 = Date.now();
function ms() { return Date.now() - t0; }

function tagComHandle(h, why) {
  if (!comHandles[h]) { comHandles[h] = why; console.log(`[${ms()} ms] handle ${h} (${why})`); }
}

// tag the COM handle
['SetCommState', 'GetCommState', 'SetCommTimeouts', 'PurgeComm', 'SetupComm',
 'ClearCommError', 'EscapeCommFunction'].forEach(function (fn) {
  const a = imp(fn); if (!a) return;
  Interceptor.attach(a, { onEnter(args) { tagComHandle(args[0].toString(), fn); } });
});

// CreateFile too
['CreateFileW', 'CreateFileA'].forEach(function (fn) {
  const a = imp(fn); if (!a) return;
  const wide = fn.endsWith('W');
  Interceptor.attach(a, {
    onEnter(args) { try { this.p = wide ? args[0].readUtf16String() : args[0].readAnsiString(); } catch (e) { this.p = null; } },
    onLeave(retval) { if (this.p && this.p.toUpperCase().indexOf('COM') >= 0 && !retval.equals(ptr('-1'))) tagComHandle(retval.toString(), this.p); }
  });
});

// Observe HGS -> DAU (the ACK/NAK we grade on)
const write = imp('WriteFile');
if (write) Interceptor.attach(write, {
  onEnter(args) {
    if (!comHandles[args[0].toString()]) return;
    const n = args[2].toInt32();
    const bytes = new Uint8Array(args[1].readByteArray(n));
    let hex = '', asc = '';
    for (let i = 0; i < bytes.length; i++) {
      hex += bytes[i].toString(16).padStart(2, '0') + ' ';
      asc += (bytes[i] >= 32 && bytes[i] < 127) ? String.fromCharCode(bytes[i]) : '.';
    }
    console.log(`[${ms()} ms] >> ${hex}`);
    send({ ev: 'tx', hex: hex.trim(), ascii: asc });
  }
});

// ClearCommError -> pretend N bytes are waiting
const cce = imp('ClearCommError');
if (cce) Interceptor.attach(cce, {
  onEnter(args) { this.h = args[0].toString(); this.stat = args[2]; },
  onLeave(retval) {
    if (!comHandles[this.h] || injectQueue.length === 0) return;
    if (this.stat && !this.stat.isNull()) {
      try { this.stat.add(4).writeU32(injectQueue.length); } catch (e) {}  // COMSTAT.cbInQue
    }
  }
});

// WaitCommEvent -> signal EV_RXCHAR when we have data to deliver
const wce = imp('WaitCommEvent');
if (wce) Interceptor.attach(wce, {
  onEnter(args) { this.h = args[0].toString(); this.mask = args[1]; },
  onLeave(retval) {
    if (!comHandles[this.h] || injectQueue.length === 0) return;
    try { this.mask.writeU32(1); } catch (e) {}   // EV_RXCHAR
    retval.replace(ptr(1));
  }
});

// ReadFile -> hand HGS the injected bytes
const read = imp('ReadFile');
if (read) Interceptor.attach(read, {
  onEnter(args) {
    this.h = args[0].toString(); this.buf = args[1];
    this.nToRead = args[2].toInt32(); this.lpRead = args[3];
  },
  onLeave(retval) {
    if (!comHandles[this.h] || injectQueue.length === 0) return;
    const n = Math.min(this.nToRead, injectQueue.length);
    const chunk = injectQueue.slice(0, n);
    try {
      this.buf.writeByteArray(chunk);
      if (this.lpRead && !this.lpRead.isNull()) this.lpRead.writeU32(n);
      retval.replace(ptr(1));
      injectQueue = injectQueue.slice(n);
      console.log(`[${ms()} ms] << injected ${n} byte(s), ${injectQueue.length} left`);
      send({ ev: 'delivered', n: n });
    } catch (e) { console.log('inject error: ' + e); }
  }
});

rpc.exports = {
  inject(hexstr) {           // queue a response (hex string) for HGS to "receive"
    const parts = hexstr.trim().split(/\s+/).filter(Boolean);
    injectQueue = injectQueue.concat(parts.map(function (h) { return parseInt(h, 16); }));
    return injectQueue.length;
  },
  clear() { injectQueue = []; return 0; },
  pending() { return injectQueue.length; }
};

console.log('hgs_oracle active');
