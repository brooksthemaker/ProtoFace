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

// ── Addressable LEDs (cheeks / ears / accents) ──────────────────────────────
// Optional WS2812/NeoPixel zones driven alongside the HUB75 face. Set to 1 and
// edit the zone table at the top of Accessories.cpp (data pins, LED counts,
// modes). Needs the Adafruit NeoPixel library. 0 = disabled (no dependency).
#define ACCESSORY_ENABLE 0

// ── Inputs: buttons / boop / light sensor ───────────────────────────────────
// Each independently optional; all use core Arduino only (no extra libraries).
// Pick GPIO that HUB75 doesn't use (GP0-GP13 are the panel).

// Buttons cycle expressions/colour/effect/etc. Edit the table in Inputs.cpp.
#define BUTTONS_ENABLE 0

// Boop sensor: a digital proximity/touch sensor that shows an expression briefly.
#define BOOP_ENABLE 0
#define BOOP_PIN 10              // free on 32-row panels; GP10 = HUB75 E on 64-row
#define BOOP_ACTIVE_LOW 1        // 1 = sensor pulls the pin to GND when booped
#define BOOP_EXPRESSION 0        // expression index to show (order in the face)
#define BOOP_DURATION 1.5f       // seconds to hold it

// Light sensor: analog LDR/phototransistor for ambient auto-brightness. While
// enabled it drives brightness automatically (manual +/- is overridden).
#define LIGHT_ENABLE 0
#define LIGHT_PIN 28             // ADC2 = GP28 (GP26/27 are the IMU I2C bus)
#define LIGHT_RAW_DARK 80        // analogRead value in darkness (calibrate)
#define LIGHT_RAW_BRIGHT 900     // analogRead value in bright light (calibrate)
#define LIGHT_MIN_BRIGHT 24      // brightness floor (never fully off)
#define LIGHT_MAX_BRIGHT 255     // brightness ceiling
#define LIGHT_SMOOTH 0.1f        // EMA smoothing per frame (0..1; lower = slower)

// ── In-helmet preview display (colour SPI TFT, ST7789 240x320) ──────────────
// A secondary display that mirrors the face + status text so the wearer can
// confirm what's showing. Runs on the RP2350's SECOND core (core1) so the SPI
// refresh doesn't slow the face on core0. Needs Adafruit_ST7789 + Adafruit_GFX.
// Uses hardware SPI0: SCK = GP18, MOSI = GP19 (do not reuse these elsewhere).
#define PREVIEW_ENABLE 0
#define PREVIEW_CS 20
#define PREVIEW_DC 21
#define PREVIEW_RST 22
#define PREVIEW_BL -1            // backlight GPIO, or -1 if BL is tied to 3.3V
#define PREVIEW_W 320            // display width AFTER rotation (landscape)
#define PREVIEW_H 240            // display height after rotation
#define PREVIEW_ROTATION 1       // 0..3; 1 or 3 = landscape for a 240x320 panel
#define PREVIEW_SCALE 2          // face px -> preview px (128x32 -> 256x64)
#define PREVIEW_FPS 12           // preview refresh cap, Hz (independent of face)

// ── IMU / head tracking (BNO055) — drives face movement ─────────────────────
// 9-axis absolute-orientation sensor on I2C1. Its gravity-referenced roll/pitch
// (drift-free, no host fusion) shift the face, on top of the idle wiggle. Needs
// Adafruit_BNO055 + Adafruit_Unified_Sensor + Adafruit_BusIO. Recenter (set the
// current pose as neutral) with serial 'r' or a BTN_RECENTER button.
#define IMU_ENABLE 0
#define IMU_SDA 26               // I2C1 SDA
#define IMU_SCL 27               // I2C1 SCL
#define IMU_ADDR 0x28            // BNO055 default (0x29 if ADR pin high)
#define IMU_SENS_X 0.20f         // pixels per degree, horizontal (flip sign to taste)
#define IMU_SENS_Y 0.20f         // pixels per degree, vertical
#define IMU_MAX 4.0f             // max face offset in pixels (clamp)
#define IMU_DEADZONE 2.0f        // ignore tilt below this many degrees
#define IMU_SMOOTH 0.2f          // EMA smoothing (0..1; lower = smoother/slower)

// ── Microphone (analog) — drives the mouth + audio-reactive effects ─────────
// An analog mic module (e.g. MAX9814 with AGC) on an ADC pin. Its envelope sets
// mouth_open and the audio level feeds ACC_AUDIO cheeks + particle density.
// ADC pins are GP26/27/28: GP26/27 are the IMU bus, so with the IMU enabled the
// mic and the light sensor must share GP28 — pick one. (IMU off frees 26/27.)
#define MIC_ENABLE 0
#define MIC_PIN 28               // ADC pin (see note above)
#define MIC_SAMPLES 256          // ADC samples per frame for the envelope
#define MIC_SENSITIVITY 0.5f     // 0..1 (higher = mouth opens more easily)
#define MIC_NOISE_FLOOR 0.04f    // ignore envelope below this (0..1)
#define MIC_ATTACK 0.6f          // smoothing when opening (0..1; higher = snappier)
#define MIC_DECAY 0.2f           // smoothing when closing

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
