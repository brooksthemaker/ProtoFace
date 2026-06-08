// Face asset format shared by the engine and the generated face headers.
//
// Faces are baked on the host (tools/convert_assets.py) into C headers: each
// expression / blink / mouth image becomes a pair of flat arrays — luminance
// (0..255, the CM5 RGB mean) and alpha (0..255 shape mask) — plus a FaceAsset
// describing the set. The engine tints luminance by the material colour and
// composites using alpha, matching the CM5 pipeline.
//
// Arrays are plain `const` so they live in memory-mapped flash on the RP2350;
// no PROGMEM / pgm_read needed with the arduino-pico core.
#pragma once
#include <Arduino.h>

struct FaceImage {
  const uint8_t *lum;    // w*h luminance
  const uint8_t *alpha;  // w*h alpha (shape mask)
};

// A rectangular region in face pixels: {x, y, w, h}. w<0 marks "unset".
struct FaceBox {
  int16_t x, y, w, h;
};

struct FaceAsset {
  uint16_t w, h;               // authored face size (half the canvas with mirror)
  uint8_t num_expr;            // number of expressions
  const char *const *names;    // expression names[num_expr]
  const FaceImage *expr;       // expression images[num_expr]
  bool has_blink;
  FaceImage blink;
  bool has_mouth;
  FaceImage mouth_open;
  FaceBox eye_l;               // w<0 if unset
  FaceBox eye_r;
  FaceBox mouth;
};
