# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Teams (`teams.md`, 2026-11-22)

- **Partners see teams with only the members they may know**
  (`known_people()`, as on the People page): in the People page's
  section, a team's page, the picker, the `@` list and the API; the
  counts ("3 of 5") count only those. Otherwise a team would tell a
  partner about clients of other projects.
- **Teams first** in the picker and the `@` list (not counted in the
  `@` list's 10 people).
- **The entry's wording:** "team · 5 members", "team · 3 of 5: 2 can't
  see internal items"; "inactive" as a third reason; "can't be assigned
  to all of them" when assigning several to-dos of different projects.
- **Nobody left to add:** the picker doesn't offer the team (as for
  people picked already); the `@` list greys out a team nobody of which
  can see the item. Subscribers, those told already and oneself count as
  in ("5 of 5"), not as left out.
- **The team's page** `/teams/<id>/` for all staff, the People page's
  section at the end and only under "Everybody"; names up to 100
  characters.
