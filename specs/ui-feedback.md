# UI feedback

The user's notes while testing, one round at a time. Add a new round at
the end as "## round N" with a bullet per note. Once a round is built,
its decisions go into the specs (general rules into `ui.md`, the rest
into the parts' specs) and its notes are deleted here; git keeps them.
Nine rounds are built (2026-11-22).

## Next round

- the to do detail doesn't mention when it was created.
- the assignment lands last in the list when importing to dos, for example http://127.0.0.1:8000/todos/952/ -- karin assigned moritz f appears after all comments.
- the 'All people' link on the bottom of a person page can go.
- grouping in the feed: the two circles of consecutive assignment (for example) touch, the list needs a slightly larger line height or something.
- are all images and files sent through Django views? That will be slow with the object storage! Or what do you say?
  - Decided 2026-11-22: pages use the files' storage URLs directly: with
    the bucket presigned URLs valid 3600 seconds (cached on the server
    so a file's URL stays the same for most of that time and browsers
    can cache it), on disk (development) `MEDIA_URL` served by Django's
    `serve()` like `STATIC_URL`. The app's checking download URLs stay
    only where an address must stay valid: mails, the API's `*_html`,
    links people copy to share. Losing access (deactivated, hidden from
    clients) leaves an already handed out URL usable for up to an hour:
    accepted.
