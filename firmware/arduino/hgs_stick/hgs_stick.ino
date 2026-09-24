// HGS Download Stick - Arduino firmware for the Waveshare ESP32-S3-Touch-LCD-1.9.
//
// Plugs into the A109S/A109N DAU maintenance connector through a MAX3232 on the
// Pico-format carrier, downloads the logs on a screen tap, and stores the .HG6
// to the TF card. Plugged into any PC afterwards it enumerates as an ordinary
// USB flash drive - no drivers, no software.
//
// Hold the screen ~1.5 s during a download to abort.
//
// Libraries: Arduino_GFX (moononournation). Board: "ESP32S3 Dev Module",
// PSRAM enabled (OPI), USB Mode "USB-OTG (TinyUSB)", USB CDC On Boot enabled.
// See README.md.

#include <Arduino.h>
#include <esp_task_wdt.h>
#include <driver/gpio.h>
#include <esp_sleep.h>

#include "config.h"
#include "cst816.h"
#include "dau_protocol.h"
#include "stick_log.h"
#include "storage.h"
#include "ui.h"

#include <FS.h>

static Cst816 touch;

// --- protocol plumbing --------------------------------------------------------
// A short read timeout keeps the idle-gap framing responsive; the 4 KB driver
// buffer is what makes it safe to repaint the screen after acking a record
// (largest real record is 2817 bytes, so the DAU cannot outrun us mid-redraw).
class SerialIo : public dau::Io {
 public:
  size_t readBytes(uint8_t* dst, size_t maxLen) override {
    const int avail = Serial1.available();
    if (avail <= 0) return 0;
    size_t n = static_cast<size_t>(avail);
    if (n > maxLen) n = maxLen;
    return Serial1.readBytes(dst, n);
  }
  void writeBytes(const uint8_t* src, size_t len) override {
    Serial1.write(src, len);
    Serial1.flush();
  }
  uint32_t nowMs() override { return millis(); }
};

class FileSink : public dau::Sink {
 public:
  bool open(const char* path) {
    file_ = storage::fs().open(path, FILE_WRITE);
    return (bool)file_;
  }
  bool write(const uint8_t* data, size_t len) override {
    if (!file_ || len == 0) return (bool)file_;
    return file_.write(data, len) == len;
  }
  void close() { if (file_) { file_.flush(); file_.close(); } }

 private:
  File file_;
};

// --- battery ------------------------------------------------------------------
// ADC1_CH3 on IO4 with a x3 divider, confirmed against Waveshare's adc_bsp.c.
// analogReadMilliVolts() uses the eFuse calibration curve, which is the
// accurate path - the naive raw*3.3/4096 is what the CircuitPython build was
// stuck with.
static float batteryVolts() {
  const uint32_t mv = analogReadMilliVolts(PIN_BAT_ADC);
  return (mv / 1000.0f) * BAT_DIVIDER;
}

