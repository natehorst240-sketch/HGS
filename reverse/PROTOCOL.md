# HGS ⇄ DAU serial download protocol (fully reverse-engineered)

Captured live from a real A109 download on 2026-07-09 (Frida tap on HGS,
`reverse/frida/hgs_capture2.py`) and cross-checked: the reassembled wire bytes
equal the `.HG` file byte-for-byte (589,237 captured vs 590,117 in a full file
— the 880-byte difference is exactly the first 8 records that streamed before
the capture attached).

## Link settings
9600 baud, 8 data bits, no parity, 1 stop bit (9600,n,8,1). Straight serial
over the DAU maintenance DB9 (channel A or B — identical).

## Roles
- **Downloader** (the PC / HGS — and what the stick emulates): master. Sends a
  request, then acknowledges each record.
- **DAU**: streams the stored records one at a time, stop-and-wait.

## Messages
All control messages are **25-byte space-padded ASCII** (no checksum, no
framing bytes):
- Request:  `DOWNLOAD LOGS` / `DOWNLOAD CUMULATIVE` / `DOWNLOAD STATUS`
- Ack:      `TRANSMISSION OK`
- (Nak, unused in a clean run: `RETRANSMIT`)

## Flow (stop-and-wait, DAU-paced)
1. Downloader → `DOWNLOAD LOGS␠␠…` (25 bytes).
2. DAU → one **record** (a complete `.HG` record; see sizes below), then
   **pauses**, waiting for an ack.
3. Downloader → `TRANSMISSION OK␠␠…` (25 bytes).
4. DAU → next record. Repeat 2–4.
5. After the last record (Power Assurance block) and its ack, the DAU sends
   nothing further; the transfer is complete.

The DAU will not send record N+1 until record N is acked, so **record
boundaries = the idle gap** after each record. A receiver reads bytes until the
line goes idle (DAU waiting), acks, and the next record starts. No length
header and no checksum are needed on the wire — framing is by the pause.

## Record sizes seen (each is exactly one `.HG` record)
| bytes | record type | count in this download |
|-------|-------------|------------------------|
| 110   | exceedance-parameter record | 25 (+8 sent before capture) |
| 92    | discrete-event counter record | 243 |
| 228   | Cumulative Log block | 1 |
| 2817  | Time History frame (`TIME HISTORY #nnn`) | 200 |
| 503   | Power Assurance Log block | 1 |

Concatenating all records in order reproduces the `.HG` file, which the
existing `hgs/hg6.py` parser already decodes (all fields BCD; see `FORMAT.md`).

## Implication for the download stick
The stick plays the downloader:
1. Send `DOWNLOAD LOGS` (25-byte padded).
2. Loop: read a record (bytes until ~50 ms idle) → send `TRANSMISSION OK`
   (25-byte padded) → append the record to the output file.
3. End when no new record arrives within a few seconds after an ack.
4. Save the concatenated records as `SSSSS_YYMMDD_A1.HG6`.

No frame parsing is required on the stick to *download* — it just relays and
acks whole records. Parsing/display happens later with `hgs/hg6.py`.
