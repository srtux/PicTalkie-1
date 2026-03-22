"""Home screen with navigation to Encoder and Decoder."""

import pygame
import pygame_gui

from ..constants import COLOR_BG, WINDOW_WIDTH, WINDOW_HEIGHT, HOME_BTN_W, HOME_BTN_H, HOME_GAP


class HomeScreen:
    """Main menu with title and two navigation buttons."""

    def __init__(self, manager):
        self.manager = manager
        cx = WINDOW_WIDTH // 2
        start_x = cx - HOME_BTN_W - HOME_GAP // 2
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
            relative_rect=pygame.Rect(start_x, btn_y, HOME_BTN_W, HOME_BTN_H),
            text="Encoder (TX)",
            manager=manager,
            object_id="#accent_button",
        )
        self.decoder_btn = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(start_x + HOME_BTN_W + HOME_GAP, btn_y, HOME_BTN_W, HOME_BTN_H),
            text="Decoder (RX)",
            manager=manager,
            object_id="#accent_button",
        )

    def show(self):
        for el in (self.title, self.subtitle, self.encoder_btn, self.decoder_btn):
            el.show()

    def hide(self):
        for el in (self.title, self.subtitle, self.encoder_btn, self.decoder_btn):
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
