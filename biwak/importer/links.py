"""Links to Basecamp recordings (specs/import-basecamp.md, "Rich text"):
shown in texts as links to a trampoline (``render_markdown()``), which
leads to what was imported from them, or to Basecamp (decided
2026-11-28). Nothing is looked up to show a text, so the order of the
imports doesn't matter, links pasted later work too, and a link doesn't
tell whether its target is in Biwak. The stored text keeps Basecamp's
address."""

import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.urls import reverse


# <account>/buckets/<project>/<path>/<id>, on Basecamp's old host and the
# app's; a comment's link ends in its anchor
LINK = re.compile(
    r"https://(?:3|app)\.basecamp\.com/\d+/buckets/\d+/"
    r"(todos|todolists|messages|documents|uploads|vaults|card_tables/cards"
    r"|card_tables|questions|inbox_forwards)/(\d+)[^\s)\]\"']*"
)
COMMENT = re.compile(r"#__recording_(\d+)$")
LINK_TYPES = {
    "todos": "Todo",
    "todolists": "Todolist",
    "messages": "Message",
    "documents": "Document",
    "uploads": "Upload",
    "vaults": "Vault",
    "card_tables/cards": "Kanban::Card",
    "card_tables": "Kanban::Board",
    "questions": "Question",
    "inbox_forwards": "Inbox::Forward",
}


def recording(href):
    """``(Basecamp type, ID, comment ID or None)`` of a link, or None"""
    found = LINK.fullmatch(href or "")
    if found is None:
        return None
    comment = COMMENT.search(href)
    return LINK_TYPES[found[1]], int(found[2]), int(comment[1]) if comment else None


def trampoline(href, *, absolute=False):
    """The trampoline's address for a link to a recording, or None: shown
    without looking anything up. ``absolute``: with ``BASE_URL`` (mails,
    the API)."""
    if recording(href) is None:
        return None
    url = f"{reverse('basecamp_link')}?{urlencode({'to': href})}"
    return settings.BASE_URL + url if absolute else url


def destination(user, href):
    """Where the trampoline leads ``user`` for a link to a recording: what
    was imported from it if they may see it (its comment's anchor when the
    comment was imported too), else Basecamp. Both look the same, nothing
    tells whether it was imported."""
    from biwak.importer.models import ImportedObject
    from biwak.items.models import Comment, Item

    bc_type, bc_id, comment = recording(href)
    keys = [(bc_type, bc_id)]
    if comment is not None:
        keys.append(("Comment", comment))
    query = Q()
    for key_type, key_id in keys:
        query |= Q(basecamp_type=key_type, basecamp_id=key_id)
    mapped = {
        (m.basecamp_type, m.basecamp_id): m.object_id
        for m in ImportedObject.objects.filter(
            query,
            content_type__in=[
                ContentType.objects.get_for_model(Item),
                ContentType.objects.get_for_model(Comment),
            ],
        )
    }
    pk = mapped.get((bc_type, bc_id))
    item = (
        Item.objects.visible_to(user).filter(pk=pk).first() if pk is not None else None
    )
    if item is None:
        return href
    url = item.get_absolute_url()
    if (
        comment is not None
        and (comment_pk := mapped.get(("Comment", comment)))
        and Comment.objects.filter(pk=comment_pk, item=item).exists()
    ):
        url += f"#comment-{comment_pk}"
    return url
