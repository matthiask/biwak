# Celebrations and animations

The tool celebrates achievements a little, for example finishing a
to-do, and moves a bit more in general.

**Status:** built (2026-11-21): `frontend/celebrate.js`,
`reactions.js`, `lantern.js`, keyframes in `main.css`.

## Principles

- **Short and quiet:** 150 to 600 ms, no sound, never blocking: the
  action is done on the server, the animation only follows it. Nothing
  animates on page load.
- **`prefers-reduced-motion: reduce` turns everything off;** the scripts
  then don't intercept at all.
- **CSS first;** JavaScript only adds or removes a class. No animation
  library, no canvas. Colors from the palette tokens.
- **One celebration per action.** Not: confetti over the page, streaks
  or counters, sounds, more emojis in the picker.

## Moments (decided 2026-11-21)

1. **Completing a to-do:** the check pops in the accent color, the
   title strikes through, the row fades and collapses; on the to-do's
   page the icon pops. `celebrate.js` takes over the submit
   (`data-celebrate="complete|reopen"`, so `x` is covered): the request
   goes out at once, and when it and the animation are done the page
   follows the redirect, so counts, recurrences and the completed
   section come from the server; a failed request submits the form
   normally. Live updates leave a row with `is-completing` alone.
   Reopening just fades back.
2. **The last open to-do of a group or list:** a burst of accent dots
   (the row waits 0.8 s before collapsing); "All done." when the whole
   list is done.
3. **Reactions:** a new pill scales in (`is-new`), a growing count bumps
   (`is-bumped`), also when others' arrive live; nothing on load.
4. **The lantern:** its dot pulses when the unread count grows live; new
   entries slide in when a live event reloads the open menu.
5. **Small transitions:** menus and the reaction picker fade in (100
   ms), modals scale in (`@starting-style`), rows new to a list slide in
   (`wb-live-enter`).
