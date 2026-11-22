# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Rich editor (specs/rich-editor.md, 2026-11-22)

- **Looking like the page:** task items show their box as the page
  does (clickable, it ticks in the document), mentions as `@Name` in
  the page's mention style (the label as written, not the current short
  name), tables as plain bordered cells, images through the
  attachment's download URL. Tight lists without paragraph spacing,
  as on the page.
- **The link button and Ctrl+K** open a small address field under the
  selection (Enter sets it, an empty address removes the link, Escape
  or leaving it cancels); nothing selected inserts the address as a
  link.
- **"Markdown"** is the toolbar's last button (an icon, at the right),
  pressed while the source shows; the live doc editor has none (its
  shared document is the editor's).
- **Plain text pasted** (no formatting on the clipboard, Ctrl+Shift+V)
  stays text: lines become breaks, blank lines paragraphs; Markdown
  characters in it are not interpreted (they're escaped when saved).
  The "Markdown" switch is the way to paste Markdown source.
- **Buttons without a selection:** bold, italic and code apply to what's
  typed next (no "bold" placeholder as in the source); heading is level
  2 and toggles; code on several blocks makes one code block of their
  lines.
- **Tab in table cells** leaves the field like elsewhere (the spec's
  rule); arrow keys move between cells.
- **Saving through forms keeps unchanged blocks' source** on the server
  (`BootstrapMixin`, `richtext.preserve.keep_source()`): only the
  blocks somebody changed are written in the editor's style.
- **A line starting with `--`** (a mail signature's) is escaped as
  `\--` when its paragraph is saved (the serializer's rule for `-` at a
  line start), so pasted mails gain a backslash.
