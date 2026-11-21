// Everything in one bundle (rspack.config.js, {% rspack_assets "main" %} in
// base.html), SortableJS as a chunk of its own
import "./styles/bootstrap.scss"
import "./styles/main.css"
import "./styles/icons.css"

import "./theme.js"
import "./menus.js"
import "./reactions.js"
import "./palette.js"
import "./shortcuts.js"
import "./copy.js"
import "./mentions.js"
import "./toolbar.js"
import "./paste.js"
import "./peek.js"
import "./checklist.js"
import "./editing.js"
import "htmx.org"
// Forms in a <dialog> (biwak/modals.py)
import "./modal.js"
import "./rule-widget.js"
import "./assignees.js"
import "./view-edit.js"
import "./lantern.js"
import "./live.js"

// The script is deferred, the page is parsed already; dragging to-dos and
// groups
if (document.querySelector("[data-todos]")) {
  import(/* webpackChunkName: "todos" */ "./todos.js")
}

// Previewing the theme and the accent color on the settings page
if (document.querySelector("[data-appearance-preview]")) {
  import("./appearance-preview.js")
}

// Attaching files to texts (specs/files.md)
// (also forms htmx brings in: the chunk is loaded when the first one appears)
function loadAttachments() {
  import(/* webpackChunkName: "attachments" */ "./attachments.js")
}
if (document.querySelector("[data-attachments]")) loadAttachments()
else {
  document.addEventListener("htmx:after:process", function once(event) {
    if (
      event.target.matches?.("[data-attachments]") ||
      event.target.querySelector?.("[data-attachments]")
    ) {
      document.removeEventListener("htmx:after:process", once)
      loadAttachments()
    }
  })
}

// Dragging the lists of a project, the links of a project or an item
if (document.querySelector("[data-sortable-order]")) {
  import(/* webpackChunkName: "sortable-order" */ "./sortable-order.js")
}

// Docs edited live (specs/collaboration.md), the doc's editor page only
if (document.querySelector("[data-collab]")) {
  import(/* webpackChunkName: "collab" */ "./collab.js")
}
