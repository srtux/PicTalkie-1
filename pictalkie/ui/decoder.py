"""Decoder screen: select WAV or record from microphone, decode with live animation, save image."""

import time

import numpy as np
import pygame
import pygame_gui
from pygame_gui.windows import UIFileDialog

from ..constants import (
    COLOR_BG, COLOR_BLACK, COLOR_ACCENT,
    IMAGE_SIZE, CHANNELS, SAMPLE_RATE, SAMPLES_PER_VALUE,
    TOTAL_PIXELS, TOTAL_VALUES, AUDIO_DURATION,
    WINDOW_WIDTH,
    MARGIN, CONTENT_INSET, BORDER_WIDTH, LAYOUT_GAP, BUTTON_GAP,
    BACK_BTN_X, TOP_Y, BACK_BTN_W, BACK_BTN_H,
    HEADING_X, HEADING_W,
    BUTTON_ROW_Y, BUTTON_H, BUTTON_H_SM, LABEL_H,
    DIALOG_X, DIALOG_Y, DIALOG_W, DIALOG_H,
)
from ..audio import (
    load_wav,
    decode_from_samples,
    normalize_decode_samples,
    parse_protocol,
    _apply_bandpass_filter,
)
from ..hilbert import get_hilbert_order
from ..image import reconstruct_image
from .components import (
    render_waveform_surface, play_audio, stop_audio, is_audio_playing,
    MicRecorder,
)