static int batteryPct() {
  const float v = batteryVolts();
  if (v < 2.5f) return -1;            // no battery / USB-only: "unknown"
  int pct = (int)((v - 3.3f) / (4.2f - 3.3f) * 100.0f);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

// Charging indication. The board's charger has no status line we can read, so
// this is inferred: a USB host is attached (TinyUSB reports the device as
// mounted - the Arduino wrapper does not expose this, hence the extern) and
// the cell is below the charger's 4.2 V float, so current must be flowing.
// At or above the float voltage it reads as full. A charge-only USB source
// with no data lines enumerates nothing, so it shows as plain "batt".
extern "C" bool tud_mounted(void);
static const float BAT_FULL_VOLTS = 4.15f;

// Fills `out` with "chg 85%", "full", "batt 85%" or "batt ?".
static void powerLabel(char* out, size_t outLen) {
  const int pct = batteryPct();
  const bool usb = tud_mounted();
  if (pct < 0)           snprintf(out, outLen, usb ? "usb, no batt" : "batt ?");
  else if (!usb)         snprintf(out, outLen, "batt %d%%", pct);
  else if (batteryVolts() >= BAT_FULL_VOLTS) snprintf(out, outLen, "full");
  else                   snprintf(out, outLen, "chg %d%%", pct);
}

// --- duration calibration -----------------------------------------------------
// Records are hundreds of tiny frames then big time-history ones, so bytes map
// non-linearly to time. Elapsed-vs-last-run gives an honest countdown.
static const uint32_t DEFAULT_SECONDS = 840;   // ~14 min until learned

static uint32_t loadCal() {
  File f = storage::fs().open("/calibration.txt", FILE_READ);
  if (!f) return DEFAULT_SECONDS;
  const uint32_t v = (uint32_t)f.parseInt();
  f.close();
  return v < 30 ? DEFAULT_SECONDS : v;
}

static void saveCal(uint32_t seconds) {
  File f = storage::fs().open("/calibration.txt", FILE_WRITE);
  if (!f) return;
  f.print(seconds);
  f.close();
}

// --- deep sleep ---------------------------------------------------------------
static void goToSleep(bool logIt) {
  if (logIt) stick_log::line("idle -> deep sleep");
  pinMode(PIN_LCD_BL, OUTPUT);
  ui::backlight(false);
  // Hold the pins that must not float while asleep. Without this the CST816's
  // active-low reset can drop as the pads are released, the controller never
  // pulses INT, and the stick never wakes - it just looks dead.
  // Park the DAU transmit line at idle and latch it. Without this the pad is
  // released on entry to sleep and the MAX3232 input floats - if the stick is
  // still plugged into the aircraft while it sleeps, that is an undefined level
  // on the DAU's receive line for as long as it sits there.
  Serial1.flush();
  Serial1.end();
  pinMode(PIN_DAU_TX, OUTPUT);
  digitalWrite(PIN_DAU_TX, HIGH);
  gpio_hold_en((gpio_num_t)PIN_DAU_TX);

  gpio_hold_en((gpio_num_t)PIN_TP_RST);
  gpio_hold_en((gpio_num_t)PIN_LCD_BL);
  gpio_deep_sleep_hold_en();
#ifdef ESP_EXT1_WAKEUP_ANY_LOW
  esp_sleep_enable_ext1_wakeup(1ULL << PIN_TP_INT, ESP_EXT1_WAKEUP_ANY_LOW);
#else
  esp_sleep_enable_ext1_wakeup(1ULL << PIN_TP_INT, ESP_EXT1_WAKEUP_ALL_LOW);
#endif
  esp_deep_sleep_start();               // wakes as a cold boot -> setup() again
}

static void enterSleep() { goToSleep(true); }

// Wake gate. Runs before the screen lights or storage mounts, so a rejected
// touch costs ~1 s of boot and nothing else - no log line, no USB enumeration,
// no flash write. Returns only if the panel was held for WAKE_HOLD_MS.
static void requireWakeHold() {
  if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_EXT1) return;   // power-on / reset: no gate
  const uint32_t t0 = millis();
  while (millis() - t0 < WAKE_HOLD_MS) {
    if (!touch.touched()) goToSleep(false);   // does not return
    delay(20);
  }
  // Held long enough. Swallow the release so this press cannot double as the
  // ready screen's "tap to start".
  touch.waitRelease();
}

static bool waitTouchOrSleep() {
  if (IDLE_SLEEP_MS == 0) {
    touch.waitTouch();
  } else if (!touch.waitTouch(IDLE_SLEEP_MS)) {
    enterSleep();                       // does not return
  }
  touch.waitRelease();
  return true;
}

// --- watchdog -----------------------------------------------------------------
static void watchdogStart() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms = WATCHDOG_S * 1000;
  cfg.idle_core_mask = 0;
  cfg.trigger_panic = true;
  esp_task_wdt_reconfigure(&cfg);
#else
  esp_task_wdt_init(WATCHDOG_S, true);
#endif
  esp_task_wdt_add(NULL);
}

static void watchdogStop() { esp_task_wdt_delete(NULL); }

