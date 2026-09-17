// HGS Download Stick - board configuration.
//
// Target: Waveshare ESP32-S3-Touch-LCD-1.9 (SKU 30939)
//   ESP32-S3R8, 16 MB flash, 8 MB octal PSRAM
//   1.9" 170x320 ST7789V2 (SPI), CST816 touch, QMI8658 IMU (unused)
//   microSD on SDMMC 1-bit, MX1.25 LiPo charger, USB-C
//
// Pin map verified against the board pinout table and schematic. Do not copy
// the ESP32-S3-Touch-LCD-1.28 map onto this board: IO17 is TP_RESET here, so
// the old UART RX pin would fight the touch controller's reset line.
#pragma once

// --- DAU serial (via MAX3232 on the Pico-format carrier) --------------------
// Header pin 15 / 17 / 18. NOT UART0 (IO43/IO44 = header pins 1/2): the ROM
// bootloader prints its 115200 log there at every power-up, and that garbage
// would go straight into the DAU.
static const int PIN_DAU_TX = 16;
static const int PIN_DAU_RX = 18;
static const int PIN_FUNCTION_SEL = 15;   // header pin 14; unresolved, see HARDWARE.md
static const bool USE_FUNCTION_SEL = false;

// --- LCD: ST7789V2, SPI -----------------------------------------------------
static const int PIN_LCD_RST = 9;
static const int PIN_LCD_CLK = 10;
static const int PIN_LCD_DC  = 11;
static const int PIN_LCD_CS  = 12;
static const int PIN_LCD_DIN = 13;        // MOSI; panel is write-only, no MISO
static const int PIN_LCD_BL  = 14;
// The backlight switch is active-LOW on this board: with the pin driven HIGH
// the panel is dark, and it lights up when the pin floats (e.g. while RST is
// held). Observed on the assembled unit 2026-09-16.
static const bool LCD_BL_ACTIVE_LOW = true;

// 170-wide panel on a 240-wide controller: centre it or everything renders
// shifted. (240-170)/2 = 35.
static const int LCD_COL_OFFSET = 35;
static const int LCD_ROW_OFFSET = 0;
static const int LCD_ROTATION   = 1;      // landscape: 320 x 170

// --- Touch: CST816, I2C 0x15 (shared bus with the QMI8658 IMU) --------------
static const int PIN_TP_SDA = 47;
static const int PIN_TP_SCL = 48;
static const int PIN_TP_RST = 17;
static const int PIN_TP_INT = 21;         // RTC-capable, so it can wake deep sleep

// --- microSD: SDMMC 1-bit ---------------------------------------------------
// There is no CS line. The socket's CD/D3 goes to a 10K pull-up, not a GPIO,
// so SPI-mode SD is physically impossible on this board - SDIO only.
static const int PIN_SD_CMD = 39;
static const int PIN_SD_D0  = 40;
static const int PIN_SD_CLK = 41;

// --- Battery: ADC1_CH3 on IO4, divider x3 (confirmed against adc_bsp.c) -----
static const int PIN_BAT_ADC = 4;
static const float BAT_DIVIDER = 3.0f;

// --- behaviour --------------------------------------------------------------
static const uint32_t DAU_BAUD = 9600;            // 9600,n,8,1 per the original app
static const int LOW_BATT_PCT = 20;
static const uint32_t WATCHDOG_S = 30;
static const size_t DOWNLOAD_MIN_BYTES = 1000;    // smaller than this = suspect
static const uint32_t IDLE_SLEEP_MS = 120000;     // 0 disables (use while developing)
static const uint32_t ABORT_HOLD_MS = 1500;
