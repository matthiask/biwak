# biwak

The command line interface of Biwak, for people and agents
(`specs/api-cli.md`).

```sh
uv tool install 'git+https://github.com/matthiask/biwak#subdirectory=cli'
biwak login https://biwak.example.org --write   # or --read
biwak projects
biwak lists PROJECT
biwak todos LIST
biwak todos --mine --due overdue
biwak todo add LIST "Order the tent" --due 2026-12-01 --assign 3
biwak todo comment TODO "The plan" --attach plan.pdf   # --attach is repeatable
biwak todo done TODO
```

Every command takes `--json` for scripts and agents. Items visible to
clients are marked **[clients]**: check that before writing anything a
client could read.

`BIWAK_URL` and `BIWAK_TOKEN` override the stored login, e.g. in scripts.
