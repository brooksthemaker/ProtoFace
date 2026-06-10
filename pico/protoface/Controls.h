// Standalone controls: single-key commands over the USB serial console,
// mirroring the CM5 solo-mode keys. Non-blocking — returns 0 when idle.
//
//   c / v   next / previous face colour
//   x / z   next / previous particle effect
//   e / w   next / previous expression
//   b       manual blink
//   + / -   brightness up / down
#pragma once
#include <Arduino.h>

inline char pollKey() {
  if (Serial.available() > 0) return (char)Serial.read();
  return 0;
}
