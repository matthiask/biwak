"""The commands; output for people by default, --json for scripts"""

import os
from urllib.parse import parse_qs, urlsplit

import click
from rich.console import Console
from rich.table import Table

from biwak_cli.core import (
    _send,
    base_url,
    browser_login,
    cli,
    current,
    download,
    echo_json,
    read_config,
    request,
    save_login,
    terminate,
    write_config,
)


console = Console(markup=False, highlight=False)

json_option = click.option("--json", "as_json", is_flag=True, help="Output JSON.")


def clients(item):
    """The marker on everything clients can see (specs/access.md)"""
    return "[clients]" if item.get("visible_to_clients") else ""


def names(people):
    return ", ".join(p["short_name"] for p in people)


attach_option = click.option(
    "--attach",
    "attach",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False),
    help="A file to attach (at most 100 MB), repeatable; appended to the text.",
)


def with_attachments(project_id, text, paths):
    """Uploads the files to the project and appends their Markdown to the
    text; saving the text links them to the item"""
    if not paths:
        return text
    inserted = []
    for path in paths:
        with click.open_file(path, "rb") as file:
            data = request(
                "POST",
                f"projects/{project_id}/attachments/",
                files={"file": (os.path.basename(path), file)},
            )
        inserted.append(data["markdown"])
    return "\n\n".join(part for part in [text.rstrip(), *inserted] if part)


def table(*columns):
    t = Table(box=None, pad_edge=False, header_style="bold")
    for column in columns:
        t.add_column(column)
    return t


# Logging in -----------------------------------------------------------------


@cli.command()
@click.argument("url", required=False)
@click.option("--read", "access", flag_value="read", help="biwak may only read.")
@click.option("--write", "access", flag_value="write", help="biwak may read and write.")
@click.option(
    "--token",
    "paste_token",
    is_flag=True,
    help="Paste a token from the API tokens page (computers without a browser).",
)
def login(url, access, paste_token):
    """Authorize biwak in your name through the browser"""
    if not (url := base_url(url or read_config().get("url"))):
        terminate("Which Biwak? Run `biwak login URL --read` or `--write`.")
    if paste_token:
        save_login(url, click.prompt("API token", hide_input=True).strip())
    elif not access:
        terminate("Choose the access: `biwak login --read` or `--write`.")
    else:
        browser_login(url, access)
    me = request("GET", "me/")
    click.echo(f"Logged in as {me['name']} ({me['access']}).")


@cli.command()
def logout():
    """Revoke biwak's token and forget it"""
    url, token = current()
    response = _send("DELETE", url, "tokens/current/", token)
    config = read_config()
    write_config({"url": config.get("url")})
    if response.status_code in {200, 401}:
        click.echo(f"Logged out from {url}.")
    else:
        terminate("Forgot the token, but couldn't revoke it: see the API tokens page.")


@cli.command()
@json_option
def me(as_json):
    """Who you are and the token's access"""
    data = request("GET", "me/")
    if as_json:
        return echo_json(data)
    kind = "client" if data["is_client"] else "staff"
    click.echo(f"{data['name']} <{data['email']}>, {kind}, {data['access']} access")
    return None


# Projects and lists ---------------------------------------------------------


@cli.command()
@json_option
@click.option("--archived", is_flag=True, help="Archived projects instead.")
@click.option(
    "--order",
    type=click.Choice(["activity", "name"]),
    help="Latest activity first or by name (default: your setting on the web).",
)
def projects(as_json, archived, order):
    """The projects you can open, bookmarked ones (*) first, with the latest
    activity (for clients: of what they see)"""
    params = {"archived": archived}
    if order:
        params["order"] = order
    data = request("GET", "projects/", params=params)
    if as_json:
        return echo_json(data)
    t = table("", "ID", "Project", "Last activity", "")
    for p in data:
        t.add_row(
            "*" if p["is_bookmarked"] else "",
            str(p["id"]),
            p["name"],
            (p["last_activity_at"] or "")[:16].replace("T", " "),
            "" if p["is_all_access"] else "limited",
        )
    console.print(t)
    return None


NOTIFY_WORDS = {
    "default": "notified by default",
    "tagged": "only when tagged",
    "nothing": "no mails",
}

