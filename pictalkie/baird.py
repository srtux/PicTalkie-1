"""
Baird amplitude formula for converting pixel values to/from audio amplitudes.

Based on John Logie Baird's 1920s mechanical television system where an audio
signal directly controlled brightness. The formula maps pixel brightness (0-255)
to audio amplitude (-1 to +1) with a DC offset of 0.2 to keep mid-gray
distinguishable from silence.

    Forward:  amplitude = (value - 127) / 255 + 0.2
    Inverse:  value = (amplitude - 0.2) * 255 + 127
"""

import numpy as np


def baird_amplitude(value):
    """Convert a pixel value (0-255) to a Baird audio amplitude (-1 to +1)."""
    amp = (value - 127) / 255 + 0.2
    return max(-1.0, min(1.0, amp))


def inverse_baird(amp):
    """Convert a Baird amplitude back to a pixel value (0-255)."""
    value = round((amp - 0.2) * 255 + 127)
    return max(0, min(255, value))


def baird_amplitude_array(values):
    """Vectorized forward Baird: pixel values (0-255) -> amplitudes (-1 to +1)."""
    arr = np.asarray(values, dtype=np.float32)
    return np.clip((arr - 127) / 255 + 0.2, -1.0, 1.0)


def inverse_baird_array(amplitudes):
    """Vectorized inverse Baird: amplitudes -> pixel values (0-255)."""
    return np.clip(np.round((amplitudes - 0.2) * 255 + 127), 0, 255).astype(int)
