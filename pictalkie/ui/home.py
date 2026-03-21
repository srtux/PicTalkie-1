"""Home screen with navigation to Encoder and Decoder."""

import pygame
import pygame_gui

from ..constants import COLOR_BG, WINDOW_WIDTH, WINDOW_HEIGHT


class HomeScreen:
    """Main menu with title and two navigation buttons."""

    def __init__(self, manager):
        self.manager = manager
        cx = WINDOW_WIDTH // 2
        btn_w, btn_h, gap = 220, 60, 30
        start_x = cx - btn_w - gap // 2
        btn_y = WINDOW_HEIGHT // 2 + 20

        self.title = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(0, WINDOW_HEIGHT // 2 - 130, WINDOW_WIDTH, 80),
            text="PicTalkie",
            manager=manager,
            object_id="#title_label",
        )
        self.subtitle = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(0, WINDOW_HEIGHT // 2 - 50, WINDOW_WIDTH, 35),
            text="Off-Grid Image Transmission",
            manager=manager,
            object_id="#subtitle_label",
        )

        self.encoder_btn = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(start_x, btn_y, btn_w, btn_h),
            text="Encoder (TX)",
            manager=manager,
            object_id="#accent_button",
        )
        self.decoder_btn = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(start_x + btn_w + gap, btn_y, btn_w, btn_h),
            text="Decoder (RX)",
            manager=manager,
            object_id="#accent_button",
        )
        self.credit = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(0, WINDOW_HEIGHT - 40, WINDOW_WIDTH, 28),
            text="Pittsburgh Regional Science & Engineering Fair",
            manager=manager,
            object_id="#credit_label",
        )

    def show(self):
        for el in (self.title, self.subtitle, self.encoder_btn, self.decoder_btn, self.credit):
            el.show()

    def hide(self):
        for el in (self.title, self.subtitle, self.encoder_btn, self.decoder_btn, self.credit):
            el.hide()

    def handle_event(self, event):
        """Returns 'encoder', 'decoder', or None."""
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == self.encoder_btn:
                return 'encoder'
            if event.ui_element == self.decoder_btn:
                return 'decoder'
        return None

    def draw_background(self, surface):
        surface.fill(COLOR_BG)
