# Organizations

The organizations people belong to: the clients' companies, the
own, and partners (freelancers, other agencies). Today an
organization is a text on each person (`User.organization`): two people
belong together only if the text matches exactly, nothing prevents typos,
and renaming means editing everyone.

**Status:** built (2026-11-21), see "Built" below, including the
decisions under "Decided meanwhile" (partners know their projects'
people). Not built yet: the people page grouping members by
organization (decided 2026-11-21).

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
  the own organization (freelancers, partner agencies, Basecamp's
  non-client collaborators) see only the projects they're members of;
  all-access projects open only to own staff
  (`access.md` to be changed accordingly, tests through every entry
  point).
- **No organization is an individual** (decided 2026-11-21): the
  organization stays optional; staff without one (freelancers) are
  partners, clients without one are fine. Only the own organization's
  people are own staff (`is_partner`: staff not in
  the own organization; `own_staff()`: not clients, `organization__is_own`).
- **The own organization always exists** (decided 2026-11-21):
  `Organization.objects.own()` creates "Our organization" if none is
  marked, for admins to rename; migration `organizations.0003` does the
  same and puts every staff person without an organization into it, so
  nobody lost access by the change. `createsuperuser` puts the admin
  there. It can't be deleted, merged into another one or unmarked; the
  mark only moves while no admin would be left out (in practice: rename
  it, or merge others into it).
