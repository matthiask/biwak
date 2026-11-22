"""The commands; output for people by default, --json for scripts"""

import os

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
    paginate,
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
    """Short names, "(inactive)" after people who left"""
    return ", ".join(
        p["short_name"] + ("" if p.get("is_active", True) else " (inactive)")
        for p in people
    )


def with_away(person):
    """The name, "(away until 2026-12-03)" after people away"""
    if person.get("away_until"):
        return f"{person['name']} (away until {person['away_until']})"
    return person["name"]


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


# The palette (biwak.accounts.models.Color; a test keeps both in step)
PALETTE = [
    "heather", "lake", "forest", "glacier", "ember",
    "alpenglow", "moss", "slate", "bark", "berry",
]  # fmt: skip


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


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def me(ctx, as_json):
    """Who you are and the token's access; `biwak me image` sets your
    profile image"""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "me/")
    if as_json:
        return echo_json(data)
    kind = "client" if data["is_client"] else "staff"
    click.echo(f"{data['name']} <{data['email']}>, {kind}, {data['access']} access")
    return None


@me.command("image")
@click.argument("path", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option("--remove", is_flag=True, help="Back to the initials.")
@json_option
def me_image(path, remove, as_json):
    """Set your profile image to the JPEG, PNG or WebP at PATH (at most 5 MB;
    cut to a square in the middle), or remove it"""
    if remove == bool(path):
        terminate("Give a file, or --remove.")
    if remove:
        data = request("DELETE", "me/image/")
    else:
        with click.open_file(path, "rb") as file:
            data = request(
                "PUT",
                "me/image/",
                files={"image": (os.path.basename(path), file)},
            )
    if as_json:
        return echo_json(data)
    click.echo(
        "Removed your profile image."
        if remove
        else f"Your profile image: {data['image_url']}"
    )
    return None


LANGUAGES = {"auto": "", "de": "de", "en": "en"}


@cli.command()
@click.option(
    "--language",
    type=click.Choice(list(LANGUAGES)),
    help="The web interface's and the mails' language; auto follows the browser.",
)
@json_option
def settings(language, as_json):
    """Your preferences for the web interface; the options change them"""
    if language is not None:
        data = request("PUT", "me/", json={"language": LANGUAGES[language]})
    else:
        data = request("GET", "me/")
    if as_json:
        return echo_json(data)
    shortcuts = "on" if data["keyboard_shortcuts"] else "off"
    click.echo(f"Language: {data['language'] or 'auto'}")
    click.echo(f"Theme: {data['theme']}, accent: {data['accent']}")
    click.echo(f"Single-key shortcuts: {shortcuts}")
    return None


# Projects and lists ---------------------------------------------------------


@cli.command()
@json_option
@click.option("--archived", is_flag=True, help="Archived projects instead.")
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
def projects(
    as_json, archived, joinable, order, everything, no_staff, limited, inactive_todos
):
    """The projects you can open, bookmarked ones (*) first, with the latest
    activity (for clients: of what they see)"""
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
            t.add_row(str(p["id"]), p["name"])
        console.print(t)
        return None
    params = {"archived": archived}
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
            p["name"],
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
            p["name"],
            " ".join(mark for mark in marks if mark),
            str(p["active_staff"]),
            ", ".join(p["client_organizations"]),
            str(p["open_todos"]),
            str(p["inactive_todos"]),
            (p["last_activity_at"] or "")[:16].replace("T", " "),
        )
    console.print(t)
    return None


@cli.group()
def project():
    """Create and join projects"""


color_option = click.option(
    "--color",
    type=click.Choice([*PALETTE, "none"]),
    help="The project's color, or 'none'.",
)


@project.command("add")
@click.argument("name")
@click.option("--description", default="", help="Markdown.")
@click.option(
    "--limited",
    is_flag=True,
    help="Only members see it (default: all staff can see it).",
)
@color_option
@json_option
def project_add(name, description, limited, color, as_json):
    """Create the project NAME (staff); you become a member. Without --color
    it gets one no other active project has."""
    body = {"name": name, "description": description, "is_all_access": not limited}
    if color is not None:
        body["color"] = "" if color == "none" else color
    data = request("POST", "projects/", json=body)
    if as_json:
        return echo_json(data)
    click.echo(
        f"Created #{data['id']} {data['name']}"
        f"{'' if data['is_all_access'] else ' (limited)'}."
    )
    return None


@project.command("edit")
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


@project.command("join")
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
    "default": "notified by default",
    "tagged": "only when tagged",
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


