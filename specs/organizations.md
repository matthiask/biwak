# Organizations

The organizations people belong to: the clients' companies, the
installation's own, and partners (freelancers, other agencies). Today an
organization is a text on each person (`User.organization`): two people
belong together only if the text matches exactly, nothing prevents typos,
and renaming means editing everyone.

**Status:** open (spec, 2026-11-21).

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`, once the questions below are answered. The rules who
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

## Questions before building

1. **Partners** (people from another company working like staff, e.g. a
   freelancer, Basecamp's non-client collaborators): staff with an
   organization other than the installation's own. Should they see only
   the projects they're members of, not every all-access project?
   Suggested: yes, partners are staff limited to their projects (a
   project being all-access opens it to the installation's own staff
   only).
2. **Who manages organizations:** all staff, or admins only? Suggested:
   all staff create and rename; admins merge and delete.
