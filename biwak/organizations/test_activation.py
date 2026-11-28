"""Activating and deactivating people (specs/activation.md): the
operations, the pages, the API and the palette; the CLI in
``biwak/test_cli_people.py``"""

from unittest.mock import patch

from allauth.usersessions.models import UserSession
from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone

from biwak.accounts import sso
from biwak.accounts.models import APIToken, CalendarToken, PushSubscription, User
from biwak.organizations import activation
from biwak.outbox.models import OutgoingMail
from biwak.palette.test_actions import palette_data
from biwak.test_utils import assert_modal, external, person, project


class Base(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")  # staff, no admin
        self.pia = external("Pia")
        self.cleo = person("Cleo", client=True, is_active=False)
        self.dora = person("Dora", client=True, is_active=False)
        self.staffer = person("Stan", is_active=False)
        self.extern = external("Paul", is_active=False)
        self.site = project("Site", members=[self.cleo, self.ada])
        self.archived = project("Old", members=[self.cleo])
        self.archived.archived_at = timezone.now()
        self.archived.save()

    def active(self, user):
        user.refresh_from_db()
        return user.is_active


class ActivateTest(Base):
    def test_sets_is_active_and_nothing_else(self):
        with self.captureOnCommitCallbacks(execute=True):
            done = activation.activate([self.cleo], actor=self.ada)
        self.assertEqual(done, [(self.cleo, False)])
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(self.cleo.invited_at)
        self.assertTrue(self.site.is_member(self.cleo))

    def test_with_the_mail_through_the_outbox_after_the_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            activation.activate([self.cleo], actor=self.ada, mail=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(OutgoingMail.objects.count(), 1)
        for callback in callbacks:
            callback()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.cleo.email])
        self.assertIn("Site", message.body)
        self.assertNotIn("Old", message.body)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.invited_by, self.ada)
        self.assertTrue(self.cleo.is_invited)

    def test_a_bounced_address_is_activated_without_the_mail(self):
        self.cleo.mail_undeliverable_at = timezone.now()
        self.cleo.save()
        with self.captureOnCommitCallbacks(execute=True):
            done = activation.activate([self.cleo], actor=self.ada, mail=True)
        self.assertEqual(done, [(self.cleo, False)])
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.invited_at)

    def test_who_may_change_whom(self):
        for actor, target, allowed in [
            (self.ada, self.cleo, True),
            (self.ada, self.staffer, False),
            (self.ada, self.extern, False),
            (self.root, self.cleo, True),
            (self.root, self.staffer, True),
            (self.root, self.extern, True),
            (self.pia, self.cleo, False),
            (self.cleo, self.dora, False),
        ]:
            with self.subTest(actor=actor, target=target):
                self.assertEqual(activation.can_change(actor, target), allowed)

    def test_the_active_admins_are_locked_before_the_check(self):
        """Two requests deactivating the last two admins at the same time
        would both see the other one still active: every active admin's row
        is locked first, with the people deactivated, in the order of their
        IDs (no deadlocks between requests locking several)"""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        otto = person("Otto", is_admin=True)
        with CaptureQueriesContext(connection) as queries:
            activation.deactivate([self.cleo], actor=self.root)
        locks = [q["sql"] for q in queries if "FOR UPDATE" in q["sql"]]
        self.assertTrue(locks)
        where = locks[0].split(" WHERE ", 1)[1]
        self.assertIn('"accounts_user"."is_admin"', where)
        self.assertIn(f"IN ({self.cleo.pk})", where)
        self.assertTrue(where.endswith('ORDER BY "accounts_user"."id" ASC FOR UPDATE'))
        self.assertEqual(len(locks), 1)
        del otto

    def test_nothing_changes_if_one_is_refused(self):
        with (
            self.captureOnCommitCallbacks(execute=True),
            self.assertRaises(PermissionError),
        ):
            activation.activate([self.cleo, self.staffer], actor=self.ada, mail=True)
        self.assertFalse(self.active(self.cleo))
        self.assertEqual(OutgoingMail.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_several_by_an_admin(self):
        activation.activate([self.cleo, self.staffer, self.extern], actor=self.root)
        for user in [self.cleo, self.staffer, self.extern]:
            self.assertTrue(self.active(user))


class DeactivateTest(Base):
    def setUp(self):
        super().setUp()
        User.objects.filter(pk=self.cleo.pk).update(is_active=True)
        self.cleo.refresh_from_db()
        self.client.force_login(self.cleo)
        self.key = self.client.session.session_key
        UserSession.objects.create(
            user=self.cleo, session_key=self.key, ip="127.0.0.1", user_agent="Firefox"
        )
        APIToken.create_for(user=self.cleo, title="T", access="read")
        CalendarToken.renew(self.cleo)

    def test_ends_access_and_keeps_the_rest(self):
        self.assertTrue(sso.session_alive(self.key, self.cleo))
        with (
            patch("biwak.collab.live.check_access") as check,
            self.captureOnCommitCallbacks(execute=True),
        ):
            done = activation.deactivate([self.cleo], actor=self.ada)
        self.assertEqual(done, [self.cleo])
        self.assertFalse(self.active(self.cleo))
        self.assertFalse(UserSession.objects.filter(user=self.cleo).exists())
        self.assertFalse(APIToken.objects.filter(user=self.cleo).exists())
        self.assertFalse(CalendarToken.objects.filter(user=self.cleo).exists())
        # Open websockets check again, and fail the check
        check.assert_any_call(user=self.cleo.pk)
        self.assertFalse(sso.session_alive(self.key, self.cleo))
        self.assertTrue(self.site.is_member(self.cleo))
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_removes_push_devices(self):
        # Decided 2026-11-28: nothing is pushed to the devices of somebody
        # who left
        PushSubscription.objects.create(
            user=self.cleo,
            endpoint="https://push.example.org/cleo",
            p256dh="k",
            auth="a",
        )
        PushSubscription.objects.create(
            user=self.ada, endpoint="https://push.example.org/ada", p256dh="k", auth="a"
        )
        with self.captureOnCommitCallbacks(execute=True):
            activation.deactivate([self.cleo], actor=self.ada)
        self.assertEqual(
            set(PushSubscription.objects.values_list("user", flat=True)), {self.ada.pk}
        )

    def test_ends_access_again_after_the_commit(self):
        """What another request made meanwhile (it didn't see the change
        yet) goes too, like ``sso.enforce_required_now_and_after_commit()``"""
        with self.captureOnCommitCallbacks() as callbacks:
            activation.deactivate([self.cleo], actor=self.ada)
            APIToken.create_for(user=self.cleo, title="Meanwhile", access="read")
            CalendarToken.renew(self.cleo)
            UserSession.objects.create(
                user=self.cleo, session_key="meanwhile", ip="127.0.0.1", user_agent="x"
            )
        for callback in callbacks:
            callback()
        self.assertFalse(APIToken.objects.filter(user=self.cleo).exists())
        self.assertFalse(CalendarToken.objects.filter(user=self.cleo).exists())
        self.assertFalse(UserSession.objects.filter(user=self.cleo).exists())

    def test_the_sessions_of_others_stay(self):
        other = Client()
        other.force_login(self.ada)
        UserSession.objects.create(
            user=self.ada,
            session_key=other.session.session_key,
            ip="127.0.0.1",
            user_agent="Firefox",
        )
        activation.deactivate([self.cleo], actor=self.ada)
        self.assertEqual(UserSession.objects.filter(user=self.ada).count(), 1)
        self.assertEqual(other.get("/").status_code, 200)

    def test_not_oneself(self):
        with self.assertRaises(activation.ActivationError):
            activation.deactivate([self.root], actor=self.root)
        self.assertTrue(self.active(self.root))

    def test_not_the_last_active_admin(self):
        # An inactive admin acting (the request layer stops them) leaves
        # nobody
        other = person("Otto", is_admin=True)
        User.objects.filter(pk=self.root.pk).update(is_active=False)
        self.root.refresh_from_db()
        with self.assertRaises(activation.ActivationError) as cm:
            activation.deactivate([other], actor=self.root)
        self.assertIn("last active admin", str(cm.exception))
        self.assertTrue(self.active(other))
        # Admins may leave while another stays
        User.objects.filter(pk=self.root.pk).update(is_active=True)
        self.root.refresh_from_db()
        activation.deactivate([other], actor=self.root)
        self.assertFalse(self.active(other))

    def test_nothing_changes_if_one_is_refused(self):
        with self.assertRaises(PermissionError):
            activation.deactivate([self.cleo, self.pia], actor=self.ada)
        self.assertTrue(self.active(self.cleo))
        self.assertTrue(APIToken.objects.filter(user=self.cleo).exists())

    def test_staff_and_externals_by_an_admin_only(self):
        with self.assertRaises(PermissionError):
            activation.deactivate([self.pia], actor=self.ada)
        activation.deactivate([self.pia, self.ada], actor=self.root)
        self.assertFalse(self.active(self.pia))
        self.assertFalse(self.active(self.ada))


class PagesTest(Base):
    def modal(self, url, **data):
        method = self.client.post if data else self.client.get
        return method(url, data, headers={"HX-Modal": "true"})

    def test_filter_lists_the_inactive(self):
        self.client.force_login(self.ada)
        response = self.client.get("/people/?inactive=1")
        self.assertContains(response, "Inactive")
        self.assertContains(response, self.cleo.email)
        self.assertContains(response, self.staffer.email)
        self.assertNotContains(response, self.root.email)
        # Activate… only for those staff may change
        self.assertContains(response, f"/people/{self.cleo.pk}/activate/")
        self.assertNotContains(response, f"/people/{self.staffer.pk}/activate/")
        active = self.client.get("/people/")
        self.assertContains(active, "?inactive=1")
        self.assertNotContains(active, self.cleo.email)

    def test_filter_is_for_staff(self):
        for user in [self.pia, person("Chris", client=True)]:
            self.client.force_login(user)
            response = self.client.get("/people/?inactive=1")
            self.assertNotContains(response, "?inactive=1")
            self.assertNotContains(response, self.cleo.email)

    def test_activate_modal_and_post(self):
        self.client.force_login(self.ada)
        url = f"/people/{self.cleo.pk}/activate/"
        assert_modal(self, self.modal(url), title=f"Activate {self.cleo.display_name}?")
        self.assertContains(self.client.get(url), "Send the invitation mail")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"mail": "on"})
        self.assertRedirects(
            response, f"/people/{self.cleo.pk}/", fetch_redirect_response=False
        )
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 1)

    def test_activate_without_the_mail_and_next(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/people/{self.cleo.pk}/activate/", {"next": "/people/?inactive=1"}
        )
        self.assertRedirects(
            response, "/people/?inactive=1", fetch_redirect_response=False
        )
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)

    def test_activate_a_bounced_address_says_so(self):
        self.cleo.mail_undeliverable_at = timezone.now()
        self.cleo.save()
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/people/{self.cleo.pk}/activate/", {"mail": "on"}, follow=True
            )
        self.assertContains(response, "bounced: no invitation mail was sent")
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)

    def test_deactivate_question_and_post(self):
        self.client.force_login(self.ada)
        UserSession.objects.create(
            user=self.dora, session_key="x", ip="127.0.0.1", user_agent="F"
        )
        User.objects.filter(pk=self.dora.pk).update(is_active=True)
        url = f"/people/{self.dora.pk}/deactivate/"
        assert_modal(
            self, self.modal(url), title=f"Deactivate {self.dora.display_name}?"
        )
        self.assertTrue(self.active(self.dora))
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.active(self.dora))
        self.assertFalse(UserSession.objects.filter(user=self.dora).exists())

    def test_buttons_on_the_persons_page(self):
        self.client.force_login(self.ada)
        page = self.client.get(f"/people/{self.cleo.pk}/")
        self.assertContains(page, "Activate…")
        self.assertNotContains(page, "Deactivate…")
        self.assertNotContains(
            self.client.get(f"/people/{self.staffer.pk}/"), "Activate…"
        )
        self.assertNotContains(self.client.get(f"/people/{self.ada.pk}/"), "…</a>")
        self.client.force_login(self.root)
        self.assertContains(self.client.get(f"/people/{self.staffer.pk}/"), "Activate…")
        self.assertContains(self.client.get(f"/people/{self.ada.pk}/"), "Deactivate…")
        # Not oneself
        self.assertNotContains(
            self.client.get(f"/people/{self.root.pk}/"), "Deactivate…"
        )

    def test_staff_may_not_change_staff_and_externals(self):
        self.client.force_login(self.ada)
        for target in [self.staffer, self.extern]:
            for name in ["activate", "deactivate"]:
                with self.subTest(target=target, name=name):
                    url = f"/people/{target.pk}/{name}/"
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url).status_code, 403)
        self.assertFalse(self.active(self.staffer))
        ada_target = f"/people/{self.ada.pk}/deactivate/"
        self.assertEqual(self.client.post(ada_target).status_code, 403)

    def test_admins_change_everybody(self):
        self.client.force_login(self.root)
        for target in [self.staffer, self.extern]:
            response = self.client.post(f"/people/{target.pk}/activate/")
            self.assertEqual(response.status_code, 302)
            self.assertTrue(self.active(target))
        self.assertEqual(
            self.client.post(f"/people/{self.pia.pk}/deactivate/").status_code, 302
        )
        self.assertFalse(self.active(self.pia))

    def test_oneself_is_refused_with_a_message(self):
        self.client.force_login(self.root)
        response = self.client.post(f"/people/{self.root.pk}/deactivate/", follow=True)
        self.assertContains(response, "You can&#x27;t deactivate yourself.")
        self.assertTrue(self.active(self.root))

    def test_clients_and_externals(self):
        client = person("Chris", client=True)
        for user, status in [(client, 404), (self.pia, 404)]:
            self.client.force_login(user)
            for name in ["activate", "deactivate"]:
                url = f"/people/{self.cleo.pk}/{name}/"
                with self.subTest(user=user, name=name):
                    self.assertEqual(self.client.get(url).status_code, status)
                    self.assertEqual(self.client.post(url).status_code, status)
        self.assertFalse(self.active(self.cleo))

    def test_palette(self):
        self.client.force_login(self.ada)
        actions = palette_data(self.client.get(f"/people/{self.cleo.pk}/"))["actions"]
        self.assertIn(
            f"/people/{self.cleo.pk}/activate/", [a.get("url") for a in actions]
        )
        actions = palette_data(self.client.get(f"/people/{self.staffer.pk}/"))[
            "actions"
        ]
        self.assertNotIn("/activate/", " ".join(a.get("url", "") for a in actions))


