"""Tests that the AM-modulated protocol survives realistic over-the-air conditions.

Simulates:
  - Leading noise / silence (mic started before transmission)
  - Volume attenuation (distance from speaker)
  - Additive white noise (ambient sound)
  - Varying attenuation levels
"""

import os
import wave

import numpy as np
from PIL import Image

from pictalkie import constants
from pictalkie.audio import (
    decode_wav_file,
    encode_to_samples,
    decode_from_samples,
    parse_protocol,
    resample_samples,
    load_wav,
    _crc16_ccitt,
    _header_payload_bytes,
    _apply_correction,
    _baird_amplitude,
    _isotonic_regression,
)
from pictalkie.image import load_and_process_image, extract_pixels_hilbert


def _encode_test_image(color=(255, 0, 0)):
    """Create and encode a solid-color 256x256 test image."""
    img = Image.new("RGB", (256, 256), color)
    temp_path = "_test_modem_img.png"
    try:
        img.save(temp_path)
        processed = load_and_process_image(temp_path)
        pixel_values = extract_pixels_hilbert(processed)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    samples = encode_to_samples(pixel_values, width=256, height=256, channels=3)
    return samples, pixel_values


def _simulate_channel(samples, attenuation=0.5, noise_level=0.0, lead_silence=1.0):
    """Simulate an over-the-air channel with attenuation, noise, and leading silence."""
    lead_samples = int(lead_silence * constants.SAMPLE_RATE)
    noise_pad = np.random.normal(0, 0.01, lead_samples).astype(np.float32)
    padded = np.concatenate([noise_pad, samples])
    attenuated = padded * attenuation
    if noise_level > 0:
        channel_noise = np.random.normal(0, noise_level, len(attenuated)).astype(np.float32)
        attenuated = attenuated + channel_noise
    return attenuated


