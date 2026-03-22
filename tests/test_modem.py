import numpy as np
from pictalkie.image import load_and_process_image, extract_pixels_hilbert
from pictalkie.audio import encode_to_samples, parse_protocol
from pictalkie import constants
from PIL import Image
import time
import os

def test_modem_robustness():
    """Test that decoding survives padding noise and volume attenuation."""
    
    # 1. Create dummy image (256x256 RGB)
    img = Image.new('RGB', (256, 256), (255, 0, 0))
    temp_path = 'temp_modem_test.png'
    
    try:
        img.save(temp_path)

        # 2. Encode
        processed = load_and_process_image(temp_path)
        pixel_values = extract_pixels_hilbert(processed)
        # Explicitly provide sizes
        samples = encode_to_samples(pixel_values, width=256, height=256, channels=3)

        # 3. Simulate Microphone: Prepend noise/silence
        noise = np.random.normal(0, 0.05, constants.SAMPLE_RATE).astype(np.float32)
        mic_samples = np.concatenate([noise, samples])

        # 4. Simulate Volume Attenuation (50% drop)
        attenuated = mic_samples * 0.5

        # 5. Decode
        protocol = parse_protocol(attenuated)

        assert protocol is not None, "Protocol should be detected!"
        
        # Check if dimensions match
        assert protocol['width'] == 256, f"Expected width 256, got {protocol['width']}"
        assert protocol['height'] == 256, f"Expected height 256, got {protocol['height']}"
        assert protocol['channels'] == 3, f"Expected 3 channels, got {protocol['channels']}"
        
    finally:
        # Cleanup temp file so we don't pollute workspace
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    # Let it run directly too for manual inspection if needed
    print("Running manual inspection...")
    test_modem_robustness()
    print("All tests passed.")
