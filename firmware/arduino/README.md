# HGS Download Stick — Arduino firmware

Target: **Waveshare ESP32-S3-Touch-LCD-1.9 (SKU 30939)** + a Pico-format carrier
carrying a MAX3232 and a DE9.

Arduino was chosen over CircuitPython/MicroPython for one reason: it is the only
framework that can expose the **SDIO** TF slot to a PC as a USB drive.
CircuitPython's MSC only publishes its internal flash and cannot reach an SDIO
card at all (the socket has no chip select); MicroPython has no MSC.

**A TF card is optional.** `storage::begin()` tries the card first and, when no
card mounts, falls back to the 9.9 MB `ffat` partition in internal flash
(mounted through the IDF wear-levelling layer, exported to the PC as 4096-byte
USB blocks). Everything above the storage module goes through `storage::fs()`
and never knows which backend is underneath. Verified 2026-09-16 with no card:
Windows mounts a 10 MB FAT volume, writes to it, and `/syslog.txt` reports
`storage=flash`.

## Layout

| File | Role |
|------|------|
| `hgs_stick/hgs_stick.ino` | mode flow, download orchestration, deep sleep |
| `hgs_stick/config.h` | **pin map — single source of truth** |
| `hgs_stick/dau_protocol.{h,cpp}` | the wire protocol, Arduino-free so it can be tested on a PC |
| `hgs_stick/cst816.{h,cpp}` | touch driver (tap = start, hold = abort) |
| `hgs_stick/ui.{h,cpp}` | HGS-styled screen, 320×170 landscape |
| `hgs_stick/storage.{h,cpp}` | SDMMC or internal-flash mount, USB MSC, HGS filename from BCD |
| `hgs_stick/stick_log.{h,cpp}` | persistent `/syslog.txt`, boot counter, reset-reason forensics |
| `test/replay_test.cpp` | **the port gate — run this first** |

Fixed buffers and `char[]` are used throughout instead of `std::string`/`std::vector`.
That is deliberate: a download runs for 10–14 minutes and must not depend on heap
behaviour partway through. The protocol reads into one static 4 KB buffer.

## Run the port gate before you flash anything

The Python implementation was validated byte-for-byte against a real A109
download. This test holds the C++ port to the same bar by replaying
`firmware/wire_test.HG6` (589,237 bytes, captured live) through a stop-and-wait
DAU emulator and requiring byte-identical output.

```bash
cd firmware/arduino/test && PATH="/c/Users/nateh/tools/w64devkit/bin:$PATH" make
```

**Status: PASS — 33/33, verified 2026-08-20** with GCC 14.1.0, clean under
`-Wall -Wextra`. The headline assertion is that the port reassembles the real
capture byte-for-byte: 589,237 bytes across 789 records, every one acked.

`make asan` does not work with w64devkit — mingw-w64 ships no `libasan`/`libubsan`.
Run that target under WSL or clang if you want the sanitizer pass; it has not
been done.

## Build

**Verified 2026-08-20: compiles clean, no errors, no warnings.**
Sketch 546,048 bytes (17% of the 3 MB app partition); globals 74,504 bytes (22%
of RAM, 253 KB left for locals).

### Command line (reproducible)

```bash
arduino-cli compile --fqbn "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,USBMode=default,CDCOnBoot=cdc,PartitionScheme=app3M_fat9M_16MB" firmware/arduino/hgs_stick
```

Upload adds `--port COMn -u`.

### GUI equivalent

1. **Board:** ESP32S3 Dev Module
2. **PSRAM:** OPI PSRAM — the R8 has *octal* PSRAM, and this is also why
   IO33–37 are unavailable
3. **Flash Size:** 16 MB, **Partition Scheme:** `16M Flash (3MB APP/9.9MB FATFS)`
4. **USB Mode:** `USB-OTG (TinyUSB)` — **mandatory.** The default
   `Hardware CDC and JTAG` has no TinyUSB stack, so `USBMSC` compiles but the
   drive never enumerates
5. **USB CDC On Boot:** Enabled (so `Serial` reaches the PC for debug)

### Toolchain versions this was verified against

