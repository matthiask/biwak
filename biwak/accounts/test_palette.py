"""The palette's contrast (specs/keyboard.md, "The palette"): WCAG AA for
every color, in light and dark, read from the tokens in
``frontend/styles/main.css``, which the accent colors and the project colors
(specs/project-colors.md) share"""

import re

from django.conf import settings
from django.test import SimpleTestCase

from biwak.accounts.models import PALETTE, Accent


CSS = (settings.BASE_DIR / "frontend/styles/main.css").read_text()

SHADES = ["fill", "fill-hover", "text", "text-hover", "bar", "tint-bg", "tint-ink"]
RING = "ring"
WHITE = (255, 255, 255)
# The navigation's text, as in main.css (rgba(255, 255, 255, 0.78))
NAV_TEXT_ALPHA = 0.78


def declarations(selector):
    """The declarations of every rule with exactly this selector"""
    return "".join(
        re.findall(
            r"^" + re.escape(selector) + r"\s*\{(.*?)\}", CSS, re.DOTALL | re.MULTILINE
        )
    )


def tokens(mode):
    """The palette's tokens of one theme: {"lake": {"fill": (r, g, b)}}"""
    result = {}
    for name, shade, value in re.findall(
        r"--wb-palette-([a-z]+)-([a-z-]+):\s*(#[0-9a-f]{6});", _theme_block(mode)
    ):
        result.setdefault(name, {})[shade] = _rgb(value)
    return result


def _theme_block(mode):
    return declarations(f'[data-bs-theme="{mode}"]')


def _rgb(value):
    if len(value) == 4:  # #fff
        value = "#" + "".join(digit * 2 for digit in value[1:])
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def page_colors(mode):
    """The page's and the cards' backgrounds"""
    text = _theme_block(mode) + (
        declarations(':root,\n[data-bs-theme="light"]') if mode == "light" else ""
    )
    return [
        _rgb(re.search(name + r":\s*(#[0-9a-f]{3,6})", text).group(1))
        for name in ["--bs-body-bg", "--wb-surface"]
    ]


def luminance(color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = map(channel, color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted([luminance(a), luminance(b)], reverse=True)
    return (high + 0.05) / (low + 0.05)


def over(alpha, foreground, background):
    return tuple(
        round(alpha * f + (1 - alpha) * b) for f, b in zip(foreground, background)
    )


TONES = ["neutral", "success", "warning", "danger"]


def tone_tokens(mode):
    """The status tones' background and ink: {"danger": {"bg": ..., "ink": ...}}"""
    result = {}
    for name, shade, value in re.findall(
        r"--wb-(" + "|".join(TONES) + r")-(bg|ink):\s*(#[0-9a-f]{6});",
        _theme_block(mode),
    ):
        result.setdefault(name, {})[shade] = _rgb(value)
    return result


class PaletteContrastTest(SimpleTestCase):
    def test_the_tones_have_contrast(self):
        """Badges (overdue to-dos, statuses): ink on its background"""
        for mode in ["light", "dark"]:
            found = tone_tokens(mode)
            self.assertEqual(sorted(found), sorted(TONES), mode)
            for name, shade in found.items():
                self.check(mode, name, "ink on bg", shade["ink"], shade["bg"], 4.5)

    def test_every_tone_has_a_class(self):
        for name in TONES[:1] + TONES[2:]:
            self.assertIn(f".wb-tone-{name} {{", CSS)

    def test_the_palette_has_every_color_and_shade(self):
        for mode in ["light", "dark"]:
            palette = tokens(mode)
            self.assertEqual(sorted(palette), sorted(PALETTE), mode)
            for name, shades in palette.items():
                self.assertEqual(sorted(shades), sorted([*SHADES, RING]), (mode, name))

    def test_the_accent_colors_are_mapped(self):
        for accent in Accent.values:
            self.assertIn(f'[data-accent="{accent}"]', CSS)

    def test_the_clients_amber_is_not_in_the_palette(self):
        self.assertNotIn("--wb-palette-amber", CSS)

    def check(self, mode, name, label, foreground, background, minimum):
        ratio = contrast(foreground, background)
        self.assertGreaterEqual(
            ratio, minimum, f"{mode} {name}: {label} has {ratio:.2f}, needs {minimum}"
        )

    def test_contrast(self):
        for mode in ["light", "dark"]:
            pages = page_colors(mode)
            for name, shade in tokens(mode).items():
                # Text on buttons and checked boxes
                for key in ["fill", "fill-hover"]:
                    self.check(mode, name, f"white on {key}", WHITE, shade[key], 4.5)
                # Buttons and checked boxes against the page: controls, 3:1
                for page in pages:
                    self.check(mode, name, "fill on the page", shade["fill"], page, 3)
                    self.check(mode, name, "ring on the page", shade[RING], page, 3)
                    # Links and text
                    for key in ["text", "text-hover"]:
                        self.check(
                            mode, name, f"{key} on the page", shade[key], page, 4.5
                        )
                # The navigation's text and its active link, on the bar
                bar = shade["bar"]
                self.check(
                    mode,
                    name,
                    "the nav text",
                    over(NAV_TEXT_ALPHA, WHITE, bar),
                    bar,
                    4.5,
                )
                self.check(mode, name, "white on the bar", WHITE, bar, 4.5)
                # Selections
                self.check(
                    mode,
                    name,
                    "ink on the tint",
                    shade["tint-ink"],
                    shade["tint-bg"],
                    4.5,
                )
