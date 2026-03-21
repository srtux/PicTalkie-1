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
