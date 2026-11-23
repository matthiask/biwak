"""Reading a forwarded mail (specs/forwarding.md)

Mail clients forward in a few shapes: the original below a separator
("---------- Forwarded message ---------" in Gmail, "Begin forwarded
message:" in Apple Mail, a line of underscores or "-----Original
Message-----" in Outlook, also in German), followed by a block of its
headers ("From:", "Date:" or "Sent:", "To:", "Cc:", "Subject:"; "Von:",
"Datum:" or "Gesendet:", "An:", "Betreff:"), or the original as an
attached message (``message/rfc822``). ``forward()`` reads the original's
subject, sender, date and recipients from either; when there's neither,
the forwarder's mail is taken as it is.

The text is the whole mail (the forwarder's lines above, the original
below, quotes and signatures kept) without the header block: HTML through
the paste converter (``biwak.richtext.htmlmarkdown``), else the plain
text. Inline images stay where they were: as placeholders
(``File.placeholder``) that ``biwak.forwarding.operations`` replaces
with the stored files.
"""

import dataclasses
import datetime as dt
import re
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup
from django.utils import timezone

from biwak.inbound.providers import MIN_INLINE_SIZE
from biwak.inbound.strip import _Text
from biwak.richtext.htmlmarkdown import from_clipboard


@dataclasses.dataclass
class File:
    name: str
    content_type: str
    content: bytes
    content_id: str = ""
    # In the text where the mail showed it inline
    placeholder: str = ""


@dataclasses.dataclass
class Forward:
    subject: str
    sender_name: str
    sender_email: str
    sent_on: dt.date | None
    to: str
    cc: str
    text: str
    files: list


# The line starting the forwarded mail
_SEPARATOR = re.compile(
    r"^\s*(-{2,}\s*(Forwarded message|Weitergeleitete Nachricht|Original Message"
    r"|Ursprüngliche Nachricht|Originalnachricht|Forwarded Message)\s*-{2,}"
    r"|_{10,}|Begin forwarded message:"
    r"|Anfang der weitergeleiteten (E-Mail|Nachricht):)\s*$",
    re.IGNORECASE,
)
# The original's headers, as the clients write them (English and German)
_FIELDS = {
    "from": r"From|Von",
    "date": r"Date|Sent|Datum|Gesendet",
    "to": r"To|An",
    "cc": r"Cc|Kopie",
    "subject": r"Subject|Betreff",
    "reply_to": r"Reply-To|Antwort an",
}
_FIELD = re.compile(
    r"^\s*(?P<name>" + "|".join(_FIELDS.values()) + r")\s?:\s*(?P<value>.*)$",
    re.IGNORECASE,
)
_FIELD_NAMES = {
    label.lower(): key for key, labels in _FIELDS.items() for label in labels.split("|")
}
_APPLE_START = re.compile(
    r"(Begin forwarded message|Anfang der weitergeleiteten (E-Mail|Nachricht))",
    re.IGNORECASE,
)
# A horizontal rule (Outlook's above the header block)
_RULE = re.compile(r"^\s*([-_*]\s*){3,}$")
# What the Markdown of the HTML adds around a header line
_MARKUP = re.compile(r"[*_\\]")
_QUOTE = re.compile(r"^(\s*>)+\s?")
# Prefixes of forwarded subjects (English, German, French)
_FORWARD_PREFIX = re.compile(r"^\s*((fwd?|wg|tr|fw)\s*:\s*)+", re.IGNORECASE)


def _plain(line):
    """The line without Markdown's emphasis and escapes and quote marks"""
    return _MARKUP.sub("", _QUOTE.sub("", line)).strip()


def _field(line):
    """``(key, value)`` if the line is one of the original's headers"""
    match = _FIELD.match(_plain(line))
    if not match:
        return None
    return _FIELD_NAMES[match["name"].lower()], match["value"].strip()


def _block(lines, start):
    """The header block starting at ``start``: its fields and the index
    after it. Blank lines between fields are allowed (HTML makes them),
    a field seen before or any other line ends it."""
    fields = {}
    index = start
    while index < len(lines):
        if not lines[index].strip() or not _plain(lines[index]):
            following = next(
                (i for i in range(index, len(lines)) if _plain(lines[i])), None
            )
            found = _field(lines[following]) if following is not None else None
            if found is None or found[0] in fields:
                break
            index = following
            continue
        found = _field(lines[index])
        if found is None or found[0] in fields:
            break
        fields[found[0]] = found[1]
        index += 1
    if "from" not in fields or not ({"date", "subject"} & fields.keys()):
        return None, start
    return fields, index


def find_header(lines):
    """``(start, end, fields)`` of the first forwarded mail's header block
    in the lines (``start`` at its separator, if any), or None"""
    for index, line in enumerate(lines):
        plain = _plain(line)
        if _SEPARATOR.match(plain):
            following = next(
                (i for i in range(index + 1, len(lines)) if _plain(lines[i])), None
            )
            if following is not None:
                fields, end = _block(lines, following)
                if fields:
                    return index, end, fields
        elif (found := _field(line)) and found[0] == "from":
            fields, end = _block(lines, index)
            if fields:
                return index, end, fields
    return None


