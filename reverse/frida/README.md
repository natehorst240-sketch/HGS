# No-capture protocol extraction (Frida)

Captures the HGS <-> DAU serial conversation from *inside* the running
`Hgs_cpp.exe`, tapping the Win32 comm API below the OLE/OCX layer. This needs
**no Wireshark, no USBPcap, no admin drivers** — just a userland Python tool —
which is the point if IT lockdown was the blocker.

What it still needs, like any method: **one real download session** with the
DAU on the machine that runs HGS. It reads bytes that are actually on the
wire; it can't invent a conversation that didn't happen.

## Steps (on the HGS laptop)

1. Install the tool (userland, no admin required in most setups):
   ```
   pip install frida-tools
   ```
2. Launch HGS *through* Frida with the hook attached, logging to a file:
   ```
   frida -f "C:\Program Files (x86)\HGS\Bin\Hgs_cpp.exe" -l hgs_sniff.js -o hgs_serial.log
   ```
   (If HGS is already the working install, adjust the path. If it must be
   started a particular way, instead run `frida -n Hgs_cpp.exe -l hgs_sniff.js
   -o hgs_serial.log` to attach to it after you start it normally.)
3. In HGS, do a **normal, complete download** — connect to the aircraft,
   run it, let it reach "COMPLETED WITH SUCCESS". If mx would also clear an
   exceedance or do anything else in the session, let that happen too; every
   exchange is useful.
4. Close HGS (or press Ctrl+C in the Frida window). You now have
   `hgs_serial.log`.

## Then

Send me `hgs_serial.log`. Or run the analyzer yourself first:
```
python decode_capture.py hgs_serial.log
```
It splits TX/RX, prints the frame-length/first-byte/last-byte structure, and
auto-detects the checksum (XOR/LRC, SUM8/16, CRC16-CCITT/MODBUS, either
endianness, allowing for header/terminator bytes). That report plus the raw
log is everything needed to finish `firmware/dau_protocol.py`.

## Notes / troubleshooting

- **Nothing logged / no "OPEN COMx" line?** HGS may open the port by a name
  the filter missed. Open `hgs_sniff.js` and the `isCom()` check; loosen it
  or tell me the COM number and I'll pin it.
- **RX shows up but looks empty:** MSComm may use a read style the overlapped
  hook doesn't catch. Send what you get — even the TX (request) side plus
  partial RX narrows the format a lot.
- **Frida can't attach:** try running the terminal "as administrator" once;
  attaching to a same-user process usually doesn't need it, but some
  endpoint-security setups do.
- This is read-only observation of a normal download — it doesn't change what
  HGS or the DAU do.
