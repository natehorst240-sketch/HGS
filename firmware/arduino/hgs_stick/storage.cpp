#include "storage.h"

#include <Arduino.h>
#include <FS.h>
#include <vfs_api.h>
#include <SD_MMC.h>
#include <USB.h>
#include <USBMSC.h>
#include <esp_vfs_fat.h>
#include <wear_levelling.h>
#include <string.h>
#include <stdio.h>
#include <ctype.h>

#include "config.h"

// TinyUSB entry points we need but the Arduino USB wrapper does not expose.
// Declared rather than #included: pulling in tusb.h from a sketch drags in the
// whole device config, and these three symbols are already linked in by the
// core's USB stack.
extern "C" bool tud_disconnect(void);
extern "C" bool tud_connect(void);
extern "C" bool tud_msc_set_sense(uint8_t lun, uint8_t sense_key,
                                  uint8_t add_sense_code,
                                  uint8_t add_sense_qualifier);

// SCSI: NOT READY TO READY CHANGE, MEDIUM MAY HAVE CHANGED. This is the
// condition a card reader raises when a new card goes in, and it is what tells
// a host to throw away its cached FAT.
static const uint8_t SENSE_UNIT_ATTENTION = 0x06;
static const uint8_t ASC_MEDIUM_CHANGED   = 0x28;

// Internal flash: the "ffat" partition from app3M_fat9M_16MB.csv (9.9 MB),
// mounted through the IDF wear-levelling layer. FAT sector == wear-levelling
// sector == 4096 bytes on this core (CONFIG_WL_SECTOR_SIZE / FATFS_SECTOR_4096),
// and that is also the block size the host is shown, so one USB block maps to
// exactly one erase-and-write on flash with no read-modify-write in the common
// case. This is the same layout Espressif's tusb_msc example uses for a
// flash-backed drive, and Windows, macOS and Linux all accept 4 KB blocks.
static const char* FLASH_MOUNT = "/ffat";
static const char* FLASH_LABEL = "ffat";
static const size_t FLASH_MAX_FILES = 8;

// The Arduino FS wrapper around a VFS mount point. F_Fat does exactly this but
// keeps its wear-levelling handle private, and the USB callbacks need it.
class FlashFs : public fs::FS {
 public:
  FlashFs() : fs::FS(FSImplPtr(new VFSImpl())) {}
  void setMountPoint(const char* mp) { _impl->mountpoint(mp); }
};

