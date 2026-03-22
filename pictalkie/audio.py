"""Audio encoding, decoding, and WAV I/O.

Encoding pipeline:
    pixel values -> protocol header + Baird amplitude -> WAV samples

Decoding pipeline:
    WAV samples -> parse protocol -> calibration correction -> pixel values

Protocol message structure:
    Preamble | Gap | Calibration | Gap | Header | Gap | Pixel Data
"""

import wave

import numpy as np

from .constants import (
    SAMPLE_RATE, SAMPLES_PER_VALUE, TOTAL_VALUES,
    IMAGE_SIZE, CHANNELS,
    VOX_WAKEUP_FREQ, VOX_WAKEUP_SAMPLES,
    CHIRP_DURATION, CHIRP_F0, CHIRP_F1, CHIRP_SAMPLES,
    GAP_SAMPLES,
    FSK_MARK, FSK_SPACE, FSK_BIT_SAMPLES, HEADER_BITS, HEADER_SAMPLES,
    CALIBRATION_LEVELS, CALIBRATION_SPV,
    PROTOCOL_SAMPLES,
)

from .image import reconstruct_image


# ---------------------------------------------------------------------------
# Digital helpers for modem especification
# ---------------------------------------------------------------------------

def _generate_chirp():
    """Generate a linear frequency sweep (Chirp) for synchronization."""
    t = np.linspace(0, CHIRP_DURATION, CHIRP_SAMPLES, endpoint=False)
    # freq(t) = f0 + (f1 - f0) * t / T
    # phase(t) = 2 * pi * int(freq(t) dt) = 2 * pi * (f0*t + (f1-f0)/2/T * t^2)
    phase = 2 * np.pi * (CHIRP_F0 * t + (CHIRP_F1 - CHIRP_F0) * t**2 / (2 * CHIRP_DURATION))
    return np.sin(phase).astype(np.float32)


def _encode_bits_afsk(bits):
    """Encode a list of bits (0 or 1) into AFSK audio samples."""
    samples = []
    t = np.linspace(0, 1.0 / SAMPLE_RATE * FSK_BIT_SAMPLES, FSK_BIT_SAMPLES, endpoint=False)
    sine_mark = np.sin(2 * np.pi * FSK_MARK * t).astype(np.float32)
    sine_space = np.sin(2 * np.pi * FSK_SPACE * t).astype(np.float32)

    for bit in bits:
        samples.append(sine_mark if bit else sine_space)

    return np.concatenate(samples)


def _int_to_bits(val, num_bits):
    """Convert an integer to a list of bits (MSB first)."""
    return [int(b) for b in format(val, f'0{num_bits}b')]


def _bits_to_int(bits):
    """Convert a list of bits back into an integer."""
    out = 0
    for bit in bits:
        out = (out << 1) | bit
    return out


def _demodulate_afsk(samples, num_bits):
    """Demodulate AFSK audio samples into a list of bits."""
    bits = []
    t = np.linspace(0, 1.0 / SAMPLE_RATE * FSK_BIT_SAMPLES, FSK_BIT_SAMPLES, endpoint=False)
    sine_mark = np.sin(2 * np.pi * FSK_MARK * t).astype(np.float32)
    sine_space = np.sin(2 * np.pi * FSK_SPACE * t).astype(np.float32)

    for i in range(num_bits):
        start = i * FSK_BIT_SAMPLES
        end = start + FSK_BIT_SAMPLES
        if end > len(samples):
            break
        chunk = samples[start:end]
        
        dot_mark = np.abs(np.dot(chunk, sine_mark))
        dot_space = np.abs(np.dot(chunk, sine_space))
        bits.append(1 if dot_mark > dot_space else 0)

    return bits




# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode_to_samples(pixel_values, width=IMAGE_SIZE, height=IMAGE_SIZE, channels=CHANNELS):
    """Encode pixel values into a full protocol message.

    Message structure:
        Chirp | Gap | AFSK Header | Gap | Calibration | Gap | Pixel Data

    Returns:
        numpy float32 array of the complete audio message.
    """
    parts = []
    gap = np.zeros(GAP_SAMPLES, dtype=np.float32)

    # 0. VOX Wakeup -- steady tone to trigger radio transmission
    t_vox = np.linspace(0, 1.0 * VOX_WAKEUP_SAMPLES / SAMPLE_RATE, VOX_WAKEUP_SAMPLES, endpoint=False)
    wakeup_tone = np.sin(2 * np.pi * VOX_WAKEUP_FREQ * t_vox).astype(np.float32)
    parts.append(wakeup_tone)

    # 1. Sync Chirp -- frequency sweep for start detection

    parts.append(_generate_chirp())
    parts.append(gap)

    # 2. digital AFSK Header -- image dimensions
    # Bits: Width (16), Height (16), Channels (8), Checksum (8)
    checksum = (width ^ height ^ channels) & 0xFF
    bits = []
    bits.extend(_int_to_bits(width, 16))
    bits.extend(_int_to_bits(height, 16))
    bits.extend(_int_to_bits(channels, 8))
    bits.extend(_int_to_bits(checksum, 8))

    parts.append(_encode_bits_afsk(bits))
    parts.append(gap)

    # 3. Calibration -- all 256 amplitude levels in order
    cal_values = np.arange(CALIBRATION_LEVELS, dtype=np.float32)
    cal_amps = np.clip((cal_values - 127) / 255 + 0.2, -1.0, 1.0)
    parts.append(np.repeat(cal_amps, CALIBRATION_SPV))
    parts.append(gap)

    # 4. Pixel data -- Baird-encoded values with repetition for noise resilience
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
    """Parse protocol sections from audio samples using Chirp sync and AFSK header.

    Returns:
        dict with calibration, width, height, channels, data_offset
        or None if protocol not detected.
    """
    if len(samples) < PROTOCOL_SAMPLES:
        return None

    # 1. Sync using Chirp correlation
    template = _generate_chirp()
    search_len = min(len(samples), int(SAMPLE_RATE * 10))
    corr = np.correlate(samples[:search_len], template, mode='valid')
    peak_val = np.max(np.abs(corr))
    if peak_val < 100.0:  # Threshold for pure noise vs real chirp
        return None
    start_idx = np.argmax(np.abs(corr))
    
    offset = start_idx + CHIRP_SAMPLES + GAP_SAMPLES

    # 2. Demodulate digital AFSK Header
    if offset + HEADER_SAMPLES > len(samples):
        return None
    header_data = samples[offset:offset + HEADER_SAMPLES]
    bits = _demodulate_afsk(header_data, HEADER_BITS)

    if len(bits) < HEADER_BITS:
        return None

    width = _bits_to_int(bits[0:16])
    height = _bits_to_int(bits[16:32])
    channels = _bits_to_int(bits[32:40])
    checksum = _bits_to_int(bits[40:48])

    calc_checksum = (width ^ height ^ channels) & 0xFF
    if checksum != calc_checksum:
        print(f"Rejecting frame: Header checksum failed ({checksum} != {calc_checksum})")
        return None

    offset += HEADER_SAMPLES + GAP_SAMPLES

    # 3. Read calibration
    cal_total = CALIBRATION_LEVELS * CALIBRATION_SPV
    if offset + cal_total > len(samples):
        return None
    cal_data = samples[offset:offset + cal_total]
    calibration = cal_data.reshape(CALIBRATION_LEVELS, CALIBRATION_SPV).mean(axis=1)
    offset += cal_total + GAP_SAMPLES

    return {
        'calibration': calibration,
        'width': width,
        'height': height,
        'channels': channels,
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
