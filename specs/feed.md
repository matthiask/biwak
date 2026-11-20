# Activity feed, bookmarks, links

## Activity feed

From the events (`notifications.md`):

- **Per project**, **per person** (what someone did) and **across
  everything** a person can see.
- Grouped by day, consecutive events on the same item merged ("Ada
  completed 5 to-dos in Website relaunch").
- Filters: type of item, person, visible to clients.
- Visibility applies to every entry (`access.md`); a client's feed only
  shows what they can see now.
- Paginated by time, fast on hundreds of thousands of events.

## Bookmarks

Any item or project, per person, private. A list of one's bookmarks,
newest first, with the item's current title and project. Bookmarked items
show a marker.

## Links

Links to outside tools on a project or on any item: Figma files,
repositories and issues, Google Drive documents, staging and production
sites, a project in a time tracking or accounting tool.

- URL, title, kind. The kind is recognised from the URL for an icon
  (a small table of known hosts, everything else "link").
- Shown prominently on the project page, in order, editable by staff.
- Internal by default; can be made visible to clients.
- Later and only where useful: integrations per kind fetching live data
  (title and preview by oEmbed, an issue's state, a budget). No tool is
  hard-coded into the core.
