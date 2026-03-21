"""End-to-end round-trip test: image -> WAV -> decoded image."""

from pathlib import Path

import numpy as np

from pictalkie.image import load_and_process_image, extract_pixels_hilbert
from pictalkie.audio import encode_to_samples, save_wav, decode_wav_file

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
INPUT_IMAGE = EXAMPLES_DIR / "flood.jpg"
OUTPUT_WAV = EXAMPLES_DIR / "sample.wav"
OUTPUT_IMAGE = EXAMPLES_DIR / "output.png"


def test_round_trip():
    """Encode flood.jpg to WAV, decode back to PNG, verify pixel-perfect match."""
    assert INPUT_IMAGE.exists(), f"Missing test input: {INPUT_IMAGE}"

    # Encode
    processed = load_and_process_image(str(INPUT_IMAGE))
    pixel_values = extract_pixels_hilbert(processed)
    samples = encode_to_samples(pixel_values)
    save_wav(samples, str(OUTPUT_WAV))

    # Decode
    decoded = decode_wav_file(str(OUTPUT_WAV))
    decoded.save(str(OUTPUT_IMAGE))

    # Compare pixel-by-pixel
    original_pixels = np.array(processed)
    decoded_pixels = np.array(decoded)

    assert original_pixels.shape == decoded_pixels.shape, (
        f"Shape mismatch: {original_pixels.shape} vs {decoded_pixels.shape}"
    )
    assert np.array_equal(original_pixels, decoded_pixels), (
        f"Pixel mismatch: {np.sum(original_pixels != decoded_pixels)} values differ"
    )


if __name__ == "__main__":
    test_round_trip()
    print("PASS: round-trip is pixel-perfect")
