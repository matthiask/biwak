"""The activity feed and search"""

import click

from biwak_cli.core import (
    actor,
    cli,
    clients,
    console,
    echo_json,
    json_option,
    link,
    paginate,
    table,
)


# The activity feed ----------------------------------------------------------


@cli.command()
@click.option("--project", type=int, help="Only this project's ID.")
@click.option("--person", type=int, help="Only what this person's ID did.")
@click.option("--kind", help="Only this kind of item: todo, list, …")
@click.option("--action", help="Only this action: created, completed, …")
@click.option("--since", help="YYYY-MM-DD: nothing older.")
@click.option("--limit", default=50, show_default=True, help="At most this many.")
@json_option
def feed(project, person, kind, action, since, limit, as_json):
    """The latest activity, newest first"""
    params = {
        key: value
        for key, value in {
            "project_id": project,
            "person_id": person,
            "kind": kind,
            "action": action,
            "since": since,
        }.items()
        if value is not None
    }
    events = paginate("feed/", params, limit=limit)
    if as_json:
        return echo_json(events)
    t = table("When", "Person", "Action", "What", "Project", "")
    for event in events:
        item = event["item"] or {}
        t.add_row(
            event["created_at"][:16].replace("T", " "),
            actor(event),
            event["action"].replace("_", " "),
            link(
                item.get("title")
                or event["data"].get("title")
                or event["data"].get("name")
                or "",
                item.get("url"),
            ),
            str(event["project_id"]),
            clients(event),
        )
    console.print(t)
    return None


# Search ---------------------------------------------------------------------


@cli.command()
@click.argument("terms", nargs=-1, required=True)
@click.option("--project", type=int, help="Only this project's ID.")
@click.option("--kind", help="Only this kind of item: todo, doc, message, …")
@click.option(
    "--mine", is_flag=True, help="Only what you created or is assigned to you."
)
@click.option(
    "--archived",
    is_flag=True,
    help="Include archived projects and lists, which are left out otherwise.",
)
@click.option("--limit", default=50, show_default=True, help="At most this many.")
@json_option
def search(terms, project, kind, mine, archived, limit, as_json):
    """Find items by words in their title, text or comments, newest first.
    Every word also matches as the start of a word."""
    params = {"q": " ".join(terms)}
    if project is not None:
        params["project_id"] = project
    if kind:
        params["kind"] = kind
    if mine:
        params["mine"] = "true"
    if archived:
        params["archived"] = "true"
    results = paginate("search/", params, limit=limit)
    if as_json:
        return echo_json(results)
    t = table("ID", "Kind", "Title", "Project", "Found", "")
    for result in results:
        found = result["excerpt"]
        if found and result["in_comment"]:
            found = f"(comment) {found}"
        t.add_row(
            str(result["id"]),
            result["kind"],
            link(result["title"], result.get("url")),
            result["project_name"] + (" (archived)" if result["archived"] else ""),
            found,
            clients(result),
        )
    console.print(t)
    return None
