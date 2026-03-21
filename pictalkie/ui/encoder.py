"""Encoder screen: select image, preview, encode to audio, play/save."""

import pygame
import pygame_gui
from pygame_gui.windows import UIFileDialog
from PIL import Image

from ..constants import (
    COLOR_BG, COLOR_BLACK, COLOR_ACCENT,
    IMAGE_SIZE, SAMPLE_RATE, SAMPLES_PER_VALUE,
    TOTAL_SAMPLES, TOTAL_VALUES, AUDIO_DURATION,
    WINDOW_WIDTH, WINDOW_HEIGHT,
)
from ..image import load_and_process_image, extract_pixels_hilbert
from ..audio import encode_to_samples, save_wav
from .components import pil_to_pygame, draw_waveform, play_audio, stop_audio, is_audio_playing


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
        self.file_dialog = None
        self.save_dialog = None

        # UI elements
        self.back_btn = self._btn(10, 8, 50, 40, "<")
        self.heading = self._label(75, 8, 300, 40, "Encoder", "#heading_label")
        self.select_btn = self._btn(50, 70, self.w - 100, 48, "Select Image")
        self.encode_btn = self._btn(50, 450, self.w - 100, 48, "ENCODE TO AUDIO", "#accent_button")
        self.play_btn = self._btn(50, 520, (self.w - 120) // 2, 44, "Play")
        self.save_btn = self._btn(70 + (self.w - 120) // 2, 520, (self.w - 120) // 2, 44,
                                  "Save WAV", "#accent_button")
        self.status_label = self._label(50, 575, self.w - 100, 30, "", "#info_label")

        self.encode_btn.hide()
        self.play_btn.hide()
        self.save_btn.hide()

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

    def handle_event(self, event):
        """Returns 'back' or None."""
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.back_btn:
                stop_audio()
                self.playing = False
                return 'back'
            if event.ui_element == self.select_btn:
                self._open_select_dialog()
            if event.ui_element == self.encode_btn:
                self._encode()
            if event.ui_element == self.play_btn:
                self._toggle_playback()
            if event.ui_element == self.save_btn:
                self._open_save_dialog()

        if event.type == pygame_gui.UI_FILE_DIALOG_PATH_PICKED:
            if event.ui_element == self.file_dialog:
                self._load_image(event.text)
            elif event.ui_element == self.save_dialog:
                if self.encoded_samples is not None:
                    path = event.text
                    if not path.endswith(".wav"):
                        path += ".wav"
                    save_wav(self.encoded_samples, path)
                    self.status_label.set_text(f"Saved: {path}")

        return None

    def _open_select_dialog(self):
        self.file_dialog = UIFileDialog(
            rect=pygame.Rect(100, 50, 700, 500),
            manager=self.manager,
            window_title="Select an image",
            allowed_suffixes={".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"},
            allow_existing_files_only=True,
        )

    def _open_save_dialog(self):
        self.save_dialog = UIFileDialog(
            rect=pygame.Rect(100, 50, 700, 500),
            manager=self.manager,
            window_title="Save WAV file",
            allowed_suffixes={".wav"},
        )

    def _load_image(self, path):
        try:
            source = Image.open(path).convert("RGB")
            self.processed_image = load_and_process_image(path)

            display_orig = source.copy()
            display_orig.thumbnail((200, 200), Image.LANCZOS)
            self.source_surface = pil_to_pygame(display_orig)
            self.processed_surface = pil_to_pygame(
                self.processed_image.resize((200, 200), Image.NEAREST)
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
        pixel_values = extract_pixels_hilbert(self.processed_image)
        self.encoded_samples = encode_to_samples(pixel_values)
        self.encoded = True
        self.encode_btn.hide()
        self.play_btn.show()
        self.save_btn.show()
        self.status_label.set_text(
            f"Encoded: {AUDIO_DURATION:.2f}s | {TOTAL_SAMPLES:,} samples | {TOTAL_VALUES:,} values"
        )

    def _toggle_playback(self):
        if self.playing:
            stop_audio()
            self.playing = False
            self.play_btn.set_text("Play")
        elif self.encoded_samples is not None:
            try:
                play_audio(self.encoded_samples, "_temp_pictalkie.wav")
                self.playing = True
                self.play_btn.set_text("Stop")
            except Exception as e:
                self.status_label.set_text(f"Playback error: {e}")

    def update(self):
        if self.playing and not is_audio_playing():
            self.playing = False
            self.play_btn.set_text("Play")

    def draw_background(self, surface):
        surface.fill(COLOR_BG)

        # Draw image previews
        if self.source_surface:
            # Original
            cx = self.w // 2
            orig_rect = self.source_surface.get_rect(centerx=cx - 120, centery=220)
            pygame.draw.rect(surface, COLOR_BLACK, orig_rect.inflate(4, 4))
            surface.blit(self.source_surface, orig_rect)

            # Processed
            if self.processed_surface:
                proc_rect = self.processed_surface.get_rect(centerx=cx + 120, centery=220)
                pygame.draw.rect(surface, COLOR_BLACK, proc_rect.inflate(4, 4))
                surface.blit(self.processed_surface, proc_rect)

            # Specs text
            font = pygame.font.SysFont("Helvetica, Arial", 15)
            specs = [
                f"Resolution: {IMAGE_SIZE}x{IMAGE_SIZE}  |  RGB  |  Baird Encoding",
                f"Sample Rate: {SAMPLE_RATE:,} Hz  |  {SAMPLES_PER_VALUE} samples/value  |  Duration: {AUDIO_DURATION:.2f}s",
            ]
            for i, line in enumerate(specs):
                surf = font.render(line, True, (139, 148, 158))
                surface.blit(surf, surf.get_rect(centerx=cx, top=340 + i * 22))

        # Draw waveform if encoded
        if self.encoded and self.encoded_samples is not None:
            wave_y, wave_w, wave_h = 600, self.w - 120, 70
            pygame.draw.rect(surface, COLOR_BLACK, (60, wave_y, wave_w, wave_h))
            draw_waveform(surface, self.encoded_samples, 60, wave_y, wave_w, wave_h)
