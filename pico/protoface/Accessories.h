// Addressable-LED accessories (cheek hubs, ears, accents) driven alongside the
// HUB75 face on the same Pico. Each "zone" is a WS2812/NeoPixel run on its own
// GPIO data pin, with a mode that ties it to the face so accents stay coherent
// with the expression/colour:
//
//   ACC_MATCH_FACE  solid current material colour (cheeks recolour with 'c'/'v')
//   ACC_BREATHE     material colour, slow brightness breathing
//   ACC_AUDIO       material colour, brightness from mouth_open (mic in Phase 4)
//   ACC_STATIC      a fixed colour set per zone
//
// Zones are defined in Accessories.cpp; enable with ACCESSORY_ENABLE in config.h.
#pragma once
#include <Arduino.h>
#include "Material.h"
#include "FaceState.h"

enum AccMode { ACC_MATCH_FACE, ACC_BREATHE, ACC_AUDIO, ACC_STATIC };

struct AccZoneCfg {
  uint8_t pin;     // GPIO data pin
  uint16_t count;  // number of LEDs in this zone
  AccMode mode;
  uint8_t r, g, b; // colour for ACC_STATIC
};

class Accessories {
 public:
  void begin();
  void update(float dt, const Material &mat, const FaceState &state);

 private:
  float t_ = 0.0f;
};