# Dates ------------------------------------------------------------------------

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            "january jan januar jän",
            "february feb februar",
            "march mar märz mär mrz maerz",
            "april apr",
            "may mai",
            "june jun juni",
            "july jul juli",
            "august aug",
            "september sep sept",
            "october oct oktober okt",
            "november nov",
            "december dec dezember dez",
        ],
        start=1,
    )
    for name in names.split()
}
_DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})\.?\s+([a-zäö]+)\.?,?\s+(\d{4})\b")
_MONTH_DAY_YEAR = re.compile(r"\b([a-zäö]+)\.?\s+(\d{1,2}),?\s+(\d{4})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
# "Fri, 20 Nov 2026 16:42:10 +0100", the Date header's format
_RFC5322 = re.compile(r"^([A-Za-z]{3},\s*)?\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _date_or_none(year, month, day):
    try:
        return dt.date(int(year), int(month), int(day))
    except ValueError, TypeError:
        return None


def parse_date(value):
    """The date of a header as clients write it ("Fri, Nov 20, 2026 at 4:42
    PM", "Freitag, 20. November 2026 16:42", "20 November 2026 at
    16:42:11 CET", "20.11.2026", RFC 5322), the day as written; None when
    it can't be read (11/12/2026 could be either)"""
    value = " ".join((value or "").split())
    if not value:
        return None
    parsed = None
    if _RFC5322.match(value):
        try:
            parsed = parsedate_to_datetime(value)
        except TypeError, ValueError, IndexError:
            parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            return parsed.date()
        return timezone.localtime(parsed).date()
    lower = value.lower()
    for match in _DAY_MONTH_YEAR.finditer(lower):
        if month := _MONTHS.get(match[2]):
            return _date_or_none(match[3], month, match[1])
    for match in _MONTH_DAY_YEAR.finditer(lower):
        if month := _MONTHS.get(match[1]):
            return _date_or_none(match[3], month, match[2])
    if match := _NUMERIC.search(lower):
        return _date_or_none(match[3], match[2], match[1])
    if match := _ISO.search(lower):
        return _date_or_none(match[1], match[2], match[3])
    return None


# Addresses --------------------------------------------------------------------


def _sender(value):
    """``(name, address)`` of a "From:" line: "Ada <ada@example.org>",
    Outlook's "Ada [mailto:ada@example.org]", a bare address or a name"""
    value = re.sub(r"\[mailto:([^\]]+)\]", r"<\1>", value or "").strip()
    name, address = parseaddr(value)
    if "@" not in address:
        return value.strip(" \"'"), ""
    return name.strip(" \"'"), address.lower()


def _recipients(value):
    """The recipients as written, one line: "Ada <ada@example.org>, Bea
    <bea@example.org>" (Outlook separates them with ";")"""
    value = re.sub(r"\[mailto:([^\]]+)\]", r"<\1>", value or "")
    people = []
    for part in value.split(r";"):
        if "@" in part:
            for name, address in getaddresses([part]):
                if "@" not in address:
                    continue
                people.append(f"{name} <{address}>" if name else address)
        elif part.strip():
            people.append(part.strip())
    return ", ".join(people)


# Parts ------------------------------------------------------------------------


def _text_of(part):
    try:
        return part.get_content()
    except LookupError, UnicodeError, AssertionError, KeyError:
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _files(message, *, skip=()):
    """The parts with a file name or a Content-ID (inline images), except
    the bodies ``skip`` and small inline parts (signature logos, like
    replies: ``MIN_INLINE_SIZE``); not into attached messages"""
    files = []
    for part in _walk(message):
        if part.is_multipart() or any(part is body for body in skip):
            continue
        if part.get_content_type() == "message/rfc822":
            continue
        content_id = str(part["Content-ID"] or "").strip().strip("<>")
        disposition = part.get_content_disposition()
        # Gmail gives attachments a Content-ID too
        inline = disposition == "inline" or (
            disposition != "attachment" and bool(content_id)
        )
        name = part.get_filename()
        if not name and not (content_id and part.get_content_maintype() == "image"):
            continue
        content = part.get_payload(decode=True) or b""
        if inline and len(content) < MIN_INLINE_SIZE:
            continue
        if not name:
            subtype = part.get_content_subtype()
            name = f"image.{'jpg' if subtype == 'jpeg' else subtype}"
        files.append(
            File(
                name=name,
                content_type=part.get_content_type(),
                content=content,
                content_id=content_id,
            )
        )
    return files


def _walk(message):
    """The parts, not descending into attached messages"""
    yield message
    if message.is_multipart():
        for part in message.iter_parts():
            if part.get_content_type() == "message/rfc822":
                yield part
                continue
            yield from _walk(part)


def _bodies(message):
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    return plain, html


def _attached(message):
    """The first attached message (forwarding as attachment)"""
    for part in _walk(message):
        if part is not message and part.get_content_type() == "message/rfc822":
            content = part.get_content()
            if hasattr(content, "get_body"):
                return content
    return None


# The text ---------------------------------------------------------------------


def _placeholders(files):
    for index, file in enumerate(files):
        file.placeholder = f"BIWAKFILE{index}X"
    return {file.content_id: file.placeholder for file in files if file.content_id}


def _html_markdown(html, by_cid):
    """Markdown of the HTML; inline images as placeholders. Apple Mail
    puts the forwarded mail into a quote: that one isn't a quote."""
    soup = BeautifulSoup(html, "html.parser")
    for quote in soup.find_all("blockquote"):
        if _APPLE_START.match(quote.get_text(" ", strip=True)):
            quote.unwrap()
    for image in soup.find_all("img"):
        src = (image.get("src") or "").strip()
        if src.lower().startswith("cid:") and (placeholder := by_cid.get(src[4:])):
            image.replace_with(f" {placeholder} ")
    return from_clipboard(str(soup))


def _html_text(html):
    """The HTML as plain lines, for reading the header block"""
    parser = _Text()
    parser.feed(html or "")
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    return [line.strip() for line in text.split("\n")]


def _cid_placeholders(text, by_cid):
    """Outlook's plain text shows inline images as "[cid:…]" """

    def replace(match):
        return by_cid.get(match[1].strip(), "")

    return re.sub(r"\[cid:([^\]]+)\]", replace, text)


def _join(*parts):
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _lines(text):
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _unquote(lines):
    """Lines all quoted (a forward inside a quote) without their marks"""
    if all(not line.strip() or _QUOTE.match(line) for line in lines):
        return [_QUOTE.sub("", line) for line in lines]
    return lines


def _without_header(lines, found):
    start, end, _fields = found
    note = lines[:start]
    while note and (not note[-1].strip() or _RULE.match(note[-1])):
        note.pop()
    return _join("\n".join(note), "\n".join(_unquote(lines[end:])))


def _subject(value):
    return " ".join((value or "").split())[:500]


def forward(mail):
    """The ``Forward`` of an ``InboundMail`` sent to the inbox"""
    message = mail.headers
    attached = _attached(message)
    if attached is not None:
        return _from_attached(mail, message, attached)

    plain_part, html_part = _bodies(message)
    plain = _text_of(plain_part) if plain_part is not None else ""
    html = _text_of(html_part) if html_part is not None else ""
    files = _files(message, skip=(plain_part, html_part))
    by_cid = _placeholders(files)

    plain_lines = _lines(_cid_placeholders(plain, by_cid))
    header_lines = plain_lines if plain.strip() else _html_text(html)
    found = find_header(header_lines)

    if html.strip():
        markdown_lines = _lines(_html_markdown(html, by_cid))
        found_markdown = find_header(markdown_lines) if found else None
        if found_markdown:
            text = _without_header(markdown_lines, found_markdown)
        elif found and plain.strip():
            text = _without_header(plain_lines, found)
        else:
            text = "\n".join(markdown_lines).strip()
    elif found:
        text = _without_header(plain_lines, found)
    else:
        text = "\n".join(plain_lines).strip()

    if found:
        fields = found[2]
        name, address = _sender(fields.get("from", ""))
        return Forward(
            subject=_subject(fields.get("subject", "")),
            sender_name=name,
            sender_email=address,
            sent_on=parse_date(fields.get("date", "")),
            to=_recipients(fields.get("to", "")),
            cc=_recipients(fields.get("cc", "")),
            text=text,
            files=files,
        )
    # Not a forward we can read: the forwarder's mail as it is
    name, address = _sender(str(message.get("From", "")))
    return Forward(
        subject=_subject(_FORWARD_PREFIX.sub("", mail.subject)),
        sender_name=name,
        sender_email=address,
        sent_on=parse_date(str(message.get("Date", ""))),
        to="",
        cc="",
        text=text,
        files=files,
    )


def _from_attached(mail, message, attached):
    """Forwarded as an attachment: the original's own headers, the
    forwarder's lines above its text, the files of both"""
    plain_part, html_part = _bodies(message)
    note_files = _files(message, skip=(plain_part, html_part))
    note = _text_of(plain_part) if plain_part is not None else ""
    if not note.strip() and html_part is not None:
        note = from_clipboard(_text_of(html_part))

    plain_part, html_part = _bodies(attached)
    files = _files(attached, skip=(plain_part, html_part))
    by_cid = _placeholders([*files, *note_files])
    if html_part is not None and _text_of(html_part).strip():
        body = _html_markdown(_text_of(html_part), by_cid)
    elif plain_part is not None:
        body = _cid_placeholders(_text_of(plain_part), by_cid)
    else:
        body = ""
    name, address = _sender(str(attached.get("From", "")))
    return Forward(
        subject=_subject(str(attached.get("Subject", ""))),
        sender_name=name,
        sender_email=address,
        sent_on=parse_date(str(attached.get("Date", ""))),
        to=_recipients(str(attached.get("To", ""))),
        cc=_recipients(str(attached.get("Cc", ""))),
        text=_join(note, body),
        files=[*files, *note_files],
    )
