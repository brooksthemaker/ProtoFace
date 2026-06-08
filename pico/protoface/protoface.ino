// Protoface — Raspberry Pi Pico 2 / Pico 2 W (RP2350, Arduino/C++).
//
// Standalone HUB75 LED face: a C++ port of the CM5 Protoface pipeline driving
// the panel through Adafruit_Protomatter. Build with the arduino-pico core
// (Earle Philhower) targeting "Raspberry Pi Pico 2" / "Pico 2 W". Install the
// Adafruit_Protomatter + Adafruit_GFX libraries. Bake a face header first with
// tools/convert_assets.py (see README), then flash this sketch.

#include <Adafruit_Protomatter.h>

#include "config.h"
#include "Controls.h"
#include "FaceEngine.h"
#include "FaceState.h"
#include "Material.h"
#include "Particles.h"

static uint8_t rgbPins[] = RGB_PINS;
static uint8_t addrPins[] = ADDR_PINS;

Adafruit_Protomatter matrix(
    CANVAS_W, BIT_DEPTH,
    1, rgbPins,
    sizeof(addrPins), addrPins,
    CLOCK_PIN, LATCH_PIN, OE_PIN,
    true /* double-buffered */);

// RGB888 working canvas (composited here) + RGB565 buffer pushed to the panel.
static uint8_t canvas[CANVAS_W * CANVAS_H * 3];
static uint16_t canvas565[CANVAS_W * CANVAS_H];

static FaceState *state = nullptr;
static FaceEngine *engine = nullptr;
static Particles *particles = nullptr;

static uint8_t colorIdx = 0;
static Material material;
static uint32_t prevMicros = 0;

static inline uint16_t to565(uint8_t r, uint8_t g, uint8_t b) {
  return ((uint16_t)(r & 0xF8) << 8) | ((uint16_t)(g & 0xFC) << 3) | (b >> 3);
}

static void handleKey(char k) {
  switch (k) {
    case 'c': colorIdx = (colorIdx + 1) % NUM_MATERIAL_COLORS;
              material = materialByIndex(colorIdx); break;
    case 'v': colorIdx = (colorIdx + NUM_MATERIAL_COLORS - 1) % NUM_MATERIAL_COLORS;
              material = materialByIndex(colorIdx); break;
    case 'x': particles->setEffect((particles->effect() + 1) % Particles::numEffects());
              Serial.print("effect: "); Serial.println(Particles::effectName(particles->effect())); break;
    case 'z': particles->setEffect((particles->effect() + Particles::numEffects() - 1) % Particles::numEffects());
              Serial.print("effect: "); Serial.println(Particles::effectName(particles->effect())); break;
    case 'e': state->nextExpression(); break;
    case 'w': state->prevExpression(); break;
    case 'b': state->triggerBlink(); break;
    case '+': case '=':
      state->brightness = min(255, state->brightness + 16); break;
    case '-': case '_':
      state->brightness = max(16, state->brightness - 16); break;
    default: break;
  }
}

void setup() {
  Serial.begin(115200);

  ProtomatterStatus st = matrix.begin();
  if (st != PROTOMATTER_OK) {
    // Can't drive the panel — report on serial and halt (LED blink would need a pin).
    for (;;) {
      Serial.print("Protomatter init failed: ");
      Serial.println((int)st);
      delay(1000);
    }
  }

  state = new FaceState(ACTIVE_FACE.num_expr);
  state->brightness = DEFAULT_BRIGHTNESS;
  engine = new FaceEngine(ACTIVE_FACE, FACE_W, FACE_H, CANVAS_W, CANVAS_H, FACE_MIRROR);
  particles = new Particles(CANVAS_W, CANVAS_H);
  particles->setEffect(DEFAULT_EFFECT);

  material = Material{DEFAULT_MATERIAL_R, DEFAULT_MATERIAL_G, DEFAULT_MATERIAL_B};

  Serial.print("Protoface (Pico/C++) running: ");
  Serial.print(CANVAS_W); Serial.print("x"); Serial.print(CANVAS_H);
  Serial.print(" @ "); Serial.print(TARGET_FPS); Serial.println(" fps target");
  Serial.println("Keys: c/v colour  x/z effect  e/w expr  b blink  +/- bright");

  prevMicros = micros();
}

void loop() {
  uint32_t now = micros();
  float dt = (now - prevMicros) / 1000000.0f;
  prevMicros = now;
  if (dt > 0.1f) dt = 0.1f;

  char k = pollKey();
  if (k) handleKey(k);

  state->update(dt);
  engine->render(canvas, *state, material);
  particles->update(dt);
  particles->composite(canvas);

  // Pack RGB888 -> RGB565 and push to the panel.
  for (int i = 0; i < CANVAS_W * CANVAS_H; i++) {
    canvas565[i] = to565(canvas[i * 3], canvas[i * 3 + 1], canvas[i * 3 + 2]);
  }
  matrix.drawRGBBitmap(0, 0, canvas565, CANVAS_W, CANVAS_H);
  matrix.show();

  // Frame cap.
  float target = 1.0f / TARGET_FPS;
  float elapsed = (micros() - now) / 1000000.0f;
  if (elapsed < target) delay((uint32_t)((target - elapsed) * 1000.0f));
}
