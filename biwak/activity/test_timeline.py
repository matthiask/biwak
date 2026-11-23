import datetime as dt
import re

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.items.models import Comment, Item
from biwak.test_utils import person, project


def region(response):
    """The text of the timeline's lines, one string per line (without the
    reactions to completing it)"""
    html = response.content.decode()
    lines = re.findall(
        r'<div class="wb-timeline-line".*?(?=</div>|<div\s+class="wb-reactions")',
        html,
        flags=re.DOTALL,
    )
    return [" ".join(re.sub(r"<[^>]+>", " ", line).split()) for line in lines]


class TimelineBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal plans", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared plans", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        Event.objects.all().delete()

    def lines(self, user=None, item=None):
        item = item or self.todo
        self.client.force_login(user or self.ada)
        response = self.client.get(item.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        return region(response)

    def age(self, event_or_action, minutes):
        """Moves an event into the past"""
        events = Event.objects.filter(action=event_or_action)
        events.update(created_at=timezone.now() - dt.timedelta(minutes=minutes))


class LinesTest(TimelineBase):
    def test_nothing_happened(self):
        self.assertEqual(self.lines(), [])

    def test_completed_and_reopened(self):
        ops.complete(self.todo, actor=self.ada)
        self.age(Action.COMPLETED, 120)
        ops.reopen(self.todo, actor=self.bob)
        first, second = self.lines()
        self.assertTrue(first.startswith("Ada completed this"), first)
        self.assertTrue(second.startswith("Bob reopened this"), second)
        self.assertIn("2 hours ago", first)

    def test_relative_times_say_just_now(self):
        # The ago filter, like everywhere (specs/ui.md), not "now"
        ops.complete(self.todo, actor=self.ada)
        (line,) = self.lines()
        self.assertTrue(line.endswith("· just now"), line)

    def test_the_exact_time_is_the_title(self):
        ops.complete(self.todo, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(self.todo.get_absolute_url())
        when = Event.objects.get().created_at
        self.assertContains(
            response, f'title="{timezone.localtime(when):%a, %-d %b %Y, %H:%M}"'
        )

    def test_moved_to_a_list_and_a_group(self):
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        other = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        ops.move_todo(self.todo, todolist=other, actor=self.ada)
        self.age(Action.MOVED, 60)
        ops.move_todo(self.todo, todolist=other, group=None, actor=self.bob)
        # Into a group of the list it's in
        other_group = ops.create_group(todolist=other.todolist, title="Later")
        ops.move_todo(self.todo, todolist=other, group=other_group, actor=self.bob)
        self.assertEqual(group.title, "Done")
        first, second = self.lines()
        self.assertTrue(first.startswith("Ada moved this to Plans"), first)
        self.assertTrue(second.startswith("Bob moved this to Later"), second)

    def test_moved_out_of_its_group(self):
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.move_todo(self.todo, todolist=self.shared, group=group, actor=self.ada)
        self.age(Action.MOVED, 60)
        ops.move_todo(self.todo, todolist=self.shared, group=None, actor=self.ada)
        first, second = self.lines()
        self.assertIn("moved this to Done", first)
        self.assertIn("moved this out of its group", second)

    def test_assigned_and_unassigned(self):
        ops.assign(self.todo, [self.bob, self.ada], actor=self.ada)
        self.age(Action.ASSIGNED, 60)
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        first, second = self.lines()
        self.assertIn("assigned Bob and Ada", first.replace("  ", " "))
        self.assertIn("removed Bob", second)

    def test_title_and_due_date(self):
        ops.update_todo(
            self.todo,
            actor=self.ada,
            title="Order two tents",
            due_on=dt.date(2026, 12, 1),
        )
        self.age(Action.EDITED, 60)
        ops.update_todo(self.todo, actor=self.bob, due_on=None)
        first, second = self.lines()
        self.assertIn("changed the title to “Order two tents”", first)
        self.assertIn("set the due date to 1 Dec 2026", first)
        self.assertIn("removed the due date", second)

    def test_notes_edits_and_old_edits_are_not_shown(self):
        ops.update_todo(self.todo, actor=self.ada, notes="Blue ones")
        # Recorded before edits said what they changed
        Event.objects.create(
            project=self.project,
            item=self.todo,
            actor=self.ada,
            action=Action.EDITED,
            is_client_visible=True,
        )
        self.assertEqual(self.lines(), [])

    def test_the_creation_comments_and_reactions_are_not_shown(self):
        ops.add_comment(self.todo, author=self.bob, content="Blue or green?")
        ops.create_todo(todolist=self.shared, title="Another", creator=self.ada)
        self.assertEqual(self.lines(), [])

    def test_trashed_and_restored(self):
        ops.trash(self.todo, actor=self.ada)
        self.age(Action.TRASHED, 60)
        ops.restore(self.todo, actor=self.bob)
        first, second = self.lines()
        self.assertIn("trashed this", first)
        self.assertIn("restored this", second)

    def test_comments_and_lines_in_one_list_oldest_first(self):
        ops.complete(self.todo, actor=self.ada)
        self.age(Action.COMPLETED, 120)
        ops.add_comment(self.todo, author=self.bob, content="Great, thanks!")
        Comment.objects.update(created_at=timezone.now() - dt.timedelta(minutes=60))
        ops.reopen(self.todo, actor=self.ada)
        self.client.force_login(self.ada)
        html = self.client.get(self.todo.get_absolute_url()).content.decode()
        positions = [
            html.index("completed this"),
            html.index("Great, thanks!"),
            html.index("reopened this"),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_history_in_the_more_menu_for_staff(self):
        # Not below the timeline (decided 2026-11-22): in the "More" menu
        self.client.force_login(self.ada)
        html = self.client.get(self.todo.get_absolute_url()).content.decode()
        link = f'<a class="dropdown-item" href="/items/{self.todo.pk}/history/">'
        self.assertEqual(html.count(link), 1)
        self.assertLess(html.index(link), html.index('id="comments"'))
        self.client.force_login(self.cleo)
        html = self.client.get(self.todo.get_absolute_url()).content.decode()
        self.assertNotIn(link, html)


class MergeTest(TimelineBase):
    def test_the_same_person_within_ten_minutes_is_one_line(self):
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.move_todo(self.todo, todolist=self.shared, group=group, actor=self.ada)
        ops.complete(self.todo, actor=self.ada)
        (line,) = self.lines()
        self.assertIn("Ada moved this to Done and completed it", line)

    def test_not_another_person_or_after_ten_minutes(self):
        ops.complete(self.todo, actor=self.ada)
        ops.assign(self.todo, [self.ada], actor=self.bob)
        self.assertEqual(len(self.lines()), 2)
        Event.objects.all().delete()
        ops.reopen(self.todo, actor=self.ada)
        self.age(Action.REOPENED, 11)
        ops.complete(self.todo, actor=self.ada)
        self.assertEqual(len(self.lines()), 2)

    def test_a_comment_in_between_breaks_it(self):
        ops.complete(self.todo, actor=self.ada)
        ops.add_comment(self.todo, author=self.bob, content="Nice")
        ops.assign(self.todo, [self.bob], actor=self.ada)
        # The comment is a bit later than the completing, the assigning after
        Event.objects.filter(action=Action.COMPLETED).update(
            created_at=timezone.now() - dt.timedelta(minutes=3)
        )
        Comment.objects.update(created_at=timezone.now() - dt.timedelta(minutes=2))
        self.assertEqual(len(self.lines()), 2)

    def test_merging_is_by_the_time_between_neighbours(self):
        # A chain of changes, each within ten minutes of the one before
        ops.complete(self.todo, actor=self.ada)
        ops.assign(self.todo, [self.bob], actor=self.ada)
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.move_todo(self.todo, todolist=self.shared, group=group, actor=self.ada)
        now = timezone.now()
        for minutes, action in [
            (18, Action.COMPLETED),
            (9, Action.ASSIGNED),
            (0, Action.MOVED),
        ]:
            Event.objects.filter(action=action).update(
                created_at=now - dt.timedelta(minutes=minutes)
            )
        (line,) = self.lines()
        self.assertIn("completed this, assigned Bob and moved it to Done", line)


class CancellingTest(TimelineBase):
    """Changes in one line which undo each other are left out, what was set
    several times says its last value"""

    def test_the_due_date_set_and_removed(self):
        ops.update_todo(self.todo, actor=self.ada, due_on=dt.date(2026, 12, 1))
        ops.update_todo(self.todo, actor=self.ada, due_on=None)
        self.assertEqual(self.lines(), [])

    def test_moved_and_moved_back(self):
        # Into the board's "Done" column and back (decision B, 2026-11-22),
        # and into another list and back
        done = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.move_todo(self.todo, todolist=self.shared, group=done, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=None, actor=self.ada)
        self.assertEqual(self.lines(), [])
        other = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        ops.move_todo(self.todo, todolist=other, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, actor=self.ada)
        self.assertEqual(self.lines(), [])
        # Elsewhere in the end, it says where
        ops.move_todo(self.todo, todolist=self.shared, group=done, actor=self.ada)
        (line,) = self.lines()
        self.assertIn("moved this to Done", line)

    def test_a_column_move_before_moving_to_another_list_and_back(self):
        # It's back in the column it started in: no line says "ColY"
        x = ops.create_group(todolist=self.shared.todolist, title="ColX")
        y = ops.create_group(todolist=self.shared.todolist, title="ColY")
        other = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        ops.move_todo(self.todo, todolist=self.shared, group=x, actor=self.ada)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=self.shared, group=y, actor=self.ada)
        ops.move_todo(self.todo, todolist=other, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=x, actor=self.ada)
        self.assertEqual(self.lines(), [])
        # Into Y in the end: it says where it ended up
        ops.move_todo(self.todo, todolist=other, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=y, actor=self.ada)
        (line,) = self.lines()
        self.assertIn("moved this to Shared plans", line)
        self.assertNotIn("Plans and", line)

    def test_the_same_person_assigned_and_removed(self):
        ops.assign(self.todo, [self.bob, self.ada], actor=self.ada)
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        (line,) = self.lines()
        self.assertIn("assigned Ada", line)
        self.assertNotIn("Bob", line)
        ops.unassign(self.todo, [self.ada], actor=self.ada)
        self.assertEqual(self.lines(), [])

    def test_completed_and_reopened(self):
        """Every one is recorded (decided 2026-11-21), the line is the net
        change"""
        ops.complete(self.todo, actor=self.ada)
        ops.reopen(self.todo, actor=self.ada)
        self.assertEqual(Event.objects.count(), 2)
        self.assertEqual(self.lines(), [])
        ops.complete(self.todo, actor=self.ada)
        (line,) = self.lines()
        self.assertIn("completed this", line)
        self.assertNotIn("reopened", line)

    def test_completed_and_reopened_by_the_other_way_round(self):
        ops.trash(self.todo, actor=self.ada)
        ops.restore(self.todo, actor=self.ada)
        self.assertEqual(self.lines(), [])

    def test_the_title_changed_and_back(self):
        ops.update_todo(self.todo, actor=self.ada, title="Order tents")
        ops.update_todo(self.todo, actor=self.ada, title="Order the tent")
        self.assertEqual(self.lines(), [])

    def test_the_title_changed_twice_says_the_last(self):
        ops.update_todo(self.todo, actor=self.ada, title="Order tents")
        # Past the editing session, so two events
        Event.objects.update(created_at=timezone.now() - dt.timedelta(minutes=9))
        ops.update_todo(self.todo, actor=self.ada, title="Order two tents")
        (line,) = self.lines()
        self.assertIn("changed the title to “Order two tents”", line)
        self.assertNotIn("Order tents", line)

    def test_the_due_date_set_twice_says_the_last(self):
        ops.update_todo(self.todo, actor=self.ada, due_on=dt.date(2026, 12, 1))
        Event.objects.update(created_at=timezone.now() - dt.timedelta(minutes=9))
        ops.update_todo(self.todo, actor=self.ada, due_on=dt.date(2026, 12, 8))
        (line,) = self.lines()
        self.assertIn("set the due date to 8 Dec 2026", line)
        self.assertNotIn("1 Dec", line)


class ClientTest(TimelineBase):
    def test_a_client_sees_no_lines_from_when_it_was_internal(self):
        hidden = ops.create_todo(
            todolist=self.internal, title="Budget", creator=self.ada
        )
        ops.complete(hidden, actor=self.ada)
        ops.assign(hidden, [self.bob], actor=self.ada)
        ops.move_todo(hidden, todolist=self.shared, actor=self.ada)
        ops.reopen(hidden, actor=self.bob)
        self.age(Action.COMPLETED, 120)
        self.age(Action.ASSIGNED, 100)
        self.age(Action.MOVED, 80)
        staff = self.lines(self.ada, hidden)
        self.assertEqual(len(staff), 4)
        client = self.lines(self.cleo, hidden)
        self.assertEqual(len(client), 2)
        self.assertIn("moved this to Shared plans", client[0])
        self.assertIn("reopened this", client[1])
        self.assertFalse(any("completed" in line for line in client))
        self.assertFalse(any("assigned" in line for line in client))

    def test_no_internal_list_names(self):
        ops.move_todo(self.todo, todolist=self.internal, actor=self.ada)
        # Moved while visible to clients, to a list they can't see (the
        # event as it would be if the list's switch changed meanwhile)
        Event.objects.filter(action=Action.MOVED).update(is_client_visible=True)
        Item.objects.filter(pk=self.todo.pk).update(is_client_visible=True)
        staff = self.lines(self.ada)
        self.assertIn("moved this to Internal plans", staff[0])
        client = self.lines(self.cleo)
        self.assertIn("moved this to another list", client[0])
        self.assertNotIn("Internal", " ".join(client))

    def test_moves_without_the_lists_id_say_another_list_to_clients(self):
        ops.move_todo(self.todo, todolist=self.shared, actor=self.ada)
        other = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        ops.move_todo(self.todo, todolist=other, actor=self.ada)
        event = Event.objects.get(action=Action.MOVED, data__to="Plans")
        del event.data["to_id"]
        event.save()
        self.assertIn("moved this to another list", self.lines(self.cleo)[0])
        self.assertIn("moved this to Plans", self.lines(self.ada)[0])

    def test_assigned_people_clients_may_not_know(self):
        outsider = person("Dora")
        Event.objects.create(
            project=self.project,
            item=self.todo,
            actor=self.ada,
            action=Action.ASSIGNED,
            data={"assignees": [outsider.pk, self.bob.pk]},
            is_client_visible=True,
        )
        # The client knows the project's members only
        self.assertIn("assigned Bob", self.lines(self.cleo)[0])
        self.assertNotIn("Dora", self.lines(self.cleo)[0])
        self.assertIn("Dora", self.lines(self.ada)[0])


class NameLinksTest(TimelineBase):
    """The actor and the people a line names link to their pages where the
    viewer may open them (decided 2026-11-22)"""

    def html(self, user):
        self.client.force_login(user)
        return self.client.get(self.todo.get_absolute_url()).content.decode()

    def link(self, user, name):
        return f'<a href="/people/{user.pk}/" class="wb-person-link">{name}</a>'

    def test_actor_and_assignees(self):
        ops.assign(self.todo, [self.bob, self.cleo], actor=self.ada)
        html = self.html(self.ada)
        for user, name in [(self.ada, "Ada"), (self.bob, "Bob"), (self.cleo, "Cleo")]:
            self.assertIn(self.link(user, name), html)
        self.assertIn("assigned Bob and Cleo", self.lines(self.ada)[0])

    def test_plain_text_for_people_the_viewer_may_not_know(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        # Ada left the project: the client may not know her anymore
        self.project.memberships.filter(user=self.ada).delete()
        html = self.html(self.cleo)
        self.assertIn("Ada", self.lines(self.cleo)[0])
        self.assertNotIn(f'href="/people/{self.ada.pk}/"', html)
        self.assertIn(self.link(self.bob, "Bob"), html)

    def test_titles_stay_escaped(self):
        ops.update_todo(self.todo, actor=self.ada, title="<b>Tent</b> & pegs")
        html = self.html(self.ada)
        self.assertIn("“&lt;b&gt;Tent&lt;/b&gt; &amp; pegs”", html)
        self.assertNotIn("<b>Tent</b>", html)


class QueryCountTest(TimelineBase):
    def count(self):
        self.client.force_login(self.ada)
        url = self.todo.get_absolute_url()
        self.client.get(url)
        with CaptureQueriesContext(connection) as queries:
            self.client.get(url)
        return len(queries)

    def test_no_query_per_line(self):
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.complete(self.todo, actor=self.ada)
        ops.add_comment(self.todo, author=self.bob, content="One")
        few = self.count()
        for n in range(6):
            ops.assign(self.todo, [self.bob], actor=self.ada)
            ops.move_todo(self.todo, todolist=self.shared, group=group, actor=self.bob)
            ops.add_comment(self.todo, author=self.ada, content=f"Comment {n}")
            ops.unassign(self.todo, [self.bob], actor=self.bob)
            ops.reopen(self.todo, actor=self.ada)
        self.assertEqual(self.count(), few)