@cli.group()
def member():
    """Add, invite and remove people in a project"""


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
@click.option(
    "--organization",
    default="",
    help="New people's organization, by name (see biwak orgs); default: the"
    " one of the address's domain.",
)
@click.option("--organization-id", type=int, help="The same by ID.")
@click.option("--staff", is_flag=True, help="Staff instead of a client (admins).")
@only_tagged_option
@json_option
def member_invite(
    project, email, name, organization, organization_id, staff, only_tagged, as_json
):
    """Add the person with this address to PROJECT, creating them (as a
    client) and mailing them how to log in if they're new"""
    payload = {
        "email": email,
        "name": name,
        "organization": organization,
        "is_client": not staff,
        "notify": "tagged" if only_tagged else "default",
    }
    if organization_id is not None:
        payload["organization_id"] = organization_id
    data = request("POST", f"projects/{project}/members/invite/", json=payload)
    if as_json:
        return echo_json(data)
    click.echo("Invited: ", nl=False)
    show_member(data)
    return None


@cli.command()
@click.argument("emails", nargs=-1, required=True)
@click.option(
    "--project",
    "projects",
    type=int,
    multiple=True,
    required=True,
    help="A project to invite them to (repeat for several).",
)
@click.option(
    "--organization",
    default="",
    help="New people's organization, by name (see biwak orgs); default: the"
    " one of each address's domain.",
)
@click.option("--organization-id", type=int, help="The same by ID.")
@click.option("--staff", is_flag=True, help="Staff instead of clients (admins).")
@only_tagged_option
@json_option
def invite(
    emails, projects, organization, organization_id, staff, only_tagged, as_json
):
    """Invite the people with these addresses to every --project at once:
    new people (clients unless --staff) get one mail naming the projects,
    people with an account are added. All or nothing: an address that
    can't be invited invites nobody."""
    person = {"organization": organization, "is_client": not staff}
    if organization_id is not None:
        person["organization_id"] = organization_id
    data = request(
        "POST",
        "invitations/",
        json={
            "people": [{"email": email, **person} for email in emails],
            "projects": list(projects),
            "notify": "tagged" if only_tagged else "default",
        },
    )
    if as_json:
        return echo_json(data)
    for invited in data:
        word = "Invited" if invited["created"] else "Added"
        click.echo(f"{word}: {invited['person']['name']} ({invited['person']['id']})")
    return None


@cli.group(invoke_without_command=True)
@click.option(
    "--inactive",
    is_flag=True,
    help="People who can't sign in and haven't left (waiting to be activated).",
)
@click.option("--left", is_flag=True, help="People who left, with the day.")
@json_option
@click.pass_context
def people(ctx, inactive, left, as_json):
    """The active people (staff), with --inactive those waiting to be
    activated, with --left those who left; `biwak people activate` and
    `deactivate` change that, `reset-sign-in` removes somebody's
    authenticator app, passkeys and API tokens"""
    if ctx.invoked_subcommand is not None:
        return None
    if inactive and left:
        terminate("--inactive or --left, not both.")
    data = request("GET", "people/", params={"inactive": inactive, "left": left})
    if as_json:
        return echo_json(data)
    columns = ["ID", "Name", "Email", "Organization"] + (["Left on"] if left else [])
    t = table(*columns)
    for person in data:
        t.add_row(
            str(person["id"]),
            with_away(person),
            person["email"],
            person["organization"],
            *([person.get("left_at") or ""] if left else []),
        )
    console.print(t)
    return None


@people.command("activate")
@click.argument("ids", nargs=-1, type=int, required=True)
@click.option(
    "--mail",
    is_flag=True,
    help="Send them the invitation mail (not to addresses that bounced).",
)
@json_option
def people_activate(ids, mail, as_json):
    """Activate the people with these IDs, all or nothing: staff activate
    clients, admins also staff and externals"""
    data = request("POST", "people/activate/", json={"ids": list(ids), "mail": mail})
    if as_json:
        return echo_json(data)
    for person in data:
        note = " (mailed)" if person["mailed"] else ""
        click.echo(f"Activated: {person['name']} ({person['id']}){note}")
    return None


@people.command("deactivate")
@click.argument("ids", nargs=-1, type=int, required=True)
@json_option
def people_deactivate(ids, as_json):
    """Deactivate the people with these IDs and end their access (sessions,
    API tokens, calendar links), all or nothing; not yourself, not the last
    active admin"""
    data = request("POST", "people/deactivate/", json={"ids": list(ids)})
    if as_json:
        return echo_json(data)
    for person in data:
        click.echo(f"Deactivated: {person['name']} ({person['id']})")
    return None


