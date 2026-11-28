// What the server rendered into the live regions (frontend/live.js), kept
// before any script runs: the toolbar, mentions, the rich editor, the
// people picker, the rule widget and htmx add to and change the forms in
// them, which isn't a change of the page. A region fetched again is
// unchanged when the server renders what it rendered before. Imported
// first in main.js.
//
// A region the page changed itself (a form submitted, a field changed, an
// htmx request from it) forgets what was rendered: it's compared with what
// it shows, as before.

const SELECTOR = "[data-live], [data-live-list] > [id]"

// id → the normalized HTML the server sent
const rendered = new Map()

export function normalized(el) {
  const clone = el.cloneNode(true)
  // Django masks the CSRF token differently on every page
  for (const token of clone.querySelectorAll("[name=csrfmiddlewaretoken]"))
    token.removeAttribute("value")
  for (const node of [
    clone,
    ...clone.querySelectorAll(".wb-live-new, .wb-live-enter"),
  ])
    node.classList.remove("wb-live-new", "wb-live-enter")
  for (const note of clone.querySelectorAll("[data-live-note]")) note.remove()
  // What scripts set on the page (menus placed, dragging, htmx)
  for (const node of [clone, ...clone.querySelectorAll("*")]) {
    node.removeAttribute("style")
    node.removeAttribute("draggable")
    node.removeAttribute("data-htmx-powered")
    for (const name of [...node.classList])
      if (name.startsWith("htmx-") || name.startsWith("sortable-"))
        node.classList.remove(name)
    if (!node.classList.length) node.removeAttribute("class")
  }
  for (const node of [clone, ...clone.querySelectorAll("[data-live-waiting]")])
    node.removeAttribute("data-live-waiting")
  return clone.outerHTML
}

// Remembers the regions in ``root`` (and ``root`` itself) as rendered
export function remember(root) {
  const regions = [...root.querySelectorAll(SELECTOR)]
  if (root.matches?.(SELECTOR)) regions.unshift(root)
  for (const region of regions)
    if (region.id) rendered.set(region.id, normalized(region))
}

// The fresh region is what the server rendered before
export function unchanged(fresh) {
  return rendered.get(fresh.id) === normalized(fresh)
}

function forget(event) {
  let node = event.target
  if (!(node instanceof Element)) return
  while ((node = node.closest(SELECTOR))) {
    rendered.delete(node.id)
    node = node.parentElement
    if (!node) break
  }
}

for (const type of ["submit", "change", "htmx:beforeRequest"])
  document.addEventListener(type, forget, true)

remember(document)
