import html
import re

from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.html import escape, format_html, format_html_join, strip_tags
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
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
                title = str(user)
                if not user.is_active:
                    # Shown as such, like assignees (specs/handover.md)
                    title = gettext("%(name)s (inactive)") % {"name": title}
                text = f'title="{escape(title)}">@{escape(display_name(user, reader))}'
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
                if not user.is_active:
                    mention.content += (
                        ' <span class="text-body-secondary">'
                        f"{escape(gettext('(inactive)'))}</span>"
                    )
            else:
                mention.content = escape(f"@{label.removeprefix('@')}")
            result.append(mention)
            index = end + 1
        block.children = result


_markdown.core.ruler.push("mentions", _mentions)


def _external_links(state):
    """Links to other sites open in a new tab, so that the installed app
    (specs/pwa.md) keeps its window"""
    for block in state.tokens:
        for token in block.children or ():
            if token.type == "link_open" and (token.attrGet("href") or "").startswith((
                "http://",
                "https://",
            )):
                token.attrSet("target", "_blank")
                token.attrSet("rel", "noopener noreferrer")


_markdown.core.ruler.push("external_links", _external_links)


def _checkboxes(state):
    """Checkboxes of task lists (``biwak/richtext/checklists.py``):
    numbered, in a mail a glyph, disabled unless the page lets the viewer
    tick them (``env["tickable"]``)"""
    from biwak.richtext.checklists import is_checkbox

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
            # Named by its line's text, for screen readers
            label = "".join(
                child.content
                for child in block.children[1:]
                if child.type in {"text", "code_inline"}
            ).strip()
            box.content = (
                f'<input class="task-list-item-checkbox" type="checkbox" '
                f'data-index="{number}"'
                f' aria-label="{escape(label)}"'
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
def checklist_markdown(context, text, item, comment=None, *, without_title=False):
    """Like ``|markdown``, and for people who may change the text its
    checkboxes can be ticked in place (``frontend/checklist.js`` posts to
    ``item_tick``); the others see them disabled. ``comment``: the text is
    that comment's. ``without_title``: a doc's page, whose header shows
    the first line when it's a heading (``render_markdown()``)."""
    from biwak.items import operations as ops
    from biwak.richtext.checklists import text_hash

    user = context["request"].user
    if comment is not None:
        allowed = not user.is_client or comment.author_id == user.pk
    else:
        allowed = ops.can_tick(user, item)
    rendered = render_markdown(
        text, item, tickable=allowed, without_title=without_title
    )
    if not allowed or 'data-index="' not in rendered:
        return rendered
    return format_html(
        '<div class="wb-checklist" data-tick-url="{}" data-version="{}"{}>{}</div>',
        reverse("item_tick", args=[item.pk]),
        text_hash(text),
        format_html(' data-comment="{}"', comment.pk) if comment is not None else "",
        rendered,
    )


@register.simple_tag
def public_markdown(text, link, *, without_title=False):
    """The text on the public page of ``link`` (specs/public-links.md):
    nobody looked up, checkboxes disabled, the item's attachments at their
    storage's URLs like on other pages (the page checked the token)"""
    return render_markdown(
        text, link.item, without_title=without_title, public_token=link.token
    )


@register.filter
def parse_datetime(value):
    """A time stored as ISO text (an event's ``data``), or None"""
    from django.utils.dateparse import parse_datetime as parse

    return parse(value) if isinstance(value, str) else value


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
    without_title=False,
    public_token=None,
):
    """``absolute`` for the API and mails: attachment URLs with BASE_URL.
    ``public_token``: the public page of the link with this token
    (specs/public-links.md): mentions as written, nobody looked up.
    ``attachment_urls=False`` skips looking them up (excerpts don't show
    them). ``tickable`` leaves task list checkboxes enabled, ``glyphs``
    turns them into ☐ and ☑ (mails). ``without_title`` leaves out the
    first line when it's a heading: a doc's title (``doc_title()``), which
    its page's header shows; the checkboxes keep their numbers."""
    from biwak.activity.mentions import mentioned_ids, reader, visible_people

    text = str(text or "")
    people = (
        visible_people(item, mentioned_ids(text))
        if item is not None and public_token is None
        else {}
    )
    env = {
        "people": people,
        "reader": reader(),
        "links": not absolute and not glyphs and public_token is None,
        "tickable": tickable,
        "glyphs": glyphs,
    }
    tokens = _markdown.parse(text, env)
    if without_title:
        tokens = _without_title(text, tokens)
    if public_token is None:
        # Nobody signs in on public pages to follow the trampoline
        _basecamp_links(tokens, absolute=absolute)
    if attachment_urls:
        _attachment_urls(tokens, item, absolute=absolute)
    return mark_safe(_markdown.renderer.render(tokens, _markdown.options, env))