@people.command("reset-sign-in")
@click.argument("person_id", type=int)
@json_option
def people_reset_sign_in(person_id, as_json):
    """Remove the person's authenticator app, passkeys and API tokens, sign
    them out everywhere and mail them what was removed; for a lost device or
    when someone else may have had access. Staff reset clients, admins also
    staff and externals, not yourself (change your own in the settings)"""
    data = request("POST", f"people/{person_id}/reset-sign-in/")
    if as_json:
        return echo_json(data)
    if data["reset"]:
        removed = data["removed"]
        what = [
            *(["authenticator app"] if removed["app"] else []),
            *([f"{removed['passkeys']} passkey(s)"] if removed["passkeys"] else []),
            *(
                [f"{removed['api_tokens']} API token(s)"]
                if removed["api_tokens"]
                else []
            ),
        ]
        click.echo(
            f"Reset: {data['name']} ({data['id']}), removed {', '.join(what)},"
            " signed out everywhere"
        )
    else:
        click.echo(
            f"{data['name']} ({data['id']}) has no authenticator app, passkeys"
            " or API tokens."
        )
    return None


# The old name (CLI 0.36.0), kept as an alias
people.add_command(
    click.Command(
        "reset-two-factor",
        callback=people_reset_sign_in.callback,
        params=people_reset_sign_in.params,
        help="Old name of reset-sign-in.",
        hidden=True,
    )
)


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def invitations(ctx, as_json):
    """Who was invited and hasn't signed in yet, the oldest invitation
    first (staff); resend or withdraw an invitation"""
    if ctx.invoked_subcommand:
        return None
    data = request("GET", "invitations/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Name", "Email", "Invited by", "Invited at", "Projects")
    for invitation in data:
        t.add_row(
            str(invitation["person"]["id"]),
            invitation["person"]["name"],
            invitation["email"],
            (invitation["invited_by"] or {}).get("name", ""),
            invitation["invited_at"][:10],
            ", ".join(str(pk) for pk in invitation["project_ids"]),
        )
    console.print(t)
    return None


@invitations.command("resend")
@click.argument("person", type=int)
@json_option
def invitations_resend(person, as_json):
    """Send the invitation of PERSON again, naming the projects they're
    in now"""
    data = request("POST", f"invitations/{person}/resend/")
    if as_json:
        return echo_json(data)
    click.echo(f"Sent again to {data['email']}.")
    return None


@invitations.command("withdraw")
@click.argument("person", type=int)
@json_option
def invitations_withdraw(person, as_json):
    """Withdraw the invitation of PERSON: removed from all their projects,
    the account deleted if nothing else refers to it, else deactivated
    (staff for clients, admins for everybody)"""
    data = request("DELETE", f"invitations/{person}/")
    if as_json:
        return echo_json(data)
    removed = [str(pk) for pk in data["removed_from"]]
    if others := data.get("removed_from_others"):
        removed.append(f"{others} other project{'s' if others > 1 else ''}")
    removed = ", ".join(removed) or "no projects"
    if data["deleted"]:
        account = "the account is deleted."
    else:
        account = "the account is deactivated."
    click.echo(f"Withdrawn: removed from {removed}; {account}")
    return None


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def orgs(ctx, as_json):
    """The organizations people belong to (own staff):
    without a command, all of them"""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "organizations/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Organization", "People", "Domains", "")
    for org in data:
        t.add_row(
            str(org["id"]),
            org["name"],
            str(org["people_count"]),
            ", ".join(org["domains"]),
            "own" if org["is_own"] else "",
        )
    console.print(t)
    return None


SIGN_IN = {
    "codes": "codes and passkeys",
    "sso_allowed": "{provider}, codes and passkeys",
    "sso_required": "only {provider}",
}
SIGN_IN_PROVIDERS = {"google": "Google", "microsoft": "Microsoft"}


def show_org(data):
    own = ", your own organization" if data["is_own"] else ""
    click.echo(f"{data['name']} ({data['id']}{own})")
    if data["domains"]:
        click.echo(f"Domains: {', '.join(data['domains'])}")
    signin = data.get("signin")
    if signin in SIGN_IN:
        provider = SIGN_IN_PROVIDERS.get(data.get("idp"), "")
        click.echo(f"Sign-in: {SIGN_IN[signin].format(provider=provider)}")
    for person in data.get("people", []):
        kind = "client" if person["is_client"] else "staff"
        click.echo(f"  {person['name']} ({person['id']}, {kind})")


@orgs.command("show")
@click.argument("org", type=int)
@json_option
def orgs_show(org, as_json):
    """The organization with ID ORG, its domains and people"""
    data = request("GET", f"organizations/{org}/")
    if as_json:
        return echo_json(data)
    show_org(data)
    return None


@orgs.command("add")
@click.argument("name")
@click.option(
    "--domain", "domains", multiple=True, help="e.g. example.org, repeatable."
)
@json_option
def orgs_add(name, domains, as_json):
    """Create an organization"""
    data = request(
        "POST", "organizations/", json={"name": name, "domains": list(domains)}
    )
    if as_json:
        return echo_json(data)
    click.echo("Created: ", nl=False)
    show_org(data)
    return None