| Component | Version |
|---|---|
| `esp32:esp32` core | 3.3.11 |
| GFX Library for Arduino | 1.6.7 |
| arduino-cli | 1.5.1 |
| host compiler (port gate) | GCC 14.1.0 (w64devkit 1.23.0) |

Core 3.x matters: it selects the `esp_task_wdt_reconfigure()` branch of the
version guard in `hgs_stick.ino`. On core 2.x the `esp_task_wdt_init()` branch
is used instead.

## Wiring

| Board | Carrier | DE9 |
|---|---|---|
| IO16 (header pin 15) | MAX3232 TTL TX-in | → DAU RXD |
| IO18 (header pin 17) | MAX3232 TTL RX-out | ← DAU TXD |
| 3V3 (header pin 36) | VCC — **3V3 only**, the S3 is not 5 V tolerant | |
| GND (header pin 18) | GND | → SIGNAL RETURN |
| IO15 (header pin 14) | FUNCTION SEL, if needed | → J101-E |

Do **not** use header pins 1/2 (IO43/IO44 = UART0). The ROM bootloader prints
its 115200 banner there at every power-up and it would go straight into the DAU.
A stock Pico RS232 HAT uses exactly those pins — rework it or build your own.

## Verification status

### Settled by the clean compile

Every API below exists with the signature used, against core 3.3.11 / GFX 1.6.7.
These were open questions before the build and are now closed:
`SD_MMC.readRAW/writeRAW/numSectors`, the `USBMSC` class and `mediaPresent()`,
the `Arduino_ESP32SPI` / `Arduino_ST7789` constructor arity,
`analogReadMilliVolts()`, `gpio_hold_en()`, and
`esp_sleep_enable_ext1_wakeup()` with `ESP_EXT1_WAKEUP_ANY_LOW`.

### Still unproven — behaviour, not signatures

A clean compile says these functions exist. It says nothing about whether they
do what this firmware assumes. Only a board can settle these.

1. **USB detach/re-attach around a download** (see *Host/MCU arbitration* below).
   Confirm on all three host OSes that the drive disappears when a download
   starts and comes back with fresh contents afterwards. **Highest-risk item —
   this is where data loss would come from.**
2. **The TF slot mounts 1-bit SDIO** on CLK 41 / CMD 39 / D0 40, and the PC then
   sees a drive. (Still unproven - no card has been tried. The internal-flash
   path *is* proven; see above.)
3. **ST7789V2 offsets** — `LCD_COL_OFFSET = 35` for a 170-wide panel. If the
   image is shifted, this is why. Rotation 1 may also need the offsets swapped.
4. ~~**CST816 answers at 0x15** on IO47/48.~~ **Proven 2026-09-16:** the boot
   log shows `touch id=0xB6` (a CST816 variant; the ID is logged, not asserted).
   Tap/hold behaviour on the assembled unit is still to be exercised.
5. **Deep-sleep wake actually works.** `gpio_hold_en` on IO17/IO14/IO16 before
   sleeping is not optional — without it the CST816's active-low reset can drop
   as the pads are released, the controller never pulses INT, and the stick
   never wakes.
6. **Battery divider ×3** — matches Waveshare's `adc_bsp.c`. Spot-check against a
   multimeter once.
7. **FUNCTION SEL (J101-E) is still unresolved.** `USE_FUNCTION_SEL` is `false`
   and the pin is left high-Z. The cable is a standard DTE port, so FUNCTION SEL
   is an RS-232 level carried on DTR (pin 4) or RTS (pin 7) — driven by the
   carrier's MAX3232 spare driver, not by a GPIO. Ring out the cable to confirm
   which pin before enabling it.

### Settled on the bench (2026-09-16)

- **Backlight is active-LOW.** The first build drove IO14 HIGH for "on" and the
  panel stayed dark until RST was held (pin floats -> backlight comes on,
  revealing a correctly drawn frame). `LCD_BL_ACTIVE_LOW` in `config.h` now
  inverts both writes in `ui.cpp`.
- **Flashing after the first time:** the TinyUSB CDC port (COM4 here) does not
  answer esptool's reset sequence. A failed attempt on it drops the ROM
  bootloader onto its own port (COM3 here); upload there. Or hold BOOT, tap RST.

