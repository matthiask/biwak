"""The combobox in front of long selects in the browser
(frontend/combobox.js, specs/ui.md, "Forms")"""

import re

from biwak.test_e2e import E2ETestCase, expect
from biwak.test_utils import external, organization, person


class ComboboxTest(E2ETestCase):
    def test_filtering_and_choosing_with_the_keyboard(self):
        dora = person("Dora", client=True)
        person("Eve", client=True, organization="Other Client Ltd")
        page = self.page
        self.goto(page, f"/projects/{self.project.pk}/people/")
        page.get_by_role("link", name="Add someone").click()
        dialog = page.get_by_role("dialog", name="Add someone")
        field = dialog.get_by_role("combobox", name="Person")
        expect(field).to_be_visible()
        # The hidden select isn't a second, nameless one for screen readers
        expect(dialog.get_by_role("combobox")).to_have_count(1)
        listbox = dialog.get_by_role("listbox")
        expect(listbox).to_be_hidden()

        # A click lists everybody, with their organization
        field.click()
        expect(listbox).to_be_visible()
        expect(
            listbox.get_by_role("option", name="Bob Example · Our organization")
        ).to_be_visible()
        options = listbox.get_by_role("option")
        expect(options.filter(has_text="Example Client Ltd")).to_have_count(1)
        # Words anywhere: the organization and the name, in any order
        field.fill("client dora")
        expect(options).to_have_count(1)
        expect(options).to_have_text("Dora Example · Example Client Ltd")
        # The address finds people too
        field.fill("eve@")
        expect(options).to_have_text("Eve Example · Other Client Ltd")
        field.fill("nobody here")
        expect(options).to_have_count(0)
        expect(listbox).to_contain_text("Nothing found")

        # Escape closes the list, not the dialog
        field.press("Escape")
        expect(listbox).to_be_hidden()
        expect(dialog).to_be_visible()

        # The arrow keys move, Enter chooses without submitting
        field.fill("example client")
        field.press("ArrowDown")
        field.press("ArrowUp")
        expect(options).to_have_count(2)
        expect(options.first).to_have_class(re.compile(r"\bactive\b"))
        field.press("Enter")
        expect(listbox).to_be_hidden()
        expect(field).to_have_value("Dora Example · Example Client Ltd")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Add").click()
        # The people page again, with Dora under her organization
        expect(dialog).to_be_hidden()
        expect(
            page.locator('[data-people-group="client"] .wb-person-link').filter(
                has_text="Dora Example"
            )
        ).to_be_visible()
        self.assertTrue(self.project.is_member(dora))
        self.assertEqual(self.errors, [])