@orgs.command("edit")
@click.argument("org", type=int)
@click.option("--name", help="The new name, for everybody.")
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Replaces the domains, repeatable.",
)
@click.option("--no-domains", is_flag=True, help="Remove all domains.")
@json_option
def orgs_edit(org, name, domains, no_domains, as_json):
    """Rename the organization with ID ORG or replace its domains"""
    payload = {}
    if name is not None:
        payload["name"] = name
    if domains or no_domains:
        payload["domains"] = list(domains)
    data = request("PATCH", f"organizations/{org}/", json=payload)
    if as_json:
        return echo_json(data)
    show_org(data)
    return None


@orgs.command("merge")
@click.argument("org", type=int)
@click.argument("into", type=int)
@click.option(
    "--confirm",
    is_flag=True,
    help="INTO signs in more strictly: change how ORG's people sign in (admins).",
)
@json_option
def orgs_merge(org, into, confirm, as_json):
    """Move the people and domains of ORG into INTO and delete ORG (the
    typo case)"""
    data = request(
        "POST",
        f"organizations/{org}/merge/",
        json={"into_id": into, "confirm": confirm},
    )
    if as_json:
        return echo_json(data)
    click.echo("Merged into ", nl=False)
    show_org(data)
    return None


@orgs.command("delete")
@click.argument("org", type=int)
@json_option
def orgs_delete(org, as_json):
    """Delete the organization with ID ORG, if nobody belongs to it"""
    data = request("DELETE", f"organizations/{org}/")
    if as_json:
        return echo_json(data)
    click.echo(f"Deleted {data['name']} ({data['id']}).")
    return None


@orgs.command("move")
@click.argument("person", type=int)
@click.argument("org", type=int, required=False)
@json_option
def orgs_move(person, org, as_json):
    """Move the person with ID PERSON to the organization ORG (none without
    it)"""
    data = request(
        "PUT", f"people/{person}/organization/", json={"organization_id": org}
    )
    if as_json:
        return echo_json(data)
    click.echo(f"{data['name']} ({data['id']}): {data['organization'] or 'none'}")
    return None


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def teams(ctx, as_json):
    """Teams, named sets of people (staff; own staff change them): without a
    command, all of them. Picking a team on the web picks its members; through
    the API send the people (biwak teams show)."""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "teams/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Team", "Members")
    for team in data:
        t.add_row(
            str(team["id"]),
            team["name"],
            ", ".join(f"{p['name']} ({p['id']})" for p in team["members"]),
        )
    console.print(t)
    return None


def show_team(data):
    click.echo(f"{data['name']} ({data['id']})")
    for person in data["members"]:
        kind = "client" if person["is_client"] else "staff"
        inactive = ", inactive" if not person["is_active"] else ""
        click.echo(f"  {person['name']} ({person['id']}, {kind}{inactive})")


def member_ids(value):
    """The IDs of ``--members`` as a list"""
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError:
        terminate("--members is people's IDs separated by commas.")


members_option = click.option(
    "--members",
    default=None,
    metavar="IDS",
    help="People's IDs separated by commas (replacing the members).",
)


@teams.command("show")
@click.argument("team", type=int)
@json_option
def teams_show(team, as_json):
    """The team with ID TEAM and its members"""
    data = request("GET", f"teams/{team}/")
    if as_json:
        return echo_json(data)
    show_team(data)
    return None


@teams.command("add")
@click.argument("name")
@members_option
@json_option
def teams_add(name, members, as_json):
    """Create a team (own staff)"""
    data = request(
        "POST",
        "teams/",
        json={"name": name, "members": member_ids(members or "")},
    )
    if as_json:
        return echo_json(data)
    click.echo("Created: ", nl=False)
    show_team(data)
    return None


@teams.command("edit")
@click.argument("team", type=int)
@click.option("--name", help="The new name.")
@members_option
@json_option
def teams_edit(team, name, members, as_json):
    """Rename the team with ID TEAM or replace its members (own staff);
    what was picked with it before stays"""
    payload = {}
    if name is not None:
        payload["name"] = name
    if members is not None:
        payload["members"] = member_ids(members)
    data = request("PATCH", f"teams/{team}/", json=payload)
    if as_json:
        return echo_json(data)
    show_team(data)
    return None


@teams.command("delete")
@click.argument("team", type=int)
@json_option
def teams_delete(team, as_json):
    """Delete the team with ID TEAM (own staff); assignees, subscribers and
    mentions picked with it stay"""
    data = request("DELETE", f"teams/{team}/")
    if as_json:
        return echo_json(data)
    click.echo(f"Deleted {data['name']} ({data['id']}).")
    return None


@member.command("remove")
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