def _save_pcm_wav(samples, sample_rate, filepath):
    """Write mono float samples as a 16-bit PCM WAV with an explicit rate."""
    with wave.open(str(filepath), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(pcm.tobytes())


def test_modem_robustness():
    """Protocol detection survives leading noise and 50% volume attenuation."""
    samples, _ = _encode_test_image()
    received = _simulate_channel(samples, attenuation=0.5)

    protocol = parse_protocol(received)
    assert protocol is not None, "Protocol should be detected"
    assert protocol["width"] == 256
    assert protocol["height"] == 256
    assert protocol["channels"] == 3


def test_decode_pixels_attenuated():
    """Decoded pixel values match original after 50% attenuation + calibration correction."""
    samples, original_values = _encode_test_image(color=(200, 100, 50))
    received = _simulate_channel(samples, attenuation=0.5)

    protocol = parse_protocol(received)
    assert protocol is not None, "Protocol not detected"

    data = received[protocol["data_offset"]:]
    decoded = decode_from_samples(data, constants.SAMPLES_PER_VALUE, protocol["calibration"])

    # With calibration correction, attenuated signal should decode perfectly
    n = min(len(original_values), len(decoded))
    orig = np.array(original_values[:n])
    dec = np.array(decoded[:n])
    assert np.array_equal(orig, dec), (
        f"Pixel mismatch: {np.sum(orig != dec)} of {n} values differ, "
        f"max error {np.max(np.abs(orig.astype(int) - dec.astype(int)))}"
    )


def test_decode_survives_noise():
    """Decoded pixels are close to originals with moderate additive noise.

    With 0.5% noise, calibration and pixel data both accumulate error,
    so we allow +-5 per channel (still visually indistinguishable).
    """
    samples, original_values = _encode_test_image(color=(128, 64, 192))
    received = _simulate_channel(samples, attenuation=0.7, noise_level=0.005)

    protocol = parse_protocol(received)
    assert protocol is not None, "Protocol not detected under noise"

    data = received[protocol["data_offset"]:]
    decoded = decode_from_samples(data, constants.SAMPLES_PER_VALUE, protocol["calibration"])

    n = min(len(original_values), len(decoded))
    orig = np.array(original_values[:n])
    dec = np.array(decoded[:n])
    max_err = np.max(np.abs(orig.astype(int) - dec.astype(int)))
    mean_err = np.mean(np.abs(orig.astype(int) - dec.astype(int)))
    assert max_err <= 5, f"Max pixel error {max_err} exceeds tolerance of 5"
    assert mean_err < 1.0, f"Mean pixel error {mean_err:.2f} too high"


def test_attenuation_levels():
    """Protocol and decode work at 25%, 50%, and 75% attenuation."""
    samples, original_values = _encode_test_image(color=(50, 150, 250))

    for attenuation in [0.25, 0.5, 0.75]:
        received = _simulate_channel(samples, attenuation=attenuation)
        protocol = parse_protocol(received)
        assert protocol is not None, f"Protocol not detected at {attenuation:.0%} volume"

        data = received[protocol["data_offset"]:]
        decoded = decode_from_samples(data, constants.SAMPLES_PER_VALUE, protocol["calibration"])

        n = min(len(original_values), len(decoded))
        orig = np.array(original_values[:n])
        dec = np.array(decoded[:n])
        assert np.array_equal(orig, dec), (
            f"At {attenuation:.0%} volume: {np.sum(orig != dec)} values differ"
        )


def test_parse_protocol_rejects_wrong_rate_false_positive():
    """Wrong-rate recordings should not parse into a bogus header."""
    samples, _ = _encode_test_image()
    recorded = resample_samples(samples, constants.SAMPLE_RATE, 48000)
    assert parse_protocol(recorded) is None


def test_decode_wav_file_resamples_48khz_recording(tmp_path):
    """48 kHz recordings are normalized before protocol parsing and decode cleanly."""
    color = (12, 120, 240)
    samples, _ = _encode_test_image(color=color)
    recorded = resample_samples(samples, constants.SAMPLE_RATE, 48000)

    wav_path = tmp_path / "recorded_48k.wav"
    _save_pcm_wav(recorded, 48000, wav_path)

    decoded = decode_wav_file(str(wav_path))
    expected = np.array(Image.new("RGB", (256, 256), color))
    actual = np.array(decoded)
    assert np.array_equal(expected, actual), (
        f"48 kHz decode mismatch: {np.sum(expected != actual)} values differ"
    )


# --- Upgrade 1: Stereo downmix ---

def test_stereo_wav_downmix(tmp_path):
    """Stereo WAV with signal on right channel decodes correctly."""
    samples, _ = _encode_test_image(color=(100, 200, 50))
    # Build stereo interleaved: left=silence, right=signal
    stereo = np.column_stack([np.zeros_like(samples), samples]).ravel()

    wav_path = tmp_path / "stereo.wav"
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(constants.SAMPLE_RATE)
        pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(pcm.tobytes())

    loaded, rate = load_wav(str(wav_path))
    assert rate == constants.SAMPLE_RATE
    # Downmixed to half amplitude (average of 0 + signal)
    protocol = parse_protocol(loaded)
    assert protocol is not None, "Chirp should be detected from downmixed stereo"
    assert protocol["width"] == 256


# --- Upgrade 2: Full-file chirp search ---

def test_full_file_chirp_search_with_late_start():
    """Chirp detection works when signal starts after 10 seconds."""
    samples, _ = _encode_test_image()
    # Prepend 15 seconds of silence
    silence = np.zeros(int(constants.SAMPLE_RATE * 15), dtype=np.float32)
    late = np.concatenate([silence, samples])

    # Default 10-second window should miss it
    assert parse_protocol(late) is None, "Default window should miss late chirp"

    # Full-file search should find it
    protocol = parse_protocol(late, max_search_samples=len(late))
    assert protocol is not None, "Full-file search should find late chirp"
    assert protocol["width"] == 256


# --- Upgrade 3: Normalized chirp detection ---

def test_chirp_detection_volume_independent():
    """Chirp is detected at very low and normal volume levels."""
    samples, _ = _encode_test_image()

    # Very quiet signal (1% amplitude)
    quiet = samples * 0.01
    protocol = parse_protocol(quiet)
    assert protocol is not None, "Normalized detection should find quiet chirp"
    assert protocol["width"] == 256

    # Normal amplitude
    protocol = parse_protocol(samples)
    assert protocol is not None, "Normal amplitude should still detect"

    # Pure noise should not trigger
    rng = np.random.RandomState(42)
    noise = rng.normal(0, 0.5, len(samples)).astype(np.float32)
    assert parse_protocol(noise) is None, "Pure noise should not trigger chirp detection"


# --- Upgrade 4: CRC-16 checksum ---

def test_crc16_checksum_validation():
    """CRC-16 detects single-bit errors that XOR-8 would miss."""
    payload = _header_payload_bytes(256, 256, 3)
    crc = _crc16_ccitt(payload)
    assert crc == _crc16_ccitt(payload), "Deterministic CRC"

    # Flip one bit in payload — CRC should differ
    corrupted = bytearray(payload)
    corrupted[0] ^= 0x01
    assert _crc16_ccitt(bytes(corrupted)) != crc, "CRC should detect single-bit flip"

    # End-to-end: encode then decode works
    samples, _ = _encode_test_image()
    protocol = parse_protocol(samples)
    assert protocol is not None
    assert protocol["width"] == 256


# --- Upgrade 5: Monotonic calibration ---

def test_monotonic_calibration_with_noisy_curve():
    """Calibration correction handles non-monotonic calibration data."""
    # Clean monotonic calibration
    pixel_vals = np.arange(256, dtype=np.float32)
    clean_cal = _baird_amplitude(pixel_vals)

    # Add random bumps to make it non-monotonic
    rng = np.random.RandomState(99)
    noisy_cal = clean_cal + rng.normal(0, 0.01, 256).astype(np.float32)

    # Test amplitudes for known pixel values
    test_pixels = np.array([0, 50, 100, 150, 200, 255])
    test_amps = _baird_amplitude(test_pixels)

    result = _apply_correction(test_amps, noisy_cal)
    max_err = np.max(np.abs(result - test_pixels))
    assert max_err <= 3, f"Noisy calibration error {max_err} exceeds tolerance of 3"


def test_isotonic_regression_enforces_monotonicity():
    """Isotonic regression output is monotonically non-decreasing."""
    rng = np.random.RandomState(123)
    y = np.sort(rng.uniform(0, 1, 256)) + rng.normal(0, 0.05, 256)
    result = _isotonic_regression(y)
    # Check non-decreasing
    diffs = np.diff(result)
    assert np.all(diffs >= -1e-12), "Isotonic output should be non-decreasing"


# --- Upgrade 6: Timing recovery ---

def test_timing_recovery_with_clock_drift():
    """Decode survives simulated clock drift of 500 ppm."""
    samples, original_values = _encode_test_image(color=(180, 90, 45))

    protocol = parse_protocol(samples)
    assert protocol is not None

    data = samples[protocol["data_offset"]:]

    # Simulate 500 ppm clock drift: stretch the audio slightly
    drift_factor = 1 + 500e-6
    n_original = len(data)
    n_drifted = int(n_original * drift_factor)
    old_x = np.linspace(0, 1, n_original)
    new_x = np.linspace(0, 1, n_drifted)
    drifted = np.interp(new_x, old_x, data).astype(np.float32)

    # With timing recovery — should correct the drift
    decoded_tr = decode_from_samples(
        drifted, constants.SAMPLES_PER_VALUE,
        protocol["calibration"], timing_recovery=True,
    )

    n = min(len(original_values), len(decoded_tr))
    orig = np.array(original_values[:n])
    dec = np.array(decoded_tr[:n])
    max_err = np.max(np.abs(orig.astype(int) - dec.astype(int)))
    assert max_err <= 1, f"Timing recovery: max error {max_err} exceeds 1"

    # Without timing recovery — should show degraded quality
    decoded_no_tr = decode_from_samples(
        drifted, constants.SAMPLES_PER_VALUE,
        protocol["calibration"], timing_recovery=False,
    )
    n2 = min(len(original_values), len(decoded_no_tr))
    orig2 = np.array(original_values[:n2])
    dec2 = np.array(decoded_no_tr[:n2])
    err_no_tr = np.max(np.abs(orig2.astype(int) - dec2.astype(int)))
    assert err_no_tr > max_err, "Timing recovery should improve decode vs. no recovery"


if __name__ == "__main__":
    test_modem_robustness()
    test_decode_pixels_attenuated()
    test_decode_survives_noise()
    test_attenuation_levels()
    print("All modem tests passed.")
