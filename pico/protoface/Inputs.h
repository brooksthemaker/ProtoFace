// Physical inputs: buttons, boop sensor, and an analog light sensor.
//
//  * Buttons  — debounced digital inputs; each maps to an action (cycle
//    expression, colour, effect, blink, brightness). Table in Inputs.cpp.
//  * Boop     — a digital proximity/touch sensor on a GPIO drives the existing
//    FaceState::triggerBoop() (show an expression for a moment when booped).
//  * Light    — an LDR/phototransistor on an ADC pin auto-dims the face to the
//    ambient light (overrides manual brightness while enabled).
//
// Each feature is independently gated in config.h; with all off this costs
// nothing and pulls in no extra libraries (core Arduino only).
#pragma once
#include <Arduino.h>
#include "FaceState.h"

enum BtnAction {
  BTN_NONE,
  BTN_NEXT_EXPR, BTN_PREV_EXPR, BTN_SET_EXPR,
  BTN_BLINK,
  BTN_NEXT_COLOR, BTN_PREV_COLOR,
  BTN_NEXT_EFFECT, BTN_PREV_EFFECT,
  BTN_BRIGHT_UP, BTN_BRIGHT_DOWN,
};

struct BtnCfg {
  uint8_t pin;
  BtnAction action;
  uint8_t param;       // expression index for BTN_SET_EXPR
  bool active_low;     // true = wired to GND with a pull-up
};

class Inputs {
 public:
  void begin();
  // Apply boop + light to *state*; return one pending button action (with its
  // param), or BTN_NONE. Call once per frame.
  BtnAction poll(FaceState &state, uint8_t *param);
};
