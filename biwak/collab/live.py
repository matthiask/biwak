"""Docs edited live (specs/collaboration.md): the shared state in the
database, who may connect, and the messages to the open editors

The state is ``LiveState`` (merged) plus the ``LiveUpdate`` rows after
it, the rich editor's document (``ytext``). Its document is what
``Doc.content`` says after every merge, so an edit through
the API can be made on the state as the API client saw it and merges with
what people type meanwhile. Merging (``files.operations.save_live()``)
writes ``Doc.content``, the events and the versions.
"""

from itertools import groupby

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from biwak.activity.mentions import mentioned_ids
from biwak.collab import ytext
from biwak.collab.models import LiveState, LiveUpdate
from biwak.items import operations as ops
from biwak.items.models import Doc, Item, Kind


# Who may do what in a doc's live session
READ = "read"
WRITE = "write"


def access(user, pk, *, session_key=None):
    """``WRITE``, ``READ`` or None (the doc doesn't exist for the person:
    the websocket refuses it like the pages, 404). Staff edit what they
    see, clients the docs they created and watch the others they see
    (decided 2026-11-20); nobody edits a read-only doc. With
    ``session_key``, the session must still exist, unexpired (logging out
    closes the session; organizations requiring single sign-on end it after
    24 hours, ``sso.session_alive()``)."""
    if session_key is not None:
        from biwak.accounts import sso

        if not sso.session_alive(session_key, user):
            return None
    # A draft is its creator's alone (specs/files.md, "Docs")
    item = (
        Item.objects
        .visible_to(user, drafts=True)
        .filter(pk=pk, kind=Kind.DOC)
        .select_related("doc")
        .first()
    )
    if item is None:
        return None
    if item.doc.read_only or not ops.can_change(user, item):
        return READ
    return WRITE


def ensure_state(doc):
    """The doc's ``LiveState``, made from its content the first time; call
    with the doc's row locked. A state whose document differs from the
    content's without updates pending (the content changed some other way)
    follows the content."""
    state = LiveState.objects.filter(doc=doc).first()
    if state is None:
        return LiveState.objects.create(doc=doc, state=ytext.initial_state(doc.content))
    if not doc.live_updates.exists():
        y = ytext.ydoc(state.state)
        if not ytext.means(y, doc.content):
            ytext.edit(y, doc.content)
            state.state = y.get_update()
            state.updated_at = timezone.now()
            state.save(update_fields=["state", "updated_at"])
    return state


@transaction.atomic
def prepare(pk):
    """Makes sure the doc has its state before the first editor syncs;
    returns the doc's project"""
    doc = Doc.objects.select_for_update(of=("self",)).select_related("item").get(pk=pk)
    ensure_state(doc)
    return doc.item.project_id


def history(pk):
    """Tells the doc's live state from one made again later (the editors
    keep unsent changes in their browsers, which only fit the history they
    were typed in)"""
    prepare(pk)
    return str(int(LiveState.objects.get(doc_id=pk).created_at.timestamp() * 1000))


def load(pk):
    """The doc's Yjs document as it is now, the updates not merged yet
    included. The updates first: a merge in between moves them into the
    state, and reading something twice changes nothing in Yjs."""
    with transaction.atomic():
        updates = list(
            LiveUpdate.objects.filter(doc_id=pk).values_list("data", flat=True)
        )
        state = LiveState.objects.get(doc_id=pk).state
    return ytext.ydoc(state, updates)


def append(pk, update, user):
    """Stores an update somebody typed"""
    return LiveUpdate.objects.create(doc_id=pk, data=update, user=user)


def apply_text(doc, content, *, user):
    """Changes the doc's text to ``content`` as an update on the state
    (whose text is the content people and the API saw last), stored like
    the others and sent to the open editors after the commit; call with
    the doc's row locked. Returns whether anything changed."""
    state = ensure_state(doc)
    update = ytext.edit(ytext.ydoc(state.state), content)
    if not update:
        return False
    append(doc.pk, update, user)
    transaction.on_commit(lambda: send_update(doc.pk, update), robust=True)
    return True


def apply_live_text(doc, content, *, user):
    """Like ``apply_text()``, but as an edit of the text as it is now: the
    state plus what people typed and isn't merged yet, so that only the
    difference between that and ``content`` (a tick: one box) is sent and
    nothing typed is lost or doubled. Call with the doc's row locked.
    Returns whether anything changed."""
    ensure_state(doc)
    update = ytext.edit(load(doc.pk), content)
    if not update:
        return False
    append(doc.pk, update, user)
    transaction.on_commit(lambda: send_update(doc.pk, update), robust=True)
    return True


