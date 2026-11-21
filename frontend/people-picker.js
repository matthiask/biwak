// The people picker (specs/todos.md, "Assignees"): a <select multiple
// data-people-picker> of people (assignees, subscribers, whom to notify)
// becomes pills, each with × to remove, and
// a field which opens the list of the others on focus and click and filters
// while typing. Up and Down choose, Enter or a click picks, Escape closes,
// Backspace in the empty field takes the last pill away. The options come
// members first (the server's order, ``assignable_people()``); a person who
// isn't a member yet says so, since assigning makes them one. The select
// stays in the form (hidden), so the form posts it as it always did and
// without JavaScript it's usable as it is.
// Keyboard handling as in mentions.js.

import { avatar, optionAvatar } from "./avatar.js"

let counter = 0

function attach(select) {
  const id = select.id || `people-${++counter}`
  const listId = `${id}-list`
  const inputId = `${id}-picker`
  const texts = {
    placeholder: select.dataset.placeholder || "Assign…",
    empty: select.dataset.empty || "Nobody found",
    remove: select.dataset.remove || "Remove %(name)s",
    new: select.dataset.new || "not in the project yet",
  }

  const root = document.createElement("div")
  root.className = "wb-picker"
  const pills = document.createElement("span")
  pills.className = "wb-picker-pills"
  const input = document.createElement("input")
  input.type = "text"
  input.id = inputId
  input.className = "wb-picker-input"
  input.placeholder = texts.placeholder
  input.autocomplete = "off"
  input.setAttribute("role", "combobox")
  input.setAttribute("aria-autocomplete", "list")
  input.setAttribute("aria-expanded", "false")
  input.setAttribute("aria-controls", listId)
  const label = select.getAttribute("aria-label")
  if (label) input.setAttribute("aria-label", label)
  const list = document.createElement("ul")
  list.id = listId
  list.className = "wb-mentions list-group wb-picker-list"
  list.setAttribute("role", "listbox")
  list.hidden = true
  root.append(pills, input, list)
  select.after(root)
  select.hidden = true
  select.dataset.pickerInput = inputId
  // The label of the form field focuses the new field
  if (select.id)
    for (const forLabel of document.querySelectorAll(
      `label[for="${select.id}"]`,
    ))
      forLabel.htmlFor = inputId

  const options = [...select.options]
  let shown = []
  let active = -1

  const chosen = () => options.filter((option) => option.selected)

  const renderPills = () => {
    pills.replaceChildren(
      ...chosen().map((option) => {
        const pill = document.createElement("span")
        pill.className = "wb-pill"
        const name = document.createElement("span")
        name.textContent = option.textContent
        const remove = document.createElement("button")
        remove.type = "button"
        remove.className = "wb-pill-remove"
        remove.textContent = "×"
        remove.setAttribute(
          "aria-label",
          texts.remove.replace("%(name)s", option.textContent),
        )
        remove.addEventListener("click", () => {
          option.selected = false
          changed()
          input.focus()
        })
        pill.append(avatar(optionAvatar(option)), name, remove)
        return pill
      }),
    )
  }

  const changed = () => {
    select.dispatchEvent(new Event("change", { bubbles: true }))
    renderPills()
    if (!list.hidden) renderList()
  }

  const matches = () => {
    const query = input.value.trim().toLowerCase()
    return options.filter(
      (option) =>
        !option.selected && option.textContent.toLowerCase().includes(query),
    )
  }

  const renderList = () => {
    shown = matches()
    if (active >= shown.length) active = shown.length - 1
    if (active < 0 && shown.length) active = 0
    list.replaceChildren(
      ...(shown.length
        ? shown.map((option, index) => {
            const item = document.createElement("li")
            item.id = `${listId}-${index}`
            item.className = `list-group-item list-group-item-action${index === active ? " active" : ""}`
            item.setAttribute("role", "option")
            item.setAttribute(
              "aria-selected",
              index === active ? "true" : "false",
            )
            const name = document.createElement("span")
            name.textContent = option.textContent
            item.append(avatar(optionAvatar(option)), " ", name)
            if (option.dataset.member === "false") {
              const detail = document.createElement("small")
              detail.className = "wb-mentions-detail"
              detail.textContent = texts.new
              item.append(" ", detail)
            }
            // mousedown keeps the focus in the field
            item.addEventListener("mousedown", (event) => {
              event.preventDefault()
              pick(option)
            })
            return item
          })
        : [emptyItem()]),
    )
    if (active >= 0 && shown.length) {
      input.setAttribute("aria-activedescendant", `${listId}-${active}`)
      list.children[active]?.scrollIntoView({ block: "nearest" })
    } else input.removeAttribute("aria-activedescendant")
  }

  const emptyItem = () => {
    const item = document.createElement("li")
    item.className = "list-group-item text-body-secondary"
    item.textContent = texts.empty
    return item
  }

  const open = () => {
    list.hidden = false
    input.setAttribute("aria-expanded", "true")
    renderList()
  }

  const close = () => {
    list.hidden = true
    input.setAttribute("aria-expanded", "false")
    input.removeAttribute("aria-activedescendant")
    active = -1
  }

  const pick = (option) => {
    option.selected = true
    input.value = ""
    active = 0
    changed()
  }

  root.addEventListener("click", (event) => {
    if (event.target === root || event.target === pills) input.focus()
  })
  input.addEventListener("focus", open)
  input.addEventListener("click", open)
  input.addEventListener("input", () => {
    active = 0
    open()
  })
  input.addEventListener("blur", () => {
    input.value = ""
    close()
  })
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      if (list.hidden) return open()
      if (!shown.length) return
      const step = event.key === "ArrowDown" ? 1 : -1
      active = (active + step + shown.length) % shown.length
      renderList()
    } else if (event.key === "Enter") {
      // Not submitting the form, and not Ctrl+Enter of the inline form
      if (!list.hidden && active >= 0 && shown[active]) {
        event.preventDefault()
        event.stopPropagation()
        pick(shown[active])
      } else if (!list.hidden) {
        event.preventDefault()
      }
    } else if (event.key === "Escape") {
      if (list.hidden) return
      event.preventDefault()
      // Not closing the inline form or the edit form as well
      event.stopPropagation()
      input.value = ""
      close()
    } else if (event.key === "Backspace" && !input.value) {
      const last = chosen().at(-1)
      if (last) {
        last.selected = false
        changed()
      }
    }
  })

  // A reset puts the form's own selection back
  select.form?.addEventListener("reset", () => setTimeout(renderPills))
  renderPills()
}

function attachAll(root) {
  const selects = [
    ...(root.matches?.("select[data-people-picker]") ? [root] : []),
    ...(root.querySelectorAll?.("select[data-people-picker]") ?? []),
  ]
  for (const select of selects) {
    if (select.dataset.pickerReady) continue
    select.dataset.pickerReady = "true"
    attach(select)
  }
}

attachAll(document)
// Forms htmx inserts later (the edit form in place of a view, live updates)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
