# PicTalkie

**Off-Grid Image Transmission via Audio**

PicTalkie lets you send a photo using ONLY a walkie-talkie radio. No internet, no cell towers, no Wi-Fi -- just two radios and sound waves. Designed for emergencies where all other communication is down.

A first responder can photograph their location, transmit it as audio over a walkie-talkie, and someone miles away can decode the audio back into the original image -- all in about 58 seconds.

*Pittsburgh Regional Science & Engineering Fair Project*

## Quickstart

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd PicTalkie
uv sync

# 2. Launch the GUI
uv run python main.py
```

This opens PicTalkie's home screen. Click **Encoder** to convert an image to audio, or **Decoder** to reconstruct an image from a WAV file.

## Programmatic Example

You can use PicTalkie as a library without the GUI:

```python
from pictalkie.image import load_and_process_image, extract_pixels_hilbert
from pictalkie.audio import encode_to_samples, save_wav, decode_wav_file

# --- Encode an image to a WAV file ---
img = load_and_process_image("photo.jpg")        # Pad + resize to 256x256
pixel_values = extract_pixels_hilbert(img)        # Extract pixels in Hilbert order
samples = encode_to_samples(pixel_values)         # Convert to Baird-encoded audio
save_wav(samples, "photo.wav")                    # Save as 16-bit PCM WAV (~58s)

# --- Decode a WAV file back to an image ---
reconstructed = decode_wav_file("photo.wav")      # Full pipeline: WAV -> PIL Image
reconstructed.save("photo_decoded.png")           # Save as PNG
```

You can also use individual components:

```python
from pictalkie.baird import baird_amplitude, inverse_baird

amp = baird_amplitude(200)      # 0.486 -- pixel brightness to audio amplitude
val = inverse_baird(amp)        # 200   -- back to pixel value (lossless round-trip)

from pictalkie.hilbert import get_hilbert_order

order = get_hilbert_order(256)  # [(x, y), ...] -- 65,536 coordinates in curve order
```

## How It Works

```mermaid
graph TD
    subgraph Encoder["ENCODER (Image -> Audio)"]
        direction TB
        E1["Load image (PNG, JPG, BMP, ...)"] --> E2["Convert to RGB"]
        E2 --> E3["Pad to square with black bars\n(no cropping -- preserves full image)"]
        E3 --> E4["Resize to 256x256\n(Lanczos resampling)"]
        E4 --> E5["Extract R, G, B values\nin Hilbert curve order\n(65,536 pixels x 3 = 196,608 values)"]
        E5 --> E6["Apply Baird formula to each value\namp = (value - 127) / 255 + 0.2\n(maps 0-255 to -0.3 ... +0.7)"]
        E6 --> E7["Repeat each amplitude 13x\n(196,608 x 13 = 2,555,904 samples)"]
        E7 --> E8["Write 16-bit PCM WAV\n44,100 Hz mono | 57.96 seconds"]
    end

    subgraph Transmission["RADIO TRANSMISSION"]
        direction TB
        TX["Play WAV into walkie-talkie"] --> RX["Record audio on receiving end"]
    end

    subgraph Decoder["DECODER (Audio -> Image)"]
        direction TB
        D1["Load WAV file\n(supports 8/16/24/32-bit, stereo)"] --> D2["Normalize samples to -1.0 ... +1.0\n(extract first channel if stereo)"]
        D2 --> D3["Chunk into groups of 13 samples"]
        D3 --> D4["Average each group\n(cancels noise, recovers amplitude)\nSNR improvement = sqrt 13 ~ 3.6x"]
        D4 --> D5["Apply inverse Baird formula\nvalue = (amp - 0.2) x 255 + 127\n(maps amplitude back to 0-255)"]
        D5 --> D6["Clamp to 0-255 integer range"]
        D6 --> D7["Place pixels on 256x256 grid\nvia inverse Hilbert curve mapping"]
        D7 --> D8["Reconstruct RGB image\n256x256 pixels | 16.7M colors"]
    end

    E8 --> TX
    RX --> D1

    style Encoder fill:#1a1a2e,stroke:#ff6b35,color:#e6edf3
    style Transmission fill:#0d1117,stroke:#8b949e,color:#e6edf3
    style Decoder fill:#1a1a2e,stroke:#3fb950,color:#e6edf3
```

## Key Specs

| Parameter        | Value                  |
|-----------------|------------------------|
| Resolution      | 256 x 256 pixels       |
| Color           | Full RGB (16.7M colors)|
| Audio duration  | 57.96 seconds          |
| Sample rate     | 44,100 Hz (CD quality) |
| Noise resilience| 13x averaging (~3.6x SNR improvement) |
| Accuracy        | 100% on clean round-trip|
| Format          | Standard 16-bit PCM WAV|

## Installation

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Using uv (recommended)

```bash
uv sync                  # Install all dependencies from pyproject.toml
uv run python main.py    # Launch the app
```

### Using pip

```bash
pip install pygame-ce pygame-gui numpy pillow
python main.py
```

## Project Structure

```
PicTalkie/
  main.py                    # Entry point
  pictalkie/                 # Modular package
    __init__.py
    constants.py             # Encoding params, colors, window settings
    baird.py                 # Baird amplitude formula (pixel <-> audio)
    hilbert.py               # Hilbert space-filling curve
    image.py                 # Image load/pad/resize and reconstruction
    audio.py                 # WAV I/O, encoding, decoding pipelines
    app.py                   # Main loop, pygame_gui manager, screen dispatch
    theme.json               # Dark UI theme for pygame_gui
    ui/
      __init__.py
      components.py          # Waveform drawing, audio playback helpers
      home.py                # Home screen (navigation)
      encoder.py             # Encoder screen (image -> audio)
      decoder.py             # Decoder screen (audio -> image, live animation)