only_tagged_option = click.option(
    "--only-tagged",
    is_flag=True,
    help="Notify them only when tagged (default: notified by default).",
)


def show_member(person):
    click.echo(f"{person['name']} ({person['id']}): {notify_word(person)}")


def notify_word(person):
    return NOTIFY_WORDS.get(person["notify"], "") if person["notify"] else ""


@cli.command()
@click.argument("project", type=int)
@json_option
def members(project, as_json):
    """The people in PROJECT; staff see addresses and how each is notified
    (notified by default, only when tagged, no mails), clients only their own"""
    data = request("GET", f"projects/{project}/members/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Name", "Email", "Notified", "")
    for person in data:
        t.add_row(
            str(person["id"]),
            person["name"],
            person["email"] or "",
            notify_word(person),
            "client" if person["is_client"] else "",
        )
    console.print(t)
    return None


@cli.group()
def member():
    """Add and invite people to a project (staff)"""


@member.command("add")
@click.argument("project", type=int)
@click.argument("person", type=int)
@only_tagged_option
@json_option
def member_add(project, person, only_tagged, as_json):
    """Add the person with ID PERSON to PROJECT"""
    data = request(
        "POST",
        f"projects/{project}/members/",
        json={"person_id": person, "notify": "tagged" if only_tagged else "default"},
    )
    if as_json:
        return echo_json(data)
    click.echo("Added: ", nl=False)
    show_member(data)
    return None


@member.command("invite")
@click.argument("project", type=int)
@click.argument("email")
@click.option("--name", default="", help="Their name, for new people.")
@click.option("--organization", default="", help="A client's organization.")
@click.option("--staff", is_flag=True, help="Staff instead of a client (admins).")
@only_tagged_option
@json_option
def member_invite(project, email, name, organization, staff, only_tagged, as_json):
    """Add the person with this address to PROJECT, creating them (as a
    client) and mailing them how to log in if they're new"""
    data = request(
        "POST",
        f"projects/{project}/members/invite/",
        json={
            "email": email,
            "name": name,
            "organization": organization,
            "is_client": not staff,
            "notify": "tagged" if only_tagged else "default",
        },
    )
    if as_json:
        return echo_json(data)
    click.echo("Invited: ", nl=False)
    show_member(data)
    return None


@cli.command()
@click.argument("project", type=int)
@json_option
def lists(project, as_json):
    """The to-do lists of PROJECT"""
    data = request("GET", f"projects/{project}/lists/")
    if as_json:
        return echo_json(data)
    t = table("ID", "List", "")
    for item in data:
        t.add_row(str(item["id"]), item["title"], clients(item))
    console.print(t)
    return None


@cli.command()
@click.argument("list_id", metavar="LIST", type=int, required=False)
@click.option("--completed", is_flag=True, help="Completed to-dos, latest first.")
@click.option("--mine", is_flag=True, help="Only to-dos assigned to you.")
@click.option("--project", "project_id", type=int, help="Only this project's ID.")
@click.option(
    "--due",
    type=click.Choice(["overdue", "today", "this_week", "later", "none"]),
    help="Only to-dos in this group by due date.",
)
@json_option
def todos(list_id, completed, mine, project_id, due, as_json):
    """The open to-dos of LIST, by group; without LIST across all projects by
    due date (--mine, --project, --due)"""
    if list_id and (mine or project_id or due):
        terminate("--mine, --project and --due go without LIST.")
    if list_id and completed:
        data = request("GET", f"lists/{list_id}/todos/completed/")["results"]
    elif list_id:
        data = request("GET", f"lists/{list_id}/todos/")
    else:
        params = {"completed": completed, "page_size": 200}
        if mine:
            params["assignee"] = "me"
        if project_id:
            params["project_id"] = project_id
        if due:
            params["due_group"] = due
        data = request("GET", "todos/", params=params)["results"]
    if as_json:
        return echo_json(data)
    t = table(
        "ID", "To-do", "Project" if not list_id else "Group", "Assignees", "Due", ""
    )
    for todo in data:
        t.add_row(
            str(todo["id"]),
            todo["title"],
            f"{todo['project_name']} / {todo['list_title']}"
            if "project_name" in todo
            else (todo["group"] or {}).get("title", ""),
            names(todo["assignees"]),
            todo["due_on"] or "",
            clients(todo),
        )
    console.print(t)
    return None


