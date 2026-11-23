"""Projects and their members"""

import click

from biwak_cli.core import (
    PALETTE,
    cli,
    console,
    echo_json,
    json_option,
    link,
    need,
    notify_option,
    request,
    table,
    terminate,
    with_away,
)


@cli.group(invoke_without_command=True)
@json_option
@click.option("--archived", is_flag=True, help="Archived projects instead.")
@click.option(
    "--templates",
    is_flag=True,
    help="Templates instead (own staff); with --archived the archived ones.",
)
@click.option(
    "--joinable",
    is_flag=True,
    help="Limited projects you're not in instead, which admins can join.",
)
@click.option(
    "--order",
    type=click.Choice(["activity", "name"]),
    help="Latest activity first or by name (default: your setting on the web).",
)
@click.option(
    "--all",
    "everything",
    is_flag=True,
    help="Every project with counts, also those you can't open (admins).",
)
@click.option("--no-staff", is_flag=True, help="With --all: no active staff member.")
@click.option("--limited", is_flag=True, help="With --all: limited projects.")
@click.option(
    "--inactive-todos",
    is_flag=True,
    help="With --all: with open to-dos whose assignees are all inactive.",
)
@click.pass_context
def projects(
    ctx,
    as_json,
    archived,
    templates,
    joinable,
    order,
    everything,
    no_staff,
    limited,
    inactive_todos,
):
    """Projects; without a command the ones you can open, bookmarked ones
    (*) first, with the latest activity (for clients: of what they see)"""
    if ctx.invoked_subcommand is not None:
        return None
    if everything:
        return all_projects(
            as_json,
            {
                "archived": archived,
                "no_staff": no_staff,
                "limited": limited,
                "inactive": inactive_todos,
            },
        )
    if no_staff or limited or inactive_todos:
        terminate("--no-staff, --limited and --inactive-todos go with --all.")
    if joinable:
        data = request("GET", "projects/joinable/")
        if as_json:
            return echo_json(data)
        t = table("ID", "Project")
        for p in data:
            t.add_row(str(p["id"]), link(p["name"], p.get("url")))
        console.print(t)
        return None
    params = {"archived": archived}
    if templates:
        params["templates"] = True
    if order:
        params["order"] = order
    data = request("GET", "projects/", params=params)
    if as_json:
        return echo_json(data)
    t = table("", "ID", "Project", "Color", "Last activity", "")
    for p in data:
        t.add_row(
            "*" if p["is_bookmarked"] else "",
            str(p["id"]),
            link(p["name"], p.get("url")),
            p["color_name"],
            (p["last_activity_at"] or "")[:16].replace("T", " "),
            "" if p["is_all_access"] else "limited",
        )
    console.print(t)
    return None


def all_projects(as_json, filters):
    """``biwak projects --all``: every project, for admins
    (specs/handover.md); --archived includes the archived ones"""
    data = request(
        "GET", "projects/all/", params={k: v for k, v in filters.items() if v}
    )
    if as_json:
        return echo_json(data)
    t = table(
        "ID", "Project", "", "Staff", "Clients", "Open", "Inactive", "Last activity"
    )
    for p in data:
        marks = [
            "" if p["is_all_access"] else "limited",
            "archived" if p["archived"] else "",
            "joinable" if p["joinable"] else "",
        ]
        t.add_row(
            str(p["id"]),
            link(p["name"], p.get("url")),
            " ".join(mark for mark in marks if mark),
            str(p["active_staff"]),
            ", ".join(p["client_organizations"]),
            str(p["open_todos"]),
            str(p["inactive_todos"]),
            (p["last_activity_at"] or "")[:16].replace("T", " "),
        )
    console.print(t)
    return None


color_option = click.option(
    "--color",
    type=click.Choice([*PALETTE, "none"]),
    help="The project's color, or 'none'.",
)


@projects.command("create")
@click.argument("name")
@click.option("--description", default="", help="Markdown.")
@click.option(
    "--limited",
    is_flag=True,
    help="Only members see it (default: all staff can see it).",
)
@color_option
@click.option(
    "--template",
    "template",
    type=int,
    metavar="ID",
    help="Start as a copy of this template (biwak projects --templates).",
)
@click.option(
    "--member",
    "members",
    type=int,
    multiple=True,
    metavar="PERSON",
    help="Add this person (repeatable), before the template is copied.",
)
@click.option(
    "--as-template",
    is_flag=True,
    help="A template instead of a project (own staff; all staff see it).",
)
@json_option
def project_add(
    name, description, limited, color, template, members, as_template, as_json
):
    """Create the project NAME (staff); you become a member. Without --color
    it gets one no other active project has. With --template it starts as a
    copy of the template's lists, messages, folders, docs and files;
    assignees who don't see the new project are left out."""
    body = {"name": name, "description": description, "is_all_access": not limited}
    if color is not None:
        body["color"] = "" if color == "none" else color
    if template is not None:
        body["template"] = template
    if members:
        body["member_ids"] = list(members)
    if as_template:
        body["is_template"] = True
    data = request("POST", "projects/", json=body)
    if as_json:
        return echo_json(data)
    kind = "template" if data["is_template"] else "project"
    click.echo(
        f"Created the {kind} #{data['id']} {data['name']}"
        f"{'' if data['is_all_access'] else ' (limited)'}."
    )
    return None


