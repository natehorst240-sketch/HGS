// Host-side port gate for the C++ DAU protocol.
//
// The Python implementation was validated byte-for-byte against a real A109
// download. This test holds the C++ port to the same bar BEFORE it is allowed
// near an aircraft: it replays firmware/wire_test.HG6 (589,237 bytes captured
// from a live download) through a stop-and-wait DAU emulator and requires the
// reassembled output to be byte-identical to the original file.
//
// Build and run:  cd firmware/arduino/test && make
//
// It compiles the exact same dau_protocol.cpp the board runs - no Arduino
// headers are involved, which is why that file was kept free of them.

#include "../hgs_stick/dau_protocol.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <vector>
#include <string>

// --- a stop-and-wait DAU emulator -------------------------------------------
// Each write from the downloader (request or ack) arms exactly one record; the
// record is then handed over in chunks of chunk_ bytes. A virtual clock
// advances tickMs_ on every nowMs() call, so the idle-gap framing is exercised
// deterministically without any real timing.
class FakeDau : public dau::Io {
 public:
  FakeDau(std::vector<std::vector<uint8_t> > records, size_t chunk, uint32_t tickMs)
      : records_(records), chunk_(chunk), tickMs_(tickMs) {}

  size_t readBytes(uint8_t* dst, size_t maxLen) override {
    if (!armed_ || next_ >= records_.size()) return 0;
    const std::vector<uint8_t>& rec = records_[next_];
    const size_t remaining = rec.size() - pos_;
    size_t n = remaining < chunk_ ? remaining : chunk_;
    if (n > maxLen) n = maxLen;
    memcpy(dst, rec.data() + pos_, n);
    pos_ += n;
    if (pos_ == rec.size()) {       // record fully delivered; wait for the ack
      pos_ = 0;
      next_++;
      armed_ = false;
    }
    return n;
  }

  void writeBytes(const uint8_t* src, size_t len) override {
    sent_.push_back(std::string(reinterpret_cast<const char*>(src), len));
    armed_ = true;                  // request or ack releases the next record
  }

  uint32_t nowMs() override { t_ += tickMs_; return t_; }

  const std::vector<std::string>& sent() const { return sent_; }
  size_t delivered() const { return next_; }

 private:
  std::vector<std::vector<uint8_t> > records_;
  std::vector<std::string> sent_;
  size_t   chunk_;
  uint32_t tickMs_;
  size_t   next_ = 0;
  size_t   pos_  = 0;
  bool     armed_ = false;
  uint32_t t_ = 0;
};

class BufferSink : public dau::Sink {
 public:
  bool write(const uint8_t* data, size_t len) override {
    if (fail) return false;
    out.insert(out.end(), data, data + len);
    return true;
  }
  std::vector<uint8_t> out;
  bool fail = false;
};

// --- helpers -----------------------------------------------------------------
static int failures = 0;

static void check(bool cond, const char* what) {
  printf("  %-52s %s\n", what, cond ? "PASS" : "*** FAIL ***");
  if (!cond) failures++;
}

static bool readFile(const char* path, std::vector<uint8_t>& out) {
  FILE* f = fopen(path, "rb");
  if (!f) return false;
  fseek(f, 0, SEEK_END);
  const long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  out.resize(static_cast<size_t>(n));
  const size_t got = fread(out.data(), 1, out.size(), f);
  fclose(f);
  return got == out.size();
}

// Split a download into records using the sizes seen on the wire.
static std::vector<std::vector<uint8_t> > splitRecords(const std::vector<uint8_t>& data) {
  static const size_t kSizes[] = {92, 110, 228, 503, 2817};
  std::vector<std::vector<uint8_t> > recs;
  size_t pos = 0, i = 0;
  while (pos < data.size()) {
    size_t n = kSizes[i++ % 5];
    if (pos + n > data.size()) n = data.size() - pos;
    recs.push_back(std::vector<uint8_t>(data.begin() + pos, data.begin() + pos + n));
    pos += n;
  }
  return recs;
}

static size_t countAcks(const std::vector<std::string>& sent) {
  size_t n = 0;
  for (size_t i = 0; i < sent.size(); ++i) {
    if (sent[i].compare(0, strlen(dau::ACK), dau::ACK) == 0) n++;
  }
  return n;
}

// --- tests --------------------------------------------------------------------
static void testWireFormat() {
  printf("\n[wire format]\n");
  std::vector<std::vector<uint8_t> > recs;
  recs.push_back(std::vector<uint8_t>(64, 'A'));
  FakeDau io(recs, 4096, 100);
  BufferSink sink;
  dau::Downloader dl(io, sink);
  dl.download();

  check(!io.sent().empty(), "something was sent");
  check(io.sent()[0].size() == dau::MSG_LEN, "request is exactly 25 bytes");
  check(io.sent()[0] == "DOWNLOAD LOGS            ", "request is space-padded ASCII");
  bool allAcks25 = true;
  for (size_t i = 1; i < io.sent().size(); ++i) {
    if (io.sent()[i].size() != dau::MSG_LEN) allAcks25 = false;
  }
  check(allAcks25, "every ack is exactly 25 bytes");
  check(countAcks(io.sent()) >= 1, "TRANSMISSION OK was sent");
}

