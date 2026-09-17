#include "stick_log.h"
#include "storage.h"

#include <Arduino.h>
#include <FS.h>
#include <Preferences.h>
#include <esp_system.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

namespace stick_log {

static bool     writable_ = true;
static uint16_t bootNo_   = 0;
static esp_reset_reason_t reason_ = ESP_RST_UNKNOWN;

static const char* reasonName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:   return "POWERON";
    case ESP_RST_EXT:       return "EXT";
    case ESP_RST_SW:        return "SW";
    case ESP_RST_PANIC:     return "PANIC";
    case ESP_RST_INT_WDT:   return "INT_WDT";
    case ESP_RST_TASK_WDT:  return "TASK_WDT";
    case ESP_RST_WDT:       return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:  return "BROWNOUT";
    case ESP_RST_SDIO:      return "SDIO";
    default:                return "UNKNOWN";
  }
}

bool priorSessionFaulted() {
  return reason_ == ESP_RST_PANIC || reason_ == ESP_RST_INT_WDT ||
         reason_ == ESP_RST_TASK_WDT || reason_ == ESP_RST_WDT ||
         reason_ == ESP_RST_BROWNOUT;
}

// Persistent boot counter. NVS lives in the internal flash, so it survives a
// flat battery and a missing card alike - the CircuitPython original used
// microcontroller.nvm for the same reason.
static uint16_t bumpBootCount() {
  Preferences prefs;
  if (!prefs.begin("hgs", false)) return 0;
  uint16_t n = prefs.getUShort("boot", 0);
  n = (uint16_t)(n + 1);
  prefs.putUShort("boot", n);
  prefs.end();
  return n;
}

static uint16_t readBootCount() {
  Preferences prefs;
  if (!prefs.begin("hgs", true)) return 0;
  const uint16_t n = prefs.getUShort("boot", 0);
  prefs.end();
  return n;
}

static void rotate() {
  File f = storage::fs().open(PATH, FILE_READ);
  if (!f) return;
  const uint32_t sz = f.size();
  f.close();
  if (sz <= MAX_BYTES) return;
  storage::fs().remove(PATH_OLD);              // best effort; may not exist
  storage::fs().rename(PATH, PATH_OLD);
}

void begin() {
  writable_ = true;
  reason_ = esp_reset_reason();

  const bool fromSleep = (reason_ == ESP_RST_DEEPSLEEP);
  bootNo_ = fromSleep ? readBootCount() : bumpBootCount();

  rotate();

  if (fromSleep) {
    // Normal wake on touch - keep it to one short line.
    linef("WAKE (boot #%u)", (unsigned)bootNo_);
    return;
  }

  linef("BOOT #%u reset_reason=%s", (unsigned)bootNo_, reasonName(reason_));
  if (reason_ == ESP_RST_TASK_WDT || reason_ == ESP_RST_INT_WDT ||
      reason_ == ESP_RST_WDT) {
    line("WARNING: previous session hung and was auto-reset by the watchdog");
  } else if (reason_ == ESP_RST_PANIC) {
    line("WARNING: previous session crashed (panic)");
  } else if (reason_ == ESP_RST_BROWNOUT) {
    // On a battery tool this is the one that matters: it usually means a flat
    // or sagging cell, not a firmware bug.
    line("WARNING: previous session browned out - check the battery");
  }
}

bool ok() { return writable_; }

void line(const char* msg) {
  if (!writable_ || !msg) return;
  File f = storage::fs().open(PATH, FILE_APPEND);
  if (!f) { writable_ = false; return; }
  // No %f: newlib-nano builds drop float formatting, and this must never be
  // the thing that breaks logging.
  const uint32_t ms = millis();
  char ts[24];
  snprintf(ts, sizeof(ts), "[%6lu.%01lus] ",
           (unsigned long)(ms / 1000), (unsigned long)((ms % 1000) / 100));
  if (f.print(ts) == 0 || f.println(msg) == 0) writable_ = false;
  f.close();
}

void linef(const char* fmt, ...) {
  char buf[192];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  line(buf);
}

void fault(const char* context, const char* detail) {
  linef("FAULT in %s: %s", context ? context : "?", detail ? detail : "");
}

size_t tail(char* out, size_t outLen, int lines) {
  if (!out || outLen == 0) return 0;
  out[0] = 0;
  File f = storage::fs().open(PATH, FILE_READ);
  if (!f) return 0;

  // The log is capped at 200 KB and we only ever want the last few lines, so
  // read a bounded window off the end rather than walking the whole file.
  const uint32_t sz = f.size();
  const uint32_t want = sz < 4096 ? sz : 4096;
  static char buf[4097];
  f.seek(sz - want);
  const size_t got = f.read(reinterpret_cast<uint8_t*>(buf), want);
  f.close();

  size_t end = got;
  while (end > 0 && (buf[end - 1] == '\n' || buf[end - 1] == '\r')) end--;
  buf[end] = 0;

  int found = 0;
  size_t start = 0;
  for (size_t i = end; i > 0; --i) {
    if (buf[i - 1] == '\n' && ++found == lines) { start = i; break; }
  }
  snprintf(out, outLen, "%s", buf + start);
  return strlen(out);
}

bool lastLine(char* out, size_t outLen) {
  return tail(out, outLen, 1) > 0;
}

uint16_t bootCount() { return bootNo_; }
const char* resetReason() { return reasonName(reason_); }

}  // namespace stick_log
