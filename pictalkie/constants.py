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
# Message: VOX Wakeup | Chirp | Gap | AFSK Header | Gap | Calibration | Gap | Pixel Data

VOX_WAKEUP_DURATION = 0.5        # seconds -- steady tone to open VOX gate
VOX_WAKEUP_FREQ = 1500           # Frequency (Hz)
VOX_WAKEUP_SAMPLES = int(SAMPLE_RATE * VOX_WAKEUP_DURATION)  # 22,050

CHIRP_DURATION = 0.12            # seconds -- frequency sweep for sync
CHIRP_F0 = 1000                  # Start frequency (Hz)
CHIRP_F1 = 3000                  # End frequency (Hz)
CHIRP_SAMPLES = int(SAMPLE_RATE * CHIRP_DURATION)  # 5,292


GAP_DURATION = 0.05              # 50ms silence between sections
GAP_SAMPLES = int(SAMPLE_RATE * GAP_DURATION)  # 2,205

FSK_MARK = 2200                  # Frequency for bit '1' (Hz)
FSK_SPACE = 1200                 # Frequency for bit '0' (Hz)
FSK_BIT_DURATION = 0.01          # 10ms per bit (100 Baud)
FSK_BIT_SAMPLES = int(SAMPLE_RATE * FSK_BIT_DURATION)  # 441

# Header bits: Width (16), Height (16), Channels (8), Checksum (8) = 48 bits
HEADER_BITS = 48
HEADER_SAMPLES = HEADER_BITS * FSK_BIT_SAMPLES  # 21,168

CALIBRATION_LEVELS = 256         # one for each possible pixel value (0-255)
CALIBRATION_DURATION = 2.56      # seconds -- 10ms per level
CALIBRATION_SPV = int(SAMPLE_RATE * CALIBRATION_DURATION / CALIBRATION_LEVELS)  # 441

PROTOCOL_SAMPLES = (
    VOX_WAKEUP_SAMPLES
    + CHIRP_SAMPLES
    + GAP_SAMPLES
    + HEADER_SAMPLES
    + GAP_SAMPLES
    + CALIBRATION_LEVELS * CALIBRATION_SPV
    + GAP_SAMPLES
)  # 168,021


# --- Total message ---
TOTAL_SAMPLES = PROTOCOL_SAMPLES + DATA_SAMPLES           # 2,701,875 (approx)
AUDIO_DURATION = TOTAL_SAMPLES / SAMPLE_RATE


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
WINDOW_HEIGHT = 850
FPS = 60

# --- UI Layout (shared) ---
MARGIN = 50                              # Left/right margin for full-width elements
CONTENT_INSET = 60                       # Inset for waveform/content areas
BORDER_WIDTH = 3                         # Border around displayed images
LAYOUT_GAP = 7                           # Vertical gap between layout sections
BUTTON_GAP = 20                          # Horizontal gap between side-by-side buttons

# Top bar
BACK_BTN_X = 10
TOP_Y = 8
BACK_BTN_W = 50
BACK_BTN_H = 40
HEADING_X = 75
HEADING_W = 300

# Buttons & labels
BUTTON_ROW_Y = 70
BUTTON_H = 48
BUTTON_H_SM = 44
LABEL_H = 30

# File dialog
DIALOG_X = 100
DIALOG_Y = 50
DIALOG_W = 700
DIALOG_H = 500
