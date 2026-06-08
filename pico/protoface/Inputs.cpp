#include "Inputs.h"
#include "config.h"

// ── Button table (edit for your wiring) ─────────────────────────────────────
// Each row: { GPIO pin, action, param, active_low }
//   actions: BTN_NEXT_EXPR BTN_PREV_EXPR BTN_SET_EXPR(param=expr index)
//            BTN_BLINK BTN_NEXT_COLOR BTN_PREV_COLOR
//            BTN_NEXT_EFFECT BTN_PREV_EFFECT BTN_BRIGHT_UP BTN_BRIGHT_DOWN
// active_low = wired button -> GND (uses the internal pull-up). Pick free pins
// (GP0-GP13 are HUB75); GP14/GP15 shown here.
#if BUTTONS_ENABLE
static BtnCfg BUTTONS[] = {
    {14, BTN_NEXT_EXPR, 0, true},   // next emote
    {15, BTN_PREV_EXPR, 0, true},   // previous emote
};
static const uint8_t NUM_BUTTONS = sizeof(BUTTONS) / sizeof(BUTTONS[0]);

struct BtnState { bool last; bool stable; uint32_t t; };
static BtnState bstate[NUM_BUTTONS];
#endif

#if BOOP_ENABLE
static bool boop_last = false, boop_stable = false;
static uint32_t boop_t = 0;
#endif

#if LIGHT_ENABLE
static float light_ema = -1.0f;
#endif

void Inputs::begin() {
#if BUTTONS_ENABLE
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    pinMode(BUTTONS[i].pin, BUTTONS[i].active_low ? INPUT_PULLUP : INPUT_PULLDOWN);
    bool raw = digitalRead(BUTTONS[i].pin);
    bstate[i].last = bstate[i].stable =
        BUTTONS[i].active_low ? !raw : raw;
    bstate[i].t = millis();
  }
#endif
#if BOOP_ENABLE
  pinMode(BOOP_PIN, BOOP_ACTIVE_LOW ? INPUT_PULLUP : INPUT_PULLDOWN);
#endif
}

BtnAction Inputs::poll(FaceState &state, uint8_t *param) {
  *param = 0;
  (void)state;

#if LIGHT_ENABLE
  {
    float raw = (float)analogRead(LIGHT_PIN);
    float n = (raw - LIGHT_RAW_DARK) /
              (float)(LIGHT_RAW_BRIGHT - LIGHT_RAW_DARK);
    if (n < 0) n = 0;
    if (n > 1) n = 1;
    float target = LIGHT_MIN_BRIGHT + n * (LIGHT_MAX_BRIGHT - LIGHT_MIN_BRIGHT);
    if (light_ema < 0) light_ema = target;
    light_ema += LIGHT_SMOOTH * (target - light_ema);
    state.brightness = (uint8_t)(light_ema + 0.5f);
  }
#endif

#if BOOP_ENABLE
  {
    bool raw = digitalRead(BOOP_PIN);
    bool active = BOOP_ACTIVE_LOW ? !raw : raw;
    if (active != boop_last) { boop_last = active; boop_t = millis(); }
    if (millis() - boop_t > 20 && active != boop_stable) {
      boop_stable = active;
      if (active) state.triggerBoop(BOOP_EXPRESSION, BOOP_DURATION);
    }
  }
#endif

#if BUTTONS_ENABLE
  for (uint8_t i = 0; i < NUM_BUTTONS; i++) {
    bool raw = digitalRead(BUTTONS[i].pin);
    bool active = BUTTONS[i].active_low ? !raw : raw;
    if (active != bstate[i].last) { bstate[i].last = active; bstate[i].t = millis(); }
    if (millis() - bstate[i].t > 20 && active != bstate[i].stable) {
      bstate[i].stable = active;
      if (active) {  // press edge
        *param = BUTTONS[i].param;
        return BUTTONS[i].action;
      }
    }
  }
#endif

  return BTN_NONE;
}
