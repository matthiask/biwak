# Organizations

The organizations people belong to: the clients' companies, the
installation's own, and partners (freelancers, other agencies). Today an
organization is a text on each person (`User.organization`): two people
belong together only if the text matches exactly, nothing prevents typos,
and renaming means editing everyone.

**Status:** open (spec, 2026-11-21).

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
