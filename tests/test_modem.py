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


if __name__ == "__main__":
    test_modem_robustness()
    test_decode_pixels_attenuated()
    test_decode_survives_noise()
    test_attenuation_levels()
    print("All modem tests passed.")
