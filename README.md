# PicTalkie

**Off-Grid Image Transmission via Audio**

PicTalkie lets you send a photo using ONLY a walkie-talkie radio. No internet, no cell towers, no Wi-Fi -- just two radios and sound waves. Designed for emergencies where all other communication is down.

It uses a hybrid **Digital/Analog frequency sync protocol** to combat severe radio static, noise thresholds, and volume compression gradients gracefully in under a minute of feed streaming.

---

## Quickstart

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd PicTalkie
uv sync

# 2. Launch the GUI
uv run python main.py
```

---

## Documentation

For complete technical specs, protocols, and logic flows, see the `docs/` directory:

-   [**Protocol Specification**](docs/protocol.md): Details sync Chirps, AFSK digital metadata headers, Calibration clamps, and analog frame scaling.
-   [**Core Algorithms**](docs/algorithms.md): Explains Vector Cross-Correlation synchronisation locks, snaked Hilbert space pixel order maps, and Baird Amplitude mappings.
-   [**Architecture & Design**](docs/architecture.md): Module responsibilities, SNR repetition code (13x), and resolution (256x256) decisions.

---

## Programmatic Example

PicTalkie can also reside as a standard headless backend workspace library utility:

```python
from pictalkie.image import load_and_process_image, extract_pixels_hilbert
from pictalkie.audio import encode_to_samples, save_wav, decode_wav_file

# --- Encode image to WAV file ---
img = load_and_process_image("photo.jpg")
pixel_values = extract_pixels_hilbert(img)
samples = encode_to_samples(pixel_values)
save_wav(samples, "photo.wav")

# --- Decode WAV file back to image ---
reconstructed = decode_wav_file("photo.wav")
reconstructed.save("photo_decoded.png")
```

---

## Key Specs

| Parameter        | Value                  |
|-----------------|------------------------|
| Default Res     | 256 x 256 pixels       |
| Color           | Full RGB (16.7M colors)|
| Sync type       | Linear Chirp Frequency sweep |
| Header depth    | AFSK Digital Mode      |
| Frame mapping   | Analog Baird Formula   |
| Sample Rate     | 44.1 kHz (Native / 48 kHz Resampling) |

---

## Inside the app Usage

### Encoder
1. Launch and click **Encoder**
2. Click **Select Image** and choose any image file
3. Click **ENCODE TO AUDIO** to resolve the samples buffer
4. **Play** to preview or **Save WAV** to export

### Decoder
1. Click **Select WAV File** loading pre-saved streams or toggle **Record from Mic** for live microphone capture
2. Click **DECODE TO IMAGE** to trigger pixel animation reconstruction outputs.

## Testing

Run the full round-trip verification:

```bash
uv run pytest tests/ -v
```

---

## Credits

All algorithms (Baird mapping, Hilbert traversal, AFSK sync) were customized specifically for high-noise radio propagation.
