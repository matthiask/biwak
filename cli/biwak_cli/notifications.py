"""Subscriptions, notifications, push devices, being away and the lantern"""

import click

from biwak_cli.core import (
    actor,
    cli,
    clients,
    console,
    echo_json,
    json_option,
    link,
    need,
    paginate,
    request,
    table,
    terminate,
)


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


@cli.group(invoke_without_command=True)
@click.option("--item", type=int, help="The item's ID (any kind of item).")
@json_option
@click.pass_context
def subscriptions(ctx, item, as_json):
    """Subscriptions; without a command who gets what happens to --item,
    and who added them"""
    if ctx.invoked_subcommand is not None:
        return None
    need(item, "--item")
    data = request("GET", f"items/{item}/subscribers/")
    if as_json:
        return echo_json(data)
    show_subscribers(data)
    return None


@subscriptions.command("add")
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
def subscriptions_add(item, people, notify, note, as_json):
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


@subscriptions.command("remove")
@click.argument("item", type=int)
@json_option
def subscriptions_remove(item, as_json):
    """Stop hearing about ITEM (not while you're assigned to it)"""
    data = request("DELETE", f"items/{item}/subscription/")
    if as_json:
        return echo_json(data)
    click.echo(f"Unsubscribed from #{item}.")
    return None


# Devices getting push notifications -----------------------------------------


@cli.group(invoke_without_command=True)
@json_option
@click.pass_context
def devices(ctx, as_json):
    """Your devices getting push notifications (they subscribe in the
    browser's settings)"""
    if ctx.invoked_subcommand is not None:
        return None
    data = request("GET", "me/push-subscriptions/")
    if as_json:
        return echo_json(data)
    if not data:
        click.echo("No devices get push notifications.")
        return None
    t = table("ID", "Device", "Added", "Last used")
    for device in data:
        t.add_row(
            str(device["id"]),
            device["name"],
            device["created_at"][:16].replace("T", " "),
            (device["last_success_at"] or "never")[:16].replace("T", " "),
        )
    console.print(t)
    return None


@devices.command("test")
@click.argument("device", type=int)
@json_option
def devices_test(device, as_json):
    """Send a test push to DEVICE at once, also in quiet hours or while
    you're away"""
    data = request("POST", f"me/push-subscriptions/{device}/test/")
    if as_json:
        echo_json(data)
    else:
        click.echo(data["detail"], err=not data["sent"])
    if not data["sent"]:
        raise SystemExit(1)


@devices.command("delete")
@click.argument("device", type=int)
@json_option
def devices_delete(device, as_json):
    """Stop pushing to DEVICE (the browser keeps its subscription, unused,
    until it's turned off there)"""
    data = request("DELETE", f"me/push-subscriptions/{device}/")
    if as_json:
        return echo_json(data)
    click.echo(f"Removed {data['name']} ({data['id']}).")
    return None


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
    " biwak subscriptions add or remove them).",
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
    """Show and set your notification level, mail delivery and quiet
    hours.
    Levels decide what you're subscribed to automatically; subscribed, you
    hear about everything on the item."""
    mails = {
        "quiet_hours": None if quiet_hours is None else quiet_hours == "on",
        "working_days": parse_days(working_days) if working_days else None,
        "working_from": working_from,
        "working_until": working_until,
    }
    if project and item:
        terminate("A project or an item, not both.")
    if project or item:
        if delivery or any(value is not None for value in mails.values()):
            terminate(
                "The delivery and quiet hours are the same everywhere;"
                " leave out --project and --item."
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
    changes = {"level": level, "delivery": delivery} | mails
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
            actor(event),
            event["action"].replace("_", " ") + more,
            str(item_id or ""),
            link(item.get("title", ""), item.get("url")),
            clients(item),
        )
    console.print(t)
    return None
