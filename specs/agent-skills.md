# Agent skills

Claude Code skills in the CLI package for common work with `biwak`,
like Governance's (`gov`) and Workbench's (`wb`). Decided 2026-11-23:
the first four below.

**Status:** open.

**Depends on:** the CLI (`api-cli.md`, `cli-style.md`); handover's bulk
commands (`handover.md`); the lantern (`lantern.md`).

**Touches:** `cli/biwak_cli/skills/`, `cli/biwak_cli/commands.py` (a
`skills` group), `cli/pyproject.toml` (package data, version),
`biwak/test_skills.py`, `AGENTS.md` (one line), this spec,
`specs/api-cli.md` (the pointer), `specs/README.md`.

## How they ship

Copied from Governance (`~/projects/sites/governance/cli/gov/skills/`,
`gov skills install`, `governance/test_skills.py`; Workbench's
`cli/wb/skills/` does the same):

- One directory per skill, `cli/biwak_cli/skills/<name>/SKILL.md`, in
  the package's data.
- `biwak skills install` links them into Claude Code's skills
  (`~/.claude/skills/<name>`): to the checkout for editable installs,
  else to uv's environment of the tool, so upgrading `biwak` updates
  them. `biwak skills` lists them. Bump the CLI's version when a skill
  changes.
- `biwak/test_skills.py` checks that every `biwak …` command a skill
  shows exists with the options it uses (as Governance's test does).
- Each skill starts like Workbench's: if `biwak` isn't installed or
  logged in, say how (`uv tool install "git+…#subdirectory=cli"`,
  `biwak login URL`).

## Rules for every skill

- **Clients:** before writing anything (a to-do, a message, a comment,
  moving, assigning), check whether clients can see where it goes
  (`visible_to_clients` in the JSON) and say so; anything clients would
  see is confirmed by the user first. The default for new things is
  internal.
- **Read first, then propose, then write:** show what would change and
  write only after the user agrees; bulk changes go through the bulk
  commands (one event, one notification, `handover.md`).
- **`--json` and IDs** for everything the skill parses; links to Biwak's
  pages in what it shows the user.
- English skill texts; the user's own language in what the skill writes
  into Biwak.

## The skills

### `biwak-triage`: what needs me

Decided 2026-11-23: the unread lantern plus what's due soon.

- Reads the lantern's unread entries (`biwak lantern`, without marking
  anything read) and my open to-dos overdue or due within 7 days
  (`biwak todos`, assignee me).
- Groups them into **act** (mentions, assignments, questions to me,
  overdue), **wait** (the ball is with others: to-dos I created that
  are assigned to others and overdue or due within 7 days) and **keep
  an eye on** (the rest of the unread entries), each with its link.
- Marks entries read only when the user asks (`biwak lantern read`).

### `biwak-from-mail`: a mail into a to-do or a message

- From a pasted or forwarded mail (text, or an `.eml` file): proposes a
  to-do (title, notes, assignees, due date, the list) or a message (the
  project, title, text, category), finding the project and list by
  name (`biwak projects`, `biwak lists`, `biwak search`).
- **Attachments are attached** (decided 2026-11-23), as replying by
  mail does.
- Internal by default; a target clients can see is named and confirmed.
- Never sends mail; who's told follows the usual rules (`notify`/`also`
  only when the user names people).

### `biwak-weekly-summary`: a project's week

- What happened in a project over the last 7 days (`biwak feed`,
  completed and new to-dos, messages, docs), what's open and overdue,
  decisions visible in messages and comments, each with its link.
- **Shown, posted only on request** (decided 2026-11-23): posted as a
  message, internal; making it visible to clients is asked separately.

### `biwak-handover`: someone leaves or is away

- Lists the person's open to-dos per project (`biwak todos`, assignee),
  proposes new assignees and dates per project, then applies them with
  the bulk commands (`biwak todos assign`, `biwak todos dates`, `biwak
  todos move` where a list changes), one project at a time, each
  confirmed.
- For people leaving, points to deactivating in the app
  (`activation.md`), which keeps the assignments (`handover.md`); for
  people away, to the away setting (`quiet-hours.md`).

## Done when

- The four skills exist, `biwak skills` lists them, `biwak skills
  install` links them (tested with a temporary home).
- `biwak/test_skills.py` passes: every command and option the skills
  show exists.
- `AGENTS.md` mentions the skills and the version bump; `api-cli.md`
  points here; the README row says built.
