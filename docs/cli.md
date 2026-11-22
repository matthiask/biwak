# The CLI and the API

The API covers what the pages do, and the `biwak` command line tool
uses it. It is for scripts, for people who
like a terminal, and for agents working for you. You find the page
for it under Settings, "API tokens and the command line".

## Tokens

A token is a personal key for scripts. On the API tokens page you give
it a title and choose "read only" or "read and write". The secret is
shown once; copy it then. A token sees exactly what you see (a client's
token only what clients see), it writes under your name, and it expires
30 days after its last use, or 24 hours after creating it where your
organization requires single sign-on ([Signing in](sign-in.md)).
"Revoke" ends it at any time.

## Installing the CLI

With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install 'git+https://github.com/matthiask/biwak#subdirectory=cli'
biwak login https://biwak.example.org --write
```

`biwak login` opens the browser, asks you to confirm and stores a token
(`--read` for a read-only one). `BIWAK_URL` and `BIWAK_TOKEN` override
the stored login, for scripts.

## A few examples

```sh
biwak projects
biwak todos --mine --due overdue
biwak todo add LIST "Order the tent" --due 2026-12-01 --assign 3
biwak todo done TODO
biwak todo assign 12 13 14 --to 7 --replace
biwak todo comment TODO "The plan" --attach plan.pdf
biwak checkin due
biwak checkin answer QUESTION "Busy with the launch"
biwak message post PROJECT "Kick-off" "We start Monday" --also 12
biwak search tent
biwak invite dora@example.net eve@example.net --project 4 --project 7
biwak invitations
biwak people --inactive
biwak people activate 12 13 --mail
biwak people deactivate 14
biwak projects --all --inactive-todos
biwak people reset-sign-in 12
biwak teams show 3
biwak settings --language de
```

The numbers are the IDs in the pages' addresses. Every command takes
`--json`. Items visible to clients are marked **[clients]**: check that
before you write anything a client could read. Writes through the CLI
and the API do what the pages do: they record the same events and send
the same notifications.

Teams are a shortcut of the web pages: a team's name in a text or
among the assignees sent through the CLI, the API or a reply by mail
isn't expanded. `biwak teams show TEAM` lists its members; send them
instead.

`biwak --help` lists the commands. The CLI's
[README](https://github.com/matthiask/biwak/tree/main/cli) has more
examples.

## The API

The API is under `/api/v1/` on your Biwak, with its documentation at
`/api/v1/docs` (when you are signed in). Send the token as a bearer
token in the `Authorization` header. Texts are Markdown, returned with
an HTML version as well, and lists are paged with a cursor.
