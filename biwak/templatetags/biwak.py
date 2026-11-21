import datetime as dt
import html
import re

from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.html import escape, format_html, format_html_join, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.tasklists import tasklists_plugin

from biwak import forms
from biwak.organizations.names import display_name


register = template.Library()

# Texts are stored as Markdown (specs/core.md): no HTML, links clickable
_markdown = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
_markdown.enable(["linkify", "strikethrough", "table"])
_markdown.use(tasklists_plugin)

_PERSON = re.compile(r"person:(\d+)")


def _mentions(state):
    """Mentions (``[@Ada](person:12)``, biwak/activity/mentions.py) are
    links to ``person:``: shown with the current short name of people who
    can see the item (``env["people"]``), the full name as ``title``, as
    plain text otherwise"""
    people = state.env.get("people") or {}
    reader = state.env.get("reader")
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        children, result = block.children, []
        index = 0
        while index < len(children):
            token = children[index]
            match = token.type == "link_open" and _PERSON.fullmatch(
                token.attrGet("href") or ""
            )
            if not match:
                result.append(token)
                index += 1
                continue
            end = index + 1
            while children[end].type != "link_close":
                end += 1
            label = "".join(t.content for t in children[index + 1 : end])
            user = people.get(int(match[1]))
            mention = Token("html_inline", "", 0)
            if user:
                text = (
                    f'title="{escape(str(user))}">@{escape(display_name(user, reader))}'
                )
                # A link to the page where the person's page is open to the
                # reader (visible_people() are those they may know); not in
                # mails and the API, whose texts leave the site
                if state.env.get("links"):
                    url = reverse("person", args=[user.pk])
                    mention.content = (
                        f'<a class="wb-mention wb-person-link" href="{url}" {text}</a>'
                    )
                else:
                    mention.content = f'<span class="wb-mention" {text}</span>'
            else:
                mention.content = escape(f"@{label.removeprefix('@')}")
            result.append(mention)
            index = end + 1
        block.children = result


_markdown.core.ruler.push("mentions", _mentions)


def _checkboxes(state):
    """Checkboxes of task lists (``biwak/checklists.py``): numbered, in a
    mail a glyph, disabled unless the page lets the viewer tick them
    (``env["tickable"]``)"""
    from biwak.checklists import is_checkbox

    number = 0
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        box = block.children[0]
        if not is_checkbox(box):
            continue
        checked = "checked" in box.content
        if state.env.get("glyphs"):
            box.content = "\u2611 " if checked else "\u2610 "
        else:
            box.content = (
                f'<input class="task-list-item-checkbox" type="checkbox" '
                f'data-index="{number}"'
                f"{' checked' if checked else ''}"
                f"{'' if state.env.get('tickable') else ' disabled'}>"
            )
        number += 1


_markdown.core.ruler.push("checkboxes", _checkboxes)


@register.filter
def markdown(text, item=None):
    """Markdown as HTML; mentions with current names when the item they're
    in is given (``{{ comment.content|markdown:item }}``)"""
    return render_markdown(text, item)


@register.simple_tag(takes_context=True)
def checklist_markdown(context, text, item, comment=None):
    """Like ``|markdown``, and for people who may change the text its
    checkboxes can be ticked in place (``frontend/checklist.js`` posts to
    ``item_tick``); the others see them disabled. ``comment``: the text is
    that comment's."""
    from biwak.checklists import text_hash
    from biwak.items import operations as ops

    user = context["request"].user
    if comment is not None:
        allowed = not user.is_client or comment.author_id == user.pk
    else:
        allowed = ops.can_tick(user, item)
    rendered = render_markdown(text, item, tickable=allowed)
    if not allowed or 'data-index="' not in rendered:
        return rendered
    return format_html(
        '<div class="wb-checklist" data-tick-url="{}" data-version="{}"{}>{}</div>',
        reverse("item_tick", args=[item.pk]),
        text_hash(text),
        format_html(' data-comment="{}"', comment.pk) if comment is not None else "",
        rendered,
    )


