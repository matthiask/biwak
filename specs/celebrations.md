# Celebrations and animations

The idea (2026-11-21): the tool celebrates achievements a little, for
example finishing a to-do, and moves a bit more in general. No more
emojis in the reaction picker (decided 2026-11-21: the 32 stay).

**Status:** spec (2026-11-21), all five moments confirmed the same day.
Built so far: moment 1 and 2 (`frontend/celebrate.js`, 2026-11-21).

Decisions made while building moments 1 and 2 (2026-11-21):

- Completing was a plain form post and redirect. `celebrate.js` takes the
  submit over (`data-celebrate="complete|reopen"` on the check's form and the
  to-do page's button, so the keyboard's `x` is covered too): the request
  goes out at once with `fetch`, the animation runs beside it, and when both
  are done the page follows the redirect (a reload where it's the same page,
  so counts, recurrences and the completed section come from the server).
  If the request fails, the form is submitted the normal way.
- With `prefers-reduced-motion: reduce` the script doesn't intercept at all.
- Live updates (`live.js`) leave a row alone while it has `is-completing`,
  so the refresh the server triggers doesn't cut the collapse short.
- The burst is for the last open to-do of the row's container (group or
  list, a page's section); "All done." only for the whole list: the list page
  renders it when everything is completed (in `#live-completed`), the script
  shows it before the page follows. The last row waits 0.8 s before
  collapsing so the dots are seen.
- The to-do's page: the icon pops (250 ms), then the page follows.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`.

**Depends on:** nothing.

**Touches:** `frontend/styles/main.css` (keyframes, a few classes),
the scripts that complete to-dos and add reactions (`frontend/todos.js`,
`frontend/reactions.js`, `frontend/lantern.js`), the to-do row and
the reactions templates; `docs/` if anything is worth a sentence.

## Principles

- **Short and quiet:** 150 to 600 ms, no sound, never blocking: the
  action is done on the server already, the animation only follows it.
  Nothing animates on page load.
- **`prefers-reduced-motion: reduce` turns everything off** (the end
  state appears at once), as the existing animations do.
- **CSS first** (keyframes, transitions); JavaScript only adds or
  removes a class. No animation library, no canvas.
- **Colors from the palette tokens** (`--wb-accent-*`,
  `--wb-palette-*`), light and dark.
- **One celebration per action:** completing ten to-dos in a row doesn't
  pile up effects.

## Moments (decided 2026-11-21)

1. **Completing a to-do:** the check fills with a short pop (scale 1 →
   1.2 → 1) in the accent color, the title strikes through left to
   right, then the row fades and collapses (instead of vanishing). On
   lists, "My to-dos", Home, the to-do's page (the "Complete" button's
   icon). Reopening: no celebration, just the reverse fade.
2. **Completing the last open to-do of a list** (or of a group): a
   small burst of a few accent-colored dots from the check (CSS only,
   a dozen pseudo-elements, under a second), and the list's empty state
   says so ("All done.").
3. **Adding a reaction:** the new pill pops in (scale), one's own
   count bumps.
4. **The lantern:** its dot pulses once when something new arrives
   live; entries slide in rather than appear.
5. **Small transitions:** menus and the reaction picker fade in (100 ms),
   modals scale in slightly, rows added live slide in (beside the
   existing highlight).

Not: confetti over the whole page, streaks or counters, sounds.

## Done when

- Each moment as above, with the reduced-motion case.
- Browser tests only for what JavaScript does (the class added after
  completing, the row removed after the animation, nothing waiting on
  the animation with reduced motion); no tests of the CSS itself
  (`AGENTS.md`).
- A short screen recording or screenshots of the moments, looked at.
