# Organizations

The organizations people belong to: the clients' companies, the own
organization, and externals (freelancers, other agencies). Who sees what
because of them is in `access.md`; inviting, activating and
deactivating people in `activation.md`; how an organization's people
sign in in `sso.md` and `two-factor.md`.

**"External", not "partner"** (decided by the user 2026-11-22):
"partner" is overloaded (Holacracy, the company's co-owners) and German
already says "Externe", so English follows: "externals" for the people,
"Ada is external", the badge "external", "external organization", in
the code, API and CLI too.

**Status:** built (2026-11-21), `biwak/organizations/`.

## The model (decided 2026-11-21)

- `Organization(name, domains, is_own)` and `User.organization`, a
  foreign key, empty allowed, protected (an organization with people
  isn't deleted). Names are unique ignoring case (stored with single
  spaces); at most one is marked as own. In the audit log.
- **Domains** (`example.org`): zero or more per organization, stored
  lowercase, unique across organizations. Inviting `someone@example.org`
  suggests "Example Ltd" (`for_new_person()`). Free-mail domains
  (`FREE_MAIL_DOMAINS` in `biwak/organizations/models.py`: gmail.com,
  outlook.com, … a small list) can't be added and never match. With
  single sign-on the domains also decide whose sign-ins count, and only
  admins change them (`sso.md`).
- **Everyone can belong to one:** clients, staff, externals; clients of
  any number of organizations per project.
- **No organization is an individual:** staff without one (freelancers)
  are externals, clients without one are fine.
- **Externals** are staff not in the own organization (`User.is_external`;
  own staff: `own_staff()`, not clients, `organization__is_own`). An
  external organization is one with staff that isn't the own
  (`is_external_organization()`, `external_organizations()`; no stored
  mark). Externals see only the projects they're members of and know all
  of those projects' people (`access.md`); they edit and archive the
  projects they're in and change members' notification choices on the
  people page, like other staff.
- **The own organization always exists:** `Organization.objects.own()`
  creates "Our organization" if none is marked, for admins to rename;
  `createsuperuser` puts the admin there. It can't be deleted, merged into
  another one or unmarked; the mark only moves (in the Django admin,
  `mark_own()`) while no admin would be left out. In practice: rename it,
  or merge others into it.
- **Admins are always own staff:** every change that would make an admin
  an external is refused with a message saying what to do first: ticking
  "is admin" on an external (`User.clean()`, the Django admin), moving an
  admin into another organization, merging an organization with admins
  into one that isn't the own, unmarking or moving the own mark
  (`_no_admin_externals()`, on the pages, the API and the Django admin).
- **Leaving the own organization** (moved, merged, another one marked,
  unmarked in the admin) drops the person's subscriptions in projects
  they can't open anymore (`forget_lost_access()`).
- **The display** "Ada, Example Ltd", with the organization's current
  name, for clients and externals, not own staff; also in the `@` list.
- **Files:** "clients of the same organization replace, rename and move
  each other's files" (`files.md`) compares the foreign key.

## Managing (decided 2026-11-21)

**Admins manage the internal team and externals, staff the clients**
(decided by the user):
`org_ops.can_touch(user, *organizations, person=)` refuses others than
admins for the own and external organizations and for moving staff (which
is how an organization becomes external). It guards moving people in
or out (pages, API, CLI), merging into or out of them (the merge modal
and the palette's "Merge…" don't offer external organizations to staff),
deleting, inviting into them (the invitation form, the new-project rows,
the API's `organization_id`; the domain's suggestion of the own or an
external organization is dropped for staff), and their domains
(`can_change_domains()`, the field disabled for staff). Renaming the own
or an external organization stays all staff's (confirmed by the user
2026-11-22). Staff keep everything for client organizations: create,
rename, merge (in the audit log), delete only without people. Externals
manage none (`access.md`).

