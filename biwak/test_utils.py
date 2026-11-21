"""Made-up people and projects for the tests (no real data, AGENTS.md)"""

from biwak.accounts.models import User
from biwak.projects.models import Membership, Project


def person(name="Ada", *, client=False, **kwargs):
    return User.objects.create_user(
        f"{name.lower()}@example.org",
        full_name=f"{name} Example",
        is_client=client,
        organization="Example Client Ltd" if client else "",
        **kwargs,
    )


def project(name="Website", *, members=(), all_access=True):
    p = Project.objects.create(name=name, is_all_access=all_access)
    for user in members:
        Membership.objects.create(project=p, user=user)
    return p


def rule_post(rule, name="recurrence"):
    """What the rule widget posts for ``rule`` (the fields it shows, as a
    browser sends them); rules it can't show post what leaving it alone
    does: the hidden field"""
    from biwak import schedules

    if (fields := schedules.rule_fields(rule)) is None:
        return {f"{name}_keep": "1"}
    return {
        f"{name}_{key}": value
        for key, value in fields.items()
        if value not in (None, "")
    }


def check_in_answers(project, people, *, content="Giraffes everywhere"):
    """A check-in question of the project, asked once, which each of
    ``people`` answered; returns the answers' items"""
    from biwak.checkins import operations as checkin_ops
    from biwak.checkins.support import MONDAY_9, at

    question = checkin_ops.create_question(
        project=project,
        title="How is the camp?",
        creator=people[0],
        people=people,
        now=at("2027-03-19 12:00"),
        **MONDAY_9,
    )
    checkin_ops.run(now=at("2027-03-22 09:00"))
    return [checkin_ops.answer(question, user=user, content=content) for user in people]
