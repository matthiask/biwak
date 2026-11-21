// Single-key shortcuts inside pages, like GitHub's (specs/keyboard.md). One
// script serves every page: rows say what they are through attributes
// (data-kb-row on the row, data-kb-open the link, data-kb-complete the toggle
// form) and the page's actions come with a shortcut from the server (base.html's
// JSON script), so nothing here is specific to a page.
//
// Never while typing (a field, contenteditable, the live editor), never with
// Ctrl, Alt or Meta held, never with a dialog open; the person's setting
// turns all of it off (WCAG 2.1.4). Ctrl+K is the palette's, always.
import { data, openPalette, runAction } from "./palette.js"

const CURRENT = "wb-kb-current"
const SEQUENCE_WAIT = 1000

const typing = (target) =>
  target instanceof Element &&
  (target.matches("input, textarea, select, [contenteditable]") ||
    target.closest("[contenteditable], .ProseMirror"))

const rows = () =>
  [...document.querySelectorAll("[data-kb-row]")].filter(
    (row) => row.getClientRects().length,
  )
const current = () => document.querySelector(`.${CURRENT}`)
const linkOf = (row) =>
  row.matches("[data-kb-open]") ? row : row.querySelector("[data-kb-open]")

function select(row) {
  current()?.classList.remove(CURRENT)
  if (!row) return
  row.classList.add(CURRENT)
  row.scrollIntoView({ block: "nearest" })
  // Focus follows, so that screen readers read the row
  const link = linkOf(row)
  if (link) link.focus({ preventScroll: true })
  else {
    row.tabIndex = -1
    row.focus({ preventScroll: true })
  }
}

function move(step) {
  const all = rows()
  if (!all.length) return
  const index = all.indexOf(current())
  if (index === -1) select(step > 0 ? all[0] : all.at(-1))
  else select(all[Math.min(all.length - 1, Math.max(0, index + step))])
}

const pageActions = () => (data ? data.actions : [])
const byShortcut = (shortcut) =>
  pageActions().find((action) => action.shortcut === shortcut)

function showHelp() {
  const dialog = document.getElementById("wb-shortcuts")
  const list = dialog?.querySelector("[data-shortcuts-page]")
  if (!list) return
  list.replaceChildren()
  const add = (keys, label) => {
    const term = document.createElement("dt")
    for (const [index, key] of keys.split(" ").entries()) {
      if (index) term.append(" ")
      const kbd = document.createElement("kbd")
      kbd.textContent = key
      term.append(kbd)
    }
    const description = document.createElement("dd")
    description.textContent = label
    list.append(term, description)
  }
  for (const action of data.actions)
    if (action.group === "page" && action.shortcut)
      add(action.shortcut, action.label)
  if (!list.children.length) {
    const none = document.createElement("dd")
    none.textContent = data.texts.no_page_shortcuts
    list.append(none)
  }
  dialog.showModal()
}

let waiting = null
let timer = null
const stopWaiting = () => {
  waiting = null
  clearTimeout(timer)
}

if (data) {
  // A link opening the help ("Keyboard shortcuts" on Home); the hint next to
  // it is what shows without JavaScript
  for (const link of document.querySelectorAll("[data-shortcuts-open]")) {
    link.hidden = false
    for (const hint of document.querySelectorAll("[data-shortcuts-hint]"))
      hint.hidden = true
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("[data-shortcuts-open]")
    if (!link || event.button !== 0) return
    event.preventDefault()
    showHelp()
  })
  document.addEventListener("keydown", (event) => {
    if (!data.shortcuts || event.defaultPrevented) return
    if (event.ctrlKey || event.altKey || event.metaKey || event.isComposing)
      return
    if (typing(event.target) || document.querySelector("dialog[open]")) return
    const key = event.key

    if (waiting) {
      const action = byShortcut(`${waiting} ${key}`)
      stopWaiting()
      if (action) {
        event.preventDefault()
        runAction(action)
      }
      return
    }

    // Enter opens the current row, unless it's a button or link's own
    // Enter (focus on the row or its link)
    if (key === "Enter") {
      const row = current()
      const link = row && linkOf(row)
      const focused = document.activeElement
      if (link && (focused === document.body || focused === row)) {
        event.preventDefault()
        link.click()
      }
      return
    }

    switch (key) {
      case "j":
        move(1)
        break
      case "k":
        move(-1)
        break
      case "o": {
        const link = current() && linkOf(current())
        if (!link) return
        link.click()
        break
      }
      case "x": {
        const form = current()?.querySelector("[data-kb-complete]")
        if (form) form.requestSubmit()
        else if (byShortcut("x")) runAction(byShortcut("x"))
        else return
        break
      }
      case "Escape": {
        if (!current()) return
        select(null)
        break
      }
      case "?":
        showHelp()
        break
      case "/":
        openPalette()
        break
      case "g":
        waiting = "g"
        timer = setTimeout(stopWaiting, SEQUENCE_WAIT)
        break
      default: {
        const action = key.length === 1 && byShortcut(key)
        if (!action) return
        runAction(action)
      }
    }
    event.preventDefault()
  })
}
