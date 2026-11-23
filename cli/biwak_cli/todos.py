"""Lists and to-dos, with handover's bulk commands, and reactions"""

import click

from biwak_cli.core import (
    attach_option,
    cli,
    clients,
    console,
    echo_json,
    json_option,
    names,
    need,
    paginate,
    request,
    table,
    terminate,
    with_attachments,
)


# Lists and to-dos -----------------------------------------------------------


@cli.group(invoke_without_command=True)
@click.option("--project", type=int, help="The project's ID.")
@click.option("--archived", is_flag=True, help="Archived lists instead.")
@json_option
@click.pass_context
def lists(ctx, project, archived, as_json):
    """To-do lists; without a command those of --project. Copy, archive and
    unarchive lists, add to-dos from text."""
    if ctx.invoked_subcommand is not None:
        return None
    need(project, "--project")
    data = request("GET", f"projects/{project}/lists/", params={"archived": archived})
    if as_json:
        return echo_json(data)
    t = table("ID", "List", "")
    for item in data:
        t.add_row(str(item["id"]), item["title"], clients(item))
    console.print(t)
    return None


@lists.command("copy")
@click.argument("list_id", metavar="LIST", type=int)
@click.option("--to", "project", type=int, required=True, help="The project's ID.")
@click.option("--title", help="The copy's title; the list's own by default.")
@click.option(
    "--shift", type=int, help="Move the due dates by DAYS (negative: earlier)."
)
@click.option("--no-dates", is_flag=True, help="Remove the due dates.")
@click.option("--visible", is_flag=True, help="Visible to clients (staff).")
@json_option
def list_copy(list_id, project, title, shift, no_dates, visible, as_json):
    """Copy the open work of LIST into a project (the same or another):
    groups, open to-dos with notes, the assignees who are members there.
    The title gets " (copy)" if the project has a list of that name."""
    if shift is not None and no_dates:
        raise click.UsageError("--shift and --no-dates don't go together.")
    body = {"project_id": project, "visible_to_clients": visible}
    if title:
        body["title"] = title
    if shift is not None:
        body |= {"dates": "shift", "days": shift}
    elif no_dates:
        body["dates"] = "remove"
    data = request("POST", f"lists/{list_id}/copy/", json=body)
    if as_json:
        return echo_json(data)
    shown = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"Copied to #{data['id']} {data['title']}: {data['url']}{shown}")
    return None


@lists.command("archive")
@click.argument("list_id", metavar="LIST", type=int)
@json_option
def list_archive(list_id, as_json):
    """Archive LIST: readable, but out of the way (it stays out of your to-dos)"""
    data = request("PATCH", f"lists/{list_id}/", json={"archived": True})
    if as_json:
        return echo_json(data)
    click.echo(f"Archived {data['title']} ({data['id']}).")
    return None


@lists.command("unarchive")
@click.argument("list_id", metavar="LIST", type=int)
@json_option
def list_unarchive(list_id, as_json):
    """Bring LIST back from the archive"""
    data = request("PATCH", f"lists/{list_id}/", json={"archived": False})
    if as_json:
        return echo_json(data)
    click.echo(f"Brought {data['title']} ({data['id']}) back from the archive.")
    return None