@cli.command()
@click.argument("project", type=int)
@click.option("--archived", is_flag=True, help="Archived lists instead.")
@json_option
def lists(project, archived, as_json):
    """The to-do lists of PROJECT"""
    data = request("GET", f"projects/{project}/lists/", params={"archived": archived})
    if as_json:
        return echo_json(data)
    t = table("ID", "List", "")
    for item in data:
        t.add_row(str(item["id"]), item["title"], clients(item))
    console.print(t)
    return None


@cli.group("list")
def list_group():
    """Archive, unarchive and copy to-do lists"""


@list_group.command("copy")
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


@list_group.command("archive")
@click.argument("list_id", metavar="LIST", type=int)
@json_option
def list_archive(list_id, as_json):
    """Archive LIST: readable, but out of the way (it stays out of your to-dos)"""
    data = request("PATCH", f"lists/{list_id}/", json={"archived": True})
    if as_json:
        return echo_json(data)
    click.echo(f"Archived {data['title']} ({data['id']}).")
    return None


@list_group.command("unarchive")
@click.argument("list_id", metavar="LIST", type=int)
@json_option
def list_unarchive(list_id, as_json):
    """Bring LIST back from the archive"""
    data = request("PATCH", f"lists/{list_id}/", json={"archived": False})
    if as_json:
        return echo_json(data)
    click.echo(f"Brought {data['title']} ({data['id']}) back from the archive.")
    return None


@cli.command()
@click.argument("list_id", metavar="[LIST]", type=int, required=False)
@click.option("--completed", is_flag=True, help="Completed to-dos, latest first.")
@click.option("--mine", is_flag=True, help="Only to-dos assigned to you.")
@click.option(
    "--assigned-by-me",
    is_flag=True,
    help="Only to-dos you assigned (to somebody else, or to you with --mine).",
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
def todos(
    list_id, completed, mine, assigned_by_me, project_id, due, by_due, started, as_json
):
    """The open to-dos of LIST, by group; without LIST across all projects,
    by project or by due date (--mine, --assigned-by-me, --project, --due,
    --by-due)"""
    if list_id and (
        mine or assigned_by_me or project_id or due or by_due or started is not None
    ):
        terminate(
            "--mine, --assigned-by-me, --project, --due, --by-due and"
            " --started/--not-started go without LIST."
        )
    if list_id and completed:
        data = paginate(f"lists/{list_id}/todos/completed/")
    elif list_id:
        data = request("GET", f"lists/{list_id}/todos/")
    else:
        params = {"completed": completed, "grouping": "due" if by_due else "project"}
        if mine:
            params["assignee"] = "me"
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


@todo.command("show")
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


@todo.command("add")
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


@todo.command("add-from-text")
@click.argument("list_id", metavar="LIST", type=int)
@click.argument("file", type=click.File(encoding="utf-8-sig"), required=False)
@click.option("--preview", is_flag=True, help="Show what would be added, add nothing.")
@json_option
def todo_add_from_text(list_id, file, preview, as_json):
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


@todo.command("edit")
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


@todo.command("move")
@click.argument("todo_id", metavar="[TODO]", type=int, required=False)
@click.option(
    "--todos",
    "todo_ids",
    help="Several to-dos' IDs, comma separated, instead of TODO; they end up"
    " next to each other in this order.",
)
@click.option("--list", "list_id", type=int, required=True, help="The list's ID.")
@click.option("--group", type=int, help="The group's ID (default: ungrouped).")
@json_option
def todo_move(todo_id, todo_ids, list_id, group, as_json):
    """Move TODO (or --todos) to the end of a list of the same project, into
    a group or ungrouped"""
    if bool(todo_id) == bool(todo_ids):
        terminate("Give either TODO or --todos.")
    if todo_id:
        data = [
            request(
                "POST",
                f"todos/{todo_id}/move/",
                json={"list_id": list_id, "group_id": group},
            )
        ]
    else:
        try:
            ids = [int(part) for part in todo_ids.split(",")]
        except ValueError:
            terminate("--todos takes IDs separated by commas.")
        data = request(
            "POST",
            f"lists/{list_id}/todos/move/",
            json={"todo_ids": ids, "group_id": group},
        )
    if as_json:
        return echo_json(data[0] if todo_id else data)
    for moved in data:
        click.echo(f"Moved #{moved['id']} {moved['title']}.")
    return None


@todo.command("assign")
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


# Subscribers ----------------------------------------------------------------


def show_subscribers(data):
    marker = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"Subscribers of #{data['item_id']}{marker}:")
    t = table("ID", "Name", "Added by")
    for row in data["subscribers"]:
        added_by = row["added_by"]
        t.add_row(
            str(row["person"]["id"]),
            row["person"]["name"],
            added_by["name"] if added_by else "",
        )
    console.print(t)