class APITest(Base):
    def setUp(self):
        super().setUp()
        self.api = Client()
        self.api.force_login(self.ada)

    def post(self, url, data=None):
        return self.api.post(
            f"/api/v1/{url}", data or {}, content_type="application/json"
        )

    def test_activate_one(self):
        response = self.post(f"people/{self.cleo.pk}/activate/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_active"])
        self.assertFalse(response.json()["mailed"])
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)

    def test_activate_one_with_the_mail(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(f"people/{self.cleo.pk}/activate/", {"mail": True})
        self.assertTrue(response.json()["mailed"])
        self.assertEqual(len(mail.outbox), 1)

    def test_bounced_is_not_mailed(self):
        self.cleo.mail_undeliverable_at = timezone.now()
        self.cleo.save()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(f"people/{self.cleo.pk}/activate/", {"mail": True})
        self.assertTrue(response.json()["is_active"])
        self.assertFalse(response.json()["mailed"])
        self.assertEqual(len(mail.outbox), 0)

    def test_bulk_activate(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                "people/activate/",
                {"ids": [self.cleo.pk, self.dora.pk], "mail": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [p["id"] for p in response.json()], [self.cleo.pk, self.dora.pk]
        )
        self.assertEqual(len(mail.outbox), 2)

    def test_bulk_is_all_or_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                "people/activate/",
                {"ids": [self.cleo.pk, self.staffer.pk], "mail": True},
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.post("people/activate/", {"ids": [self.cleo.pk, 9999]}).status_code,
            404,
        )
        self.assertFalse(self.active(self.cleo))
        self.assertEqual(self.post("people/activate/", {"ids": []}).status_code, 400)

    def test_staff_may_not_change_staff_or_externals(self):
        for target in [self.staffer, self.extern]:
            self.assertEqual(
                self.post(f"people/{target.pk}/activate/").status_code, 403
            )
        self.assertEqual(
            self.post(f"people/{self.pia.pk}/deactivate/").status_code, 403
        )
        self.assertTrue(self.active(self.pia))

    def test_admins_change_everybody(self):
        self.api.force_login(self.root)
        response = self.post(
            "people/activate/", {"ids": [self.staffer.pk, self.extern.pk]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.active(self.staffer))
        response = self.post(f"people/{self.pia.pk}/deactivate/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

    def test_deactivate_ends_access(self):
        User.objects.filter(pk=self.cleo.pk).update(is_active=True)
        self.cleo.refresh_from_db()
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        CalendarToken.renew(self.cleo)
        response = self.post(f"people/{self.cleo.pk}/deactivate/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(APIToken.objects.filter(user=self.cleo).exists())
        self.assertFalse(CalendarToken.objects.filter(user=self.cleo).exists())
        other = Client()
        self.assertEqual(
            other.get(
                "/api/v1/me/", headers={"Authorization": f"Bearer {secret}"}
            ).status_code,
            401,
        )

    def test_bulk_deactivate_refuses_oneself_as_a_whole(self):
        self.api.force_login(self.root)
        response = self.post("people/deactivate/", {"ids": [self.ada.pk, self.root.pk]})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.active(self.ada))

    def test_clients_and_externals_get_403(self):
        for user in [person("Chris", client=True), self.pia]:
            self.api.force_login(user)
            with self.subTest(user=user):
                self.assertEqual(
                    self.post(f"people/{self.cleo.pk}/activate/").status_code, 403
                )
                self.assertEqual(
                    self.post("people/deactivate/", {"ids": [self.ada.pk]}).status_code,
                    403,
                )
                self.assertEqual(self.api.get("/api/v1/people/").status_code, 403)
        self.assertFalse(self.active(self.cleo))

    def test_list(self):
        response = self.api.get("/api/v1/people/", {"inactive": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {p["id"] for p in response.json()},
            {self.cleo.pk, self.dora.pk, self.staffer.pk, self.extern.pk},
        )
        active = {p["id"] for p in self.api.get("/api/v1/people/").json()}
        self.assertIn(self.ada.pk, active)
        self.assertNotIn(self.cleo.pk, active)


class NameTest(TestCase):
    """Staff correct clients' names, admins everybody's (decided 2026-11-21)"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        project(members=[self.root, self.bob, self.cleo])

    def rename(self, actor, who, name="Lovelace Ada"):
        self.client.force_login(actor)
        return self.client.post(
            f"/people/{who.pk}/name/", {"full_name": name, "short_name": ""}
        )

    def test_staff_rename_clients(self):
        self.assertContains(
            (
                self.client.force_login(self.bob),
                self.client.get(f"/people/{self.cleo.pk}/"),
            )[1],
            "Edit the name…",
        )
        self.assertEqual(
            self.rename(self.bob, self.cleo, "Cleo Example").status_code, 302
        )
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.full_name, "Cleo Example")

    def test_staff_dont_rename_staff_admins_do(self):
        self.assertEqual(self.rename(self.bob, self.root).status_code, 403)
        self.assertEqual(
            self.rename(self.root, self.bob, "Bob Builder").status_code, 302
        )
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.full_name, "Bob Builder")

    def test_clients_dont(self):
        self.assertEqual(self.rename(self.cleo, self.bob).status_code, 404)

    def test_in_the_palette_as_the_button(self):
        """ "Edit the name…" in the palette exactly where the button is"""
        for actor, who, offered in [
            (self.bob, self.cleo, True),
            (self.bob, self.root, False),
            (self.root, self.bob, True),
            (self.root, self.root, False),
            (self.cleo, self.bob, False),
        ]:
            with self.subTest(actor=actor, who=who):
                self.client.force_login(actor)
                page = self.client.get(f"/people/{who.pk}/")
                urls = [a.get("url") for a in palette_data(page)["actions"]]
                self.assertEqual(f"/people/{who.pk}/name/" in urls, offered)

    def test_not_oneself_its_in_the_settings(self):
        for actor in [self.root, self.bob]:
            with self.subTest(actor=actor):
                response = self.rename(actor, actor)
                self.assertRedirects(
                    response, "/accounts/settings/", fetch_redirect_response=False
                )
                actor.refresh_from_db()
                self.assertNotEqual(actor.full_name, "Lovelace Ada")


class DjangoAdminTest(TestCase):
    """The Django admin's ``is_active`` and ``is_admin`` go through the same
    rules: unticking ``is_active`` deactivates (sessions, tokens, calendar
    links end), and the last active admin stays one"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.cleo = person("Cleo", client=True)
        self.client.force_login(self.root)

    def post(self, user, **changes):
        data = {
            "email": user.email,
            "full_name": user.full_name,
            "short_name": user.short_name,
            "language": user.language,
            "organization": user.organization_id or "",
            "is_client": "on" if user.is_client else "",
            "is_active": "on" if user.is_active else "",
            "is_admin": "on" if user.is_admin else "",
            "mail_undeliverable_at_0": "",
            "mail_undeliverable_at_1": "",
        } | changes
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/admin/accounts/user/{user.pk}/change/", data)

    def test_unticking_is_active_deactivates(self):
        other = Client()
        other.force_login(self.cleo)
        UserSession.objects.create(
            user=self.cleo,
            session_key=other.session.session_key,
            ip="127.0.0.1",
            user_agent="Firefox",
        )
        APIToken.create_for(user=self.cleo, title="T", access="read")
        CalendarToken.renew(self.cleo)
        response = self.post(self.cleo, is_active="")
        self.assertEqual(response.status_code, 302)
        self.cleo.refresh_from_db()
        self.assertFalse(self.cleo.is_active)
        self.assertFalse(UserSession.objects.filter(user=self.cleo).exists())
        self.assertFalse(APIToken.objects.filter(user=self.cleo).exists())
        self.assertFalse(CalendarToken.objects.filter(user=self.cleo).exists())

    def test_the_last_active_admin(self):
        for changes in [{"is_active": ""}, {"is_admin": ""}]:
            with self.subTest(changes=changes):
                response = self.post(self.root, **changes)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "last active admin")
                self.root.refresh_from_db()
                self.assertTrue(self.root.is_active)
                self.assertTrue(self.root.is_admin)
        # With another admin, an admin may stop being one
        otto = person("Otto", is_admin=True)
        self.assertEqual(self.post(otto, is_admin="").status_code, 302)
        otto.refresh_from_db()
        self.assertFalse(otto.is_admin)

    def test_reticking_is_active_activates(self):
        # Like "Activate": an active person isn't among "People who left"
        activation.deactivate([self.cleo], actor=self.root)
        self.cleo.refresh_from_db()
        self.assertIsNotNone(self.cleo.left_at)
        self.assertEqual(self.post(self.cleo, is_active="on").status_code, 302)
        self.cleo.refresh_from_db()
        self.assertTrue(self.cleo.is_active)
        self.assertIsNone(self.cleo.left_at)
        self.assertFalse(self.cleo.left_in_basecamp)

    def test_losing_access_drops_subscriptions(self):
        # Like ``set_organization()``: leaving the own organization or
        # becoming a client drops subscriptions in projects they can't open
        from biwak.activity.models import Subscription
        from biwak.activity.operations import subscribe
        from biwak.items import operations as item_ops
        from biwak.organizations.models import Organization

        ada = person("Ada")
        website = project("Website", members=[ada])
        todolist = item_ops.create_list(project=website, title="Launch", creator=ada)
        agency = Organization.objects.create(name="Example External Agency")
        for name, changes in [
            ("Bob", {"organization": agency.pk}),
            ("Gil", {"is_client": "on"}),
        ]:
            with self.subTest(changes=changes):
                bob = person(name)
                subscribe(bob, todolist)
                self.assertEqual(self.post(bob, **changes).status_code, 302)
                self.assertFalse(Subscription.objects.filter(user=bob).exists())
