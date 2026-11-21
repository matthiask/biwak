# biwak

The command line interface of Biwak, for people and agents
(`specs/api-cli.md`).

```sh
uv tool install 'git+https://github.com/matthiask/biwak#subdirectory=cli'
biwak login https://biwak.example.org --write   # or --read
biwak projects
biwak project add "New project" --limited   # staff; you become a member
biwak project join ID                        # admins: biwak projects --joinable
biwak lists PROJECT
biwak todos LIST
biwak todos --mine --due overdue
biwak todos --assigned-by-me             # what you assigned to others (or yourself with --mine)
biwak todo add LIST "Order the tent" --due 2026-12-01 --assign 3
biwak todo comment TODO "The plan" --attach plan.pdf   # --attach is repeatable
biwak react TODO 👍                    # again removes it; --comment ID for a comment
biwak subscribers ITEM                 # who gets what happens to it, and who added them
biwak subscribe ITEM --people 3,4 --notify --note "Have a look"   # --notify: tell them now
biwak todo done TODO
biwak todo move TODO --list LIST --group GROUP   # or --todos 1,2,3
biwak checkins PROJECT
biwak checkin due
biwak checkin answer QUESTION "Busy with the launch"   # or standard input
biwak checkin add PROJECT "Read any good books?" --schedule weekly --time 09:00
biwak notifications --level concerns_me --delivery digest
biwak members PROJECT
biwak member add PROJECT PERSON --only-tagged      # notified only when tagged
biwak member invite PROJECT ada@example.org --name "Ada" --organization "Example Ltd"
biwak orgs                                  # organizations (staff); show, add, edit, merge, delete, move
biwak orgs merge 12 7                       # people and domains of 12 into 7
biwak member remove PROJECT PERSON          # staff anybody, everybody themselves
biwak messages PROJECT
biwak message post PROJECT "Kick-off" "We start Monday" --notify nobody   # default: everybody
biwak files PROJECT [FOLDER]
biwak file upload PROJECT plan.pdf --folder 12 --notify nobody
biwak file download FILE
biwak doc show DOC
biwak doc edit DOC                                     # in $EDITOR
```

Every command takes `--json` for scripts and agents. Items visible to
clients are marked **[clients]**: check that before writing anything a
client could read.

`BIWAK_URL` and `BIWAK_TOKEN` override the stored login, e.g. in scripts.
