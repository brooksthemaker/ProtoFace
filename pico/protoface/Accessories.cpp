#include "config.h"

#if ACCESSORY_ENABLE
#include "Accessories.h"
#include <Adafruit_NeoPixel.h>

// ── Edit your addressable-LED zones here ────────────────────────────────────
// Each row: { GPIO data pin, LED count, mode, r, g, b }
//   modes: ACC_MATCH_FACE  ACC_BREATHE  ACC_AUDIO  ACC_STATIC
// r,g,b are only used by ACC_STATIC. Pick data pins NOT used by HUB75
// (GP0-GP13 are taken by the panel) — e.g. GP16, GP17, GP18...
static AccZoneCfg ZONES[] = {
    {16, 7, ACC_MATCH_FACE, 0, 0, 0},  // left cheek hub
    {17, 7, ACC_MATCH_FACE, 0, 0, 0},  // right cheek hub
};
static const uint8_t NUM_ZONES = sizeof(ZONES) / sizeof(ZONES[0]);

static Adafruit_NeoPixel *strips[NUM_ZONES];

void Accessories::begin() {
  for (uint8_t i = 0; i < NUM_ZONES; i++) {
    strips[i] = new Adafruit_NeoPixel(ZONES[i].count, ZONES[i].pin,
                                      NEO_GRB + NEO_KHZ800);
    strips[i]->begin();
    strips[i]->clear();
    strips[i]->show();
  }
}

void Accessories::update(float dt, const Material &mat, const FaceState &state) {
  t_ += dt;
  float bscale = state.brightness / 255.0f;

  for (uint8_t i = 0; i < NUM_ZONES; i++) {
    const AccZoneCfg &z = ZONES[i];
    uint8_t r = mat.r, g = mat.g, b = mat.b;
    float k = bscale;

    switch (z.mode) {
      case ACC_BREATHE: {
        float br = 0.35f + 0.65f * (0.5f + 0.5f * sinf(2.0f * PI * 0.25f * t_));
        k *= br;
      } break;
      case ACC_AUDIO:
        k *= 0.2f + 0.8f * state.mouth_open;
        break;
      case ACC_STATIC:
        r = z.r; g = z.g; b = z.b;
        break;
      case ACC_MATCH_FACE:
      default:
        break;
    }

    uint32_t c = strips[i]->Color((uint8_t)(r * k), (uint8_t)(g * k),
                                  (uint8_t)(b * k));
    for (uint16_t p = 0; p < z.count; p++) strips[i]->setPixelColor(p, c);
    strips[i]->show();
  }
}

#endif  // ACCESSORY_ENABLE
