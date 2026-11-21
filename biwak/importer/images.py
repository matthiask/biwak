"""Basecamp's profile images (specs/ui-round-2.md, part C)"""

import io

from PIL import Image


SIZE = 64
# The corners of a generated image have the same color: the largest
# difference per channel is below this
CORNER_DIFFERENCE = 12
# Quantized to this many colors, the most common one covers at least this
# share of the pixels
PALETTE_COLORS = 8
DOMINANT_SHARE = 0.6


def looks_generated(data):
    """Whether Basecamp made this image itself (a flat colored square with
    white initials, or its beige placeholder) instead of a person
    uploading it. The API answers alike for both, so the content decides.

    Scaled to 64 pixels, an image looks generated when both are true:

    - the four corners have the same color (below 12 per channel);
    - quantized to 8 colors, the most common one covers at least 60% of
      the pixels.

    Checked on 2026-11-21 against 104 real people: all 68 generated images
    passed, the three closest real ones (a drawing, an illustration, a dark
    photo) didn't. Raises on data which isn't an image.
    """
    image = Image.open(io.BytesIO(data))
    image.load()
    image = image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    last = SIZE - 1
    corners = [
        image.getpixel(xy) for xy in [(0, 0), (last, 0), (0, last), (last, last)]
    ]
    if any(
        max(corner[i] for corner in corners) - min(corner[i] for corner in corners)
        >= CORNER_DIFFERENCE
        for i in range(3)
    ):
        return False
    counts = image.quantize(PALETTE_COLORS).getcolors()
    return max(count for count, _ in counts) >= DOMINANT_SHARE * SIZE * SIZE