```

## Algorithms Explained

PicTalkie uses three core algorithms working together. Here's what each one does and why it matters.

### 1. Baird Amplitude Formula

*What it does:* Converts a pixel's brightness into a sound level.

Think of it like a dimmer switch -- a dark pixel becomes a quiet sound, a bright pixel becomes a loud sound. This is the same principle John Logie Baird used in the 1920s to build the first working television, where audio signals controlled the brightness of a lamp.

```
Encoding:  amplitude = (pixel_value - 127) / 255 + 0.2
Decoding:  pixel_value = (amplitude - 0.2) * 255 + 127
```

**Why the +0.2 offset?** Without it, a mid-gray pixel (value 127) would map to silence (amplitude 0). The decoder wouldn't be able to tell the difference between "gray pixel" and "no signal." The offset shifts everything up so every pixel produces a distinct sound level.

| Pixel | Color | Amplitude | Sound |
|-------|-------|-----------|-------|
| 0 | Black | -0.30 | Quiet, inverted |
| 76 | Dark gray | 0.00 | Silence point |
| 127 | Mid-gray | +0.20 | Baseline hum |
| 200 | Light | +0.49 | Moderately loud |
| 255 | White | +0.70 | Loudest |

### 2. Hilbert Space-Filling Curve

*What it does:* Decides the order in which pixels are read from the image.

Instead of reading pixels left-to-right like reading a book, PicTalkie follows a Hilbert curve -- a single path that snakes through the entire image while keeping nearby pixels close together in the sequence.

```
Hilbert order:          Row-by-row order:
0---1   14--15          0  1  2  3
    |   |               4  5  6  7
3---2   13--12          8  9  10 11
|            |          12 13 14 15
4   7---8   11
|   |   |    |
5---6   9--10
```

**Why does this matter?** If radio static corrupts a chunk of audio, it damages a consecutive sequence of pixel values. With row-by-row order, that corruption would appear as a long horizontal streak across the image. With the Hilbert curve, the same corruption appears as a small localized blob -- much less destructive to the overall image.

### 3. Flat Block Repetition (Noise Resilience)

*What it does:* Each pixel value is written as 13 identical audio samples instead of just 1.

This is PicTalkie's defense against walkie-talkie noise. When the decoder receives the audio, it groups every 13 samples and takes their average. Random noise pushes some samples up and others down, but the average cancels it out.

```
Encoder writes:  [0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49, 0.49]
                  \_________________________ 13 identical copies _________________________/

After radio noise: [0.51, 0.47, 0.52, 0.48, 0.50, 0.46, 0.53, 0.49, 0.48, 0.51, 0.47, 0.50, 0.49]
                    \_________________________ noise added to each _________________________/

Decoder averages:  0.493  (close to the original 0.49 -- noise cancelled out!)
```

The noise reduction follows the statistical law of large numbers: **SNR improvement = sqrt(N)**. With 13 repetitions, noise is reduced by a factor of ~3.6x.

### Design Decisions

- **Padding over cropping**: Images are padded with black bars to make them square, never cropped. In an emergency, every part of the image could matter -- a street sign at the edge, a building number in the corner.
- **256x256 resolution**: The Hilbert curve requires a power-of-2 grid size. 256x256 gives 65,536 pixels of detail at the cost of ~58 seconds of audio. The previous 128x128 mode fit in 15 seconds but had 4x fewer pixels.
- **13 samples per value**: Chosen to maximize noise resilience for analog radio transmission. Lower values (e.g., 3 or 5) would shorten the audio but reduce tolerance for walkie-talkie static.

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `baird.py` | Forward and inverse Baird formula (2 functions) |
| `hilbert.py` | Hilbert curve index-to-coordinate conversion |
| `image.py` | Load/pad/resize images, extract/reconstruct pixels in Hilbert order |
| `audio.py` | WAV read/write, encode pixel values to samples, decode samples to pixels |
| `constants.py` | All tunable parameters and colors in one place |
| `app.py` | Pygame + pygame_gui init, screen dispatch loop, temp file cleanup |
| `theme.json` | Dark UI theme (colors, fonts) for pygame_gui |
| `ui/components.py` | Waveform drawing, audio playback, microphone recording, PIL conversion |
| `ui/home.py` | Home screen with navigation buttons |
| `ui/encoder.py` | Image selection, preview, encoding, waveform display, audio playback |
| `ui/decoder.py` | WAV or microphone input, live pixel-by-pixel decoding animation |

## Usage

### Encoder
1. Launch PicTalkie and click **Encoder**
2. Click **Select Image** and choose any image file
3. Preview shows the original alongside the processed 256x256 version
4. Click **ENCODE TO AUDIO** to generate the audio
5. **Play** to preview or **Save WAV** to export

### Decoder
1. Click **Decoder** from the home screen
2. Load audio in one of two ways:
   - **Select WAV File** -- choose a previously saved PicTalkie WAV
   - **Record from Mic** -- record live audio from your microphone (click again to stop)
3. Click **DECODE TO IMAGE** to watch the live reconstruction
4. The image builds pixel-by-pixel in sync with audio playback
5. Click **Save Image as PNG** when complete

## License

This project was created for the Pittsburgh Regional Science & Engineering Fair.
