#include "dau_protocol.h"

#include <string.h>
#include <stdio.h>

namespace dau {

const char* const CMD_DOWNLOAD_LOGS       = "DOWNLOAD LOGS";
const char* const CMD_DOWNLOAD_CUMULATIVE = "DOWNLOAD CUMULATIVE";
const char* const CMD_DOWNLOAD_STATUS     = "DOWNLOAD STATUS";
const char* const ACK                     = "TRANSMISSION OK";

bool looksLikeHgs(const uint8_t* rec, size_t len) {
  if (len < 20) return false;
  static const char* const kMarkers[] = {"CUMULATIVE", "FAULT", "PARAMETER",
                                         "POWER", "TIME", "AFCS",
                                         "ASSURANCE", "LOG"};
  for (size_t k = 0; k < sizeof(kMarkers) / sizeof(kMarkers[0]); ++k) {
    const size_t mlen = strlen(kMarkers[k]);
    if (len < mlen) continue;
    for (size_t i = 0; i + mlen <= len; ++i) {
      if (memcmp(rec + i, kMarkers[k], mlen) == 0) return true;
    }
  }
  const size_t head = len < 48 ? len : 48;
  size_t printable = 0;
  for (size_t i = 0; i < head; ++i) {
    if (rec[i] >= 0x20 && rec[i] <= 0x7E) printable++;
  }
  return printable >= head / 2;   // >=50% printable ASCII
}

// The download-only guarantee lives here. Every byte this firmware can put on
// the aircraft's line passes through send(), and send() will only emit one of
// these four read-side messages.
bool isPermittedMessage(const char* msg) {
  if (!msg) return false;
  return strcmp(msg, CMD_DOWNLOAD_LOGS) == 0 ||
         strcmp(msg, CMD_DOWNLOAD_CUMULATIVE) == 0 ||
         strcmp(msg, CMD_DOWNLOAD_STATUS) == 0 ||
         strcmp(msg, ACK) == 0;
}

bool Downloader::send(const char* msg) {
  if (!isPermittedMessage(msg)) return false;   // refuse; transmit nothing
  uint8_t out[MSG_LEN];
  memset(out, ' ', MSG_LEN);            // space-pad to the 25-byte wire size
  const size_t n = strlen(msg);
  memcpy(out, msg, n < MSG_LEN ? n : MSG_LEN);
  io_.writeBytes(out, MSG_LEN);
  return true;
}

bool Downloader::aborting() {
  if (!abort_ && abortCheck_()) abort_ = true;
  return abort_;
}

size_t Downloader::readRecord(uint32_t firstTimeoutMs, size_t& tailLen,
                              bool& writeFailed) {
  size_t idx = 0, total = 0;
  tailLen = 0;
  writeFailed = false;

  // Wait for the first byte of the record (or give up -> end of transfer).
  const uint32_t start = io_.nowMs();
  for (;;) {
    if (aborting()) return 0;
    const size_t n = io_.readBytes(buf_ + idx, MAX_RECORD - idx);
    if (n) { idx += n; total += n; break; }
    if (io_.nowMs() - start > firstTimeoutMs) return 0;
  }

  // Accumulate until the line goes idle - that gap is the record boundary.
  uint32_t last = io_.nowMs();
  while (io_.nowMs() - last < FRAME_IDLE_MS) {
    if (aborting()) break;
    if (idx == MAX_RECORD) {
      // Pathological: no real record exceeds 2817 bytes. The output file is a
      // pure concatenation, so flushing early keeps it byte-correct.
      if (!sink_.write(buf_, idx)) { writeFailed = true; return total; }
      idx = 0;
    }
    const size_t n = io_.readBytes(buf_ + idx, MAX_RECORD - idx);
    if (n) { idx += n; total += n; last = io_.nowMs(); }
  }
  tailLen = idx;
  return total;
}

Result Downloader::download(const char* command) {
  Result r;
  abort_ = false;

  // Fail closed before a single byte reaches the aircraft.
  if (!isPermittedMessage(command)) {
    status_("COMMAND REFUSED (not read-only)");
    r.status = Status::Refused;
    return r;
  }

  status_("DOWNLOADER TO START");

  // Send the request and wait for the first record, retransmitting (like HGS
  // does about every 5 s) if the DAU is slow or missed it.
  size_t len = 0, tail = 0;
  bool writeFailed = false;
  for (int attempt = 0; attempt < REQUEST_RETRIES; ++attempt) {
    if (abort_) break;
    send(command);
    if (attempt == 0) {
      status_("REQUEST FRAME MSG SENT");
    } else {
      char msg[32];
      snprintf(msg, sizeof(msg), "RETRYING REQUEST (%d)", attempt + 1);
      status_(msg);
    }
    len = readRecord(REQUEST_TIMEOUT_MS, tail, writeFailed);
    if (len) break;
  }

  // Guard against a floating/disconnected RX reading noise as a "record": bail
  // before writing anything to the card.
  if (len && validate_ && !(len == tail && validate_(buf_, tail))) {
    status_("NO VALID DATA (line noise?)");
    r.status = Status::Noise;
    return r;
  }

  while (!abort_ && len) {
    if (writeFailed || !sink_.write(buf_, tail)) {
      status_("STORAGE ERROR");
      r.status = Status::WriteError;
      return r;
    }
    r.bytes += len;
    r.records++;
    send(ACK);
    char msg[24];
    snprintf(msg, sizeof(msg), "FRAME %u OK", (unsigned)r.records);
    status_(msg);
    progress_(r.records, r.bytes);

    len = readRecord(END_TIMEOUT_MS, tail, writeFailed);
    if (!len && !abort_) {
      // Silence could mean done, OR the DAU missed our ack and is still
      // waiting. Nudge once with the ack before ending.
      send(ACK);
      len = readRecord(END_TIMEOUT_MS, tail, writeFailed);
    }
  }

  if (abort_) {
    status_("COMPLETED WITH ABORT");
    r.status = Status::Aborted;
    return r;
  }
  if (r.records == 0) {
    status_("NO RESPONSE FROM DAU");
    r.status = Status::NoResponse;
    return r;
  }
  char msg[48];
  snprintf(msg, sizeof(msg), "COMPLETED WITH SUCCESS  %u records",
           (unsigned)r.records);
  status_(msg);
  r.status = Status::Ok;
  return r;
}

}  // namespace dau
