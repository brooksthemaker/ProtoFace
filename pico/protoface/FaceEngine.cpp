#include "FaceEngine.h"

static inline uint8_t lerp8(uint8_t a, uint8_t b, float t) {
  int v = (int)(a + (b - a) * t + 0.5f);
  if (v < 0) v = 0;
  if (v > 255) v = 255;
  return (uint8_t)v;
}

static inline int clampi(int v, int lo, int hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

FaceEngine::FaceEngine(const FaceAsset &asset, uint16_t face_w, uint16_t face_h,
                       uint16_t canvas_w, uint16_t canvas_h, bool mirror)
    : asset_(asset), fw_(face_w), fh_(face_h), cw_(canvas_w), ch_(canvas_h),
      mirror_(mirror) {
  wlum_ = (uint8_t *)malloc((size_t)fw_ * fh_);
  walpha_ = (uint8_t *)malloc((size_t)fw_ * fh_);
}

FaceEngine::~FaceEngine() {
  free(wlum_);
  free(walpha_);
}

void FaceEngine::blendRegion(const FaceImage &src, float t, const FaceBox &box) {
  if (box.w < 0) return;
  int x1 = clampi(box.x + box.w, 0, fw_);
  int y1 = clampi(box.y + box.h, 0, fh_);
  for (int y = clampi(box.y, 0, fh_); y < y1; y++) {
    for (int x = clampi(box.x, 0, fw_); x < x1; x++) {
      int i = y * fw_ + x;
      wlum_[i] = lerp8(wlum_[i], src.lum[i], t);
      walpha_[i] = lerp8(walpha_[i], src.alpha[i], t);
    }
  }
}

void FaceEngine::blendWhole(const FaceImage &src, float t) {
  int n = fw_ * fh_;
  for (int i = 0; i < n; i++) {
    wlum_[i] = lerp8(wlum_[i], src.lum[i], t);
    walpha_[i] = lerp8(walpha_[i], src.alpha[i], t);
  }
}

void FaceEngine::blendMask(const FaceImage &src, float t, const uint8_t *mask) {
  int n = fw_ * fh_;
  for (int i = 0; i < n; i++) {
    if (mask[i] == 0) continue;            // outside the drawn region
    float mt = t * (mask[i] / 255.0f);     // soft, shape-following weight
    wlum_[i] = lerp8(wlum_[i], src.lum[i], mt);
    walpha_[i] = lerp8(walpha_[i], src.alpha[i], mt);
  }
}

void FaceEngine::compose(const FaceState &state) {
  const FaceImage &cur = asset_.expr[state.expression()];
  const FaceImage &prev = asset_.expr[state.prevExpressionIdx()];
  float t = state.transitionT();
  int n = fw_ * fh_;

  if (t >= 1.0f || cur.lum == prev.lum) {
    memcpy(wlum_, cur.lum, n);
    memcpy(walpha_, cur.alpha, n);
  } else {
    for (int i = 0; i < n; i++) {
      wlum_[i] = lerp8(prev.lum[i], cur.lum[i], t);
      walpha_[i] = lerp8(prev.alpha[i], cur.alpha[i], t);
    }
  }

  // Blink: shape mask wins; else eye boxes; else whole-face swap.
  float bw = state.blinkWeight();
  if (bw > 0.0f && asset_.has_blink) {
    if (asset_.eye_mask) {
      blendMask(asset_.blink, bw, asset_.eye_mask);
    } else if (asset_.eye_l.w >= 0 || asset_.eye_r.w >= 0) {
      blendRegion(asset_.blink, bw, asset_.eye_l);
      blendRegion(asset_.blink, bw, asset_.eye_r);
    } else {
      blendWhole(asset_.blink, bw);
    }
  }

  // Mouth open: shape mask wins; else mouth box.
  if (state.mouth_open > 0.0f && asset_.has_mouth) {
    if (asset_.mouth_mask) {
      blendMask(asset_.mouth_open, state.mouth_open, asset_.mouth_mask);
    } else if (asset_.mouth.w >= 0) {
      blendRegion(asset_.mouth_open, state.mouth_open, asset_.mouth);
    }
  }
}

void FaceEngine::render(uint8_t *canvas, const FaceState &state,
                        const Material &mat) {
  compose(state);

  // Integer wiggle + gyro shift (edge-clamped sampling, like CM5 _shift_int).
  float wdx, wdy;
  state.wiggleOffset(&wdx, &wdy);
  int dx = (int)lroundf(wdx + state.gyro_dx);
  int dy = (int)lroundf(wdy + state.gyro_dy);

  float bscale = state.brightness / 255.0f;

  for (int fy = 0; fy < fh_; fy++) {
    int sy = clampi(fy - dy, 0, fh_ - 1);
    for (int fx = 0; fx < fw_; fx++) {
      int sx = clampi(fx - dx, 0, fw_ - 1);
      int si = sy * fw_ + sx;
      float factor = (wlum_[si] / 255.0f) * (walpha_[si] / 255.0f) * bscale;
      uint8_t *px = canvas + (fy * cw_ + fx) * 3;
      px[0] = (uint8_t)(mat.r * factor);
      px[1] = (uint8_t)(mat.g * factor);
      px[2] = (uint8_t)(mat.b * factor);
    }
  }

  // Mirror the left half into the right (flipped horizontally).
  if (mirror_) {
    for (int y = 0; y < ch_; y++) {
      uint8_t *row = canvas + y * cw_ * 3;
      for (int j = 0; j < fw_ && (fw_ + j) < cw_; j++) {
        uint8_t *dst = row + (fw_ + j) * 3;
        uint8_t *src = row + (fw_ - 1 - j) * 3;
        dst[0] = src[0];
        dst[1] = src[1];
        dst[2] = src[2];
      }
    }
  }
}
