// A folder's tiles (files/_tiles.html, specs/files.md, "Moving and selecting"):
// selecting several without checkboxes, Ctrl-click (Cmd on a Mac) adding
// or removing a tile and Shift-click the range from the last one, Ctrl+Space
// and Shift+arrows on the focused tile the same; the bar acts on the
// selection, Escape and "Deselect" clear it. Tiles are dragged onto a
// folder, ".." or a breadcrumb ([data-drop-folder]); dragging a selected
// tile drags the selection. A plain click opens the tile as before.

import { send } from "./http.js"
import { openModal } from "./modal.js"
import { addFiles } from "./upload.js"

const SELECTED = "is-selected"
const TARGET = "is-drop-target"
const TYPE = "application/x-biwak-items"

const grid = document.querySelector("[data-tiles]")
const bar = document.querySelector("[data-selection-bar]")
let anchor = null
let dragged = []

const tiles = () => [...grid.querySelectorAll("[data-tile-movable]")]
const selection = () =>
  tiles().filter((tile) => tile.classList.contains(SELECTED))
const isMac = /Mac|iPhone|iPad/.test(navigator.platform)
const toggleKey = (event) => (isMac ? event.metaKey : event.ctrlKey)

function update() {
  const count = selection().length
  bar.hidden = count === 0
  const label = bar.querySelector("[data-selection-count]")
  label.textContent =
    count === 1
      ? label.dataset.one
      : label.dataset.many.replace("%(count)s", String(count))
}

function toggle(tile) {
  tile.classList.toggle(SELECTED)
  anchor = tile
  update()
}

function selectRange(tile) {
  const all = tiles()
  const from = all.indexOf(anchor)
  const to = all.indexOf(tile)
  if (from === -1) return toggle(tile)
  const [start, end] = from < to ? [from, to] : [to, from]
  for (const [index, other] of all.entries())
    other.classList.toggle(SELECTED, index >= start && index <= end)
  update()
}

function clear() {
  for (const tile of tiles()) tile.classList.remove(SELECTED)
  anchor = null
  update()
}

const ids = (list) => list.map((tile) => tile.dataset.tile)

function withItems(url, list) {
  const target = new URL(url, window.location.href)
  for (const id of ids(list)) target.searchParams.append("items", id)
  return target.pathname + target.search
}

grid.addEventListener("click", (event) => {
  const tile = event.target.closest("[data-tile]")
  if (!tile?.matches("[data-tile-movable]")) return
  if (toggleKey(event)) {
    event.preventDefault()
    toggle(tile)
  } else if (event.shiftKey) {
    event.preventDefault()
    selectRange(tile)
  }
})

grid.addEventListener("keydown", (event) => {
  const tile = event.target.closest("[data-tile-movable]")
  if (!tile) return
  if (event.key === " " && toggleKey(event)) {
    event.preventDefault()
    toggle(tile)
    return
  }
  if (!event.shiftKey || !event.key.startsWith("Arrow")) return
  // The neighbour in the grid: left and right in the row, up and down a
  // column (the tiles' positions tell)
  const all = tiles()
  const box = tile.getBoundingClientRect()
  const candidates = all.filter((other) => {
    if (other === tile) return false
    const b = other.getBoundingClientRect()
    switch (event.key) {
      case "ArrowLeft":
        return b.top === box.top && b.left < box.left
      case "ArrowRight":
        return b.top === box.top && b.left > box.left
      case "ArrowUp":
        return b.top < box.top && b.left === box.left
      default:
        return b.top > box.top && b.left === box.left
    }
  })
  const distance = (other) => {
    const b = other.getBoundingClientRect()
    return Math.abs(b.top - box.top) + Math.abs(b.left - box.left)
  }
  candidates.sort((a, b) => distance(a) - distance(b))
  const next = candidates[0]
  if (!next) return
  event.preventDefault()
  if (!anchor) anchor = tile
  selectRange(next)
  next.focus()
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
  const url = withItems(link.href, selection())
  if (event.ctrlKey || event.metaKey || event.shiftKey) window.open(url)
  else openModal(url, link)
})

