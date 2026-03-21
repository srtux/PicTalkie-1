"""Decoder screen: select WAV or record from microphone, decode with live animation, save image."""

import time

import numpy as np
import pygame
import pygame_gui
from pygame_gui.windows import UIFileDialog

from ..constants import (
    COLOR_BG, COLOR_BLACK, COLOR_ACCENT,
    IMAGE_SIZE, CHANNELS, SAMPLE_RATE, SAMPLES_PER_VALUE,
    TOTAL_PIXELS, TOTAL_VALUES, TOTAL_SAMPLES, AUDIO_DURATION,
    WINDOW_WIDTH, WINDOW_HEIGHT,
)
from ..audio import load_wav, decode_from_samples, parse_protocol
from ..hilbert import get_hilbert_order
from ..image import reconstruct_image
from .components import (
    render_waveform_surface, play_audio, stop_audio, is_audio_playing,
    MicRecorder,
)


class DecoderScreen:
    """Decode a Baird-encoded WAV or live microphone recording back to an image."""

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

        # Protocol state
        self.image_width = IMAGE_SIZE
        self.image_height = IMAGE_SIZE
        self.image_channels = CHANNELS
        self.total_pixels = TOTAL_PIXELS
        self.total_values = TOTAL_VALUES
        self.data_offset = 0
        self.calibration = None

        # Live animation
        self.decode_start_time = None
        self.pixels_decoded = 0
        self.all_pixel_values = None
        self.hilbert_order = None
        self.live_surface = None
        self.live_display = None
        self.playing_audio = False
        self.waveform_surface = None

        # Microphone
        self.mic = MicRecorder()
        self.mic_recording = False

        # UI
        self.back_btn = self._btn(10, 8, 50, 40, "<")
        self.heading = self._label(75, 8, 300, 40, "Decoder", "#heading_label")

        half_w = (self.w - 120) // 2
        self.select_btn = self._btn(50, 70, half_w, 48, "Select WAV File")
        self.record_btn = self._btn(70 + half_w, 70, half_w, 48, "Record from Mic", "#accent_button")

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
        # Stop recording if we navigate away
        if self.mic_recording:
            self._stop_recording()

    def handle_event(self, event):
        """Returns 'back' or None."""
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.back_btn:
                stop_audio()
                self.playing_audio = False
                if self.mic_recording:
                    self._stop_recording()
                return 'back'
            if event.ui_element == self.select_btn and not self.mic_recording:
                stop_audio()
                self.playing_audio = False
                self._open_select_dialog()
            if event.ui_element == self.record_btn:
                if self.mic_recording:
                    self._stop_recording()
                else:
                    self._start_recording()
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

    # --- Microphone recording ---

    def _start_recording(self):
        try:
            self.mic.start()
            self.mic_recording = True
            self.record_btn.set_text("Stop Recording")
            self.status_label.set_text("Recording... (click Stop when transmission ends)")
            self._reset_decode_state()
            self.decode_btn.hide()
            self.save_btn.hide()
            self.waveform_surface = None
        except Exception as e:
            self.status_label.set_text(f"Mic error: {e}")

    def _stop_recording(self):
        samples = self.mic.stop()
        self.mic_recording = False
        self.record_btn.set_text("Record from Mic")

        if len(samples) < SAMPLES_PER_VALUE:
            self.status_label.set_text("Recording too short -- no audio captured")
            return

        self._load_samples(samples, SAMPLE_RATE, source="Microphone")

    # --- File loading ---

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
            samples, sample_rate = load_wav(path)
            self._load_samples(samples, sample_rate, source=path.split('/')[-1])
        except Exception as e:
            self.status_label.set_text(f"Error: {e}")
            self.wav_samples = None

    def _load_samples(self, samples, sample_rate, source=""):
        """Common path for loading audio from WAV or microphone."""
        self.wav_samples = samples
        self.wav_sample_rate = sample_rate
        self._reset_decode_state()

        duration = len(samples) / (sample_rate or SAMPLE_RATE)
        self.status_label.set_text(f"Loaded: {source}  |  {duration:.2f}s")
        self.waveform_surface = render_waveform_surface(samples, self.w - 120, 80)
        self.decode_btn.show()
        self.save_btn.hide()

    def _reset_decode_state(self):
        self.decoded = False
        self.decoding = False
        self.decoded_image = None
        self.decoded_surface = None
        self.all_pixel_values = None
        self.live_surface = None
        self.live_display = None
        self.pixels_decoded = 0
        self.image_width = IMAGE_SIZE
        self.image_height = IMAGE_SIZE
        self.image_channels = CHANNELS
        self.total_pixels = TOTAL_PIXELS
        self.total_values = TOTAL_VALUES
        self.data_offset = 0
        self.calibration = None

    # --- Decoding ---

    def _start_decoding(self):
        if self.wav_samples is None:
            return
        try:
            protocol = parse_protocol(self.wav_samples)
            if protocol is not None:
                self.image_width = protocol['width']
                self.image_height = protocol['height']
                self.image_channels = protocol['channels']
                self.data_offset = protocol['data_offset']
                self.calibration = protocol['calibration']
                data = self.wav_samples[self.data_offset:]
            else:
                self.data_offset = 0
                self.calibration = None
                data = self.wav_samples

            self.total_pixels = self.image_width * self.image_height
            self.total_values = self.total_pixels * self.image_channels

            self.all_pixel_values = decode_from_samples(
                data, SAMPLES_PER_VALUE, self.calibration
            )
            self.hilbert_order = get_hilbert_order(self.image_width)
            self.live_surface = pygame.Surface((self.image_width, self.image_height))
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
        # Update recording timer
        if self.mic_recording:
            elapsed = self.mic.elapsed_seconds
            expected = AUDIO_DURATION
            self.progress_label.set_text(f"Recording: {elapsed:.1f}s  (expected: ~{expected:.0f}s)")
            return

        if not (self.decoding and self.all_pixel_values is not None):
            return

        elapsed = time.time() - self.decode_start_time
        sr = self.wav_sample_rate or SAMPLE_RATE
        total_duration = len(self.wav_samples) / sr
        protocol_duration = self.data_offset / sr
        data_duration = total_duration - protocol_duration

        if elapsed < protocol_duration:
            target_pixels = 0
        else:
            data_elapsed = elapsed - protocol_duration
            progress = min(data_elapsed / data_duration, 1.0) if data_duration > 0 else 1.0
            target_pixels = min(int(progress * self.total_pixels), self.total_pixels)

        if target_pixels > self.pixels_decoded:
            for p in range(self.pixels_decoded, target_pixels):
                if p < len(self.hilbert_order):
                    hx, hy = self.hilbert_order[p]
                    base = p * self.image_channels
                    if base + 2 < len(self.all_pixel_values):
                        self.live_surface.set_at((hx, hy), (
                            self.all_pixel_values[base],
                            self.all_pixel_values[base + 1],
                            self.all_pixel_values[base + 2],
                        ))
            self.pixels_decoded = target_pixels
            self.live_display = pygame.transform.scale(self.live_surface, (256, 256))
            pct = (self.pixels_decoded / self.total_pixels) * 100
            self.progress_label.set_text(f"{self.pixels_decoded:,} / {self.total_pixels:,} pixels  ({pct:.0f}%)")

        if self.pixels_decoded >= self.total_pixels:
            self.decoding = False
            self.decoded = True
            self.decoded_image = reconstruct_image(
                self.all_pixel_values, self.image_width, self.image_channels
            )
            self.decoded_surface = self.live_display
            self.save_btn.show()
            self.progress_label.set_text(
                f"{self.image_width}x{self.image_height} RGB  |  {self.total_pixels:,} pixels  |  {self.total_values:,} values decoded"
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

        # Recording level indicator
        if self.mic_recording and self.mic._chunks:
            wave_x, wave_y = 60, 155
            wave_w, wave_h = self.w - 120, 80
            pygame.draw.rect(surface, COLOR_BLACK, (wave_x, wave_y, wave_w, wave_h))
            # Show last ~1 second of audio as a live waveform
            recent = self.mic._chunks[-50:] if len(self.mic._chunks) > 50 else self.mic._chunks
            if recent:
                recent_samples = np.concatenate(recent)
                from .components import draw_waveform
                draw_waveform(surface, recent_samples, wave_x, wave_y, wave_w, wave_h, color=COLOR_ACCENT)

        # Live image reconstruction
        display_surf = self.live_display if self.decoding else self.decoded_surface
        if display_surf:
            img_x = self.w // 2 - 128
            img_y = 340
            pygame.draw.rect(surface, COLOR_BLACK, (img_x - 3, img_y - 3, 262, 262))
            surface.blit(display_surf, (img_x, img_y))
