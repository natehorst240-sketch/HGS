#include "cst816.h"

#include <Arduino.h>
#include <Wire.h>

static const uint8_t kAddr     = 0x15;
static const uint8_t kRegBase  = 0x01;   // 6 bytes: gesture, fingers, xH, xL, yH, yL
static const uint8_t kRegChipId = 0xA7;

static bool readReg(uint8_t reg, uint8_t* buf, size_t len) {
  Wire.beginTransmission(kAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)kAddr, (int)len) != (int)len) return false;
  for (size_t i = 0; i < len; ++i) buf[i] = Wire.read();
  return true;
}

bool Cst816::begin(int sda, int scl, int rst, int irq, int width, int height) {
  rst_ = rst;
  irq_ = irq;
  width_ = width;
  height_ = height;

  Wire.begin(sda, scl, 400000);

  if (rst_ >= 0) {
    pinMode(rst_, OUTPUT);
    reset();
  }
  // INT is a pulse on this part, not a level, so we poll I2C rather than
  // trigger on it. Claim it as an input so nothing else drives the line - and
  // it doubles as the deep-sleep wake source (IO21 is RTC-capable).
  if (irq_ >= 0) pinMode(irq_, INPUT_PULLUP);

  return chipId() >= 0;
}

void Cst816::reset() {
  if (rst_ < 0) return;
  digitalWrite(rst_, HIGH);
  delay(50);
  digitalWrite(rst_, LOW);
  delay(5);
  digitalWrite(rst_, HIGH);
  delay(50);                 // CST816 needs ~50 ms after reset
}

int Cst816::chipId() {
  uint8_t b = 0;
  return readReg(kRegChipId, &b, 1) ? b : -1;
}

bool Cst816::read(int& x, int& y) {
  uint8_t b[6];
  if (!readReg(kRegBase, b, sizeof(b))) return false;   // NAK / idle = no touch
  if (b[1] < 1) return false;                           // FingerNum == 0
  const int px = ((b[2] & 0x0F) << 8) | b[3];
  const int py = ((b[4] & 0x0F) << 8) | b[5];
  if (px >= width_ || py >= height_) return false;      // implausible -> noise
  x = px;
  y = py;
  return true;
}

bool Cst816::touched() {
  int x, y;
  return read(x, y);
}

bool Cst816::waitTouch(uint32_t timeoutMs, uint32_t pollMs) {
  const uint32_t t0 = millis();
  for (;;) {
    if (touched()) return true;
    if (timeoutMs && millis() - t0 > timeoutMs) return false;
    delay(pollMs);
  }
}

void Cst816::waitRelease(uint32_t pollMs, uint32_t settleMs) {
  uint32_t clearSince = 0;
  for (;;) {
    if (!touched()) {
      if (clearSince == 0) clearSince = millis();
      else if (millis() - clearSince >= settleMs) return;
    } else {
      clearSince = 0;
    }
    delay(pollMs);
  }
}

void Cst816::holdBegin(uint32_t holdMs, uint32_t intervalMs) {
  holdMs_ = holdMs;
  interval_ = intervalMs;
  lastPoll_ = 0;
  downSince_ = 0;
  tripped_ = false;
}

bool Cst816::holdTripped() {
  if (tripped_) return true;
  const uint32_t now = millis();
  if (now - lastPoll_ < interval_) return false;   // rate limit: this is called
  lastPoll_ = now;                                 // on every protocol poll
  if (!touched()) {
    downSince_ = 0;
    return false;
  }
  if (downSince_ == 0) downSince_ = now;
  else if (now - downSince_ >= holdMs_) tripped_ = true;
  return tripped_;
}
