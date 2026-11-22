# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Languages (`languages.md`, 2026-11-22)

- **The Language section** comes after Appearance, three radios
  (Automatic, Deutsch, English) with a Save button like the page's other
  sections, not saved on change: saving reloads the page in the new
  language anyway.
- **Login codes and allauth's mails** go out in the recipient's language
  if they have one (chosen or from their invitation), else in the page's
  (the browser's), not English: they asked for it in that browser just
  now.
- **The invitation's language** is the one of the last invitation mail:
  resending it in another language changes it.
- **The feed in German** is in the perfect tense ("Ada hat „Zelt
  bestellen“ erstellt"); merged entries end with "(in Webseite)". The
  actions as filter labels are participles ("erstellt").
- **Key names** stay Ctrl, Shift, Enter, Alt, Esc (Swiss keyboards).
- **The palette's color names are translated:** Heide, See, Wald,
  Gletscher, Glut, Alpenglühen, Moos, Schiefer, Rinde, Beere; the
  clients' amber is Bernstein.
- **"all-access" projects** are "offene Projekte", limited ones
  "eingeschränkt"; "Only when tagged" is "Nur wenn markiert"; Monday to
  Friday is "Werktag".
- **The rule widget's controls** stay pieces around the fields ("alle
  [3] Tage", "am [März] [5]"); the description below them is a whole
  German sentence ("alle 2 Jahre am 5. März").
