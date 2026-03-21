"""Image loading, processing, and reconstruction via Hilbert curve ordering."""

from PIL import Image

from .constants import IMAGE_SIZE, CHANNELS
from .hilbert import get_hilbert_order


def load_and_process_image(image_path):
    """Load any image, pad to square with black bars (no cropping), resize to IMAGE_SIZE x IMAGE_SIZE.

    Padding preserves the complete original image -- critical for emergencies
    where no part of the image can be lost.

    Returns:
        PIL Image (IMAGE_SIZE x IMAGE_SIZE, RGB).
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    square_size = max(w, h)

    padded = Image.new("RGB", (square_size, square_size), (0, 0, 0))
    padded.paste(img, ((square_size - w) // 2, (square_size - h) // 2))
    return padded.resize((IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS)


def extract_pixels_hilbert(img):
    """Extract pixel R, G, B values in Hilbert curve order.

    Returns:
        List of TOTAL_VALUES ints (0-255): [R0, G0, B0, R1, G1, B1, ...].
    """
    pixels = list(img.getdata())
    order = get_hilbert_order(IMAGE_SIZE)
    values = []
    for x, y in order:
        r, g, b = pixels[y * IMAGE_SIZE + x]
        values.extend([r, g, b])
    return values


def reconstruct_image(pixel_values, image_size=IMAGE_SIZE, channels=CHANNELS):
    """Place decoded pixel values back onto a 2D grid using inverse Hilbert mapping.

    Args:
        pixel_values: Flat list of ints (0-255) in Hilbert order.

    Returns:
        PIL Image (image_size x image_size, RGB).
    """
    img = Image.new("RGB", (image_size, image_size), (0, 0, 0))
    pixels = img.load()
    order = get_hilbert_order(image_size)
    n_pixels = min(image_size * image_size, len(pixel_values) // channels)

    for d in range(n_pixels):
        x, y = order[d]
        base = d * channels
        if base + 2 < len(pixel_values):
            pixels[x, y] = (pixel_values[base], pixel_values[base + 1], pixel_values[base + 2])

    return img
