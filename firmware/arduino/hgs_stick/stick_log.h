// Persistent diagnostic log for the HGS Download Stick.
//
// Port of firmware/stick_log.py. Appends one-line entries to /syslog.txt on the
// card, so the log is readable from any PC alongside the downloads. Timestamps
// are seconds-since-boot (the stick has no clock until it reads the DAU's);
// each power-on writes a header line so sessions are easy to tell apart.
//
// Changes from the CircuitPython original, both forced by this board:
//   - the boot counter lives in NVS (Preferences) rather than
//     microcontroller.nvm; same guarantee, survives power loss
//   - this build deep-sleeps between downloads, so every touch is technically a
//     cold boot. Wake-from-sleep writes a compact WAKE line and does NOT bump
//     the boot counter, otherwise a day on the bench would bury the log in
//     BOOT headers
//
// Writes are best-effort: if the card is missing or the append fails, logging
// silently no-ops rather than taking the tool down with it.
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace stick_log {

static const char* const PATH     = "/syslog.txt";
static const char* const PATH_OLD = "/syslog.old.txt";
static const uint32_t MAX_BYTES   = 200000;   // rotate beyond this

// Rotate if needed, bump the boot counter, write the session header. Call once
// after storage::begin().
void begin();

bool ok();                                    // false once a write has failed
void line(const char* msg);
void linef(const char* fmt, ...);

// One-line fault summary. C++ has no exception object to unpack, so the caller
// supplies the context and a short detail - same shape as the Python
// exception(exc, context).
void fault(const char* context, const char* detail);

// Last `lines` log lines, newline-separated, into out. Returns bytes written.
size_t tail(char* out, size_t outLen, int lines);
bool lastLine(char* out, size_t outLen);

uint16_t bootCount();
const char* resetReason();

// True when the previous session ended in a watchdog reset, a panic, or a
// brownout - i.e. something the maintainer should be told about on screen.
bool priorSessionFaulted();

}  // namespace stick_log
