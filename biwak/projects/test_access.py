from django.test import TestCase

from biwak.activity.models import Event
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects.models import Membership, Project
from biwak.test_utils import person, project


class ProjectAccessTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")  # member
        self.bob = person("Bob")  # staff, not a member
        self.admin = person("Root", is_admin=True)
        self.cleo = person("Cleo", client=True)  # member
        self.dora = person("Dora", client=True)  # not a member
        self.open = project("Open", members=[self.ada, self.cleo])
        self.limited = project("Limited", members=[self.ada], all_access=False)

    def accessible(self, user):
        return set(Project.objects.accessible_to(user))

    def test_projects(self):
        self.assertEqual(self.accessible(self.ada), {self.open, self.limited})
        self.assertEqual(self.accessible(self.bob), {self.open})
        # Admins see limited projects only by joining
        self.assertEqual(self.accessible(self.admin), {self.open})
        self.assertEqual(self.accessible(self.cleo), {self.open})
        self.assertEqual(self.accessible(self.dora), set())

    def test_inactive_people(self):
        self.ada.is_active = False
        self.ada.save()
        self.assertEqual(self.accessible(self.ada), set())

    def test_items_and_events(self):
        internal = ops.create_list(
            project=self.open, title="Internal", creator=self.ada
        )
        shared = ops.create_list(
            project=self.open, title="Shared", creator=self.ada, visible=True
        )
        secret = ops.create_list(
            project=self.limited, title="Salaries", creator=self.ada
        )
        Membership.objects.create(project=self.limited, user=self.cleo)

        self.assertEqual(set(Item.objects.visible_to(self.bob)), {internal, shared})
        self.assertEqual(
            set(Item.objects.visible_to(self.ada)), {internal, shared, secret}
        )
        # A client member of a limited project still sees only what's visible
        self.assertEqual(set(Item.objects.visible_to(self.cleo)), {shared})
        self.assertEqual(
            {e.item for e in Event.objects.visible_to(self.cleo)}, {shared}
        )
        self.assertEqual(
            {e.item for e in Event.objects.visible_to(self.bob)}, {internal, shared}
        )