class InviteRowsTest(E2ETestCase):
    """ "Add another" of the invite form (frontend/invite.js,
    specs/activation.md, "Inviting")"""

    def test_adding_rows(self):
        page = self.page
        self.goto(page, f"/projects/{self.project.pk}/people/")
        page.get_by_role("link", name="Invite by email").click()
        dialog = page.get_by_role("dialog", name="Invite people")
        emails = dialog.get_by_role("textbox", name="Email")
        expect(emails).to_have_count(3)
        dialog.get_by_role("button", name="Add another").click()
        expect(emails).to_have_count(4)
        expect(emails.nth(3)).to_be_focused()
        emails.nth(0).fill("dora@example.net")
        emails.nth(3).fill("eve@example.net")
        dialog.get_by_role("button", name="Invite").click()
        expect(dialog).to_be_hidden()
        expect(
            page.locator(".wb-person-link", has_text="eve@example.net")
        ).to_be_visible()
        self.assertTrue(
            self.project.memberships.filter(user__email="dora@example.net").exists()
        )
        self.assertEqual(self.errors, [])

    def add_domain(self, name, domain):
        # Cleo's organization exists already (setUp)
        org = organization(name)
        org.domains = [domain]
        org.save()

    def open_form(self, page):
        self.goto(page, f"/projects/{self.project.pk}/people/")
        page.get_by_role("link", name="Invite by email").click()
        return page.get_by_role("dialog", name="Invite people")

    def test_filled_in_from_the_address(self):
        organization("Our organization", is_own=True, domains=["ours.example"])
        self.add_domain("Example Client Ltd", "client.example")
        organization("Other Client Ltd", domains=["other.example"])
        root = person("Root", is_admin=True)
        page = self.login(root)
        dialog = self.open_form(page)
        emails = dialog.get_by_role("textbox", name="Email")
        orgs = dialog.get_by_role("combobox", name="Organization")
        roles = dialog.get_by_role("combobox", name="Staff or client")
        expect(roles.nth(0)).to_have_value("1")

        # Leaving the address fills in the organization and the role
        emails.nth(0).fill("bob@ours.example")
        emails.nth(0).press("Tab")
        expect(orgs.nth(0)).to_have_value("Our organization")
        expect(roles.nth(0)).to_have_value("")
        # Another address refills the fields nobody changed
        emails.nth(0).fill("dora@client.example")
        emails.nth(0).press("Tab")
        expect(orgs.nth(0)).to_have_value("Example Client Ltd")
        expect(roles.nth(0)).to_have_value("1")

        # A field changed by hand stays, the other one still follows
        orgs.nth(1).fill("Other Client Ltd")
        emails.nth(1).fill("bob@ours.example")
        emails.nth(1).press("Tab")
        expect(roles.nth(1)).to_have_value("")
        expect(orgs.nth(1)).to_have_value("Other Client Ltd")
        roles.nth(1).select_option("1")
        emails.nth(1).fill("carl@ours.example")
        emails.nth(1).press("Tab")
        emails.nth(0).fill("bob@ours.example")
        emails.nth(0).press("Tab")
        expect(roles.nth(0)).to_have_value("")
        expect(roles.nth(1)).to_have_value("1")
        expect(orgs.nth(1)).to_have_value("Other Client Ltd")

        # Free mail and an unknown domain: no organization, a client
        for email in ["eve@gmail.com", "eve@unknown.example"]:
            emails.nth(0).fill(email)
            emails.nth(0).press("Tab")
            expect(orgs.nth(0)).to_have_value("")
            expect(roles.nth(0)).to_have_value("1")

        # A row added later fills in too
        dialog.get_by_role("button", name="Add another").click()
        emails.nth(3).fill("fay@client.example")
        emails.nth(3).press("Tab")
        expect(orgs.nth(3)).to_have_value("Example Client Ltd")
        self.assertEqual(self.errors, [])

    def test_staff_get_no_role_and_only_client_organizations(self):
        organization("Our organization", is_own=True, domains=["ours.example"])
        self.add_domain("Example Client Ltd", "client.example")
        dialog = self.open_form(self.page)
        emails = dialog.get_by_role("textbox", name="Email")
        orgs = dialog.get_by_role("combobox", name="Organization")
        expect(dialog.get_by_role("combobox", name="Staff or client")).to_have_count(0)
        emails.nth(0).fill("dora@client.example")
        emails.nth(0).press("Tab")
        expect(orgs.nth(0)).to_have_value("Example Client Ltd")
        # Not the own organization: staff can't invite into it
        emails.nth(0).fill("bob@ours.example")
        emails.nth(0).press("Tab")
        expect(orgs.nth(0)).to_have_value("")
        self.assertEqual(self.errors, [])

    def test_new_project_rows_fill_in_too(self):
        """The new-project modal's rows: the domain's organization if it's
        one of those involved and Ada may put people there, no role"""
        self.add_domain("Example Client Ltd", "client.example")
        self.add_domain("Other Client Ltd", "other.example")
        self.add_domain("Third Client Ltd", "third.example")
        external(organization_name="Example External Agency")
        self.add_domain("Example External Agency", "agency.example")
        page = self.page
        self.goto(page, "/projects/")
        page.get_by_role("link", name="New project").click()
        dialog = page.get_by_role("dialog", name="New project")
        dialog.locator("[name=name]").fill("Camp")
        for name in [
            "Example Client Ltd",
            "Other Client Ltd",
            "Example External Agency",
        ]:
            dialog.get_by_label(name, exact=True).check()
        dialog.get_by_role("button", name="Continue").click()
        emails = dialog.get_by_role("textbox", name="Email")
        orgs = dialog.get_by_role("combobox", name="Organization")
        expect(emails).to_have_count(3)
        expect(dialog.get_by_role("combobox", name="Staff or client")).to_have_count(0)
        client = str(organization("Example Client Ltd").pk)
        other = str(organization("Other Client Ltd").pk)

        emails.nth(0).fill("dora@client.example")
        emails.nth(0).press("Tab")
        expect(orgs.nth(0)).to_have_value(client)
        # Not involved, an external organization (staff can't put people
        # there), free mail: by the address's domain
        for email in ["eve@third.example", "paul@agency.example", "eve@gmail.com"]:
            emails.nth(0).fill(email)
            emails.nth(0).press("Tab")
            expect(orgs.nth(0)).to_have_value("")
        # A choice by hand stays
        orgs.nth(1).select_option(other)
        emails.nth(1).fill("fay@client.example")
        emails.nth(1).press("Tab")
        emails.nth(0).fill("gus@client.example")
        emails.nth(0).press("Tab")
        expect(orgs.nth(0)).to_have_value(client)
        expect(orgs.nth(1)).to_have_value(other)
        self.assertEqual(self.errors, [])


