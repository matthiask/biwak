// Everything in one bundle (rspack.config.js, {% rspack_assets "main" %} in
// base.html), SortableJS as a chunk of its own
import "./styles/bootstrap.scss"
import "./styles/main.css"
import "./styles/icons.css"

import "./theme.js"
import "./menus.js"
import "./copy.js"
import "./mentions.js"
import "htmx.org"

// The script is deferred, the page is parsed already; dragging to-dos,
// groups and lists
if (document.querySelector("[data-todos], [data-sortable-lists]")) {
  import(/* webpackChunkName: "todos" */ "./todos.js")
}

// Attaching files to texts (specs/files.md)
if (document.querySelector("[data-attachments]")) {
  import(/* webpackChunkName: "attachments" */ "./attachments.js")
}

// Dragging links on projects and items
if (document.querySelector("[data-sortable-links]")) {
  import(/* webpackChunkName: "links" */ "./links.js")
}
