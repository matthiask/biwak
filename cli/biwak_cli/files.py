"""Files, folders and docs, and moving items"""

import os

import click

from biwak_cli.core import (
    PALETTE,
    also_option,
    attach_option,
    cli,
    clients,
    console,
    download,
    echo_json,
    echo_linked,
    json_option,
    link,
    need,
    paginate,
    people_ids,
    request,
    table,
    terminate,
    visible_option,
    with_attachments,
)


@cli.group(invoke_without_command=True)
@click.option("--project", type=int, help="The project's ID.")
@click.option("--folder", type=int, help="This folder's contents.")
@json_option
@click.pass_context
def files(ctx, project, folder, as_json):
    """Files; without a command the docs and files of --project's root, or
    of --folder. Upload, replace and download files."""
    if ctx.invoked_subcommand is not None:
        return None
    need(project, "--project")
    data = request(
        "GET",
        f"projects/{project}/files/",
        params={"folder_id": folder} if folder else None,
    )
    if as_json:
        return echo_json(data)
    if data["breadcrumbs"]:
        click.echo("/ " + " / ".join(c["title"] for c in data["breadcrumbs"]))
    click.echo(f"Order: {data['ordering']}")
    t = table("ID", "Kind", "Name", "Size", "")
    for entry in data["entries"]:
        t.add_row(
            str(entry["id"]),
            entry["kind"],
            link(entry["title"], entry.get("url")),
            f"{entry['size']:,} B" if entry["size"] is not None else "",
            clients(entry),
        )
    console.print(t)
    return None


@cli.group()
def folders():
    """Create, change and order folders, move docs and files into them"""


@folders.command("create")
@click.argument("project", type=int)
@click.argument("title")
@click.option("--folder", "parent", type=int, help="Inside this folder.")
@visible_option
@click.option(
    "--color",
    type=click.Choice([*PALETTE, "none"]),
    help="The folder's color; without, it has none.",
)
@json_option
def folder_new(project, title, parent, visible, color, as_json):
    """Create a folder titled TITLE in PROJECT"""
    body = {"title": title, "parent_id": parent, "visible_to_clients": visible}
    if color not in (None, "none"):
        body["color"] = color
    data = request("POST", f"projects/{project}/folders/", json=body)
    if as_json:
        return echo_json(data)
    click.echo(f"Created #{data['id']}: {data['url']}")
    return None


@folders.command("move")
@click.argument("item", type=int)
@click.argument("folder", type=int, required=False)
@json_option
def folder_move(item, folder, as_json):
    """Move a folder, doc or file ITEM into FOLDER, or to the root"""
    data = request("POST", f"items/{item}/move/", json={"parent_id": folder})
    if as_json:
        return echo_json(data)
    click.echo(f"Moved #{item}.{' [clients]' if data['visible_to_clients'] else ''}")
    return None


@cli.group()
def items():
    """What works on any kind of item"""


@items.command("move")
@click.argument("item", type=int)
@click.option("--to", "project", type=int, required=True, help="The project's ID.")
@click.option(
    "--confirm",
    is_flag=True,
    help="Move it although people are dropped or clients there will see it.",
)
@json_option
def items_move(item, project, confirm, as_json):
    """Move the list, message, folder, doc or file ITEM at the top of its
    project to the top of another project, with everything in it.
    Assignees and subscribers who aren't members there are dropped."""
    data = request(
        "POST",
        f"items/{item}/move/",
        json={"project_id": project, "confirm": confirm},
    )
    if as_json:
        return echo_json(data)
    shown = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"Moved #{item} to project {data['project_id']}.{shown}")
    return None


@folders.command("update")
@click.argument("folder_id", metavar="FOLDER", type=int)
@click.option("--title", help="The new name.")
@click.option(
    "--color",
    type=click.Choice([*PALETTE, "none"]),
    help="A name of the palette, or 'none'.",
)
@json_option
def folder_update(folder_id, title, color, as_json):
    """Rename FOLDER or give it a color"""
    body = {}
    if title is not None:
        body["title"] = title
    if color is not None:
        body["color"] = "" if color == "none" else color
    if not body:
        raise click.UsageError("Give --title or --color.")
    data = request("PATCH", f"folders/{folder_id}/", json=body)
    if as_json:
        return echo_json(data)
    click.echo(
        f"#{folder_id}: {data['folder']['title']}, {data['color_name'] or 'no color'}"
    )
    return None


ORDERINGS = ["alphabetical", "reverse", "newest", "oldest"]


@folders.command("order")
@click.argument("project", type=int)
@click.argument("ordering", type=click.Choice(ORDERINGS))
@click.option("--folder", "folder_id", type=int, help="This folder's contents.")
@json_option
def folder_order(project, ordering, folder_id, as_json):
    """Order the docs and files of PROJECT's top level, or of a folder, for
    everybody; folders come first (staff)"""
    if folder_id:
        data = request("PATCH", f"folders/{folder_id}/", json={"ordering": ordering})
    else:
        data = request(
            "PATCH", f"projects/{project}/files/", json={"ordering": ordering}
        )
    if as_json:
        return echo_json(data)
    click.echo(f"Order: {data['ordering']}")
    return None


@files.command("upload")
@click.argument("project", type=int)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--folder", "parent", type=int, help="Into this folder.")
@click.option("--description", default="", help="Markdown.")
@also_option
@visible_option
@json_option
def file_upload(project, path, parent, description, also, visible, as_json):
    """Upload the file at PATH to PROJECT's root or a folder"""
    if visible:
        click.secho("Clients can see this file.", fg="yellow", err=True)
    with click.open_file(path, "rb") as file:
        data = request(
            "POST",
            f"projects/{project}/files/",
            files={"file": (os.path.basename(path), file)},
            data={
                "description": description,
                "visible_to_clients": "true" if visible else "false",
                "also": ",".join(map(str, people_ids(also))),
                **({"parent_id": parent} if parent else {}),
            },
        )
    if as_json:
        return echo_json(data)
    click.echo(f"Uploaded #{data['id']} {data['name']}: {data['url']}")
    return None


