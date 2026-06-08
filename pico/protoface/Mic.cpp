#include "config.h"

#if MIC_ENABLE
#include "Mic.h"

void Mic::begin() {
  analogReadResolution(12);  // 0..4095
}

void Mic::update(FaceState &state, float dt) {
  (void)dt;

  // Measure the AC envelope as peak-to-peak over a burst of samples (the mic's
  // DC bias sits near mid-scale; we only care about the swing).
  int mn = 4095, mx = 0;
  for (int i = 0; i < MIC_SAMPLES; i++) {
    int v = analogRead(MIC_PIN);
    if (v < mn) mn = v;
    if (v > mx) mx = v;
  }
  float amp = (mx - mn) / 4095.0f;  // 0..1

  // Noise gate, then sensitivity scaling.
  float e = amp;
  if (e < MIC_NOISE_FLOOR) {
    e = 0.0f;
  } else {
    e = (e - MIC_NOISE_FLOOR) / (1.0f - MIC_NOISE_FLOOR);
  }
  e *= (0.5f + MIC_SENSITIVITY);
  if (e > 1.0f) e = 1.0f;
  level_ = e;

  // Asymmetric smoothing: open fast, close slower.
  float k = (e > mouth_) ? MIC_ATTACK : MIC_DECAY;
  mouth_ += k * (e - mouth_);
  state.mouth_open = mouth_;
}

#endif  // MIC_ENABLE
