# 🏗️ PicTalkie Architecture & Design Decisions

This document outlines the module structure and the engineering logic behind the choice of parameters in PicTalkie.

---

## 🧩 Module Responsibilities

| Module | Purpose |
| :--- | :--- |
| **`hilbert.py`** | Logic for converting linear pixel indices into 2D coordinates using the **Hilbert Space-Filling Curve**. |
| **`image.py`** | Image processing pipeline: loading, padding to square, resizing, and pixel extraction/reconstruction. |
| **`audio.py`** | Digital Signal Processing (DSP) core: WAV file handling, **DPSK** header encoding/decoding, and **Vector Cross-Correlation** sync logic. |
| **`constants.py`** | Single source of truth for all tunable parameters, colors, and layout metrics. |
| **`app.py`** | Main entry point; initializes Pygame/GUI, handles the screen dispatch loop, and manages temporary cleanup. |
| **`theme.json`** | Dark UI configuration (colors, fonts, borders) for the `pygame_gui` system. |
| **`ui/components.py`** | Reusable UI components: Waveform displays, audio playback controllers, and microphone recording helpers (PyAudio/NumPy). |
| **`ui/home.py`** | Application navigation hub. |
| **`ui/encoder.py`** | Image-to-audio workspace: selection, processing, and playback. |
| **`ui/decoder.py`** | Audio-to-image workspace: supports loading WAV files or live microphone capture with real-time reconstruction. |

---

## 💡 Design Decisions

### 1. Square Padding vs. Cropping
PicTalkie uses **black-bar padding** instead of cropping to square. In emergency scenarios, preserving the *entire* image is prioritized over aesthetic fill-screen crops.

### 2. Resolution (256x256)
We increased the transmission resolution from 128x128 to **256x256** to balance detail with transmission time. At the current Baird repetition rate, a 256x256 image takes approximately **58 seconds** to transmit (under the common 1-minute VOX timeout for many walkie-talkies).

### 3. Samples Per Value (13x)
To overcome the high signal-to-noise ratio (SNR) challenges of cheap hand-held radios, each pixel value is repeated **13 times**. 
- **The Why**: Radio transmission introduces "spikes" and "dropouts". The decoder averages the 13 samples per value to cancel out random noise, acting as a robust **analog smoothing filter**.
### 4. Sample Rate Normalization (48 kHz Support)
To support modern mobile recordings (often 48 kHz), the system aligns audio samples back to the native **44.1 kHz** protocol rate continuous time-lock:
- **Resampling**: Offline WAV processing employs highly accurate Fast Fourier Transform (**FFT**) frequency-domain resampling. Live Microphone feeds employ fast **Linear Interpolation** resamplings to handle chunk arrivals without phase shifts.
- **Noise Filtering**: Both modes run continuous full-buffer **FFT bandpass filtering (brick-wall)** to avoid edge transient distortion and ensure exact pixel amplitude mapping thresholds stay artifact-free.
This aligns coordinates seamlessly ensuring time-critical chirp correlate locks without accumulating phase-drift edge pauses.

---

## 🔬 Testing Strategy

The system includes a full **"Round Trip"** test suite:

- **What it tests**: 
  1. Loads `examples/flood.jpg`.
  2. Encodes it to a temporary WAV.
  3. Decodes the WAV back into a PNG.
  4. Performs a **bit-identical comparison** between the input pixels and decoded outputs.
- **How to run**:
  ```bash
  uv run pytest tests/ -v
  ```

---

