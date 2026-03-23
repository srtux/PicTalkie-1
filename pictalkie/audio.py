"""Audio encoding, decoding, and WAV I/O with AM carrier modulation.

Encoding pipeline:
    pixel values -> Baird amplitude -> AM modulate onto carrier -> WAV samples

Decoding pipeline:
    WAV samples -> parse protocol -> AM demodulate (RMS) -> calibration correction -> pixel values

Protocol message structure:
    VOX Wakeup | Chirp | Gap | DPSK Header | Gap | Calibration | Gap | Pixel Data

Header uses Bell 212A-style Differential PSK: bits are encoded as phase *changes*
of a 1800 Hz carrier, making detection immune to amplitude variations. The header
is repeated 3× and majority-voted per bit for robustness.

Pixel data uses AM modulation: the carrier frequency equals SAMPLE_RATE /
SAMPLES_PER_VALUE (~3392 Hz), placing exactly one sine cycle per sample group.
RMS energy of one full sine period is phase-independent, making the decode robust
to timing misalignment over-the-air.
"""

import wave
from math import gcd

import numpy as np

from .constants import (
    SAMPLE_RATE, SAMPLES_PER_VALUE, TOTAL_VALUES,
    IMAGE_SIZE, CHANNELS,
    VOX_WAKEUP_FREQ, VOX_WAKEUP_SAMPLES,
    CHIRP_DURATION, CHIRP_F0, CHIRP_F1, CHIRP_SAMPLES,
    GAP_SAMPLES,
    DPSK_FREQ, DPSK_BIT_SAMPLES, HEADER_BITS, HEADER_REPS, HEADER_SAMPLES,
    CALIBRATION_LEVELS, CALIBRATION_REPS, CALIBRATION_TOTAL,
    PROTOCOL_SAMPLES,
    CHIRP_DETECT_THRESHOLD, CHIRP_PEAK_SIDELOBE_RATIO,
)

from .image import reconstruct_image


# ---------------------------------------------------------------------------
# Digital helpers for modem specification
# ---------------------------------------------------------------------------

def _generate_chirp():
    """Generate a linear frequency sweep (Chirp) for synchronization."""
    t = np.linspace(0, CHIRP_DURATION, CHIRP_SAMPLES, endpoint=False)
    phase = 2 * np.pi * (CHIRP_F0 * t + (CHIRP_F1 - CHIRP_F0) * t**2 / (2 * CHIRP_DURATION))
    return np.sin(phase).astype(np.float32)


def _int_to_bits(val, num_bits):
    """Convert an integer to a list of bits (MSB first)."""
    return [int(b) for b in format(val, f'0{num_bits}b')]


def _bits_to_int(bits):
    """Convert a list of bits back into an integer."""
    out = 0
    for bit in bits:
        out = (out << 1) | bit
    return out


def _is_power_of_two(value):
    """Return True when value is a positive power of two."""
    return value > 0 and (value & (value - 1)) == 0


