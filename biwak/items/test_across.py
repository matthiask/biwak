"""Copying lists and moving top-level items to another project
(specs/lists-across-projects.md): the operations"""

import datetime as dt

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from biwak.activity.models import Action, Event, Subscription
from biwak.activity.operations import subscribe
from biwak.bookmarks.models import Bookmark
from biwak.files import attachments
from biwak.files.models import Attachment
from biwak.items import operations as ops, visibility
from biwak.items.models import Comment, Item, Kind, Status
from biwak.projects.models import Membership
from biwak.public_links import operations as link_ops
from biwak.public_links.models import PublicLink
from biwak.reactions import operations as reaction_ops
from biwak.test_utils import external, person, project


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.dan = person("Dan", client=True, organization="Example Shop Ltd")
        self.pitch = project("Pitch", members=[self.ada, self.bob, self.cleo])
        self.website = project("Website", members=[self.ada, self.dan])
        self.shop = project("Shop", members=[self.ada, self.dan], all_access=False)
        self.list = ops.create_list(
            project=self.pitch,
            title="Launch",
            creator=self.ada,
            description="The launch",
            visible=True,
        )
        self.todolist = self.list.todolist
        self.later = ops.create_group(todolist=self.todolist, title="Later")
        self.tent = ops.create_todo(
            todolist=self.list,
            title="Order the tent",
            creator=self.ada,
            notes="- [ ] poles\n- [x] pegs",
            due_on=dt.date(2026, 12, 1),
            assignees=[self.ada, self.bob],
            recurrence="FREQ=WEEKLY",
            recurrence_ends_on=dt.date(2027, 3, 1),
        )
        self.stove = ops.create_todo(
            todolist=self.list,
            title="Buy a stove",
            creator=self.cleo,
            group=self.later,
            assignees=[self.cleo],
        )
        self.maps = ops.create_todo(todolist=self.list, title="Maps", creator=self.ada)
        ops.complete(self.maps, actor=self.ada)
        ops.add_comment(self.tent, author=self.bob, content="Which size?")


