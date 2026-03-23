"""Encoder screen: select image, preview, encode to audio, play/save."""

import time
from pathlib import Path

import pygame
import pygame_gui
from pygame_gui.windows import UIFileDialog
from PIL import Image

from ..constants import (
    COLOR_BG, COLOR_BLACK, COLOR_TEXT_DIM, COLOR_ACCENT,
    IMAGE_SIZE, SAMPLE_RATE, SAMPLES_PER_VALUE,
    TOTAL_SAMPLES, TOTAL_VALUES, AUDIO_DURATION,
    WINDOW_WIDTH,
    MARGIN, CONTENT_INSET, BUTTON_GAP,
    BACK_BTN_X, TOP_Y, BACK_BTN_W, BACK_BTN_H,
    HEADING_X, HEADING_W,
    BUTTON_ROW_Y, BUTTON_H, BUTTON_H_SM, LABEL_H,
    DIALOG_X, DIALOG_Y, DIALOG_W, DIALOG_H,
)
from ..image import load_and_process_image, extract_pixels_hilbert
from ..audio import encode_to_samples, save_wav
from .components import pil_to_pygame, draw_waveform, play_audio, stop_audio, is_audio_playing

# --- Encoder-specific layout ---
PREVIEW_SIZE = 200                       # Thumbnail display size for image previews
PREVIEW_OFFSET_X = 120                   # Horizontal offset from center for each preview
PREVIEW_CENTER_Y = 220                   # Vertical center of preview images
PREVIEW_BORDER = 4                       # Border padding around preview thumbnails
ENCODE_BTN_Y = 450
PLAYBACK_BTN_Y = 520
STATUS_Y = 575
SPECS_TEXT_Y = 340
SPECS_LINE_H = 22
SPECS_FONT_SIZE = 15
WAVE_Y = 600
WAVE_H = 70


