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
import "./select-rows.js"
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
import "./start-date.js"
import "./connection.js"
import "./stored-docs.js"
import "./people-picker.js"
import "./told.js"
import "./clients-note.js"
import "./combobox.js"
import "./invite.js"
import "./view-edit.js"
import "./lantern.js"
import "./autosubmit.js"
import "./submit-shortcut.js"
import "./save-on-change.js"
import "./filters.js"
import "./live.js"
import "./celebrate.js"

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

// The rich editor for every Markdown field (specs/rich-editor.md), also in
// forms htmx brings in
function loadEditor() {
  import(/* webpackChunkName: "editor" */ "./editor/fields.js")
}
if (document.querySelector("textarea[data-toolbar]")) loadEditor()
else {
  document.addEventListener("htmx:after:process", function once(event) {
    if (
      event.target.matches?.("textarea[data-toolbar]") ||
      event.target.querySelector?.("textarea[data-toolbar]")
    ) {
      document.removeEventListener("htmx:after:process", once)
      loadEditor()
    }
  })
}

// Dragging the lists of a project, the links of a project or an item
if (document.querySelector("[data-sortable-order]")) {
  import(/* webpackChunkName: "sortable-order" */ "./sortable-order.js")
}

// A folder's tiles: selecting, dragging, dropping (specs/files.md, "Moving
// and selecting"); uploading several files, also on the form's own page
// (the modal "Upload files" opens from the palette on other pages too)
if (document.querySelector("[data-tiles]")) {
  import(/* webpackChunkName: "files" */ "./files.js")
} else if (document.querySelector("[data-upload]")) {
  import(/* webpackChunkName: "files" */ "./upload.js")
} else {
  document.addEventListener("htmx:after:process", function once(event) {
    if (event.target.querySelector?.("[data-upload]")) {
      document.removeEventListener("htmx:after:process", once)
      import(/* webpackChunkName: "files" */ "./upload.js")
    }
  })
}

// Adding to-dos from text (specs/todos-from-text.md): dropping text files
// onto a list, the modal's preview
if (
  document.querySelector(
    "[data-drop-text], [data-drop-text-page], [data-from-text]",
  )
) {
  import(/* webpackChunkName: "from-text" */ "./from-text.js")
}

// Docs edited live (specs/collaboration.md), the doc's editor page only
if (document.querySelector("[data-collab]")) {
  import(/* webpackChunkName: "collab" */ "./collab.js")
}
