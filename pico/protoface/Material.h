// Material colour for the C++ face engine.
//
// On the CM5 the material is multiplied by face luminance per pixel; the engine
// here does the same in the tint stage. A material is just an RGB colour plus a
// small named palette matching the CM5 solo controls. (Scrolling/tiled PNG
// materials are a later phase.)
#pragma once
#include <Arduino.h>

struct Material {
  uint8_t r, g, b;
};

struct NamedColor {
  const char *name;
  uint8_t r, g, b;
};

// Matches the FACE_COLORS palette in the CM5 run.py.
static const NamedColor MATERIAL_COLORS[] = {
    {"teal", 0, 220, 180},   {"red", 255, 0, 0},     {"orange", 255, 110, 0},
    {"yellow", 255, 230, 0}, {"green", 0, 255, 0},   {"blue", 0, 90, 255},
    {"purple", 160, 0, 255}, {"magenta", 255, 0, 150}, {"white", 255, 255, 255},
};
static const uint8_t NUM_MATERIAL_COLORS =
    sizeof(MATERIAL_COLORS) / sizeof(MATERIAL_COLORS[0]);

inline Material materialByIndex(uint8_t i) {
  const NamedColor &c = MATERIAL_COLORS[i % NUM_MATERIAL_COLORS];
  Material m = {c.r, c.g, c.b};
  return m;
}
