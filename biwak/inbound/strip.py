"""What somebody wrote in a reply, without the quoted mail and the
signature (specs/notifications.md, stage 2)

Mail clients quote differently: Gmail and Apple Mail with a line "On …
wrote:" ("Am … schrieb …:"), Outlook with a block of headers ("From:",
"Sent:"; "Von:", "Gesendet:") or "-----Original Message-----", phones add
"Sent from my iPhone". We cut at the first of these, then
``email-reply-parser`` removes what's left (``>`` quotes, signatures).
Mails without a plain text part are turned into text first.
"""

import re
from html.parser import HTMLParser

from email_reply_parser import EmailReplyParser


# A line starting a quote header, and how it ends (the header may be
# wrapped over up to three lines)
_QUOTE_HEADERS = [
    (re.compile(r"^(>\s?)*On\s"), re.compile(r"wrote:\s*$")),
    (re.compile(r"^(>\s?)*Am\s"), re.compile(r"schrieb.*:\s*$")),
]
_SEPARATORS = re.compile(
    r"^\s*(-{2,}\s*(Original Message|Ursprüngliche Nachricht|Originalnachricht)"
    r"\s*-{2,}|_{10,}|-- ?|Begin forwarded message:|Anfang der weitergeleiteten"
    r" (E-Mail|Nachricht):|-{5,}\s*(Forwarded message|Weitergeleitete Nachricht)"
    r"\s*-{5,})\s*$",
    re.IGNORECASE,
)
# Outlook's block of the quoted mail's headers: "From:" followed by "Sent:"
_OUTLOOK_FROM = re.compile(r"^\s*\*?(From|Von)\s?:\*?\s", re.IGNORECASE)
_OUTLOOK_NEXT = re.compile(
    r"^\s*\*?(Sent|Date|To|Gesendet|Datum|An)\s?:\*?\s", re.IGNORECASE
)
# Phones' signatures, the last lines of a reply
_PHONE_SIGNATURE = re.compile(
    r"^\s*(Sent from|Sent with|Sent via|Get Outlook for|Gesendet von|Gesendet mit"
    r"|Von meinem|Von Outlook|Holen Sie sich Outlook)\b.{0,60}$",
    re.IGNORECASE,
)


def _cut(lines):
    """Lines up to the first quote header or separator"""
    for index, line in enumerate(lines):
        if _SEPARATORS.match(line):
            return lines[:index]
        for start, end in _QUOTE_HEADERS:
            if start.match(line) and any(
                end.search(" ".join(lines[index : index + count]))
                for count in range(1, 4)
            ):
                return lines[:index]
        if _OUTLOOK_FROM.match(line) and any(
            _OUTLOOK_NEXT.match(following) for following in lines[index + 1 : index + 4]
        ):
            return lines[:index]
    return lines


def strip_text(text):
    """The reply in a plain text body"""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = _cut(lines)
    while lines and (not lines[-1].strip() or _PHONE_SIGNATURE.match(lines[-1])):
        lines.pop()
    return EmailReplyParser.parse_reply("\n".join(lines)).strip()


# Where the quoted mail starts in clients' HTML
_HTML_QUOTE = re.compile(
    r"<blockquote|<div[^>]*class=\"?[^\">]*(gmail_quote|moz-cite-prefix)"
    r"|<[^>]*id=\"?(divRplyFwdMsg|appendonsend|mail-editor-reference-message-container)",
    re.IGNORECASE,
)
_BLOCKS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script", "head", "title"}:
            self.skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"style", "script", "head", "title"}:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCKS - {"br"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(" ".join(data.split("\n")))


def html_to_text(html):
    match = _HTML_QUOTE.search(html or "")
    if match:
        html = html[: match.start()]
    parser = _Text()
    parser.feed(html or "")
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = [line.strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def reply_text(mail):
    """What the person wrote: from the plain text part, or from the HTML
    when there's none"""
    if mail.text.strip():
        return strip_text(mail.text)
    return strip_text(html_to_text(mail.html))
