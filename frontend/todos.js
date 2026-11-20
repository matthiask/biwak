// Dragging to-dos within and between groups, and groups as blocks
// (items/todolist.html, specs/core.md). Each move is one request; the page
// stays as it is. SortableJS is a chunk of its own (main.js).
import { MultiDrag, Sortable } from "sortablejs"

Sortable.mount(new MultiDrag())

import "./add-todo.js"

function csrfToken() {
  return document.querySelector("[name=csrfmiddlewaretoken]")?.value
}

function post(url, data) {
  const body = new FormData()
  for (const [key, value] of Object.entries(data)) body.append(key, value)
  return fetch(url, {
    method: "POST",
    body,
    headers: { "X-CSRFToken": csrfToken() },
  }).then((response) => {
    if (!response.ok) window.location.reload()
  })
}

// Clicking grips selects several to-dos, dragging one of them moves them
// all; one request with the to-dos in their new order and where the first
// one is among the others
for (const container of document.querySelectorAll("[data-todos]")) {
  Sortable.create(container, {
    group: `todos-${container.dataset.list}`,
    handle: "[data-handle]",
    draggable: "[data-todo]",
    animation: 120,
    multiDrag: true,
    selectedClass: "is-selected",
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
      const data = new FormData()
      for (const row of ordered) data.append("todos", row.dataset.todo)
      data.append("group", event.to.dataset.group)
      data.append("index", index)
      fetch(`/lists/${event.to.dataset.list}/todos/move/`, {
        method: "POST",
        body: data,
        headers: { "X-CSRFToken": csrfToken() },
      }).then((response) => {
        if (!response.ok) window.location.reload()
      })
      for (const row of moved) Sortable.utils.deselect(row)
    },
  })
}

for (const container of document.querySelectorAll("[data-groups]")) {
  Sortable.create(container, {
    handle: "[data-group-handle]",
    draggable: "[data-group-item]",
    animation: 120,
    onEnd(event) {
      if (event.oldIndex === event.newIndex) return
      // The ungrouped section comes first and doesn't move
      const groups = [...container.querySelectorAll("[data-group-item]")]
      post(`/groups/${event.item.dataset.groupItem}/move/`, {
        index: groups.indexOf(event.item),
        quiet: "1",
      })
    },
  })
}

// The lists on the project page, all IDs in their new order
for (const container of document.querySelectorAll("[data-sortable-lists]")) {
  Sortable.create(container, {
    handle: "[data-list-handle]",
    draggable: "[data-list-item]",
    animation: 120,
    onEnd(event) {
      if (event.oldIndex === event.newIndex) return
      const body = new FormData()
      for (const item of container.querySelectorAll("[data-list-item]")) {
        body.append("lists", item.dataset.listItem)
      }
      fetch(container.dataset.sortableLists, {
        method: "POST",
        body,
        headers: { "X-CSRFToken": csrfToken() },
      }).then((response) => {
        if (!response.ok) window.location.reload()
      })
    },
  })
}