# One to-do ------------------------------------------------------------------


repeat_option = click.option(
    "--repeat",
    metavar="RULE",
    help=(
        "Repeat when completed: weekdays, weekly, biweekly, monthly, "
        "monthly-first, monthly-last, quarterly, yearly (counting from the "
        "due date) or an RRULE like FREQ=WEEKLY;BYDAY=MO,TH; 'none' removes it."
    ),
)


@cli.group()
def todo():
    """Show, add, change, complete and comment on to-dos"""


def show_reactions(reactions):
    """``👍 2 (Ada, Bob), Thanks! 1 (Cleo)``, yours marked with *"""
    return ", ".join(
        f"{r['content']} {r['count']}{'*' if r['mine'] else ''} ({names(r['people'])})"
        for r in reactions
    )


def show_todo(data):
    marker = " [clients]" if data["visible_to_clients"] else ""
    done = " (completed)" if data["completed_at"] else ""
    click.echo(f"#{data['id']} {data['title']}{done}{marker}")
    for label, value in [
        ("Group", (data["group"] or {}).get("title")),
        ("Assignees", names(data["assignees"])),
        ("Due", data["due_on"]),
        ("Repeats", data.get("recurrence_description")),
        ("Repeats until", data.get("recurrence_ends_on")),
        ("Reactions", show_reactions(data.get("reactions", []))),
        ("URL", data["url"]),
    ]:
        if value:
            click.echo(f"{label}: {value}")
    if data["notes"]:
        click.echo(f"\n{data['notes']}")


@todo.command("show")
@click.argument("todo_id", metavar="TODO", type=int)
@click.option("--comments", is_flag=True, help="With the comments.")
@json_option
def todo_show(todo_id, comments, as_json):
    """Show TODO"""
    data = request("GET", f"todos/{todo_id}/")
    if comments:
        data["comments"] = request("GET", f"items/{todo_id}/comments/")["results"]
    if as_json:
        return echo_json(data)
    show_todo(data)
    for comment in data.get("comments", []):
        click.echo(f"\n{comment['author']['name']}, {comment['created_at'][:16]}:")
        click.echo(comment["content"])
        if comment.get("reactions"):
            click.echo(f"Reactions: {show_reactions(comment['reactions'])}")
    return None


@todo.command("add")
@click.argument("list_id", metavar="LIST", type=int)
@click.argument("title")
@click.option("--notes", default="", help="Markdown.")
@click.option("--due", help="YYYY-MM-DD.")
@click.option("--assign", multiple=True, type=int, help="A person's ID, repeatable.")
@click.option("--group", type=int, help="The group's ID.")
@attach_option
@repeat_option
@json_option
def todo_add(list_id, title, notes, due, assign, group, attach, repeat, as_json):
    """Add a to-do titled TITLE to LIST"""
    if attach:
        project_id = request("GET", f"lists/{list_id}/")["project_id"]
        notes = with_attachments(project_id, notes, attach)
    data = request(
        "POST",
        f"lists/{list_id}/todos/",
        json={
            "title": title,
            "notes": notes,
            "due_on": due,
            "assignees": list(assign),
            "group_id": group,
            **({"recurrence": repeat} if repeat else {}),
        },
    )
    if as_json:
        return echo_json(data)
    show_todo(data)
    return None


@todo.command("edit")
@click.argument("todo_id", metavar="TODO", type=int)
@click.option("--title")
@click.option("--notes", help="Markdown, replaces the notes.")
@click.option("--due", help="YYYY-MM-DD, or 'none' to remove it.")
@click.option(
    "--assign",
    multiple=True,
    type=int,
    help="Replaces the assignees, repeatable; --assign 0 removes all.",
)
@attach_option
@repeat_option
@json_option
def todo_edit(todo_id, title, notes, due, assign, attach, repeat, as_json):
    """Change TODO; --attach appends to the notes (or to --notes)"""
    changes = {}
    if title is not None:
        changes["title"] = title
    if notes is not None:
        changes["notes"] = notes
    if attach:
        current = request("GET", f"todos/{todo_id}/")
        changes["notes"] = with_attachments(
            current["project_id"],
            current["notes"] if notes is None else notes,
            attach,
        )
    if due is not None:
        changes["due_on"] = None if due == "none" else due
    if assign:
        changes["assignees"] = [pk for pk in assign if pk]
    if repeat is not None:
        changes["recurrence"] = "" if repeat == "none" else repeat
    if not changes:
        terminate("Nothing to change.")
    data = request("PATCH", f"todos/{todo_id}/", json=changes)
    if as_json:
        return echo_json(data)
    show_todo(data)
    return None


