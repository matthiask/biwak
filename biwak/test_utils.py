"""Made-up people and projects for the tests (no real data, AGENTS.md)"""

from html.parser import HTMLParser

from biwak.accounts.models import User
from biwak.organizations.models import Organization
from biwak.projects.models import Membership, Project


def organization(name="Example Client Ltd", **kwargs):
    """The organization of this name, created if needed; ``is_own=True``
    is the own organization, which always exists: it gets the name"""
    if kwargs.pop("is_own", False):
        own = Organization.objects.own()
        own.name = name
        for field, value in kwargs.items():
            setattr(own, field, value)
        own.save()
        return own
    return Organization.objects.get_or_create(name=name, defaults=kwargs)[0]


def person(name="Ada", *, client=False, **kwargs):
    """Clients belong to "Example Client Ltd", staff to the installation's
    own organization, unless ``organization`` says otherwise (a name, an
    organization or None: an individual, a partner if staff)"""
    if "organization" in kwargs:
        org = kwargs.pop("organization")
    else:
        org = "Example Client Ltd" if client else Organization.objects.own()
    if isinstance(org, str):
        org = organization(org) if org else None
    return User.objects.create_user(
        f"{name.lower()}@example.org",
        full_name=f"{name} Example",
        is_client=client,
        organization=org,
        **kwargs,
    )


def partner(name="Pia", *, organization_name="Example Partner Agency", **kwargs):
    """Staff of another organization: sees only the projects they're
    members of (specs/access.md)"""
    return person(name, organization=organization_name, **kwargs)


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


MODAL = {"HX-Modal": "true"}


def assert_modal(test, response, *, title):
    """The response is the form for the dialog (``biwak/modals.py``): no
    page around it, labelled by its title, which posts to the dialog"""
    test.assertEqual(response.status_code, 200)
    test.assertNotContains(response, "<html")
    test.assertNotContains(response, "wb-navbar")
    test.assertContains(response, f'id="modal-title">{title}</h1>')
    test.assertContains(response, 'hx-target="#modal"')


def assert_page(test, response, *, title):
    """The same form as a page of its own (without JavaScript)"""
    test.assertEqual(response.status_code, 200)
    test.assertContains(response, "<html")
    test.assertContains(response, f">{title}</h1>")
    test.assertNotContains(response, "hx-post")
    test.assertNotContains(response, 'id="modal-title"')


def assert_modal_redirect(test, response, url=None):
    """A modal form saved: the dialog's request is answered with
    ``HX-Redirect``, which loads the page"""
    test.assertEqual(response.status_code, 200)
    test.assertIn("HX-Redirect", response.headers)
    if url is not None:
        test.assertEqual(response.headers["HX-Redirect"], url)


def tags(html, *, cls, **attrs):
    """The start tags (their attributes) with the class ``cls`` among
    others and the ``attrs`` (``data_x`` for ``data-x``), in any order:
    what matters of an element without its other classes"""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            if cls in (attributes.get("class") or "").split() and all(
                attributes.get(name) == value for name, value in wanted.items()
            ):
                found.append(attributes)

    Parser().feed(html)
    return found
