// Dragging the links of a project or an item (bookmarks/_links.html): all
// IDs in their new order, one request
import { Sortable } from "sortablejs"

function csrfToken() {
  return document.querySelector("[name=csrfmiddlewaretoken]")?.value
}

for (const container of document.querySelectorAll("[data-sortable-links]")) {
  Sortable.create(container, {
    handle: "[data-link-handle]",
    draggable: "[data-link-item]",
    animation: 120,
    onEnd(event) {
      if (event.oldIndex === event.newIndex) return
      const body = new FormData()
      for (const item of container.querySelectorAll("[data-link-item]")) {
        body.append("links", item.dataset.linkItem)
      }
      fetch(container.dataset.sortableLinks, {
        method: "POST",
        body,
        headers: { "X-CSRFToken": csrfToken() },
      }).then((response) => {
        if (!response.ok) window.location.reload()
      })
    },
  })
}
