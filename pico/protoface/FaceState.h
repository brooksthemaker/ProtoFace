// Face animation state — C++ port of the CM5 protoface/state.py.
//
// Holds the same logic: expression crossfade, the blink state machine, the boop
// override timer, and idle-wiggle parameters. Expressions are tracked by index
// into the active FaceAsset's name table. ProtoHUD IPC is dropped (standalone).
#pragma once
#include <Arduino.h>

struct WiggleCfg {
  float speed;
  float amplitude_x;
  float amplitude_y;
};

class FaceState {
 public:
  FaceState(uint8_t num_expr);

  // Expression control
  void setExpression(uint8_t idx);
  void nextExpression();
  void prevExpression();
  void triggerBoop(uint8_t idx, float duration);
  void triggerBlink();

  void update(float dt);
  void wiggleOffset(float *dx, float *dy) const;  // idle wiggle in pixels

  // Read by the face engine each frame.
  uint8_t expression() const { return expr_; }
  uint8_t prevExpressionIdx() const { return prev_expr_; }
  float transitionT() const { return transition_t_; }
  float blinkWeight() const { return blink_weight_; }

  // Driven by inputs (mic/gyro) in later phases.
  float mouth_open = 0.0f;
  float gyro_dx = 0.0f, gyro_dy = 0.0f;
  uint8_t brightness = 200;

  WiggleCfg wiggle = {0.3f, 2.0f, 1.0f};

  // Tunables (defaults match the CM5 build).
  float expression_fade = 0.3f;   // seconds
  float blink_duration = 0.15f;
  float blink_interval_min = 3.0f;
  float blink_interval_max = 7.0f;

 private:
  void updateBlink(float dt);

  uint8_t num_expr_;
  uint8_t expr_;
  uint8_t prev_expr_;
  float transition_t_ = 1.0f;
  float time_ = 0.0f;

  // Blink state machine: 0 open, 1 closing, 2 closed, 3 opening.
  uint8_t blink_phase_ = 0;
  float blink_weight_ = 0.0f;
  float blink_t_ = 0.0f;
  float next_blink_;

  // Boop override.
  float boop_remaining_ = 0.0f;
  uint8_t boop_prev_ = 0;
};
