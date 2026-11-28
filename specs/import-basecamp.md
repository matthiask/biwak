# Importing a Basecamp 4 account

For moving an existing team over: reads the Basecamp API and creates
projects, people and items.

**Status:** built (2026-11-21), the download cache 2026-11-22, fewer queries 2026-11-23, email forwards 2026-11-23, the answer cache 2026-11-23, organizations by domain 2026-11-23, renewing the token 2026-11-27. Not built: other people's bookmarks (the API
only gives the token owner's). Dropped (decided 2026-11-23):
`--lazy-files` (fetching old attachments when first opened: nothing to
fetch once the Basecamp account is cancelled) and the import as a job in
the cluster (the cache and `--archive` make running it locally enough).

## Running it

The code is `biwak/importer/`: `client.py` the API, `convert.py` HTML
to Markdown, `importer.py`, `images.py`, `models.py` `ImportedObject`,
`support.py` recorded shapes with made-up data and a fake client for
the tests.

`BASECAMP_TOKEN=... ./manage.py import_basecamp --account ID --project ID
[--project ID ...] [--templates] [--dry-run] [--since YYYY-MM-DD] [--full]
[--include-disabled] [--user EMAIL] [--archive] [--cache-dir DIR | --no-cache]
[--answers-max-age HOURS] [--token-command CMD]`.
Always dry-run first: counts per kind, people to create, problems, what
goes into internal containers, archived recordings skipped.

- The token must be an administrator's: only they get the people's
  addresses (others get them redacted; the importer reports it and
  creates placeholder people `basecamp-ID@import.invalid`).
- **The token expires** (found 2026-11-27: a big project's import
  stopped with a 401 after 50 minutes): the Basecamp CLI's OAuth tokens
  last an hour. `--token-command "basecamp auth token"` runs the command
  for the token (without `BASECAMP_TOKEN`, which the CLI would echo
  back) and again whenever Basecamp answers 401, retrying the request
  once with the new token ("token renewed" in the progress). A 401
  without the option, or with a token the command can't renew, stops
  the run (`client.Unauthorized`, not an `ApiError`, which would turn
  every remaining request into a problem in the report) and says how to
  go on: a rerun continues, since what was imported is skipped.
- The import runs as the token's owner (`/my/profile.json`, or
  `--user`), who must be Biwak staff: they create the projects and own
  the bookmarks.
- **Idempotent:** `ImportedObject(basecamp_id, basecamp_type,
  content_type, object_id)` maps what was imported, so a second run
  updates titles, texts, due dates, assignees, completion, archived
  lists, categories and visibility, and adds new comments; it doesn't
  change imported comments, positions or files. **Basecamp wins**
  (decided 2026-11-22, for now): a recording changed in Basecamp since
  the last run (every one with `--full`) gets Basecamp's state, also
  where it was changed in Biwak meanwhile (a to-do completed in Biwak
  and open in Basecamp is reopened); comments made in Biwak stay.
  **Undoing Biwak's change happens now** (decided 2026-11-27): when the
  to-do's last completing (or reopening) in Biwak is newer than
  Basecamp's time (the completion's, or `updated_at`, Basecamp doesn't
  say when it was reopened), the importer completes or reopens it at the
  time of the run, without a person ("Biwak"), the event noted as its
  own (`data["imported"] = "basecamp"`, `importing(noted=)`): "Biwak
  reopened this (Basecamp import)" in the timeline and the feed, after
  what it undid. At Basecamp's time it sorted before the change it
  undid, in a line of the creator's, and the timeline left it out.
  **Basecamp's changes name nobody** (decided 2026-11-28 by the user,
  after a to-do's creator who had left months before "edited" it):
  Basecamp says when a recording changed, never who changed it, so what a
  later run brings over (edits, renames, visibility, archiving,
  reopening, assignments changed since) is recorded at Basecamp's time
  without a person, noted as the import's ("Biwak edited this (Basecamp
  import)", `Importer._from_basecamp()`); a completion without its
  person in Basecamp too. Assignments at a to-do's creation stay the
  creator's, and so do docs, whose versions need an author. The events
  earlier runs recorded in the creator's name were changed the same way
  (`activity` 0025: their times are Basecamp's, in milliseconds).
  Unchanged recordings aren't touched. `--since` skips leaves
  (to-dos, cards, messages, docs, files, answers, comments) last updated
  before the date; containers are always read.
- **`--archive`** (decided 2026-11-22): archives each project in
  Basecamp (`PUT /projects/ID/status/archived.json`) once its import went
  through; a failed import archives nothing, projects already archived
  are left alone, a dry run lists what it would archive. Accounts may
  limit archiving to administrators and the project's creator: Basecamp
  answers 403 and the import stops there (rerun without `--archive`, the
  import itself is done).
- **Progress** on stderr while it runs (decided 2026-11-22; `-v 0`
  silences it, the report goes to stdout at the end): each project
  ("[2/14]", its name, archived or not), its number of people, each
  tool as it starts, a line every 25 items with the requests sent and
  the time so far, a summary per project, and every wait of a second or
  more (the rate limit, a 429, a server error being retried).
- **Later runs skip what didn't change** (decided 2026-11-22): each
  imported recording remembers Basecamp's `updated_at` and comment
  count; when both are the same, the recording isn't updated and its
  comments and subscribers aren't fetched (the two requests per
  recording that made a second run as slow as the first). The report
  counts them as unchanged (a dry run too). Their times aren't written
  back either (found 2026-11-27: every rerun set Basecamp's `updated_at`
  again, also on items changed in Biwak since). Changed subscriptions don't
  change `updated_at`, so they come along only with `--full`, which reads
  everything. `ImportedObject`'s `basecamp_updated_at` and `basecamp_comments_count` (cards say
  `comment_count`), stored once the recording's comments and subscribers
  are done, so an interrupted run reads it again; rows from before have
  none and are read completely once. The children of containers (lists,
  groups, folders, card tables' columns, questions' answers) are still
  listed, new children don't change the parent; what the listing already
  gives (visibility, completion, assignees, archived) is still compared,
  costing no request. `--since` skips older leaves before any of this.
