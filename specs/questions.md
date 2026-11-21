# Open questions and decisions to confirm

Collected 2026-11-20 from all specs. The decisions themselves stay in
the specs (and the dated list in `SPEC.md`); this file only lists what
still waits for an answer, with a suggestion. Answer by number; the
answer goes into the spec named, and the entry leaves this file.

## Asked, not answered yet

1. **Production runs with `LIVE=False`** (the secret). That turns off
   Django's security middleware and the cache-busting static file
   names. Intended? *Suggestion: set `LIVE=True`.*
2. **Real-time editing** (`collaboration.md`, branch `collaboration`):
   merge only once Redis is configured, or merge now and deploy later?
   (Since 2026-11-21 the channel layer uses the shared Redis of
   `CACHE_URL`, already in the cluster's environment; no `REDIS_URL`
   needed.) *Suggestion: merge and deploy together.*
3. **Search order** (`search.md`): newest first by `updated_at` (built),
   or by relevance (needs another cursor)? *Suggestion: keep newest
   first.*
4. **Search "only mine"** (`search.md`): items you created (built), or
   also assigned to you or commented on? *Suggestion: created or
   assigned.*
5. **Search matching** (`search.md`): all words anywhere in an item
   (title, text and comments together; built), or all in one text?
   *Suggestion: keep it.*
6. **Replies with attachments over 25 MB** (`notifications.md` stage 2):
   left out silently and noted in `InboundMessage.error`. Tell the
   person? *Suggestion: a line in the posted comment ("an attachment
   was too large").*
7. **Signature logos in replies** (`notifications.md` stage 2): Outlook's
   inline images become attachments. Leave out small inline images?
   *Suggestion: leave out inline images under 20 KB.*
8. **Reply tokens on leaving** (`notifications.md` stage 2): revoke them
   when a person is deactivated or removed from a project? Access is
   checked on every reply anyway. *Suggestion: no, the check is enough.*

## Values and wording the agents chose (marked open in the specs)

9. **Check-ins** (`checkins.md`):
   - the summary at 07:00 in the question's time zone, while the digest
     uses the installation's;
   - 5 occurrences per page;
   - no default time of day (the form asks);
   - people with the level "nothing" are still asked (only the summary
     respects it).

   *Suggestion: all as built.*
10. **Collaboration** (`collaboration.md`):
    - the editor's wording ("Changes are saved as you type.", "You are
      watching. You can't change this doc.", "Watch live", "Make
      read-only");
    - a version with several authors is kept by whoever started it
      within its 10 minutes;
    - no limit on doc size beyond the websocket frame limit.

    *Suggestion: as built.*
11. **Files** (`files.md`, stage 2):
    - saving a doc gives the lock up (moot once collaboration is merged:
      it removes the locks);
    - a file keeps its title when a new version is uploaded;
    - previews don't enlarge images smaller than 400 px.

    *Suggestion: as built.*
12. **Wording of mails and messages** nobody decided:
    - the answer to rejected replies (`biwak/inbound/receive.py`);
    - the check-in mails;
    - "Reply to this mail to comment/answer.";
    - the Google refusal and the passkey offer (confirmed).

    *Suggestion: review them all at once with the German translation.*

## Lists of agents' decisions never confirmed

Each spec section below lists decisions an agent made while building,
marked "proposed" or "to confirm". None looked wrong in review. Confirm
them as a whole, or name the ones to change.

13. `todos.md`, "Decisions made while building stage 1" (presets
    counted from the due date, short months falling on the last day,
    count meaning "more to come", one series, who creates the next
    to-do, API `recurrence` values).
14. `todos.md`, "Decisions made while building stage 2" (archived
    projects and lists left out, "this week" until Sunday, filters
    refusing unknown values, the iCal feed's contents).
15. `projects-overview.md`, Status (audit log ignoring the activity
    columns, `GREATEST`, what the card counts count, card wording,
    archived projects in the API).
16. `files.md`, "Details of stage 1" (who links which attachment,
    where attachments can be added, trashed items' attachments not
    downloadable).
17. `files.md`, stage 2 details (doc versions per 10 minutes and
    person, clients replace only what they uploaded, pinning events
    notifying nobody, mentions in new forms without `@` completion).
18. `checkins.md`, Status (the model additions `starts_on`, `next_at`,
    `Occurrence.date`, who answers, the summary rules).
19. `search.md`, "Decisions made on the way" (besides 3 to 5: the
    archived filter's wording).

## Not decided, not urgent

20. **Agent skills** (`api-cli.md`): which ones, after the importer;
    needs a spec.
21. **The Basecamp importer** (`import-basecamp.md`): needs recorded
    API responses of a real account to work against.
22. **Replying by mail is off** until DNS, Resend and three
    environment variables are set up (`notifications.md`, "Setting it
    up").
