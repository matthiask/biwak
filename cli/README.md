# biwak

The command line interface of Biwak, for people and agents
(`specs/api-cli.md`).

```sh
uv tool install 'git+https://github.com/matthiask/biwak#subdirectory=cli'
biwak login https://biwak.example.org --write   # or --read
biwak projects
biwak projects create "New project" --limited   # staff; you become a member
biwak projects join ID                        # admins: biwak projects --joinable
biwak projects --all --no-staff              # admins: every project with counts; --limited, --inactive-todos, --archived
biwak lists --project PROJECT                   # --archived for the archived ones
biwak lists archive LIST                    # and unarchive: out of the way, still readable
biwak todos --list LIST
biwak todos --mine --due overdue
biwak todos --assigned-by-me             # what you assigned to others (or yourself with --mine)
biwak todos --assignee PERSON --by-due    # somebody's open to-dos, also after they left
biwak todos create LIST "Order the tent" --due 2026-12-01 --assign 3
biwak todos comment TODO "The plan" --attach plan.pdf   # --attach is repeatable
biwak reactions create TODO 👍                # again removes it; --comment ID for a comment
biwak subscriptions --item ITEM            # who gets what happens to it, and who added them
biwak subscriptions add ITEM --people 3,4 --notify --note "Have a look"   # --notify: tell them now
biwak subscriptions add ITEM            # yourself: you hear about everything on it
biwak subscriptions remove ITEM         # stop hearing about it
biwak todos complete TODO
biwak todos assign TODO TODO --to PERSON --replace   # several at once, all or nothing; each assignee told once
biwak todos move TODO --list LIST --group GROUP   # or --todos 1,2,3
biwak checkins --project PROJECT
biwak checkins due
biwak checkins answer QUESTION "Busy with the launch"   # or standard input
biwak checkins create PROJECT "Read any good books?" --schedule weekly --time 09:00
biwak notifications --level concerns_me --delivery digest
biwak members --project PROJECT
biwak members add PROJECT PERSON --notify-about-everything
biwak members invite PROJECT ada@example.org --name "Ada" --organization "Example Ltd"
biwak invitations create ada@example.org bob@example.org --project 4 --project 7   # several at once, all or nothing
biwak invitations                           # not signed in yet (staff); resend PERSON, withdraw PERSON
biwak people --inactive                      # who can't sign in; activate ID… [--mail], deactivate ID…, reset-sign-in ID
biwak orgs                                  # organizations (staff); show, create, update, merge, delete, move
biwak orgs merge 12 7                       # people and domains of 12 into 7
biwak teams                                 # teams with their members (staff); show, create, update, delete
biwak teams create "Design team" --members 3,4  # own staff; on the web picking a team picks its members
biwak members remove PROJECT PERSON          # staff anybody, everybody themselves
biwak messages --project PROJECT
biwak messages create PROJECT "Kick-off" "We start Monday" --notify nobody   # default: everybody
biwak files --project PROJECT [--folder FOLDER]
biwak files upload PROJECT plan.pdf --folder 12 --notify nobody
biwak files download FILE
biwak docs show DOC
biwak docs update DOC                                   # in $EDITOR
biwak skills install                      # the agent skills into ~/.claude/skills; biwak skills lists them
```

Every command takes `--json` for scripts and agents. Items visible to
clients are marked **[clients]**: check that before writing anything a
client could read.

`BIWAK_URL` and `BIWAK_TOKEN` override the stored login, e.g. in scripts.