@files.command("replace")
@click.argument("file_id", metavar="FILE", type=int)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@json_option
def file_replace(file_id, path, as_json):
    """Upload the file at PATH as a new version of FILE"""
    with click.open_file(path, "rb") as file:
        data = request(
            "POST",
            f"files/{file_id}/versions/",
            files={"file": (os.path.basename(path), file)},
        )
    if as_json:
        return echo_json(data)
    click.echo(f"Replaced #{file_id}: {len(data['versions'])} versions.")
    return None


@files.command("download")
@click.argument("file_id", metavar="FILE", type=int)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    help="Save as; the file's name by default.",
)
@click.option("--version", type=int, help="An older version's ID (staff).")
def file_download(file_id, output, version):
    """Download FILE, the current version unless --version says otherwise"""
    data = request("GET", f"files/{file_id}/")
    chosen = (
        next((v for v in data["versions"] if v["id"] == version), None)
        if version
        else data["versions"][0]
    )
    if chosen is None:
        terminate(f"File #{file_id} has no version #{version} for you.")
    target = output or chosen["name"]
    path = (
        f"files/{file_id}/download/"
        if chosen["is_current"]
        else f"files/{file_id}/versions/{chosen['id']}/download/"
    )
    download(path, target)
    click.echo(f"Saved {target} ({chosen['size']:,} B).")


@cli.group()
def docs():
    """Show, create and edit docs"""


@docs.command("show")
@click.argument("doc_id", metavar="DOC", type=int)
@click.option("--comments", is_flag=True, help="With the comments.")
@click.option("--version", type=int, help="An older version's ID (staff).")
@json_option
def doc_show(doc_id, comments, version, as_json):
    """Show DOC"""
    data = request("GET", f"docs/{doc_id}/")
    if version:
        old = request("GET", f"docs/{doc_id}/versions/{version}/")
        data |= {
            "title": old["title"],
            "content": old["content"],
            "version_id": version,
        }
    if comments:
        data["comments"] = paginate(f"items/{doc_id}/comments/")
    if as_json:
        return echo_json(data)
    marker = " [clients]" if data["visible_to_clients"] else ""
    echo_linked(f"#{data['id']} ", link(data["title"], data.get("url")), marker)
    if data["read_only"]:
        click.echo("Read-only.")
    click.echo(f"URL: {data['url']}")
    if data["content"]:
        click.echo(f"\n{data['content']}")
    for comment in data.get("comments", []):
        click.echo(f"\n{comment['author']['name']}, {comment['created_at'][:16]}:")
        click.echo(comment["content"])
    return None


@docs.command("create")
@click.argument("project", type=int)
@click.argument("title")
@click.argument("text", required=False)
@click.option("--folder", "parent", type=int, help="Inside this folder.")
@also_option
@visible_option
@attach_option
@json_option
def doc_new(project, title, text, parent, also, visible, attach, as_json):
    """Create a doc titled TITLE in PROJECT; TEXT (Markdown) or standard input

    TITLE becomes the first line of the doc, a heading before TEXT."""
    if text is None:
        text = click.get_text_stream("stdin").read()
    if visible:
        click.secho("Clients can see this doc.", fg="yellow", err=True)
    data = request(
        "POST",
        f"projects/{project}/docs/",
        json={
            "title": title,
            "content": with_attachments(project, text, attach),
            "parent_id": parent,
            "visible_to_clients": visible,
            "also": people_ids(also),
        },
    )
    if as_json:
        return echo_json(data)
    click.echo(f"Created #{data['id']}: {data['url']}")
    return None


@docs.command("update")
@click.argument("doc_id", metavar="DOC", type=int)
@click.option(
    "--new-version", is_flag=True, help="Make a version now, not only after 10 minutes."
)
@json_option
def doc_edit(doc_id, new_version, as_json):
    """Edit DOC in $EDITOR and save when you quit

    The doc's title is the first line of its text: change the heading to
    rename it.

    People editing the doc in the browser meanwhile see your changes
    arrive; saving over a newer version somebody else made meanwhile is
    refused."""
    doc = request("GET", f"docs/{doc_id}/")
    if doc["read_only"]:
        raise click.ClickException("The doc is read-only.")
    if doc["visible_to_clients"]:
        click.secho("Clients can see this doc.", fg="yellow", err=True)
    text = click.edit(doc["content"], extension=".md")
    if text is None or text == doc["content"]:
        click.echo("No changes.")
        return None
    changes = {
        "content": text,
        "new_version": new_version,
        "base_version": doc["version_id"],
    }
    data = request("PATCH", f"docs/{doc_id}/", json=changes)
    if as_json:
        return echo_json(data)
    click.echo(f"Saved #{doc_id}.")
    return None


@docs.command("read-only")
@click.argument("doc_id", metavar="DOC", type=int)
@click.option("--off", is_flag=True, help="Make it editable again.")
@json_option
def doc_read_only(doc_id, off, as_json):
    """Make DOC read-only for everybody, or editable again (staff)"""
    data = request("PATCH", f"docs/{doc_id}/", json={"read_only": not off})
    if as_json:
        return echo_json(data)
    click.echo(f"#{doc_id} is {'read-only' if data['read_only'] else 'editable'}.")
    return None