@cli.command()
@click.argument("item", type=int)
@json_option
def subscribers(item, as_json):
    """Who gets what happens to ITEM (any kind of item), and who added them"""
    data = request("GET", f"items/{item}/subscribers/")
    if as_json:
        return echo_json(data)
    show_subscribers(data)
    return None


@cli.command()
@click.argument("item", type=int)
@click.option(
    "--people",
    default="",
    help="The IDs of the people to subscribe, separated by commas; without"
    " it, yourself.",
)
@click.option(
    "--notify", is_flag=True, help="Tell them now, with a notification at once."
)
@click.option(
    "--note", default="", help="One line sent with --notify, at most 200 characters."
)
@json_option
def subscribe(item, people, notify, note, as_json):
    """Subscribe yourself or other people to ITEM: subscribed, you hear
    about everything on it. Others: people who can see it (clients and
    externals: whom they may know). Quietly, or with --notify: "Ada wants
    you to see this". Marked [clients] if clients can see it."""
    if not people.strip():
        data = request("PUT", f"items/{item}/subscription/")
        if as_json:
            return echo_json(data)
        click.echo(f"Subscribed to #{item}.")
        return None
    try:
        ids = [int(part) for part in people.split(",") if part.strip()]
    except ValueError:
        raise click.UsageError("--people takes IDs separated by commas.") from None
    data = request(
        "POST",
        f"items/{item}/subscribers/",
        json={"people": ids, "notify": notify, "note": note},
    )
    if as_json:
        return echo_json(data)
    if data["visible_to_clients"]:
        click.secho("Clients can see this.", fg="yellow", err=True)
    click.echo(f"Subscribed {len(ids)} to #{item}{' and told them' if notify else ''}.")
    show_subscribers(data)
    return None


@cli.command()
@click.argument("item", type=int)
@json_option
def unsubscribe(item, as_json):
    """Stop hearing about ITEM (not while you're assigned to it)"""
    data = request("DELETE", f"items/{item}/subscription/")
    if as_json:
        return echo_json(data)
    click.echo(f"Unsubscribed from #{item}.")
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
            asked,
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
    occurrences = paginate(f"checkins/{question_id}/occurrences/", limit=limit)
    if as_json:
        return echo_json(data | {"occurrences": occurrences})
    marker = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"#{data['id']} {data['title']}{marker}")
    for label, value in [
        ("Asked", f"{data['schedule_description']}, {data['time_of_day'][:5]}"),
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
@click.option(
    "--time",
    "time_of_day",
    required=True,
    help="HH:MM, in the installation's time zone.",
)
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
@click.argument("question_id", metavar="[QUESTION]", type=int, required=False)
@click.option(
    "--project",
    "project_id",
    type=int,
    help="Resume all the paused check-ins of this project",
)
@json_option
def checkin_resume(question_id, project_id, as_json):
    """Ask QUESTION, or with --project all its paused check-ins, again from
    the next date; what was missed isn't asked (staff)"""
    if (question_id is None) == (project_id is None):
        raise click.UsageError("Give a QUESTION or --project, not both.")
    if project_id is not None:
        data = request("POST", f"projects/{project_id}/checkins/resume/")
        if as_json:
            return echo_json(data)
        click.echo(f"Resumed {len(data)} check-in(s).")
        return None
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

also_option = click.option(
    "--also",
    default="",
    metavar="IDS",
    help="People's IDs separated by commas to tell too, besides those who"
    " want to hear (the folder's subscribers, people notified of everything).",
)
visible_option = click.option(
    "--visible", is_flag=True, help="Visible to clients (staff; clients always are)."
)


def people_ids(value):
    """The IDs of ``--also`` as a list"""
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError:
        terminate("--also is people's IDs separated by commas.")


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
@click.option(
    "--order",
    type=click.Choice(["latest", "newest"]),
    help="Latest update (posting or comment) or newest posts first (default: "
    "the board's order).",
)
@json_option
def messages(project, limit, order, as_json):
    """The message board of PROJECT: pinned first, then in the board's
    order"""
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
        data["comments"] = paginate(f"items/{message_id}/comments/")
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
    click.echo(f"Order: {data['ordering']}")
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


@cli.command("move")
@click.argument("item", type=int)
@click.option("--to", "project", type=int, required=True, help="The project's ID.")
@click.option(
    "--confirm",
    is_flag=True,
    help="Move it although people are dropped or clients there will see it.",
)
@json_option
def move(item, project, confirm, as_json):
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


@folder.command("rename")
@click.argument("folder_id", metavar="FOLDER", type=int)
@click.argument("title")
@json_option
def folder_rename(folder_id, title, as_json):
    """Rename FOLDER to TITLE"""
    data = request("PATCH", f"folders/{folder_id}/", json={"title": title})
    if as_json:
        return echo_json(data)
    click.echo(f"Renamed #{folder_id}: {data['folder']['title']}")
    return None


@folder.command("color")
@click.argument("folder_id", metavar="FOLDER", type=int)
@click.argument("color", type=click.Choice([*PALETTE, "none"]))
@json_option
def folder_color(folder_id, color, as_json):
    """Give FOLDER a color (a name of the palette), or 'none'"""
    data = request(
        "PATCH",
        f"folders/{folder_id}/",
        json={"color": "" if color == "none" else color},
    )
    if as_json:
        return echo_json(data)
    click.echo(f"#{folder_id}: {data['color_name'] or 'no color'}")
    return None


ORDERINGS = ["alphabetical", "reverse", "newest", "oldest"]


@folder.command("order")
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


@cli.group("file")
def file_group():
    """Upload, replace and download files"""


@file_group.command("upload")
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
        data["comments"] = paginate(f"items/{doc_id}/comments/")
    if as_json:
        return echo_json(data)
    marker = " [clients]" if data["visible_to_clients"] else ""
    click.echo(f"#{data['id']} {data['title']}{marker}")
    if data["read_only"]:
        click.echo("Read-only.")
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


@doc.command("edit")
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


@doc.command("read-only")
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
            result["title"],
            result["project_name"] + (" (archived)" if result["archived"] else ""),
            found,
            clients(result),
        )
    console.print(t)
    return None