- **Several tools of a kind** (two to-do sets, several message boards
  or Docs & Files) are merged as they come (decided 2026-11-22): their
  lists, messages and files land together in the project. The report
  lists the projects that had several, with the tools' names ("Camp
  kitchen, To-dos: "To-dos", "Kitchen to-dos"").
- **Switched-off tools** are skipped unless `--include-disabled`
  (decided 2026-11-22): the report (also a dry run's) lists those that
  aren't empty, with what's in them; empty ones (Basecamp's defaults)
  stay silent. Checking costs a request per switched-off tool: the
  tool's own record (`/todosets/ID.json`: `todolists_count` and the
  to-dos in `completed_ratio`; `/message_boards/ID.json`:
  `messages_count`; `/vaults/ID.json`: `vaults_count`,
  `documents_count`, `uploads_count`; `/card_tables/ID.json`: its
  columns' `cards_count`; `/questionnaires/ID.json`: `questions_count`),
  e.g. "Camp kitchen, Card table "Planning": 12 cards". A tool that can't
  be checked is a problem in the report. Tools never imported (schedule,
  chat, …) are ignored, on or off.
- **Files over the upload limit** (100 MB, `files.models.MAX_SIZE`;
  decided 2026-11-22: really large files belong elsewhere) aren't
  imported: the report lists each with its size, where it would have
  gone (project and folder, or "a text in" the project) and its link
  in Basecamp. Known sizes skip the download; a text keeps "name (not
  imported: too large)" in its place. The run goes on.
- **Download cache** (decided 2026-11-22): a run into a fresh or reset
  database, or with `--full`, would download every file again. Downloads
  (uploads and files in texts) are cached on disk, by default in
  `$XDG_CACHE_HOME/biwak/basecamp/` (`~/.cache/biwak/basecamp/` without
  it), `--cache-dir DIR` elsewhere, `--no-cache` neither reads nor writes
  it. **The key is where the API redirects to**, the storage location
  without its query (the signed, short-lived part): `FileCache` in
  `client.py`, a file per location named by its SHA-256 (in a
  subdirectory of its first two characters), nothing else stored. Not
  the API URL: an upload's `download_url`
  (`…/buckets/B/uploads/U/download/NAME`) stays the same when a new
  version replaces the file (Basecamp keeps the upload's ID and URL), so
  it would serve the old file; the storage location is a different one
  per version (verified 2026-11-22 with an upload of two versions; files
  in texts are `…/blobs/UUID/download/NAME`). So the API's request is
  still made (and counts against the rate limit), only the storage
  download is skipped. An answer without a redirect isn't cached.
  Written to a temporary file in the same directory and renamed, so an
  interrupted run leaves no half file; a failed download stores nothing;
  never cleaned up by the importer. **Profile images aren't cached**:
  `avatar_url` is the person's (`…/people/TOKEN/avatar`), the same
  whatever the image; people with an image are never fetched again
  anyway. The report counts files downloaded and from the cache ("Files:
  3 downloaded, 12 from the cache"), and those answered without a
  redirect. A dry run downloads nothing.
- **Answer cache** (decided 2026-11-23: the time goes into Basecamp's
  requests at 50 per 10 seconds, not into writing Biwak, so a dry run
  followed by the run cost the requests twice): the API's JSON answers
  (`get()`, `paginate()` with the `Link` header) are stored in the cache
  directory's `answers/` (`AnswerCache` in `client.py`) and reused while
  younger than `--answers-max-age` hours (default 1, 0 always asks;
  decided 2026-11-23 by the user, it was 6: a completion in Basecamp
  went unnoticed by a later run; the cache is for one work session,
  a dry run and the run after it;
  `--no-cache` neither). Keyed by the SHA-256 of who asks and the URL:
  what an answer contains depends on who asks (addresses only for
  administrators). Who asks is the token's person
  (`/my/profile.json`, asked at the start of every run, never from the
  cache; decided 2026-11-27, it was the token: a renewed token found
  nothing); the token itself isn't stored. Errors aren't cached,
  an older answer is fetched and overwritten, none is deleted. What
  changes in Basecamp within the hour is missed by that run, not lost:
  the run stores the `updated_at` it saw, so the next run after the
  answers expired takes it up. Downloads still ask the API for the
  redirect (the signed location is short-lived). The report counts
  "Basecamp answers: N from the cache".
- **Few queries** (decided 2026-11-23: the import may run locally
  against production through an SSH tunnel, ~6 ms per query): the
  mappings of a listing's records (`ImportedObject`) are read with one
  query per listing and kept for the project (`Importer._preload()`,
  `_remember()` keeps them up to date), not per Basecamp type for the
  whole account: what was moved to another project in Biwak is still
  found. Everybody (by ID and address) and the people's mappings are
  read once per run. The objects themselves are still read each time.
  Events recorded inside `importing()` don't touch the projects'
  activity times (an UPDATE each): `recompute_activity()` sets them
  once per project, also when the import stops halfway (as far as it
  got), the same times as before.
  `QueriesTest` keeps the first run's count from creeping back.
- **Rates:** at most 50 requests per 10 seconds, 429 waited out
  (`Retry-After`); one request per recording for its comments and its
  subscribers (on later runs only for changed ones), so big accounts take
  a while the first time.

## Importing the whole account (planned, 2026-11-22)

Goal: import everything still current in one go (all active projects,
archived ones changed in the last few years) instead of project by
project. Waiting for Basecamp's account export to confirm the plan.

- **The API only lists projects you're on:** `/projects.json` gave 115
  active and at least 15 archived projects (only the first page of
  archived ones counted) for an account owner and admin, which isn't all
  of them.
- **The export as the source: probably not.** As far as we know it is a
  browsable HTML archive with the files, not the API's JSON. Check it
  for what the importer relies on: client visibility per recording (the
  rule that a client never sees what was internal depends on it),
  people's email addresses, Basecamp's IDs (a second run updates),
  subscriptions, check-in schedules, assignees as people. Parsing HTML
  would be a second, worse importer.
- **Plan:** the export as the inventory, the API as the source. Compare
  the export's project IDs with what the API lists; the person importing
  gets added to the missing projects in Basecamp; then a bulk selection
  in `import_basecamp` (e.g. `--all-active --archived-since DATE`)
  walking `/projects.json` and `?status=archived`. The API has no
  archiving date, so the cutoff would be the project's `updated_at`.
- **Runtime:** about two requests per recording (comments,
  subscribers) at 50 per 10 seconds: hours for a big account. Reruns
  update, so an interrupted run is simply started again.
- **After importing in production:** merge the imported organization of
  the own company into the own organization, rename it and add the
  domain (done locally, 2026-11-22).
- **The person importing** becomes a member of every project they were
  only added to for the import (the importer copies Basecamp's
  members); that's fine (decided 2026-11-22).
- **Archived projects** depend on the export: if it makes a browsable
  archive easily, archived projects may not be imported at all;
  otherwise a cutoff by `updated_at` (open).

## Running the whole import in production (idea, 2026-11-22)

The projects: the active and archived ones from Basecamp's project list
(`basecamp projects list`, `/projects.json?status=archived`), excluded
and sample projects skipped by the importer. Hours of runtime, memory
mostly one downloaded file (up to 100 MB): one process per project (a
shell loop over the IDs, so memory stays bounded and one failure doesn't
stop the rest; a rerun skips what's done). For now it runs locally
against production (`fl manage-remote biwak-feinheit-app
~/projects/sites/biwak "import_basecamp …"`, in the argocd repository),
so the download cache survives pod restarts; the checkout must match the
deployed version. Not as a job in the cluster (decided 2026-11-23).

## Mapping

| Basecamp | Biwak |
| --- | --- |
| Project | Project, members with staff/client from Basecamp |
| To-do set, to-do list | List |
| To-do list group | Group of the list |
| To-do | To-do (assignees, due and start dates, completion, notes, repeating) |
| Card table | List with its columns as groups, shown as board; the columns' colors as below |
| Card | To-do in its column's group; steps as a checklist in the notes (confirmed 2026-11-21: the reason for checklists in Markdown) |
| Message board, message | Message board, message (category by name, ignoring case, in the installation's one list; created when missing, with Basecamp's icon as its emoji; confirmed 2026-11-21) |
| Vault (folder), document, upload | Folder, doc, file |
| Questionnaire, question, answer | Check-in question, answer |
| Comment | Comment |
| Client visibility | Visible to clients on the container or item |
| Subscriptions, bookmarks | Subscriptions (who can see it), bookmarks |
| Email forwards, forward | Message (see below) |
| Schedule, chat, pings, wormholes | Not imported |
| Boosts | Not imported (decided 2026-11-23 by the user), though Biwak has reactions |

### Column colors

Decided 2026-11-23 by the user: a card table column's `color` (bc3-api,
"Change color of a column": white, red, orange, yellow, green, blue,
aqua, purple, gray, pink, brown, or `null`) becomes the group's color,
the nearest of the palette (`BASECAMP_COLORS` in
`biwak/importer/importer.py`); a second run takes over a changed color
like a changed title. A to-do list group with a `color` is mapped the
same way.

| Basecamp | Biwak |
| --- | --- |
| white, `null`, anything else | none |
| red, orange | Ember |
| yellow | Moss (the clients' amber is reserved) |
| green | Forest |
| blue | Lake |
| aqua | Glacier |
| purple | Heather |
| gray | Slate |
| pink | Alpenglow |
| brown | Bark |

## Rules

- **Through the operations** (`AGENTS.md`), inside
  `activity.operations.importing(at=...)`: events notify nobody and carry
  the original time; the original times are set on items, comments and
  projects afterwards. Open pages and live editors still check access at
  once when an import changes who sees what. Basecamp doesn't say when
  somebody was assigned: a new to-do's assignments are dated at its
  creation, so the timeline shows them before the comments; people
  assigned since the last run at the to-do's `updated_at` (decided
  2026-11-22).
- **No mails from an import** (decided 2026-11-22: nobody hears about
  anything before people use Biwak): no notifications, questions paused,
  and imported check-in occurrences count as summarized
  (`checkins.operations.add_occurrence()`), so `send_mails` sends no
  summaries of past check-ins (it did, found 2026-11-22). Tests run
  `send_mails` with the after-commit callbacks, where mails are sent.
- **Visibility** as in Basecamp, so a client never sees what was internal
  there: top-level containers and items get Basecamp's
  `visible_to_clients`, children inherit. What was **internal inside a
  visible container** goes into an internal "<container> (internal)"
  (decided 2026-11-21): a top-level folder for docs and files (nested
  folders flattened into it), a list for to-dos (groups of the same
  title; a board for a card table). An internal answer to a visible
  question can't move and is skipped and reported. A client's internal
  message stays internal.
- **People** by address. Those without an account are created (never
  admins) as staff or client as in Basecamp. **Own staff active in
  Basecamp are active** (decided 2026-11-22: they work in Biwak from
  the start): Basecamp's employees still among the account's people,
  not a tombstone, with a real address. **Everybody else is inactive**
  (clients, externals, placeholders, people gone from Basecamp), so
  nobody else gets mail or a login before someone decides
  (`activation.md`); the operations accept inactive people only inside
  `importing()`. Active people are never marked as left by a later run.
- **Excluded projects** (decided 2026-11-22): `importer.EXCLUDED` lists
  Basecamp project IDs never imported; a run for one reads only the
  project and reports it as skipped.
- **Basecamp's sample people are never imported** (decided 2026-11-22):
  `DummyUser` entries (made-up colleagues with `example.com` addresses,
  from the demo project every new account gets). A project with any of
  them among its people is Basecamp's sample project: skipped before
  anything is written, reported as a problem. One turning up anywhere
  else stops the run (`ImportRefused`, the command's error).
  Companies become organizations: employees get the own organization,
  clients and collaborators their company's (collaborators become
  externals). Existing people keep theirs. A company is the organization
  it was imported as before (by Basecamp's company ID, `Company` in the
  mapping), else the one of its name (ignoring case and spaces), else a
  new one. **The account's own company** (its employees') never becomes
  an organization, whatever it or the own organization is called
  (decided 2026-11-22: renaming the own organization made every run
  create the company again); its collaborators are externals without
  one. **Merging organizations** moves the mapping to the organization
  merged into (`organizations.operations.merge()`), so a merge sticks.
  **Without a company the domain decides** (decided by the user
  2026-11-23: people removed from Basecamp have no company, so staff of
  the own organization's domain who left were imported as individual
  externals): a new client or collaborator without a company gets the
  organization whose domains include the address's, as invitations do
  (`org_ops.for_new_person()`; free-mail domains never match; the own
  and external organizations only when an admin imports,
  `org_ops.can_touch()`). A collaborator who gets the own organization
  so is own staff, still inactive like collaborators (waiting to be
  activated). The dry run says so after the kind: "Gus Example
  <gus@team.example> (staff, Example Team by the address)". People with
  a company (also the own company's collaborators) keep the rule above.
- **People who left** (decided 2026-11-22, `activation.md`): the
  account's people (`/people.json`) are read once per run, also when
  later runs skip unchanged recordings; inactive people who turn up in a
  project but aren't among them get `left_at` (the run's date). The
  report lists them ("People who left Basecamp:"), a dry run too
  without writing. People with `left_at` who are among the account's
  people again get it cleared ("Back in Basecamp:", decided 2026-11-22
  by the user), only when the importer set it (`left_in_basecamp`), not
  when somebody was deactivated in Biwak.
- **Marks:** imported people get a drawn mark like everybody when
  they're created (`people.md`, "Stage 2: drawn marks"), counted with
  the organization's people who haven't left, so those imported
  together, waiting to be activated, get different ones.
- **Profile images** (decided 2026-11-21): for people without an image
  in Biwak, `avatar_url` from `people/<id>.json` (`people.json` has
  null), processed like an upload, never overwriting one. Basecamp's
  generated ones (a flat square with initials, its beige placeholder)
  are skipped, told apart by content (`looks_generated()`: scaled to 64
  pixels, the four corners within 12 per channel, and quantized to 8
  colors the most common covering at least 60 %). A dry run fetches
  nothing; people with an image are never fetched again.
- **Rich text:** HTML to Markdown with `markdownify`
  (`biwak/richtext/htmlmarkdown.py`, shared with pasting); mentions of the
  project's people become `[@Name](person:ID)`, others stay `@Name`;
  files in texts are downloaded once and attached. **Links to
  recordings** (on `3.basecamp.com` and `app.basecamp.com`) keep
  Basecamp's address in the stored text and lead to what was imported
  from them when the text is shown (`render_markdown()`,
  `biwak/importer/links.py`; decided 2026-11-28 by the user): whatever
  was imported first, links pasted later too, a comment's anchor
  (`#__recording_ID`) to the imported comment. One query per text with
  such links; links to what wasn't imported lead to Basecamp. Before,
  the importer rewrote the stored texts at the end of each project,
  which missed targets imported in later runs.
- **Check-ins:** the schedule becomes a rule through
  `schedules.validate()` (`every_day` with days weekly on those,
  `every_other_week` interval 2, `every_month` by day or by
  `week_instance`: "the 2nd Monday", and "the last Monday" as the last
  one whether Basecamp says -1 or 5), in the installation's time zone
  (Basecamp's has none; confirmed 2026-11-21), `start_date` the first
  date. Imported **paused**, so Biwak doesn't start mailing people
  unasked. Occurrences come from the
  answers' `group_on`.
- **Email forwards** (decided 2026-11-23 by the user): each forward
  becomes an internal message (also when a client forwarded it) in the
  category "Email forwards" with 📨, created when missing like the
  others. By the forwarder, with the line about the original sender above
  the text as when filing a forwarded mail (`forwarding.md`: "Forwarded
  from <ada@example.org>, 3 Dec 2026"; Basecamp gives only the sender's
  address, the date is the forward's), in the forwarder's language. The
  text is the mail's plain lines (Basecamp keeps them with autolinks,
  `convert.plain_to_markdown()`), files as in other texts; replies become
  comments. The API wants the bucket in the path here
  (`/buckets/ID/inboxes/ID/forwards.json`,
  `/buckets/ID/inbox_forwards/ID/replies.json`; without it 404, checked
  2026-11-23). Archived forwards can't be found: the recordings' listing
  refuses the type, the forwards' listing ignores `status=archived`
  (both checked 2026-11-23).
- **Repeating to-dos** (2026-11-23; an earlier version of this spec said
  the API has none): a to-do's `repetition_schedule`, in the to-do and
  in its list's listing, though not in Basecamp's documentation. Only
  the newest to-do of a series has it: Basecamp creates the next one
  ahead and moves the schedule on, as Biwak moves the rule
  (`todos.md`), so older ones, open or done, come in without a rule and
  nothing branches. Only open, active to-dos get a rule (completing one
  with a rule while importing would make a next one); `end_date` is the
  end date, the time of day is dropped (to-dos have dates). A schedule
  we don't know is a problem in the report and the to-do doesn't repeat.
  `recurrence_of()`:

  | `frequency` | `days` | Rule |
  | --- | --- | --- |
  | `every_week` | weekdays (0 Sunday) | weekly on those days |
  | `every_day_of_month` | days of the month | monthly on those days |
  | `custom_month` (`month_interval`) | days of the month | every n months on those days |
  | `every_month` (`week_instance`) | a weekday | monthly on the nth weekday |
  | `every_day`, `every_other_week` | weekdays | as for check-ins |

  The 29th to 31st alone fall on the last day of shorter months. Seen in
  the API 2026-11-23: the first four. Unlike Basecamp, the next to-do
  only comes once the current one is completed.
  **Imported before** (decided 2026-11-23 by the user): to-dos imported
  before schedules were stay unchanged in Basecamp and are skipped by
  later runs; the listing gives their schedule anyway, so a later run
  adds it, without a request and without `--full`, to an open to-do
  without a rule which never had one in Biwak (no edit event of its
  repeat, by anybody or an import: a rule removed on purpose stays
  removed). The report lists them ("Schedules added to to-dos imported
  before", a dry run "to add").
- **Archived** (decided 2026-11-21, `archiving.md`): archived to-dos
  come in completed at the recording's `updated_at`, by the importing
  person unless Basecamp names who completed it, with their comments;
  archived lists and projects stay archived; archived messages, docs,
  files and questions are skipped and listed in the report.
- **Templates** (decided 2026-11-22, `templates.md`): `--templates`
  imports the account's project templates and its to-do list library
  as templates, once per import (with or without `--project`). The API
  serves them like projects: `GET /templates.json`, each template a
  bucket with a dock (fetched from `/templates/ID.json` when the listing
  has none), its tools imported as a project's; the library is `GET
  /template_library/todolists.json` → `{bucket, todolists}`, one
  template named "To-do list library" whatever the bucket's name
  (decided 2026-11-22: one library) holding those lists. Mapped as `Template`, so a second run
  updates them; created with `create_template()`, so no members
  (Basecamp's people of a template aren't added), visibility as in
  Basecamp, archived templates archived. `Importer.run_templates()`.
- **Not imported:** trashed recordings (anything in Basecamp's trash:
  to-dos, messages, docs, files, comments; confirmed 2026-11-21), pins of
  messages (not in the API), older versions of files, docs' history.