static void testSynthetic() {
  printf("\n[synthetic records - mirrors test_protocol.py]\n");
  std::vector<std::vector<uint8_t> > recs;
  recs.push_back(std::vector<uint8_t>(92, 'A'));
  recs.push_back(std::vector<uint8_t>(110, 'B'));
  recs.push_back(std::vector<uint8_t>(228, 'C'));
  std::vector<uint8_t> expected;
  for (size_t i = 0; i < recs.size(); ++i)
    expected.insert(expected.end(), recs[i].begin(), recs[i].end());

  FakeDau io(recs, 4096, 100);      // whole record per read, like the Python fake
  BufferSink sink;
  dau::Downloader dl(io, sink);
  dau::Result r = dl.download();

  check(r.status == dau::Status::Ok, "status == Ok");
  check(r.records == 3, "3 records");
  check(r.bytes == expected.size(), "byte count matches");
  check(sink.out == expected, "reassembled stream is byte-identical");
}

static void testChunked() {
  printf("\n[chunked delivery - exercises idle-gap accumulation]\n");
  // 64-byte chunks with the clock ticking 10 ms per poll: every gap inside a
  // record is under FRAME_IDLE_MS, so the reader must keep accumulating and
  // only close the record on the real gap.
  std::vector<std::vector<uint8_t> > recs;
  for (int i = 0; i < 5; ++i) {
    std::vector<uint8_t> r(503);
    for (size_t j = 0; j < r.size(); ++j) r[j] = static_cast<uint8_t>(i * 31 + j);
    recs.push_back(r);
  }
  std::vector<uint8_t> expected;
  for (size_t i = 0; i < recs.size(); ++i)
    expected.insert(expected.end(), recs[i].begin(), recs[i].end());

  FakeDau io(recs, 64, 10);
  BufferSink sink;
  dau::Downloader dl(io, sink);
  dau::Result r = dl.download();

  check(r.status == dau::Status::Ok, "status == Ok");
  check(r.records == 5, "records not split by intra-record gaps");
  check(sink.out == expected, "reassembled stream is byte-identical");
}

static void testRealDownload(const char* path) {
  printf("\n[replay of the real capture: %s]\n", path);
  std::vector<uint8_t> original;
  if (!readFile(path, original)) {
    printf("  *** FAIL *** cannot read %s\n", path);
    failures++;
    return;
  }
  std::vector<std::vector<uint8_t> > recs = splitRecords(original);
  printf("  %zu bytes in %zu records\n", original.size(), recs.size());

  FakeDau io(recs, 256, 5);
  BufferSink sink;
  dau::Downloader dl(io, sink);
  dl.onValidateFirst(dau::looksLikeHgs);      // noise guard active, as on the board
  dau::Result r = dl.download();

  check(r.status == dau::Status::Ok, "status == Ok");
  check(r.records == recs.size(), "every record acked");
  check(r.bytes == original.size(), "total byte count matches the file");
  check(sink.out.size() == original.size(), "output length matches");
  check(sink.out == original, "OUTPUT IS BYTE-IDENTICAL TO THE REAL DOWNLOAD");
  check(countAcks(io.sent()) >= recs.size(), "one ack per record");
}

static void testNoiseRejected() {
  printf("\n[noise rejection]\n");
  std::vector<uint8_t> noise;
  for (int i = 0; i < 200; ++i) noise.push_back(static_cast<uint8_t>((i * 97) ^ 0xA5));
  std::vector<std::vector<uint8_t> > recs;
  recs.push_back(noise);

  FakeDau io(recs, 4096, 100);
  BufferSink sink;
  dau::Downloader dl(io, sink);
  dl.onValidateFirst(dau::looksLikeHgs);
  dau::Result r = dl.download();

  check(r.status == dau::Status::Noise, "binary noise rejected");
  check(sink.out.empty(), "nothing written to storage");

  // ...and a real HGS-looking record must still be accepted.
  std::vector<uint8_t> good;
  const char* label = "CUMULATIVE LOG           ";
  good.insert(good.end(), label, label + strlen(label));
  good.resize(92, 0x00);
  std::vector<std::vector<uint8_t> > recs2;
  recs2.push_back(good);
  FakeDau io2(recs2, 4096, 100);
  BufferSink sink2;
  dau::Downloader dl2(io2, sink2);
  dl2.onValidateFirst(dau::looksLikeHgs);
  check(dl2.download().status == dau::Status::Ok, "genuine record accepted");
}

