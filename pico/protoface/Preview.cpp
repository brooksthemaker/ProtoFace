#include "config.h"

#if PREVIEW_ENABLE
#include "Preview.h"
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

// Hardware SPI0 (SCK=GP18, MOSI=GP19 on the arduino-pico default mapping).
static Adafruit_ST7789 tft(&SPI, PREVIEW_CS, PREVIEW_DC, PREVIEW_RST);

// Pre-scaled RGB565 image of the face, drawn in one block transfer.
static uint16_t scaled[(CANVAS_W * PREVIEW_SCALE) * (CANVAS_H * PREVIEW_SCALE)];
static char last_status[64] = {0};

static inline uint16_t to565(uint8_t r, uint8_t g, uint8_t b) {
  return ((uint16_t)(r & 0xF8) << 8) | ((uint16_t)(g & 0xFC) << 3) | (b >> 3);
}

void Preview::begin() {
#if PREVIEW_BL >= 0
  pinMode(PREVIEW_BL, OUTPUT);
  digitalWrite(PREVIEW_BL, HIGH);
#endif
  tft.init(240, 320);  // native panel resolution
  tft.setRotation(PREVIEW_ROTATION);
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextSize(2);
}

void Preview::update(const uint8_t *canvas, uint16_t w, uint16_t h,
                     const char *expr, uint8_t r, uint8_t g, uint8_t b,
                     const char *effect, uint8_t brightness) {
  const int S = PREVIEW_SCALE;
  const int sw = w * S, sh = h * S;

  // Nearest-neighbour upscale into the RGB565 buffer.
  for (int y = 0; y < h; y++) {
    for (int x = 0; x < w; x++) {
      const uint8_t *px = canvas + (y * w + x) * 3;
      uint16_t c = to565(px[0], px[1], px[2]);
      for (int dy = 0; dy < S; dy++) {
        uint16_t *row = scaled + (y * S + dy) * sw + x * S;
        for (int dx = 0; dx < S; dx++) row[dx] = c;
      }
    }
  }

  int ox = (PREVIEW_W - sw) / 2;
  if (ox < 0) ox = 0;
  const int oy = 24;
  tft.drawRGBBitmap(ox, oy, scaled, sw, sh);

  // Status line — redraw only on change to avoid flicker.
  char status[64];
  snprintf(status, sizeof(status), "%s  fx:%s  b:%d",
           expr ? expr : "", effect ? effect : "", brightness);
  if (strcmp(status, last_status) != 0) {
    strncpy(last_status, status, sizeof(last_status) - 1);
    tft.fillRect(0, oy + sh + 12, PREVIEW_W, 28, ST77XX_BLACK);
    tft.setCursor(6, oy + sh + 14);
    tft.setTextColor(to565(r, g, b), ST77XX_BLACK);
    tft.print(status);
  }
}

#endif  // PREVIEW_ENABLE