def _crc16_ccitt(data_bytes):
    """Compute CRC-16-CCITT (polynomial 0x1021, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data_bytes:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def _header_payload_bytes(width, height, channels):
    """Pack header fields into bytes for CRC computation."""
    return bytes([
        (width >> 8) & 0xFF, width & 0xFF,
        (height >> 8) & 0xFF, height & 0xFF,
        channels & 0xFF,
    ])


def _is_valid_header(width, height, channels):
    """Reject implausible headers instead of accepting checksum collisions.

    PicTalkie currently transmits square Hilbert-mapped RGB images, so
    headers must describe a square power-of-two raster with a sane channel
    count. This filters out false positives when a recording is at the wrong
    sample rate and the DPSK symbols are misread.
    """
    if channels not in (1, 3, 4):
        return False
    if width != height:
        return False
    return _is_power_of_two(width)


# ---------------------------------------------------------------------------
# DPSK modulation (Bell 212A-style)
# ---------------------------------------------------------------------------

def _encode_dpsk(bits):
    """Encode bits using Differential Phase Shift Keying with majority voting.

    Each bit is a phase *change* of a 1800 Hz carrier:
      - bit '1' -> flip phase 180 degrees
      - bit '0' -> keep phase

    A reference symbol precedes each of HEADER_REPS repetitions.
    The decoder compares adjacent symbols — only the sign of the dot product
    matters, making detection completely immune to amplitude variations.
    """
    t = np.arange(DPSK_BIT_SAMPLES) / SAMPLE_RATE
    carrier = np.sin(2 * np.pi * DPSK_FREQ * t).astype(np.float32)

    result = []
    for _ in range(HEADER_REPS):
        phase = 1.0
        result.append(carrier * phase)  # reference symbol
        for bit in bits:
            if bit == 1:
                phase *= -1
            result.append(carrier * phase)

    return np.concatenate(result)


def _demodulate_dpsk(samples, num_bits):
    """Demodulate DPSK with majority voting across HEADER_REPS repetitions.

    For each bit, compares the dot product of adjacent symbols:
      - negative dot -> phase flipped -> bit '1'
      - positive dot -> phase same    -> bit '0'

    With 3 repetitions and majority voting, a bit error requires the same bit
    to be corrupted in 2 of 3 independent measurements.
    """
    symbols_per_rep = 1 + num_bits  # ref + data
    all_reps = []

    for r in range(HEADER_REPS):
        rep_offset = r * symbols_per_rep * DPSK_BIT_SAMPLES
        bits = []
        for i in range(num_bits):
            prev_start = rep_offset + i * DPSK_BIT_SAMPLES
            curr_start = rep_offset + (i + 1) * DPSK_BIT_SAMPLES

            if curr_start + DPSK_BIT_SAMPLES > len(samples):
                break

            prev = samples[prev_start:prev_start + DPSK_BIT_SAMPLES]
            curr = samples[curr_start:curr_start + DPSK_BIT_SAMPLES]

            dot = np.dot(prev, curr)
            bits.append(1 if dot < 0 else 0)

        if len(bits) == num_bits:
            all_reps.append(bits)

    if not all_reps:
        return []

    if len(all_reps) == 1:
        return all_reps[0]

    # Majority voting across repetitions
    result = []
    for bit_idx in range(num_bits):
        votes = sum(rep[bit_idx] for rep in all_reps)
        result.append(1 if votes > len(all_reps) // 2 else 0)

    return result


# ---------------------------------------------------------------------------
# AM carrier modulation (Baird encoding)
# ---------------------------------------------------------------------------

def _baird_amplitude(values):
    """Map pixel values (0-255) to AM carrier amplitudes in [0.1, 1.0].

    The 0.1 floor ensures even black pixels produce a measurable signal,
    distinguishable from silence/noise during over-the-air transmission.
    """
    v = np.asarray(values, dtype=np.float32)
    return 0.1 + (v / 255.0) * 0.9


def _inverse_baird(amplitudes):
    """Map AM carrier amplitudes back to pixel values (0-255)."""
    return np.clip(np.round((amplitudes - 0.1) / 0.9 * 255), 0, 255).astype(int)


def _am_modulate(baseband):
    """AM-modulate a baseband signal onto the carrier.

    Carrier frequency = SAMPLE_RATE / SAMPLES_PER_VALUE (~3392 Hz),
    giving exactly one sine cycle per sample group.
    """
    t = np.arange(len(baseband))
    carrier = np.sin(2 * np.pi * t / SAMPLES_PER_VALUE)
    return (baseband * carrier).astype(np.float32)


def _am_demodulate(signal, spv):
    """Demodulate AM signal by computing RMS energy of each sample group.

    Returns the envelope amplitude (peak, not RMS) for each group.
    With exactly one carrier cycle per group, RMS = peak / sqrt(2),
    so peak = RMS * sqrt(2). This is phase-independent.
    """
    n = len(signal) // spv
    trimmed = signal[:n * spv]
    chunks = trimmed.reshape(n, spv)
    rms = np.sqrt((chunks ** 2).mean(axis=1))
    return rms * np.sqrt(2)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def encode_to_samples(pixel_values, width=IMAGE_SIZE, height=IMAGE_SIZE, channels=CHANNELS):
    """Encode pixel values into a full protocol message.

    Message structure:
        VOX Wakeup | Chirp | Gap | DPSK Header | Gap | Calibration | Gap | Pixel Data

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

    # 2. DPSK Header -- image dimensions, repeated 3× with majority voting
    checksum = _crc16_ccitt(_header_payload_bytes(width, height, channels))
    bits = []
    bits.extend(_int_to_bits(width, 16))
    bits.extend(_int_to_bits(height, 16))
    bits.extend(_int_to_bits(channels, 8))
    bits.extend(_int_to_bits(checksum, 16))

    parts.append(_encode_dpsk(bits))
    parts.append(gap)

    # 3. Calibration -- all 256 amplitude levels, AM-modulated, repeated for averaging
    cal_values = np.arange(CALIBRATION_LEVELS, dtype=np.float32)
    cal_amps = _baird_amplitude(cal_values)
    one_rep_baseband = np.repeat(cal_amps, SAMPLES_PER_VALUE)
    one_rep_modulated = _am_modulate(one_rep_baseband)
    parts.append(np.tile(one_rep_modulated, CALIBRATION_REPS))
    parts.append(gap)

    # 4. Pixel data -- Baird amplitudes AM-modulated onto carrier
    values = np.asarray(pixel_values, dtype=np.float32)
    amplitudes = _baird_amplitude(values)
    baseband = np.repeat(amplitudes, SAMPLES_PER_VALUE)
    parts.append(_am_modulate(baseband))

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
    """Load a WAV file, normalize to float32 (-1 to +1), downmix to mono.

    Supports 8, 16, 24, and 32-bit WAV files.  Multi-channel recordings are
    averaged across channels so that signal on any channel is preserved.

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
        n_frames = len(samples) // n_channels
        samples = samples[:n_frames * n_channels]
        samples = samples.reshape(n_frames, n_channels).mean(axis=1).astype(np.float32)

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


def resample_samples(samples, from_rate, to_rate=SAMPLE_RATE):
    """Resample audio while preserving carrier amplitudes.

    The decode pipeline is tuned for SAMPLE_RATE timing. Many microphones and
    recorders save at 48 kHz, so we resample back to the native protocol rate
    before chirp/header parsing.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if from_rate == to_rate or len(samples) == 0:
        return samples

    common = gcd(int(from_rate), int(to_rate))
    up = int(to_rate) // common
    down = int(from_rate) // common

    n_in = len(samples)
    block = min(n_in, int(from_rate) * 10)  # process at most 10 seconds at a time
    result_parts = []
    pos = 0
    while pos < n_in:
        end = min(pos + block, n_in)
        chunk = samples[pos:end]
        chunk_len = len(chunk)
        target_len = int(np.round(chunk_len * up / down))
        if target_len == 0:
            break

        spectrum = np.fft.rfft(chunk)
        target_spectrum_len = target_len // 2 + 1

        if target_spectrum_len <= len(spectrum):
            resampled_spectrum = spectrum[:target_spectrum_len]
        else:
            resampled_spectrum = np.zeros(target_spectrum_len, dtype=spectrum.dtype)
            resampled_spectrum[:len(spectrum)] = spectrum

        resampled = np.fft.irfft(resampled_spectrum, n=target_len)
        resampled *= target_len / chunk_len
        result_parts.append(resampled)
        pos = end

    if not result_parts:
        return np.array([], dtype=np.float32)
    return np.concatenate(result_parts).astype(np.float32)


