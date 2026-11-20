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
