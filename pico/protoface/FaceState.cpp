#include "FaceState.h"

static float randf(float a, float b) {
  return a + (b - a) * (float)random(0, 10001) / 10000.0f;
}

FaceState::FaceState(uint8_t num_expr)
    : num_expr_(num_expr ? num_expr : 1), expr_(0), prev_expr_(0) {
  next_blink_ = randf(blink_interval_min, blink_interval_max);
}

void FaceState::setExpression(uint8_t idx) {
  if (idx >= num_expr_ || idx == expr_) return;
  prev_expr_ = expr_;
  expr_ = idx;
  transition_t_ = 0.0f;
}

void FaceState::nextExpression() {
  setExpression((uint8_t)((expr_ + 1) % num_expr_));
}

void FaceState::prevExpression() {
  setExpression((uint8_t)((expr_ + num_expr_ - 1) % num_expr_));
}

void FaceState::triggerBoop(uint8_t idx, float duration) {
  if (boop_remaining_ <= 0.0f) boop_prev_ = expr_;
  boop_remaining_ = duration;
  setExpression(idx);
}

void FaceState::triggerBlink() {
  if (blink_phase_ == 0) {
    blink_phase_ = 1;
    blink_t_ = 0.0f;
  }
}

void FaceState::update(float dt) {
  time_ += dt;

  if (transition_t_ < 1.0f) {
    transition_t_ += dt / (expression_fade > 0.01f ? expression_fade : 0.01f);
    if (transition_t_ > 1.0f) transition_t_ = 1.0f;
  }

  if (boop_remaining_ > 0.0f) {
    boop_remaining_ -= dt;
    if (boop_remaining_ <= 0.0f) setExpression(boop_prev_);
  }

  updateBlink(dt);
}

void FaceState::updateBlink(float dt) {
  const float half = blink_duration / 2.0f;
  switch (blink_phase_) {
    case 0:  // open
      next_blink_ -= dt;
      if (next_blink_ <= 0.0f) { blink_phase_ = 1; blink_t_ = 0.0f; }
      break;
    case 1:  // closing
      blink_t_ += dt;
      blink_weight_ = min(1.0f, blink_t_ / half);
      if (blink_t_ >= half) { blink_phase_ = 2; blink_t_ = 0.0f; }
      break;
    case 2:  // closed (brief hold)
      blink_t_ += dt;
      if (blink_t_ >= 0.04f) { blink_phase_ = 3; blink_t_ = 0.0f; }
      break;
    case 3:  // opening
      blink_t_ += dt;
      blink_weight_ = max(0.0f, 1.0f - blink_t_ / half);
      if (blink_t_ >= half) {
        blink_weight_ = 0.0f;
        blink_phase_ = 0;
        next_blink_ = randf(blink_interval_min, blink_interval_max);
      }
      break;
  }
}

void FaceState::wiggleOffset(float *dx, float *dy) const {
  *dx = wiggle.amplitude_x * sinf(2.0f * PI * wiggle.speed * time_);
  *dy = wiggle.amplitude_y * sinf(2.0f * PI * wiggle.speed * time_ * 1.3f);
}