@register.filter
def mail_markdown(text, item=None):
    """For mails: like ``markdown``, attachment URLs with BASE_URL and
    checkboxes as ☐ and ☑"""
    return render_markdown(text, item, absolute=True, glyphs=True)


def render_markdown(
    text,
    item=None,
    *,
    absolute=False,
    attachment_urls=True,
    tickable=False,
    glyphs=False,
):
    """``absolute`` for the API and mails: attachment URLs with BASE_URL.
    ``attachment_urls=False`` skips looking them up (excerpts don't show
    them). ``tickable`` leaves task list checkboxes enabled, ``glyphs``
    turns them into ☐ and ☑ (mails)."""
    from biwak.activity.mentions import mentioned_ids, reader, visible_people

    text = str(text or "")
    people = visible_people(item, mentioned_ids(text)) if item is not None else {}
    env = {
        "people": people,
        "reader": reader(),
        "links": not absolute and not glyphs,
        "tickable": tickable,
        "glyphs": glyphs,
    }
    tokens = _markdown.parse(text, env)
    if attachment_urls:
        _attachment_urls(tokens, item, absolute=absolute)
    return mark_safe(_markdown.renderer.render(tokens, _markdown.options, env))


def _attachment_reference(token):
    """``(attribute, key)`` of a link or image to ``attachment:KEY``"""
    from biwak.files.models import REFERENCE

    attr = {"link_open": "href", "image": "src"}.get(token.type)
    if attr and (match := REFERENCE.fullmatch(token.attrGet(attr) or "")):
        return attr, match[1]
    return None


def _attachment_urls(tokens, item, *, absolute):
    """``attachment:KEY`` (specs/files.md) becomes the download URL; images
    show inline, scaled to the text's width. Whoever reads the text may
    not see the attachment: the download checks. Only the item's own
    attachments: a reference to another item's (or a missing one) becomes
    a plain "attachment", without its name, which its URL contains too."""
    from biwak.files.models import Attachment

    blocks = [token for token in tokens if token.children]
    keys = {
        reference[1]
        for block in blocks
        for child in block.children
        if (reference := _attachment_reference(child))
    }
    if not keys:
        return
    found = {}
    if item is not None and item.pk is not None:
        found = {a.key: a for a in Attachment.objects.filter(key__in=keys, item=item)}
    for block in blocks:
        result = []
        children = block.children
        index = 0
        while index < len(children):
            child = children[index]
            index += 1
            if (reference := _attachment_reference(child)) is None:
                result.append(child)
                continue
            attr, key = reference
            if attachment := found.get(key):
                url = attachment.get_absolute_url()
                child.attrSet(attr, settings.BASE_URL + url if absolute else url)
                if attr == "src":
                    child.attrJoin("class", "wb-attachment-image")
                    child.attrSet("loading", "lazy")
                result.append(child)
                continue
            text = Token("text", "", 0)
            text.content = gettext("attachment")
            result.append(text)
            if attr == "href":
                # Leave out the link's text up to its end
                while children[index].type != "link_close":
                    index += 1
                index += 1
        block.children = result


@register.filter
def item_title(item):
    """An item's title with the mentions as ``@`` and current names"""
    from biwak.activity.mentions import plain as plain_mentions

    return plain_mentions(item.title, item)


@register.filter
def title_text(title):
    """A stored title (e.g. an event's) with the mentions as ``@`` and their
    labels, without looking anybody up"""
    from biwak.activity.mentions import plain as plain_mentions

    return plain_mentions(title)


@register.filter
def plain(text):
    """The text without Markdown, e.g. for snippets"""
    return " ".join(strip_tags(markdown(text)).split())


