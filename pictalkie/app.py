"""Main application loop: Pygame + pygame_gui initialization, screen management."""

import os
import sys

import pygame
import pygame_gui

from .constants import WINDOW_WIDTH, WINDOW_HEIGHT, FPS, SAMPLE_RATE
from .ui.home import HomeScreen
from .ui.encoder import EncoderScreen
from .ui.decoder import DecoderScreen


def _theme_path():
    return os.path.join(os.path.dirname(__file__), "theme.json")


def _cleanup_temp_files():
    """Remove temporary WAV files created during the session."""
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ("_temp_pictalkie.wav", "_temp_pictalkie_decode.wav"):
        path = os.path.normpath(os.path.join(base, "..", name))
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def main():
    """Initialize Pygame, create screens, and run the main event/render loop."""
    pygame.init()
    pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1)

    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("PicTalkie - Off-Grid Image Transmission")
    clock = pygame.time.Clock()

    manager = pygame_gui.UIManager((WINDOW_WIDTH, WINDOW_HEIGHT), _theme_path())

    screens = {
        'home': HomeScreen(manager),
        'encoder': EncoderScreen(manager),
        'decoder': DecoderScreen(manager),
    }

    current = 'home'
    screens['encoder'].hide()
    screens['decoder'].hide()

    def switch_to(name):
        nonlocal current
        screens[current].hide()
        current = name
        screens[current].show()

    running = True
    while running:
        time_delta = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            manager.process_events(event)

            result = screens[current].handle_event(event)
            if result == 'back':
                switch_to('home')
            elif result in screens:
                switch_to(result)

        manager.update(time_delta)

        if hasattr(screens[current], 'update'):
            screens[current].update()

        screens[current].draw_background(screen)
        manager.draw_ui(screen)
        pygame.display.flip()

    _cleanup_temp_files()
    pygame.quit()
    sys.exit()