@cli.group(invoke_without_command=True)
@click.option("--list", "list_id", type=int, help="Only this list's ID, by group.")
@click.option("--completed", is_flag=True, help="Completed to-dos, latest first.")
@click.option("--mine", is_flag=True, help="Only to-dos assigned to you.")
@click.option(
    "--assignee",
    type=int,
    help="Only to-dos assigned to this person's ID (people who left too).",
)
@click.option(
    "--assigned-by-me",
    is_flag=True,
    help="Only to-dos you assigned (to somebody else, or to you with --mine"
    " or to --assignee).",
)
@click.option("--project", "project_id", type=int, help="Only this project's ID.")
@click.option(
    "--due",
    type=click.Choice(["overdue", "today", "this_week", "next_week", "later", "none"]),
    help="Only to-dos in this group by due date.",
)
@click.option(
    "--by-due",
    is_flag=True,
    help="Order by due date instead of by project, list and group.",
)
@click.option(
    "--started/--not-started",
    default=None,
    help="Only to-dos which have started (or have no start date), or only"
    " those starting later; default: all.",
)
@json_option
@click.pass_context
def todos(
    ctx,
    list_id,
    completed,
    mine,
    assignee,
    assigned_by_me,
    project_id,
    due,
    by_due,
    started,
    as_json,
):
    """To-dos; without a command the open ones of --list, by group, or
    across all projects, by project or by due date (--mine, --assignee,
    --assigned-by-me, --project, --due, --by-due)"""
    if ctx.invoked_subcommand is not None:
        return None
    if list_id and (
        mine
        or assignee
        or assigned_by_me
        or project_id
        or due
        or by_due
        or started is not None
    ):
        terminate(
            "--mine, --assignee, --assigned-by-me, --project, --due, --by-due"
            " and --started/--not-started go without --list."
        )
    if mine and assignee:
        terminate("--mine or --assignee, not both.")
    if list_id and completed:
        data = paginate(f"lists/{list_id}/todos/completed/")
    elif list_id:
        data = request("GET", f"lists/{list_id}/todos/")
    else:
        params = {"completed": completed, "grouping": "due" if by_due else "project"}
        if mine:
            params["assignee"] = "me"
        if assignee:
            params["assignee"] = assignee
        if assigned_by_me:
            params["assigned_by"] = "me"
        if project_id:
            params["project_id"] = project_id
        if due:
            params["due_group"] = due
        if started is not None:
            params["started"] = "true" if started else "false"
        data = paginate("todos/", params)
    if as_json:
        return echo_json(data)
    if not list_id and not completed and not by_due:
        show_todos_by_project(data)
        return None
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
            dates(todo),
            clients(todo),
        )
    console.print(t)
    return None


def dates(todo):
    """The due date, from the start date if there's one"""
    if todo.get("starts_on"):
        return f"{todo['starts_on']} – {todo['due_on']}"
    return todo["due_on"] or ""


def show_todos_by_project(data):
    """Headings for projects, lists and groups, as the page has them"""
    seen = None
    t = None
    for todo in data:
        heading = (
            todo["project_id"],
            todo["list_id"],
            (todo["group"] or {}).get("id"),
        )
        if heading != seen:
            if t is not None:
                console.print(t)
            if seen is None or heading[0] != seen[0]:
                console.print(f"[bold]{todo['project_name']}[/bold]")
            if seen is None or heading[:2] != seen[:2]:
                console.print(f"  {todo['list_title']}")
            if todo["group"]:
                console.print(f"    [dim]{todo['group']['title']}[/dim]")
            t = table("ID", "To-do", "Assignees", "Due", "")
            seen = heading
        t.add_row(
            str(todo["id"]),
            todo["title"],
            names(todo["assignees"]),
            dates(todo),
            clients(todo),
        )
    if t is not None:
        console.print(t)


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
        ("Starts", data.get("starts_on")),
        ("Repeats", data.get("recurrence_description")),
        ("Repeats until", data.get("recurrence_ends_on")),
        (
            "Checklist",
            f"{data['checklist_done']}/{data['checklist_total']}"
            if data.get("checklist_total")
            else None,
        ),
        ("Reactions", show_reactions(data.get("reactions", []))),
        ("URL", data["url"]),
    ]:
        if value:
            click.echo(f"{label}: {value}")
    if data["notes"]:
        click.echo(f"\n{data['notes']}")


@todos.command("show")
@click.argument("todo_id", metavar="TODO", type=int)
@click.option("--comments", is_flag=True, help="With the comments.")
@json_option
def todo_show(todo_id, comments, as_json):
    """Show TODO"""
    data = request("GET", f"todos/{todo_id}/")
    if comments:
        data["comments"] = paginate(f"items/{todo_id}/comments/")
    if as_json:
        return echo_json(data)
    show_todo(data)
    for comment in data.get("comments", []):
        click.echo(f"\n{comment['author']['name']}, {comment['created_at'][:16]}:")
        click.echo(comment["content"])
        if comment.get("reactions"):
            click.echo(f"Reactions: {show_reactions(comment['reactions'])}")
    return None