def _basecamp_links(tokens, *, absolute):
    """Links to Basecamp recordings go through the trampoline
    (``biwak.importer.links``), which leads into Biwak or to Basecamp: no
    new tab, nothing looked up"""
    from biwak.importer.links import trampoline

    for token in tokens:
        for child in token.children or ():
            if child.type != "link_open":
                continue
            if url := trampoline(child.attrGet("href"), absolute=absolute):
                child.attrSet("href", url)
                child.attrs.pop("target", None)
                child.attrs.pop("rel", None)


def _without_title(text, tokens):
    """The tokens without the heading on the text's first line with
    anything in it (``doc_title()``'s line)"""
    first = next(
        (number for number, line in enumerate(text.splitlines()) if line.strip()),
        None,
    )
    if tokens and tokens[0].type == "heading_open" and tokens[0].map[0] == first:
        end = next(i for i, t in enumerate(tokens) if t.type == "heading_close")
        return tokens[end + 1 :]
    return tokens


def _attachment_reference(token):
    """``(attribute, key)`` of a link or image to ``attachment:KEY``"""
    from biwak.files.models import REFERENCE

    attr = {"link_open": "href", "image": "src"}.get(token.type)
    if attr and (match := REFERENCE.fullmatch(token.attrGet(attr) or "")):
        return attr, match[1]
    return None


def _attachment_urls(tokens, item, *, absolute):
    """``attachment:KEY`` (specs/files.md) becomes the file's URL; images
    show inline, scaled to the text's width. On pages (which checked
    access to the item) the storage's URL (``file_urls``), in mails and
    the API (``absolute``) the download view's, which checks whoever
    follows it. Only the item's own attachments: a reference to another
    item's (or a missing one) becomes a plain "attachment", without its
    name, which its URL contains too."""
    from biwak.files import file_urls
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
                child.attrSet(
                    attr,
                    settings.BASE_URL + attachment.get_absolute_url()
                    if absolute
                    else file_urls.file_url(attachment),
                )
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
    from biwak.activity import mentions

    return mentions.title(item.title, item)


@register.filter
def title_text(title):
    """A stored title (e.g. an event's) with the mentions as ``@`` and their
    labels, without looking anybody up"""
    from biwak.activity import mentions

    return mentions.title(title)


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


@register.simple_tag
def forwarded_waiting(user):
    """The person menu's "Forwarded" (specs/forwarding.md): None while
    forwarding is off or for clients, else how many mails wait"""
    from biwak.forwarding import operations

    if not operations.enabled() or not operations.can_forward(user):
        return None
    return operations.waiting(user)


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
def person_link(context, person, *, name=None):
    """A person's name (or ``name``), linked to their page when the viewer
    may open it (``known_people()``), else plain text: names in sentences,
    the activity, the timeline and histories (``person_page`` adds the
    mark, for lists)"""
    from biwak.organizations.people import linked_name

    if person is None:
        # Events without an actor (specs/stale-todos.md)
        return gettext("Biwak")
    label = name if name is not None else short_name(context, person)
    request = context.get("request")
    return linked_name(person, label, _known_people(request) if request else set())


@register.simple_tag(takes_context=True)
def person_page(context, person, *, size="sm", name=None):
    """The mark and the short name (or ``name``) of a person, linked to
    their page (``/people/<id>/``) when the viewer may open it
    (``known_people()``, as the page itself), else plain text; a quiet link
    (no underline until hover). The one place lists of people use."""
    from biwak.organizations.people import linked_name

    label = name if name is not None else short_name(context, person)
    if not person.is_active:
        # Inactive people show as such (specs/handover.md)
        label = format_html(
            '{} <span class="text-body-secondary">{}</span>',
            label,
            gettext("(inactive)"),
        )
    inner = format_html("{} {}", avatar(context, person, size), label)
    request = context.get("request")
    return linked_name(person, inner, _known_people(request) if request else set())


@register.simple_tag(takes_context=True)
def person_avatar(context, person, *, size="md"):
    """The mark of a person alone, linked to their page like
    ``person_page`` (rows of avatars: the project's members); the mark's
    title and label name them"""
    from biwak.organizations.people import linked_name

    request = context.get("request")
    return linked_name(
        person,
        avatar(context, person, size),
        _known_people(request) if request else set(),
    )


