// Compile-time configuration for the Pico C++ build.
//
// Unlike the CM5 (YAML) and CircuitPython (JSON) builds, the C++ port keeps
// config compile-time so there is no parser or filesystem dependency. Edit and
// re-flash to change panel wiring, geometry, or defaults. Runtime tweaks
// (colour, effect, expression, brightness) are available over USB serial.
#pragma once
#include <Arduino.h>

// ── Panel geometry ──────────────────────────────────────────────────────────
// One HUB75 chain shown as a single wide canvas: 2x 64x32 -> 128x32.
#define PANEL_W 64        // single panel width
#define PANEL_H 32        // single panel height (32-row -> 4 address lines)
#define CHAIN_LEN 2       // panels daisy-chained
#define CANVAS_W (PANEL_W * CHAIN_LEN)  // 128
#define CANVAS_H (PANEL_H)              // 32

// Right half mirrors the left (matches the CM5 mirror_of layout).
#define FACE_MIRROR 1
// Authored face size when mirroring is the left half; full canvas otherwise.
#if FACE_MIRROR
  #define FACE_W (CANVAS_W / 2)  // 64
#else
  #define FACE_W (CANVAS_W)
#endif
#define FACE_H (CANVAS_H)

// ── HUB75 pins (Pimoroni Interstate 75 defaults; change for your wiring) ─────
#define RGB_PINS  {0, 1, 2, 3, 4, 5}   // R0 G0 B0 R1 G1 B1
#define ADDR_PINS {6, 7, 8, 9}         // A B C D  (add 10 for 64-row: {6,7,8,9,10})
#define CLOCK_PIN 11
#define LATCH_PIN 12
#define OE_PIN    13
#define BIT_DEPTH 5                     // Protomatter colour depth 1..6

// ── Render defaults ─────────────────────────────────────────────────────────
#define TARGET_FPS 30
#define DEFAULT_BRIGHTNESS 200          // 0..255 (applied in the tint stage)
#define DEFAULT_MATERIAL_R 0            // teal
#define DEFAULT_MATERIAL_G 220
#define DEFAULT_MATERIAL_B 180
#define DEFAULT_EFFECT 0                // index into Particles effect table; 0 = none

// ── Active face ─────────────────────────────────────────────────────────────
// Generate with: tools/convert_assets.py --name main --out assets/main.h ...
#if __has_include("assets/main.h")
  #include "assets/main.h"
  #define ACTIVE_FACE FACE_main
#else
  #error "Missing face header assets/main.h. Bake it first, e.g.: \
python tools/convert_assets.py --src ../faces/main --name main \
--out protoface/assets/main.h --width 64 --height 32  (see pico/README.md)"
#endif
