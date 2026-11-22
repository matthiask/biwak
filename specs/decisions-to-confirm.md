# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Tables and pasted Markdown (specs/rich-editor.md, 2026-11-22)

- **"Insert table"** is in the toolbar after "Code" (icon `table`); in
  the Markdown source it inserts an empty 2×2 table's Markdown on lines
  of its own.
- **The table's bar** sits above the table at its left edge, over the
  line before it (a floating panel in the surface color with a shadow,
  like the link's address field); it shows while the cursor is in a
  table and the editor or the bar has the focus. Icons: row above
  `arrow-bar-up`, row below `arrow-bar-down`, column left
  `arrow-bar-left`, column right `arrow-bar-right`, delete row
  `dash-square`, delete column `x-square`, delete table `trash`,
  alignment `text-left`/`text-center`/`text-right`; names as titles and
  for screen readers.
- **"Row above" is unavailable in the header row**, like "Delete row"
  (a row above it would have to become the header); both shown dimmed
  (`aria-disabled`), not hidden.
- **Keyboard:** Tab from a cell reaches the bar (Tab leaves the field
  there too), Escape goes back to the cell; the bar keeps the focus
  after an action.
- **Alignment pressed again** takes it off (no alignment, `---`).
- **Pasted Markdown when undone** becomes the plain text, whose
  Markdown characters are then escaped (`\## Packing`).