// --- the download -------------------------------------------------------------
static void runDownload() {
  const int batt = batteryPct();
  char msg[96];
  snprintf(msg, sizeof(msg), "download requested batt=%d%% free=%luKB",
           batt, (unsigned long)storage::freeKb());
  stick_log::line(msg);

  if (batt >= 0 && batt < LOW_BATT_PCT) {
    char l0[32];
    snprintf(l0, sizeof(l0), "LOW BATTERY  %d%%", batt);
    ui::screen(l0, "Charge before use", "", "TAP=override wait=cancel",
               0, ui::BLACK, ui::RED);
    if (!touch.waitTouch(10000)) {
      stick_log::line("low-battery: cancelled");
      return;
    }
    touch.waitRelease();
  }

  if (storage::freeKb() < 1024) {
    ui::screen("CARD FULL", "Offload on a PC first", "", "", 0, ui::BLACK, ui::RED);
    stick_log::line("blocked: card full");
    delay(6000);
    return;
  }

  // Take the volume away from the host for the duration - the MCU and the PC
  // must never both hold this filesystem writable.
  storage::setHostAccess(false);

  char part[48];
  storage::nextPartName(part, sizeof(part));
  snprintf(msg, sizeof(msg), "download start -> %s", part);
  stick_log::line(msg);

  FileSink sink;
  if (!sink.open(part)) {
    stick_log::fault("storage", "cannot create the .PART file");
    ui::screen("STORAGE ERROR", "Cannot create file", "", "Check the card",
               0, ui::BLACK, ui::RED);
    storage::setHostAccess(true);
    return;
  }

  SerialIo io;
  dau::Downloader dl(io, sink);

  const uint32_t t0 = millis();
  const uint32_t estSecs = loadCal();
  static char phase[40];
  snprintf(phase, sizeof(phase), "REQUEST FRAME MSG SENT");

  touch.holdBegin(ABORT_HOLD_MS);
  dl.onAbortCheck([]() { return touch.holdTripped(); });
  dl.onValidateFirst(dau::looksLikeHgs);
  dl.onStatus([](const char* s) {
    esp_task_wdt_reset();
    snprintf(phase, sizeof(phase), "%s", s);
  });
  dl.onProgress([&](size_t records, size_t bytes) {
    esp_task_wdt_reset();
    const uint32_t el = (millis() - t0) / 1000;
    int pct = estSecs ? (int)(el * 100 / estSecs) : 0;
    if (pct > 99) pct = 99;
    char a[28], b[28], c[28], d[28];
    snprintf(a, sizeof(a), "COM_1: DOWNLOADING");
    snprintf(b, sizeof(b), "%.20s", phase);
    snprintf(c, sizeof(c), "%u KB   frame %u",
             (unsigned)(bytes / 1024), (unsigned)records);
    const uint32_t eta = estSecs > el ? estSecs - el : 0;
    snprintf(d, sizeof(d), "%lu:%02lu  ETA %lu:%02lu",
             (unsigned long)el / 60, (unsigned long)el % 60,
             (unsigned long)eta / 60, (unsigned long)eta % 60);
    ui::panel(a, b, c, d);
    ui::bar(pct);
  });

  ui::screen("COM_1: DOWNLOADING", "REQUEST FRAME MSG SENT", "", "",
             "hold screen = ABORT", ui::RED);
  ui::bar(0);

  watchdogStart();
  const dau::Result r = dl.download(dau::CMD_DOWNLOAD_LOGS);
  watchdogStop();
  sink.close();

  const uint32_t el = (millis() - t0) / 1000;

  // Nothing usable arrived (aborted before the first byte, no response, line
  // noise): drop the empty .PART rather than litter the volume. Anything with
  // real bytes in it is kept for post-mortem, whatever the outcome.
  const bool empty = (storage::fileSize(part) == 0);
  if (empty) storage::removeFile(part);

  if (r.status == dau::Status::Ok && r.bytes >= DOWNLOAD_MIN_BYTES) {
    ui::bar(100);
    saveCal(el);
    char finalName[48];
    if (!storage::finalise(part, finalName, sizeof(finalName))) {
      snprintf(finalName, sizeof(finalName), "%s", part);
    }
    snprintf(msg, sizeof(msg), "download OK %u bytes in %lus -> %s",
             (unsigned)r.bytes, (unsigned long)el, finalName);
    stick_log::line(msg);
    char l1[28], l2[28];
    snprintf(l1, sizeof(l1), "%u KB in %lu:%02lu", (unsigned)(r.bytes / 1024),
             (unsigned long)el / 60, (unsigned long)el % 60);
    snprintf(l2, sizeof(l2), "%.24s", finalName + 1);
    ui::screen("COMPLETED WITH SUCCESS", l1, l2, "Tap for another",
               0, ui::BLACK, ui::GREEN);
  } else if (r.status == dau::Status::Ok || r.bytes > 0) {
    char l1[28];
    snprintf(l1, sizeof(l1), "only %u bytes", (unsigned)r.bytes);
    snprintf(msg, sizeof(msg), "download SHORT (%u bytes) kept %s",
             (unsigned)r.bytes, part);
    stick_log::line(msg);
    ui::screen("SUSPECT DOWNLOAD", l1, "kept as .PART", "Retry",
               0, ui::BLACK, ui::AMBER);
  } else if (r.status == dau::Status::Aborted) {
    stick_log::line(empty ? "download ABORTED by user (nothing received)"
                          : "download ABORTED by user (partial kept)");
    ui::screen("COMPLETED WITH ABORT",
               empty ? "nothing received" : "partial kept as .PART", "",
               "Tap to retry", 0, ui::BLACK, ui::AMBER);
  } else {
    const bool noise = (r.status == dau::Status::Noise);
    stick_log::line(noise ? "download FAILED (line noise)"
                           : "download FAILED (no response)");
    ui::screen(noise ? "NO DATA RECEIVED" : "DOWNLOAD FAILED",
               noise ? "Line noise - reseat" : "Check cable / DAU pwr",
               noise ? "connector & retry" : "", "Tap to retry",
               0, ui::BLACK, ui::RED);
  }

  storage::setHostAccess(true);         // give the volume back to the PC
}

