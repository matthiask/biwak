"""Full-text search (specs/search.md): PostgreSQL's ``simple`` configuration
(no stemming, the same for every language) with prefix matching, over the
titles of items, the text of every kind (in its detail model) and the
comments.

The texts are indexed by expression indexes (``migrations/0001_indexes.py``),
so nothing has to be kept up to date. The search finds item IDs, which then
go through ``Item.objects.visible_to()`` like every other query for items:
comments are found through their item, and a client never finds what they
can't see.
"""

import html

from django.db import connection
from django.db.models import BooleanField, F, Func, Q, Value
from django.utils.safestring import mark_safe

from biwak.checkins.models import Answer
from biwak.items.glance import with_checklist
from biwak.items.models import (
    Comment,
    Doc,
    Item,
    Kind,
    Message,
    Status,
    Todo,
    TodoList,
    Upload,
)


PAGE_SIZE = 50
EXCERPT_CHARS = 200
# Words past this many are ignored
MAX_TERMS = 10
MAX_QUERY_CHARS = 200

# Where each kind keeps its text; the other kinds only have a title
TEXTS = {
    Kind.LIST: (TodoList, "description"),
    Kind.TODO: (Todo, "notes"),
    Kind.MESSAGE: (Message, "content"),
    Kind.DOC: (Doc, "content"),
    Kind.FILE: (Upload, "description"),
    Kind.ANSWER: (Answer, "content"),
}

# Around the matched words in ``ts_headline``; private use characters, which
# are taken out of the texts first so that they can't fake a match
START, STOP = "", ""


def vector(column):
    """The expression of the indexes"""
    return Func(Value("simple"), F(column), function="to_tsvector")


class Matches(Func):
    template = "(%(expressions)s)"
    arg_joiner = " @@ "
    output_field = BooleanField()


def prefixes(terms):
    """One ``tsquery`` as text per word, each matching as the start of a
    word; empty if there are no words"""
    # Quoted lexemes, so that nothing the person types is syntax
    return [
        "'" + lexeme.replace("\\", "\\\\").replace("'", "''") + "':*"
        for lexeme in _lexemes(terms)
    ]


def tsquery(text):
    return Func(Value("simple"), Value(text), function="to_tsquery")


def _lexemes(text):
    """The words as the database indexes them (so that "1.5" or an email
    address match what is stored)"""
    with connection.cursor() as cursor:
        # In the order typed (a tsvector is sorted, its positions aren't)
        cursor.execute(
            "SELECT lexeme FROM unnest(to_tsvector('simple', %s)) "
            "ORDER BY positions[1] LIMIT %s",
            [text[:MAX_QUERY_CHARS], MAX_TERMS],
        )
        return [row[0] for row in cursor.fetchall()]


def is_archived(item):
    """In an archived project, or an archived list or in one"""
    if item.project.archived_at is not None:
        return True
    lists = [item, item.parent] if item.parent_id else [item]
    return any(i.kind == Kind.LIST and i.status == Status.ARCHIVED for i in lists)


def matching_ids(prefix):
    """A query for the IDs of the items with the word in their title, in
    their text or in one of their comments. Every part uses its index."""
    query = tsquery(prefix)
    parts = [
        Item.objects.filter(Matches(vector("title"), query)).values("pk"),
        Comment.objects.filter(Matches(vector("content"), query)).values("item_id"),
    ]
    parts += [
        model.objects.filter(Matches(vector(column), query)).values("pk")
        for model, column in TEXTS.values()
    ]
    return parts[0].union(*parts[1:], all=True)


def search(
    user,
    terms,
    *,
    project=None,
    kind=None,
    mine=False,
    archived=False,
):
    """The items the person can see with all the words, newest first.
    ``project`` and ``kind`` narrow it down, ``mine`` keeps what the person
    created and the to-dos assigned to them, ``archived`` brings in the archived
    projects and lists with their contents, which are left out otherwise."""
    words = prefixes(terms)
    if not words:
        return Item.objects.none()
    items = with_checklist(Item.objects.visible_to(user)).select_related(
        "project", "creator", "answer", "parent"
    )
    # Every word anywhere in the item: the title can have one, the text
    # another, a comment a third
    for word in words:
        items = items.filter(pk__in=matching_ids(word))
    if project is not None:
        items = items.filter(project=project)
    if kind:
        items = items.filter(kind=kind)
    if mine:
        items = items.filter(Q(creator=user) | Q(todo__assignees=user)).distinct()
    if not archived:
        items = items.filter(project__archived_at__isnull=True).exclude(
            Q(kind=Kind.LIST, status=Status.ARCHIVED)
            | Q(parent__kind=Kind.LIST, parent__status=Status.ARCHIVED)
        )
    return items.order_by("-updated_at", "-pk")


