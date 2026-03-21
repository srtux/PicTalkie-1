# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                        # Install dependencies
uv sync --group dev            # Install with pytest
uv run python main.py          # Launch the GUI
uv run pytest tests/ -v        # Run all tests
uv run pytest tests/test_round_trip.py -v  # Run single test
```

## Architecture

PicTalkie transmits images as audio over walkie-talkies. The pipeline is:

**Encode:** Image → pad to square → resize to 256x256 → extract RGB in Hilbert curve order → Baird amplitude formula → repeat each value 13x → wrap in protocol (preamble, calibration, sync, header, gaps) → 16-bit PCM WAV

**Decode:** WAV → parse protocol → build calibration correction table → average each 13-sample group → map amplitudes to pixel values → place on 2D grid via inverse Hilbert curve → RGB image

### Module roles

- `baird.py`, `hilbert.py` — Pure math functions (amplitude formula, space-filling curve)
- `image.py` — Image I/O: pad/resize, extract/reconstruct pixels in Hilbert order
- `audio.py` — Audio I/O: full protocol encode/decode, WAV read/write, calibration correction
- `constants.py` — All tunable parameters, protocol timing, colors, and UI layout. No magic numbers elsewhere.
- `app.py` — Pygame main loop with three-screen dispatch (home, encoder, decoder)
- `ui/components.py` — Shared helpers: waveform rendering, audio playback, microphone recording
- `ui/encoder.py`, `ui/decoder.py` — Screen classes that manage UI state and wire together the pipeline

### Audio protocol structure

The WAV message is self-describing: `Preamble (0.3s) | Gap | Calibration (2.56s, 256 levels) | Gap | Sync (0.12s, alternating 0/255) | Gap | Header (0.03s, width/height/channels) | Gap | Pixel Data (~58s)`. The decoder auto-detects the protocol; if absent, falls back to legacy headerless format.

### Key conventions

- Screen-specific layout constants live at the top of each UI file; shared layout constants live in `constants.py`
- Audio data flows as numpy float32 arrays (`*_samples`); pixel data flows as Python int lists (`*_values`, 0-255)
- The Hilbert curve requires power-of-2 image dimensions; images are always padded (never cropped) to preserve emergency detail
- The calibration section lets the decoder correct for radio channel distortion by measuring what each amplitude level actually sounds like after transmission
