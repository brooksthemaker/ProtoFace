// IMU head-tracking (Bosch BNO055) — drives face movement.
//
// The BNO055 fuses accel/gyro/mag on-chip and outputs absolute orientation, so
// we read drift-free, gravity-referenced tilt and map it to the face's pixel
// offset (FaceState gyro_dx/gyro_dy), which the engine already applies on top of
// the idle wiggle. A neutral pose is captured as the baseline; recenter() resets
// it (e.g. after putting the helmet on).
//
// Gated by IMU_ENABLE in config.h; the BNO055 libraries are only pulled in when
// enabled. Two tilt axes map to X/Y — flip IMU_SENS_* signs (or swap the axes
// in Imu.cpp) if the motion comes out mirrored.
#pragma once
#include <Arduino.h>
#include "FaceState.h"

class Imu {
 public:
  bool begin();
  void update(FaceState &state, float dt);
  void recenter() { have_base_ = false; }
  bool ok() const { return ok_; }

 private:
  bool ok_ = false;
  bool have_base_ = false;
  float base_x_ = 0.0f, base_y_ = 0.0f;
  float dx_ = 0.0f, dy_ = 0.0f;  // smoothed pixel offset
};
