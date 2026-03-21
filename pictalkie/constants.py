"""Encoding parameters, UI theme colors, and window settings."""

# --- Encoding format ---
# Audio duration = (IMAGE_SIZE^2 * CHANNELS * SAMPLES_PER_VALUE) / SAMPLE_RATE
# These are tuned so the audio fits in a 15-second walkie-talkie transmission.

SAMPLE_RATE = 44100          # CD-quality, universally supported
IMAGE_SIZE = 128             # Largest power-of-2 that fits in 15s (Hilbert curve requires power of 2)
CHANNELS = 3                 # RGB color
SAMPLES_PER_VALUE = 13       # Repetitions per value for noise resilience (SNR ~3.6x via averaging)

# Derived
TOTAL_PIXELS = IMAGE_SIZE * IMAGE_SIZE                     # 16,384
TOTAL_VALUES = TOTAL_PIXELS * CHANNELS                     # 49,152
TOTAL_SAMPLES = TOTAL_VALUES * SAMPLES_PER_VALUE           # 638,976
AUDIO_DURATION = TOTAL_SAMPLES / SAMPLE_RATE               # ~14.49s

# --- Dark theme (GitHub-inspired) ---
COLOR_BG = (13, 17, 23)
COLOR_SURFACE = (22, 27, 34)
COLOR_SURFACE2 = (28, 35, 51)
COLOR_BORDER = (48, 54, 61)
COLOR_TEXT = (230, 237, 243)
COLOR_TEXT_DIM = (139, 148, 158)
COLOR_ACCENT = (255, 107, 53)
COLOR_ACCENT_DARK = (229, 90, 43)
COLOR_GREEN = (63, 185, 80)
COLOR_BLACK = (0, 0, 0)

# --- Window ---
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 700
FPS = 60
