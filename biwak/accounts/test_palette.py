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


def _page_text(mode):
    return _theme_block(mode) + (
        declarations(':root,\n[data-bs-theme="light"]') if mode == "light" else ""
    )


def tinted_page(mode, bar):
    """The page's background with its share of the accent's bar mixed in
    (``color-mix(in oklab, var(--wb-accent-bar) N%, #base)``)"""
    share, base = re.search(
        r"--bs-body-bg:\s*color-mix\(in oklab,\s*var\(--wb-accent-bar\)\s*"
        r"(\d+)%,\s*(#[0-9a-f]{6})\)",
        _page_text(mode),
    ).groups()
    return oklab_mix(bar, _rgb(base), int(share) / 100)


def _linear(value):
    value /= 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _srgb(value):
    value = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return round(min(max(value, 0), 1) * 255)


def _to_oklab(color):
    r, g, b = map(_linear, color)
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * lc + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * lc - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * lc + 0.7827717662 * m - 0.8086757660 * s,
    )


def _from_oklab(lab):
    L, a, b = lab
    lc = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return tuple(
        _srgb(value)
        for value in (
            4.0767416621 * lc - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * lc + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * lc - 0.7034186147 * m + 1.7076147010 * s,
        )
    )


def oklab_mix(color, base, share):
    """``color-mix(in oklab, color share, base)``"""
    a, b = _to_oklab(color), _to_oklab(base)
    return _from_oklab(tuple(share * x + (1 - share) * y for x, y in zip(a, b)))


def page_colors(mode, bar=None):
    """The page's and the cards' backgrounds; the page's with the accent
    whose bar color is given"""
    text = _page_text(mode)
    surface = _rgb(re.search(r"--wb-surface:\s*(#[0-9a-f]{3,6})", text).group(1))
    return [tinted_page(mode, bar), surface]


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

    def test_the_text_has_contrast_on_every_tinted_page(self):
        for mode in ["light", "dark"]:
            text = _page_text(mode)
            body = _rgb(re.search(r"--bs-body-color:\s*(#[0-9a-f]{6})", text).group(1))
            alpha = float(
                re.search(
                    r"--bs-secondary-color:\s*rgba\([^)]*,\s*([\d.]+)\)", text
                ).group(1)
            )
            for name, shade in tokens(mode).items():
                for page in page_colors(mode, shade["bar"]):
                    self.check(mode, name, "text on the page", body, page, 4.5)
                    self.check(
                        mode,
                        name,
                        "secondary text on the page",
                        over(alpha, body, page),
                        page,
                        4.5,
                    )

    def test_contrast(self):
        for mode in ["light", "dark"]:
            for name, shade in tokens(mode).items():
                pages = page_colors(mode, shade["bar"])
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


class AvatarColorsTest(SimpleTestCase):
    def test_every_palette_color_has_an_avatar_rule_using_its_fill(self):
        """Initials are white on the fill: ``test_contrast`` checks white on
        every fill for 4.5:1"""
        for name in PALETTE:
            self.assertRegex(
                CSS,
                rf'\[data-avatar-color="{name}"\]\s*\{{\s*--wb-avatar-bg:'
                rf"\s*var\(--wb-palette-{name}-fill\);",
            )
        self.assertEqual(CSS.count("[data-avatar-color="), len(PALETTE))
