// CST816 capacitive touch driver (Waveshare ESP32-S3-Touch-LCD-1.9).
//
// Ported from the CST816S driver in firmware/touch_cst816.py. Same part family,
// same register map - only the pins move (SDA 47 / SCL 48 / RST 17 / INT 21,
// and the bus is shared with the QMI8658 IMU at 0x6B).
//
//   0x01 GestureID   0x02 FingerNum   0x03/04 XposH/L   0x05/06 YposH/L
//   0xA7 ChipID (0xB5 = CST816S; other CST816 variants report different IDs,
//        so this is logged for bring-up, never asserted on)
#pragma once

#include <stdint.h>

class Cst816 {
 public:
  bool begin(int sda, int scl, int rst, int irq, int width, int height);
  void reset();

  // Chip ID, or -1 if the controller does not answer.
  int chipId();

  // True if a finger is down; fills x/y in panel coordinates when it is.
  bool read(int& x, int& y);
  bool touched();

  // Block until touched. false on timeout (timeoutMs == 0 waits forever).
  bool waitTouch(uint32_t timeoutMs = 0, uint32_t pollMs = 20);
  // Block until the screen has been clear for settleMs.
  void waitRelease(uint32_t pollMs = 20, uint32_t settleMs = 150);

  // Rate-limited press-and-hold detector, cheap enough to be the downloader's
  // abort check (it is polled on every byte-level read). A brief tap will not
  // trip it - only a deliberate hold.
  void holdBegin(uint32_t holdMs, uint32_t intervalMs = 250);
  bool holdTripped();

 private:
  int rst_ = -1, irq_ = -1;
  int width_ = 170, height_ = 320;
  uint32_t holdMs_ = 1500, interval_ = 250;
  uint32_t lastPoll_ = 0, downSince_ = 0;
  bool tripped_ = false;
};
