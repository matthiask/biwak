"""Changes to a person's own preferences (specs/keyboard.md); the settings
page and the API's ``me/`` call these"""

from django.db import transaction

from biwak.accounts.models import Accent, Theme


@transaction.atomic
def set_preferences(user, *, keyboard_shortcuts=None, theme=None, accent=None):
    """The person's keyboard setting, theme and accent color, what's given"""
    fields = []
    if keyboard_shortcuts is not None:
        user.keyboard_shortcuts = bool(keyboard_shortcuts)
        fields.append("keyboard_shortcuts")
    if theme is not None:
        user.theme = Theme(theme)
        fields.append("theme")
    if accent is not None:
        user.accent = Accent(accent)
        fields.append("accent")
    if fields:
        user.save(update_fields=fields)
