# Languages: German, and a language per person

The interface in German as well as English, chosen per person. The
texts have been marked for translation from the start (`SPEC.md`);
this part adds the German catalog and makes everything follow the
person's choice. Decided with the user 2026-11-22. German only for now;
a third language is a catalog, nothing else.

**Status:** built (2026-11-22).

## The German

- **Du** (decided 2026-11-22), also for clients: "Du hast 3 neue
  Benachrichtigungen".
- **Swiss spelling** (decided 2026-11-22): ss, never ß ("Grüsse",
  "gross").
- **Gender-neutral with the colon** (`AGENTS.md`: "Kund:innen",
  "Teilnehmer:innen"), never the asterisk; neutral words where they
  exist ("Mitarbeitende", "Personen").
- **One glossary** (below), used everywhere; a test checks the catalog
  for the words the glossary replaces (e.g. no "Aufgabe" where it says
  "To-do", no "ß").

### Glossary (reviewed by the user 2026-11-22)

| English | German |
|---|---|
| project | Projekt |
| to-do, to-dos | To-do, To-dos |
| list, group | Liste, Gruppe |
| board (view) | Board |
| message board, message | Mitteilungen, Mitteilung (decided 2026-11-22 by the user: "Nachricht" sounds strange; "Beitrag" is taken by "posts to everyone"); a forwarded mail is "eingehende Mail" |
| doc, file, folder | Dokument, Datei, Ordner |
| check-in, question, answer | Check-in, Frage, Antwort |
| comment | Kommentar |
| subscribe, subscribers | abonnieren, Abonnent:innen |
| mention | Erwähnung |
| client, clients | Kund:in, Kund:innen |
| staff | Team (the own people), Mitarbeitende |
| external, externals (staff outside the own organization) | Externe ("die Externen", "eine externe Person", "Ada ist extern", badge "extern"; decided 2026-11-22: "Partner" is taken by Holacracy and the co-owners, so English says "external" too) |
| visible to clients | für Kund:innen sichtbar |
| team (the named set) | Team |
| lantern | Laterne |
| feed, activity | Aktivität |
| bookmark | Lesezeichen |
| profile image, drawn mark, photo | Profilbild, Zeichnung, Foto (proposed 2026-11-22) |
| trash | Papierkorb |
| archive, archived | archivieren, archiviert |
| public link | öffentlicher Link |
| template | Vorlage |
| command palette | Befehlspalette |
| settings | Einstellungen |
| sign in, sign out | anmelden, abmelden |
| assign, assignee | zuweisen, zugewiesen |
| due | fällig |
| people who left, "left on 3 Mar 2025" | Ehemalige, "nicht mehr dabei seit 3. März 2025" (decided 2026-11-22 by the user: "gegangen" sounds like they were terminated; empty: "Keine Ehemaligen.") |

## Choosing

`biwak/accounts/languages.py` (`language_for()`); `User.language`,
activated by `biwak/accounts/middleware.py`.

