#include "hg6.h"

#include <stdio.h>
#include <string.h>

namespace hg6 {

static const char FRAME_MARKER[] = "TIME HISTORY #";
static const size_t FRAME_MARKER_LEN = sizeof(FRAME_MARKER) - 1;

// --- BCD helpers, identical to hgs/hg6.py --------------------------------------
static int bcd(uint8_t b) { return (b >> 4) * 10 + (b & 0x0F); }

static long bcdInt(const uint8_t* p, size_t n) {
  long v = 0;
  for (size_t i = 0; i < n; ++i) v = v * 100 + bcd(p[i]);
  return v;
}

// "20YY-MM-DD HH:MM:SS"
static void ts(const uint8_t* s, char* out, size_t outLen) {
  snprintf(out, outLen, "20%02d-%02d-%02d %02d:%02d:%02d",
           bcd(s[0]), bcd(s[1]), bcd(s[2]), bcd(s[3]), bcd(s[4]), bcd(s[5]));
}

// "HH:MM:SS"
static void hms(const uint8_t* s, char* out, size_t outLen) {
  snprintf(out, outLen, "%02d:%02d:%02d", bcd(s[0]), bcd(s[1]), bcd(s[2]));
}

// 4-byte BCD running-time counter: 00 47 85 38 -> "04785:38"
static void hhmm(const uint8_t* s, char* out, size_t outLen) {
  long hours = 0;
  for (int i = 0; i < 3; ++i) hours = hours * 100 + bcd(s[i]);
  snprintf(out, outLen, "%05ld:%d%d", hours, s[3] >> 4, s[3] & 0x0F);
}

// Multi-byte BCD scaled by 10 / 100, printed like Python's :.1f / :.2f.
static void tenths(const uint8_t* p, size_t n, char* out, size_t outLen) {
  const long v = bcdInt(p, n);
  snprintf(out, outLen, "%ld.%ld", v / 10, v % 10);
}
static void intStr(const uint8_t* p, size_t n, char* out, size_t outLen) {
  snprintf(out, outLen, "%ld", bcdInt(p, n));
}

// Full BCD timestamp sanity check (catalog events, power assurance).
static bool bcdTsOk(const uint8_t* t, size_t avail) {
  if (avail < 6) return false;
  bool any = false;
  for (int i = 0; i < 6; ++i) any |= (t[i] != 0);
  if (!any) return false;
  const int yy = bcd(t[0]), mm = bcd(t[1]), dd = bcd(t[2]);
  const int hh = bcd(t[3]), mi = bcd(t[4]), ss = bcd(t[5]);
  return yy >= 20 && yy <= 40 && mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31 &&
         hh <= 23 && mi <= 59 && ss <= 59;
}

// Time-history sample check: month..seconds only, like _plausible_ts().
static bool plausibleTs(const uint8_t* s) {
  const int mm = bcd(s[1]), dd = bcd(s[2]), hh = bcd(s[3]), mi = bcd(s[4]), ss = bcd(s[5]);
  return mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31 && hh <= 23 && mi <= 59 && ss <= 59;
}

static size_t findBytes(const uint8_t* d, size_t len, size_t from,
                        const char* needle, size_t nlen) {
  if (nlen > len) return len;
  for (size_t i = from; i + nlen <= len; ++i) {
    if (d[i] == (uint8_t)needle[0] && memcmp(d + i, needle, nlen) == 0) return i;
  }
  return len;                                 // "not found" == len
}

// --- parameter catalog ---------------------------------------------------------
static bool isLabel(const uint8_t* d, size_t len, size_t o) {
  if (o + LABEL_LEN > len) return false;
  int upper = 0;
  for (size_t i = 0; i < LABEL_LEN; ++i) {
    const uint8_t c = d[o + i];
    if (c < 0x20 || c > 0x7E) return false;
    if (c >= 'A' && c <= 'Z') upper++;
  }
  const uint8_t f = d[o];
  if (!(f == '#' || (f >= '0' && f <= '9') || (f >= 'A' && f <= 'Z'))) return false;
  return upper >= 3;
}

static int trailingSpaces(const uint8_t* d, size_t o) {
  int n = 0;
  for (size_t i = LABEL_LEN; i > 0; --i) {
    if (d[o + i - 1] == ' ') n++; else break;
  }
  return n;
}

// Visit every label offset in [0, end) in order; `fn(o, next)` gets the label
// offset and the offset of the following label (or `end`).
// `end` bounds the scan (the first time-history frame); a label window may
// extend past it into the file, exactly as the Python slice does.
template <typename Fn>
static void scanLabels(const uint8_t* d, size_t len, size_t end, Fn fn) {
  size_t prev = end;                          // offset of the pending label
  size_t o = 0;
  while (o < end) {
    if (isLabel(d, len, o)) {
      // A printable seq-id byte can make the window qualify one byte early;
      // the correctly aligned window has more trailing padding.
      while (o + 1 < end && isLabel(d, len, o + 1) &&
             trailingSpaces(d, o + 1) > trailingSpaces(d, o)) {
        o++;
      }
      if (prev != end) fn(prev, o);
      prev = o;
      o += LABEL_LEN;
    } else {
      o++;
    }
  }
  if (prev != end) fn(prev, end);
}

static bool startsWith(const char* s, const char* prefix) {
  return strncmp(s, prefix, strlen(prefix)) == 0;
}

static void parseCatalog(const uint8_t* d, size_t len, size_t end, Parsed& out) {
  out.params = 0;
  out.nev = 0;
  scanLabels(d, len, end, [&](size_t o, size_t nxt) {
    char label[LABEL_LEN + 1];
    memcpy(label, d + o, LABEL_LEN);
    label[LABEL_LEN] = 0;
    // Python .strip(): trim both ends
    size_t s = 0, e = LABEL_LEN;
    while (s < e && label[s] == ' ') s++;
    while (e > s && label[e - 1] == ' ') e--;
    label[e] = 0;
    const char* name = label + s;
    if (startsWith(name, "TIME HISTORY") || startsWith(name, "CUMULATIVE")) return;
    out.params++;

    const uint8_t* ts1 = d + o + LABEL_LEN;
    if (!bcdTsOk(ts1, nxt > o + LABEL_LEN ? nxt - (o + LABEL_LEN) : 0)) return;
    if (out.nev >= MAX_EVENTS) return;
    Event& ev = out.ev[out.nev++];
    snprintf(ev.label, sizeof(ev.label), "%s", name);
    ts(ts1, ev.first, sizeof(ev.first));
    ev.last[0] = 0;
    if (nxt >= 22 && bcdTsOk(d + nxt - 22, 6)) ts(d + nxt - 22, ev.last, sizeof(ev.last));
    ev.count = (nxt >= 6 && nxt - 6 > o + LABEL_LEN) ? bcd(d[nxt - 6]) : 0;
    ev.afcs = strstr(name, "FAIL CODE") != nullptr;
  });
}

// --- cumulative log --------------------------------------------------------------
static void addRow(Parsed& out, const char* item, const char* value) {
  if (out.ncum >= MAX_CUM) return;
  Row& r = out.cum[out.ncum++];
  snprintf(r.item, sizeof(r.item), "%s", item);
  snprintf(r.value, sizeof(r.value), "%s", value);
}

static void parseCumulative(const uint8_t* d, size_t len, Parsed& out) {
  out.ncum = 0;
  const size_t o = findBytes(d, len, 0, "CUMULATIVE LOG", 14);
  if (o == len) return;
  size_t th = findBytes(d, len, o, FRAME_MARKER, FRAME_MARKER_LEN);
  const uint8_t* blk = d + o;
  const size_t blen = th - o;
  if (blen < 64) return;                      // truncated block: nothing trustworthy
  const size_t p = LABEL_LEN;
  char v[40], v2[20];

  snprintf(v2, sizeof(v2), "%02d:%02d:%02d", bcd(blk[p + 4]), bcd(blk[p + 5]), bcd(blk[p + 6]));
  snprintf(v, sizeof(v), "20%02d-%02d-%02d %s", bcd(blk[p]), bcd(blk[p + 1]), bcd(blk[p + 2]), v2);
  addRow(out, "Cumulative Data", v);
  snprintf(v, sizeof(v), "20%02d-%02d-%02d", bcd(blk[p + 8]), bcd(blk[p + 9]), bcd(blk[p + 10]));
  addRow(out, "Dau Batt. Install Date", v);
  memcpy(v, blk + p + 11, 5); v[5] = 0;
  addRow(out, "Aircraft S/N", v);
  hms(blk + p + 16, v, sizeof(v)); addRow(out, "Most Recent Flight Start", v);
  hms(blk + p + 19, v, sizeof(v)); addRow(out, "Most Recent Flight Stop", v);
  snprintf(v, sizeof(v), "%02d:%02d", bcd(blk[p + 22]), bcd(blk[p + 23]));
  addRow(out, "Most Recent Flight Time", v);
  hhmm(blk + p + 24, v, sizeof(v)); addRow(out, "Total Flight Time", v);
  intStr(blk + p + 28, 3, v, sizeof(v)); addRow(out, "Number of Flights", v);
  intStr(blk + blen - 4, 2, v, sizeof(v)); addRow(out, "Chip Burner Activations", v);

  struct Block { const char* name; size_t ao; size_t snlen; };
  static const Block blocks[4] = {{"Main Transmission", 56, 7}, {"Tail Transmission", 79, 7},
                                  {"Engine 1", 102, 6}, {"Engine 2", 161, 6}};
  char item[40];
  for (int i = 0; i < 4; ++i) {
    const Block& b = blocks[i];
    const size_t nxt = (i + 1 < 4) ? blocks[i + 1].ao : blen - 4;
    if (b.ao + b.snlen + 6 > blen) break;
    memcpy(v, blk + b.ao, b.snlen); v[b.snlen] = 0;
    { size_t e = b.snlen; while (e > 0 && v[e - 1] == ' ') v[--e] = 0;
      size_t s = 0; while (v[s] == ' ') s++;
      if (s) memmove(v, v + s, strlen(v + s) + 1); }
    snprintf(item, sizeof(item), "%s S/N", b.name);  addRow(out, item, v);
    const size_t q = b.ao + b.snlen;
    intStr(blk + q, 2, v, sizeof(v));
    snprintf(item, sizeof(item), "%s TBO", b.name);  addRow(out, item, v);
    hhmm(blk + q + 2, v, sizeof(v));
    snprintf(item, sizeof(item), "%s TSN", b.name);  addRow(out, item, v);

    if (startsWith(b.name, "Engine")) {
      size_t r = q + 10;
      while (r < nxt && blk[r] == 0) r++;
      r -= 1;
      if (r + 4 + 5 + 30 > blen) break;
      hhmm(blk + r, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Running Time", b.name); addRow(out, item, v);
      const size_t c = r + 4 + 5;
      snprintf(v, sizeof(v), "%d", bcd(blk[c]));
      snprintf(item, sizeof(item), "%s Chip D.A.", b.name); addRow(out, item, v);
      hms(blk + c + 1, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Start-up", b.name); addRow(out, item, v);
      hms(blk + c + 4, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Shutdown", b.name); addRow(out, item, v);
      intStr(blk + c + 10, 2, v, sizeof(v));
      snprintf(item, sizeof(item), "%s LIM ON Activations", b.name); addRow(out, item, v);
      intStr(blk + c + 12, 3, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Training Activations", b.name); addRow(out, item, v);
      // 12 BCD digits with a leading pad zero: 010029042104 -> 1002904-2-104
      char digits[13];
      for (int k = 0; k < 6; ++k) {
        digits[k * 2]     = (char)('0' + (blk[c + 15 + k] >> 4));
        digits[k * 2 + 1] = (char)('0' + (blk[c + 15 + k] & 0x0F));
      }
      digits[12] = 0;
      snprintf(v, sizeof(v), "%.7s-%c-%.3s", digits + 1, digits[8], digits + 9);
      snprintf(item, sizeof(item), "%s EECU P/N", b.name); addRow(out, item, v);
      intStr(blk + c + 21, 3, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Compr.Turbine C.Counts", b.name); addRow(out, item, v);
      intStr(blk + c + 24, 3, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Pwr Turbine C.Counts", b.name); addRow(out, item, v);
      intStr(blk + c + 27, 3, v, sizeof(v));
      snprintf(item, sizeof(item), "%s Imp.Turbine C.Counts", b.name); addRow(out, item, v);
    } else {
      // Transmissions: chip detector D.A. is the last nonzero BCD pair.
      long chip = 0;
      for (size_t k = nxt - 2; k > q + 6; --k) {
        if (blk[k] || blk[k + 1]) { chip = bcdInt(blk + k, 2); break; }
      }
      snprintf(v, sizeof(v), "%ld", chip);
      snprintf(item, sizeof(item), "%s Cumulative Chip D.A.", b.name); addRow(out, item, v);
    }
  }
}

// --- power assurance ---------------------------------------------------------------
static void parsePowerAssurance(const uint8_t* d, size_t len, Parsed& out) {
  out.npa = 0;
  const size_t o = findBytes(d, len, 0, "POWER ASSURANCE LOG", 19);
  if (o == len) return;
  size_t p = o + LABEL_LEN;
  while (p + 34 <= len && bcdTsOk(d + p, 6) && out.npa < MAX_PA) {
    const uint8_t* s = d + p;
    PaRow& r = out.pa[out.npa++];
    ts(s, r.col[0], 20);
    intStr(s + 6, 3, r.col[1], 20);           // OAT
    intStr(s + 9, 3, r.col[2], 20);           // Pa
    intStr(s + 28, 2, r.col[3], 20);          // IAS
    intStr(s + 12, 2, r.col[4], 20);          // N2 1
    intStr(s + 16, 2, r.col[5], 20);          // TRQ 1
    intStr(s + 20, 2, r.col[6], 20);          // TOT 1 Act
    tenths(s + 24, 2, r.col[7], 20);          // N1 1 Act
    snprintf(r.col[8], 20, "%s", s[30] ? "ON" : "OFF");   // IDLE 1
    snprintf(r.col[9], 20, "%s", s[32] ? "ON" : "OFF");   // MAN 1
    intStr(s + 14, 2, r.col[10], 20);         // N2 2
    intStr(s + 18, 2, r.col[11], 20);         // TRQ 2
    intStr(s + 22, 2, r.col[12], 20);         // TOT 2 Act
    tenths(s + 26, 2, r.col[13], 20);         // N1 2 Act
    snprintf(r.col[14], 20, "%s", s[31] ? "ON" : "OFF");  // IDLE 2
    snprintf(r.col[15], 20, "%s", s[33] ? "ON" : "OFF");  // MAN 2
    p += 34;
  }
}

// --- time history summary -------------------------------------------------------------
static void parseTimeHistory(const uint8_t* d, size_t len, Parsed& out) {
  ThSummary& t = out.th;
  memset(&t, 0, sizeof(t));
  size_t pos = 0;
  for (;;) {
    const size_t f = findBytes(d, len, pos, FRAME_MARKER, FRAME_MARKER_LEN);
    if (f == len) break;
    pos = f + 1;
    // marker must be followed by exactly three digits ("TIME HISTORY #001")
    if (f + FRAME_MARKER_LEN + 3 > len) break;
    bool digits = true;
    for (int k = 0; k < 3; ++k) {
      const uint8_t c = d[f + FRAME_MARKER_LEN + k];
      if (c < '0' || c > '9') digits = false;
    }
    if (!digits) continue;
    t.frames++;
    const size_t limit = (f + FRAME_LEN < len) ? f + FRAME_LEN : len;
    size_t off = f + LABEL_LEN;
    int n = 0;
    while (off + SAMPLE_LEN <= limit && plausibleTs(d + off)) {
      if (t.samples == 0) ts(d + off, t.first, sizeof(t.first));
      ts(d + off, t.last, sizeof(t.last));
      t.samples++;
      n++;
      off += SAMPLE_LEN;
    }
    if (n) t.framesWithData++;
  }
}

void parse(const uint8_t* d, size_t len, Parsed& out) {
  memset(&out, 0, sizeof(out));
  const size_t thStart = findBytes(d, len, 0, FRAME_MARKER, FRAME_MARKER_LEN);
  parseCatalog(d, len, thStart, out);         // catalog ends where the frames begin
  parseCumulative(d, len, out);
  parsePowerAssurance(d, len, out);
  if (thStart != len) parseTimeHistory(d, len, out);
}

}  // namespace hg6
