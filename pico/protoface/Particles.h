// Particle overlay — C++ port of the CM5 particles, composited with additive
// blending into the RGB888 canvas (the per-pixel work that was the risk in the
// interpreted runtimes is trivial here).
//
// Phase 2 will extend this toward the full multi-layer system + presets; this
// is a single-layer effect table covering the common effects.
#pragma once
#include <Arduino.h>

#define MAX_PARTICLES 64

struct Particle {
  float x, y, vx, vy, life, maxlife;
  uint8_t r, g, b, size;
  bool alive;
};

class Particles {
 public:
  Particles(uint16_t w, uint16_t h);

  void setEffect(uint8_t idx);
  uint8_t effect() const { return effect_; }
  static const char *effectName(uint8_t idx);
  static uint8_t numEffects();

  void update(float dt);
  // Additive-blend live particles into an RGB888 canvas (w*h*3, row-major).
  void composite(uint8_t *canvas) const;

 private:
  void spawn();

  uint16_t w_, h_;
  uint8_t effect_ = 0;
  Particle p_[MAX_PARTICLES];
  uint8_t count_ = 0;        // target population for the current effect
};
