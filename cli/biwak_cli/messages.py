"""Messages and forwarded mails"""

import click

from biwak_cli.core import (
    also_option,
    attach_option,
    cli,
    clients,
    console,
    echo_json,
    json_option,
    need,
    paginate,
    people_ids,
    request,
    table,
    terminate,
    visible_option,
    with_attachments,
)


# Messages -------------------------------------------------------------------


def category_id(name):
    """The ID of a category given by name or ID"""
    if name is None:
        return None
    categories = request("GET", "message-categories/")
    for category in categories:
        if name in {str(category["id"]), category["name"]}:
            return category["id"]
    terminate(
        f"No category {name!r}. There are: "
        + ", ".join(c["name"] for c in categories)
        + "."
    )
    return None


@cli.group(invoke_without_command=True)
@click.option("--project", type=int, help="The project's ID.")
@click.option("--limit", default=25, show_default=True, help="At most this many.")
@click.option(
    "--order",
    type=click.Choice(["latest", "newest"]),
    help="Latest update (posting or comment) or newest posts first (default: "
    "the board's order).",
)
@json_option
@click.pass_context
def messages(ctx, project, limit, order, as_json):
    """Messages; without a command the message board of --project: pinned
    first, then in the board's order"""
    if ctx.invoked_subcommand is not None:
        return None
    need(project, "--project")
    params = {"page_size": limit} | ({"order": order} if order else {})
    data = request("GET", f"projects/{project}/messages/", params=params)
    if as_json:
        return echo_json(data)
    t = table("ID", "", "Category", "Message", "By", "Date", "Comments", "")
    for message in data["results"]:
        category = message["category"]
        t.add_row(
            str(message["id"]),
            "pinned" if message["pinned"] else "",
            f"{category['emoji']} {category['name']}".strip() if category else "",
            message["title"],
            message["creator"]["short_name"],
            message["created_at"][:10],
            str(message["comment_count"]),
            clients(message),
        )
    console.print(t)
    return None


def show_message(data):
    marker = " [clients]" if data["visible_to_clients"] else ""
    pinned = " (pinned)" if data["pinned"] else ""
    click.echo(f"#{data['id']} {data['title']}{pinned}{marker}")
    category = data["category"]
    for label, value in [
        (
            "Category",
            f"{category['emoji']} {category['name']}".strip() if category else "",
        ),
        ("By", data["creator"]["name"]),
        ("Date", data["created_at"][:16].replace("T", " ")),
        ("URL", data["url"]),
    ]:
        if value:
            click.echo(f"{label}: {value}")
    if data["content"]:
        click.echo(f"\n{data['content']}")


@messages.command("show")
@click.argument("message_id", metavar="MESSAGE", type=int)
@click.option("--comments", is_flag=True, help="With the comments.")
@json_option
def message_show(message_id, comments, as_json):
    """Show MESSAGE"""
    data = request("GET", f"messages/{message_id}/")
    if comments:
        data["comments"] = paginate(f"items/{message_id}/comments/")
    if as_json:
        return echo_json(data)
    show_message(data)
    for comment in data.get("comments", []):
        click.echo(f"\n{comment['author']['name']}, {comment['created_at'][:16]}:")
        click.echo(comment["content"])
    return None


@messages.command("create")
@click.argument("project", type=int)
@click.argument("title")
@click.argument("text", required=False)
@click.option("--category", help="A category's name or ID.")
@also_option
@visible_option
@attach_option
@json_option
def message_post(project, title, text, category, also, visible, attach, as_json):
    """Post a message titled TITLE to PROJECT; TEXT (Markdown) or standard input"""
    if text is None:
        text = click.get_text_stream("stdin").read()
    if visible:
        click.secho("Clients can see this message.", fg="yellow", err=True)
    data = request(
        "POST",
        f"projects/{project}/messages/",
        json={
            "title": title,
            "content": with_attachments(project, text, attach),
            "category_id": category_id(category),
            "visible_to_clients": visible,
            "also": people_ids(also),
        },
    )
    if as_json:
        return echo_json(data)
    click.echo(f"Posted #{data['id']}: {data['url']}")
    return None


@messages.command("pin")
@click.argument("message_id", metavar="MESSAGE", type=int)
@click.option("--undo", is_flag=True, help="Unpin it again.")
@json_option
def message_pin(message_id, undo, as_json):
    """Pin MESSAGE for everybody (staff); it tells nobody"""
    data = request("DELETE" if undo else "PUT", f"messages/{message_id}/pin/")
    if as_json:
        return echo_json(data)
    click.echo(f"{'Unpinned' if undo else 'Pinned'} #{message_id}.")
    return None


# Forwarded mails --------------------------------------------------------------


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def forwarded(ctx, as_json):
    """Your forwarded mails, newest first (staff): `biwak forwarded file ID`
    files one as a message or a to-do, `biwak forwarded delete ID` deletes
    one; unfiled ones are deleted after 30 days"""
    if ctx.invoked_subcommand is not None:
        return None
    data = paginate("forwarded/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Subject", "From", "Sent", "Files")
    for mail in data:
        sender = mail["sender"]
        t.add_row(
            str(mail["id"]),
            mail["subject"],
            f"{sender['name']} <{sender['email']}>"
            if sender["email"]
            else sender["name"],
            mail["sent_on"] or "",
            str(len(mail["files"])),
        )
    console.print(t)
    return None


@forwarded.command("file")
@click.argument("forwarded_id", type=int)
@click.option("--message", "project", type=int, help="As a message in this project.")
@click.option("--category", type=int, help="The message's category.")
@click.option("--todo", "todolist", type=int, help="As a to-do in this list.")
@click.option("--group", type=int, help="The to-do's group in the list.")
@click.option("--title", help="Instead of the mail's subject.")
@json_option
def forwarded_file(forwarded_id, project, category, todolist, group, title, as_json):
    """File the forwarded mail FORWARDED_ID as an internal message
    (--message PROJECT) or as a to-do in a list (--todo LIST; clients
    see it, its text and files when they see the list); it leaves your
    forwarded mails"""
    if (project is None) == (todolist is None):
        terminate("Give --message PROJECT or --todo LIST.")
    if project is not None:
        payload = {"kind": "message", "project_id": project, "category_id": category}
    else:
        payload = {"kind": "todo", "list_id": todolist, "group_id": group}
    if title:
        payload["title"] = title
    data = request("POST", f"forwarded/{forwarded_id}/file/", json=payload)
    if as_json:
        return echo_json(data)
    click.echo(f"Filed as #{data['id']} {data['title']}")
    click.echo(data["url"])
    return None


@forwarded.command("delete")
@click.argument("forwarded_id", type=int)
def forwarded_delete(forwarded_id):
    """Delete the forwarded mail FORWARDED_ID with its files"""
    request("DELETE", f"forwarded/{forwarded_id}/")
    click.echo(f"Deleted the forwarded mail {forwarded_id}.")