- **Pages** (`/organizations/`, own staff only; linked from the People
  page, a project's people page and the palette's "Go to
  organizations"): the list with people and domains, an organization's
  page with its people, and modals to create, edit (name and domains),
  merge ("Merge…": people and domains move, the other one is deleted),
  delete and move a person ("Change organization",
  `/people/ID/organization/`, shown only where allowed).
- **Picking an organization** (`biwak/organizations/forms.py`): a text
  field completing existing names (a `<datalist>`, no JavaScript); a new
  name asks "Create 'Exmaple Ltd'?" and creates it only once ticked,
  together with the invitation, which catches most typos. Inviting
  leaves an empty field to the address's domain; a domain of the own
  organization is suggested for admins only. People who exist keep their
  organization.
- **Inviting staff:** without an organization the person is an
  individual external, and the form says so ("No organization: staff see
  only the projects they're added to"); admins can pick the own
  organization.
  Made-up staff in the tests (`biwak/test_utils.py`) belong to the own
  organization.
- **The Django admin:** organizations with their people count, the own
  mark, a person's organization with autocomplete.

## The People page (decided 2026-11-21)

- **`/people/`, "People" in the navigation** and "Go to people" in the
  palette; the way into the organizations pages.
- **Order:** the own organization first, then the other organizations by
  name, each marked as a client or external organization, then people
  without an organization (freelancers, individual clients). Headings
  link to the organization's page for own staff. The own organization
  is marked "Your own organization" only for its people; clients and
  externals see it by its name alone, here and on a project's people page
  (decided 2026-11-22).
- **Each person:** name, address, role (admin, staff, external, client),
  their name linking to their page. Own staff get "Change
  organization" (the own organization for admins only) and links to the
  organizations. "Change organization" in a row (here and on an
  organization's page) is a quiet icon (the building, no border; decided
  2026-11-23, the user: "the repeating change organization button is
  somewhat ugly"), named "Change the organization of Cleo Example" as
  its `title` and `aria-label`, a modal and also a page
  (`organizations/_change_organization.html`); the person's page keeps
  the labelled button.
- **Clients and externals** see the people they share a project with
  (`known_people()`, `access.md`), grouped the same way. Externals see
  addresses as on a project's people page; clients only those of their
  own organization.
- **Active people only** by default (decided 2026-11-23 by the user:
  "the default in the people list should be active people", the
  "Everybody" filter became "Active"), for everybody; inactive people
  and people who left are under the "Inactive" and "People who left"
  filters for own staff (`activation.md`), for others only through
  their pages and names. Like the API's people list and `biwak people`.
  Invitations and the "Invited" filter: `activation.md`.
- Teams, at the end for staff: `teams.md`.

## Projects and organizations

- **The new-project modal** (`biwak/projects/views.py`, two steps) asks
  for the organizations involved (all but the own). Without any it adds
  the project at once. With some, "Continue" shows their people
  (externals included), all ticked, own staff to tick (externals come with
  their organization), and three rows to invite people without an
  account (address, name, organization: the domain's if left empty, else
  the only one involved; invited as clients). Leaving an address selects
  the domain's organization if it's one of those involved and the
  inviter may put people there (as in `activation.md`, "Filled in from
  the address", decided 2026-11-22), else "By the address's domain"; only
  while the inviter hasn't changed the row's organization. The
  organizations involved can't change in that step (hidden there), so
  nothing is filled in again for them. Everybody picked becomes a
  member, the invitations go out with the project, and an invitation
  that fails adds nothing. `form_response(template=)` takes a template
  extending `modal_form.html` (block `fields`) for the rows.
- **A project's people page by organization** (`project_groups()` in
  `biwak/organizations/people.py`): own staff, client organizations,
  external organizations (by name), then people without an organization;
  within a group by name, the full name without the organization under
  its heading. For own staff each organization with active people who
  aren't members gets "Add people from …": the "Add someone" modal with
  `?organization=ID`, offering only them, preselected when there's one.
  Clients and externals see the same groups without actions (clients
  without addresses).
- **The page's actions** (decided 2026-11-22): "Add someone", "Invite by
  email" and "Organizations" in the page header (all quiet, icons only on
  phones). **Each row has its actions in it** (decided 2026-11-22, the
  user: the "…" menu and its modals took too many clicks): the choice of
  `notifications.md` as a small select ("Only when tagged", "Everything
  new") where `can_change_notify_choice()` allows it, saving
  itself on change (`frontend/save-on-change.js`,
  `[data-save-on-change]`, posting to `member_notify`; a Save button
  without JavaScript), and for own staff "Remove", which asks first in
  the existing modal. No "…" menu, no "saved" message (confirmed by the
  user 2026-11-22). While it saves the select is disabled; saved, it's
  enabled with the new value; when the save fails (offline, a network
  error, an answer other than 2xx) it shakes (`.wb-shake`, not with
  reduced motion), goes back to the stored value and is enabled again
  (decided by the user 2026-11-22). The focus stays on it.
- **Removing asks first, and nobody leaves** (decided 2026-11-22):
  "Remove" in the row opens a question (`member_remove`, GET asks
  through `form_response(form=None)` like the trash, POST removes; a page
  without JavaScript): "Remove Bob Example from Website?", saying
  whether Bob still sees the project (own staff in an all-access one) or
  doesn't any more and stops hearing about it, and that Bob's open
  to-dos in it lose Bob as assignee; for oneself "Remove yourself from
  …?", then the projects page. Only own staff (`can_manage_members()`)
  remove people, anybody including themselves; clients and externals
  can't leave (403 on the page and in the API): notifications cover
  dropping a project or not hearing about it ("Only when tagged", "No
  mails", unsubscribing), and letting clients and externals leave let
  them get around the organization's decisions about who works on a
  project.

## API, CLI, importer

- **API** (`biwak/organizations/api.py`), own staff only, with the
  pages' rules: `GET|POST /api/v1/organizations/`, `GET|PATCH|DELETE
  /api/v1/organizations/{id}/` (with its people and the read-only sign-in
  setting), `POST /api/v1/organizations/{id}/merge/` (`into_id`,
  `confirm`, `sso.md`), `PUT /api/v1/people/{id}/organization/`
  (`organization_id`, null for none). People carry `organization` (the
  name) and `organization_id`; invitations take `organization_id` or an
  existing `organization` by name (400 for an unknown one: create it
  first), else the address's domain decides.
- **CLI:** `biwak orgs [show|create|update|merge|delete|move]`, `biwak members
  invite … --organization NAME | --organization-id ID`; `biwak members`
  shows the organization.
- **The importer** (`biwak/importer/importer.py`): Basecamp's companies
  become organizations by name (ignoring case and spaces); clients and
  collaborators (staff who aren't Basecamp employees) get theirs, which
  makes collaborators externals; employees the own organization. The dry
  run says "external" and the company. It assigns and mentions as in
  Basecamp, also for a creator who's an external now.
