from importlib import import_module

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from biwak.audit.models import LoggedAction
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization, domain_of, normalize_name
from biwak.test_utils import organization, partner, person


class ModelTest(TestCase):
    def test_names_ignore_case_and_spaces(self):
        org = organization("Example Ltd")
        self.assertEqual(normalize_name("  Example   Ltd "), "Example Ltd")
        self.assertEqual(Organization.objects.named(" example  LTD"), org)
        self.assertIsNone(Organization.objects.named(""))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Organization.objects.create(name="EXAMPLE LTD")

    def test_domains_match_but_never_free_mail(self):
        org = organization("Example Ltd", domains=["example.org"])
        self.assertEqual(Organization.objects.for_email("Cleo@Example.org"), org)
        self.assertIsNone(Organization.objects.for_email("cleo@other.org"))
        Organization.objects.filter(pk=org.pk).update(domains=["gmail.com"])
        self.assertEqual(domain_of("cleo@gmail.com"), "")
        self.assertIsNone(Organization.objects.for_email("cleo@gmail.com"))
        self.assertIsNone(Organization.objects.for_email("not an address"))

    def test_only_one_own(self):
        organization("Example Team", is_own=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Organization.objects.create(name="Other Team", is_own=True)

    def test_partners(self):
        ada = person("Ada")
        self.assertFalse(ada.is_partner)
        self.assertTrue(ada.sees_all_access)
        pia = partner("Pia")
        self.assertTrue(pia.is_partner)
        self.assertFalse(pia.sees_all_access)
        self.assertEqual(pia.display_name, "Pia Example, Example Partner Agency")
        own = organization("Example Team", is_own=True)
        ada.organization = own
        self.assertTrue(ada.sees_all_access)
        self.assertEqual(ada.display_name, "Ada Example")
        cleo = person("Cleo", client=True)
        self.assertFalse(cleo.is_partner)
        self.assertFalse(cleo.sees_all_access)
        self.assertEqual(cleo.display_name, "Cleo Example, Example Client Ltd")

    def test_migration_merges_names(self):
        names = import_module("biwak.accounts.migrations.0012_organizations").names
        self.assertEqual(
            names(["Example  Ltd", "", "example ltd ", "  ", "Other AG"]),
            {
                "Example  Ltd": "Example Ltd",
                "example ltd ": "Example Ltd",
                "Other AG": "Other AG",
            },
        )


class OperationsTest(TestCase):
    def setUp(self):
        self.admin = person("Ada", is_admin=True)
        self.bob = person("Bob")
        self.own = organization("Example Team", is_own=True)

    def test_create_and_rename(self):
        org = org_ops.create_organization(
            name=" Example  Ltd", domains="Example.org, @example.net", actor=self.bob
        )
        self.assertEqual(org.name, "Example Ltd")
        self.assertEqual(org.domains, ["example.org", "example.net"])
        with self.assertRaises(ValidationError):
            org_ops.create_organization(name="example ltd", actor=self.bob)
        org_ops.update_organization(org, name="Example Limited", actor=self.bob)
        org.refresh_from_db()
        self.assertEqual(org.name, "Example Limited")
        # Clients and partners don't manage organizations
        for nobody in [person("Cleo", client=True), partner("Pia")]:
            with self.assertRaises(PermissionError):
                org_ops.create_organization(name="Other", actor=nobody)

    def test_domains(self):
        org = organization("Example Ltd", domains=["example.org"])
        for wrong in ["gmail.com", "not a domain", "example"]:
            with self.subTest(wrong), self.assertRaises(ValidationError):
                org_ops.create_organization(name="Other", domains=wrong, actor=self.bob)
        with self.assertRaisesMessage(ValidationError, "belongs to Example Ltd"):
            org_ops.create_organization(
                name="Other", domains=["example.org"], actor=self.bob
            )
        # Its own domains again are fine
        org_ops.update_organization(
            org, domains=["example.org", "example.com"], actor=self.bob
        )
        org.refresh_from_db()
        self.assertEqual(org.domains, ["example.org", "example.com"])

    def test_merge(self):
        typo = organization("Exmaple Ltd", domains=["example.net"])
        org = organization("Example Ltd", domains=["example.org"])
        cleo = person("Cleo", client=True, organization=typo)
        LoggedAction.objects.all().delete()
        org_ops.merge(typo, org, actor=self.bob)
        cleo.refresh_from_db()
        org.refresh_from_db()
        self.assertEqual(cleo.organization, org)
        self.assertEqual(org.domains, ["example.org", "example.net"])
        self.assertFalse(Organization.objects.filter(pk=typo.pk).exists())
        # In the audit log: the person moved, the domains, the deletion
        logged = {(a.table_name, a.action) for a in LoggedAction.objects.all()}
        self.assertIn(("accounts_user", "U"), logged)
        self.assertIn(("organizations_organization", "U"), logged)
        self.assertIn(("organizations_organization", "D"), logged)
        with self.assertRaises(ValidationError):
            org_ops.merge(org, org, actor=self.bob)

    def test_delete_only_without_people(self):
        org = organization("Example Ltd")
        cleo = person("Cleo", client=True, organization=org)
        with self.assertRaises(ValidationError):
            org_ops.delete_organization(org, actor=self.bob)
        org_ops.set_organization(cleo, None, actor=self.bob)
        org_ops.delete_organization(org, actor=self.bob)
        self.assertFalse(Organization.objects.filter(pk=org.pk).exists())

    def test_the_own_organization_is_for_admins(self):
        org = organization("Example Ltd")
        other = organization("Other Ltd")
        pia = partner("Pia")
        # Merging into or out of it, moving people in or out, deleting it
        for change in [
            lambda actor: org_ops.merge(org, self.own, actor=actor),
            lambda actor: org_ops.merge(self.own, org, actor=actor),
            lambda actor: org_ops.set_organization(pia, self.own, actor=actor),
            lambda actor: org_ops.delete_organization(self.own, actor=actor),
            lambda actor: org_ops.mark_own(org, actor=actor),
        ]:
            with self.assertRaises(PermissionError), transaction.atomic():
                change(self.bob)
        org_ops.set_organization(self.bob, self.own, actor=self.admin)
        with self.assertRaises(PermissionError):
            org_ops.set_organization(self.bob, other, actor=self.bob)
        # Partners and partner organizations: admins (decided 2026-11-21)
        with self.assertRaises(PermissionError):
            org_ops.set_organization(pia, other, actor=self.bob)
        org_ops.set_organization(pia, other, actor=self.admin)
        with self.assertRaises(PermissionError):
            org_ops.merge(org, other, actor=self.bob)
        # Client organizations: all staff
        org_ops.merge(org, organization("Third Ltd"), actor=self.bob)
        # The own one always exists: not deleted, not merged away, the mark
        # not removed; moving it would make the admins partners
        with self.assertRaisesMessage(ValidationError, "always exists"):
            org_ops.delete_organization(self.own, actor=self.admin)
        with self.assertRaisesMessage(ValidationError, "always exists"):
            org_ops.merge(self.own, other, actor=self.admin)
        with self.assertRaisesMessage(ValidationError, "always"):
            org_ops.mark_own(None, actor=self.admin)
        with self.assertRaisesMessage(ValidationError, "no admin"):
            org_ops.mark_own(other, actor=self.admin)
        self.assertEqual(Organization.objects.get(is_own=True), self.own)
