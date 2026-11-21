"""Plain text helpers"""

import re


_BREAKS = re.compile(r"\r\n?")


def line_breaks(text):
    r"""``\n`` for every line break: browsers send a textarea's as ``\r\n``,
    and the live editor (CodeMirror) counts a line break as one character
    where Yjs would count two (specs/collaboration.md)"""
    return _BREAKS.sub("\n", text) if text else text
