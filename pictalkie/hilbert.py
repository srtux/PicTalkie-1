"""
Hilbert space-filling curve for spatial-locality-preserving pixel ordering.

A Hilbert curve visits every point in a 2D grid exactly once while keeping
spatially close pixels close together in the sequence. If radio static corrupts
a section of audio, the damage appears as a small localized blob rather than
a long streak across the image.

Grid size must be a power of 2.
"""


def hilbert_d2xy(n, d):
    """Convert 1D Hilbert curve index `d` to (x, y) coordinates on an n x n grid."""
    x = y = 0
    s = 1
    while s < n:
        rx = 1 & (d // 2)
        ry = 1 & (d ^ rx)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        d //= 4
        s *= 2
    return (x, y)


def get_hilbert_order(size):
    """Pre-compute the full Hilbert curve path for a size x size grid.

    Returns:
        List of (x, y) tuples of length size*size.
    """
    return [hilbert_d2xy(size, d) for d in range(size * size)]
