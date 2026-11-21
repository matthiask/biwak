# Organizations

The organizations people belong to: the clients' companies, the
installation's own, and partners (freelancers, other agencies). Today an
organization is a text on each person (`User.organization`): two people
belong together only if the text matches exactly, nothing prevents typos,
and renaming means editing everyone.

**Status:** built (2026-11-21), see "Built" below; open: the questions
under "Decided meanwhile". Not built: the people page grouping members by
organization ("Later").

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. The rules who
sees what (`access.md`) change for partners: tests through every entry
point.

**Depends on:** the core, the importer (Basecamp's companies).

**Touches:**
- `biwak/accounts/` (the model, the person's field);
- inviting and adding members (`biwak/projects/`);
- the new-project form;
- `can_change()` for files (same organization);
- the API and the CLI;
- the importer;
- the admin.

## Decided (2026-11-21)

- **A model:** `Organization(name, domains, is_own)` and
  `User.organization` as a foreign key (empty allowed). No production
  data yet, so the migration only needs to turn existing texts into
  organizations, merging names that differ only in case and spaces.
- **Email domains:** an organization has zero or more domains
  (`example.org`). Inviting `someone@example.org` preselects "Example
  Ltd"; staff can change it. Free-mail domains (gmail.com, outlook.com,
  … a small list) are never used for matching.
- **Everyone can belong to one:** clients, staff, and partners. Clients
  come from any number of organizations per project, so Basecamp's
  limit doesn't apply.
- **Partners see only their projects:** staff whose organization isn't
  the installation's own (freelancers, partner agencies, Basecamp's
  non-client collaborators) see only the projects they're members of;
  all-access projects open only to the installation's own staff
  (`access.md` to be changed accordingly, tests through every entry
  point).

## Managing organizations

- **Pages for staff:** a list of organizations with their people and
  domains; creating, renaming (once, for everyone), adding domains.
- **Merging** two organizations (the typo case): moves the people and
  domains to one and deletes the other, recorded in the audit log.
- **Picking an organization** (inviting, editing a person) is a field with
  autocomplete over existing names; a new name creates the organization
  only after confirming ("Create 'Exmaple Ltd'?"), which catches most
  typos.
- **The installation's own organization** is marked (`is_own`), set once
  by an admin.

## Starting a project with organizations

- **The new-project form** asks for the organizations involved ("this
  and that organization"), then lists their people to pick from, all or
  some, plus staff as today.
- **The picked people** become members; people without an account yet
  are invited from the same step (name, address; the domain preselects
  the organization).
- **Later:** a project's people page groups members by organization and
  offers "add people from …".

## Elsewhere

- The person's display ("Ada, Example Ltd") and the `@` list show the
  organization's current name.
- Files: "clients of the same organization replace, rename and move each
  other's files" (decided 2026-11-21) compares the foreign key, not text.
- **API and CLI:** organizations (list, create, rename, merge for
  staff), `organization_id` on people and invitations, `biwak orgs`.
- **The importer:** Basecamp's companies become organizations (by name,
  merging as above); people point to theirs.

## Managing (decided 2026-11-21)

All staff create, rename and merge client and partner organizations
(recorded in the audit log); deleting only organizations without
people; anything touching the installation's own organization (merging
into it, moving people in or out, marking it) only admins, since it
decides who sees all-access projects.

## Built

- **The model** (`biwak/organizations/`): `Organization(name, domains,
  is_own)`, names unique ignoring case (stored with single spaces),
  at most one marked as the installation's own; `User.organization` a
  foreign key (empty allowed, protected: an organization with people
  isn't deleted). Migration `accounts.0012` turned the texts into
  organizations, merging names that differ only in case and spaces (the
  oldest person's spelling wins). In the audit log.
- **Domains** are stored lowercase, unique across organizations;
  free-mail domains (`FREE_MAIL_DOMAINS`: gmail.com, googlemail.com,
  outlook.com, hotmail.com, yahoo.com, icloud.com, gmx.ch, gmx.net,
  bluewin.ch and a few more) can't be added and never match.
- **Picking an organization** (`biwak/organizations/forms.py`): a text
  field completing the existing names (a `<datalist>`, no JavaScript); a
  name that doesn't exist asks "Create 'Exmaple Ltd'?" and creates it
  only once ticked, together with the invitation. Inviting leaves an
  empty field to the address's domain; people who exist keep their
  organization. Everybody can belong to one, staff too.
- **Pages** (`/organizations/`, the installation's own staff only; linked
  from a project's people page and the palette's "Go to organizations"):
  the list with people and domains, an organization's page with its
  people, and modals to create, edit (name and domains), merge ("Merge…":
  people and domains move, the other one is deleted), delete (only
  without people) and move a person to another organization ("Change
  organization", `/people/ID/organization/`). The installation's own is
  marked in the Django admin; merging into or out of it, moving people in
  or out of it and deleting it are admins only, also on these pages.
- **The new-project modal** asks for the organizations involved (all but
  the installation's own); without any it adds the project at once, as
  before. With some, "Continue" shows their people (partners included),
  all ticked, the installation's own staff to tick, and three rows to
  invite people without an account (address, name, organization: the
  domain's if left empty, else the only one involved; invited as
  clients). Everybody picked becomes a member, the invitations go out
  with the project, and an invitation that fails adds nothing.
  `form_response(template=)` takes a template extending
  `modal_form.html` (block `fields`) for the rows.
- **Display:** "Ada, Example Ltd" for clients and partners (the current
  name), also in the `@` list.
- **API and CLI** (`biwak/organizations/api.py`, CLI 0.25.0): `GET|POST
  /api/v1/organizations/`, `GET|PATCH|DELETE /api/v1/organizations/{id}/`
  (with its people), `POST /api/v1/organizations/{id}/merge/`
  (`into_id`), `PUT /api/v1/people/{id}/organization/`
  (`organization_id`, null for none), the installation's own staff only,
  with the pages' rules; people carry `organization` (the name) and
  `organization_id`; invitations take `organization_id` or an existing
  `organization` by name (400 for an unknown one: create it first), else
  the address's domain decides. `biwak orgs [show|add|edit|merge|delete|move]`,
  `biwak member invite … --organization NAME | --organization-id ID`,
  `biwak members` shows the organization.
- **The importer** (`biwak/importer/importer.py`): Basecamp's companies
  become organizations by name (ignoring case and spaces); clients and
  collaborators (staff who aren't Basecamp employees) get theirs, which
  makes collaborators partners; employees the installation's own if one
  is marked, else none. The dry run's list says "partner" and the company.
- **The admin:** organizations with their people count; marking one as
  the installation's own moves the mark (`mark_own()`); a person's
  organization with autocomplete.

## Decided meanwhile (2026-11-21, to be confirmed)

- **Staff without an organization** count as the installation's own: an
  installation without organizations set up behaves as before. Only staff
  in another organization are partners.
- **Partners** learn about members only, like clients (the `@` list,
  mentions, assignees, subscribers), and don't create projects, add or
  invite people or manage organizations: those forms list everybody.
  They edit and archive the projects they're in, like other staff.
- **Managing organizations** is for the installation's own staff (the
  spec's "all staff", partners left out for the reason above).
- **The new-project modal** adds the project at once without
  organizations involved; people invited there are clients; the staff
  list is the installation's own staff (partners come with their
  organization).
- **Inviting** someone who exists doesn't change their organization; a
  domain matching the installation's own preselects it for admins only.
- **Shown with the organization** ("Ada, Example Ltd"): clients and
  partners, not the installation's own staff.