@todo.command("done")
@click.argument("todo_id", metavar="TODO", type=int)
@json_option
def todo_done(todo_id, as_json):
    """Complete TODO"""
    data = request("POST", f"todos/{todo_id}/complete/")
    if as_json:
        return echo_json(data)
    click.echo(f"Completed #{data['id']} {data['title']}.")
    return None


@todo.command("reopen")
@click.argument("todo_id", metavar="TODO", type=int)
@json_option
def todo_reopen(todo_id, as_json):
    """Reopen TODO"""
    data = request("POST", f"todos/{todo_id}/reopen/")
    if as_json:
        return echo_json(data)
    click.echo(f"Reopened #{data['id']} {data['title']}.")
    return None


@todo.command("comment")
@click.argument("todo_id", metavar="TODO", type=int)
@click.argument("text", required=False)
@attach_option
@json_option
def todo_comment(todo_id, text, attach, as_json):
    """Comment on TODO; TEXT (Markdown) or standard input"""
    if text is None:
        text = click.get_text_stream("stdin").read()
    item = request("GET", f"todos/{todo_id}/")
    if item["visible_to_clients"]:
        click.secho("Clients can see this comment.", fg="yellow", err=True)
    text = with_attachments(item["project_id"], text, attach)
    data = request("POST", f"items/{todo_id}/comments/", json={"content": text})
    if as_json:
        return echo_json(data)
    click.echo(f"Commented on #{todo_id}.")
    return None


@cli.command()
@click.argument("todo_id", metavar="TODO", type=int)
@click.argument("content")
@click.option(
    "--comment", "comment_id", type=int, help="React to this comment ID instead."
)
@json_option
def react(todo_id, content, comment_id, as_json):
    """React to TODO (or a comment) with CONTENT: an emoji or at most 40
    characters. The same again removes your reaction."""
    path = (
        f"comments/{comment_id}/reactions/"
        if comment_id
        else f"items/{todo_id}/reactions/"
    )
    mine = any(r["mine"] and r["content"] == content for r in request("GET", path))
    method = "DELETE" if mine else "POST"
    reactions = request(method, path, json={"content": content})
    if as_json:
        return echo_json(reactions)
    click.echo(
        f"{'Removed your' if mine else 'Reacted with'} {content}"
        f"{' on comment ' + str(comment_id) if comment_id else f' on #{todo_id}'}."
    )
    return None


# Check-ins ------------------------------------------------------------------


@cli.command()
@click.argument("project", type=int)
@json_option
def checkins(project, as_json):
    """The check-in questions of PROJECT with their schedules"""
    data = request("GET", f"projects/{project}/checkins/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Question", "Asked", "Next", "")
    for question in data:
        asked = f"{question['schedule_description']}, {question['time_of_day'][:5]}"
        t.add_row(
            str(question["id"]),
            question["title"],
            f"{asked} {question['time_zone']}",
            "paused"
            if question["paused"]
            else (question["next_at"] or "")[:16].replace("T", " "),
            clients(question),
        )
    console.print(t)
    return None


@cli.group()
def checkin():
    """Show, answer and set up check-in questions"""


def show_answers(occurrence):
    click.echo(f"\n{occurrence['date']} (#{occurrence['id']})")
    for answer in occurrence["answers"]:
        click.echo(f"\n{answer['author']['name']}:")
        click.echo(answer["content"])
    if occurrence["missing"]:
        click.echo(f"\nHasn't answered yet: {names(occurrence['missing'])}")


