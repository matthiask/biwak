"""Search (specs/search.md): the page's search, cursor paginated."""

from ninja import Router

from biwak.api_conventions import ItemOut, item_out, page_of, paginated
from biwak.items.models import Kind
from biwak.projects.api import project_for
from biwak.search import queries


router = Router(tags=["search"])


class ResultOut(ItemOut):
    project_name: str
    project_archived: bool
    # The project, the list or the list it is in is archived
    archived: bool
    # Escaped HTML with the matched words in <mark>; empty if only the title
    # has them
    title_html: str
    excerpt: str
    excerpt_html: str
    # The excerpt is from a comment
    in_comment: bool


def result_out(item):
    hit = item.hit
    return item_out(item) | {
        "project_name": item.project.name,
        "project_archived": item.project.archived_at is not None,
        "archived": queries.is_archived(item),
        "title_html": hit.title,
        "excerpt": hit.text,
        "excerpt_html": hit.excerpt_html,
        "in_comment": hit.in_comment,
    }


@router.get("search/", response=page_of(ResultOut))
def search(
    request,
    *,
    q: str,
    project_id: int | None = None,
    kind: Kind | None = None,
    mine: bool = False,
    archived: bool = False,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """Items with all the words (each also as the start of a word) in their
    title, text or comments, newest first; ``mine`` only what you
    created or what is assigned to you.
    Archived projects and lists (with their contents) are left out unless
    ``archived``; templates always."""
    project = project_for(request, project_id) if project_id else None
    found = queries.search(
        request.user,
        q,
        project=project,
        kind=kind,
        mine=mine,
        archived=archived,
    )

    def prepare(items):
        hits = queries.hits(items, q)
        for item in items:
            item.hit = hits[item.pk]

    return paginated(
        request,
        found,
        result_out,
        prepare=prepare,
        ordering=("-updated_at", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )
