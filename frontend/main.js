// Everything in one bundle (rspack.config.js, {% rspack_assets "main" %} in
// base.html), SortableJS as a chunk of its own
import "./styles/bootstrap.scss"
import "./styles/main.css"
import "./styles/icons.css"

import "./theme.js"
import "./menus.js"
import "htmx.org"

// The script is deferred, the page is parsed already
if (document.querySelector("[data-todos]")) {
  import(/* webpackChunkName: "todos" */ "./todos.js")
}