@todos.command("create")
@click.argument("list_id", metavar="LIST", type=int)
@click.argument("title")
@click.option("--notes", default="", help="Markdown.")
@click.option("--due", help="YYYY-MM-DD.")
@click.option("--starts", help="YYYY-MM-DD, with --due and not after it.")
@click.option("--assign", multiple=True, type=int, help="A person's ID, repeatable.")
@click.option("--group", type=int, help="The group's ID.")
@attach_option
@repeat_option
@json_option
def todo_add(
    list_id, title, notes, due, starts, assign, group, attach, repeat, as_json
):
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
            "starts_on": starts,
            "assignees": list(assign),
            "group_id": group,
            **({"recurrence": repeat} if repeat else {}),
        },
    )
    if as_json:
        return echo_json(data)
    show_todo(data)
    return None


@lists.command("add-from-text")
@click.argument("list_id", metavar="LIST", type=int)
@click.argument("file", type=click.File(encoding="utf-8-sig"), required=False)
@click.option("--preview", is_flag=True, help="Show what would be added, add nothing.")
@json_option
def list_add_from_text(list_id, file, preview, as_json):
    """Add the to-dos of FILE (Markdown or plain text) or standard input to
    LIST: headings become groups (existing ones of that name are used),
    list items to-dos, what's indented under them their notes, ticked
    items completed to-dos; a text without list items gives a to-do per
    line"""
    text = (file or click.get_text_stream("stdin")).read()
    data = request(
        "POST",
        f"lists/{list_id}/todos/from-text/",
        json={"text": text, "preview": preview},
    )
    if as_json:
        return echo_json(data)
    if data["problem"]:
        terminate(data["problem"])
    lst = request("GET", f"lists/{list_id}/")
    marker = " [clients]" if lst["visible_to_clients"] else ""
    for group in data["groups"]:
        if group["title"] is not None:
            state = "new" if group["new"] else "existing"
            click.echo(f"{group['title']} ({state})")
        for todo in group["todos"]:
            box = "[x]" if todo["completed"] else "[ ]"
            checklist = (
                f" ({todo['checklist_done']}/{todo['checklist_total']})"
                if todo["checklist_total"]
                else ""
            )
            number = f"#{todo['id']} " if todo["id"] else ""
            click.echo(f"  {box} {number}{todo['title']}{checklist}")
    if data["left_out"]:
        click.echo(f"{data['left_out']} paragraph(s) left out: not list items.")
    count = data["count"]
    if data["added"]:
        click.echo(f"Added {count} to-do(s) to {lst['title']}{marker}.")
    else:
        click.echo(f"Would add {count} to-do(s) to {lst['title']}{marker}.")
    return None


@todos.command("update")
@click.argument("todo_id", metavar="TODO", type=int)
@click.option("--title")
@click.option("--notes", help="Markdown, replaces the notes.")
@click.option("--due", help="YYYY-MM-DD, or 'none' to remove it (and the start date).")
@click.option(
    "--starts", help="YYYY-MM-DD, not after the due date, or 'none' to remove it."
)
@click.option(
    "--assign",
    multiple=True,
    type=int,
    help="Replaces the assignees, repeatable; --assign 0 removes all.",
)
@attach_option
@repeat_option
@json_option
def todo_edit(todo_id, title, notes, due, starts, assign, attach, repeat, as_json):
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
    if starts is not None:
        changes["starts_on"] = None if starts == "none" else starts
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


