# UI feedback

The user's notes while testing, one round at a time. Add a new round at
the end as "## round N" with a bullet per note. Once a round is built,
its decisions go into the specs (general rules into `ui.md`, the rest
into the parts' specs) and its notes are deleted here; git keeps them.
Seven rounds are built (2026-11-21).

## Next round

- The history button can go into the More drop-down.
- Visible to clients is now a button shown at the bottom of items; I'm not sure about that decision. I'd rather have it less visible. For example, I can create folders which are directly visible to the client. If I want to change that later, having to go to the More menu is fine. Same for to do lists and messages, I think.
- The full project card should be clickable, not just the title.
- The timeago filter should only show one component (13 hours ago, not 13 hours, 37 minutes ago)
- "People asked" in check ins: I wonder if grouping people by organization would be nicer. "Visible to clients" would only show client organizations when visible to clients (makes no sense otherwise). I'd also like to have a way to select multiple people at once. Or, we can use the autocomplete from the start.
  - Decided 2026-11-22: the people picker (autocomplete), with teams for several at once; clients only offered while the question is visible to clients.
- In the people of a project list, I'd like to be able to configure notifications directly and remove people from the project directly. The more menu with the modal requires too many clicks for my taste.
  - Decided 2026-11-22: removing always asks first (a modal or a confirmation in place, either is fine).

## Next round

- Ctrl+Enter should submit all kinds of forms, for example the comment form.