def _known_people(request):
    """None if the viewer may know everybody, else the set of the people
    they may know (``biwak.organizations.people.known_people()``); looked
    up once per request"""
    from biwak.organizations.people import known_ids

    if not hasattr(request, "_known_people"):
        request._known_people = known_ids(request.user)
    return request._known_people


@register.simple_tag(takes_context=True)
def known_in(context, item, people):
    """Those of ``people`` the viewer may see named in the item's project
    (``Project.people_known_to()``: clients and externals don't learn about
    people removed from it), looked up once per project and request"""
    from django.contrib.auth.models import AnonymousUser

    from biwak.projects.models import known_ids_for

    request = context.get("request")
    viewer = getattr(request, "user", None) or AnonymousUser()
    known = known_ids_for(viewer, item)
    return [p for p in people if known is None or p.pk in known]


AVATAR_SIZES = ("sm", "md", "lg")


@register.simple_tag(takes_context=True)
def avatar(context, person, size="sm"):
    """The mark of a person (specs/people.md): their image, or their drawn
    mark in white on a color of the palette. The image only where the
    viewer may know the person (else the image view would answer 404), the
    name is the ``title``. Away (specs/quiet-hours.md): a small sign, and the title
    says until when."""
    if size not in AVATAR_SIZES:
        raise ValueError(f"Unknown avatar size {size!r}")
    name = str(person)
    css = f"wb-avatar wb-avatar-{size}"
    if not person.is_active:
        # Greyed, the title says why (specs/handover.md)
        css += " wb-avatar-inactive"
        name = gettext("%(name)s (inactive)") % {"name": name}
    away = person.away_text if person.is_active else ""
    if away:
        name = f"{name}\n{away}"
    request = context.get("request")
    mark = None
    if person.image and request is not None:
        known = _known_people(request)
        if known is None or person.pk in known:
            mark = format_html(
                '<img class="{}" src="{}" alt="{}" title="{}"'
                ' width="256" height="256" loading="lazy">',
                css,
                person.image_url,
                name,
                name,
            )
    if mark is None:
        # The drawn mark in white through a CSS mask (frontend/styles/marks.css)
        mark = format_html(
            '<span class="{} wb-mark wb-mark-{}" data-avatar-color="{}" title="{}"'
            ' role="img" aria-label="{}"></span>',
            css,
            person.mark,
            person.avatar_color,
            name,
            name,
        )
    if not away:
        return mark
    return format_html(
        '<span class="wb-away-mark">{}<span class="wb-away-sign"'
        ' aria-hidden="true">{}</span></span>',
        mark,
        icon("moon-fill"),
    )


@register.simple_tag
def away_detail(person, *, parentheses=False):
    """ "away until 3 Dec" for someone away (specs/quiet-hours.md), quiet;
    nothing otherwise"""
    from biwak.accounts.quiet import away_detail as detail

    if not person.is_active or not (text := detail(person)):
        return ""
    return format_html(
        '<span class="wb-away-detail">{}</span>',
        f"({text})" if parentheses else text,
    )


@register.simple_tag(takes_context=True)
def away_notice(context, person):
    """ "Ada is away until 3 Dec: back on the 4th" on a line of its own,
    under a to-do's assignees (specs/quiet-hours.md); nothing otherwise"""
    from biwak.accounts.quiet import away_notice as notice

    if not person.is_active:
        return ""
    if not (text := notice(person, short_name(context, person))):
        return ""
    return format_html('<div class="wb-away-line small">{}</div>', text)


@register.simple_tag
def away_attrs(person):
    """The people picker's ``data-away`` attributes of an option written by
    hand (``items/_add_todo.html``)"""
    from django.forms.utils import flatatt

    from biwak.accounts.quiet import option_attrs

    return flatatt(option_attrs(person))


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


@register.simple_tag(takes_context=True)
def public_link_badge(context, item):
    """ "Public link" on the item's own page while a live one exists, for
    staff, opening Share… (specs/public-links.md, decided 2026-11-22:
    the page only, not rows or tiles)"""
    from biwak.public_links.models import PublicLink

    request = context.get("request")
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or user.is_client:
        return ""
    if not item.is_shareable:
        return ""
    link = PublicLink.objects.live().filter(item=item).first()
    if link is None:
        return ""
    return format_html(
        '<a class="badge wb-public-badge" href="{}" data-modal title="{}">{}</a>',
        reverse("item_share", args=[item.pk]),
        gettext("Shared publicly until %(date)s")
        % {"date": date_format(localtime(link.expires_at), "SHORT_DATETIME_FORMAT")},
        gettext("Public link"),
    )


