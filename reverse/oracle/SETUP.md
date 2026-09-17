# Reverse the protocol on this desktop — no aircraft needed

Idea: run HGS here and let it talk to a Python "DAU" instead of a real one.
HGS emits its request frames (Phase 1), then acts as an oracle that grades our
guessed response frames as "FRAME CHECKED OK" vs "RETRANSMIT" (Phase 2). We
already have the data payload (decoded from your .HG6), so HGS just has to tell
us the framing/checksum that wraps it.

Everything below is on your own Lenovo desktop. No IT, no aircraft.

## One-time setup: a virtual serial cable

HGS won't download without a COM port ("NO PORT PC"). This desktop has none,
so install a virtual null-modem pair:

1. Get **com0com** (free, open source). Use a signed build so Windows 11 loads
   the driver — the "com0com with signed driver" release (from the
   com0com project on SourceForge). Install it.
2. Open its "Setup Command Prompt" (installed with it) or the GUI. Make a pair;
   note the two names it creates, e.g. **COM3 <-> COM4**. If it names them
   `CNCA0/CNCB0`, rename to COM3/COM4 in the com0com GUI so HGS can see them.
   (These two ports are wired together: whatever HGS writes to COM3, my script
   reads on COM4, and vice-versa.)

## Point HGS at the port

In HGS: Tools -> Com Settings, set the port to **COM3** (the HGS half of the
pair), 9600, N, 8, 1. Make sure HGS mode is a normal download mode
(Tools -> Hgs Mode Settings), not view-only.

## Phase 1 — capture HGS's requests

1. In a terminal here:  `python capture_requests.py COM4`
2. In HGS, start a normal download (IDS -> Download Logs, or Download
   Cumulative — whichever).
3. HGS sends its request frames; the script prints and logs them to
   `hgs_requests.log`. HGS will retry a few times and fail ("DOWNLOAD FAILED")
   because nothing is really answering — that's expected.
4. Ctrl+C the script. Send me `hgs_requests.log` (or run
   `python ../frida/decode_capture.py hgs_requests.log`).

That log is the exact byte format the **stick** must send to the DAU.

## Phase 2 — make HGS confirm the response format (the oracle)

Once we know the request format from Phase 1, run `dau_emulator.py`: it answers
HGS's requests with candidate response frames wrapping the known payload, and
watches whether HGS advances to the next frame (accepted) or repeats its
request (rejected). We sweep framing/checksum options until HGS accepts —
at which point we've reverse-engineered the response format, and the emulator
*is* a working DAU that HGS downloads from cleanly.

I'll fill in `dau_emulator.py`'s framing from what Phase 1 shows; the skeleton
is already there so we can iterate quickly.

## What this gets us
- Phase 1  -> the request/handshake bytes the stick sends.
- Phase 2  -> the response framing/checksum the stick parses.
Together that's the whole protocol, validated by HGS itself, with zero aircraft
time. Then `firmware/dau_protocol.py` gets filled in and the stick is buildable.
