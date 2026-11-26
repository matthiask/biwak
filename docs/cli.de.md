# Die CLI und die API

Die API deckt ab, was die Seiten tun, und das Kommandozeilenwerkzeug
`biwak` nutzt sie. Sie ist für Skripte, für Leute, die gerne im Terminal
arbeiten, und für Agents, die für dich arbeiten. Die Seite dazu findest
du in den Einstellungen unter „API-Tokens und die Kommandozeile“.

## Tokens

Ein Token ist ein persönlicher Schlüssel für Skripte. Auf der Seite
API-Tokens gibst du ihm einen Titel und wählst „nur lesen“ oder „lesen
und schreiben“. Das Secret wird einmal gezeigt; kopiere es dann. Ein
Token sieht genau, was du siehst (das Token von Kund:innen nur, was
Kund:innen sehen), schreibt unter deinem Namen und läuft 30 Tage nach
seiner letzten Verwendung ab, oder 24 Stunden nach dem Erstellen, wo
deine Organisation Single Sign-on verlangt ([Anmelden](sign-in.de.md)).
„Widerrufen“ beendet es jederzeit.

## Die CLI installieren

Mit [uv](https://docs.astral.sh/uv/):

```sh
uv tool install 'git+https://github.com/matthiask/biwak#subdirectory=cli'
biwak login https://biwak.example.org --write
```

`biwak login` öffnet den Browser, bittet dich zu bestätigen und
speichert ein Token (`--read` für eines, das nur liest). `BIWAK_URL` und
`BIWAK_TOKEN` gehen dem gespeicherten Login vor, für Skripte.

Befehle und Optionen mit Tab vervollständigen, einmal pro Shell:

```sh
echo 'eval "$(biwak completion bash)"' >> ~/.bashrc     # bash
echo 'eval "$(biwak completion zsh)"' >> ~/.zshrc       # zsh
biwak completion fish > ~/.config/fish/completions/biwak.fish   # fish
```

Im Terminal sind Titel Links auf ihre Seite in Biwak.

## Ein paar Beispiele

```sh
biwak projects
biwak todos --mine --due overdue
biwak todos --mine --started
biwak todos create LIST "Zelt bestellen" --due 2026-12-01 --starts 2026-11-28 --assign 3
biwak lists add-from-text LIST plan.md --preview
biwak todos complete TODO
biwak todos --assignee 7
biwak todos --list LIST --mine
biwak todos --list LIST --group none
biwak todos assign 12 13 14 --to 7 --replace
biwak todos comment TODO "Der Plan" --attach plan.pdf
biwak checkins due
biwak checkins answer QUESTION "Mit dem Launch beschäftigt"
biwak messages create PROJECT "Kick-off" "Wir beginnen am Montag" --also 12
biwak lists copy LIST --to PROJECT --shift 7
biwak projects --templates
biwak projects create "Website" --template 5 --member 12
biwak items move ITEM --to PROJECT --confirm
biwak search Zelt
biwak forwarded file 21 --todo LIST
biwak invitations create dora@example.net eve@example.net --project 4 --project 7
biwak invitations
biwak people --inactive
biwak people --left
biwak people activate 12 13 --mail
biwak people deactivate 14
biwak projects --all --inactive-todos
biwak people reset-sign-in 12
biwak teams show 3
biwak settings --language de
```

Die Zahlen sind die IDs in den Adressen der Seiten. Jeder Befehl nimmt
`--json`. Einträge, die für Kund:innen sichtbar sind, sind mit
**[clients]** markiert: Prüfe das, bevor du etwas schreibst, das
Kund:innen lesen könnten. Was über die CLI und die API geschrieben wird,
tut, was die Seiten tun: Es hält dieselben Ereignisse fest und sendet
dieselben Benachrichtigungen. Die Ausgabe der CLI und ihre Hilfe sind
auf Englisch.

Teams sind eine Abkürzung der Webseiten: Der Name eines Teams in einem
Text oder unter den Zugewiesenen, über die CLI, die API oder eine
Antwort per Mail geschickt, wird nicht aufgelöst. `biwak teams show
TEAM` zeigt seine Mitglieder; schicke stattdessen diese.

`biwak --help` zeigt die Befehle: eine Gruppe pro Sache in der Mehrzahl
(`biwak todos`, `biwak lists`, `biwak messages`, …), die allein sie
auflistet (`biwak lists --project 4`) und die Verben `show`, `create`,
`update` und `delete` hat und eigene (`biwak todos complete`); `biwak
GROUP --help` zeigt die einer Gruppe. Das
[README](https://github.com/matthiask/biwak/tree/main/cli) der CLI hat
mehr Beispiele.

## Agent-Skills

Die CLI bringt Skills für [Claude Code](https://claude.com/claude-code)
mit, die häufige Arbeiten über `biwak` erledigen. Verknüpfe sie einmal
mit deinem Claude Code, und wieder, wenn `biwak` neue bringt:

```sh
biwak skills install
biwak skills
```

- **biwak-triage:** was dich braucht: die ungelesenen Einträge der
  Laterne und die To-dos, die in den nächsten 7 Tagen fällig sind,
  gruppiert in handeln, warten und im Auge behalten. Als gelesen
  markiert es nur, wenn du darum bittest.
- **biwak-from-mail:** eine Mail (eingefügt oder als `.eml`-Datei) als
  To-do oder Mitteilung, mit ihren Anhängen.
- **biwak-weekly-summary:** die letzten 7 Tage eines Projekts; als
  interne Mitteilung gepostet nur, wenn du darum bittest.
- **biwak-handover:** die offenen To-dos von jemandem, der geht oder
  abwesend ist, Projekt für Projekt übergeben.

Sie schlagen vor und schreiben nur, was du bestätigt hast; Neues ist
intern, ausser du bestätigst, dass Kund:innen es sehen dürfen. Ein
Upgrade von `biwak` aktualisiert sie.

## Die API

Die API liegt unter `/api/v1/` auf deinem Biwak, mit ihrer Dokumentation
unter `/api/v1/docs` (wenn du angemeldet bist). Schicke das Token als
Bearer-Token im Header `Authorization`. Texte sind Markdown, auch als
HTML zurückgegeben, und Listen sind mit einem Cursor seitenweise.
