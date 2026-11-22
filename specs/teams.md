# Teams: picking several people at once

Named sets of people ("Design team") for assigning, adding subscribers
and mentioning several people in one go, like Basecamp's groups. A team
is a shortcut, not a thing items point at: picking it **expands at once
into its members**, and only the people are stored. Changing or
deleting a team later changes nothing that was picked with it. Decided
with the user 2026-11-22.

Named "team" because "group" is a list's heading (`core.md`).

**Status:** open.

Depends on: `people.md`, `organizations.md` (the People page),
`todos.md` (the people picker), `subscribers.md`, `notifications.md`
(mentions), `access.md`.

## Managing teams

- **Any own staff** creates, renames, changes and deletes teams, on the
  People page (a "Teams" section, each team's page or modal listing its
  members with the people picker). Partners and clients don't.
- **A team** has a name (unique, ignoring case) and members: any active
  or inactive person, staff, partners and clients alike ("Client X's
  people").
- **Only staff see teams** (own staff and partners): their names and
  members never show to clients, in pages, the API or mails.
- Deactivating someone keeps them in their teams (they're skipped when
  expanding, below); deleting a person's account removes them.
- `Team(name)`, `TeamMember(team, user)`, through operations, audited
  (`audit_tables()`).

## Using a team

Wherever several people are picked, staff find teams among the people,
marked as a team with its number of members:

- **The people picker** (`frontend/people-picker.js`, `PeopleField`):
  assignees, subscribers, whom to notify. Picking a team adds a pill per
  member, as if each had been picked; removing one afterwards is
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

## API and CLI

- Staff list, show, create, change and delete teams (`/api/teams/`),
  the CLI `biwak teams …` with `--json`. Clients get 404.
- **`@Team` is only expanded on the web** (decided 2026-11-22): texts
  and assignees sent through the API, the CLI and mail replies don't
  expand it; agents read a team's members and send the people.

## Help

The People chapter: what teams are, that picking one picks its members
now and changing the team later doesn't change earlier picks.

## Done when

- Staff manage teams on the People page; partners and clients can't,
  and clients never see a team's name anywhere (pages, mentions list,
  picker, API).
- Picking a team in the picker and in the `@` list adds exactly the
  members who can be there, says how many were left out and why, and
  stores only people (tests on the endpoints' JSON, browser tests for
  the picker and the `@` list).
- Deleting or changing a team afterwards leaves assignees, subscribers
  and mentions as they were.
- API and CLI tests as staff and as a client.