class OrganizationFieldTest(E2ETestCase):
    """The organization field (biwak/organizations/forms.py): a text field
    whose names the combobox finds by words anywhere; a new name stays as
    typed and is created after confirming"""

    def setUp(self):
        super().setUp()
        organization("Zebra Clients")
        organization("Alpine Agency")
        self.dora = person("Dora", client=True, organization="Example Client Ltd")

    def open(self):
        page = self.page
        self.goto(page, "/people/")
        page.get_by_role("link", name="Change the organization of Dora Example").click()
        dialog = page.get_by_role("dialog", name="The organization of Dora Example")
        return dialog, dialog.get_by_role("combobox", name="Organization")

    def test_finding_and_choosing(self):
        dialog, field = self.open()
        expect(field).to_have_value("Example Client Ltd")
        listbox = dialog.get_by_role("listbox")
        options = listbox.get_by_role("option")
        # Words anywhere, not only the start
        field.fill("clients zeb")
        expect(options).to_have_count(1)
        expect(options).to_have_text("Zebra Clients")
        # Escape closes the list, not the dialog, keeping what was typed
        field.press("Escape")
        expect(listbox).to_be_hidden()
        expect(dialog).to_be_visible()
        expect(field).to_have_value("clients zeb")
        field.fill("agency")
        field.press("ArrowDown")
        field.press("Enter")
        expect(listbox).to_be_hidden()
        expect(field).to_have_value("Alpine Agency")
        dialog.get_by_role("button", name="Save").click()
        expect(dialog).to_be_hidden()
        self.dora.refresh_from_db()
        self.assertEqual(self.dora.organization.name, "Alpine Agency")
        self.assertEqual(self.errors, [])

    def test_a_new_name_stays(self):
        """Enter without choosing submits what was typed, even when it's the
        start of an existing name"""
        dialog, field = self.open()
        field.fill("Zebra")
        expect(dialog.get_by_role("option", name="Zebra Clients")).to_be_visible()
        field.press("Enter")
        expect(dialog.get_by_label("Create “Zebra”?")).to_be_visible()
        expect(field).to_have_value("Zebra")
        dialog.get_by_label("Create “Zebra”?").check()
        dialog.get_by_role("button", name="Save").click()
        expect(dialog).to_be_hidden()
        self.dora.refresh_from_db()
        self.assertEqual(self.dora.organization.name, "Zebra")
        self.assertEqual(self.errors, [])
