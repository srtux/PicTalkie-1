"""Shared UI helpers: waveform drawing, audio playback, PIL conversion."""

import os

import numpy as np
import pygame

from ..constants import COLOR_ACCENT, COLOR_GREEN, SAMPLE_RATE
from ..audio import save_wav


def pil_to_pygame(pil_image):
    """Convert a PIL Image to a Pygame Surface."""
    return pygame.image.fromstring(pil_image.tobytes(), pil_image.size, pil_image.mode)


def draw_waveform(surface, samples, x, y, w, h, color=COLOR_ACCENT):
    """Draw a min/max waveform visualization of audio samples."""
    n = len(samples)
    mid_y = y + h // 2
    for px in range(w):
        start_idx = int(px * n / w)
        end_idx = max(start_idx + 1, int((px + 1) * n / w))
        chunk = samples[start_idx:min(end_idx, n)]
        if len(chunk) == 0:
            continue
        top_px = mid_y - int(float(np.max(chunk)) * h / 2)
        bot_px = mid_y - int(float(np.min(chunk)) * h / 2)
        pygame.draw.line(surface, color, (x + px, top_px), (x + px, bot_px))


def render_waveform_surface(samples, w, h, color=COLOR_GREEN):
    """Pre-render a waveform to a cached surface."""
    surf = pygame.Surface((w, h))
    surf.fill((0, 0, 0))
    draw_waveform(surf, samples, 0, 0, w, h, color)
    return surf


def play_audio(samples, temp_name):
    """Save samples to a temp WAV and play via pygame mixer."""
    temp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", temp_name)
    temp_path = os.path.normpath(temp_path)
    save_wav(samples, temp_path)
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1)
    pygame.mixer.music.load(temp_path)
    pygame.mixer.music.play()


def stop_audio():
    """Stop pygame mixer playback."""
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


def is_audio_playing():
    """Check if pygame mixer is currently playing."""
    try:
        return pygame.mixer.get_init() and pygame.mixer.music.get_busy()
    except Exception:
        return False


# --- Microphone recording ---

class MicRecorder:
    """Records audio from the system microphone in a background thread.

    Usage:
        recorder = MicRecorder()
        recorder.start()
        # ... wait ...
        samples = recorder.stop()  # returns float32 numpy array at SAMPLE_RATE Hz
    """

    def __init__(self):
        self.recording = False
        self._chunks = []
        self._stream = None
        self._device_rate = None

    def start(self):
        """Start recording from the default microphone."""
        import sounddevice as sd
        self._chunks = []
        self.recording = True

        # Use the mic's native sample rate to avoid driver resampling issues
        device_info = sd.query_devices(kind='input')
        self._device_rate = int(device_info['default_samplerate'])

        self._stream = sd.InputStream(
            samplerate=self._device_rate,
            channels=1,
            dtype='float32',
            callback=self._callback,
            blocksize=2048,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each audio block."""
        if self.recording:
            self._chunks.append(indata[:, 0].copy())

    def stop(self):
        """Stop recording and return samples as float32 array at SAMPLE_RATE Hz."""
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            return np.array([], dtype=np.float32)

        raw = np.concatenate(self._chunks)
        self._chunks = []

        # Resample to SAMPLE_RATE if mic uses a different rate
        if self._device_rate and self._device_rate != SAMPLE_RATE:
            raw = _resample(raw, self._device_rate, SAMPLE_RATE)

        # Normalize: scale peak amplitude to match encoder's range (~0.7 max)
        peak = np.max(np.abs(raw))
        if peak > 0.001:
            raw = raw * (0.7 / peak)

        return raw

    @property
    def elapsed_seconds(self):
        """How many seconds of audio have been recorded so far."""
        if not self._chunks:
            return 0.0
        total = sum(len(c) for c in self._chunks)
        return total / (self._device_rate or SAMPLE_RATE)


def _resample(samples, from_rate, to_rate):
    """Resample audio using linear interpolation."""
    duration = len(samples) / from_rate
    n_out = int(duration * to_rate)
    x_old = np.linspace(0, duration, len(samples), endpoint=False)
    x_new = np.linspace(0, duration, n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)
