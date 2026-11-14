// Storage + USB mass storage for the HGS Download Stick.
//
// Two backends, picked once at boot:
//   1. a TF card in the slot (1-bit SDMMC - the socket's CD/D3 goes to a 10K
//      pull-up rather than a GPIO, so there is no chip select and SPI-mode SD
//      is physically impossible on this board), or, when no card mounts,
//   2. the 9.9 MB "ffat" partition in internal flash, through the IDF
//      wear-levelling layer. No card is needed for normal use.
//
// USB: whichever medium mounted is exported to the PC with the ESP32-S3's
// native USB, so the stick enumerates as an ordinary flash drive - no
// drivers, nothing to install. Everything else in the firmware reaches the
// files through fs() and never needs to know which backend is underneath.
//
// Host/MCU arbitration: a FAT volume must never be written by the MCU and the
// host at the same time. During a download we report the media as absent, which
// makes the host drop its mount and re-read it afterwards. This is the same
// invariant boot.py enforced on CircuitPython, done by hand.
#pragma once

#include <stdint.h>
#include <stddef.h>
#include <FS.h>

namespace storage {

bool begin();                 // mount card or internal flash, start USB MSC
bool mounted();               // some backend is up
bool cardPresent();           // the card backend specifically
const char* backendName();    // "card" / "flash" / "none", for the log + screen
fs::FS& fs();                 // the mounted volume; only valid after begin()
uint64_t freeBytes();
uint32_t freeKb();
int downloadCount();          // number of *.HG6 files in the root

// Hand the volume to the MCU (false) or back to the PC (true).
void setHostAccess(bool allowed);

// "/DOWNLOAD_NN.HG6.PART" - the next unused partial name.
void nextPartName(char* out, size_t outLen);

// Rename a finished .PART to the HGS-style name the Windows app would have
// used: SSSSS_YYMMDD_An.HG6, read from the Cumulative Log block. Falls back to
// stripping ".PART" when the serial/date cannot be parsed. Returns the final
// name in `out`.
//
// `typeLetter` is the letter before the sequence number: 'A' for DOWNLOAD
// LOGS (what the Windows app writes). Cumulative-only and status downloads use
// 'C' and 'S' so they are distinguishable on the drive; those letters are our
// convention, the Windows app's naming for them has not been observed.
bool finalise(const char* partPath, char typeLetter, char* out, size_t outLen);

// Stored downloads ("/NAME.HG6"), newest name first (lexical, which orders the
// SSSSS_YYMMDD names by date). Returns how many were written to `names`.
static const size_t NAME_LEN = 32;
int listDownloads(char (*names)[NAME_LEN], int maxNames);

// Read a whole file into `buf` (at most `maxLen` bytes); `got` = bytes read.
bool readAll(const char* path, uint8_t* buf, size_t maxLen, size_t& got);

void removeFile(const char* path);
uint32_t fileSize(const char* path);


}  // namespace storage
