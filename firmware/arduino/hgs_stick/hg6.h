// .HG6 download-file decoder - portable C++ port of hgs/hg6.py.
//
// Gives the stick the same Data View the Linux app has: Cumulative Log,
// Fault Log, AFCS Fault Log, Power Assurance Log, and a Time History summary
// (the full 1 Hz table is thousands of rows and stays on the PC).
//
// Deliberately free of Arduino headers: firmware/arduino/test/hg6_test.cpp
// compiles this exact file on the host and holds it to the Python parser's
// output on the real sample downloads, field for field.
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace hg6 {

static const size_t LABEL_LEN  = 25;
static const size_t SAMPLE_LEN = 31;
static const size_t FRAME_LEN  = 2817;

static const int MAX_CUM    = 48;   // 43 rows in a real file
static const int MAX_EVENTS = 64;   // populated fault / AFCS catalog entries
static const int MAX_PA     = 32;   // power assurance records
static const int PA_COLS    = 16;

struct Row {                 // Cumulative Log: Item / Value
  char item[40];
  char value[36];
};

struct Event {               // Fault Log / AFCS Fault Log row
  char label[LABEL_LEN + 1];
  char first[20];            // "2026-07-05 14:05:39"
  char last[20];             // "" when never repeated
  int  count;
  bool afcs;                 // label carries "FAIL CODE"
};

struct PaRow {               // Power Assurance Log row, same 16 columns as the app
  char col[PA_COLS][20];
};

struct ThSummary {
  int  frames;               // "TIME HISTORY #nnn" headers found
  int  framesWithData;       // frames whose first sample has a plausible timestamp
  int  samples;              // total 1 Hz rows
  char first[20];            // first / last sample timestamps
  char last[20];
};

struct Parsed {
  int       params;          // parameter catalog entries (exceedance dictionary)
  Row       cum[MAX_CUM];
  int       ncum;
  Event     ev[MAX_EVENTS];
  int       nev;
  PaRow     pa[MAX_PA];
  int       npa;
  ThSummary th;
};

// Decode a whole download held in memory. Sections that are absent leave
// their counts at zero; nothing is ever read past `len`.
void parse(const uint8_t* data, size_t len, Parsed& out);

}  // namespace hg6
