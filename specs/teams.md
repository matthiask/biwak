# Teams: picking several people at once

Named sets of people ("Design team") for assigning, adding subscribers
and mentioning several people in one go, like Basecamp's groups. A team
is a shortcut, not a thing items point at: picking it **expands at once
into its members**, and only the people are stored. Changing or
deleting a team later changes nothing that was picked with it. Decided
with the user 2026-11-22.

Named "team" because "group" is a list's heading (`core.md`).

**Status:** built (2026-11-22).

## Managing teams

- **Any own staff** creates, renames, changes and deletes teams, on the
  People page (a "Teams" section, each team's page or modal listing its
  members with the people picker). Externals and clients don't.
- **A team** has a name (unique, ignoring case) and members: any active
  or inactive person, staff, externals and clients alike ("Client X's
  people").
- **Only staff see teams** (own staff and externals): their names and
  members never show to clients, in pages, the API or mails.
- Deactivating someone keeps them in their teams (they're skipped when
  expanding, below); deleting a person's account removes them.
- `Team(name)`, `TeamMember(team, user)` (`biwak/teams/`), through
  operations (`operations.py`), audited
  (`audit_tables()`). Names up to 100 characters (confirmed by the user
  2026-11-22). Changing teams records no event: the audit log has it,
  nobody is told.
- **Pages** (confirmed by the user 2026-11-22): "Teams" at the end of
  the People page ("Everybody" only, `teams/_teams.html`), each team
  with its members; "New team" for own staff (also in the palette). A
  team's page (`/teams/<id>/`, `teams/team_detail.html`, for staff)
  lists its members; own staff get Edit (name and the people picker offering everybody,
  inactive people too) and Delete (a question), also in the palette.
- **Externals see teams with only the members they may know**
  (`known_people()`, as on the People page), everywhere: pages, picker,
  `@` list, API; the counts ("3 of 5") count only those, so a team
  doesn't tell an external about clients of other projects (confirmed by
  the user 2026-11-22).

## Using a team

Wherever several people are picked, staff find teams among the people,
marked as a team with its number of members (`biwak/teams/picking.py`
for the picker's `data-teams` and the `@` list's entries;
`PeopleField.offer_teams()` and `PeopleSelect.team_attrs()` in
`biwak/forms.py`):

- **The people picker** (`frontend/people-picker.js`, `PeopleField`):
  assignees, subscribers, whom to notify, the people a check-in asks.
  Picking a team adds a pill per member, as if each had been picked; removing one afterwards is
  removing a pill.
- **Typing `@`** in Markdown fields (`frontend/mentions.js`): choosing a
  team inserts a mention per member (`[@Ada](person:12)
  [@Bob](person:15)`); the stored text has only people.
- **Who's added:** only the members who'd be offered and available
  there, as if picked one by one: active, able to see the item, in the
  project. The others are left out, and the entry says so before
  picking ("3 of 5: 2 can't see internal items"; the same reasons as
  greyed-out people). A team never adds anyone to a project.
- Members already picked or mentioned aren't added twice.
- **How it shows** (confirmed by the user 2026-11-22): **teams come
  last** in both lists, after the people (decided by the user
  2026-11-22: "Teams are a special case"), and don't count towards the
  `@` list's 10 people. A people mark (`teamMark()` in
  `frontend/avatar.js`),
  "team · 5 members" or "team · 3 of 5: 1 not a member of this project,
  1 inactive" (the reasons: "can't see internal items", "not a member of
  this project", "inactive"; across projects in "Assign…": "can't be
  assigned to all of them"). Those subscribed or told already and oneself
  count as in, not as left out. In the picker a team with nobody left to
  add isn't offered (like people picked already); in the `@` list a
  team nobody of which can see the item is greyed out, like people.
  "Also tell…" at the top leaves out clients while "Visible to clients"
  is unticked, as the picker does for them one by one.
- **Check-ins' "People asked"** is the picker too (decided 2026-11-22,
  `checkins.md`), its clients following "Visible to clients" like "Also
  tell…".
- **Not in:** the API's mentionable list.

## API and CLI

- Staff list and show teams with their members, own staff create,
  change and delete them (`/api/v1/teams/`, `{name, members: [IDs]}`,
  PATCH replaces the members; externals 403), the CLI `biwak teams
  [show|add|edit|delete]` with `--json` and `--members 3,4`. Clients get
  404.
- **`@Team` is only expanded on the web** (decided 2026-11-22): texts
  and assignees sent through the API, the CLI and mail replies don't
  expand it; agents read a team's members and send the people.

## Help

The People chapter: what teams are, that picking one picks its members
now and changing the team later doesn't change earlier picks.

## Tests

`biwak/teams/test_teams.py` (operations, pages, palette),
`test_picking.py` (the picker's `data-teams`, the `@` list's JSON, as
staff, external and client), `test_api.py` (API and CLI);
`TeamsTest` in `biwak/test_e2e.py` (the picker, "Also tell…" following
the checkbox, the `@` list).
