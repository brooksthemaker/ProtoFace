"""
Threaded microphone input.

Supports two backends selected by inputs.microphone.type in config:

  type: usb  (default)
    Standard USB/built-in mic via PyAudio.  Set device_index to pin a
    specific device, or leave null for the system default.

  type: i2s
    I2S MEMS microphone (INMP441, SPH0645, ICS43434, etc.) accessed via
    an ALSA device created by a device-tree overlay in /boot/config.txt.

    Typical /boot/config.txt additions:
      dtoverlay=i2s-mems-mic            # most MEMS mics (mono)
      dtoverlay=googlevoicehat-soundcard # AIY Voice HAT

    Auto-detects the ALSA device by scanning PyAudio device names for a
    case-insensitive substring match against device_name (default: "i2s").
    Override device_index to skip auto-detection.

    I2S mics return 32-bit signed integer samples.  The driver maps a
    mono microphone to the LEFT channel of a stereo stream by default;
    set channel: 1 to use the right channel instead.

Both backends expose the same public attributes:
  .volume      float 0-1  smoothed RMS
  .spectrum    ndarray (32,) normalised FFT bands
  .mouth_open  float 0-1  derived from volume above sensitivity threshold
"""

import threading
import math

import numpy as np

try:
    import pyaudio
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_FFT_BANDS = 32

# Substrings searched (case-insensitive) in PyAudio device names when
# type=i2s and no explicit device_index is set.
_I2S_NAME_HINTS = ('i2s', 'snd_rpi', 'simple-card', 'seeed', 'mems')


def _find_device_by_name(pa, hint: str) -> int | None:
    """Return the first input device whose name contains *hint* (case-insensitive)."""
    hint_lo = hint.lower()
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0 and hint_lo in info['name'].lower():
            return i
    return None


def _find_i2s_device(pa) -> int | None:
    """Try each _I2S_NAME_HINTS in order; return first match."""
    for hint in _I2S_NAME_HINTS:
        idx = _find_device_by_name(pa, hint)
        if idx is not None:
            return idx
    return None


class Microphone:
    def __init__(self, cfg: dict):
        mic_cfg = cfg.get('inputs', {}).get('microphone', {})
        self._enabled   = mic_cfg.get('enabled', True) and _AVAILABLE
        self._type      = mic_cfg.get('type', 'usb').lower()   # 'usb' | 'i2s'
        self._device    = mic_cfg.get('device_index', None)    # explicit override
        self._dev_name  = mic_cfg.get('device_name', None)     # i2s name hint
        self._rate      = mic_cfg.get('sample_rate', 44100)
        self._chunk     = mic_cfg.get('chunk', 1024)
        self._smoothing = mic_cfg.get('smoothing', 0.15)
        # I2S: which channel carries the microphone signal (0=left, 1=right)
        self._i2s_channel = mic_cfg.get('channel', 0)

        self.volume:     float        = 0.0
        self.spectrum:   np.ndarray   = np.zeros(_FFT_BANDS)
        self.mouth_open: float        = 0.0

        self._raw_volume  = 0.0
        self._spectrum    = np.zeros(_FFT_BANDS)
        self._lock        = threading.Lock()
        self._stream      = None
        self._pa          = None
        self._thread      = None
        self._running     = False

        if self._enabled:
            self._start()
        elif not _AVAILABLE and mic_cfg.get('enabled', False):
            print('[mic] PyAudio not installed — microphone disabled')

    # ── Startup ───────────────────────────────────────────────────────────────

    def _start(self):
        self._pa = pyaudio.PyAudio()

        if self._type == 'i2s':
            self._start_i2s()
        else:
            self._start_usb()

    def _start_usb(self):
        kwargs = dict(
            format=pyaudio.paFloat32,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
        )
        if self._device is not None:
            kwargs['input_device_index'] = self._device
        self._open_stream(kwargs, sample_fmt='float32', channels=1)

    def _start_i2s(self):
        # Resolve device index
        if self._device is not None:
            dev_idx = self._device
        else:
            hint = self._dev_name or ''
            if hint:
                dev_idx = _find_device_by_name(self._pa, hint)
            else:
                dev_idx = _find_i2s_device(self._pa)

            if dev_idx is None:
                print('[mic] I2S device not found — check dtoverlay in /boot/config.txt')
                print('[mic] Available input devices:')
                for i in range(self._pa.get_device_count()):
                    info = self._pa.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        print(f'       [{i}] {info["name"]}')
                self._enabled = False
                return

        # I2S mics expose a stereo stream on Pi even when physically mono.
        # Capture 2 channels; pick the active channel after de-interleaving.
        dev_info   = self._pa.get_device_info_by_index(dev_idx)
        n_channels = min(2, int(dev_info['maxInputChannels']))
        rate       = self._rate if self._rate else int(dev_info['defaultSampleRate'])

        kwargs = dict(
            format=pyaudio.paInt32,
            channels=n_channels,
            rate=rate,
            input=True,
            input_device_index=dev_idx,
            frames_per_buffer=self._chunk,
        )
        self._i2s_channels = n_channels
        self._rate = rate
        self._open_stream(kwargs, sample_fmt='int32', channels=n_channels)

    def _open_stream(self, kwargs: dict, sample_fmt: str, channels: int):
        self._sample_fmt = sample_fmt
        self._capture_channels = channels
        try:
            self._stream = self._pa.open(**kwargs)
        except Exception as e:
            print(f'[mic] failed to open stream: {e}')
            self._enabled = False
            return

        self._running = True
        self._thread = threading.Thread(target=self._capture, daemon=True)
        self._thread.start()

    # ── Capture thread ────────────────────────────────────────────────────────

    def _capture(self):
        while self._running:
            try:
                data = self._stream.read(self._chunk, exception_on_overflow=False)

                if self._sample_fmt == 'int32':
                    raw = np.frombuffer(data, dtype=np.int32).astype(np.float32)
                    raw /= float(2 ** 31)            # normalise to -1..+1
                    if self._capture_channels > 1:
                        # de-interleave; pick the configured channel
                        raw = raw[self._i2s_channel::self._capture_channels]
                else:
                    raw = np.frombuffer(data, dtype=np.float32)

                rms      = float(np.sqrt(np.mean(raw ** 2)))
                rms_norm = min(1.0, rms * 10.0)

                fft       = np.abs(np.fft.rfft(raw, n=self._chunk))
                fft       = fft[:self._chunk // 2]
                band_size = max(1, len(fft) // _FFT_BANDS)
                bands     = np.array([
                    fft[i * band_size:(i + 1) * band_size].mean()
                    for i in range(_FFT_BANDS)
                ], dtype=np.float32)
                if bands.max() > 0:
                    bands /= bands.max()

                with self._lock:
                    self._raw_volume = rms_norm
                    self._spectrum   = bands
            except Exception:
                pass

    # ── Main-thread interface ─────────────────────────────────────────────────

    def update(self, dt: float, sensitivity: float = 0.5):
        if not self._enabled:
            return
        with self._lock:
            raw  = self._raw_volume
            spec = self._spectrum.copy()

        alpha           = self._smoothing
        self.volume     = self.volume   * (1.0 - alpha) + raw  * alpha
        self.spectrum   = self.spectrum * (1.0 - alpha) + spec * alpha
        self.mouth_open = float(np.clip(
            (self.volume - sensitivity) / (1.0 - sensitivity + 1e-6), 0, 1))

    def close(self):
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()