## Host/MCU arbitration

A FAT volume must never be written by the MCU while a host has it mounted. The
first cut of this used `USBMSC::mediaPresent(false)`. **That is not sufficient**,
and the source says why:

```cpp
void USBMSC::mediaPresent(bool media_present) {
  msc_luns[_lun].media_present = media_present;   // one bool, nothing else
}
```

It sets a flag that `TEST UNIT READY` reports and that makes `capacity`/`read10`
return zero. It never calls `tud_msc_set_sense()`. So the host is told the medium
went *away*, but is never told it **changed** — there is no SCSI unit attention
(sense 0x06 / ASC 0x28, `MEDIUM MAY HAVE CHANGED`), which is the condition that
makes an OS discard a cached FAT. Whether it re-reads is then host discretion:
Linux usually does, Windows is inconsistent.

There is no prior art for using it this way. Espressif's own `USBMSC.ino` is a
RAM disk that sets `mediaPresent(true)` once and never toggles it, and the
USBMSC+SD combination has known rough edges
([#5692](https://github.com/espressif/arduino-esp32/issues/5692),
[#7106](https://github.com/espressif/arduino-esp32/issues/7106)). The strongest
signal is negative: CircuitPython hit this exact problem and refused to solve it
dynamically — `storage.remount()` picks an owner at boot and never changes it.

So `setHostAccess()` **detaches from the USB bus** instead:

| | |
|---|---|
| download starts | `mediaPresent(false)` then `tud_disconnect()` |
| download ends | `mediaPresent(true)`, unit attention 0x06/0x28, `tud_connect()` |

The host sees a device removal and unmounts; on re-attach it enumerates from
scratch, which forces a complete fresh read. That is the software equivalent of
unplugging the stick — a defined USB operation rather than a hope about caching.
On battery at the aircraft, with no host attached, both calls are no-ops.

Pure boot-time ownership (the CircuitPython `boot.py` model) was the first plan
but is **not implementable here**: the Arduino core exposes no VBUS or
`tud_mounted()` API, and MSC has to be registered before `USB.begin()`, so there
is no reliable way to know whether a host is present before committing to a mode.
Detach/re-attach achieves the same invariant without needing to know.

## Download-only guarantee

The stick must never write to the aircraft beyond the protocol's own request and
ack bytes. This is enforced structurally, not by convention:

- `Downloader::send()` is the only function that transmits on the DAU line, and
  it refuses anything outside four read-side strings — the three `DOWNLOAD *`
  requests and `TRANSMISSION OK`
- `download()` rejects a non-whitelisted command before a byte leaves, returning
  `Status::Refused`
- no erase, clear, set, reset or write command exists anywhere in the codebase
- the TX pin is parked at UART idle in the first two statements of `setup()` and
  latched with `gpio_hold_en` across deep sleep, so a floating MAX3232 input
  never puts an undefined level on the aircraft's receive line

The port gate proves it: across a full replay, **791 messages transmitted, all
whitelisted, exactly one non-ack** (the initial request). Write-style commands
(`ERASE LOGS`, `CLEAR FAULTS`, `RESET DAU`, …) are refused with zero bytes sent.

The one deliberate exception worth knowing: after silence, one extra unsolicited
`TRANSMISSION OK` is sent to cover a missed ack. It is protocol-legal and
inherited from the validated Python implementation.

## Behaviour

- **Tap** the screen to start; **hold ~1.5 s** to abort.
- Downloads land as `/DOWNLOAD_NN.HG6.PART`, renamed on success to the HGS-style
  `SSSSS_YYMMDD_An.HG6` parsed from the Cumulative Log block.
- Failed downloads are **kept** as `.PART` for post-mortem. Empty ones are removed.
- Line noise on a floating RX is rejected before anything is written.
- `/syslog.txt` on the card records every session.
- Idle 2 min on the ready screen → deep sleep. **Wake by holding the screen
  ~1.5 s** (`WAKE_HOLD_MS`); a brief touch wakes the chip but it goes straight
  back to sleep without lighting up, so pocket contact does not start
  downloads. Set `IDLE_SLEEP_MS = 0` while developing over USB.