# Public links ---------------------------------------------------------------


def show_public_link(link):
    item = link["item"]
    click.echo(f"#{item['id']} {item['title']} {clients(item)}".rstrip())
    click.echo(link["url"])
    click.echo(f"Expires {link['expires_at'][:16].replace('T', ' ')}")


@cli.command("public-links")
@json_option
def public_links(as_json):
    """The live public links in the projects you can open (admins: all),
    the soonest expiry first (staff)"""
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


@cli.command()
@click.argument("item", type=int)
@click.option(
    "--days",
    type=click.Choice(["1", "3", "7", "30"]),
    default="7",
    show_default=True,
    help="How long the link works.",
)
@json_option
def share(item, days, as_json):
    """A public link to ITEM (a to-do, message, doc or file) for people
    without an account, read only, until it expires;
    replaces the one there is (staff)"""
    data = request("POST", f"items/{item}/public-link/", json={"days": int(days)})
    if as_json:
        return echo_json(data)
    show_public_link(data)
    return None


@cli.command()
@click.argument("item", type=int)
@json_option
def unshare(item, as_json):
    """Stop sharing ITEM publicly: its public link stops working (staff)"""
    data = request("DELETE", f"items/{item}/public-link/")
    if as_json:
        return echo_json(data)
    click.echo(f"Stopped sharing #{item} publicly.")
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
    """The links to outside tools of PROJECT"""
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


@cli.group()
def link():
    """Add and delete links to outside tools"""


@link.command("add")
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


@link.command("delete")
@click.argument("link_id", metavar="LINK", type=int)
def link_delete(link_id):
    """Delete LINK"""
    request("DELETE", f"links/{link_id}/")
    click.echo(f"Deleted link #{link_id}.")


# Notifications --------------------------------------------------------------

LEVELS = ["everything", "concerns_me"]


WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_days(value):
    """ "mon-fri", "mon,wed,fri" or "sat,sun" as 0 (Monday) to 6"""
    days = set()
    for part in value.lower().replace(" ", "").split(","):
        first, _dash, last = part.partition("-")
        if first not in WEEKDAYS or (last and last not in WEEKDAYS):
            raise click.BadParameter(f"{part!r}: use mon, tue, …, sun or mon-fri.")
        start, end = WEEKDAYS.index(first), WEEKDAYS.index(last or first)
        if end < start:
            raise click.BadParameter(f"{part!r}: from an earlier day to a later one.")
        days.update(range(start, end + 1))
    return sorted(days)


def show_days(days):
    return ",".join(WEEKDAYS[day] for day in days) or "none"


