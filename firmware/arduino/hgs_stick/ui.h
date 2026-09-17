// Screen for the HGS Download Stick, styled after the Windows HGS app: navy
// title bar, a sunken "Hgs Status" panel, and the app's own phase strings.
//
// The 1.9" panel is 170x320 portrait, driven here at rotation 1 => 320x170
// landscape, which fits the app's rectangular status panel far better than the
// round 1.28" board ever did.
#pragma once

#include <stdint.h>

namespace ui {

// Win9x-ish palette, RGB565.
static const uint16_t BG     = 0xC618;   // face gray
static const uint16_t NAVY   = 0x0010;   // title bar
static const uint16_t WHITE  = 0xFFFF;
static const uint16_t BLACK  = 0x0000;
static const uint16_t GREEN  = 0x07E0;
static const uint16_t RED    = 0xF800;
static const uint16_t AMBER  = 0xFD20;
static const uint16_t CYAN   = 0x07FF;
static const uint16_t SHADOW = 0x8410;

bool begin();
void backlight(bool on);

// Full repaint: title bar + status panel + optional hint line.
void screen(const char* l0, const char* l1 = "", const char* l2 = "",
            const char* l3 = "", const char* hint = 0,
            uint16_t hintColor = BLACK, uint16_t textColor = BLACK);

// Repaint just the panel text - no flicker during a download.
void panel(const char* l0, const char* l1 = "", const char* l2 = "",
           const char* l3 = "", uint16_t textColor = BLACK);

// Progress bar. Only the columns that actually changed are redrawn.
void bar(int pct, bool visible = true);

}  // namespace ui
