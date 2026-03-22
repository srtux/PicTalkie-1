"""Simulate live mic streaming: encode an image, feed chunks through the
streaming decode pipeline, and verify the result matches pixel-perfect."""

from pathlib import Path

import numpy as np

from pictalkie.audio import encode_to_samples, decode_from_samples, parse_protocol
from pictalkie.image import load_and_process_image, extract_pixels_hilbert, reconstruct_image

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
INPUT_IMAGE = EXAMPLES_DIR / "flood.jpg"


def test_streaming_decode():
    """Encode flood.jpg, feed audio in small chunks (simulating mic), decode live."""
    assert INPUT_IMAGE.exists(), f"Missing test input: {INPUT_IMAGE}"

    # --- Encode ---
    processed = load_and_process_image(str(INPUT_IMAGE))
    pixel_values = extract_pixels_hilbert(processed)
    samples = encode_to_samples(pixel_values)

    # --- Simulate mic: prepend silence + noise, attenuate ---
    noise = np.random.normal(0, 0.02, 22050).astype(np.float32)  # 0.5s noise
    mic_stream = np.concatenate([noise, samples * 0.6])           # 60% volume

    # --- Stream in chunks, mimicking MicRecorder callback ---
    chunk_size = 2048
    accumulated = np.array([], dtype=np.float32)
    protocol_info = None
    all_pixel_values = []
    samples_decoded = 0

    for start in range(0, len(mic_stream), chunk_size):
        chunk = mic_stream[start:start + chunk_size]
        accumulated = np.concatenate([accumulated, chunk])

        # Try to sync (find chirp + parse header)
        if protocol_info is None:
            protocol_info = parse_protocol(accumulated)
            if protocol_info is not None:
                print(f"  Synced at chunk {start // chunk_size}: "
                      f"{protocol_info['width']}x{protocol_info['height']} "
                      f"ch={protocol_info['channels']}")
            continue

        # Incremental decode: only new samples past data_offset
        data = accumulated[protocol_info['data_offset']:]
        new_data = data[samples_decoded:]

        if len(new_data) >= 13:  # SAMPLES_PER_VALUE
            new_values = decode_from_samples(
                new_data, 13, protocol_info['calibration']
            )
            n_decoded = (len(new_data) // 13) * 13
            samples_decoded += n_decoded
            all_pixel_values.extend(new_values)

    assert protocol_info is not None, "Protocol was never detected"

    width = protocol_info['width']
    height = protocol_info['height']
    channels = protocol_info['channels']
    total_pixels = width * height

    decoded_pixels = len(all_pixel_values) // channels
    print(f"  Decoded {decoded_pixels:,} / {total_pixels:,} pixels "
          f"({decoded_pixels / total_pixels * 100:.1f}%)")
    assert decoded_pixels >= total_pixels, (
        f"Incomplete decode: {decoded_pixels} < {total_pixels}"
    )

    # --- Verify pixel-perfect match ---
    img = reconstruct_image(all_pixel_values, width, channels, height)

    original_pixels = np.array(processed)
    decoded_pixels_arr = np.array(img)

    assert original_pixels.shape == decoded_pixels_arr.shape, (
        f"Shape mismatch: {original_pixels.shape} vs {decoded_pixels_arr.shape}"
    )
    assert np.array_equal(original_pixels, decoded_pixels_arr), (
        f"Pixel mismatch: {np.sum(original_pixels != decoded_pixels_arr)} values differ"
    )
    print("  PASS: streaming decode is pixel-perfect")


if __name__ == "__main__":
    test_streaming_decode()
