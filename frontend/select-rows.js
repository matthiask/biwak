// Selecting to-dos on the to-dos page and a list's page (list and board),
// like a folder's tiles (files.js; specs/handover.md): Ctrl-click (Cmd on a
// Mac) adds a row or takes it out, Shift-click selects from the last one
// clicked; x on the current row and Shift with the arrow keys come from
// shortcuts.js (toggleRow(), extendSelection()). A plain click opens the
// to-do as always. The bar ([data-row-selection-bar]) acts on the selection;
// Escape and "Deselect" clear it.
//
// On a list's page clicking grips selects for dragging several to-dos
// (todos.js, SortableJS's MultiDrag) with the same class, so those count
// here too; taking a row out here takes it out there (``hooks``). Rows
// selected here aren't dragged together: SortableJS's selection is one
// group's, this one goes across groups and lists.

import { openModal } from "./modal.js"
import { data } from "./palette.js"

const SELECTED = "is-selected"

const bar = document.querySelector("[data-row-selection-bar]")
let anchor = null

// Set by todos.js: tell SortableJS about rows taken out here
export const hooks = { deselect: null }

const rows = () =>
  [...document.querySelectorAll("[data-select-row]")].filter(
    (row) => row.getClientRects().length,
  )
const selection = () => [
  ...document.querySelectorAll(`[data-select-row].${SELECTED}`),
]
const isMac = /Mac|iPhone|iPad/.test(navigator.platform)
const toggleKey = (event) => (isMac ? event.metaKey : event.ctrlKey)

export function selectable(row) {
  return Boolean(bar && row?.matches("[data-select-row]"))
}

export function update() {
  if (!bar) return
  const count = selection().length
  bar.hidden = count === 0
  const label = bar.querySelector("[data-selection-count]")
  label.textContent =
    count === 1
      ? label.dataset.one
      : label.dataset.many.replace("%(count)s", String(count))
}

function set(row, on) {
  if (row.classList.contains(SELECTED) === on) return
  if (!on && hooks.deselect) hooks.deselect(row)
  row.classList.toggle(SELECTED, on)
}

// Selects or deselects the row; false when it isn't a row to select
export function toggleRow(row) {
  if (!selectable(row)) return false
  set(row, !row.classList.contains(SELECTED))
  anchor = row
  update()
  return true
}

function selectRange(row) {
  const all = rows()
  const from = all.indexOf(anchor)
  const to = all.indexOf(row)
  if (from === -1 || to === -1) return toggleRow(row)
  const [start, end] = from < to ? [from, to] : [to, from]
  for (const [index, other] of all.entries())
    set(other, index >= start && index <= end)
  update()
  return true
}

// Shift with an arrow key: the next row (step 1) or the previous one (-1)
// joins the selection from the anchor (the current row at first); returns
// the row to make current, or null
export function extendSelection(row, step) {
  if (!selectable(row)) return null
  const all = rows()
  const next = all[all.indexOf(row) + step]
  if (!next) return null
  if (!anchor || !all.includes(anchor)) {
    anchor = row
  }
  selectRange(next)
  return next
}

export function clear() {
  for (const row of selection()) set(row, false)
  anchor = null
  update()
}

if (bar) {
  document.addEventListener("click", (event) => {
    const row = event.target.closest?.("[data-select-row]")
    if (!row || event.button !== 0) return
    // The check, the grip and the peek keep their own clicks
    if (event.target.closest("form, button, [data-handle], .wb-peek")) return
    if (toggleKey(event)) {
      event.preventDefault()
      toggleRow(row)
    } else if (event.shiftKey) {
      event.preventDefault()
      selectRange(row)
    }
  })

  // With the shortcuts off, x and Shift+↑/↓ still select with the focus in
  // a row (its link), like a focused tile's x (files.js; decided
  // 2026-11-22): keys acting on the focused element only. With them on,
  // shortcuts.js does it for the current row (the focus follows it)
  document.addEventListener("keydown", (event) => {
    if (data?.shortcuts) return
    const row = event.target.closest?.("[data-select-row]")
    if (!row || event.ctrlKey || event.altKey || event.metaKey) return
    if (event.target.closest("input, textarea, select, [contenteditable]"))
      return
    if (event.key === "x" && !event.shiftKey) {
      if (!toggleRow(row)) return
      event.preventDefault()
    } else if (
      event.shiftKey &&
      (event.key === "ArrowDown" || event.key === "ArrowUp")
    ) {
      const next = extendSelection(row, event.key === "ArrowDown" ? 1 : -1)
      if (!next) return
      event.preventDefault()
      next.querySelector("a[href]")?.focus()
    }
  })

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !selection().length) return
    if (document.querySelector("dialog[open]")) return
    clear()
  })

  bar.addEventListener("click", (event) => {
    if (event.target.closest("[data-selection-clear]")) {
      clear()
      return
    }
    const link = event.target.closest("[data-selection-action]")
    if (!link) return
    event.preventDefault()
    const url = new URL(link.href, window.location.href)
    for (const row of selection())
      url.searchParams.append("items", row.dataset.selectRow)
    url.searchParams.set(
      "next",
      window.location.pathname + window.location.search,
    )
    const target = url.pathname + url.search
    if (event.ctrlKey || event.metaKey || event.shiftKey) window.open(target)
    else openModal(target, link)
  })

  // Rows a live update replaced aren't selected anymore
  document.addEventListener("biwak:live", update)
  update()
}