@register.filter
def excerpt(text, chars=200, item=None):
    """The text as plain text of at most about ``chars`` characters
    (specs/glance.md): Markdown rendered like ``|markdown``, tags
    stripped, whitespace collapsed, cut at a word boundary, "…" added.
    Images and attachments become nothing, links their text. Plain
    ``str``: templates escape it. Mentions show the current name of people
    who see ``item`` (from Python only: a filter takes one argument), the
    label as written without it."""
    chars = int(chars)
    rendered = (
        str(render_markdown(text, item, attachment_urls=False))
        .replace("</p>", " ")
        .replace("<br>", " ")
    )
    # strip_tags leaves entities; unescape the text (it is escaped again on
    # output) so that "&amp;" doesn't show
    result = " ".join(html.unescape(strip_tags(rendered)).split())
    if len(result) <= chars:
        return result
    cut = result[:chars]
    if not result[chars].isspace():
        # In the middle of a word: back to the last space, if there is one
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip() + "…"


def _feed_people(request):
    from biwak.activity.feed import people_visible_to

    if not hasattr(request, "_feed_people"):
        request._feed_people = set(
            people_visible_to(request.user).values_list("pk", flat=True)
        )
    return request._feed_people


@register.simple_tag(takes_context=True)
def can_open_feed(context, person):
    """Whether the viewer gets the person's feed (else a 404, see
    ``people_visible_to``); looked up once per request"""
    return person.pk in _feed_people(context["request"])


def _viewer(context):
    """Who looks at the page: the request's user, else whoever reads now
    (a template rendered for a mail)"""
    from biwak.activity.mentions import reader

    request = context.get("request")
    return request.user if request is not None else reader()


@register.simple_tag(takes_context=True)
def short_name(context, person):
    """The person's short name as the viewer sees it (``display_name()``:
    "Moritz F." when somebody else they may know is a Moritz too). The one
    way templates print a short name."""
    return display_name(person, _viewer(context))


@register.simple_tag(takes_context=True)
def person_link(context, person, *, name=None, css=""):
    """A person's name, linked to their feed (specs/feed.md) when the
    viewer would not get a 404 there, else plain text"""
    label = name if name is not None else short_name(context, person)
    if can_open_feed(context, person):
        return format_html(
            '<a href="{}" class="{}">{}</a>',
            reverse("person_feed", args=[person.pk]),
            css,
            label,
        )
    return label


@register.simple_tag(takes_context=True)
def person_page(context, person, *, size="sm", name=None):
    """The mark and the short name (or ``name``) of a person, linked to
    their page (``/people/<id>/``) when the viewer may open it
    (``known_people()``, as the page itself), else plain text; a quiet link
    (no underline until hover). The one place lists of people use."""
    label = name if name is not None else short_name(context, person)
    inner = format_html("{} {}", avatar(context, person, size), label)
    request = context.get("request")
    known = _known_people(request) if request is not None else set()
    if known is None or person.pk in known:
        return format_html(
            '<a href="{}" class="wb-person-link">{}</a>',
            reverse("person", args=[person.pk]),
            inner,
        )
    return inner


def _known_people(request):
    """None if the viewer may know everybody, else the set of the people
    they may know (``biwak.organizations.people.known_people()``); looked
    up once per request"""
    from biwak.organizations.people import known_people
    from biwak.projects.models import knows_everybody

    if not hasattr(request, "_known_people"):
        request._known_people = (
            None
            if knows_everybody(request.user)
            else set(known_people(request.user).values_list("pk", flat=True))
        )
    return request._known_people


AVATAR_SIZES = ("sm", "md", "lg")


@register.simple_tag(takes_context=True)
def avatar(context, person, size="sm"):
    """The mark of a person (specs/people.md): their image, or the initials
    on a color of the palette. The image only where the viewer may know the
    person (else the image view would answer 404), the name is the
    ``title``."""
    if size not in AVATAR_SIZES:
        raise ValueError(f"Unknown avatar size {size!r}")
    name = str(person)
    request = context.get("request")
    if person.image and request is not None:
        known = _known_people(request)
        if known is None or person.pk in known:
            return format_html(
                '<img class="wb-avatar wb-avatar-{}" src="{}" alt="{}" title="{}"'
                ' width="256" height="256" loading="lazy">',
                size,
                person.image_url,
                name,
                name,
            )
    return format_html(
        '<span class="wb-avatar wb-avatar-{}" data-avatar-color="{}" title="{}"'
        ' role="img" aria-label="{}">{}</span>',
        size,
        person.avatar_color,
        name,
        name,
        person.initials,
    )