// Dragging onto folders, "..", and the breadcrumbs ------------------------

const targetOf = (event) => event.target.closest?.("[data-drop-folder]")

function droppable(target) {
  if (!target || !dragged.length) return false
  const folder = target.dataset.dropFolder
  // Not onto itself, not where they are already
  if (dragged.some((tile) => tile.dataset.tile === folder)) return false
  return folder !== grid.dataset.tilesFolder
}

grid.addEventListener("dragstart", (event) => {
  const tile = event.target.closest?.("[data-tile-movable]")
  if (!tile) return
  dragged = tile.classList.contains(SELECTED) ? selection() : [tile]
  event.dataTransfer.effectAllowed = "move"
  event.dataTransfer.setData(TYPE, ids(dragged).join(","))
  for (const one of dragged) one.classList.add("is-dragged")
})

document.addEventListener("dragend", () => {
  for (const tile of dragged) tile.classList.remove("is-dragged")
  dragged = []
  for (const el of document.querySelectorAll(`.${TARGET}`))
    el.classList.remove(TARGET)
})

document.addEventListener("dragover", (event) => {
  const target = targetOf(event)
  if (!droppable(target)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = "move"
  target.classList.add(TARGET)
})

document.addEventListener("dragleave", (event) => {
  const target = targetOf(event)
  if (target && !target.contains(event.relatedTarget))
    target.classList.remove(TARGET)
})

document.addEventListener("drop", (event) => {
  const target = targetOf(event)
  if (!droppable(target)) return
  event.preventDefault()
  const data = [["folder", target.dataset.dropFolder]]
  for (const id of ids(dragged)) data.push(["items", id])
  for (const tile of dragged) tile.closest("li").hidden = true
  // The page as the server has it now: the order, the counts, and the
  // message of a refused move
  const reload = () => window.location.reload()
  send(grid.dataset.tilesMove, data).then(reload, reload)
})

// Files from the computer (part 4b): dropped anywhere into the window
// they open "Upload files" for this folder, dropped onto a folder, ".."
// or a breadcrumb for that one

const uploadUrl = grid.dataset.tilesUpload
const DROPPING = "wb-dropping-files"
const hasFiles = (event) => event.dataTransfer?.types.includes("Files")
const inDialog = (event) => event.target.closest?.("dialog")

function stopDropping() {
  document.body.classList.remove(DROPPING)
  for (const el of document.querySelectorAll(`.${TARGET}`))
    el.classList.remove(TARGET)
}

function waitFor(selector) {
  return new Promise((resolve) => {
    const started = performance.now()
    const look = () => {
      const found = document.querySelector(selector)
      if (found || performance.now() - started > 10000) resolve(found)
      else requestAnimationFrame(look)
    }
    look()
  })
}

if (uploadUrl) {
  document.addEventListener("dragover", (event) => {
    if (!hasFiles(event) || inDialog(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "copy"
    document.body.classList.add(DROPPING)
    const target = targetOf(event)
    for (const el of document.querySelectorAll(`.${TARGET}`))
      if (el !== target) el.classList.remove(TARGET)
    target?.classList.add(TARGET)
  })

  document.addEventListener("dragleave", (event) => {
    // Out of the window
    if (hasFiles(event) && !event.relatedTarget) stopDropping()
  })

  document.addEventListener("drop", (event) => {
    if (!hasFiles(event) || inDialog(event)) return
    event.preventDefault()
    stopDropping()
    const dropped = [...event.dataTransfer.files]
    if (!dropped.length) return
    const target = targetOf(event)
    const folder = target ? target.dataset.dropFolder : grid.dataset.tilesFolder
    const url = new URL(uploadUrl, window.location.href)
    if (folder) url.searchParams.set("folder", folder)
    openModal(url.pathname + url.search, document.activeElement)
    waitFor("#modal [data-upload]").then((zone) => {
      if (zone) addFiles(zone, dropped)
    })
  })
}

update()
