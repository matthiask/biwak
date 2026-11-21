// Mentioning people in text fields with data-mentions="URL"
// (specs/notifications.md). Typing "@" and a part of a name or address
// lists the matching people (the URL answers ?q= with at most 10); those
// who can't see the item are greyed out with the reason and can't be
// chosen. For items not created yet, data-mentions-visible="#id" names the
// "visible to clients" checkbox, whose state is sent as ?visible=1.
// Up/Down choose, Enter or a click inserts
// "[@Name](person:ID)", Escape closes. Without JavaScript the fields stay
// plain fields. Adapted from Governance's mentions.js.

const DELAY = 150

// The "@query" before the caret, if any: "@" at the start or after a
// space or an opening bracket, no line break, not already a mention
function queryAt(field) {
  const before = field.value.slice(0, field.selectionStart)
  const match = /(?:^|[\s(])@([^@\n[\]()]{0,40})$/.exec(before)
  return match
    ? { query: match[1], start: before.length - match[1].length - 1 }
    : null
}

// Where a character of the field is (relative to its border box, not
// scrolled): a hidden copy with the same text styles, wrapped the same way
const MIRRORED = [
  "boxSizing",
  "width",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "borderStyle",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "fontFamily",
  "fontSize",
  "fontStyle",
  "fontWeight",
  "lineHeight",
  "letterSpacing",
  "wordSpacing",
  "textIndent",
  "textTransform",
  "tabSize",
]

function caretPosition(field, index) {
  const style = getComputedStyle(field)
  const mirror = document.createElement("div")
  for (const property of MIRRORED) mirror.style[property] = style[property]
  const single = field.tagName === "INPUT"
  Object.assign(mirror.style, {
    position: "absolute",
    top: "0",
    left: "-9999px",
    visibility: "hidden",
    overflow: "hidden",
    whiteSpace: single ? "pre" : "pre-wrap",
    overflowWrap: single ? "normal" : "break-word",
  })
  // Without the textarea's scrollbar
  const scrollbar = field.offsetWidth - field.clientWidth
  mirror.style.width = `${field.offsetWidth - scrollbar}px`
  mirror.style.boxSizing = "border-box"
  mirror.textContent = field.value.slice(0, index)
  const marker = document.createElement("span")
  marker.textContent = field.value[index] || "@"
  mirror.append(marker)
  document.body.append(mirror)
  const position = {
    top: marker.offsetTop + Number.parseFloat(style.borderTopWidth),
    left: marker.offsetLeft + Number.parseFloat(style.borderLeftWidth),
    height: marker.offsetHeight,
  }
  mirror.remove()
  return position
}

let counter = 0

function attach(field) {
  const url = field.dataset.mentions
  const list = document.createElement("ul")
  list.className = "wb-mentions list-group"
  list.id = `${field.id || `mentions-${++counter}`}-mentions`
  list.setAttribute("role", "listbox")
  list.hidden = true
  field.after(list)
  field.parentElement.classList.add("position-relative")
  field.setAttribute("aria-autocomplete", "list")
  field.setAttribute("aria-controls", list.id)

  let results = []
  let active = -1
  let current = null
  let timer = null
  let controller = null

  const close = () => {
    list.hidden = true
    results = []
    field.removeAttribute("aria-activedescendant")
  }

  // The next person who can be chosen, in the direction of step
  const next = (from, step) => {
    for (let i = 1; i <= results.length; i++) {
      const n = results.length
      const index = (((from + step * i) % n) + n) % n
      if (results[index].available) return index
    }
    return -1
  }

  const render = () => {
    list.replaceChildren(
      ...results.map((person, index) => {
        const item = document.createElement("li")
        item.id = `${list.id}-${index}`
        item.className = `list-group-item${person.available ? " list-group-item-action" : " is-unavailable"}${index === active ? " active" : ""}`
        item.setAttribute("role", "option")
        item.setAttribute("aria-selected", index === active ? "true" : "false")
        item.setAttribute("aria-disabled", person.available ? "false" : "true")
        const name = document.createElement("span")
        name.textContent = person.name
        const detail = document.createElement("small")
        detail.className = "wb-mentions-detail"
        detail.textContent = person.available ? person.email : person.reason
        item.append(name, " ", detail)
        // mousedown keeps the focus in the field
        item.addEventListener("mousedown", (event) => {
          event.preventDefault()
          if (person.available) pick(person)
        })
        return item
      }),
    )
    list.hidden = !results.length
    if (active >= 0) {
      field.setAttribute("aria-activedescendant", `${list.id}-${active}`)
    } else {
      field.removeAttribute("aria-activedescendant")
    }
    if (results.length) place()
  }

  // Below the line with the "@", starting at it, inside the field's
  // parent (which is relative)
  const place = () => {
    const caret = caretPosition(field, current.start)
    const top = Math.min(
      field.offsetTop + caret.top + caret.height - field.scrollTop,
      field.offsetTop + field.offsetHeight,
    )
    const left = field.offsetLeft + caret.left - field.scrollLeft
    const maxLeft = field.parentElement.clientWidth - list.offsetWidth
    list.style.top = `${top}px`
    list.style.left = `${Math.max(0, Math.min(left, maxLeft))}px`
  }

  const pick = (person) => {
    const label = person.name.replace(/[[\]]/g, "")
    const mention = `[@${label}](person:${person.id}) `
    field.setRangeText(mention, current.start, field.selectionStart, "end")
    field.dispatchEvent(new Event("input", { bubbles: true }))
    close()
  }

  const load = async (typed) => {
    controller?.abort()
    controller = new AbortController()
    try {
      const target = new URL(url, location.href)
      const params = target.searchParams
      params.set("q", typed.query)
      // New items: who will see it depends on the visibility checkbox
      const checkbox = field.dataset.mentionsVisible
        ? document.querySelector(field.dataset.mentionsVisible)
        : null
      if (checkbox?.checked) params.set("visible", "1")
      const response = await fetch(target, {
        credentials: "same-origin",
        signal: controller.signal,
      })
      if (!response.ok || current !== typed) return
      results = await response.json()
      active = results.findIndex((person) => person.available)
      render()
    } catch {
      // Aborted, or offline: no list
    }
  }

  field.addEventListener("input", () => {
    current = queryAt(field)
    clearTimeout(timer)
    if (!current) {
      close()
      return
    }
    const typed = current
    timer = setTimeout(() => load(typed), DELAY)
  })

  field.addEventListener("keydown", (event) => {
    if (list.hidden) return
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      const found = next(active, event.key === "ArrowDown" ? 1 : -1)
      if (found >= 0) active = found
      render()
    } else if (event.key === "Enter") {
      if (active < 0) return
      // Not submitting the form, and not Ctrl+Enter of the inline form
      event.preventDefault()
      event.stopPropagation()
      pick(results[active])
    } else if (event.key === "Escape") {
      event.preventDefault()
      // Not closing the inline form or a menu as well
      event.stopPropagation()
      close()
    }
  })

  field.addEventListener("blur", close)
}

export const attachAll = (root) => {
  for (const field of root.querySelectorAll(
    "textarea[data-mentions], input[data-mentions]",
  )) {
    if (!field.dataset.mentions || field.dataset.mentionsAttached) continue
    field.dataset.mentionsAttached = "true"
    attach(field)
  }
}
attachAll(document)
// Also fields htmx inserts later
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
