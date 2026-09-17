#include "ui.h"

#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <string.h>

#include "config.h"

namespace ui {

// 170-wide glass on a 240-wide controller: without the 35-pixel column offset
// everything renders shifted. This is the classic ST7789 170x320 gotcha.
static Arduino_DataBus* bus = new Arduino_ESP32SPI(
    PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_CLK, PIN_LCD_DIN, GFX_NOT_DEFINED);
static Arduino_GFX* gfx = new Arduino_ST7789(
    bus, PIN_LCD_RST, LCD_ROTATION, true /* IPS */, 170, 320,
    LCD_COL_OFFSET, LCD_ROW_OFFSET, LCD_COL_OFFSET, LCD_ROW_OFFSET);

static const int W = 320, H = 170;

// Layout, landscape.
static const int TITLE_H  = 26;
static const int PANEL_X  = 8,  PANEL_Y = 44, PANEL_W = 304, PANEL_H = 84;
static const int LINE_X   = 16, LINE_Y  = 52, LINE_DY = 20;
static const int BAR_X    = 20, BAR_Y   = 134, BAR_W = 280, BAR_H = 14;
static const int HINT_Y   = 154;

static int barLast = -1;

static int centreX(const char* s, int size) {
  const int w = (int)strlen(s) * 6 * size;
  const int x = (W - w) / 2;
  return x < 0 ? 0 : x;
}

static void text(const char* s, int x, int y, uint16_t fg, uint16_t bg, int size) {
  gfx->setTextSize(size);
  gfx->setTextColor(fg, bg);
  gfx->setCursor(x, y);
  gfx->print(s);
}

void backlight(bool on) {
  const bool level = LCD_BL_ACTIVE_LOW ? !on : on;
  digitalWrite(PIN_LCD_BL, level ? HIGH : LOW);
}

bool begin() {
  pinMode(PIN_LCD_BL, OUTPUT);
  backlight(false);                       // off until something is drawn
  if (!gfx->begin()) return false;
  gfx->fillScreen(BG);
  backlight(true);
  return true;
}

static void titleBar() {
  gfx->fillRect(0, 0, W, TITLE_H, NAVY);
  text("A109S  HGS", centreX("A109S  HGS", 2), 5, WHITE, NAVY, 2);
}

void panel(const char* l0, const char* l1, const char* l2, const char* l3,
           uint16_t textColor) {
  gfx->fillRect(PANEL_X, PANEL_Y, PANEL_W, PANEL_H, WHITE);
  gfx->fillRect(PANEL_X, PANEL_Y, PANEL_W, 2, SHADOW);        // sunken edge
  gfx->fillRect(PANEL_X, PANEL_Y, 2, PANEL_H, SHADOW);

  const char* lines[4] = {l0, l1, l2, l3};
  for (int i = 0; i < 4; ++i) {
    if (!lines[i] || !lines[i][0]) continue;
    text(lines[i], LINE_X, LINE_Y + i * LINE_DY, textColor, WHITE, 2);
  }
}

void screen(const char* l0, const char* l1, const char* l2, const char* l3,
            const char* hint, uint16_t hintColor, uint16_t textColor) {
  gfx->fillScreen(BG);
  titleBar();
  text("Hgs Status:", 10, 32, BLACK, BG, 1);
  panel(l0, l1, l2, l3, textColor);
  barLast = -1;
  if (hint && hint[0]) text(hint, centreX(hint, 1), HINT_Y, hintColor, BG, 1);
}

void bar(int pct, bool visible) {
  if (!visible) {
    gfx->fillRect(BAR_X, BAR_Y, BAR_W, BAR_H, BG);
    barLast = -1;
    return;
  }
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  const int fill = BAR_W * pct / 100;
  if (fill == barLast) return;              // only redraw when it actually moves
  if (barLast < 0) gfx->fillRect(BAR_X, BAR_Y, BAR_W, BAR_H, 0x2104);   // track
  if (fill > 0) gfx->fillRect(BAR_X, BAR_Y, fill, BAR_H, CYAN);
  barLast = fill;
}

}  // namespace ui
