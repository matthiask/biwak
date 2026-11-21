"""``looks_generated`` with images made here"""

import io
import random

from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from biwak.importer.images import looks_generated


def png(image):
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class LooksGeneratedTest(SimpleTestCase):
    def test_a_flat_square_with_letters(self):
        image = Image.new("RGB", (200, 200), (47, 128, 237))
        ImageDraw.Draw(image).text((70, 90), "AE", fill="white", font_size=60)
        self.assertTrue(looks_generated(png(image)))

    def test_a_flat_placeholder(self):
        self.assertTrue(looks_generated(png(Image.new("RGB", (80, 80), "beige"))))

    def test_a_noisy_photo(self):
        rng = random.Random(1)
        image = Image.new("RGB", (100, 100))
        image.putdata([
            tuple(rng.randrange(256) for _ in range(3)) for _ in range(10000)
        ])
        self.assertFalse(looks_generated(png(image)))

    def test_flat_corners_with_lots_of_detail(self):
        rng = random.Random(2)
        image = Image.new("RGB", (200, 200), (250, 250, 250))
        draw = ImageDraw.Draw(image)
        for _ in range(1500):
            x, y = rng.randrange(20, 180), rng.randrange(20, 180)
            draw.rectangle(
                (x, y, x + 12, y + 12),
                fill=tuple(rng.randrange(256) for _ in range(3)),
            )
        self.assertFalse(looks_generated(png(image)))

    def test_corners_differing_by_twelve(self):
        flat = Image.new("RGB", (64, 64), (100, 100, 100))
        self.assertTrue(looks_generated(png(flat)))
        flat.putpixel((0, 0), (111, 100, 100))
        self.assertTrue(looks_generated(png(flat)))
        flat.putpixel((0, 0), (112, 100, 100))
        self.assertFalse(looks_generated(png(flat)))

    def test_not_an_image(self):
        with self.assertRaises(OSError):
            looks_generated(b"nope")