def normalize_decode_samples(samples, sample_rate):
    """Convert recorded audio to the protocol's native sample rate."""
    if sample_rate <= 0:
        raise ValueError(f"Invalid sample rate: {sample_rate}")
    return resample_samples(samples, sample_rate, SAMPLE_RATE)


def _apply_bandpass_filter(samples, low=800.0, high=2800.0):
    """Apply an FFT brickwall bandpass filter to remove room noise rumble.

    Args:
        samples: float32 array of audio samples at SAMPLE_RATE.
        low: Minimum frequency cut-off point in Hz.
        high: Maximum frequency cut-off point in Hz.
    """
    if len(samples) == 0:
        return samples

    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1.0 / SAMPLE_RATE)

    mask = (freqs >= low) & (freqs <= high)
    spectrum_filtered = spectrum.copy()
    spectrum_filtered[~mask] = 0

    filtered_signal = np.fft.irfft(spectrum_filtered, n=len(samples))
    return filtered_signal.astype(np.float32)

# ---------------------------------------------------------------------------
# Protocol parsing
# ---------------------------------------------------------------------------

def parse_protocol(samples, max_search_samples=None):
    """Parse protocol sections from audio samples using Chirp sync and DPSK header.

    Args:
        samples: float32 audio at SAMPLE_RATE.
        max_search_samples: how far into *samples* to look for the chirp.
            Defaults to 10 seconds (suitable for the live streaming decoder).
            Pass ``len(samples)`` when decoding a complete file so the chirp
            can be found regardless of leading silence.

    Returns:
        dict with calibration, width, height, channels, data_offset
        or None if protocol not detected.
    """
    if len(samples) < PROTOCOL_SAMPLES:
        return None

    # 1. Sync using normalized chirp correlation
    template = _generate_chirp()
    if max_search_samples is None:
        search_len = min(len(samples), int(SAMPLE_RATE * 10))
    else:
        search_len = min(len(samples), max_search_samples)
    corr = np.correlate(samples[:search_len], template, mode='valid')

    # Energy-normalize so the threshold is volume-independent (0-1 scale)
    template_energy = np.sqrt(np.sum(template ** 2))
    sq = samples[:search_len].astype(np.float64) ** 2
    cumsum = np.concatenate([[0.0], np.cumsum(sq)])
    n_corr = len(corr)
    tpl_len = len(template)
    window_energy = np.sqrt(cumsum[tpl_len:tpl_len + n_corr] - cumsum[:n_corr])
    window_energy = np.maximum(window_energy, 1e-10)
    norm_corr = np.abs(corr) / (template_energy * window_energy)

    peak_val = np.max(norm_corr)
    if peak_val < CHIRP_DETECT_THRESHOLD:
        return None

    # Peak-to-sidelobe check: reject random noise that correlates weakly everywhere
    median_corr = np.median(norm_corr)
    if median_corr > 1e-10 and peak_val / median_corr < CHIRP_PEAK_SIDELOBE_RATIO:
        return None

    start_idx = np.argmax(norm_corr)

    offset = start_idx + CHIRP_SAMPLES + GAP_SAMPLES

    # 2. Demodulate DPSK Header (3× repetition with majority voting)
    if offset + HEADER_SAMPLES > len(samples):
        return None
    header_data = samples[offset:offset + HEADER_SAMPLES]
    bits = _demodulate_dpsk(header_data, HEADER_BITS)

    if len(bits) < HEADER_BITS:
        return None

    width = _bits_to_int(bits[0:16])
    height = _bits_to_int(bits[16:32])
    channels = _bits_to_int(bits[32:40])
    checksum = _bits_to_int(bits[40:56])

    calc_checksum = _crc16_ccitt(_header_payload_bytes(width, height, channels))
    if checksum != calc_checksum:
        return None
    if not _is_valid_header(width, height, channels):
        return None

    offset += HEADER_SAMPLES + GAP_SAMPLES

    # 3. Read calibration (AM-modulated, repeated CALIBRATION_REPS times)
    if offset + CALIBRATION_TOTAL > len(samples):
        return None
    cal_data = samples[offset:offset + CALIBRATION_TOTAL]
    rep_len = CALIBRATION_LEVELS * SAMPLES_PER_VALUE
    cal_reps = cal_data.reshape(CALIBRATION_REPS, rep_len)
    cal_demod = np.array([_am_demodulate(rep, SAMPLES_PER_VALUE) for rep in cal_reps])
    calibration = cal_demod.mean(axis=0)
    offset += CALIBRATION_TOTAL + GAP_SAMPLES

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