class CopyListTest(Fixture, TestCase):
    def copy(self, **kwargs):
        kwargs.setdefault("project", self.pitch)
        kwargs.setdefault("title", "Launch")
        return ops.copy_list(self.list, actor=self.ada, **kwargs)

    def test_open_work(self):
        copy = self.copy(project=self.website)
        self.assertEqual(copy.project, self.website)
        self.assertEqual(copy.title, "Launch")
        self.assertEqual(copy.todolist.description, "The launch")
        self.assertEqual([g.title for g in copy.todolist.groups.all()], ["Later"])
        todos = list(ops.open_todos(copy))
        self.assertEqual([t.title for t in todos], ["Order the tent", "Buy a stove"])
        tent, stove = todos
        self.assertEqual(tent.todo.notes, "- [ ] poles\n- [x] pegs")
        self.assertEqual((tent.todo.checklist_done, tent.todo.checklist_total), (1, 2))
        self.assertEqual(tent.todo.recurrence, "FREQ=WEEKLY")
        self.assertEqual(tent.todo.due_on, dt.date(2026, 12, 1))
        self.assertIsNone(tent.todo.group)
        self.assertEqual(stove.todo.group.todolist, copy.todolist)
        self.assertEqual(stove.todo.group.title, "Later")
        self.assertEqual({t.creator for t in todos}, {self.ada})
        # Nothing else
        self.assertFalse(Comment.objects.filter(item__in=todos).exists())
        self.assertEqual(Item.objects.filter(parent=copy).count(), 2)
        self.assertEqual(
            list(Event.objects.filter(project=self.website).values_list("action")),
            [(Action.CREATED,)],
        )
        self.assertEqual(Event.objects.get(project=self.website).item, copy)
        self.assertEqual(
            list(Subscription.objects.filter(item=copy).values_list("user")),
            [(self.ada.pk,)],
        )
        # The source is untouched
        self.assertEqual(Item.objects.filter(parent=self.list).count(), 3)
        self.assertEqual(visibility.check(), [])

    def test_assignees(self):
        """Kept where they see the copy; staff who don't are added to the
        project, clients who don't are left out (decided 2026-11-22)"""
        # Website is all-access: Bob sees it as own staff
        self.assertEqual(
            [list(p) for p in ops.copy_people(self.list, self.website, visible=False)],
            [[], [self.cleo]],
        )
        copy = self.copy(project=self.website)
        tent, stove = ops.open_todos(copy)
        self.assertEqual(set(tent.todo.assignees.all()), {self.ada, self.bob})
        self.assertEqual(list(stove.todo.assignees.all()), [])
        self.assertFalse(self.website.is_member(self.bob))
        # Assigned means subscribed
        self.assertTrue(Subscription.objects.filter(item=tent, user=self.ada).exists())
        # Shop is limited: Bob is added
        self.assertEqual(
            [list(p) for p in ops.copy_people(self.list, self.shop, visible=False)],
            [[self.bob], [self.cleo]],
        )
        copy = self.copy(project=self.shop)
        tent, _stove = ops.open_todos(copy)
        self.assertEqual(set(tent.todo.assignees.all()), {self.ada, self.bob})
        self.assertTrue(self.shop.is_member(self.bob))
        self.assertTrue(
            Event.objects.filter(
                project=self.shop, action=Action.ADDED, data__user=self.bob.pk
            ).exists()
        )
        # Within the project: Cleo only if the copy is visible
        self.assertEqual(
            [list(p) for p in ops.copy_people(self.list, self.pitch, visible=True)],
            [[], []],
        )
        copy = self.copy(visible=True)
        _tent, stove = ops.open_todos(copy)
        self.assertEqual(list(stove.todo.assignees.all()), [self.cleo])
        copy = self.copy()
        _tent, stove = ops.open_todos(copy)
        self.assertEqual(list(stove.todo.assignees.all()), [])

    def test_title(self):
        """The list's own; " (copy)", " (copy 2)" only on a clash ignoring
        case (decided 2026-11-22)"""
        self.assertEqual(self.copy().title, "Launch (copy)")
        self.assertEqual(self.copy().title, "Launch (copy 2)")
        self.assertEqual(self.copy(title="launch").title, "launch (copy 3)")
        self.assertEqual(self.copy(project=self.website).title, "Launch")
        self.assertEqual(self.copy(project=self.website).title, "Launch (copy)")
        self.assertEqual(self.copy(title="Other").title, "Other")

    def test_dates(self):
        # Start dates move with due dates (start-dates.md)
        ops.update_todo(self.tent, actor=self.ada, starts_on=dt.date(2026, 11, 29))
        copy = self.copy(dates=ops.Dates.SHIFT, days=7)
        tent = ops.open_todos(copy).first()
        self.assertEqual(tent.todo.due_on, dt.date(2026, 12, 8))
        self.assertEqual(tent.todo.starts_on, dt.date(2026, 12, 6))
        copy = self.copy()
        self.assertEqual(
            ops.open_todos(copy).first().todo.starts_on, dt.date(2026, 11, 29)
        )
        copy = self.copy(dates=ops.Dates.SHIFT, days=7)
        self.assertEqual(tent.todo.recurrence_ends_on, dt.date(2027, 3, 8))
        copy = self.copy(dates=ops.Dates.SHIFT, days=-1)
        self.assertEqual(
            ops.open_todos(copy).first().todo.due_on, dt.date(2026, 11, 30)
        )
        copy = self.copy(dates=ops.Dates.REMOVE)
        tent = ops.open_todos(copy).first()
        self.assertIsNone(tent.todo.due_on)
        self.assertIsNone(tent.todo.starts_on)
        # The rule stays
        self.assertEqual(tent.todo.recurrence, "FREQ=WEEKLY")

    def test_visibility(self):
        """The target's: internal unless asked for"""
        copy = self.copy(project=self.website)
        self.assertFalse(copy.is_client_visible)
        self.assertFalse(
            Item.objects.filter(parent=copy, is_client_visible=True).exists()
        )
        copy = self.copy(project=self.website, visible=True)
        self.assertTrue(copy.is_client_visible)
        self.assertEqual(
            Item.objects.filter(parent=copy, is_client_visible=False).count(), 0
        )
        self.assertEqual(visibility.check(), [])
        self.assertTrue(Event.objects.get(item=copy).is_client_visible)

    def test_attachments(self):
        """Copied: new files, not shared rows"""
        attachment = attachments.upload(
            project=self.pitch,
            file=ContentFile(b"plan", name="plan.txt"),
            uploaded_by=self.ada,
        )
        ops.update_todo(
            self.tent,
            actor=self.ada,
            notes=f"See [plan.txt](attachment:{attachment.key})",
        )
        copy = self.copy(project=self.website)
        tent = ops.open_todos(copy).first()
        new = Attachment.objects.get(item=tent)
        self.assertNotEqual(new.key, attachment.key)
        self.assertEqual(new.project, self.website)
        self.assertEqual(tent.todo.notes, f"See [plan.txt](attachment:{new.key})")
        self.assertNotEqual(new.file.name, attachment.file.name)
        with new.file.open("rb") as file:
            self.assertEqual(file.read(), b"plan")
        self.assertEqual(Attachment.objects.get(pk=attachment.pk).item, self.tent)

    def test_archived_project(self):
        self.website.archived_at = timezone.now()
        self.website.save()
        with self.assertRaises(ValueError):
            self.copy(project=self.website)
        self.assertFalse(Item.objects.filter(project=self.website).exists())


