"""Check-ins: questions asked again and again, and their answers"""

import click

from biwak_cli.core import (
    attach_option,
    cli,
    clients,
    console,
    echo_json,
    echo_linked,
    json_option,
    link,
    names,
    need,
    paginate,
    request,
    table,
    with_attachments,
)


@cli.group(invoke_without_command=True)
@click.option("--project", type=int, help="The project's ID.")
@json_option
@click.pass_context
def checkins(ctx, project, as_json):
    """Check-in questions; without a command those of --project with their
    schedules"""
    if ctx.invoked_subcommand is not None:
        return None
    need(project, "--project")
    data = request("GET", f"projects/{project}/checkins/")
    if as_json:
        return echo_json(data)
    t = table("ID", "Question", "Asked", "Next", "")
    for question in data:
        asked = f"{question['schedule_description']}, {question['time_of_day'][:5]}"
        t.add_row(
            str(question["id"]),
            link(question["title"], question.get("url")),
            asked,
            "paused"
            if question["paused"]
            else (question["next_at"] or "")[:16].replace("T", " "),
            clients(question),
        )
    console.print(t)
    return None


def show_answers(occurrence):
    click.echo(f"\n{occurrence['date']} (#{occurrence['id']})")
    for answer in occurrence["answers"]:
        click.echo(f"\n{answer['author']['name']}:")
        click.echo(answer["content"])
    if occurrence["missing"]:
        click.echo(f"\nHasn't answered yet: {names(occurrence['missing'])}")


@checkins.command("show")
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
    echo_linked(f"#{data['id']} ", link(data["title"], data.get("url")), marker)
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


@checkins.command("answer")
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


@checkins.command("due")
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
            link(due["title"], due.get("url")),
            due["project_name"],
            due["date"],
            str(due["occurrence_id"]),
            clients(due),
        )
    console.print(t)
    return None


@checkins.command("create")
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


@checkins.command("pause")
@click.argument("question_id", metavar="QUESTION", type=int)
@json_option
def checkin_pause(question_id, as_json):
    """Stop asking QUESTION (staff)"""
    data = request("PATCH", f"checkins/{question_id}/", json={"paused": True})
    if as_json:
        return echo_json(data)
    click.echo(f"Paused #{question_id}.")
    return None


@checkins.command("resume")
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


@checkins.command("mail")
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
