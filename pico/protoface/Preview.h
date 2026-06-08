// In-helmet confirmation display — a colour SPI TFT (ST7789) that mirrors a
// scaled copy of the face canvas plus a status line (expression / effect /
// brightness). Intended to run on the RP2350's second core (core1) so the SPI
// refresh is decoupled from the face frame rate.
//
// Gated by PREVIEW_ENABLE in config.h; the display libraries are only pulled in
// when enabled. Header stays dependency-free so the sketch compiles without the
// TFT libraries when the preview is off.
#pragma once
#include <Arduino.h>

class Preview {
 public:
  void begin();
  // Push a scaled copy of an RGB888 canvas (w*h*3) + a status line. The status
  // text is redrawn only when it changes, to avoid flicker.
  void update(const uint8_t *canvas, uint16_t w, uint16_t h,
              const char *expr, uint8_t r, uint8_t g, uint8_t b,
              const char *effect, uint8_t brightness);
};