def _timing_recovery_demodulate(signal, nominal_spv):
    """AM demodulate with global timing recovery to compensate clock drift.

    Measures the actual carrier frequency via FFT peak detection with
    parabolic interpolation, then demodulates using fractional-stride
    positioning.  Only corrects when drift exceeds ~100 ppm — below that,
    the standard integer-SPV demodulation is used unchanged, preserving
    pixel-perfect round-trips for clean signals.
    """
    total = len(signal)

    # Short signals can't accumulate meaningful drift
    if total < nominal_spv * 1000:
        return _am_demodulate(signal, nominal_spv)

    # Estimate actual carrier frequency using FFT over full signal
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(total, 1.0 / SAMPLE_RATE)

    expected_freq = SAMPLE_RATE / nominal_spv
    lo, hi = expected_freq * 0.99, expected_freq * 1.01
    mask = (freqs >= lo) & (freqs <= hi)

    search = spectrum.copy()
    search[~mask] = 0
    peak_bin = int(np.argmax(search))

    # Parabolic interpolation for sub-bin precision
    if 0 < peak_bin < len(spectrum) - 1:
        a, b, c = float(spectrum[peak_bin - 1]), float(spectrum[peak_bin]), float(spectrum[peak_bin + 1])
        denom = a - 2 * b + c
        delta = 0.5 * (a - c) / denom if abs(denom) > 1e-10 else 0.0
        peak_freq = freqs[peak_bin] + delta * (freqs[1] - freqs[0])
    else:
        peak_freq = expected_freq

    actual_spv = SAMPLE_RATE / peak_freq

    # Only correct when drift exceeds ~100 ppm
    if abs(actual_spv - nominal_spv) / nominal_spv < 100e-6:
        return _am_demodulate(signal, nominal_spv)

    # Demodulate using fractional stride to avoid resampling artifacts
    n_values = int(total / actual_spv)
    starts = (np.arange(n_values) * actual_spv).astype(int)
    offsets = np.arange(nominal_spv)
    indices = starts[:, np.newaxis] + offsets[np.newaxis, :]
    indices = np.clip(indices, 0, total - 1)
    chunks = signal[indices]
    rms = np.sqrt((chunks ** 2).mean(axis=1))
    return rms * np.sqrt(2)


