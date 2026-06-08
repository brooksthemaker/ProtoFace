// Microphone (analog) — drives mouth movement and audio-reactive effects.
//
// Samples an analog mic module on an ADC pin each frame, measures the audio
// envelope (peak-to-peak of the AC signal), and maps it to FaceState.mouth_open
// with a noise gate and asymmetric attack/decay smoothing (fast open, slower
// close, like a real mouth). level() exposes the 0..1 envelope so cheeks
// (ACC_AUDIO) and particle density can react too.
//
// A C++ analogue of the CM5 microphone.py (PyAudio + FFT). We use an amplitude
// envelope rather than a full FFT — enough for mouth + reactive intensity on a
// microcontroller. Gated by MIC_ENABLE in config.h.
#pragma once
#include <Arduino.h>
#include "FaceState.h"

class Mic {
 public:
  void begin();
  void update(FaceState &state, float dt);
  float level() const { return level_; }  // 0..1 audio envelope

 private:
  float level_ = 0.0f;
  float mouth_ = 0.0f;
};
