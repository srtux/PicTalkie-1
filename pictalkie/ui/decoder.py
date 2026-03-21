"""Decoder screen: select WAV, decode with live animation, save image."""

import time

import pygame
import pygame_gui
from pygame_gui.windows import UIFileDialog

from ..constants import (
    COLOR_BG, COLOR_BLACK, COLOR_ACCENT, COLOR_GREEN,
    IMAGE_SIZE, CHANNELS, SAMPLE_RATE, SAMPLES_PER_VALUE,
    TOTAL_PIXELS, TOTAL_VALUES, WINDOW_WIDTH, WINDOW_HEIGHT,
)
from ..audio import load_wav, decode_from_samples, _detect_samples_per_value
from ..hilbert import get_hilbert_order
from ..image import reconstruct_image
from .components import (
    render_waveform_surface, play_audio, stop_audio, is_audio_playing,
)


class DecoderScreen:
    """Decode a Baird-encoded WAV back to an image with live animation."""

    def __init__(self, manager):
        self.manager = manager
        self.w = WINDOW_WIDTH
        self.elements = []

        # WAV state
        self.wav_samples = None
        self.wav_sample_rate = None

        # Decode state
        self.decoded_image = None
        self.decoded_surface = None
        self.decoding = False
        self.decoded = False

        # Live animation
        self.decode_start_time = None
        self.pixels_decoded = 0
        self.spv = SAMPLES_PER_VALUE
        self.all_pixel_values = None
        self.hilbert_order = None
        self.live_surface = None
        self.live_display = None
        self.playing_audio = False
        self.waveform_surface = None

        # UI
        self.back_btn = self._btn(10, 8, 50, 40, "<")
        self.heading = self._label(75, 8, 300, 40, "Decoder", "#heading_label")
        self.select_btn = self._btn(50, 70, self.w - 100, 48, "Select WAV File")
        self.decode_btn = self._btn(50, 280, self.w - 100, 48, "DECODE TO IMAGE", "#accent_button")
        self.save_btn = self._btn(50, 645, self.w - 100, 44, "Save Image as PNG", "#accent_button")
        self.status_label = self._label(50, 125, self.w - 100, 30, "", "#info_label")
        self.progress_label = self._label(50, 612, self.w - 100, 30, "", "#progress_label")

        self.decode_btn.hide()
        self.save_btn.hide()
        self.file_dialog = None
        self.save_dialog = None

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
        self.decode_btn.hide()
        self.save_btn.hide()
        self.progress_label.set_text("")
        if self.wav_samples is not None and not self.decoding and not self.decoded:
            self.decode_btn.show()
        if self.decoded:
            self.save_btn.show()

    def hide(self):
        for el in self.elements:
            el.hide()

    def handle_event(self, event):
        """Returns 'back' or None."""
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.back_btn:
                stop_audio()
                self.playing_audio = False
                return 'back'
            if event.ui_element == self.select_btn:
                stop_audio()
                self.playing_audio = False
                self._open_select_dialog()
            if event.ui_element == self.decode_btn:
                self._start_decoding()
            if event.ui_element == self.save_btn:
                self._open_save_dialog()

        if event.type == pygame_gui.UI_FILE_DIALOG_PATH_PICKED:
            if event.ui_element == self.file_dialog:
                self._load_wav(event.text)
            elif event.ui_element == self.save_dialog:
                if self.decoded_image:
                    path = event.text
                    if not path.endswith(".png"):
                        path += ".png"
                    self.decoded_image.save(path)
                    self.status_label.set_text(f"Saved: {path}")

        return None

    def _open_select_dialog(self):
        self.file_dialog = UIFileDialog(
            rect=pygame.Rect(100, 50, 700, 500),
            manager=self.manager,
            window_title="Select a PicTalkie WAV file",
            allowed_suffixes={".wav"},
            allow_existing_files_only=True,
        )

    def _open_save_dialog(self):
        self.save_dialog = UIFileDialog(
            rect=pygame.Rect(100, 50, 700, 500),
            manager=self.manager,
            window_title="Save decoded image",
            allowed_suffixes={".png"},
        )

    def _load_wav(self, path):
        try:
            self.wav_samples, self.wav_sample_rate = load_wav(path)
            self.decoded = False
            self.decoding = False
            self.decoded_image = None
            self.decoded_surface = None
            self.all_pixel_values = None
            self.live_surface = None
            self.live_display = None
            self.pixels_decoded = 0

            duration = len(self.wav_samples) / (self.wav_sample_rate or SAMPLE_RATE)
            n_values = len(self.wav_samples) // SAMPLES_PER_VALUE
            self.status_label.set_text(
                f"Loaded: {path.split('/')[-1]}  |  {duration:.2f}s  |  {n_values:,} values"
            )
            self.waveform_surface = render_waveform_surface(self.wav_samples, self.w - 120, 80)
            self.decode_btn.show()
            self.save_btn.hide()
        except Exception as e:
            self.status_label.set_text(f"Error: {e}")
            self.wav_samples = None

    def _start_decoding(self):
        if self.wav_samples is None:
            return
        try:
            self.spv = _detect_samples_per_value(self.wav_samples)
            self.all_pixel_values = decode_from_samples(self.wav_samples, self.spv)
            self.hilbert_order = get_hilbert_order(IMAGE_SIZE)
            self.live_surface = pygame.Surface((IMAGE_SIZE, IMAGE_SIZE))
            self.live_surface.fill(COLOR_BLACK)

            play_audio(self.wav_samples, "_temp_pictalkie_decode.wav")
            self.playing_audio = True
            self.decode_start_time = time.time()
            self.pixels_decoded = 0
            self.decoding = True
            self.decoded = False
            self.decode_btn.hide()
        except Exception as e:
            self.status_label.set_text(f"Decode error: {e}")

    def update(self):
        if not (self.decoding and self.all_pixel_values is not None):
            return

        elapsed = time.time() - self.decode_start_time
        total_duration = len(self.wav_samples) / (self.wav_sample_rate or SAMPLE_RATE)
        progress = min(elapsed / total_duration, 1.0) if total_duration > 0 else 1.0
        target_pixels = min(int(progress * TOTAL_PIXELS), TOTAL_PIXELS)

        if target_pixels > self.pixels_decoded:
            for p in range(self.pixels_decoded, target_pixels):
                if p < len(self.hilbert_order):
                    hx, hy = self.hilbert_order[p]
                    base = p * CHANNELS
                    if base + 2 < len(self.all_pixel_values):
                        self.live_surface.set_at((hx, hy), (
                            self.all_pixel_values[base],
                            self.all_pixel_values[base + 1],
                            self.all_pixel_values[base + 2],
                        ))
            self.pixels_decoded = target_pixels
            self.live_display = pygame.transform.scale(self.live_surface, (256, 256))
            pct = (self.pixels_decoded / TOTAL_PIXELS) * 100
            self.progress_label.set_text(f"{self.pixels_decoded:,} / {TOTAL_PIXELS:,} pixels  ({pct:.0f}%)")

        if self.pixels_decoded >= TOTAL_PIXELS:
            self.decoding = False
            self.decoded = True
            self.decoded_image = reconstruct_image(self.all_pixel_values)
            self.decoded_surface = self.live_display
            self.save_btn.show()
            self.progress_label.set_text(
                f"{IMAGE_SIZE}x{IMAGE_SIZE} RGB  |  {TOTAL_PIXELS:,} pixels  |  {TOTAL_VALUES:,} values decoded"
            )

        if self.playing_audio and not is_audio_playing():
            self.playing_audio = False

    def draw_background(self, surface):
        surface.fill(COLOR_BG)

        # Waveform
        if self.waveform_surface:
            wave_x, wave_y = 60, 155
            pygame.draw.rect(surface, COLOR_BLACK, (wave_x, wave_y, self.w - 120, 80))
            surface.blit(self.waveform_surface, (wave_x, wave_y))

            # Playback position
            if self.decoding and self.decode_start_time is not None:
                elapsed = time.time() - self.decode_start_time
                total_dur = len(self.wav_samples) / (self.wav_sample_rate or SAMPLE_RATE)
                prog = min(elapsed / total_dur, 1.0) if total_dur > 0 else 0
                px = wave_x + int(prog * (self.w - 120))
                pygame.draw.line(surface, COLOR_ACCENT, (px, wave_y), (px, wave_y + 80), 2)

        # Live image reconstruction
        display_surf = self.live_display if self.decoding else self.decoded_surface
        if display_surf:
            img_x = self.w // 2 - 128
            img_y = 340
            pygame.draw.rect(surface, COLOR_BLACK, (img_x - 3, img_y - 3, 262, 262))
            surface.blit(display_surf, (img_x, img_y))