static void testNoResponseAndAbort() {
  printf("\n[no response / abort / storage failure]\n");
  {
    std::vector<std::vector<uint8_t> > none;
    FakeDau io(none, 4096, 100);
    BufferSink sink;
    dau::Downloader dl(io, sink);
    dau::Result r = dl.download();
    check(r.status == dau::Status::NoResponse, "silent DAU -> NoResponse");
    check(io.sent().size() == static_cast<size_t>(dau::REQUEST_RETRIES),
          "request retransmitted 6x");
  }
  {
    std::vector<std::vector<uint8_t> > recs;
    for (int i = 0; i < 10; ++i) recs.push_back(std::vector<uint8_t>(228, 'X'));
    // Chunked delivery, so the abort check is polled *during* a record - which
    // is what happens on real hardware, where bytes trickle in at 9600 baud and
    // the accumulate loop spins the whole time. Delivering whole records in one
    // burst would only poll it once per record and abort late.
    FakeDau io(recs, 64, 10);
    BufferSink sink;
    dau::Downloader dl(io, sink);
    int calls = 0;
    dl.onAbortCheck([&calls]() { return ++calls > 12; });   // hold the screen
    dau::Result r = dl.download();
    check(r.status == dau::Status::Aborted, "hold -> Aborted");
    check(r.records < 10, "aborted before the end");
  }
  {
    std::vector<std::vector<uint8_t> > recs;
    recs.push_back(std::vector<uint8_t>(228, 'Y'));
    FakeDau io(recs, 4096, 100);
    BufferSink sink;
    sink.fail = true;                                       // card full / removed
    dau::Downloader dl(io, sink);
    check(dl.download().status == dau::Status::WriteError, "sink failure surfaces");
  }
}

// The safety property that matters most: this tool downloads, it never writes
// to the aircraft. Proven two ways - a rogue command must be refused before any
// byte leaves, and across a full real download every single transmitted message
// must be one of the four permitted read-side strings.
static void testDownloadOnly() {
  printf("\n[download-only guarantee]\n");

  const char* rogue[] = {"ERASE LOGS", "CLEAR FAULTS", "RESET DAU",
                         "SET PARAMETER", "WRITE CONFIG", ""};
  bool allRefused = true, allSilent = true;
  for (size_t i = 0; i < sizeof(rogue) / sizeof(rogue[0]); ++i) {
    std::vector<std::vector<uint8_t> > recs;
    recs.push_back(std::vector<uint8_t>(92, 'A'));
    FakeDau io(recs, 4096, 100);
    BufferSink sink;
    dau::Downloader dl(io, sink);
    const dau::Result r = dl.download(rogue[i]);
    if (r.status != dau::Status::Refused) allRefused = false;
    if (!io.sent().empty()) allSilent = false;
  }
  check(allRefused, "every write-style command is refused");
  check(allSilent, "refused commands transmit ZERO bytes");
  check(!dau::isPermittedMessage("ERASE LOGS"), "whitelist rejects unknown text");
  check(dau::isPermittedMessage(dau::CMD_DOWNLOAD_LOGS), "whitelist accepts the request");
  check(dau::isPermittedMessage(dau::ACK), "whitelist accepts the ack");

  // Now audit the whole transmit log of a real download.
  std::vector<uint8_t> original;
  if (!readFile("../../wire_test.HG6", original)) return;
  std::vector<std::vector<uint8_t> > recs = splitRecords(original);
  FakeDau io(recs, 256, 5);
  BufferSink sink;
  dau::Downloader dl(io, sink);
  dl.download();

  bool onlyPermitted = true;
  size_t nonAck = 0;
  for (size_t i = 0; i < io.sent().size(); ++i) {
    const std::string& m = io.sent()[i];
    if (m.size() != dau::MSG_LEN) { onlyPermitted = false; continue; }
    std::string trimmed = m;
    while (!trimmed.empty() && trimmed[trimmed.size() - 1] == ' ')
      trimmed.erase(trimmed.size() - 1);
    if (!dau::isPermittedMessage(trimmed.c_str())) onlyPermitted = false;
    if (trimmed != dau::ACK) nonAck++;
  }
  printf("  %zu messages transmitted across the whole download\n", io.sent().size());
  check(onlyPermitted, "EVERY transmitted message is on the read-only whitelist");
  check(nonAck == 1, "exactly one non-ack message sent (the initial request)");
}

int main(int argc, char** argv) {
  const char* capture = argc > 1 ? argv[1] : "../../wire_test.HG6";
  printf("HGS DAU protocol - host replay gate\n");

  testWireFormat();
  testSynthetic();
  testChunked();
  testRealDownload(capture);
  testNoiseRejected();
  testNoResponseAndAbort();
  testDownloadOnly();

  printf("\n%s\n", failures == 0 ? "RESULT: PASS - safe to flash"
                                 : "RESULT: FAIL - do NOT flash");
  return failures == 0 ? 0 : 1;
}
