---
name: biwak-from-mail
description: Turn a mail (pasted, forwarded or an .eml file) into a to-do or a message in Biwak (the project management tool for teams working with clients) with the `biwak` CLI, with its attachments attached. Use when the user wants to file, track or post a mail in Biwak, make a to-do or a message from a mail, or asks to put a request from a mail on a list.
---

# A mail into a to-do or a message in Biwak

The `biwak` CLI talks to Biwak (see `biwak --help`). If `biwak` isn't
installed or logged in, tell the user to run
`uv tool install "git+https://github.com/matthiask/biwak#subdirectory=cli"`
and `biwak login URL --write`, which authorizes `biwak` in the browser.
Creating needs `--write`; if `biwak` answers that the token only allows
reading, ask the user to log in with `--write` instead of working around
it. If a command or option below is missing, `uv tool upgrade biwak-cli`.

The skill proposes, the user decides: nothing is created before the user
agreed to the proposal. It never sends mail; who hears about the new
to-do or message follows Biwak's usual rules.

## 1. Read the mail

From the pasted text, or from an `.eml` file: the sender, the date, the
subject, the text (without quoted earlier mails and signatures unless
they matter) and the attachments. Save the attachments of an `.eml` file
to the scratchpad, e.g.:

```sh
python3 - <mail.eml> <scratchpad>/attachments <<'EOF'
import email, email.policy, pathlib, sys
message = email.message_from_bytes(pathlib.Path(sys.argv[1]).read_bytes(), policy=email.policy.default)
target = pathlib.Path(sys.argv[2])
target.mkdir(parents=True, exist_ok=True)
for part in message.iter_attachments():
    name = pathlib.Path(part.get_filename() or "attachment").name
    (target / name).write_bytes(part.get_payload(decode=True))
    print(target / name)
EOF
```

Leave out inline images of signatures and logos; ask about attachments
of a pasted mail that aren't in the scratchpad (the user can save
them). Each attachment is at most 100 MB.

## 2. Find where it goes

The project, by name, and what's in it:

    biwak me --json
    biwak projects --json
    biwak search <words> --json
    biwak lists --project <project> --json
    biwak members --project <project> --json
    biwak messages --project <project> --order newest --json

`biwak search` finds earlier to-dos and messages about the same thing
(the sender's name, the subject's words): if one exists, propose a
comment there instead (`biwak todos comment <todo> <text> --attach
<file>`) or ask. When the project or list isn't clear, ask; don't guess.

## 3. Propose

A **to-do** for something to do (a request, a change, a bug), a
**message** for something to know or discuss (news, a decision, a
report). Show the user:

- **To-do:** the list (and group, its `groups`), the title (short, what
  to do), the notes (what's needed from the mail, its sender and date,
  quotes where the wording matters), the assignees (only members of the
  project, from `biwak members`; nobody unless the user or the mail
  names someone), a due date only if the mail or the user gives one.
- **Message:** the project, the title, the text (Markdown), the
  category if one fits (a wrong name lists the categories), and people
  to tell besides those who want to hear (`--also`) only when the user
  names them.
- The attachments that will be attached.
- **Who will see it.** A to-do is visible to clients when its list is
  (`visible_to_clients` of the list); a message is internal unless
  created with `--visible`. The default is internal: propose an internal
  list or an internal message. If the target is visible to clients, say
  so plainly ("clients will see this to-do and its attachments") and
  create it only after the user confirmed that.

Write titles and texts in the user's language (the one they speak with
you, or `language` from `biwak me --json`); quotes from the mail stay as
they are. Leave out what doesn't belong in a shared tool (signatures,
phone numbers, unrelated people in copy) unless the user wants it.

## 4. Create, after the user agreed

    biwak todos create <list> <title> --notes <notes> --assign <person> --due <date> --attach <file> --json
    biwak messages create <project> <title> <text> --category <category> --attach <file> --json

`--assign` and `--attach` are repeatable; `--group <group>` puts the
to-do into a group. A long message text goes in on standard input:

    biwak messages create <project> <title> --json < <scratchpad>/message.md

Attachments are appended to the to-do's notes or the message's text, as
replying by mail does. A message for clients gets `--visible`, only
after the user confirmed it.

Show the result with its link (`url`) and whether clients can see it.
