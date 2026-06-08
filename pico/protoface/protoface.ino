// Protoface — Raspberry Pi Pico 2 / Pico 2 W (RP2350, Arduino/C++).
//
// Standalone HUB75 LED face: a C++ port of the CM5 Protoface pipeline driving
// the panel through Adafruit_Protomatter. Build with the arduino-pico core
// (Earle Philhower) targeting "Raspberry Pi Pico 2" / "Pico 2 W". Install the
// Adafruit_Protomatter + Adafruit_GFX libraries. Bake a face header first with
// tools/convert_assets.py (see README), then flash this sketch.

#include <Adafruit_Protomatter.h>

#include "config.h"
#include "Accessories.h"
#include "Controls.h"
#include "FaceEngine.h"
#include "FaceState.h"
#include "Inputs.h"
#include "Material.h"
#include "Particles.h"
#include "Preview.h"

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

#if ACCESSORY_ENABLE
static Accessories accessories;
#endif
static Inputs inputs;
#if PREVIEW_ENABLE
static Preview preview;
#endif

static inline uint16_t to565(uint8_t r, uint8_t g, uint8_t b) {
  return ((uint16_t)(r & 0xF8) << 8) | ((uint16_t)(g & 0xFC) << 3) | (b >> 3);
}

// Shared action handler — both serial keys and physical buttons route here.
static void doAction(BtnAction a, uint8_t param) {
  switch (a) {
    case BTN_NEXT_COLOR: colorIdx = (colorIdx + 1) % NUM_MATERIAL_COLORS;
      material = materialByIndex(colorIdx); break;
    case BTN_PREV_COLOR: colorIdx = (colorIdx + NUM_MATERIAL_COLORS - 1) % NUM_MATERIAL_COLORS;
      material = materialByIndex(colorIdx); break;
    case BTN_NEXT_EFFECT:
      particles->setEffect((particles->effect() + 1) % Particles::numEffects());
      Serial.print("effect: "); Serial.println(Particles::effectName(particles->effect())); break;
    case BTN_PREV_EFFECT:
      particles->setEffect((particles->effect() + Particles::numEffects() - 1) % Particles::numEffects());
      Serial.print("effect: "); Serial.println(Particles::effectName(particles->effect())); break;
    case BTN_NEXT_EXPR: state->nextExpression(); break;
    case BTN_PREV_EXPR: state->prevExpression(); break;
    case BTN_SET_EXPR: state->setExpression(param); break;
    case BTN_BLINK: state->triggerBlink(); break;
    case BTN_BRIGHT_UP: state->brightness = min(255, state->brightness + 16); break;
    case BTN_BRIGHT_DOWN: state->brightness = max(16, state->brightness - 16); break;
    default: break;
  }
}

static void handleKey(char k) {
  switch (k) {
    case 'c': doAction(BTN_NEXT_COLOR, 0); break;
    case 'v': doAction(BTN_PREV_COLOR, 0); break;
    case 'x': doAction(BTN_NEXT_EFFECT, 0); break;
    case 'z': doAction(BTN_PREV_EFFECT, 0); break;
    case 'e': doAction(BTN_NEXT_EXPR, 0); break;
    case 'w': doAction(BTN_PREV_EXPR, 0); break;
    case 'b': doAction(BTN_BLINK, 0); break;
    case '+': case '=': doAction(BTN_BRIGHT_UP, 0); break;
    case '-': case '_': doAction(BTN_BRIGHT_DOWN, 0); break;
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

#if ACCESSORY_ENABLE
  accessories.begin();
#endif
  inputs.begin();

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

  // Physical inputs: applies boop + light to state, returns a button action.
  uint8_t bparam = 0;
  BtnAction act = inputs.poll(*state, &bparam);
  if (act != BTN_NONE) doAction(act, bparam);

  state->update(dt);
  engine->render(canvas, *state, material);
  particles->update(dt);
  particles->composite(canvas);

#if ACCESSORY_ENABLE
  accessories.update(dt, material, *state);
#endif

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

// ── Core 1: in-helmet preview display ───────────────────────────────────────
// Runs the SPI TFT mirror on the second core so its refresh never stalls the
// face loop on core 0. Reads the shared canvas/state at its own capped rate;
// brief tearing is harmless for a monitor.
#if PREVIEW_ENABLE
void setup1() { preview.begin(); }

void loop1() {
  static uint32_t last = 0;
  uint32_t now = millis();
  if (now - last < (uint32_t)(1000 / PREVIEW_FPS)) return;
  last = now;

  // state/particles are built in core 0's setup(); skip until they exist.
  if (!state || !particles) return;

  const char *expr = ACTIVE_FACE.names[state->expression()];
  const char *fx = Particles::effectName(particles->effect());
  preview.update(canvas, CANVAS_W, CANVAS_H, expr,
                 material.r, material.g, material.b, fx, state->brightness);
}
#endif
