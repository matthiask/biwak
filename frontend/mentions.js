// Mentioning people in text fields with data-mentions="URL"
// (specs/notifications.md). Typing "@" and a part of a name or address
// lists the matching people (the URL answers ?q= with at most 10); those
// who can't see the item are greyed out with the reason and can't be
// chosen. For items not created yet, data-mentions-visible="#id" names the
// "visible to clients" checkbox, whose state is sent as ?visible=1.
// Up/Down choose, Enter or a click inserts
// "[@Ada](person:ID)", Escape closes. Without JavaScript the fields stay
// plain fields. Adapted from Governance's mentions.js.
//
// Teams (specs/teams.md, staff only) come last, saying how many of their
// members can see the item and why the others are left out; choosing one
// inserts a mention per member who can, but not of those mentioned in the
// field already.

import { avatar, teamMark } from "./avatar.js"

const DELAY = 150

const queryAt = (field) =>
  mentionQuery(field.value.slice(0, field.selectionStart))

// The "@query" at the end of the text before the caret, if any: "@" at the start or after a
// space or an opening bracket, no line break, not already a mention
export function mentionQuery(before) {
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

// The list of people (and teams) for a query, below a place in a field:
// shared by textareas (here) and the rich editor (editor/mentions.js).
// ``anchor`` is the element the list goes after (its parent is made
// relative); ``position(start)`` says where the "@" is, relative to that
// parent; ``onPick(person, mentions)`` inserts: ``mentions`` is the
// Markdown ("[@Ada](person:12) ", one per member for a team, without those
// in ``mentioned()``); ``owner`` gets aria-controls and
// aria-activedescendant.
export function mentionList({
  url,
  visible,
  anchor,
  owner,
  position,
  onPick,
  mentioned,
}) {
  const list = document.createElement("ul")
  list.className = "wb-mentions list-group"
  list.id = `${owner.id || `mentions-${++counter}`}-mentions`
  list.setAttribute("role", "listbox")
  list.hidden = true
  anchor.after(list)
  anchor.parentElement.classList.add("position-relative")
  owner.setAttribute("aria-autocomplete", "list")
  owner.setAttribute("aria-controls", list.id)

  let results = []
  let active = -1
  let current = null
  let timer = null
  let controller = null

  const close = () => {
    clearTimeout(timer)
    controller?.abort()
    current = null
    list.hidden = true
    results = []
    owner.removeAttribute("aria-activedescendant")
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
        if (person.team) {
          item.dataset.team = person.id
          detail.textContent = person.detail
          item.append(teamMark(), " ", name, " ", detail)
        } else {
          detail.textContent = person.available ? person.email : person.reason
          // "Ada Example, Example Ltd" (specs/organizations.md)
          const organization = person.organization
            ? `, ${person.organization}`
            : ""
          item.append(
            avatar(person.avatar),
            " ",
            name,
            organization,
            " ",
            detail,
          )
        }
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
      owner.setAttribute("aria-activedescendant", `${list.id}-${active}`)
    } else {
      owner.removeAttribute("aria-activedescendant")
    }
    if (results.length) place()
  }

  // Below the line with the "@", starting at it
  const place = () => {
    const at = position(current.start)
    const maxLeft = anchor.parentElement.clientWidth - list.offsetWidth
    list.style.top = `${at.top}px`
    list.style.left = `${Math.max(0, Math.min(at.left, maxLeft))}px`
  }

  const pick = (person) => {
    let mention = syntax(person)
    if (person.team) {
      // Not twice: those mentioned in the field already are left out
      const already = mentioned()
      mention = person.members
        .filter((member) => !already.has(String(member.id)))
        .map(syntax)
        .join("")
    }
    const typed = current
    close()
    onPick(typed, mention)
  }

  const load = async (typed) => {
    controller?.abort()
    controller = new AbortController()
    try {
      const target = new URL(url, location.href)
      const params = target.searchParams
      params.set("q", typed.query)
      // New items: who will see it depends on the visibility checkbox
      const checkbox = visible ? document.querySelector(visible) : null
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

  return {
    // ``typed``: {query, start} or null
    update(typed) {
      clearTimeout(timer)
      if (!typed) {
        close()
        return
      }
      if (
        current &&
        current.query === typed.query &&
        current.start === typed.start
      )
        return
      current = typed
      timer = setTimeout(() => load(typed), DELAY)
    },
    close,
    // Whether the key was the list's
    keydown(event) {
      if (list.hidden) return false
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const found = next(active, event.key === "ArrowDown" ? 1 : -1)
        if (found >= 0) active = found
        render()
      } else if (event.key === "Enter") {
        if (active < 0) return false
        pick(results[active])
      } else if (event.key === "Escape") {
        close()
      } else return false
      // Not submitting the form, closing the inline form or a menu as well
      event.preventDefault()
      event.stopPropagation()
      return true
    },
  }
}

// The short name: pages show the current one, the label is a fallback
const syntax = (person) => {
  const label = (person.short_name || person.name).replace(/[[\]]/g, "")
  return `[@${label}](person:${person.id}) `
}

function attach(field) {
  const list = mentionList({
    url: field.dataset.mentions,
    visible: field.dataset.mentionsVisible,
    anchor: field,
    owner: field,
    position(start) {
      const caret = caretPosition(field, start)
      return {
        top: Math.min(
          field.offsetTop + caret.top + caret.height - field.scrollTop,
          field.offsetTop + field.offsetHeight,
        ),
        left: field.offsetLeft + caret.left - field.scrollLeft,
      }
    },
    mentioned: () =>
      new Set(
        [...field.value.matchAll(/\]\(person:(\d+)\)/g)].map((m) => m[1]),
      ),
    onPick(typed, mention) {
      field.setRangeText(mention, typed.start, field.selectionStart, "end")
      field.dispatchEvent(new Event("input", { bubbles: true }))
    },
  })
  // The rich editor (frontend/editor/) writes into the hidden field: not
  // typed here
  const rich = () => field.richEditor?.active
  field.addEventListener("input", () =>
    list.update(rich() ? null : queryAt(field)),
  )
  field.addEventListener("keydown", (event) => list.keydown(event))
  field.addEventListener("blur", () => list.close())
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