// --- setup / loop ---------------------------------------------------------------
void setup() {
  // FIRST, before anything else that can take time: park the DAU transmit line
  // at UART idle (mark = high). Between reset and Serial1.begin() this pin is
  // an undriven input, and a floating MAX3232 driver input puts an
  // indeterminate level on the aircraft's receive line - display init alone is
  // a ~100 ms window of that. Driving it high means the only thing the DAU ever
  // sees from us is a valid idle line.
  pinMode(PIN_DAU_TX, OUTPUT);
  digitalWrite(PIN_DAU_TX, HIGH);

  // Wake from deep sleep leaves the pads latched - release them before use.
  gpio_hold_dis((gpio_num_t)PIN_DAU_TX);
  gpio_hold_dis((gpio_num_t)PIN_TP_RST);
  gpio_hold_dis((gpio_num_t)PIN_LCD_BL);
  gpio_deep_sleep_hold_dis();

  Serial.begin(115200);                 // USB CDC, debug only

  // Touch first: the wake gate below has to run before anything visible.
  touch.begin(PIN_TP_SDA, PIN_TP_SCL, PIN_TP_RST, PIN_TP_INT, 170, 320);
  requireWakeHold();

  ui::begin();
  ui::screen("HGS DOWNLOAD STICK", "starting...", "", "");

  // FUNCTION SEL (J101-E): the cable is a standard DTE port, so this is an
  // RS-232 level driven through the MAX3232's spare driver, not a GPIO. Which
  // DE9 pin carries it (DTR pin 4 is the likely one) is still to be confirmed,
  // so leave this high-Z - an output here would drive unknown aircraft wiring.
  if (USE_FUNCTION_SEL) {
    pinMode(PIN_FUNCTION_SEL, OUTPUT);
    digitalWrite(PIN_FUNCTION_SEL, LOW);
  } else {
    pinMode(PIN_FUNCTION_SEL, INPUT);
  }

  // Buffer size must be set BEFORE begin(): once the UART driver is installed
  // arduino-esp32 rejects the call and silently leaves the 256-byte default.
  // The 4 KB buffer is what makes it safe to repaint the screen after acking a
  // record, since the largest record (2817 B) still fits while we are drawing.
  Serial1.setRxBufferSize(4096);
  // NOT UART0: IO43/IO44 carry the ROM bootloader's 115200 banner at every
  // power-up, which would be injected straight into the DAU.
  Serial1.begin(DAU_BAUD, SERIAL_8N1, PIN_DAU_RX, PIN_DAU_TX);
  Serial1.setTimeout(20);

  if (!storage::begin()) {
    ui::screen("NO STORAGE", "card and flash", "both failed to mount", "",
               0, ui::BLACK, ui::RED);
    for (;;) delay(1000);
  }

  // Card is up, so the log has somewhere to live. This also rotates the log,
  // bumps the persistent boot counter, and records why the last session ended.
  stick_log::begin();
  stick_log::linef("ready, storage=%s touch id=0x%02X free=%luKB downloads=%d",
                   storage::backendName(), touch.chipId(),
                   (unsigned long)storage::freeKb(), storage::downloadCount());
}

void loop() {
  ui::bar(0, false);
  char power[16], l2[28], l3[28];
  powerLabel(power, sizeof(power));
  snprintf(l2, sizeof(l2), "%s  free %luMB", power,
           (unsigned long)(storage::freeBytes() / (1024 * 1024)));
  // A watchdog reset, panic or brownout last time is worth surfacing on the
  // ready screen - the maintainer should not have to open syslog.txt to find out.
  if (stick_log::priorSessionFaulted()) {
    snprintf(l3, sizeof(l3), "! prev: %s", stick_log::resetReason());
  } else {
    snprintf(l3, sizeof(l3), "%d download(s) stored", storage::downloadCount());
  }

  ui::screen("COM_1: STAND BY READY", "COM_2: - NOT AVAILABLE -", l2, l3,
             "Tap screen to download");

  waitTouchOrSleep();
  runDownload();
  waitTouchOrSleep();                   // hold the result until acknowledged
}
