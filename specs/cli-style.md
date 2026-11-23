# The CLI in the style of gov and wb

Biwak's CLI follows the same rules as the other apps' CLIs (`gov`,
Governance; `wb`, Workbench): decided with the user 2026-11-22. Today it
pairs a plural command that shows things with a singular group that acts
on them (`biwak todos LIST`, `biwak todo add`); the other apps have one
group per thing.

**Status:** built (2026-11-22, CLI 0.60.0, `MINIMUM` 0.60.0); the rules
are in `api-cli.md`.

What was decided on the way (by the rules, 2026-11-22):

- Listing by a thing is an option, not an argument (a group's argument
  would swallow its subcommands): `biwak members --project ID`, `biwak
  lists|messages|checkins|links --project ID`, `biwak files --project ID
  [--folder ID]`, `biwak todos --list ID`, `biwak subscriptions --item
  ID`. Without it they stop with "Missing option".
- `members add|remove` (not `create|delete`): like `subscriptions
  add|remove`, they add an existing person to something.
- `invite` is `invitations create`; `invitations withdraw` stays (it
  does more than delete: it removes the person from their projects).
- `folder rename` and `folder color` are one `folders update FOLDER
  [--title] [--color]`; `folder move ITEM [FOLDER]` is `folders move`
  (into a folder), `move ITEM --to PROJECT` is `items move`.
- `orgs move PERSON [ORG]` stays in `orgs`.
- `docs`, `folders`, `reactions` and `items` have nothing to list
  without an item: alone they show their help.
- `todo done` is `todos complete`; `message post` is `messages create`.
- `biwak search --templates` is gone (search never finds templates,
  `templates.md`).

## The rules

- **One group per thing, in the plural:** `biwak todos`, `biwak lists`,
  `biwak messages`, `biwak docs`, `biwak files`, `biwak folders`,
  `biwak checkins`, `biwak links`, `biwak members`, `biwak projects`,
  `biwak people`, `biwak teams`, `biwak bookmarks`, `biwak invitations`,
  `biwak public-links`, `biwak forwarded`, `biwak orgs`.
- **The group alone lists** (as `gov proposals`), with the options the
  plural command has today (`biwak todos --mine --due overdue`,
  `biwak todos LIST` becomes `biwak todos --list LIST`).
- **Subcommands are verbs**, the same words across groups: `show`,
  `create` (not `add`, `new` or `post`), `update` (not `edit`), `delete`
  (or `trash` where it goes to the trash), and the group's own verbs
  (`todos complete`, `todos reopen`, `todos assign`, `todos comment`,
  `todos move`, `lists copy`, `lists archive`, `lists unarchive`,
  `lists add-from-text`, `messages pin`, `files upload`, `files
  download`, `files replace`, `checkins answer`, `checkins pause`,
  `members invite`, `projects join`, …).
- **Actions on any item** go to the group of what they make:
  `subscriptions add|remove ITEM` (today `subscribe`, `unsubscribe`,
  `subscribers`), `public-links create|delete ITEM` (`share`,
  `unshare`), `reactions create ITEM` (`react`), `bookmarks create|delete`
  (`bookmark`), `items move ITEM` (`move`).
- **Top level** only what isn't a thing: `login`, `logout`, `me`,
  `search`, `feed`, `lantern`, `away`, `settings`, `notifications`, as
  in gov and wb (`auth`, `tokens`, `completion` and `skills` there,
  when Biwak gets them).
- **Titles link to their page** (2026-11-23, as in gov and wb): in a
  terminal, the titles and names in tables and the heading of `show`
  are OSC 8 hyperlinks to the item's `url` (`link()` and `echo_linked()`
  in `core.py`, through rich); piped or redirected, plain text. CLI
  0.65.0.
- **No aliases for the old names:** nobody uses the CLI but its author
  (2026-11-22); `MINIMUM` in `biwak/cli_version.py` refuses older CLIs,
  the version goes to 0.60.0.

## Done when

- Every command renamed by the rules, `--help` texts saying what each
  does, `[clients]` and `--json` as before.
- The CLI tests (`biwak/test_cli*.py`) use the new names; the help's CLI
  chapter (`docs/cli.md`), `specs/api-cli.md` and every spec naming a
  command updated (grep for "biwak ").
- `specs/api-cli.md` says the rules (this file's "The rules") once.