@checkin.command("show")
@click.argument("question_id", metavar="QUESTION", type=int)
@click.option(
    "--limit", default=1, show_default=True, help="How many occurrences, latest first."
)
@json_option
def checkin_show(question_id, limit, as_json):
    """Show QUESTION with the answers of its latest occurrences"""
    data = request("GET", f"checkins/{question_id}/")
    occurrences = request(
        "GET", f"checkins/{question_id}/occurrences/", params={"page_size": limit}
    )["results"][:limit]
    if as_json:
        return echo_json(data | {"occurrences": occurrences})
    marker = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"#{data['id']} {data['title']}{marker}")
    for label, value in [
        ("Asked", f"{data['schedule_description']}, {data['time_of_day'][:5]}"),
        ("Time zone", data["time_zone"]),
        ("People", names(data["people"])),
        ("Mails about answers", data["mail"]),
        ("Paused", "yes" if data["paused"] else ""),
        ("URL", data["url"]),
    ]:
        if value:
            click.echo(f"{label}: {value}")
    for occurrence in occurrences:
        show_answers(occurrence)
    return None


@checkin.command("answer")
@click.argument("question_id", metavar="QUESTION", type=int)
@click.argument("text", required=False)
@click.option(
    "--occurrence", type=int, help="An older occurrence's ID (default: the latest)."
)
@attach_option
@json_option
def checkin_answer(question_id, text, occurrence, attach, as_json):
    """Answer QUESTION (or change your answer); TEXT (Markdown) or standard
    input"""
    if text is None:
        text = click.get_text_stream("stdin").read()
    question = request("GET", f"checkins/{question_id}/")
    if question["visible_to_clients"]:
        click.secho("Clients can see this answer.", fg="yellow", err=True)
    text = with_attachments(question["project_id"], text, attach)
    data = request(
        "POST",
        f"checkins/{question_id}/answer/",
        json={"content": text, "occurrence_id": occurrence},
    )
    if as_json:
        return echo_json(data)
    click.echo(f"Answered #{question_id} (occurrence #{data['occurrence_id']}).")
    return None


@checkin.command("due")
@click.option("--project", type=int, help="Only this project's ID.")
@json_option
def checkin_due(project, as_json):
    """The questions you haven't answered yet (the latest time they were asked)"""
    data = request(
        "GET", "me/checkins/due/", params={"project_id": project} if project else None
    )
    if as_json:
        return echo_json(data)
    t = table("ID", "Question", "Project", "Asked", "Occurrence", "")
    for due in data:
        t.add_row(
            str(due["question_id"]),
            due["title"],
            due["project_name"],
            due["date"],
            str(due["occurrence_id"]),
            clients(due),
        )
    console.print(t)
    return None


@checkin.command("add")
@click.argument("project", type=int)
@click.argument("title")
@click.option(
    "--schedule",
    required=True,
    metavar="RULE",
    help=(
        "weekdays, weekly, biweekly, monthly, monthly-first, monthly-last, "
        "quarterly, yearly (counting from --from) or an RRULE (at most daily)."
    ),
)
@click.option("--time", "time_of_day", required=True, help="HH:MM.")
@click.option("--zone", help="The time zone (default: the installation's).")
@click.option(
    "--from", "starts_on", help="YYYY-MM-DD, the first date (default: today)."
)
@click.option("--people", multiple=True, type=int, help="A person's ID, repeatable.")
@click.option(
    "--clients", is_flag=True, help="Visible to clients (internal otherwise)."
)
@json_option
def checkin_add(
    project,
    title,
    schedule,
    time_of_day,
    zone,
    starts_on,
    people,
    clients,
    as_json,
):
    """Add the question TITLE to PROJECT (staff)"""
    body = {
        "title": title,
        "schedule": schedule,
        "time_of_day": time_of_day,
        "people": list(people),
        "visible_to_clients": clients,
    }
    if zone:
        body["time_zone"] = zone
    if starts_on:
        body["starts_on"] = starts_on
    data = request("POST", f"projects/{project}/checkins/", json=body)
    if as_json:
        return echo_json(data)
    click.echo(f"Added #{data['id']} {data['title']}.")
    return None


@checkin.command("pause")
@click.argument("question_id", metavar="QUESTION", type=int)
@json_option
def checkin_pause(question_id, as_json):
    """Stop asking QUESTION (staff)"""
    data = request("PATCH", f"checkins/{question_id}/", json={"paused": True})
    if as_json:
        return echo_json(data)
    click.echo(f"Paused #{question_id}.")
    return None


