"""People, invitations, organizations and teams"""

import click

from biwak_cli.core import (
    cli,
    console,
    echo_json,
    json_option,
    notify_option,
    request,
    table,
    terminate,
    with_away,
)


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


@invitations.command("create")
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
@notify_option
@json_option
def invitations_create(
    emails,
    projects,
    organization,
    organization_id,
    staff,
    notify_about_everything,
    as_json,
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
            "notify": "default" if notify_about_everything else "tagged",
        },
    )
    if as_json:
        return echo_json(data)
    for invited in data:
        word = "Invited" if invited["created"] else "Added"
        click.echo(f"{word}: {invited['person']['name']} ({invited['person']['id']})")
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


@orgs.command("create")
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


@orgs.command("update")
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


@teams.command("create")
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


@teams.command("update")
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
