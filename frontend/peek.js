// The peek below a to-do's row (specs/glance.md): the first click loads it
// (htmx), the next one closes it. Capturing, so that htmx doesn't load it
// again.
document.addEventListener(
  "click",
  (event) => {
    const button = event.target.closest("[data-peek]")
    if (!button) return
    const target = document.getElementById(button.getAttribute("aria-controls"))
    const open = target?.firstElementChild
    for (const other of document.querySelectorAll(
      `[data-peek][aria-controls="${button.getAttribute("aria-controls")}"]`,
    )) {
      other.setAttribute("aria-expanded", open ? "false" : "true")
    }
    if (open) {
      event.stopPropagation()
      target.replaceChildren()
    }
  },
  true,
)
