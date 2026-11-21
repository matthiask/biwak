// Dragging the entries of a list into a new order (the lists of a project,
// the links of a project or an item): the container with
// data-sortable-order="URL" and data-sortable-field="NAME" holds the entries
// with data-sortable-item="ID", dragged by their [data-sortable-handle].
// The request has the IDs in their new order, as NAME.
import { Sortable } from "sortablejs"
import { post } from "./http.js"

for (const container of document.querySelectorAll("[data-sortable-order]")) {
  Sortable.create(container, {
    handle: "[data-sortable-handle]",
    draggable: "[data-sortable-item]",
    animation: 120,
    onEnd(event) {
      if (event.oldIndex === event.newIndex) return
      const field = container.dataset.sortableField
      post(
        container.dataset.sortableOrder,
        [...container.querySelectorAll("[data-sortable-item]")].map((item) => [
          field,
          item.dataset.sortableItem,
        ]),
      )
    },
  })
}
