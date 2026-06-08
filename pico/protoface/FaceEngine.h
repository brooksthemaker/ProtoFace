// Face engine — C++ port of the CM5 face.py + renderer.py pipeline.
//
// Each frame it composes the active expression (crossfaded from the previous),
// applies blink (eye regions or whole-face) and the mouth-open region, then
// renders to the RGB888 canvas with an integer wiggle/gyro shift (edge-clamped)
// and material tint (luminance x colour x brightness). With mirroring the left
// half is rendered and copied flipped into the right half.
#pragma once
#include <Arduino.h>
#include "face_asset.h"
#include "FaceState.h"
#include "Material.h"

class FaceEngine {
 public:
  // face_w/face_h: rendered face size; canvas_w/canvas_h: full panel canvas.
  FaceEngine(const FaceAsset &asset, uint16_t face_w, uint16_t face_h,
             uint16_t canvas_w, uint16_t canvas_h, bool mirror);
  ~FaceEngine();

  uint8_t numExpressions() const { return asset_.num_expr; }
  const char *expressionName(uint8_t i) const { return asset_.names[i]; }

  // Compose + render the face into an RGB888 canvas (canvas_w*canvas_h*3).
  void render(uint8_t *canvas, const FaceState &state, const Material &mat);

 private:
  void compose(const FaceState &state);  // -> wlum_/walpha_
  void blendRegion(const FaceImage &src, float t, const FaceBox &box);
  void blendWhole(const FaceImage &src, float t);

  const FaceAsset &asset_;
  uint16_t fw_, fh_, cw_, ch_;
  bool mirror_;
  uint8_t *wlum_;    // fw_*fh_ working luminance
  uint8_t *walpha_;  // fw_*fh_ working alpha
};