- **Settings** (`/accounts/settings/`, `keyboard.md`): "Language":
  Automatic (the browser's), Deutsch, English, each in its own
  language. Saved on change like the page's other settings; the page
  reloads in the new language.
- **Before choosing** (decided 2026-11-22): pages follow the browser
  (`Accept-Language`, `LocaleMiddleware`), else English; the sign-in
  pages too. Signed in with a choice, the choice wins
  (`accounts.middleware`).
- **API and CLI:** `language` in `GET/PUT /api/v1/me/` (`""`, `de`,
  `en`); the API's own messages (errors) in the token owner's language
  (`api_auth.py`). `biwak settings --language de`. Texts the API returns are people's texts, not translated.

## What follows the language

- **Pages and the Django admin.** Every template text and form label
  (`gettext`, `{% translate %}`, `{% blocktranslate %}` with plurals),
  `capfirst` labels (`ui.md`).
- **JavaScript.** Texts the scripts show (fallbacks, `aria-label`s,
  messages) come from the page: data attributes rendered by the server
  or `json_script`; no runtime catalog fetch.
- **Dates, times, numbers:** formats per language (`biwak/formats/`,
  `FORMAT_MODULE_PATH`; templates name them, `|dateformat:"SHORT_DATE_FORMAT"`):
  English "22 Nov 2026", German "22. Nov. 2026" (decided 2026-11-22),
  24-hour times in both; relative times ("vor 13
  Stunden", one unit, `ui-feedback.md` round 8; `ago()` in
  `biwak/text.py`, units of their own for German's dative); weekday and month
  names in the rule widget and check-ins' schedules; file sizes.
- **Mails** in the recipient's language: their choice, else for an
  invitation the inviter's language at the time, else English
  (`LANGUAGE_CODE`; `User.invitation_language` remembers the language
  of the last invitation mail). Notifications, digests, check-in
  questions and summaries, security mails, invitations, mail reply
  errors: one helper (`translation.override(language_for(user))`).
  Subjects too. Mails are rendered per recipient.
- **Texts stored once and shown later** are rendered when shown, in the
  reader's language: events (the feed, the lantern, history), the
  palette's actions, empty states. Anything stored as English text for
  display is a bug.
- **The calendar feed** (`/calendar/<token>.ics`): its owner's language.
- **Not translated:** people's texts, names of projects and items,
  categories, the API's field names, the CLI's output (English, for
  agents; its help too), the help pages (decided 2026-11-22: later; a
  German reader sees the English help with a line saying so).
- **Search** stays as it is (`search.md`: no stemming, both languages).

## Checks

- `makemessages` for Python, templates and the frontend's server-rendered
  texts (`fl mm -l de`, `fl cm`); the `.po` and `.mo` committed in
  `conf/locale/de/`.
- `biwak/test_catalog.py`: the catalog is complete (no empty or fuzzy
  entries, `msgfmt --check`), compiled, current with the code, follows
  the glossary (above), no `gettext()` at import; run in CI.
- `biwak/test_german.py`: the main pages rendered in German (staff and
  client) with no English left from a list of common words, and mails
  in each recipient's language (one German, one English in the same
  event).

## Further decisions (2026-11-22, confirmed by the user)

- The Language section comes after Appearance: three radios (each
  language in itself, `lang` set), saved with its button like the
  others; the page comes back in the new language.
- Mails before a choice: the language of the last invitation mail
  (resending sets it again), else English. Login codes and allauth's
  mails: the recipient's language if they have one, else the page's
  (they asked for it in their browser just now).
- Feed sentences in the perfect tense ("hat „Zelt bestellen“ erstellt"),
  whole sentences (`activity/_event.html`, the `{% capture %}` tag);
  the actions as filter labels have a context of their own (`action`,
  participles: "erstellt").
- Key names stay as on Swiss keyboards: Ctrl, Shift, Enter, Alt, Esc.
- The palette's color names are translated: Heide, See, Wald,
  Gletscher, Glut, Alpenglühen, Moos, Schiefer, Rinde, Beere; the
  clients' amber is Bernstein.
- "all-access" projects are "offene Projekte", limited ones
  "eingeschränkt"; "Only when tagged" is "Nur wenn markiert"; Monday to
  Friday is "Werktag".
- The rule widget's controls stay pieces around the fields ("alle [3]
  Tage", "am [März] [5]"); the description below them is a whole
  sentence ("alle 2 Jahre am 5. März").
- allauth's texts people see when signing in (form errors, messages, the
  login-code mails) are in our catalog with our German
  (`biwak/accounts/allauth_texts.py`, its exact English; ours wins). The
  Django admin keeps Django's German ("Sie").
- A doc without a title is stored empty and shown as "Untitled" /
  "Unbenannt" (`files.md`). The own organization's "Our organization" and
  the importer's " (internal)" stay: names people rename.
- New texts are translated in the branch that adds them (`AGENTS.md`).
