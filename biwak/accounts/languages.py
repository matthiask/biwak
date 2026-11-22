"""The language a person reads Biwak in (specs/languages.md): pages follow
their choice, else the browser (``LocaleMiddleware``); mails follow their
choice, else the language of their invitation, else English"""

from django.conf import settings
from django.utils import translation


def supported(language):
    """``language`` as one of ``LANGUAGES`` (``de-ch`` → ``de``), or the
    default"""
    try:
        return translation.get_supported_language_variant(language or "")
    except LookupError:
        return settings.LANGUAGE_CODE


def language_for(user):
    """The language of mails to ``user``: ``translation.override(
    language_for(user))`` around building them, subject included"""
    return user.language or user.invitation_language or settings.LANGUAGE_CODE


# Each in its own language (specs/languages.md, "Choosing"); not marked for
# translation on purpose
CHOICES = [("", None), ("de", "Deutsch"), ("en", "English")]


def choices():
    """The settings' choices: Automatic in the active language, the
    languages in their own"""
    from django.utils.translation import gettext

    return [
        (value, label or gettext("Automatic (the browser's language)"))
        for value, label in CHOICES
    ]