@register.inclusion_tag("items/_due_badge.html")
def due_badge(todo, date_format="MONTH_DAY_FORMAT", *, badge_only=False):
    """A to-do's due date (``todo``: the item's ``Todo`` detail), as a
    danger badge when it's open and past due, as a quiet "Today" badge on
    the day, else as plain text; nothing without a date. ``badge_only``:
    just the badge, without the day, and nothing when it would be plain
    text (next to the date, on the to-do's page). One place for
    lists, the board, "my to-dos" and the to-do's page (specs/todos.md, "The
    to-do's page"). With a start date the range, "3–7 Dec"
    (specs/start-dates.md)."""
    from biwak.formats import format_range
    from biwak.items import due

    return {
        "due_on": todo.due_on,
        "dates": todo.due_on and format_range(todo.starts_on, todo.due_on, date_format),
        "short_dates": todo.due_on
        and format_range(todo.starts_on, todo.due_on, "MONTH_DAY_FORMAT"),
        "state": due.badge_state(todo),
        "date_format": date_format,
        "badge_only": badge_only,
    }


@register.filter
def moment(when, on=None):
    """A past moment by the one rule (``biwak.richtext.text.moment``,
    specs/ui.md): "3 hours ago" within seven days, then the date, the exact
    time on hover. ``{{ x|moment:"on" }}`` for sentences: "on 12 Nov
    2026"."""
    from biwak.formats import format_date
    from biwak.richtext import text

    if not when:
        return ""
    return format_html(
        '<time datetime="{}" title="{}">{}</time>',
        when.isoformat(),
        format_date(localtime(when), "SHORT_WEEKDAY_DATETIME_FORMAT"),
        text.moment(when, on=on == "on"),
    )


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


@register.simple_tag(takes_context=True)
def move_url(context, item):
    """The form for moving an item (an entry of its "More" menu), empty for
    what doesn't move: completed to-dos, lists and messages without another
    project to go to (specs/lists-across-projects.md)"""
    if item.kind == "todo":
        if item.todo.is_completed:
            return ""
        return reverse("todo_move_to", args=[item.pk])
    if item.kind in {"folder", "doc", "file"}:
        return reverse("item_move", args=[item.pk])
    if item.kind in {"list", "message"}:
        from biwak.items.across import target_projects

        if target_projects(context["request"].user, item).exists():
            return reverse("item_move_project", args=[item.pk])
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
def assignee_attrs(teams=None):
    """The attributes of the inline form's select of people
    (``frontend/people-picker.js``), with the teams' (``teams``,
    ``PeopleSelect.team_attrs()``, specs/teams.md)"""
    attrs = {**forms.people_picker_attrs(), **(teams or {})}
    return format_html_join(" ", '{}="{}"', attrs.items())


@register.simple_tag
def posted_here(form, group):
    """Whether the bound inline form of the list page was sent from this
    group's section (``None``: the ungrouped one), and came back with its
    errors"""
    return form.is_bound and str(form.data.get("group") or "") == (
        str(group.pk) if group else ""
    )


class CaptureNode(template.Node):
    def __init__(self, nodelist, name):
        self.nodelist = nodelist
        self.name = name

    def render(self, context):
        context[self.name] = mark_safe(self.nodelist.render(context).strip())
        return ""


@register.tag
def capture(parser, token):
    """``{% capture as subject %}…{% endcapture %}``: the rendered block as a
    variable, so that ``{% blocktranslate %}`` can place it in a whole
    sentence (specs/languages.md: German orders the words differently)"""
    bits = token.split_contents()
    if len(bits) != 3 or bits[1] != "as":
        raise template.TemplateSyntaxError("Usage: {% capture as name %}")
    nodelist = parser.parse(("endcapture",))
    parser.delete_first_token()
    return CaptureNode(nodelist, bits[2])


@register.filter(expects_localtime=True, is_safe=False)
def dateformat(value, name):
    """``{{ day|dateformat:"SHORT_DATE_FORMAT" }}``: a format of the active
    language by its name, Django's or ours (``biwak.formats``)"""
    from biwak.formats import format_date

    if value in {None, ""}:
        return ""
    return format_date(value, name)