def decode_from_samples(samples, samples_per_value=SAMPLES_PER_VALUE,
                        calibration=None, timing_recovery=True):
    """Decode AM-modulated audio samples back into pixel values.

    Extracts amplitude envelope via RMS, then maps to pixel values
    using calibration correction or inverse Baird formula.

    Args:
        timing_recovery: use block-based timing estimation to compensate
            clock drift.  Set False for incremental streaming decode.

    Returns:
        List of ints (0-255).
    """
    if calibration is not None and timing_recovery:
        amplitudes = _timing_recovery_demodulate(samples, samples_per_value)
    else:
        amplitudes = _am_demodulate(samples, samples_per_value)

    if calibration is not None:
        pixel_values = _apply_correction(amplitudes, calibration)
    else:
        pixel_values = _inverse_baird(amplitudes)

    return pixel_values.tolist()


def _isotonic_regression(y):
    """Pool Adjacent Violators — enforce monotonically non-decreasing.

    Runs in O(n) and is equivalent to scikit-learn's IsotonicRegression
    but avoids an external dependency.
    """
    n = len(y)
    result = y.astype(np.float64).copy()
    # Each block: [running_sum, count, start_index]
    blocks = []
    for i in range(n):
        blocks.append([result[i], 1, i])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            curr = blocks.pop()
            blocks[-1][0] += curr[0]
            blocks[-1][1] += curr[1]
    out = np.empty(n, dtype=np.float64)
    for s, c, start in blocks:
        out[start:start + c] = s / c
    return out


def _apply_correction(amplitudes, calibration):
    """Map received amplitudes to pixel values using calibration data.

    calibration[i] = measured amplitude for pixel value i after transmission.
    Enforces monotonicity via isotonic regression, then uses linear
    interpolation for sub-pixel accuracy (reduces banding artifacts).
    """
    mono_cal = _isotonic_regression(np.asarray(calibration, dtype=np.float64))
    pixel_indices = np.arange(len(mono_cal), dtype=np.float64)
    interpolated = np.interp(amplitudes, mono_cal, pixel_indices)
    return np.clip(np.round(interpolated), 0, 255).astype(int)


def decode_wav_file(filepath):
    """Full pipeline: WAV file -> reconstructed PIL Image.

    Auto-detects protocol header. Falls back to legacy format.
    Resamples recorded WAVs to the protocol's native rate when needed.
    """
    samples, sample_rate = load_wav(filepath)
    decode_samples = normalize_decode_samples(samples, sample_rate)

    protocol = parse_protocol(decode_samples, max_search_samples=len(decode_samples))
    if protocol is not None:
        data = decode_samples[protocol['data_offset']:]
        pixel_values = decode_from_samples(data, SAMPLES_PER_VALUE, protocol['calibration'])
        return reconstruct_image(pixel_values, protocol['width'], protocol['channels'])

    # Legacy format (no protocol)
    spv = _detect_samples_per_value(decode_samples)
    pixel_values = decode_from_samples(decode_samples, spv)
    return reconstruct_image(pixel_values)





def _detect_samples_per_value(samples):
    """Auto-detect samples_per_value from audio length (legacy format only)."""
    spv = SAMPLES_PER_VALUE
    expected_values = len(samples) // spv
    if expected_values < TOTAL_VALUES and len(samples) % TOTAL_VALUES == 0:
        spv = len(samples) // TOTAL_VALUES
    return spv