class EncoderScreen:
    """Encode an image to Baird-encoded audio."""

    def __init__(self, manager):
        self.manager = manager
        self.w = WINDOW_WIDTH
        self.elements = []

        # State
        self.source_surface = None
        self.processed_surface = None
        self.processed_image = None
        self.encoded_samples = None
        self.encoded = False
        self.playing = False
        self.playback_start_time = None
        self.file_dialog = None
        self.save_dialog = None

        # Webcam state
        self.cam = None
        self.live_preview = False
        self.cam_index = 0
        self.current_frame = None

        # UI elements
        self.back_btn = self._btn(BACK_BTN_X, TOP_Y, BACK_BTN_W, BACK_BTN_H, "<")
        self.heading = self._label(HEADING_X, TOP_Y, HEADING_W, BACK_BTN_H, "Encoder", "#heading_label")
        half_w = (self.w - 2 * MARGIN - BUTTON_GAP) // 2
        self.select_btn = self._btn(MARGIN, BUTTON_ROW_Y, half_w, BUTTON_H, "Select Image")
        self.cam_btn = self._btn(MARGIN + BUTTON_GAP + half_w, BUTTON_ROW_Y, half_w, BUTTON_H, "Live Camera")
        self.encode_btn = self._btn(
            MARGIN, ENCODE_BTN_Y, self.w - 2 * MARGIN, BUTTON_H,
            "ENCODE TO AUDIO", "#accent_button",
        )

        half_w = (self.w - 2 * CONTENT_INSET) // 2
        self.play_btn = self._btn(MARGIN, PLAYBACK_BTN_Y, half_w, BUTTON_H_SM, "Play")
        self.save_btn = self._btn(
            MARGIN + BUTTON_GAP + half_w, PLAYBACK_BTN_Y, half_w, BUTTON_H_SM,
            "Save WAV", "#accent_button",
        )
        self.status_label = self._label(MARGIN, STATUS_Y, self.w - 2 * MARGIN, LABEL_H, "", "#info_label")

        self.encode_btn.hide()
        self.play_btn.hide()
        self.save_btn.hide()
        self._auto_loaded = False

    def _btn(self, x, y, w, h, text, obj_id=None):
        btn = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(x, y, w, h), text=text,
            manager=self.manager, object_id=obj_id,
        )
        self.elements.append(btn)
        return btn

    def _label(self, x, y, w, h, text, obj_id=None):
        lbl = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(x, y, w, h), text=text,
            manager=self.manager, object_id=obj_id,
        )
        self.elements.append(lbl)
        return lbl

    def show(self):
        # One-shot: auto-load example image on first open for quick testing
        if not self._auto_loaded:
            self._auto_loaded = True
            example = Path(__file__).resolve().parent.parent.parent / "examples" / "test_image.png"

            if example.exists():
                self._load_image(str(example))
                self._encode()

        for el in self.elements:
            el.show()
        self.encode_btn.hide()
        self.play_btn.hide()
        self.save_btn.hide()
        if self.source_surface:
            self.encode_btn.show()
        if self.encoded:
            self.encode_btn.hide()
            self.play_btn.show()
            self.save_btn.show()

    def hide(self):
        for el in self.elements:
            el.hide()
        self._stop_camera()  # Insure stream stops when screen hides

    def handle_event(self, event):
        """Returns 'back' or None."""
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.back_btn:
                stop_audio()
                self.playing = False
                return 'back'
            if event.ui_element == self.select_btn:
                self._open_select_dialog()
            if event.ui_element == self.cam_btn:
                self._toggle_camera()
            if event.ui_element == self.encode_btn:
                self._encode()
            if event.ui_element == self.play_btn:
                self._toggle_playback()
            if event.ui_element == self.save_btn:
                self._open_save_dialog()

        if event.type == pygame_gui.UI_FILE_DIALOG_PATH_PICKED:
            if event.ui_element == self.file_dialog:
                self._stop_camera()  # Stop live feed if file dialog picks something
                self._load_image(event.text)
            elif event.ui_element == self.save_dialog:
                if self.encoded_samples is not None:
                    path = event.text
                    if not path.endswith(".wav"):
                        path += ".wav"
                    try:
                        save_wav(self.encoded_samples, path)
                        self.status_label.set_text(f"Saved: {path}")
                    except Exception as e:
                        self.status_label.set_text(f"Save error: {e}")

        return None

    def _toggle_camera(self):
        import cv2
        if self.live_preview:
            self._capture_frame()
            self._stop_camera()
        else:
            try:
                self.cam = cv2.VideoCapture(self.cam_index)
                if self.cam.isOpened():
                    self.live_preview = True
                    self.cam_btn.set_text("Take Picture")
                    self.status_label.set_text("Camera Active")
                    self.source_surface = None
                    self.processed_surface = None
                    self.encoded = False
                else:
                    self.status_label.set_text("Failed to open camera")
            except Exception as e:
                self.status_label.set_text(f"Camera Error: {e}")

    def _stop_camera(self):
        if self.cam:
            self.cam.release()
            self.cam = None
        self.live_preview = False
        self.cam_btn.set_text("Live Camera")

    def _capture_frame(self):
        if self.current_frame is not None:
            from PIL import Image
            # crop is already square from update()
            img = Image.fromarray(self.current_frame)
            self.processed_image = img.resize((IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS)
            
            self.processed_surface = pil_to_pygame(
                self.processed_image.resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.NEAREST)
            )
            self.encoded = False
            self.encode_btn.show()
            self.status_label.set_text("Captured frame. Ready to Encode.")

    def _open_select_dialog(self):
        self.file_dialog = UIFileDialog(
            rect=pygame.Rect(DIALOG_X, DIALOG_Y, DIALOG_W, DIALOG_H),
            manager=self.manager,
            window_title="Select an image",
            allowed_suffixes={".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"},
            allow_existing_files_only=True,
        )

    def _open_save_dialog(self):
        self.save_dialog = UIFileDialog(
            rect=pygame.Rect(DIALOG_X, DIALOG_Y, DIALOG_W, DIALOG_H),
            manager=self.manager,
            window_title="Save WAV file",
            allowed_suffixes={".wav"},
        )

    def _load_image(self, path):
        try:
            source = Image.open(path).convert("RGB")
            self.processed_image = load_and_process_image(path)

            display_orig = source.copy()
            display_orig.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
            self.source_surface = pil_to_pygame(display_orig)
            self.processed_surface = pil_to_pygame(
                self.processed_image.resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.NEAREST)
            )
            self.encoded = False
            self.encoded_samples = None
            self.encode_btn.show()
            self.play_btn.hide()
            self.save_btn.hide()
            self.status_label.set_text(f"Loaded: {path.split('/')[-1]}")
        except Exception as e:
            self.status_label.set_text(f"Error: {e}")

    def _encode(self):
        if not self.processed_image:
            return
        try:
            pixel_values = extract_pixels_hilbert(self.processed_image)
            self.encoded_samples = encode_to_samples(pixel_values)
            self.encoded = True
            self.encode_btn.hide()
            self.play_btn.show()
            self.save_btn.show()
            self.status_label.set_text(
                f"Encoded: {AUDIO_DURATION:.2f}s | {TOTAL_SAMPLES:,} samples | {TOTAL_VALUES:,} values"
            )
        except Exception as e:
            self.status_label.set_text(f"Encode Error: {e}")

    def _toggle_playback(self):
        if self.playing:
            stop_audio()
            self.playing = False
            self.play_btn.set_text("Play")
        elif self.encoded_samples is not None:
            try:
                play_audio(self.encoded_samples, "_temp_pictalkie.wav")
                self.playing = True
                self.playback_start_time = time.time()
                self.play_btn.set_text("Stop")
            except Exception as e:
                self.status_label.set_text(f"Playback error: {e}")

    def update(self):
        if self.playing and not is_audio_playing():
            self.playing = False
            self.play_btn.set_text("Play")

        if self.live_preview and self.cam:
            import cv2
            ret, frame = self.cam.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = frame_rgb.shape[:2]
                size = min(h, w)
                start_h = (h - size) // 2
                start_w = (w - size) // 2
                crop = frame_rgb[start_h:start_h+size, start_w:start_w+size]
                self.current_frame = crop
                
                from PIL import Image
                img = Image.fromarray(crop)
                img.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
                self.source_surface = pil_to_pygame(img)

    def draw_background(self, surface):
        surface.fill(COLOR_BG)

        # Draw image previews
        if self.source_surface:
            cx = self.w // 2
            orig_rect = self.source_surface.get_rect(
                centerx=cx - PREVIEW_OFFSET_X, centery=PREVIEW_CENTER_Y,
            )
            pygame.draw.rect(surface, COLOR_BLACK, orig_rect.inflate(PREVIEW_BORDER, PREVIEW_BORDER))
            surface.blit(self.source_surface, orig_rect)

            if self.processed_surface:
                proc_rect = self.processed_surface.get_rect(
                    centerx=cx + PREVIEW_OFFSET_X, centery=PREVIEW_CENTER_Y,
                )
                pygame.draw.rect(surface, COLOR_BLACK, proc_rect.inflate(PREVIEW_BORDER, PREVIEW_BORDER))
                surface.blit(self.processed_surface, proc_rect)

            font = pygame.font.SysFont("Helvetica, Arial", SPECS_FONT_SIZE)
            specs = [
                f"Resolution: {IMAGE_SIZE}x{IMAGE_SIZE}  |  RGB  |  Baird Encoding",
                f"Sample Rate: {SAMPLE_RATE:,} Hz  |  {SAMPLES_PER_VALUE} samples/value  |  Duration: {AUDIO_DURATION:.2f}s",
            ]
            for i, line in enumerate(specs):
                surf = font.render(line, True, COLOR_TEXT_DIM)
                surface.blit(surf, surf.get_rect(centerx=cx, top=SPECS_TEXT_Y + i * SPECS_LINE_H))

        # Draw waveform if encoded
        if self.encoded and self.encoded_samples is not None:
            wave_w = self.w - 2 * CONTENT_INSET
            pygame.draw.rect(surface, COLOR_BLACK, (CONTENT_INSET, WAVE_Y, wave_w, WAVE_H))
            draw_waveform(surface, self.encoded_samples, CONTENT_INSET, WAVE_Y, wave_w, WAVE_H)

            if self.playing:
                elapsed = time.time() - self.playback_start_time
                total_dur = len(self.encoded_samples) / SAMPLE_RATE
                prog = min(elapsed / total_dur, 1.0) if total_dur > 0 else 0
                px = CONTENT_INSET + int(prog * wave_w)
                pygame.draw.line(surface, COLOR_ACCENT, (px, WAVE_Y), (px, WAVE_Y + WAVE_H), 2)
