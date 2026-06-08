#include "Particles.h"

// emit: 0 random, 1 bottom, 2 top.
struct EffectDef {
  const char *name;
  uint8_t count;
  uint8_t emit;
  float grav;        // +y px/s^2
  float vmin, vmax;
  float life_min, life_max;
  uint8_t ncolors;
  uint8_t colors[4][3];
  uint8_t size;
};

static const EffectDef EFFECTS[] = {
    {"none", 0, 0, 0, 0, 0, 0, 0, 0, {{0, 0, 0}}, 1},
    {"sparkle", 10, 0, 0, 0, 0, 0.05f, 0.2f, 1, {{255, 255, 220}}, 1},
    {"embers", 28, 1, -10, 8, 22, 0.6f, 1.4f, 2,
     {{255, 60, 0}, {255, 110, 10}}, 1},
    {"snow", 30, 2, 12, 4, 10, 2.0f, 4.0f, 1, {{200, 220, 255}}, 1},
    {"rain", 32, 2, 60, 40, 80, 0.4f, 0.9f, 1, {{120, 160, 255}}, 2},
    {"confetti", 26, 2, 30, 10, 30, 1.0f, 2.0f, 4,
     {{255, 80, 80}, {80, 255, 120}, {90, 140, 255}, {255, 230, 90}}, 1},
    {"fireflies", 16, 0, 0, 2, 8, 1.0f, 2.5f, 1, {{180, 255, 120}}, 1},
};
static const uint8_t NUM_EFFECTS = sizeof(EFFECTS) / sizeof(EFFECTS[0]);

static float frand(float a, float b) {
  return a + (b - a) * (float)random(0, 10001) / 10000.0f;
}

Particles::Particles(uint16_t w, uint16_t h) : w_(w), h_(h) {
  for (uint8_t i = 0; i < MAX_PARTICLES; i++) p_[i].alive = false;
}

uint8_t Particles::numEffects() { return NUM_EFFECTS; }

const char *Particles::effectName(uint8_t idx) {
  return EFFECTS[idx % NUM_EFFECTS].name;
}

void Particles::setEffect(uint8_t idx) {
  effect_ = idx % NUM_EFFECTS;
  count_ = min((int)EFFECTS[effect_].count, MAX_PARTICLES);
  for (uint8_t i = 0; i < MAX_PARTICLES; i++) p_[i].alive = false;
}

void Particles::spawn() {
  const EffectDef &e = EFFECTS[effect_];
  for (uint8_t i = 0; i < MAX_PARTICLES; i++) {
    if (p_[i].alive) continue;
    Particle &q = p_[i];
    if (e.emit == 1) {  // bottom
      q.x = frand(0, w_); q.y = h_ - 1;
    } else if (e.emit == 2) {  // top
      q.x = frand(0, w_); q.y = 0;
    } else {  // random
      q.x = frand(0, w_); q.y = frand(0, h_);
    }
    float speed = frand(e.vmin, e.vmax);
    if (e.emit == 1) { q.vx = frand(-4, 4); q.vy = -speed; }
    else if (e.emit == 2) { q.vx = frand(-4, 4); q.vy = speed; }
    else {
      float a = frand(0, 2.0f * PI);
      q.vx = speed * cosf(a); q.vy = speed * sinf(a);
    }
    q.maxlife = frand(e.life_min, e.life_max);
    q.life = q.maxlife;
    uint8_t c = (uint8_t)random(0, e.ncolors);
    q.r = e.colors[c][0]; q.g = e.colors[c][1]; q.b = e.colors[c][2];
    q.size = e.size;
    q.alive = true;
    return;
  }
}

void Particles::update(float dt) {
  if (effect_ == 0) return;
  const EffectDef &e = EFFECTS[effect_];

  // Maintain population.
  uint8_t alive = 0;
  for (uint8_t i = 0; i < MAX_PARTICLES; i++) if (p_[i].alive) alive++;
  while (alive < count_) { spawn(); alive++; }

  for (uint8_t i = 0; i < MAX_PARTICLES; i++) {
    Particle &q = p_[i];
    if (!q.alive) continue;
    q.life -= dt;
    if (q.life <= 0.0f) { q.alive = false; continue; }
    q.vy += e.grav * dt;
    q.x += q.vx * dt;
    q.y += q.vy * dt;
    if (q.y < -2 || q.y > h_ + 2) q.alive = false;
  }
}

void Particles::composite(uint8_t *canvas) const {
  if (effect_ == 0) return;
  for (uint8_t i = 0; i < MAX_PARTICLES; i++) {
    const Particle &q = p_[i];
    if (!q.alive) continue;
    // Fade brightness over the particle's lifetime.
    float f = q.life / (q.maxlife > 0.0f ? q.maxlife : 1.0f);
    if (f > 1.0f) f = 1.0f;
    int cx = (int)q.x, cy = (int)q.y;
    int s = q.size;
    for (int dy = -s + 1; dy < s; dy++) {
      int y = cy + dy;
      if (y < 0 || y >= h_) continue;
      for (int dx = -s + 1; dx < s; dx++) {
        int x = cx + dx;
        if (x < 0 || x >= w_) continue;
        uint8_t *px = canvas + (y * w_ + x) * 3;
        int nr = px[0] + (int)(q.r * f);
        int ng = px[1] + (int)(q.g * f);
        int nb = px[2] + (int)(q.b * f);
        px[0] = nr > 255 ? 255 : nr;
        px[1] = ng > 255 ? 255 : ng;
        px[2] = nb > 255 ? 255 : nb;
      }
    }
  }
}
