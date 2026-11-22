# UI feedback

The user's notes while testing, one round at a time. Add a new round at
the end as "## round N" with a bullet per note. Once a round is built,
its decisions go into the specs (general rules into `ui.md`, the rest
into the parts' specs) and its notes are deleted here; git keeps them.
Eight rounds are built (2026-11-22).

## Next round

- http://127.0.0.1:8000/people/13/feed/ : A user's feed doesn't provide a way to navigate to the user profile. But then, I wonder anyway if linking the feed is all that useful, and if we can't just provide a small preview of what they did last on their page with a link to the full feed at http://127.0.0.1:8000/feed/?person=13? The global activity feed links the user's feed, it should probably instead link their profile.
  - Decided 2026-11-22: the person feed page (`/people/<id>/feed/`) goes,
    no redirects; a person's page shows their last 5 activity entries
    (merged like the activity) with "All activity" to `/feed/?person=ID`;
    names in the activity link to the person's page; "My activity" opens
    `/feed/?person=<me>`.