namespace storage {

static USBMSC msc;
static FlashFs flashFs;
static wl_handle_t wl = WL_INVALID_HANDLE;
static fs::FS* vol = nullptr;               // whichever backend mounted
static bool onCard = false;
static bool hostAllowed = true;
static uint32_t blockSize = 512;
static uint32_t blockCount = 0;
static uint8_t blockBuf[4096];              // >= max(512, wl sector)

bool mounted() { return vol != nullptr; }
bool usingCard() { return onCard; }
const char* backendName() { return !mounted() ? "none" : (onCard ? "card" : "flash"); }

fs::FS& fs() { return *vol; }

// --- raw block access, backend-neutral --------------------------------------
static bool readBlock(uint32_t block, uint8_t* dst) {
  if (onCard) return SD_MMC.readRAW(dst, block);
  return wl_read(wl, (size_t)block * blockSize, dst, blockSize) == ESP_OK;
}

static bool writeBlock(uint32_t block, const uint8_t* src) {
  if (onCard) return SD_MMC.writeRAW(const_cast<uint8_t*>(src), block);
  const size_t addr = (size_t)block * blockSize;
  if (wl_erase_range(wl, addr, blockSize) != ESP_OK) return false;
  return wl_write(wl, addr, src, blockSize) == ESP_OK;
}

// --- USB mass storage callbacks ---------------------------------------------
// These hand the host raw blocks straight off the medium. The card path uses
// the arduino-esp32 SD_MMC raw-sector API (readRAW/writeRAW/numSectors); it is
// present in 2.0.x and 3.x but has moved before, so it is the first thing to
// check if the drive never enumerates with a card in.
static int32_t mscRead(uint32_t lba, uint32_t offset, void* buffer, uint32_t bufsize) {
  if (!mounted()) return -1;
  uint8_t* dst = static_cast<uint8_t*>(buffer);
  uint32_t done = 0;
  while (done < bufsize) {
    const uint32_t block = lba + (offset + done) / blockSize;
    const uint32_t off   = (offset + done) % blockSize;
    if (!readBlock(block, blockBuf)) return -1;
    uint32_t n = blockSize - off;
    if (n > bufsize - done) n = bufsize - done;
    memcpy(dst + done, blockBuf + off, n);
    done += n;
  }
  return static_cast<int32_t>(bufsize);
}

static int32_t mscWrite(uint32_t lba, uint32_t offset, uint8_t* buffer, uint32_t bufsize) {
  if (!mounted() || !hostAllowed) return -1;
  uint32_t done = 0;
  while (done < bufsize) {
    const uint32_t block = lba + (offset + done) / blockSize;
    const uint32_t off   = (offset + done) % blockSize;
    uint32_t n = blockSize - off;
    if (n > bufsize - done) n = bufsize - done;
    if (n == blockSize) {
      memcpy(blockBuf, buffer + done, blockSize);
    } else {                                   // partial block: read-modify-write
      if (!readBlock(block, blockBuf)) return -1;
      memcpy(blockBuf + off, buffer + done, n);
    }
    if (!writeBlock(block, blockBuf)) return -1;
    done += n;
  }
  return static_cast<int32_t>(bufsize);
}

static bool mscStartStop(uint8_t, bool, bool load_eject) {
  return true;                                  // allow the host to eject
}

// --- mounting ---------------------------------------------------------------
static bool mountCard() {
  SD_MMC.setPins(PIN_SD_CLK, PIN_SD_CMD, PIN_SD_D0);
  // 1-bit mode, and never format on mount failure: this is a maintainer's card
  // and silently reformatting it would be unforgivable.
  if (!SD_MMC.begin("/sdcard", true /* mode1bit */, false /* format */)) return false;
  vol = &SD_MMC;
  onCard = true;
  blockSize = 512;
  blockCount = SD_MMC.numSectors();
  return true;
}

static bool mountFlash() {
  // Formatting on first use is fine here, unlike the card: the partition is
  // ours, it ships blank, and nothing else ever writes it.
  esp_vfs_fat_mount_config_t conf = {};
  conf.format_if_mount_failed = true;
  conf.max_files = FLASH_MAX_FILES;
  conf.allocation_unit_size = CONFIG_WL_SECTOR_SIZE;
  conf.disk_status_check_enable = false;
  conf.use_one_fat = false;
  const esp_err_t err = esp_vfs_fat_spiflash_mount_rw_wl(FLASH_MOUNT, FLASH_LABEL, &conf, &wl);
  if (err != ESP_OK) {
    log_e("ffat mount failed: %d", (int)err);
    wl = WL_INVALID_HANDLE;
    return false;
  }
  flashFs.setMountPoint(FLASH_MOUNT);
  vol = &flashFs;
  onCard = false;
  blockSize = wl_sector_size(wl);
  if (blockSize == 0 || blockSize > sizeof(blockBuf)) {
    log_e("unexpected wl sector size %u", (unsigned)blockSize);
    esp_vfs_fat_spiflash_unmount_rw_wl(FLASH_MOUNT, wl);
    wl = WL_INVALID_HANDLE;
    vol = nullptr;
    return false;
  }
  blockCount = wl_size(wl) / blockSize;
  return true;
}

static void unmountVolume() {
  if (!mounted()) return;
  if (onCard) {
    SD_MMC.end();
  } else {
    esp_vfs_fat_spiflash_unmount_rw_wl(FLASH_MOUNT, wl);
    wl = WL_INVALID_HANDLE;
    flashFs.setMountPoint(NULL);
  }
  vol = nullptr;
}

// Drop the MCU-side FATFS cache and re-read the volume. Used when the volume
// changes hands: the host may have deleted or added files while it owned the
// medium, and FATFS would otherwise trust its cached FAT/directory sectors.
static bool remountVolume() {
  const bool wasCard = onCard;
  unmountVolume();
  return wasCard ? mountCard() : mountFlash();
}

bool begin() {
  if (!mountCard() && !mountFlash()) return false;

  msc.vendorID("HGS");
  msc.productID(onCard ? "Download Stick" : "Stick (flash)");
  msc.productRevision("1.0");
  msc.onRead(mscRead);
  msc.onWrite(mscWrite);
  msc.onStartStop(mscStartStop);
  msc.mediaPresent(true);
  msc.begin(blockCount, static_cast<uint16_t>(blockSize));
  USB.begin();
  return true;
}

bool cardPresent() { return onCard; }

uint64_t freeBytes() {
  if (!mounted()) return 0;
  if (onCard) return SD_MMC.totalBytes() - SD_MMC.usedBytes();
  uint64_t total = 0, free = 0;
  if (esp_vfs_fat_info(FLASH_MOUNT, &total, &free) != ESP_OK) return 0;
  return free;
}

uint32_t freeKb() { return static_cast<uint32_t>(freeBytes() / 1024); }

// Hand the volume to the MCU (false) or back to the PC (true).
//
// This used to rely on mediaPresent() alone. It does not do enough:
// USBMSC::mediaPresent() sets one bool that TEST UNIT READY reports, and never
// raises a SCSI unit attention - so a host is told the medium went away but is
// never told it changed, and whether it re-reads the FAT is left to the OS.
// Espressif's own MSC example is a RAM disk that sets it once and never toggles
// it; there is no shipped example of live sharing.
//
// So we detach from the USB bus outright. The host sees a device removal and
// unmounts; on re-attach it enumerates from scratch, which forces a completely
// fresh read of the volume. That is the software equivalent of unplugging the
// stick, and it is a defined USB operation rather than a hope about caching.
// With no host attached (on battery at the aircraft) both calls are no-ops.
//
// The mirror-image problem - the MCU trusting a FAT the host has since
// rewritten - is handled by remounting our side once the host is off the bus.
void setHostAccess(bool allowed) {
  hostAllowed = allowed;
  if (!allowed) {
    msc.mediaPresent(false);          // belt: refuse reads/writes immediately
    tud_disconnect();                 // braces: leave the bus entirely
    delay(50);                        // let the host see the detach
    if (!remountVolume()) log_e("remount for MCU access failed");
    return;
  }
  msc.mediaPresent(true);
  // Announce the medium changed, for any host that stayed attached.
  tud_msc_set_sense(0, SENSE_UNIT_ATTENTION, ASC_MEDIUM_CHANGED, 0x00);
  tud_connect();
}

static bool endsWithNoCase(const char* s, const char* suffix) {
  const size_t ls = strlen(s), lx = strlen(suffix);
  if (ls < lx) return false;
  for (size_t i = 0; i < lx; ++i) {
    if (toupper(s[ls - lx + i]) != toupper(suffix[i])) return false;
  }
  return true;
}

int downloadCount() {
  if (!mounted()) return 0;
  File root = vol->open("/");
  if (!root) return 0;
  int n = 0;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    if (endsWithNoCase(f.name(), ".HG6")) n++;
    f.close();
  }
  root.close();
  return n;
}

