"""Shared UI helpers: waveform drawing, audio playback, PIL conversion."""

import os

import numpy as np
import pygame

from ..constants import COLOR_ACCENT, COLOR_GREEN, SAMPLE_RATE
from ..audio import save_wav, resample


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

    For streaming access during recording, use get_samples() or get_recent_samples().
    All public methods return audio resampled to SAMPLE_RATE Hz.
    """

    def __init__(self):
        self.recording = False
        self._chunks = []
        self._stream = None
        self._device_rate = None
        self._sample_count = 0
        # Incremental resampling cache: avoids re-processing all chunks each frame
        self._cache = np.array([], dtype=np.float32)
        self._chunks_cached = 0

    def start(self):
        """Start recording from the default microphone."""
        import sounddevice as sd
        self._chunks = []
        self._sample_count = 0
        self._cache = np.array([], dtype=np.float32)
        self._chunks_cached = 0
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
            self._sample_count += len(indata)

    def _update_cache(self):
        """Resample any new chunks and append to the cache."""
        n = len(self._chunks)
        if n <= self._chunks_cached:
            return
        new_chunks = self._chunks[self._chunks_cached:]
        self._chunks_cached = n
        raw = np.concatenate(new_chunks)
        if self._device_rate and self._device_rate != SAMPLE_RATE:
            raw = resample(raw, self._device_rate, SAMPLE_RATE)
        self._cache = np.concatenate([self._cache, raw]) if len(self._cache) else raw

    def stop(self):
        """Stop recording and return samples as float32 array at SAMPLE_RATE Hz."""
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            return np.array([], dtype=np.float32)

        self._update_cache()
        result = self._cache.copy()

        self._chunks = []
        self._sample_count = 0
        self._cache = np.array([], dtype=np.float32)
        self._chunks_cached = 0

        # Normalize: scale peak amplitude to match encoder's range (~0.7 max)
        peak = np.max(np.abs(result))
        if peak > 0.001:
            result = result * (0.7 / peak)

        return result

    @property
    def has_data(self):
        """True if any audio chunks have been recorded."""
        return self._sample_count > 0

    @property
    def elapsed_seconds(self):
        """How many seconds of audio have been recorded so far."""
        if self._sample_count == 0:
            return 0.0
        return self._sample_count / (self._device_rate or SAMPLE_RATE)

    def get_samples(self):
        """Return all recorded samples resampled to SAMPLE_RATE Hz.

        Uses an incremental cache — only new chunks are resampled each call.
        Returns None if no data recorded yet.
        """
        if not self._chunks:
            return None
        self._update_cache()
        return self._cache

    def get_recent_samples(self, max_chunks=50):
        """Return the most recent chunks concatenated (for live waveform display).

        Returns raw device-rate samples (not resampled) for display only.
        Returns None if no data recorded yet.
        """
        if not self._chunks:
            return None
        recent = self._chunks[-max_chunks:]
        return np.concatenate(recent)


