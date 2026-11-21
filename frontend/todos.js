// Dragging to-dos within and between groups, and groups as blocks
// (items/todolist.html, specs/core.md). Each move is one request; the page
// stays as it is. SortableJS is a chunk of its own (main.js).
import { MultiDrag, Sortable } from "sortablejs"

Sortable.mount(new MultiDrag())

import "./add-todo.js"
import { post, remember } from "./http.js"

// Clicking grips selects several to-dos, dragging one of them moves them
// all; one request with the to-dos in their new order and where the first
// one is among the others
let undo = () => {}

function sortTodos(container) {
  if (Sortable.get(container)) return
  Sortable.create(container, {
    group: `todos-${container.dataset.list}`,
    handle: "[data-handle]",
    draggable: "[data-todo]",
    animation: 120,
    multiDrag: true,
    selectedClass: "is-selected",
    onStart() {
      undo = remember(document.querySelectorAll("[data-todos]"))
    },
    onEnd(event) {
      const moved = event.items.length ? event.items : [event.item]
      if (
        moved.length === 1 &&
        event.from === event.to &&
        event.oldIndex === event.newIndex
      )
        return
      const rows = [...event.to.querySelectorAll("[data-todo]")]
      const ordered = rows.filter((row) => moved.includes(row))
      const index = rows
        .slice(0, rows.indexOf(ordered[0]))
        .filter((row) => !moved.includes(row)).length
      post(
        event.to.dataset.moveUrl,
        [
          ...ordered.map((row) => ["todos", row.dataset.todo]),
          ["group", event.to.dataset.group],
          ["index", index],
        ],
        undo,
      )
      for (const row of moved) Sortable.utils.deselect(row)
    },
  })
}

function sortGroups(container) {
  if (Sortable.get(container)) return
  Sortable.create(container, {
    handle: "[data-group-handle]",
    draggable: "[data-group-item]",
    animation: 120,
    onStart() {
      undo = remember([container])
    },
    onEnd(event) {
      if (event.oldIndex === event.newIndex) return
      // The ungrouped section comes first and doesn't move
      const groups = [...container.querySelectorAll("[data-group-item]")]
      post(
        event.item.dataset.moveUrl,
        {
          index: groups.indexOf(event.item),
          quiet: "1",
        },
        undo,
      )
    },
  })
}

for (const container of document.querySelectorAll("[data-todos]"))
  sortTodos(container)
for (const container of document.querySelectorAll("[data-groups]"))
  sortGroups(container)

// Groups a live update brings (frontend/live.js)
document.addEventListener("biwak:live", (event) => {
  const node = event.detail
  for (const container of [node, ...node.querySelectorAll("[data-todos]")])
    if (container.matches("[data-todos]")) sortTodos(container)
})
