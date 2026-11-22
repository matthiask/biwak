# The CLI in the style of gov and wb

Biwak's CLI follows the same rules as the other apps' CLIs (`gov`,
Governance; `wb`, Workbench): decided with the user 2026-11-22. Today it
pairs a plural command that shows things with a singular group that acts
on them (`biwak todos LIST`, `biwak todo add`); the other apps have one
group per thing.

**Status:** open.

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
