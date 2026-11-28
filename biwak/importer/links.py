"""Links to Basecamp recordings (specs/import-basecamp.md, "Links"): in texts
they lead to what was imported from them when the text is shown
(``render_markdown()``), so the order of the imports doesn't matter and
links pasted later work too (decided 2026-11-28). The stored text keeps
Basecamp's address."""

import re

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q


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


def biwak_urls(hrefs, *, absolute=False):
    """``{href: URL}`` for the links whose recordings were imported (a
    comment's anchor too, when it was imported), with one query for the
    mappings and one for what they point to. ``absolute``: with
    ``BASE_URL`` (mails, the API)."""
    from biwak.importer.models import ImportedObject
    from biwak.items.models import Comment, Item

    wanted = {href: found for href in set(hrefs) if (found := recording(href))}
    if not wanted:
        return {}
    keys = set()
    for bc_type, bc_id, comment in wanted.values():
        keys.add((bc_type, bc_id))
        if comment is not None:
            keys.add(("Comment", comment))
    query = Q()
    for bc_type, bc_id in keys:
        query |= Q(basecamp_type=bc_type, basecamp_id=bc_id)
    item_type = ContentType.objects.get_for_model(Item)
    comment_type = ContentType.objects.get_for_model(Comment)
    mapped = {
        (m.basecamp_type, m.basecamp_id): m.object_id
        for m in ImportedObject.objects.filter(
            query, content_type__in=[item_type, comment_type]
        )
    }
    items = {
        item.pk: item
        for item in Item.objects.filter(
            pk__in=[pk for key, pk in mapped.items() if key[0] != "Comment"]
        ).only("pk", "kind")
    }
    urls = {}
    for href, (bc_type, bc_id, comment) in wanted.items():
        item = items.get(mapped.get((bc_type, bc_id)))
        if item is None:
            continue
        url = item.get_absolute_url()
        if comment is not None and (pk := mapped.get(("Comment", comment))):
            url += f"#comment-{pk}"
        urls[href] = settings.BASE_URL + url if absolute else url
    return urls