void nextPartName(char* out, size_t outLen) {
  for (int n = 1; n < 100; ++n) {
    snprintf(out, outLen, "/DOWNLOAD_%02d.HG6.PART", n);
    if (!vol->exists(out)) {
      char finished[40];
      snprintf(finished, sizeof(finished), "/DOWNLOAD_%02d.HG6", n);
      if (!vol->exists(finished)) return;
    }
  }
  snprintf(out, outLen, "/DOWNLOAD_XX.HG6.PART");
}

static uint8_t bcd(uint8_t b) { return (b >> 4) * 10 + (b & 0x0F); }

// The aircraft serial and date live in the Cumulative Log block (BCD) - see
// FORMAT.md section 2. Same parse as hgs_basename() in the Python firmware.
//
// The block is not at a fixed offset: it follows the parameter catalog and the
// fault logs, and in real downloads it has been seen at ~26 KB. So the file is
// streamed through in 4 KB chunks with a carry-over, rather than assuming it
// fits in some fixed-size head buffer (a 16 KB head is exactly how the first
// board build ended up naming everything DOWNLOAD_NN).
static const char   CL_MARKER[]   = "CUMULATIVE LOG";
static const size_t CL_MARKER_LEN = sizeof(CL_MARKER) - 1;
static const size_t CL_LABEL_LEN  = 25;                 // space-padded label
static const size_t CL_NEED       = CL_LABEL_LEN + 16;  // label + date/time/sn
static const size_t CL_SCAN_LIMIT = 256 * 1024;         // give up past this
static const size_t CL_CHUNK      = 4096;
static const size_t CL_CARRY      = 64;                 // >= CL_NEED