- **Inviting staff:** the domain preselects as before; without a choice
  the person is an individual partner, and the form says so ("No
  organization: staff see only the projects they're added to"). An
  admin can pick the own organization. The importer puts Basecamp's
  employees into the own organization; collaborators without a company
  stay individual partners. Made-up staff in the tests
  (`biwak/test_utils.py`) belong to the own organization.
- **Admins are always own staff** (decided
  2026-11-21): every change that would make an admin a partner is
  refused, and the message says what to do first: ticking "is admin" on
  a partner (`User.clean()`, the Django admin), moving an admin into
  another organization, merging an organization with admins into one
  that isn't the own, unmarking or moving the own mark while admins
  would be left out (`_no_admin_partners()`, the pages, the API and the
  Django admin).
- **Partners don't create projects, invite or add people, or manage
  organizations** (decided 2026-11-21): those forms list everybody
  (organizations and their people), which partners mustn't learn about.
  They edit
  and archive the projects they're in and change members' notification
  choices on the people page, like other staff.

## Managing organizations

- **Pages for staff:** a list of organizations with their people and
  domains; creating, renaming (once, for everyone), adding domains.
- **Merging** two organizations (the typo case): moves the people and
  domains to one and deletes the other, recorded in the audit log.
- **Picking an organization** (inviting, editing a person) is a field with
  autocomplete over existing names; a new name creates the organization
  only after confirming ("Create 'Exmaple Ltd'?"), which catches most
  typos.
- **The own organization** is marked (`is_own`), set once
  by an admin.

## The People page (decided 2026-11-21)

- **`/people/`, "People" in the navigation** and "Go to people" in the
  palette: the way into the organizations pages (which settles where
  they're linked from).
- **Order:** the own organization first, then the other
  organizations by name, each marked as a client or partner organization
  (partner: it has staff), then people without an organization
  (freelancers, individual clients). Headings link to the organization's
  page for own staff.
- **Each person:** name, address, role (admin, staff, partner, client),
  a link to their feed where the viewer may open it; inactive people
  quietly, marked "inactive", last in their group. The installation's
  own staff get the existing "Change organization" modal (the own
  organization for admins only, as everywhere) and links to the
  organizations; no new operations.
- **Clients and partners** see the people they share a project with
  (the members rule), grouped the same way. Partners see addresses as on
  a project's people page; clients only those of their own organization.
- **API and CLI:** there's no `GET /api/v1/people/`, so nothing new
  there (people come with projects' members and `biwak orgs show`).

## Starting a project with organizations

- **The new-project form** asks for the organizations involved ("this
  and that organization"), then lists their people to pick from, all or
  some, plus staff as today.
- **The picked people** become members; people without an account yet
  are invited from the same step (name, address; the domain preselects
  the organization).
- **A project's people page groups members by organization** (decided
  2026-11-21, to build): own staff first, then each client organization,
  then partners' organizations, each with its heading and "add people
  from …" (the organization's people who aren't members yet).

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
people; anything touching the own organization (merging
into it, moving people in or out, marking it) only admins, since it
decides who sees all-access projects.

## Built

- **The model** (`biwak/organizations/`): `Organization(name, domains,
  is_own)`, names unique ignoring case (stored with single spaces),
  at most one marked as own; `User.organization` a
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
- **Pages** (`/organizations/`, own staff only; linked
  from the People page, a project's people page and the palette's "Go to
  organizations"):
  the list with people and domains, an organization's page with its
  people, and modals to create, edit (name and domains), merge ("Merge…":
  people and domains move, the other one is deleted), delete (only
  without people) and move a person to another organization ("Change
  organization", `/people/ID/organization/`). The own organization is
  marked in the Django admin; merging into or out of it, moving people in
  or out of it and deleting it are admins only, also on these pages.
- **The new-project modal** asks for the organizations involved (all but
  the own organization); without any it adds the project at once, as
  before. With some, "Continue" shows their people (partners included),
  all ticked, own staff to tick, and three rows to
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
  (`organization_id`, null for none), own staff only,
  with the pages' rules; people carry `organization` (the name) and
  `organization_id`; invitations take `organization_id` or an existing
  `organization` by name (400 for an unknown one: create it first), else
  the address's domain decides. `biwak orgs [show|add|edit|merge|delete|move]`,
  `biwak member invite … --organization NAME | --organization-id ID`,
  `biwak members` shows the organization.
- **The importer** (`biwak/importer/importer.py`): Basecamp's companies
  become organizations by name (ignoring case and spaces); clients and
  collaborators (staff who aren't Basecamp employees) get theirs, which
  makes collaborators partners; employees the own organization (it
  always exists). The dry run's list says "partner" and the company.
- **Partners know their projects' people** (built 2026-11-21, see
  "Decided meanwhile"): `knows_people_of(viewer, project)` and
  `Project.people_q()` in `biwak/projects/models.py`, used by
  `Project.people_known_to()`, `mentions.known_to()` and
  `mentions.candidates_for()` (the `@` list), mentions written
  (`mentions.update()`), `assignable_people()`, the check-in form and
  `_check_people()`; `known_people()` adds the own staff of the
  all-access projects a partner is in (People page, person pages,
  images, display names). Conservative choices (not in the decision):
  a person's feed and the palette's people still go by projects shared
  as members (`people_visible_to()`), as for own staff; inactive own
  staff count as the project's people (names in histories); assigning a
  non-member own staff makes them a member, as when own staff assign.
- **The admin:** organizations with their people count; marking one as
  the own organization moves the mark (`mark_own()`); a person's
  organization with autocomplete.

## Decided meanwhile (2026-11-21, confirmed by the user the same day)

- **Partners see everybody in their projects** (changed by the user
  2026-11-21, it was "members only, like clients"): in a project they're
  in, partners know all its people, like staff of a limited project:
  the members, the staff with access, its clients, in the `@` list,
  mentions, assignees, subscribers, the people a check-in asks, names
  in an item's history, mails and the feed. Still nothing about people
  outside their projects (the people page, person pages, the API's
  people lists only show people they share a project with). The feed's
  old title of a list moved out of sight only for the own staff. Errors
  naming people by ID say nothing about who exists. The importer assigns
  and mentions as in Basecamp, also for a creator who's a partner now.
- **Leaving the own organization** (moved, merged, another
  one marked, unmarked in the admin) drops the person's subscriptions in
  projects they can't open anymore, like being removed from a limited
  project (`forget_lost_access()`).
- **The new-project modal** adds the project at once without
  organizations involved; people invited there are clients; the staff
  list is own staff (partners come with their
  organization).
- **Inviting** someone who exists doesn't change their organization; a
  domain matching the own organization preselects it for admins only.
- **Shown with the organization** ("Ada, Example Ltd"): clients and
  partners, not own staff.
