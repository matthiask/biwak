// Everything in one bundle (rspack.config.js, {% rspack_assets "main" %} in
// base.html), SortableJS as a chunk of its own
import "./styles/bootstrap.scss"
import "./styles/main.css"
import "./styles/icons.css"

import "./theme.js"
import "./menus.js"
import "./palette.js"
import "./shortcuts.js"
import "./copy.js"
import "./mentions.js"
import "./toolbar.js"
import "./paste.js"
import "./peek.js"
import "./checklist.js"
import "htmx.org"
import "./rule-widget.js"

// The script is deferred, the page is parsed already; dragging to-dos and
// groups
if (document.querySelector("[data-todos]")) {
  import(/* webpackChunkName: "todos" */ "./todos.js")
}

// Attaching files to texts (specs/files.md)
if (document.querySelector("[data-attachments]")) {
  import(/* webpackChunkName: "attachments" */ "./attachments.js")
}

// Renewing the lock of a doc being edited (specs/files.md)
if (document.querySelector("[data-doc-lock]")) {
  import(/* webpackChunkName: "doc-lock" */ "./doc-lock.js")
}

// Dragging the lists of a project, the links of a project or an item
if (document.querySelector("[data-sortable-order]")) {
  import(/* webpackChunkName: "sortable-order" */ "./sortable-order.js")
}