@checkin.command("resume")
@click.argument("question_id", metavar="QUESTION", type=int)
@json_option
def checkin_resume(question_id, as_json):
    """Ask QUESTION again from the next date; what was missed isn't asked (staff)"""
    data = request("PATCH", f"checkins/{question_id}/", json={"paused": False})
    if as_json:
        return echo_json(data)
    click.echo(f"Resumed #{question_id}, next: {(data['next_at'] or '')[:16]}.")
    return None


@checkin.command("mail")
@click.argument("question_id", metavar="QUESTION", type=int)
@click.argument("mode", type=click.Choice(["each", "summary", "none"]), required=False)
@json_option
def checkin_mail(question_id, mode, as_json):
    """Show or set how you hear about the answers: a mail each, a summary the
    morning after (the default) or none"""
    path = f"checkins/{question_id}/mail/"
    data = request("PUT", path, json={"mode": mode}) if mode else request("GET", path)
    if as_json:
        return echo_json(data)
    click.echo(f"Mails about answers: {data['mode']}")
    return None


# Messages -------------------------------------------------------------------

notify_option = click.option(
    "--notify",
    default="everybody",
    show_default=True,
    metavar="WHOM",
    help="Whom to tell: everybody (in the project), nobody, or people's IDs"
    " separated by commas.",
)
visible_option = click.option(
    "--visible", is_flag=True, help="Visible to clients (staff; clients always are)."
)


def whom(value):
    """``everybody``, ``nobody`` or the IDs as a list"""
    if value in {"everybody", "nobody"}:
        return value
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError:
        terminate("--notify is everybody, nobody or people's IDs separated by commas.")


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


@cli.command()
@click.argument("project", type=int)
@click.option("--limit", default=25, show_default=True, help="At most this many.")
@json_option
def messages(project, limit, as_json):
    """The message board of PROJECT: pinned first, then the newest"""
    data = request("GET", f"projects/{project}/messages/", params={"page_size": limit})
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


@cli.group()
def message():
    """Show, post and pin messages"""


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


@message.command("show")
@click.argument("message_id", metavar="MESSAGE", type=int)
@click.option("--comments", is_flag=True, help="With the comments.")
@json_option
def message_show(message_id, comments, as_json):
    """Show MESSAGE"""
    data = request("GET", f"messages/{message_id}/")
    if comments:
        data["comments"] = request("GET", f"items/{message_id}/comments/")["results"]
    if as_json:
        return echo_json(data)
    show_message(data)
    for comment in data.get("comments", []):
        click.echo(f"\n{comment['author']['name']}, {comment['created_at'][:16]}:")
        click.echo(comment["content"])
    return None


@message.command("post")
@click.argument("project", type=int)
@click.argument("title")
@click.argument("text", required=False)
@click.option("--category", help="A category's name or ID.")
@notify_option
@visible_option
@attach_option
@json_option
def message_post(project, title, text, category, notify, visible, attach, as_json):
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
            "notify": whom(notify),
        },
    )
    if as_json:
        return echo_json(data)
    click.echo(f"Posted #{data['id']}: {data['url']}")
    return None


@message.command("pin")
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


# Docs and files -------------------------------------------------------------


@cli.command()
@click.argument("project", type=int)
@click.argument("folder", type=int, required=False)
@json_option
def files(project, folder, as_json):
    """The docs and files of PROJECT's root, or of FOLDER"""
    data = request(
        "GET",
        f"projects/{project}/files/",
        params={"folder_id": folder} if folder else None,
    )
    if as_json:
        return echo_json(data)
    if data["breadcrumbs"]:
        click.echo("/ " + " / ".join(c["title"] for c in data["breadcrumbs"]))
    t = table("ID", "Kind", "Name", "Size", "")
    for entry in data["entries"]:
        t.add_row(
            str(entry["id"]),
            entry["kind"],
            entry["title"],
            f"{entry['size']:,} B" if entry["size"] is not None else "",
            clients(entry),
        )
    console.print(t)
    return None


@cli.group()
def folder():
    """Create folders and move docs and files"""


