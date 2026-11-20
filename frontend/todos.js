// Dragging to-dos within and between groups, and groups as blocks
// (items/todolist.html, specs/core.md). Each move is one request; the page
// stays as it is. SortableJS is a chunk of its own (main.js).
import Sortable from "sortablejs"

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

for (const container of document.querySelectorAll("[data-todos]")) {
  Sortable.create(container, {
    group: `todos-${container.dataset.list}`,
    handle: "[data-handle]",
    draggable: "[data-todo]",
    animation: 120,
    onEnd(event) {
      if (event.from === event.to && event.oldIndex === event.newIndex) return
      post(`/todos/${event.item.dataset.todo}/move/`, {
        list: event.to.dataset.list,
        group: event.to.dataset.group,
        index: event.newIndex,
        quiet: "1",
      })
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
      })
    },
  })
}