# --- Decoder-specific layout ---
STATUS_Y = 125
WAVE_Y = 155
WAVE_H = 80
DECODE_BTN_Y = 250
DISPLAY_SIZE = 450                       # Decoded image display size (upscaled from IMAGE_SIZE)
IMAGE_Y = 305
PROGRESS_Y = IMAGE_Y + DISPLAY_SIZE + LAYOUT_GAP
SAVE_Y = PROGRESS_Y + LABEL_H + LAYOUT_GAP
PLAYBACK_LINE_W = 2                      # Waveform playback position indicator width
MIC_RECENT_CHUNKS = 50                   # Recent mic chunks shown in live waveform


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
        self.back_btn = self._btn(BACK_BTN_X, TOP_Y, BACK_BTN_W, BACK_BTN_H, "<")
        self.heading = self._label(HEADING_X, TOP_Y, HEADING_W, BACK_BTN_H, "Decoder", "#heading_label")

        half_w = (self.w - 2 * CONTENT_INSET) // 2
        self.select_btn = self._btn(MARGIN, BUTTON_ROW_Y, half_w, BUTTON_H, "Select WAV File")
        self.record_btn = self._btn(
            MARGIN + BUTTON_GAP + half_w, BUTTON_ROW_Y, half_w, BUTTON_H,
            "Record from Mic", "#accent_button",
        )

        self.decode_btn = self._btn(
            MARGIN, DECODE_BTN_Y, self.w - 2 * MARGIN, BUTTON_H,
            "DECODE TO IMAGE", "#accent_button",
        )
        self.save_btn = self._btn(
            MARGIN, SAVE_Y, self.w - 2 * MARGIN, BUTTON_H_SM,
            "Save Image as PNG", "#accent_button",
        )
        self.status_label = self._label(MARGIN, STATUS_Y, self.w - 2 * MARGIN, LABEL_H, "", "#info_label")
        self.progress_label = self._label(MARGIN, PROGRESS_Y, self.w - 2 * MARGIN, LABEL_H, "", "#progress_label")

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
                    try:
                        self.decoded_image.save(path)
                        self.status_label.set_text(f"Saved: {path}")
                    except Exception as e:
                        self.status_label.set_text(f"Save error: {e}")

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
            rect=pygame.Rect(DIALOG_X, DIALOG_Y, DIALOG_W, DIALOG_H),
            manager=self.manager,
            window_title="Select a PicTalkie WAV file",
            allowed_suffixes={".wav"},
            allow_existing_files_only=True,
        )

    def _open_save_dialog(self):
        self.save_dialog = UIFileDialog(
            rect=pygame.Rect(DIALOG_X, DIALOG_Y, DIALOG_W, DIALOG_H),
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
        self.wav_samples = normalize_decode_samples(samples, sample_rate)
        self.wav_sample_rate = SAMPLE_RATE
        self._reset_decode_state()

        duration = len(samples) / (sample_rate or SAMPLE_RATE)
        self.status_label.set_text(f"Loaded: {source}  |  {duration:.2f}s")
        self.waveform_surface = render_waveform_surface(
            self.wav_samples, self.w - 2 * CONTENT_INSET, WAVE_H,
        )
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
        self.stream_synced = False
        self.protocol_info = None
        self._last_chunk_count = 0
        self._resampled_cache = None

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

            if self.mic._chunks:
                # Continuous resampling over full buffer to avoid phase-drift rounding errors
                n_chunks = len(self.mic._chunks)
                if n_chunks > self._last_chunk_count:
                    self._last_chunk_count = n_chunks
                    current_raw = np.concatenate(self.mic._chunks)
                    device_rate = self.mic._device_rate or SAMPLE_RATE
                    if device_rate != SAMPLE_RATE:
                        from .components import _resample
                        current_samples = _resample(current_raw, device_rate, SAMPLE_RATE)
                    else:
                        current_samples = current_raw

                    current_samples = _apply_bandpass_filter(current_samples)
                    self._resampled_cache = current_samples


                current_samples = self._resampled_cache
                if current_samples is None:
                    return


                if not self.stream_synced:
                    protocol = parse_protocol(current_samples)
                    if protocol:
                        self.stream_synced = True
                        self.protocol_info = protocol
                        self.image_width = protocol['width']
                        self.image_height = protocol['height']
                        self.image_channels = protocol['channels']
                        self.total_pixels = self.image_width * self.image_height
                        
                        self.hilbert_order = get_hilbert_order(self.image_width)
                        self.live_surface = pygame.Surface((self.image_width, self.image_height))
                        self.live_surface.fill((0, 0, 0))
                        self.pixels_decoded = 0
                        self.status_label.set_text("Synced! Decoding live...")

                if self.stream_synced:
                    data = current_samples[self.protocol_info['data_offset']:]

                    # Decode only the tail we haven't decoded yet
                    already = len(self.all_pixel_values) if self.all_pixel_values else 0
                    skip_samples = already * SAMPLES_PER_VALUE
                    if skip_samples < len(data):
                        new_vals = decode_from_samples(
                            data[skip_samples:], SAMPLES_PER_VALUE,
                            self.protocol_info['calibration'],
                        )


                        if self.all_pixel_values is None:
                            self.all_pixel_values = new_vals
                        else:
                            self.all_pixel_values.extend(new_vals)

                    if self.all_pixel_values is None:
                        return

                    target_pixels = min(len(self.all_pixel_values) // self.image_channels, self.total_pixels)
                    
                    if target_pixels > self.pixels_decoded:
                        for p in range(self.pixels_decoded, target_pixels):
                            if p < len(self.hilbert_order):
                                hx, hy = self.hilbert_order[p]
                                base = p * self.image_channels
                                if self.image_channels == 1:
                                    if base < len(self.all_pixel_values):
                                        v = self.all_pixel_values[base]
                                        self.live_surface.set_at((hx, hy), (v, v, v))
                                else:
                                    if base + 2 < len(self.all_pixel_values):
                                        self.live_surface.set_at((hx, hy), (
                                            self.all_pixel_values[base],
                                            self.all_pixel_values[base + 1],
                                            self.all_pixel_values[base + 2],
                                        ))
                        self.pixels_decoded = target_pixels
                        self.live_display = pygame.transform.scale(self.live_surface, (DISPLAY_SIZE, DISPLAY_SIZE))
                        pct = (self.pixels_decoded / self.total_pixels) * 100
                        self.progress_label.set_text(f"Decoded: {self.pixels_decoded:,} / {self.total_pixels:,} pixels ({pct:.0f}%)")

                    if self.pixels_decoded >= self.total_pixels:
                        self.mic.stop()
                        self.mic_recording = False
                        self.record_btn.set_text("Record from Mic")
                        
                        self.decoded = True
                        self.decoding = False
                        self.decoded_image = reconstruct_image(self.all_pixel_values, self.image_width, self.image_channels)
                        self.decoded_surface = self.live_display
                        self.save_btn.show()
                        self.progress_label.set_text(f"Decoded: {self.image_width}x{self.image_height} complete!")
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
                    if self.image_channels == 1:
                        if base < len(self.all_pixel_values):
                            v = self.all_pixel_values[base]
                            self.live_surface.set_at((hx, hy), (v, v, v))
                    else:
                        if base + 2 < len(self.all_pixel_values):
                            self.live_surface.set_at((hx, hy), (
                                self.all_pixel_values[base],
                                self.all_pixel_values[base + 1],
                                self.all_pixel_values[base + 2],
                            ))
            self.pixels_decoded = target_pixels
            self.live_display = pygame.transform.scale(
                self.live_surface, (DISPLAY_SIZE, DISPLAY_SIZE),
            )
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

        wave_w = self.w - 2 * CONTENT_INSET

        # Waveform
        if self.waveform_surface:
            pygame.draw.rect(surface, COLOR_BLACK, (CONTENT_INSET, WAVE_Y, wave_w, WAVE_H))
            surface.blit(self.waveform_surface, (CONTENT_INSET, WAVE_Y))

            # Playback position
            if self.decoding and self.decode_start_time is not None:
                elapsed = time.time() - self.decode_start_time
                total_dur = len(self.wav_samples) / (self.wav_sample_rate or SAMPLE_RATE)
                prog = min(elapsed / total_dur, 1.0) if total_dur > 0 else 0
                px = CONTENT_INSET + int(prog * wave_w)
                pygame.draw.line(
                    surface, COLOR_ACCENT,
                    (px, WAVE_Y), (px, WAVE_Y + WAVE_H), PLAYBACK_LINE_W,
                )

        # Recording level indicator
        if self.mic_recording and self.mic._chunks:
            pygame.draw.rect(surface, COLOR_BLACK, (CONTENT_INSET, WAVE_Y, wave_w, WAVE_H))
            recent = self.mic._chunks[-MIC_RECENT_CHUNKS:]
            if recent:
                recent_samples = np.concatenate(recent)
                from .components import draw_waveform
                draw_waveform(surface, recent_samples, CONTENT_INSET, WAVE_Y, wave_w, WAVE_H, color=COLOR_ACCENT)

        # Live image reconstruction (during mic recording, WAV decode, or after completion)
        display_surf = self.live_display if (self.decoding or self.mic_recording) else self.decoded_surface
        if display_surf:
            img_x = self.w // 2 - DISPLAY_SIZE // 2
            border_size = DISPLAY_SIZE + 2 * BORDER_WIDTH
            pygame.draw.rect(
                surface, COLOR_BLACK,
                (img_x - BORDER_WIDTH, IMAGE_Y - BORDER_WIDTH, border_size, border_size),
            )
            surface.blit(display_surf, (img_x, IMAGE_Y))
