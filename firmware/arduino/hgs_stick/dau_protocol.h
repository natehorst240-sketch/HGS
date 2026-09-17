// DAU download protocol - portable C++ port of firmware/dau_protocol.py.
//
// FULLY REVERSE-ENGINEERED from a live A109 capture (see reverse/PROTOCOL.md).
// The Python original was validated byte-for-byte against a real download; this
// port is held to the same standard by firmware/arduino/test/replay_test.cpp.
//
// Protocol (9600,n,8,1), stop-and-wait, DAU-paced:
//   1. downloader -> "DOWNLOAD LOGS" (25-byte space-padded ASCII)
//   2. DAU -> one whole record (92/110/228/503/2817 bytes), then pauses for an ack
//   3. downloader -> "TRANSMISSION OK" (25-byte space-padded ASCII)
//   4. repeat 2-3; concatenated records == the .HG file
//
// Record boundaries are the idle gap after each record, so we frame by
// inter-byte idle time. Deliberately free of Arduino headers: the host-side
// replay test compiles this exact translation unit.
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <functional>

namespace dau {

static const size_t   MSG_LEN            = 25;    // control messages, space-padded
static const uint32_t FRAME_IDLE_MS      = 60;    // gap = record done, DAU awaits ack
static const uint32_t END_TIMEOUT_MS     = 4000;  // silence this long => (maybe) done
static const uint32_t REQUEST_TIMEOUT_MS = 5000;  // wait for record 1 before resend
static const int      REQUEST_RETRIES    = 6;     // ~30 s, like HGS's 5 s retransmits
static const size_t   MAX_RECORD         = 4096;  // largest real record is 2817

extern const char* const CMD_DOWNLOAD_LOGS;
extern const char* const CMD_DOWNLOAD_CUMULATIVE;
extern const char* const CMD_DOWNLOAD_STATUS;
extern const char* const ACK;

// Byte transport. Implemented over HardwareSerial on the board, and over a
// canned record list in the replay test.
class Io {
 public:
  virtual ~Io() {}
  // Non-blocking-ish: copy up to maxLen bytes, return how many (0 if none).
  virtual size_t readBytes(uint8_t* dst, size_t maxLen) = 0;
  virtual void writeBytes(const uint8_t* src, size_t len) = 0;
  // Monotonic milliseconds. Wrap is fine - comparisons use unsigned deltas.
  virtual uint32_t nowMs() = 0;
};

// Where reassembled records go (a file on SD, or a buffer in the test).
class Sink {
 public:
  virtual ~Sink() {}
  virtual bool write(const uint8_t* data, size_t len) = 0;
};

enum class Status {
  Ok,           // completed, records received
  Aborted,      // user held the screen
  NoResponse,   // DAU never answered
  Noise,        // something answered but it was not HGS data
  WriteError,   // the sink refused (card full / removed)
  Refused,      // caller asked for a command outside the read-only set
};

// DOWNLOAD-ONLY GUARANTEE
// -----------------------
// This tool must never write to the aircraft beyond the protocol's own request
// and ack bytes. That is enforced structurally, not by convention:
//   - Downloader::send() is the ONLY function in the firmware that transmits
//     on the DAU line, and it refuses anything outside the four strings below
//   - all four are read-side: three DOWNLOAD_* requests and the ack
//   - no erase, clear, set, reset or write command exists anywhere in the
//     codebase, so none can be sent even by a future caller passing a rogue
//     string to download()
bool isPermittedMessage(const char* msg);

struct Result {
  Status status  = Status::NoResponse;
  size_t bytes   = 0;
  size_t records = 0;
  bool ok() const { return status == Status::Ok; }
};

using StatusFn   = std::function<void(const char*)>;
using ProgressFn = std::function<void(size_t records, size_t bytes)>;
using AbortFn    = std::function<bool()>;
using ValidateFn = std::function<bool(const uint8_t* rec, size_t len)>;

// Reject line noise from a floating / disconnected RX. Real HGS records carry
// 25-byte ASCII labels and known log keywords; random UART noise is ~37%
// printable and has no markers.
bool looksLikeHgs(const uint8_t* rec, size_t len);

class Downloader {
 public:
  Downloader(Io& io, Sink& sink) : io_(io), sink_(sink) {}

  void onStatus(StatusFn f)          { status_ = f; }
  void onProgress(ProgressFn f)      { progress_ = f; }
  void onAbortCheck(AbortFn f)       { abortCheck_ = f; }
  // Defaults to accept-anything; pass looksLikeHgs to enable the noise guard.
  void onValidateFirst(ValidateFn f) { validate_ = f; }

  Result download(const char* command = CMD_DOWNLOAD_LOGS);

 private:
  // Returns false and transmits NOTHING if msg is not on the permitted list.
  bool send(const char* msg);
  bool aborting();
  // Reads one record. Returns its total length; the trailing tailLen bytes are
  // left in buf_. Anything before that has already been flushed to sink_, which
  // only happens for pathologically long records.
  size_t readRecord(uint32_t firstTimeoutMs, size_t& tailLen, bool& writeFailed);

  Io&   io_;
  Sink& sink_;
  StatusFn   status_     = [](const char*) {};
  ProgressFn progress_   = [](size_t, size_t) {};
  AbortFn    abortCheck_ = []() { return false; };
  ValidateFn validate_;
  bool    abort_ = false;
  uint8_t buf_[MAX_RECORD];
};

}  // namespace dau
