# Languages: German, and a language per person

The interface in German as well as English, chosen per person. The
texts have been marked for translation from the start (`SPEC.md`);
this part adds the German catalog and makes everything follow the
person's choice. Decided with the user 2026-11-22. German only for now;
a third language is a catalog, nothing else.

**Status:** built 2026-11-22 (branch `languages`). Choosing:
`biwak/accounts/languages.py` (`language_for()`), the settings' Language
section, `language` on `/api/v1/me/`, `biwak settings --language`.
`User.invitation_language` remembers the language of the last invitation
mail. The catalog: `conf/locale/de/LC_MESSAGES/django.po` (`fl mm -l de`,
`fl cm`); `biwak/test_catalog.py` (complete, compiled, current with the
code, the glossary, no `gettext()` at import), `biwak/test_german.py`
(pages and mails). Relative times: `biwak/text.py` (`ago()`, units of
their own for German's dative). The feed's events are whole sentences
(`activity/_event.html`, the `{% capture %}` tag).

Depends on: everything with texts; `accounts` (the `language` field,
`middleware.py` activating it), `notifications.md` and `mail-sending.md`
(mails), `keyboard.md` (the settings page, the palette), `api-cli.md`,
`activation.md` (invitations), `help.md`.

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
- Written by the agent building this part, reviewed by the user
  afterwards (changing a word in the catalog is cheap).

### Glossary (proposed, for the user to review)

| English | German |
|---|---|
| project | Projekt |
| to-do, to-dos | To-do, To-dos |
| list, group | Liste, Gruppe |
| board (view) | Board |
| message board, message | Nachrichten, Nachricht |
| doc, file, folder | Dokument, Datei, Ordner |
| check-in, question, answer | Check-in, Frage, Antwort |
| comment | Kommentar |
| subscribe, subscribers | abonnieren, Abonnent:innen |
| mention | Erwähnung |
| client, clients | Kund:in, Kund:innen |
| staff | Team (the own people), Mitarbeitende |
| partner (staff outside the own organization) | Externe ("die Externen", "eine externe Person", "Ada ist extern", badge "extern"; decided 2026-11-22: "Partner" is taken by Holacracy and the co-owners) |
| visible to clients | für Kund:innen sichtbar |
| team (the named set) | Team |
| lantern | Laterne |
| feed, activity | Aktivität |
| bookmark | Lesezeichen |
| trash | Papierkorb |
| archive, archived | archivieren, archiviert |
| public link | öffentlicher Link |
| command palette | Befehlspalette |
| settings | Einstellungen |
| sign in, sign out | anmelden, abmelden |
| assign, assignee | zuweisen, zugewiesen |
| due | fällig |

## Choosing

- **Settings** (`/accounts/settings/`, `keyboard.md`): "Language":
  Automatic (the browser's), Deutsch, English, each in its own
  language. Saved on change like the page's other settings; the page
  reloads in the new language.
- **Before choosing** (decided 2026-11-22): pages follow the browser
  (`Accept-Language`, `LocaleMiddleware`), else English; the sign-in
  pages too. Signed in with a choice, the choice wins
  (`accounts.middleware`, as now).
- **API and CLI:** `language` in `GET/PUT /api/v1/me/` (`""`, `de`,
  `en`); the API's own messages (errors) in the token owner's language
  (`api_auth.py`, as now). `biwak settings --language de` (CLI version
  bump). Texts the API returns are people's texts, not translated.

## What follows the language

- **Pages and the Django admin.** Every template text and form label
  (`gettext`, `{% translate %}`, `{% blocktranslate %}` with plurals),
  `capfirst` labels (`ui.md`).
- **JavaScript.** Texts the scripts show come from the page (data
  attributes rendered by the server, as most do now). The part
  inventories `frontend/` for English left in scripts (fallbacks,
  `aria-label`s, messages) and moves them into data attributes or a
  small catalog the page renders (`json_script`); no runtime catalog
  fetch.
- **Dates, times, numbers:** Django's formats for the language
  (`USE_L10N`): "22. Nov. 2026", 24-hour times; relative times ("vor 13
  Stunden", one unit, `ui-feedback.md` round 8); weekday and month
  names in the rule widget and check-ins' schedules; file sizes.
- **Mails** in the recipient's language: their choice, else for an
  invitation the inviter's language at the time, else English
  (`LANGUAGE_CODE`). Notifications, digests, check-in questions and
  summaries, security mails, invitations, mail reply errors: one
  helper (`translation.override(language_for(user))`) instead of the
  copies in `projects/operations.py`, `checkins/mails.py`,
  `security_mails.py`. Subjects too. Mails are rendered per recipient
  (they already are).
- **Texts stored once and shown later** are rendered when shown, in the
  reader's language: events (the feed, the lantern, history), the
  palette's actions, empty states. Anything stored as English text for
  display is a bug to fix here.
- **The calendar feed** (`/calendar/<token>.ics`): its owner's language.
- **Not translated:** people's texts, names of projects and items,
  categories, the API's field names, the CLI's output (English, for
  agents; its help too), the help pages (decided 2026-11-22: later; a
  German reader sees the English help with a line saying so).
- **Search** stays as it is (`search.md`: no stemming, both languages).

## Checks

- `makemessages` for Python, templates and the frontend's server-rendered
  texts; the `.po` and `.mo` committed in `conf/locale/de/`; a test
  that the catalog is complete (no empty or fuzzy entries, `msgfmt
  --check`), run in CI.
- A test rendering the main pages in German (staff and client) that
  finds no English left from a list of common words, and mails in each
  recipient's language (one German, one English in the same event).
- The glossary test (above).

## Decided while building (2026-11-22, see `decisions-to-confirm.md`)

- The Language section comes after Appearance: three radios (each
  language in itself, `lang` set), saved with its button like the
  others; the page comes back in the new language.
- Mails before a choice: the language of the last invitation mail
  (resending sets it again), else English. Login codes and allauth's
  mails: the recipient's language if they have one, else the page's
  (they asked for it in their browser just now).
- Feed sentences in the perfect tense ("hat „Zelt bestellen“ erstellt");
  the actions as filter labels have a context of their own (`action`,
  participles: "erstellt").
- Key names stay as on Swiss keyboards: Ctrl, Shift, Enter, Alt, Esc.
- New texts are translated in the branch that adds them (`AGENTS.md`).

## Done when

- A person chooses Deutsch, English or Automatic in Settings (and the
  API and CLI); pages, the admin, JavaScript texts, dates, relative
  times and mails follow it; without a choice pages follow the browser.
- The German catalog is complete, Swiss, "du", gender-neutral with the
  colon, using the glossary.
- Mails to several people for one event are each in their language.
- The help says how to choose (English for now).