@folder.command("new")
@click.argument("project", type=int)
@click.argument("title")
@click.option("--folder", "parent", type=int, help="Inside this folder.")
@visible_option
@json_option
def folder_new(project, title, parent, visible, as_json):
    """Create a folder titled TITLE in PROJECT"""
    data = request(
        "POST",
        f"projects/{project}/folders/",
        json={"title": title, "parent_id": parent, "visible_to_clients": visible},
    )
    if as_json:
        return echo_json(data)
    click.echo(f"Created #{data['id']}: {data['url']}")
    return None


@folder.command("move")
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


@cli.group("file")
def file_group():
    """Upload, replace and download files"""


@file_group.command("upload")
@click.argument("project", type=int)
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--folder", "parent", type=int, help="Into this folder.")
@click.option("--description", default="", help="Markdown.")
@notify_option
@visible_option
@json_option
def file_upload(project, path, parent, description, notify, visible, as_json):
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
                "notify": notify,
                **({"parent_id": parent} if parent else {}),
            },
        )
    if as_json:
        return echo_json(data)
    click.echo(f"Uploaded #{data['id']} {data['name']}: {data['url']}")
    return None


@file_group.command("replace")
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


@file_group.command("download")
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
def doc():
    """Show, create and edit docs"""


@doc.command("show")
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
        data["comments"] = request("GET", f"items/{doc_id}/comments/")["results"]
    if as_json:
        return echo_json(data)
    marker = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"#{data['id']} {data['title']}{marker}")
    if data["locked_by"]:
        click.echo(f"Being edited by {data['locked_by']['name']}.")
    click.echo(f"URL: {data['url']}")
    if data["content"]:
        click.echo(f"\n{data['content']}")
    for comment in data.get("comments", []):
        click.echo(f"\n{comment['author']['name']}, {comment['created_at'][:16]}:")
        click.echo(comment["content"])
    return None


@doc.command("new")
@click.argument("project", type=int)
@click.argument("title")
@click.argument("text", required=False)
@click.option("--folder", "parent", type=int, help="Inside this folder.")
@notify_option
@visible_option
@attach_option
@json_option
def doc_new(project, title, text, parent, notify, visible, attach, as_json):
    """Create a doc titled TITLE in PROJECT; TEXT (Markdown) or standard input"""
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
            "notify": whom(notify),
        },
    )
    if as_json:
        return echo_json(data)
    click.echo(f"Created #{data['id']}: {data['url']}")
    return None


@doc.command("edit")
@click.argument("doc_id", metavar="DOC", type=int)
@click.option("--title", help="Rename the doc too.")
@click.option(
    "--new-version", is_flag=True, help="Make a version now, not only after 10 minutes."
)
@json_option
def doc_edit(doc_id, title, new_version, as_json):
    """Edit DOC in $EDITOR and save when you quit

    Takes the doc's lock while you edit, and refuses to save over a newer
    version somebody else made meanwhile."""
    doc = request("PUT", f"docs/{doc_id}/lock/")
    if doc["visible_to_clients"]:
        click.secho("Clients can see this doc.", fg="yellow", err=True)
    text = click.edit(doc["content"], extension=".md")
    if text is None or (text == doc["content"] and not title):
        request("DELETE", f"docs/{doc_id}/lock/")
        click.echo("No changes.")
        return None
    changes = {
        "content": text,
        "new_version": new_version,
        "base_version": doc["version_id"],
    }
    if title:
        changes["title"] = title
    try:
        data = request("PATCH", f"docs/{doc_id}/", json=changes)
    except SystemExit:
        # The lock is ours still, give it up
        request("DELETE", f"docs/{doc_id}/lock/")
        raise
    if as_json:
        return echo_json(data)
    click.echo(f"Saved #{doc_id}.")
    return None


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
    params["page_size"] = min(limit, 200)
    events = []
    while len(events) < limit:
        data = request("GET", "feed/", params=params)
        events += data["results"]
        if not data["next"]:
            break
        # "next" is the URL of the next page
        params["cursor"] = parse_qs(urlsplit(data["next"]).query)["cursor"][0]
    events = events[:limit]
    if as_json:
        return echo_json(events)
    t = table("When", "Person", "Action", "What", "Project", "")
    for event in events:
        item = event["item"] or {}
        t.add_row(
            event["created_at"][:16].replace("T", " "),
            event["actor"]["short_name"],
            event["action"].replace("_", " "),
            item.get("title")
            or event["data"].get("title")
            or event["data"].get("name")
            or "",
            str(event["project_id"]),
            clients(event),
        )
    console.print(t)
    return None


