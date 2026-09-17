# Reverse-engineering the HGS serial protocol from Hgs_cpp.exe

Goal: recover the DAU download wire protocol (request frames, framing,
checksum, ACK/retry) without a serial capture, by disassembling the binary.

Tooling: capstone + pefile (in `reverse/`, scripts `hdis.py`).
Binary: 32-bit MFC 4.2, statically linked MFC, ImageBase 0x400000.

## What was recovered (high confidence)

**Two-channel architecture.** The download manager handles two ports in
parallel, displayed as `COM_1:`/`COM_2:` — these are DAU channels A and B.
Confirms maintenance's statement that either DB9 works; the app literally
runs both channels through one state machine.

**The full download state machine** (message table at .data 0x8ad13c,
indexed by an integer state per port):

| idx | state string |
|-----|--------------|
| 0 | - NOT AVAILABLE - |
| 1 | STAND BY READY |
| 2 | DOWNLOADER TO START |
| 3 | REQUEST FRAME MSG SENT |
| 4 | DESCRIPTION BYTES RECEIVED |
| 5 | WAIT FOR FRAME COMPLETION |
| 6 | FRAME BYTES RECEIVED |
| 7 | FRAME CHECKED OK |
| 8 | RETRYING MANAGER |
| 9 | RETRYING DOWNLOADER TO START |
| 10 | DOWNLOAD FAILED |
| 11 | COMPLETED WITH ABORT |
| 12 | COMPLETED WITH SUCCESS WRITING FILE |
| 13 | COMPLETED WITH SUCCESS |

An identical upload table exists at 0x8ad104 (UPLOADER TO START, ...).

**Object layout of the download manager** (`this` = dialog+…):
- `this+0x214` : per-port state sub-object
    - `+0x30 / +0x34` : current state, port 0 / port 1  (getter 0x429f10,
      setter 0x429f20 — setter also writes a shadow copy at +0x38/+0x3c)
    - `+0x178 / +0x17c` : per-port retry flag (setter 0x429f60)
- `this+0x3a4` : the comm/frame object (reset via 0x42d7d0/0x42d790)
- `this+0x188` : progress/worker object
- `this+0x204` : "which ports active" selector (0=none/1/2)

**I/O is OLE-marshalled, not raw.** The exe talks to MSCOMM32.OCX through
COleDispatchDriver (IDispatch::Invoke). Send = set MSComm.Output with a
binary BSTR (built via SysAllocStringByteLen at 0x4642f6); receive = read
MSComm.Input VARIANT in the OnComm event handler. No `WriteFile`/`ReadFile`
on the port — all bytes pass through the OCX.

## The wall (why the exact wire bytes aren't in the exe)

1. **No in-exe checksum.** A full-.text scan for byte-wise `xor/add/adc
   reg,[mem]` accumulation (the shape of every simple LRC/sum checksum)
   returns *nothing*. So "FRAME CHECKED OK" is either a structure/length
   validation, a 16-bit word sum, or an integrity check performed inside
   the OCX — not a liftable byte-loop in the application.
2. **Event-driven receive.** Frame parsing runs in the MFC ActiveX event
   sink (OnComm), reached by dynamic dispatch, not a static call chain,
   so the parser can't be xref'd from the request site.
3. **Frame contents are data-driven.** The request payload is assembled
   from per-log descriptors (record sizes 0x4650 = 18000 appears as a
   bound — matches the time-history frame math), not hard-coded magic
   bytes that would reveal the format by inspection.

## BREAKTHROUGH — request format captured live (2026-07-09)

Ran HGS on the desktop against a Prolific USB-serial adapter (COM1) with a
Frida hook (reverse/frida/) tapping ReadFile/WriteFile below the OCX. On
"IDS Downloading -> Download Logs", HGS transmitted:

    OPEN \\.\COM1
    >> "DOWNLOAD LOGS            "   (25 bytes: ASCII, space-padded)
    >> (same, retransmitted every ~5.1 s while no reply)

So the **request protocol is 25-byte space-padded ASCII commands** — no
checksum, no STX/ETX. This is why the binary's string table is full of
25-char commands; they ARE the wire messages. Known/likely commands (from
strings, to confirm by capture): DOWNLOAD LOGS, DOWNLOAD CUMULATIVE,
DOWNLOAD STATUS, STAND BY READY, TRANSMISSION OK, RETRANSMIT, READY TO UPLOAD,
UPLOAD DATA, COPY_FILES, DELETE_FILES, TRANSFER_FILES.

Retransmit timeout ≈ 5 s. Confirmed commands so far (each 25-byte, space-pad):
`DOWNLOAD LOGS`, `DOWNLOAD CUMULATIVE`.

### Receive path (how HGS listens for the reply)
Captured live: after sending the command HGS does
    WaitCommEvent (overlapped, pending)
    ClearCommError -> reads COMSTAT.cbInQue  (bytes waiting; stays 0 here)
and retransmits after ~5 s of cbInQue==0. So the injection oracle is:
hook ClearCommError to report cbInQue = len(reply), hook ReadFile on the COM
handle to hand HGS our crafted reply bytes, and (if needed) complete
WaitCommEvent with EV_RXCHAR. Then watch HGS advance
REQUEST FRAME MSG SENT -> DESCRIPTION BYTES RECEIVED -> FRAME CHECKED OK,
sweeping response framing until it accepts. Response payload source = the
already-decoded .HG6. This reverses the response format with no aircraft.

### Oracle result (2026-07-09): injection works; HGS ignores malformed data
Built hgs_oracle.js (inject via ClearCommError/ReadFile/WaitCommEvent) +
oracle_driver.py. Confirmed: HGS's ReadFile received our injected 64 bytes
("delivered 64 bytes"). But HGS did NOT react to garbage — no TRANSMISSION OK,
no RETRANSMIT; it just timed out and failed. So HGS validates response
structure before acknowledging; blind probing won't reveal the format.

### Outgoing-message structure (from disasm 0x429f80 / 0x42a0e0)
HGS builds each transmit as:  status_string(25) + [command(25) if flag] +
formatted_record_number. Tables: 0x8ad874 = "TRANSMISSION OK" (ACK) states,
0x8ad850 = "RETRANSMIT" (NAK) states, 0x8ad894 = command table
(DOWNLOAD LOGS / CUMULATIVE / STATUS). So the protocol is TEXT-based:
25-byte status/command tokens plus record numbers. The DAU's response
(the "description" then frames) almost certainly follows the same text shape.

### Remaining work — the response/description format
Need HGS's receive parser (the MSComm OnComm handler that reads the reply and
sets state DESCRIPTION BYTES RECEIVED -> FRAME CHECKED OK). It's event-driven,
not yet located in the disassembly. Once known, inject a valid description via
the (working) oracle and HGS will ACK, confirming the format. This is the last
piece before dau_protocol.py can be completed.

## Assessment (pre-capture, now superseded for the request side)

Static analysis recovered the protocol's *structure* (handshake states,
channel model, retry model, object layout) but not the *byte encoding*
(frame delimiters, request opcodes, checksum). Those live in the
OLE/OCX boundary and would require either:
- **A serial capture** of one real download (still the fastest, surest path
  — one 10-minute session yields the exact bytes), or
- **Dynamic analysis**: run the exe under a debugger / on a serial-port
  emulator and breakpoint the MSComm Input/Output invokes to log payloads.

The stick firmware's `dau_protocol.py` state machine already matches the
recovered state model; only the byte-level `TODO(protocol)` fills remain,
and they need one of the two methods above.
