"""Encoding parameters, UI theme colors, and window settings."""

# --- Encoding format ---

SAMPLE_RATE = 44100          # CD-quality, universally supported
IMAGE_SIZE = 256             # Power-of-2 required by Hilbert curve (256x256 = 65,536 pixels)
CHANNELS = 3                 # RGB color
SAMPLES_PER_VALUE = 13       # Repetitions per value for noise resilience (SNR ~3.6x via averaging)

# Derived (pixel data only)
TOTAL_PIXELS = IMAGE_SIZE * IMAGE_SIZE                     # 65,536
TOTAL_VALUES = TOTAL_PIXELS * CHANNELS                     # 196,608
DATA_SAMPLES = TOTAL_VALUES * SAMPLES_PER_VALUE            # 2,555,904

# --- Protocol sections ---
# Message: Preamble | Gap | Calibration | Gap | Sync | Gap | Header | Gap | Pixel Data

PREAMBLE_DURATION = 0.3          # seconds -- carrier tone for radio wake-up
PREAMBLE_AMPLITUDE = 0.2         # mid-gray baseline (same as Baird offset)
PREAMBLE_SAMPLES = int(SAMPLE_RATE * PREAMBLE_DURATION)  # 13,230

GAP_DURATION = 0.05              # 50ms silence between sections
GAP_SAMPLES = int(SAMPLE_RATE * GAP_DURATION)  # 2,205

CALIBRATION_LEVELS = 256         # one for each possible pixel value (0-255)
CALIBRATION_DURATION = 2.56      # seconds -- 10ms per level
CALIBRATION_SPV = int(SAMPLE_RATE * CALIBRATION_DURATION / CALIBRATION_LEVELS)  # 441

SYNC_PATTERN = [0, 255, 0, 255, 0, 255]
SYNC_COUNT = len(SYNC_PATTERN)   # 6
SYNC_DURATION = 0.12             # seconds
SYNC_SPV = int(SAMPLE_RATE * SYNC_DURATION / SYNC_COUNT)  # 882

HEADER_COUNT = 3                 # width, height, channels
HEADER_DURATION = 0.03           # seconds
HEADER_SPV = int(SAMPLE_RATE * HEADER_DURATION / HEADER_COUNT)  # 441

NUM_GAPS = 4
PROTOCOL_SAMPLES = (
    PREAMBLE_SAMPLES
    + CALIBRATION_LEVELS * CALIBRATION_SPV
    + SYNC_COUNT * SYNC_SPV
    + HEADER_COUNT * HEADER_SPV
    + NUM_GAPS * GAP_SAMPLES
)  # 141,561

# --- Total message ---
TOTAL_SAMPLES = PROTOCOL_SAMPLES + DATA_SAMPLES           # 2,697,465
AUDIO_DURATION = TOTAL_SAMPLES / SAMPLE_RATE               # ~61.17s

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