# Bookmarks and links --------------------------------------------------------


@cli.command()
@json_option
def bookmarks(as_json):
    """Your bookmarks, newest first"""
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


@cli.group()
def bookmark():
    """Bookmark or un-bookmark an item or a project"""


@bookmark.command("add")
@click.argument("target", type=int)
@click.option("--project", "is_project", is_flag=True, help="TARGET is a project.")
def bookmark_add(target, is_project):
    """Bookmark the item (or, with --project, the project) TARGET"""
    request("PUT", f"{'projects' if is_project else 'items'}/{target}/bookmark/")
    click.echo(f"Bookmarked #{target}.")


@bookmark.command("remove")
@click.argument("target", type=int)
@click.option("--project", "is_project", is_flag=True, help="TARGET is a project.")
def bookmark_remove(target, is_project):
    """Remove the bookmark of the item (or, with --project, the project) TARGET"""
    request("DELETE", f"{'projects' if is_project else 'items'}/{target}/bookmark/")
    click.echo(f"Removed the bookmark of #{target}.")


@cli.command()
@click.argument("project", type=int)
@json_option
def links(project, as_json):
    """The links to outside tools of PROJECT and its items"""
    data = request("GET", f"projects/{project}/links/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Title", "Kind", "URL", "On item", "")
    for link in data:
        t.add_row(
            str(link["id"]),
            link["title"],
            link["kind"],
            link["url"],
            str(link["item_id"] or ""),
            clients(link),
        )
    console.print(t)
    return None


@cli.group()
def link():
    """Add and delete links to outside tools"""


@link.command("add")
@click.argument("project", type=int)
@click.argument("url")
@click.option("--title", default="", help="The host if left out.")
@click.option("--item", type=int, help="On this item instead of the project.")
@click.option(
    "--clients", is_flag=True, help="Visible to clients (internal otherwise)."
)
@json_option
def link_add(project, url, title, item, clients, as_json):
    """Add URL to PROJECT, or to --item of it"""
    body = {"url": url, "title": title, "visible_to_clients": clients}
    path = f"items/{item}/links/" if item else f"projects/{project}/links/"
    data = request("POST", path, json=body)
    if as_json:
        return echo_json(data)
    click.echo(f"Added link #{data['id']} ({data['kind']}).")
    return None


@link.command("delete")
@click.argument("link_id", metavar="LINK", type=int)
def link_delete(link_id):
    """Delete LINK"""
    request("DELETE", f"links/{link_id}/")
    click.echo(f"Deleted link #{link_id}.")


# Notifications --------------------------------------------------------------

LEVELS = ["everything", "concerns_me", "nothing"]


@cli.command()
@click.option(
    "--level",
    type=click.Choice([*LEVELS, "default"]),
    help="What to be told about; 'default' removes a project's or item's own.",
)
@click.option("--delivery", type=click.Choice(["each", "digest"]), help="Mails.")
@click.option("--project", type=int, help="Show or set the level for PROJECT.")
@click.option("--item", type=int, help="Show or set the level for an item.")
@json_option
def notifications(level, delivery, project, item, as_json):
    """Show and set your notification level and mail delivery"""
    if project and item:
        terminate("A project or an item, not both.")
    if project or item:
        if delivery:
            terminate(
                "The delivery is the same everywhere; leave out --project and --item."
            )
        path = (
            f"projects/{project}/notifications/"
            if project
            else (f"items/{item}/notifications/")
        )
        if level == "default":
            data = request("DELETE", path)
        elif level:
            data = request("PUT", path, json={"level": level})
        else:
            data = request("GET", path)
        if as_json:
            return echo_json(data)
        click.echo(f"Level: {data['level'] or 'as usual'}")
        return None
    if level == "default":
        terminate("'default' is for --project and --item.")
    if level or delivery:
        changes = {"level": level, "delivery": delivery}
        data = request(
            "PUT",
            "me/notifications/",
            json={k: v for k, v in changes.items() if v},
        )
    else:
        data = request("GET", "me/notifications/")
    if as_json:
        return echo_json(data)
    click.echo(f"Level: {data['level']}")
    click.echo(f"Delivery: {data['delivery']}")
    return None
