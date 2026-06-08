#include "config.h"

#if IMU_ENABLE
#include "Imu.h"
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>

static Adafruit_BNO055 bno(55, IMU_ADDR, &Wire1);

static inline float deadzone(float v, float dz) {
  if (v > dz) return v - dz;
  if (v < -dz) return v + dz;
  return 0.0f;
}

static inline float clampf(float v, float lo, float hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

bool Imu::begin() {
  Wire1.setSDA(IMU_SDA);
  Wire1.setSCL(IMU_SCL);
  Wire1.begin();
  ok_ = bno.begin();
  if (ok_) bno.setExtCrystalUse(true);
  return ok_;
}

void Imu::update(FaceState &state, float dt) {
  (void)dt;
  if (!ok_) return;

  sensors_event_t ev;
  bno.getEvent(&ev);
  // Two gravity-referenced tilt axes (degrees). y/z are roll/pitch; swap or
  // negate via config if the on-helmet motion comes out mirrored.
  float ax = ev.orientation.y;
  float ay = ev.orientation.z;

  if (!have_base_) {
    base_x_ = ax;
    base_y_ = ay;
    have_base_ = true;
  }

  float rx = deadzone(ax - base_x_, IMU_DEADZONE);
  float ry = deadzone(ay - base_y_, IMU_DEADZONE);

  float tx = clampf(rx * IMU_SENS_X, -IMU_MAX, IMU_MAX);
  float ty = clampf(ry * IMU_SENS_Y, -IMU_MAX, IMU_MAX);

  dx_ += IMU_SMOOTH * (tx - dx_);
  dy_ += IMU_SMOOTH * (ty - dy_);

  state.gyro_dx = dx_;
  state.gyro_dy = dy_;
}

#endif  // IMU_ENABLE