// Parses the block at `blk` (pointing at the label). Returns false if the
// date bytes are not a plausible BCD date or the S/N is blank.
static bool parseCumulative(const uint8_t* blk, char* out, size_t outLen) {
  const uint8_t* p = blk + CL_LABEL_LEN;
  const uint8_t yy = bcd(p[0]), mm = bcd(p[1]), dd = bcd(p[2]);
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return false;

  char sn[6] = {0};
  memcpy(sn, p + 11, 5);
  for (int i = 4; i >= 0; --i) {                        // trim trailing spaces
    if (sn[i] == ' ') sn[i] = 0; else break;
  }
  if (!sn[0]) return false;

  snprintf(out, outLen, "%s_%02u%02u%02u", sn, yy, mm, dd);
  return true;
}

static bool hgsBasename(const char* partPath, char* out, size_t outLen) {
  File f = vol->open(partPath, FILE_READ);
  if (!f) return false;

  static uint8_t buf[CL_CHUNK + CL_CARRY];
  size_t carry = 0;
  size_t scanned = 0;
  bool found = false;
  while (!found && scanned < CL_SCAN_LIMIT) {
    const size_t got = f.read(buf + carry, CL_CHUNK);
    if (got == 0) break;
    const size_t len = carry + got;
    for (size_t i = 0; i + CL_NEED <= len; ++i) {
      if (memcmp(buf + i, CL_MARKER, CL_MARKER_LEN) != 0) continue;
      found = parseCumulative(buf + i, out, outLen);
      break;                                            // first label wins
    }
    scanned += got;
    // Keep the tail so a label straddling two chunks is still seen whole.
    carry = len < CL_CARRY ? len : CL_CARRY;
    memmove(buf, buf + len - carry, carry);
  }
  f.close();
  return found;
}

bool finalise(const char* partPath, char typeLetter, char* out, size_t outLen) {
  char base[32];
  if (!hgsBasename(partPath, base, sizeof(base))) {
    // strip ".PART"
    snprintf(out, outLen, "%s", partPath);
    const size_t n = strlen(out);
    if (n > 5) out[n - 5] = 0;
    return vol->rename(partPath, out);
  }
  for (int n = 1; n < 100; ++n) {
    snprintf(out, outLen, "/%s_%c%d.HG6", base, typeLetter, n);
    if (!vol->exists(out)) return vol->rename(partPath, out);
  }
  return false;
}

int listDownloads(char (*names)[NAME_LEN], int maxNames) {
  if (!mounted() || maxNames <= 0) return 0;
  File root = vol->open("/");
  if (!root) return 0;
  int n = 0;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    const char* nm = f.name();
    if (nm[0] == '/') nm++;                       // core versions differ here
    if (endsWithNoCase(nm, ".HG6")) {
      char cand[NAME_LEN];
      snprintf(cand, sizeof(cand), "/%s", nm);
      // insertion sort, descending, so the newest SSSSS_YYMMDD name is first
      int pos = n < maxNames ? n : maxNames - 1;
      if (n >= maxNames && strcmp(cand, names[pos]) <= 0) { f.close(); continue; }
      while (pos > 0 && strcmp(cand, names[pos - 1]) > 0) {
        memcpy(names[pos], names[pos - 1], NAME_LEN);
        pos--;
      }
      memcpy(names[pos], cand, NAME_LEN);
      if (n < maxNames) n++;
    }
    f.close();
  }
  root.close();
  return n;
}

bool readAll(const char* path, uint8_t* buf, size_t maxLen, size_t& got) {
  got = 0;
  if (!mounted()) return false;
  File f = vol->open(path, FILE_READ);
  if (!f) return false;
  while (got < maxLen) {
    const size_t n = f.read(buf + got, maxLen - got);
    if (n == 0) break;
    got += n;
  }
  const bool complete = (f.available() == 0);
  f.close();
  return complete;
}

void removeFile(const char* path) { if (mounted()) vol->remove(path); }

uint32_t fileSize(const char* path) {
  if (!mounted()) return 0;
  File f = vol->open(path, FILE_READ);
  if (!f) return 0;
  const uint32_t n = f.size();
  f.close();
  return n;
}


}  // namespace storage