class MoveToProjectTest(Fixture, TestCase):
    def test_everything_comes_along(self):
        tent_comment = Comment.objects.get(item=self.tent)
        reaction_ops.add_reaction(self.bob, "👍", item=self.tent)
        link = link_ops.create_public_link(self.tent, days=7, actor=self.ada)
        Bookmark.objects.create(user=self.ada, item=self.list)
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.website)
        self.assertEqual(
            set(
                Item.objects.filter(parent=self.list).values_list("project", flat=True)
            ),
            {self.website.pk},
        )
        self.assertEqual(Comment.objects.get(pk=tent_comment.pk).item, self.tent)
        self.assertTrue(self.tent.reactions.exists())
        # Except its public links, which end (specs/public-links.md)
        self.assertFalse(PublicLink.objects.filter(pk=link.pk).exists())
        self.assertTrue(Bookmark.objects.filter(item=self.list).exists())
        # Every event moves, the old project keeps only the trace
        self.assertFalse(
            Event.objects.filter(project=self.pitch, item__isnull=False).exists()
        )
        moved = Event.objects.get(item=self.list, action=Action.MOVED)
        self.assertEqual(moved.project, self.website)
        self.assertEqual(
            moved.data,
            moved.data
            | {
                "from_project": "Pitch",
                "from_project_id": self.pitch.pk,
                "to_project": "Website",
                "to_project_id": self.website.pk,
            },
        )
        self.assertTrue(
            Event.objects.filter(
                project=self.website, item=self.tent, action=Action.COMMENTED
            ).exists()
        )
        self.assertEqual(visibility.check(), [])

    def test_people_not_in_the_target(self):
        """Assigned staff and externals who don't see it there are added,
        clients and subscribers who don't are dropped (decided 2026-11-22)"""
        pia = external()
        Membership.objects.create(project=self.pitch, user=pia)
        ops.assign(self.tent, [pia], actor=self.ada)
        subscribe(self.bob, self.list)
        eve = person("Eve")
        subscribe(eve, self.list)
        self.assertEqual(
            [list(p) for p in ops.move_people(self.list, self.shop)],
            [[self.bob, pia], [self.cleo, eve]],
        )
        ops.move_to_project(self.list, project=self.shop, actor=self.ada)
        self.assertEqual(set(self.tent.todo.assignees.all()), {self.ada, self.bob, pia})
        self.assertEqual(list(self.stove.todo.assignees.all()), [])
        self.assertTrue(self.shop.is_member(self.bob))
        self.assertTrue(self.shop.is_member(pia))
        self.assertFalse(self.shop.is_member(self.cleo))
        self.assertFalse(self.shop.is_member(eve))
        self.assertFalse(
            Subscription.objects.filter(
                user__in=[self.cleo, eve], item__project=self.shop
            ).exists()
        )
        self.assertTrue(
            Subscription.objects.filter(user=self.bob, item=self.list).exists()
        )
        # The unassigning is history: recorded, telling nobody
        self.assertTrue(
            Event.objects.filter(item=self.stove, action=Action.UNASSIGNED).exists()
        )

    def test_people_who_see_it_stay(self):
        """Own staff of an all-access project see it there: nobody added"""
        subscribe(self.bob, self.list)
        self.assertEqual(
            [list(p) for p in ops.move_people(self.list, self.website)],
            [[], [self.cleo]],
        )
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        self.assertEqual(set(self.tent.todo.assignees.all()), {self.ada, self.bob})
        self.assertFalse(self.website.is_member(self.bob))

    def test_a_trace_in_the_old_project(self):
        """For its staff (decided 2026-11-22)"""
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        trace = Event.objects.get(project=self.pitch, action=Action.MOVED)
        self.assertIsNone(trace.item)
        self.assertFalse(trace.is_client_visible)
        self.assertEqual(trace.data["title"], "Launch")
        self.assertEqual(trace.data["to_project_id"], self.website.pk)

    def test_completed_todos_keep_their_assignees(self):
        ops.assign(self.maps, [self.bob], actor=self.ada)
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        self.assertEqual(list(self.maps.todo.assignees.all()), [self.bob])

    def test_new_clients(self):
        """Who'd see it there and doesn't now"""
        self.assertEqual(list(ops.new_clients(self.list, self.website)), [self.dan])
        Membership.objects.create(project=self.pitch, user=self.dan)
        self.assertEqual(list(ops.new_clients(self.list, self.website)), [])
        internal = ops.create_list(
            project=self.pitch, title="Internal", creator=self.ada
        )
        self.assertEqual(list(ops.new_clients(internal, self.website)), [])

    def test_keeps_the_switch(self):
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        self.list.refresh_from_db()
        self.assertTrue(self.list.visible_to_clients)
        self.assertTrue(self.list.is_client_visible)
        doc = ops.create_doc(project=self.pitch, title="Plan", creator=self.ada)
        ops.move_to_project(doc, project=self.website, actor=self.ada)
        doc.refresh_from_db()
        self.assertFalse(doc.is_client_visible)

    def test_top_level_kinds(self):
        message = ops.create_message(project=self.pitch, title="Hi", creator=self.ada)
        folder = ops.create_folder(project=self.pitch, title="Maps", creator=self.ada)
        doc = ops.create_doc(
            project=self.pitch, title="Plan", creator=self.ada, parent=folder
        )
        file = ops.create_upload(
            project=self.pitch,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
        )
        for item in [message, folder, file]:
            with self.subTest(kind=item.kind):
                ops.move_to_project(item, project=self.website, actor=self.ada)
                item.refresh_from_db()
                self.assertEqual(item.project, self.website)
        doc.refresh_from_db()
        self.assertEqual(doc.project, self.website)
        self.assertEqual(doc.parent, folder)

    def test_refused(self):
        folder = ops.create_folder(project=self.pitch, title="Maps", creator=self.ada)
        doc = ops.create_doc(
            project=self.pitch, title="Plan", creator=self.ada, parent=folder
        )
        for item, target in [
            (doc, self.website),
            (self.tent, self.website),
            (self.list, self.pitch),
        ]:
            with self.subTest(item=item.title), self.assertRaises(ValueError):
                ops.move_to_project(item, project=target, actor=self.ada)
        for archived in [self.pitch, self.website]:
            archived.archived_at = timezone.now()
            archived.save()
            with self.subTest(archived=archived.name), self.assertRaises(ValueError):
                ops.move_to_project(self.list, project=self.website, actor=self.ada)
            archived.archived_at = None
            archived.save()
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.pitch)

    def test_attachments_follow(self):
        attachment = attachments.upload(
            project=self.pitch,
            file=ContentFile(b"plan", name="plan.txt"),
            uploaded_by=self.ada,
        )
        ops.add_comment(
            self.tent, author=self.ada, content=f"[plan](attachment:{attachment.key})"
        )
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        attachment.refresh_from_db()
        self.assertEqual(attachment.project, self.website)

    def test_position(self):
        ops.create_list(project=self.website, title="Other", creator=self.ada)
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        self.assertEqual(
            list(
                Item.objects.filter(
                    project=self.website, kind=Kind.LIST, parent=None
                ).values_list("title", flat=True)
            ),
            ["Other", "Launch"],
        )

    def test_trashed_children_come_along(self):
        ops.trash(self.stove, actor=self.ada)
        ops.move_to_project(self.list, project=self.website, actor=self.ada)
        self.stove.refresh_from_db()
        self.assertEqual(self.stove.project, self.website)
        self.assertEqual(self.stove.status, Status.TRASHED)