def live_text(doc):
    """The doc's text as the open editors have it: ``Doc.content`` follows
    a few seconds after the typing. Call with the doc's row locked."""
    ensure_state(doc)
    return ytext.text(load(doc.pk), doc.content)


def may_write(user, item):
    """Whether what the person typed is merged: they still see the doc and
    may change it. Trashing and the read-only option don't count: what was
    typed before is kept."""
    return (
        ops.can_change(user, item)
        and Item.objects
        .visible_to(user, with_trashed=True, drafts=True)
        .filter(pk=item.pk)
        .exists()
    )


def merge(doc):
    """Merges the pending updates into the state; call with the doc's row
    locked. The updates of people who can't change the doc anymore are
    dropped, unless others' updates build on them (their text would be
    lost); either way they aren't authors. Returns the text, the authors
    (in order, without repetitions), who typed the mentions new in the
    text, by the mentioned person's ID (the author whose updates completed
    them), and everybody whose updates are in the text (authors and those
    kept, whose files are linked too)."""
    state = ensure_state(doc)
    updates = list(doc.live_updates.select_related("user"))
    if not updates:
        return doc.content, [], {}, []
    LiveUpdate.objects.filter(pk__in=[u.pk for u in updates]).delete()
    authors = {u.user_id: u.user for u in updates}
    authors = {pk: user for pk, user in authors.items() if may_write(user, doc.item)}
    kept = [u for u in updates if u.user_id in authors]
    if len(kept) < len(updates) and _strands(state.state, updates, kept):
        kept = updates
    y = ytext.ydoc(state.state)
    known = mentioned_ids(ytext.text(y))
    typed = {}
    for user_id, run in groupby(kept, key=lambda u: u.user_id):
        for update in run:
            y.apply_update(bytes(update.data))
        now = mentioned_ids(ytext.text(y))
        if user_id in authors:
            for pk in now - known:
                typed.setdefault(pk, authors[user_id])
        known = now
    state.state = y.get_update()
    state.updated_at = timezone.now()
    state.save(update_fields=["state", "updated_at"])
    typists = list({u.user_id: u.user for u in kept}.values())
    return ytext.text(y, doc.content), list(authors.values()), typed, typists


def _strands(state, updates, kept):
    """Whether some of ``kept`` build on the other updates: Yjs keeps them
    pending without them, and their text out of the document"""
    y = ytext.ydoc(state)
    clients = set()
    for update in updates:
        before = ytext.clocks(y)
        y.apply_update(bytes(update.data))
        if update in kept:
            clients |= {
                client
                for client, clock in ytext.clocks(y).items()
                if before.get(client) != clock
            }
    everything = ytext.clocks(y)
    merged = ytext.clocks(ytext.ydoc(state, [u.data for u in kept]))
    return any(merged.get(client, 0) < everything[client] for client in clients)


def pending():
    """Docs with updates not merged yet, e.g. after the server stopped
    while somebody was typing (``fairy_tasks``)"""
    return Doc.objects.filter(live_updates__isnull=False).distinct()


# Messages to the open editors (consumers.DocConsumer) ------------------


def doc_group(pk):
    return f"collab-doc-{pk}"


def project_group(pk):
    return f"collab-project-{pk}"


def user_group(pk):
    return f"collab-user-{pk}"


def _send(group, message):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(group, message)


def send_update(pk, update):
    """An update made on the server (the API) to the doc's editors"""
    _send(doc_group(pk), {"type": "doc.update", "update": update})


def check_access(*, doc=None, project=None, user=None, session=None):
    """Tells the editors of a doc, of a project's docs or of a person to
    check whether they may still edit or see the doc, after the commit;
    ``session``: the key of a login session that ended (logging out), whose
    websockets close"""
    groups = [
        group(pk)
        for group, pk in [
            (doc_group, doc),
            (project_group, project),
            (user_group, user),
        ]
        if pk is not None
    ]
    message = {"type": "access.check"}
    if session is not None:
        message["session"] = session
    transaction.on_commit(
        lambda: [_send(group, message) for group in groups],
        robust=True,
    )