@projects.command("update")
@click.argument("project_id", metavar="ID", type=int)
@click.option("--name")
@click.option("--description", help="Markdown, replaces the description.")
@click.option("--limited/--all-access", default=None, help="Who can see it (staff).")
@color_option
@json_option
def project_edit(project_id, name, description, limited, color, as_json):
    """Change the project ID (staff)"""
    changes = {}
    if name is not None:
        changes["name"] = name
    if description is not None:
        changes["description"] = description
    if limited is not None:
        changes["is_all_access"] = not limited
    if color is not None:
        changes["color"] = "" if color == "none" else color
    if not changes:
        terminate("Nothing to change.")
    data = request("PATCH", f"projects/{project_id}/", json=changes)
    if as_json:
        return echo_json(data)
    click.echo(
        f"#{data['id']} {data['name']}"
        f"{', ' + data['color_name'] if data['color'] else ''}."
    )
    return None


@projects.command("join")
@click.argument("project_id", metavar="ID", type=int)
@json_option
def project_join(project_id, as_json):
    """Join the project ID: staff all-access ones, admins also limited ones
    (see `biwak projects --joinable`); recorded in the project"""
    data = request("POST", f"projects/{project_id}/join/")
    if as_json:
        return echo_json(data)
    click.echo(f"Joined #{data['id']} {data['name']}.")
    return None


NOTIFY_WORDS = {
    "default": "everything new",
    "tagged": "only when tagged",
}


def show_member(person):
    click.echo(f"{person['name']} ({person['id']}): {notify_word(person)}")


def notify_word(person):
    return NOTIFY_WORDS.get(person["notify"], "") if person["notify"] else ""


@cli.group(invoke_without_command=True)
@click.option("--project", type=int, help="The project's ID.")
@json_option
@click.pass_context
def members(ctx, project, as_json):
    """The people in projects; without a command those of --project: staff
    see addresses and how each is notified (everything new,
    only when tagged, no mails), clients only their own"""
    if ctx.invoked_subcommand is not None:
        return None
    need(project, "--project")
    data = request("GET", f"projects/{project}/members/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Name", "Organization", "Email", "Notified", "")
    for person in data:
        t.add_row(
            str(person["id"]),
            with_away(person),
            person.get("organization") or "",
            person["email"] or "",
            notify_word(person),
            "client" if person["is_client"] else "",
        )
    console.print(t)
    return None


@members.command("add")
@click.argument("project", type=int)
@click.argument("person", type=int)
@notify_option
@json_option
def member_add(project, person, notify_about_everything, as_json):
    """Add the person with ID PERSON to PROJECT"""
    data = request(
        "POST",
        f"projects/{project}/members/",
        json={
            "person_id": person,
            "notify": "default" if notify_about_everything else "tagged",
        },
    )
    if as_json:
        return echo_json(data)
    click.echo("Added: ", nl=False)
    show_member(data)
    return None


@members.command("invite")
@click.argument("project", type=int)
@click.argument("email")
@click.option("--name", default="", help="Their name, for new people.")
@click.option(
    "--organization",
    default="",
    help="New people's organization, by name (see biwak orgs); default: the"
    " one of the address's domain.",
)
@click.option("--organization-id", type=int, help="The same by ID.")
@click.option("--staff", is_flag=True, help="Staff instead of a client (admins).")
@notify_option
@json_option
def member_invite(
    project,
    email,
    name,
    organization,
    organization_id,
    staff,
    notify_about_everything,
    as_json,
):
    """Add the person with this address to PROJECT, creating them (as a
    client) and mailing them how to log in if they're new"""
    payload = {
        "email": email,
        "name": name,
        "organization": organization,
        "is_client": not staff,
        "notify": "default" if notify_about_everything else "tagged",
    }
    if organization_id is not None:
        payload["organization_id"] = organization_id
    data = request("POST", f"projects/{project}/members/invite/", json=payload)
    if as_json:
        return echo_json(data)
    click.echo("Invited: ", nl=False)
    show_member(data)
    return None


@members.command("remove")
@click.argument("project", type=int)
@click.argument("person", type=int)
@json_option
def member_remove(project, person, as_json):
    """Remove the person with ID PERSON from PROJECT; own staff only,
    themselves included"""
    data = request("DELETE", f"projects/{project}/members/{person}/")
    if as_json:
        return echo_json(data)
    click.echo(f"Removed {data['name']} ({data['id']}).")
    return None
