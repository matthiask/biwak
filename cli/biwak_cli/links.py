"""Public links, bookmarks and links"""

import click

from biwak_cli.core import (
    cli,
    clients,
    console,
    echo_json,
    json_option,
    need,
    request,
    table,
)


# Public links ---------------------------------------------------------------


def show_public_link(link):
    item = link["item"]
    click.echo(f"#{item['id']} {item['title']} {clients(item)}".rstrip())
    click.echo(link["url"])
    click.echo(f"Expires {link['expires_at'][:16].replace('T', ' ')}")


@cli.group("public-links", invoke_without_command=True)
@json_option
@click.pass_context
def public_links(ctx, as_json):
    """Public links; without a command the live ones in the projects you
    can open (admins: all), the soonest expiry first (staff)"""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "public-links/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Kind", "Title", "Project", "Expires", "By", "URL", "")
    for link in data:
        item = link["item"]
        t.add_row(
            str(item["id"]),
            item["kind"],
            item["title"],
            str(item["project_id"]),
            link["expires_at"][:16].replace("T", " "),
            link["created_by"]["short_name"],
            link["url"],
            clients(item),
        )
    console.print(t)
    return None


@public_links.command("create")
@click.argument("item", type=int)
@click.option(
    "--days",
    type=click.Choice(["1", "3", "7", "30"]),
    default="7",
    show_default=True,
    help="How long the link works.",
)
@json_option
def public_links_create(item, days, as_json):
    """A public link to ITEM (a to-do, message, doc or file) for people
    without an account, read only, until it expires;
    replaces the one there is (staff)"""
    data = request("POST", f"items/{item}/public-link/", json={"days": int(days)})
    if as_json:
        return echo_json(data)
    show_public_link(data)
    return None


@public_links.command("delete")
@click.argument("item", type=int)
@json_option
def public_links_delete(item, as_json):
    """Stop sharing ITEM publicly: its public link stops working (staff)"""
    data = request("DELETE", f"items/{item}/public-link/")
    if as_json:
        return echo_json(data)
    click.echo(f"Stopped sharing #{item} publicly.")
    return None


# Bookmarks and links --------------------------------------------------------


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def bookmarks(ctx, as_json):
    """Bookmarks; without a command yours, newest first"""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "bookmarks/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Kind", "Title", "Project", "")
    for bookmark in data:
        if item := bookmark["item"]:
            t.add_row(
                str(item["id"]),
                item["kind"],
                item["title"],
                str(item["project_id"]),
                clients(item),
            )
        else:
            project = bookmark["project"]
            t.add_row(
                str(project["id"]), "project", project["name"], str(project["id"]), ""
            )
    console.print(t)
    return None


@bookmarks.command("create")
@click.argument("target", type=int)
@click.option("--project", "is_project", is_flag=True, help="TARGET is a project.")
def bookmark_add(target, is_project):
    """Bookmark the item (or, with --project, the project) TARGET"""
    request("PUT", f"{'projects' if is_project else 'items'}/{target}/bookmark/")
    click.echo(f"Bookmarked #{target}.")


@bookmarks.command("delete")
@click.argument("target", type=int)
@click.option("--project", "is_project", is_flag=True, help="TARGET is a project.")
def bookmark_remove(target, is_project):
    """Remove the bookmark of the item (or, with --project, the project) TARGET"""
    request("DELETE", f"{'projects' if is_project else 'items'}/{target}/bookmark/")
    click.echo(f"Removed the bookmark of #{target}.")


@cli.group(invoke_without_command=True)
@click.option("--project", type=int, help="The project's ID.")
@json_option
@click.pass_context
def links(ctx, project, as_json):
    """Links to outside tools; without a command those of --project"""
    if ctx.invoked_subcommand is not None:
        return None
    need(project, "--project")
    data = request("GET", f"projects/{project}/links/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Title", "Kind", "URL", "")
    for link in data:
        t.add_row(
            str(link["id"]),
            link["title"],
            link["kind"],
            link["url"],
            clients(link),
        )
    console.print(t)
    return None


@links.command("create")
@click.argument("project", type=int)
@click.argument("url")
@click.option("--title", default="", help="The host if left out.")
@click.option(
    "--clients", is_flag=True, help="Visible to clients (internal otherwise)."
)
@json_option
def link_add(project, url, title, clients, as_json):
    """Add URL to PROJECT"""
    body = {"url": url, "title": title, "visible_to_clients": clients}
    data = request("POST", f"projects/{project}/links/", json=body)
    if as_json:
        return echo_json(data)
    click.echo(f"Added link #{data['id']} ({data['kind']}).")
    return None


@links.command("delete")
@click.argument("link_id", metavar="LINK", type=int)
def link_delete(link_id):
    """Delete LINK"""
    request("DELETE", f"links/{link_id}/")
    click.echo(f"Deleted link #{link_id}.")
