"""Audio encoding, decoding, and WAV I/O.

Encoding pipeline:
    pixel values -> Baird amplitude -> repeat N times -> WAV samples

Decoding pipeline:
    WAV samples -> chunk by N -> average -> inverse Baird -> pixel values
"""

import wave

import numpy as np

from .constants import SAMPLE_RATE, SAMPLES_PER_VALUE, TOTAL_VALUES
from .image import reconstruct_image


def encode_to_samples(pixel_values):
    """Convert pixel values to audio samples using Baird encoding.

    Each pixel value is converted to a Baird amplitude repeated SAMPLES_PER_VALUE
    times, creating a staircase waveform robust against noise via averaging.

    Returns:
        numpy float32 array of length len(pixel_values) * SAMPLES_PER_VALUE.
    """
    values = np.asarray(pixel_values, dtype=np.float32)
    amplitudes = np.clip((values - 127) / 255 + 0.2, -1.0, 1.0)
    return np.repeat(amplitudes, SAMPLES_PER_VALUE)


def save_wav(samples, filepath):
    """Save float32 samples (-1 to +1) as a 16-bit mono PCM WAV file."""
    with wave.open(filepath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        int_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(int_samples.tobytes())


def load_wav(filepath):
    """Load a WAV file, normalize to float32 (-1 to +1), extract first channel.

    Supports 8, 16, 24, and 32-bit WAV files.

    Returns:
        (samples, sample_rate) tuple.
    """
    with wave.open(filepath, 'r') as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        raw_data = wf.readframes(wf.getnframes())

    samples = _normalize_samples(raw_data, sample_width)

    if n_channels > 1:
        samples = samples[::n_channels]

    return samples, sample_rate


def _normalize_samples(raw_data, sample_width):
    """Convert raw WAV bytes to float32 samples in [-1, 1]."""
    if sample_width == 1:
        samples = np.frombuffer(raw_data, dtype=np.uint8).astype(np.float32)
        return (samples - 128) / 128.0
    elif sample_width == 2:
        return np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 3:
        return _decode_24bit(raw_data)
    elif sample_width == 4:
        return np.frombuffer(raw_data, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width} bytes")


def _decode_24bit(raw_data):
    """Decode 24-bit WAV samples (no native numpy dtype)."""
    n_samples = len(raw_data) // 3
    samples = np.zeros(n_samples, dtype=np.float32)
    for i in range(n_samples):
        b = raw_data[i * 3:i * 3 + 3]
        value = b[0] | (b[1] << 8) | (b[2] << 16)
        if value & 0x800000:
            value -= 0x1000000
        samples[i] = value / 8388608.0
    return samples


def decode_from_samples(samples, samples_per_value=SAMPLES_PER_VALUE):
    """Decode audio samples back into pixel values.

    Chunks samples into groups, averages each group to recover the Baird
    amplitude, then applies the inverse formula.

    Returns:
        List of ints (0-255).
    """
    n_values = len(samples) // samples_per_value
    trimmed = samples[:n_values * samples_per_value]
    chunks = trimmed.reshape(n_values, samples_per_value)
    amplitudes = chunks.mean(axis=1)
    pixel_values = np.clip(np.round((amplitudes - 0.2) * 255 + 127), 0, 255).astype(int)
    return pixel_values.tolist()


def decode_wav_file(filepath):
    """Full pipeline: WAV file -> reconstructed PIL Image.

    Auto-detects samples_per_value if the WAV length doesn't match the default.
    """
    samples, sample_rate = load_wav(filepath)
    spv = _detect_samples_per_value(samples)
    pixel_values = decode_from_samples(samples, spv)
    return reconstruct_image(pixel_values)


def _detect_samples_per_value(samples):
    """Auto-detect samples_per_value from audio length."""
    spv = SAMPLES_PER_VALUE
    expected_values = len(samples) // spv
    if expected_values < TOTAL_VALUES and len(samples) % TOTAL_VALUES == 0:
        spv = len(samples) // TOTAL_VALUES
    return spv