@cli.command()
@click.option(
    "--level",
    type=click.Choice([*LEVELS, "default"]),
    help="What to be told about; 'default' removes a project's or list's own.",
)
@click.option(
    "--delivery", type=click.Choice(["each", "digest", "none"]), help="Mails."
)
@click.option(
    "--quiet-hours",
    type=click.Choice(["on", "off"]),
    help="Mails and digests wait outside your working days and hours.",
)
@click.option(
    "--working-days", help="The working days for quiet hours: mon-fri, mon,wed,fri…"
)
@click.option(
    "--from",
    "working_from",
    metavar="HH:MM",
    help="When the working time starts (the installation's time zone).",
)
@click.option(
    "--until", "working_until", metavar="HH:MM", help="When the working time ends."
)
@click.option("--project", type=int, help="Show or set the level for PROJECT.")
@click.option(
    "--item",
    type=int,
    help="Show or set the level for a list (other items have none:"
    " biwak subscribe or unsubscribe them).",
)
@json_option
def notifications(
    level,
    delivery,
    quiet_hours,
    working_days,
    working_from,
    working_until,
    project,
    item,
    as_json,
):
    """Show and set your notification level, mail delivery and quiet hours.
    Levels decide what you're subscribed to automatically; subscribed, you
    hear about everything on the item."""
    quiet = {
        "quiet_hours": None if quiet_hours is None else quiet_hours == "on",
        "working_days": parse_days(working_days) if working_days else None,
        "working_from": working_from,
        "working_until": working_until,
    }
    if project and item:
        terminate("A project or an item, not both.")
    if project or item:
        if delivery or any(value is not None for value in quiet.values()):
            terminate(
                "The delivery and quiet hours are the same everywhere; leave out"
                " --project and --item."
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
    changes = {"level": level, "delivery": delivery} | quiet
    changes = {k: v for k, v in changes.items() if v is not None}
    if changes:
        data = request("PUT", "me/notifications/", json=changes)
    else:
        data = request("GET", "me/notifications/")
    if as_json:
        return echo_json(data)
    click.echo(f"Level: {data['level']}")
    click.echo(f"Delivery: {data['delivery']}")
    working = (
        f"{show_days(data['working_days'])}"
        f" {data['working_from'][:5]}-{data['working_until'][:5]}"
        f" ({data['time_zone']})"
    )
    if data["quiet_hours"]:
        click.echo(f"Quiet hours: on, mails go {working}")
    else:
        click.echo("Quiet hours: off")
    return None


@cli.command()
@click.option(
    "--until",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="The last day away (YYYY-MM-DD).",
)
@click.option("--note", default="", help="One line shown with your name.")
@click.option("--back", is_flag=True, help="End being away early.")
@click.option("--person", type=int, help="Somebody else (admins, when someone forgot).")
@json_option
def away(until, note, back, person, as_json):
    """Show whether you're away, or set an away time: nothing is mailed
    meanwhile, the day after one digest says what happened"""
    if until and back:
        terminate("--until or --back, not both.")
    path = f"people/{person}/away/" if person else "me/away/"
    if until:
        payload = {"until": until.date().isoformat(), "note": note}
        data = request("PUT", path, json=payload)
    elif back:
        data = request("DELETE", path)
    elif person:
        terminate("With --person: --until or --back.")
    else:
        data = request("GET", "me/")
    if as_json:
        return echo_json(data)
    if data.get("away_until"):
        note = f": {data['away_note']}" if data.get("away_note") else ""
        click.echo(f"{data['name']} is away until {data['away_until']}{note}")
    else:
        click.echo(f"{data['name']} isn't away.")
    return None


# The lantern ----------------------------------------------------------------


@cli.command()
@click.option("--unread", is_flag=True, help="Only those not read yet.")
@click.option("--mentions", is_flag=True, help="Only those mentioning you.")
@click.option("--read", "read_item", type=int, metavar="ITEM", help="Mark ITEM read.")
@click.option("--all", "read_all", is_flag=True, help="Mark everything read.")
@click.option("--limit", default=50, show_default=True, help="At most this many.")
@json_option
def lantern(unread, mentions, read_item, read_all, limit, as_json):
    """Your notifications by item, newest first, or mark them read"""
    if read_item is not None and read_all:
        terminate("An item or --all, not both.")
    if read_item is not None or read_all:
        data = request(
            "POST",
            "lantern/read/",
            json={"all": True} if read_all else {"item_id": read_item},
        )
        if as_json:
            return echo_json(data)
        click.echo(f"Marked {data['read']} as read.")
        return None
    params = {"unread": "true"} if unread else {}
    if mentions:
        params["mentions"] = "true"
    entries = paginate("lantern/", params, limit=limit)
    if as_json:
        return echo_json(entries)
    # One row per item with its newest entry first, as the menu groups them
    groups = {}
    for entry in entries:
        groups.setdefault((entry["event"]["item"] or {}).get("id"), []).append(entry)
    t = table("When", "", "Person", "Action", "Item", "What", "")
    for item_id, group in groups.items():
        entry = group[0]
        event = entry["event"]
        item = event["item"] or {}
        more = f" (+{len(group) - 1})" if len(group) > 1 else ""
        t.add_row(
            event["created_at"][:16].replace("T", " "),
            ("new" if any(not e["read"] for e in group) else "")
            + (" @" if any(e["mentioned"] for e in group) else "")
            + (" bookmarked" if entry["bookmarked"] else ""),
            event["actor"]["short_name"],
            event["action"].replace("_", " ") + more,
            str(item_id or ""),
            item.get("title", ""),
            clients(item),
        )
    console.print(t)
    return None