# Excerpts ---------------------------------------------------------------------


class Hit:
    """What the person sees of a result: the title and the excerpt with the
    matched words marked (``<mark>``), escaped HTML; ``text`` is the excerpt
    without markup; ``in_comment`` if it's from a comment"""

    def __init__(self, title="", text="", excerpt_html="", *, in_comment=False):
        self.title = title
        self.text = text
        self.excerpt_html = excerpt_html
        self.in_comment = in_comment


def clip(marked, chars=EXCERPT_CHARS):
    """The text with markers, whitespace collapsed, at most ``chars``
    characters (markers don't count), cut with an ellipsis; no marker is
    left open"""
    marked = " ".join(marked.split())
    out, count, open_ = [], 0, False
    for character in marked:
        if character == START:
            open_ = True
        elif character == STOP:
            open_ = False
        else:
            if count == chars:
                out.append(STOP * open_ + "…")
                return "".join(out)
            count += 1
        out.append(character)
    return "".join(out)


def to_html(marked):
    """Escaped HTML, the matches in ``<mark>``: the only markup there is"""
    return mark_safe(
        html.escape(marked).replace(START, "<mark>").replace(STOP, "</mark>")
    )


def to_text(marked):
    return marked.replace(START, "").replace(STOP, "")


def headlines(texts, text):
    """``ts_headline`` of every text with the query, in one query. Characters
    in the texts that are markers are taken out first."""
    clean = [text.replace(START, "").replace(STOP, "") for text in texts]
    options = f"StartSel={START}, StopSel={STOP}, MaxWords=35, MinWords=15"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ts_headline('simple', t, to_tsquery('simple', %s), %s)"
            " FROM unnest(%s::text[]) WITH ORDINALITY AS u(t, n) ORDER BY n",
            [text, options, clean],
        )
        return [row[0] for row in cursor.fetchall()]


def as_text(text):
    """Markdown as plain text, the whole of it"""
    from biwak.templatetags.biwak import excerpt

    return excerpt(text, chars=len(text or "") + 1) if text else ""


def hits(items, terms):
    """``{item ID: Hit}`` for the items of a page of results: the title and
    an excerpt of the text, or of the first comment if only a comment has
    the words (none if only the title has them). Two queries per kind at
    most, the items are the person's, so nothing else is checked here."""
    from biwak.activity.mentions import plain

    words = prefixes(terms)
    items = list(items)
    if not words or not items:
        return {}
    # Each text marks the words it has
    text = " | ".join(words)
    query = tsquery(text)
    texts = {}
    for kind, (model, column) in TEXTS.items():
        ids = [item.pk for item in items if item.kind == kind]
        if ids:
            texts |= dict(model.objects.filter(pk__in=ids).values_list("pk", column))
    ids = [item.pk for item in items]
    comments = {}
    for item_id, content in (
        Comment.objects
        .filter(item__in=ids)
        .filter(Matches(vector("content"), query))
        .order_by("-created_at", "-pk")
        .values_list("item_id", "content")
    ):
        # The first match in time
        comments[item_id] = content
    # Titles first, then the texts, then the comments: one query
    sources = [plain(item.title, item) for item in items]
    # Texts as plain text, like the excerpts elsewhere (specs/glance.md):
    # no Markdown, mentions as written (no query per result)
    sources += [as_text(texts.get(item.pk, "")) for item in items]
    sources += [as_text(comments.get(item.pk, "")) for item in items]
    marked = headlines(sources, text)
    count = len(items)
    result = {}
    for index, item in enumerate(items):
        title, text, comment = (marked[index + count * n] for n in range(3))
        if START in text:
            excerpt, in_comment = text, False
        elif START in comment:
            excerpt, in_comment = comment, True
        else:
            excerpt, in_comment = "", False
        excerpt = clip(excerpt)
        result[item.pk] = Hit(
            # Only if it wasn't cut
            title=to_html(title)
            if START in title and to_text(title) == " ".join(sources[index].split())
            else "",
            text=to_text(excerpt),
            excerpt_html=to_html(excerpt),
            in_comment=in_comment,
        )
    return result
