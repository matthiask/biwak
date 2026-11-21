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


def invite_data(projects, *rows, notify="default"):
    """What the invite form (``biwak/projects/invitations.py``) posts for
    ``rows``, dicts of a row's fields (email, full_name, organization,
    create_organization, is_client), to ``projects``"""
    data = {
        "projects": [getattr(p, "pk", p) for p in projects],
        "notify": notify,
        "person-TOTAL_FORMS": str(len(rows)),
        "person-INITIAL_FORMS": "0",
        "person-MIN_NUM_FORMS": "1",
        "person-MAX_NUM_FORMS": "50",
    }
    for index, values in enumerate(rows):
        for key, value in values.items():
            data[f"person-{index}-{key}"] = value
    return data


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


# Both identity providers set up, with made-up apps (specs/sso.md)
SSO_PROVIDERS = {
    "google": {
        "APPS": [{"client_id": "google-id", "secret": "google-secret"}],
        "SCOPE": ["openid", "profile", "email"],
    },
    "microsoft": {
        "APPS": [
            {
                "client_id": "microsoft-id",
                "secret": "microsoft-secret",
                "settings": {"tenant": "organizations"},
            }
        ],
        "SCOPE": ["openid", "email", "profile", "User.Read"],
    },
}


def sign_in_with(client, user, provider="google", *, at=None, claims=None):
    """Logged in as somebody who signed in through the identity provider
    ``at`` (a timestamp, default now), as allauth records it and with what
    counted (``biwak.accounts.sso.remember_sign_in``): ``hd`` the first of
    the organization's domains, ``tid`` its tenant, unless ``claims`` say
    otherwise"""
    import time

    at = time.time() if at is None else at
    # As stored now
    org = Organization.objects.filter(pk=user.organization_id).first()
    client.force_login(user)
    session = client.session
    session["account_authentication_methods"] = [
        {"method": "socialaccount", "at": at, "provider": provider, "uid": "1234"}
    ]
    session["account_authentication_methods_user"] = str(user.pk)
    session["biwak_sso"] = {  # sso.SESSION_KEY
        "user": user.pk,
        "org": org.pk if org else None,
        "email": user.email,
        "provider": provider,
        "hd": org.domains[0] if org and org.domains and provider == "google" else None,
        "tid": org.tenant_id if org and provider == "microsoft" else None,
        "at": at,
    } | (claims or {})
    session.save()


def bare_doc(**kwargs):
    """A doc whose text is exactly ``content``, without the heading
    ``create_doc()`` puts in front (specs/doc-titles.md), for tests of the
    text itself; the title stays what's given"""
    from biwak.items import operations as ops
    from biwak.items.models import Doc, DocVersion

    content = kwargs.pop("content", "")
    item = ops.create_doc(**kwargs)
    Doc.objects.filter(item=item).update(content=content)
    DocVersion.objects.filter(doc_id=item.pk).update(content=content)
    item.doc.refresh_from_db()
    return item