@register.simple_tag
def icon(name):
    """A Bootstrap Icon (frontend/styles/icons.css lists those in use),
    hidden from screen readers: the button's label or title says it"""
    return format_html('<i class="bi bi-{}" aria-hidden="true"></i>', name)


@register.simple_tag
def client_badge(item):
    """The bright badge on everything visible to clients (specs/access.md):
    items, and links, which have a flag of their own"""
    visible = getattr(item, "is_client_visible", None)
    if visible is None:
        visible = item.visible_to_clients
    if not visible:
        return ""
    return format_html(
        '<span class="badge wb-client-badge" title="{}">{}</span>',
        gettext("Clients can see this"),
        gettext("Clients"),
    )


@register.inclusion_tag("items/_due_badge.html")
def due_badge(todo, date_format="j. M", *, badge_only=False):
    """A to-do's due date (``todo``: the item's ``Todo`` detail), as a
    danger badge when it's open and past due, as a quiet "Today" badge on
    the day, else as plain text; nothing without a date. ``badge_only``:
    just the badge, without the day, and nothing when it would be plain
    text (next to the date, on the to-do's page). One place for
    lists, the board, "my to-dos" and the to-do's page (specs/ui-round-1.md,
    part 5)."""
    from biwak.items import due

    return {
        "due_on": todo.due_on,
        "state": due.badge_state(todo),
        "date_format": date_format,
        "badge_only": badge_only,
    }


@register.filter
def ago(when):
    """How long ago, "just now" under a minute (``timesince`` says "0
    minutes"), else "5 minutes ago" """
    from django.utils import timezone
    from django.utils.timesince import timesince

    now = timezone.now()
    if now - when < dt.timedelta(minutes=1):
        return gettext("just now")
    return gettext("%(time)s ago") % {"time": timesince(when, now)}


@register.simple_tag
def project_dot(project):
    """The project's color as a dot before its name (specs/project-colors.md);
    nothing without a color. The color's name is there for screen readers: a
    color is never the only signal."""
    color = getattr(project, "color", "")
    if not color:
        return ""
    return format_html(
        '<span class="wb-project-dot" data-project-color="{}"'
        ' title="{}"><span class="visually-hidden">{}</span></span>',
        color,
        project.color_label,
        gettext("Color: %(color)s") % {"color": project.color_label},
    )


@register.simple_tag
def move_url(item):
    """The form for moving an item (an entry of its "More" menu), empty for
    what doesn't move: completed to-dos, lists, messages"""
    if item.kind == "todo":
        if item.todo.is_completed:
            return ""
        return reverse("todo_move_to", args=[item.pk])
    if item.kind in {"folder", "doc", "file"}:
        return reverse("item_move", args=[item.pk])
    return ""


@register.simple_tag
def rule_widget(bound_field, uid, *, posted=False):
    """The rule widget of a form field with ids of its own (``uid``): the
    list page has one inline form per group, all from the same form. Shows
    the field's initial value, not what was posted to another one; with
    ``posted``, what was posted to this one."""
    widget = bound_field.field.widget
    if hasattr(bound_field.form, "ends"):
        widget.ends = bound_field.form.ends(posted=posted)
    return widget.render(
        bound_field.html_name,
        bound_field.value() if posted else bound_field.initial,
        attrs={"id": f"{bound_field.auto_id}_{uid}"},
    )


@register.simple_tag
def assignee_attrs():
    """The attributes of the inline form's select of people
    (``frontend/assignees.js``)"""
    return format_html_join(" ", '{}="{}"', forms.assignee_picker_attrs().items())


@register.simple_tag
def posted_here(form, group):
    """Whether the bound inline form of the list page was sent from this
    group's section (``None``: the ungrouped one), and came back with its
    errors"""
    return form.is_bound and str(form.data.get("group") or "") == (
        str(group.pk) if group else ""
    )