@todos.command("move")
@click.argument("todo_ids", metavar="[TODO]...", type=int, nargs=-1)
@click.option(
    "--todos",
    "several",
    help="Several to-dos' IDs, comma separated, instead of TODO.",
)
@click.option(
    "--list", "list_id", type=int, required=True, help="The list's ID (any project)."
)
@click.option("--group", type=int, help="The group's ID (default: ungrouped).")
@click.option(
    "--confirm",
    is_flag=True,
    help="Into another project: move although people are added or dropped.",
)
@json_option
def todo_move(todo_ids, several, list_id, group, confirm, as_json):
    """Move TODO (or several, next to each other in this order) to the end
    of a list, into a group or ungrouped: all or nothing. Into another
    project (staff) people who don't see them there are added or dropped:
    the error says who, --confirm moves anyway."""
    if bool(todo_ids) == bool(several):
        terminate("Give either TODO or --todos.")
    if several:
        try:
            todo_ids = [int(part) for part in several.split(",")]
        except ValueError:
            terminate("--todos takes IDs separated by commas.")
    data = request(
        "POST",
        "todos/move/",
        json={
            "ids": list(todo_ids),
            "list_id": list_id,
            "group_id": group,
            "confirm": confirm,
        },
    )
    if as_json:
        return echo_json(data[0] if len(data) == 1 and not several else data)
    for moved in data:
        click.echo(f"Moved #{moved['id']} {moved['title']}.")
    return None


@todos.command("dates")
@click.argument("todo_ids", metavar="TODO...", type=int, nargs=-1, required=True)
@click.option("--due", help="YYYY-MM-DD: one due date for all (start dates stay).")
@click.option(
    "--shift",
    type=int,
    help="Move due and start dates by this many days (negative: earlier).",
)
@click.option("--remove", is_flag=True, help="Remove the due and start dates.")
@json_option
def todo_dates(todo_ids, due, shift, remove, as_json):
    """Set, move or remove the due dates of every TODO at once: all or
    nothing"""
    if sum([due is not None, shift is not None, remove]) != 1:
        terminate("Give one of --due, --shift and --remove.")
    if due is not None:
        changes = {"dates": "set", "due_on": due}
    elif shift is not None:
        changes = {"dates": "shift", "days": shift}
    else:
        changes = {"dates": "remove"}
    data = request("POST", "todos/dates/", json={"ids": list(todo_ids), **changes})
    if as_json:
        return echo_json(data)
    for dated in data:
        click.echo(f"#{dated['id']} {dated['title']}: {dates(dated) or '-'}")
    return None


@todos.command("assign")
@click.argument("todo_ids", metavar="TODO...", type=int, nargs=-1, required=True)
@click.option(
    "--to",
    "people",
    multiple=True,
    type=int,
    required=True,
    help="A person's ID, repeatable.",
)
@click.option(
    "--replace",
    is_flag=True,
    help="Instead of the current assignees (default: added to them).",
)
@json_option
def todo_assign(todo_ids, people, replace, as_json):
    """Assign the people --to to every TODO at once: all or nothing; each new
    assignee is told once"""
    data = request(
        "POST",
        "todos/assign/",
        json={"ids": list(todo_ids), "people": list(people), "replace": replace},
    )
    if as_json:
        return echo_json(data)
    for assigned in data:
        marker = f" {clients(assigned)}" if clients(assigned) else ""
        click.echo(
            f"#{assigned['id']} {assigned['title']}{marker}:"
            f" {names(assigned['assignees'])}"
        )
    return None


@todos.command("complete")
@click.argument("todo_id", metavar="TODO", type=int)
@json_option
def todo_done(todo_id, as_json):
    """Complete TODO"""
    data = request("POST", f"todos/{todo_id}/complete/")
    if as_json:
        return echo_json(data)
    click.echo(f"Completed #{data['id']} {data['title']}.")
    return None


@todos.command("reopen")
@click.argument("todo_id", metavar="TODO", type=int)
@json_option
def todo_reopen(todo_id, as_json):
    """Reopen TODO"""
    data = request("POST", f"todos/{todo_id}/reopen/")
    if as_json:
        return echo_json(data)
    click.echo(f"Reopened #{data['id']} {data['title']}.")
    return None


@todos.command("comment")
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


@cli.group()
def reactions():
    """Reactions on to-dos and comments"""


@reactions.command("create")
@click.argument("todo_id", metavar="TODO", type=int)
@click.argument("content")
@click.option(
    "--comment", "comment_id", type=int, help="React to this comment ID instead."
)
@json_option
def reactions_create(todo_id, content, comment_id, as_json):
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
