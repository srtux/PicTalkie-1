"""Audio encoding, decoding, and WAV I/O.

Encoding pipeline:
    pixel values -> protocol header + Baird amplitude -> WAV samples

Decoding pipeline:
    WAV samples -> parse protocol -> calibration correction -> pixel values

Protocol message structure:
    Preamble | Gap | Calibration | Gap | Sync | Gap | Header | Gap | Pixel Data
"""

import wave

import numpy as np

from .constants import (
    SAMPLE_RATE, SAMPLES_PER_VALUE, TOTAL_VALUES,
    IMAGE_SIZE, CHANNELS,
    PREAMBLE_SAMPLES, PREAMBLE_AMPLITUDE,
    GAP_SAMPLES,
    CALIBRATION_LEVELS, CALIBRATION_SPV,
    SYNC_PATTERN, SYNC_COUNT, SYNC_SPV,
    HEADER_COUNT, HEADER_SPV,
    PROTOCOL_SAMPLES,
)
from .image import reconstruct_image


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode_to_samples(pixel_values, width=IMAGE_SIZE, height=IMAGE_SIZE, channels=CHANNELS):
    """Encode pixel values into a full protocol message.

    Message structure:
        Preamble (0.3s) | Gap | Calibration (2.56s) | Gap |
        Sync (0.12s) | Gap | Header (0.03s) | Gap | Pixel Data (~57.96s)

    Returns:
        numpy float32 array of the complete audio message.
    """
    parts = []
    gap = np.zeros(GAP_SAMPLES, dtype=np.float32)

    # 1. Preamble -- steady carrier tone so the radio can wake up
    parts.append(np.full(PREAMBLE_SAMPLES, PREAMBLE_AMPLITUDE, dtype=np.float32))
    parts.append(gap)

    # 2. Calibration -- all 256 amplitude levels in order
    cal_values = np.arange(CALIBRATION_LEVELS, dtype=np.float32)
    cal_amps = np.clip((cal_values - 127) / 255 + 0.2, -1.0, 1.0)
    parts.append(np.repeat(cal_amps, CALIBRATION_SPV))
    parts.append(gap)

    # 3. Sync -- alternating low-high pattern for alignment
    sync_values = np.array(SYNC_PATTERN, dtype=np.float32)
    sync_amps = np.clip((sync_values - 127) / 255 + 0.2, -1.0, 1.0)
    parts.append(np.repeat(sync_amps, SYNC_SPV))
    parts.append(gap)

    # 4. Header -- image dimensions (width, height, channels)
    header_values = np.array([width, height, channels], dtype=np.float32)
    header_amps = np.clip((header_values - 127) / 255 + 0.2, -1.0, 1.0)
    parts.append(np.repeat(header_amps, HEADER_SPV))
    parts.append(gap)

    # 5. Pixel data -- Baird-encoded values with repetition for noise resilience
    values = np.asarray(pixel_values, dtype=np.float32)
    amplitudes = np.clip((values - 127) / 255 + 0.2, -1.0, 1.0)
    parts.append(np.repeat(amplitudes, SAMPLES_PER_VALUE))

    return np.concatenate(parts)


# ---------------------------------------------------------------------------
# WAV I/O
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Protocol parsing
# ---------------------------------------------------------------------------

def parse_protocol(samples):
    """Parse protocol sections from audio samples.

    Returns:
        dict with calibration, width, height, channels, data_offset
        or None if protocol not detected (legacy format).
    """
    if len(samples) < PROTOCOL_SAMPLES:
        return None

    offset = PREAMBLE_SAMPLES + GAP_SAMPLES

    # Read calibration: average each level's samples to get measured amplitude
    cal_total = CALIBRATION_LEVELS * CALIBRATION_SPV
    cal_data = samples[offset:offset + cal_total]
    calibration = cal_data.reshape(CALIBRATION_LEVELS, CALIBRATION_SPV).mean(axis=1)
    offset += cal_total + GAP_SAMPLES

    # Verify sync pattern
    sync_total = SYNC_COUNT * SYNC_SPV
    sync_data = samples[offset:offset + sync_total]
    sync_amps = sync_data.reshape(SYNC_COUNT, SYNC_SPV).mean(axis=1)
    sync_vals = np.round((sync_amps - 0.2) * 255 + 127).astype(int)
    expected = np.array(SYNC_PATTERN)
    if not np.allclose(sync_vals, expected, atol=30):
        return None
    offset += sync_total + GAP_SAMPLES

    # Read header (no clamping -- width=256 must survive the round-trip)
    header_total = HEADER_COUNT * HEADER_SPV
    header_data = samples[offset:offset + header_total]
    header_amps = header_data.reshape(HEADER_COUNT, HEADER_SPV).mean(axis=1)
    header_vals = np.round((header_amps - 0.2) * 255 + 127).astype(int)
    offset += header_total + GAP_SAMPLES

    return {
        'calibration': calibration,
        'width': int(header_vals[0]),
        'height': int(header_vals[1]),
        'channels': int(header_vals[2]),
        'data_offset': offset,
    }


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def decode_from_samples(samples, samples_per_value=SAMPLES_PER_VALUE, calibration=None):
    """Decode audio samples back into pixel values.

    If calibration is provided, uses nearest-neighbor lookup against the
    calibration amplitudes. Otherwise falls back to inverse Baird formula.

    Returns:
        List of ints (0-255).
    """
    n_values = len(samples) // samples_per_value
    trimmed = samples[:n_values * samples_per_value]
    chunks = trimmed.reshape(n_values, samples_per_value)
    amplitudes = chunks.mean(axis=1)

    if calibration is not None:
        pixel_values = _apply_correction(amplitudes, calibration)
    else:
        pixel_values = np.clip(np.round((amplitudes - 0.2) * 255 + 127), 0, 255).astype(int)

    return pixel_values.tolist()


def _apply_correction(amplitudes, calibration):
    """Map received amplitudes to pixel values using calibration data.

    calibration[i] = measured amplitude for pixel value i after transmission.
    For each received amplitude, finds the nearest calibration level.
    """
    sorted_idx = np.argsort(calibration)
    sorted_cal = calibration[sorted_idx]

    insert = np.searchsorted(sorted_cal, amplitudes)
    insert = np.clip(insert, 0, len(sorted_cal) - 1)
    left = np.clip(insert - 1, 0, len(sorted_cal) - 1)

    dist_right = np.abs(amplitudes - sorted_cal[insert])
    dist_left = np.abs(amplitudes - sorted_cal[left])

    best = np.where(dist_left < dist_right, left, insert)
    return sorted_idx[best].astype(int)


def decode_wav_file(filepath):
    """Full pipeline: WAV file -> reconstructed PIL Image.

    Auto-detects protocol header. Falls back to legacy format.
    """
    samples, sample_rate = load_wav(filepath)

    protocol = parse_protocol(samples)
    if protocol is not None:
        data = samples[protocol['data_offset']:]
        pixel_values = decode_from_samples(data, SAMPLES_PER_VALUE, protocol['calibration'])
        return reconstruct_image(pixel_values, protocol['width'], protocol['channels'])

    # Legacy format (no protocol)
    spv = _detect_samples_per_value(samples)
    pixel_values = decode_from_samples(samples, spv)
    return reconstruct_image(pixel_values)


def _detect_samples_per_value(samples):
    """Auto-detect samples_per_value from audio length (legacy format only)."""
    spv = SAMPLES_PER_VALUE
    expected_values = len(samples) // spv
    if expected_values < TOTAL_VALUES and len(samples) % TOTAL_VALUES == 0:
        spv = len(samples) // TOTAL_VALUES
    return spv
