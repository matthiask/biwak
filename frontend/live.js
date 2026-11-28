// Live updates (specs/lantern.md): one websocket per tab (/ws/live/,
// biwak/live/consumers.py). The server only says that something changed,
// with IDs; the page then fetches itself through its normal view (with its
// permission checks) and takes over the regions that changed:
//
// - [data-live] with an id: replaced when its HTML differs from what the
//   server rendered before and from what it shows (what scripts add to
//   forms isn't a change, frontend/live-rendered.js), unless it's
//   being edited (focus in a field, a changed field, an open <details>):
//   then it waits, with a note, until the form is saved or closed;
// - [data-live-list] with an id: its children (each with an id) are added,
//   removed, reordered and updated one by one.
//
// What's new is marked with .wb-live-new (a short highlight), except on a
// page restored from the back/forward cache. Several
// changes within a moment are fetched once; after reconnecting the page is
// fetched once, so nothing is missed. The lantern's count is
// frontend/lantern.js's (the "biwak:lantern" event).

import { report } from "./connection.js"
import { normalized, remember, unchanged } from "./live-rendered.js"

const body = document.body
const path = body.dataset.liveSocket
const watched = body.dataset.liveItem
// biwak/live/consumers.py
const CLOSE_NO_LOGIN = 4401
const CLOSE_NOT_FOUND = 4404
// Changes arriving within this time are fetched once (ms)
const GATHER = 300
// A ping this often, and a socket without a pong this long after it is
// dead (ms): nothing else is sent while the page is quiet, and a connection
// that died without a close (sleep, another network) isn't noticed
// otherwise
const PING_EVERY = 30000
const PONG_WAIT = 10000
const FIELDS = "input, textarea, select, [contenteditable]"

const texts = {
  changed: body.dataset.liveChanged || "Changed meanwhile.",
  gone:
    body.dataset.liveGone ||
    "This isn’t here anymore: it was trashed, or you can’t see it anymore.",
  back: body.dataset.liveBack || "Back",
}

let socket = null
let connectedBefore = false
let retry = 1000
let timer = null
let reconnect = null
let pinger = null
let pongTimer = null
let fetching = false
let again = false
// Back in the history: the page takes over what changed without marking it
let quiet = false
// Regions waiting while they're edited: id → the new element
const waiting = new Map()

function state(value) {
  body.dataset.liveState = value
  // Connecting keeps what was reported: a socket that never gets through
  // goes on retrying, and that's no short blip
  if (value !== "connecting") report("live", value !== "offline")
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const query = watched ? `?item=${encodeURIComponent(watched)}` : ""
  state("connecting")
  socket = new WebSocket(`${scheme}//${location.host}${path}${query}`)
  socket.addEventListener("message", (event) => {
    let data
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }
    if (data.type === "pong") {
      clearTimeout(pongTimer)
      pongTimer = null
    } else if (data.type === "ready") {
      state("connected")
      clearInterval(pinger)
      pinger = setInterval(ping, PING_EVERY)
      retry = 1000
      // Back after being offline: whatever happened meanwhile
      if (connectedBefore && watched) schedule()
      connectedBefore = true
      document.dispatchEvent(new CustomEvent("biwak:lantern"))
    } else if (data.type === "changed" && String(data.watched) === watched) {
      schedule()
    } else if (data.type === "lantern") {
      document.dispatchEvent(new CustomEvent("biwak:lantern"))
    }
  })
  socket.addEventListener("close", (event) => {
    // A socket given up on (``dead()``) has been replaced already
    if (event.target !== socket) return
    socket = null
    stopPinging()
    if (event.code === CLOSE_NO_LOGIN) {
      state("closed")
      return
    }
    if (event.code === CLOSE_NOT_FOUND) {
      // The page says so itself (its view answers 404)
      state("closed")
      refresh()
      return
    }
    state("offline")
    reconnect = setTimeout(connect, retry)
    retry = Math.min(retry * 2, 30000)
  })
}

function ping() {
  if (socket?.readyState !== WebSocket.OPEN || pongTimer) return
  socket.send(JSON.stringify({ type: "ping" }))
  pongTimer = setTimeout(dead, PONG_WAIT)
}

function stopPinging() {
  clearInterval(pinger)
  clearTimeout(pongTimer)
  pinger = pongTimer = null
}

// No pong: the connection is gone without a close. A new socket at once;
// the old one's close (whenever the browser gets to it) is ignored
function dead() {
  const old = socket
  socket = null
  stopPinging()
  old?.close()
  state("offline")
  retry = 1000
  clearTimeout(reconnect)
  connect()
}

// The browser is back: no waiting for the next try
addEventListener("online", () => {
  if (socket) {
    ping()
    return
  }
  if (!reconnect) return
  clearTimeout(reconnect)
  retry = 1000
  connect()
})

// Back in the history, restored as it was left (the back/forward cache):
// whatever changed meanwhile is taken over quietly, as a reload would show
// it (GitHub issue #2)
addEventListener("pageshow", (event) => {
  if (!event.persisted || !path) return
  quiet = true
  schedule()
})

// Back from sleep or another tab: is the socket still there?
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") ping()
})

function schedule() {
  clearTimeout(timer)
  timer = setTimeout(refresh, GATHER)
}

async function refresh() {
  if (fetching) {
    again = true
    return
  }
  fetching = true
  try {
    const response = await fetch(location.href, {
      credentials: "same-origin",
    })
    if (!response.ok || response.redirected) {
      if ([403, 404].includes(response.status) || response.redirected) gone()
      return
    }
    const fresh = new DOMParser().parseFromString(
      await response.text(),
      "text/html",
    )
    for (const region of topRegions(fresh)) {
      const current = document.getElementById(region.id)
      if (current) update(current, region)
    }
    quiet = false
    body.dataset.liveUpdated = String(Date.now())
  } catch {
    // Offline: the reconnect fetches again
  } finally {
    fetching = false
    if (again) {
      again = false
      schedule()
    }
  }
}

function topRegions(root) {
  return [...root.querySelectorAll("[data-live], [data-live-list]")].filter(
    (el) => el.id && !el.parentElement.closest("[data-live], [data-live-list]"),
  )
}

function gone() {
  if (document.querySelector("[data-live-gone]")) return
  const note = document.createElement("div")
  note.className = "alert alert-info"
  note.setAttribute("role", "alert")
  note.dataset.liveGone = ""
  note.textContent = `${texts.gone} `
  const back = document.createElement("a")
  const crumbs = document.querySelectorAll("main nav a")
  back.href = crumbs.length ? crumbs[crumbs.length - 1].href : "/"
  back.textContent = texts.back
  note.append(back)
  document.querySelector("main").prepend(note)
  if (socket) socket.close()
}

// Comparing ---------------------------------------------------------------

function dirty(field) {
  if (field.type === "checkbox" || field.type === "radio")
    return field.checked !== field.defaultChecked
  if (field.tagName === "SELECT")
    return [...field.options].some((o) => o.selected !== o.defaultSelected)
  if (field.type === "hidden" || field.type === "submit") return false
  return "defaultValue" in field && field.value !== field.defaultValue
}

function editing(el) {
  const active = document.activeElement
  if (active && el.contains(active) && active.matches(FIELDS)) return true
  if (el.querySelector("details[open]")) return true
  // An edit form shown in place of the view (frontend/view-edit.js)
  if (el.matches("[data-view-form]") || el.querySelector("[data-view-form]"))
    return true
  // A to-do's peek opened on its row
  if (el.querySelector(".wb-peek:not(:empty)")) return true
  return [...el.querySelectorAll("input, textarea, select")].some(dirty)
}

// Updating ----------------------------------------------------------------

function adopt(fresh) {
  const node = document.importNode(fresh, true)
  return node
}

function mark(node) {
  if (quiet) return
  node.classList.remove("wb-live-new")
  // Restart the animation
  void node.offsetWidth
  node.classList.add("wb-live-new")
}

// A row that wasn't there slides in, beside the highlight (the class goes
// when it's done, a row moved later doesn't slide again)
function enter(node) {
  if (quiet) return
  node.classList.add("wb-live-enter")
  node.addEventListener("animationend", (event) => {
    if (event.target === node) node.classList.remove("wb-live-enter")
  })
}

function settle(node) {
  window.htmx?.process(node)
  document.dispatchEvent(new CustomEvent("biwak:live", { detail: node }))
}

function update(current, fresh) {
  if (current.hasAttribute("data-live-list")) {
    syncAttributes(current, fresh)
    updateChildren(current, fresh)
    return
  }
  // Completed here a moment ago, its animation (frontend/celebrate.js) ends it
  if (current.classList.contains("is-completing")) return
  if (unchanged(fresh) || normalized(current) === normalized(fresh)) return
  if (editing(current)) {
    wait(current, fresh)
    return
  }
  replace(current, fresh)
}

function replace(current, fresh) {
  waiting.delete(current.id)
  remember(fresh)
  const node = adopt(fresh)
  current.replaceWith(node)
  mark(node)
  settle(node)
}

// A group's color is an attribute of its section (specs/core.md, "Group
// colors"), a list whose children are synced one by one
function syncAttributes(current, fresh) {
  for (const name of ["hidden", "class", "data-group-color"]) {
    const value = fresh.getAttribute(name)
    if (value === null) current.removeAttribute(name)
    else if (name !== "class" || current.getAttribute(name) !== value)
      current.setAttribute(name, value)
  }
}

function updateChildren(current, fresh) {
  const wanted = [...fresh.children].filter((child) => child.id)
  const ids = new Set(wanted.map((child) => child.id))
  for (const child of [...current.children]) {
    if (
      child.id &&
      !ids.has(child.id) &&
      !editing(child) &&
      !child.classList.contains("is-completing")
    )
      child.remove()
  }
  wanted.forEach((freshChild, index) => {
    let node = document.getElementById(freshChild.id)
    if (node && node.parentElement !== current) {
      // Moved here from another list (a to-do into another group)
      if (editing(node)) return
      node.remove()
      node = null
    }
    if (node) {
      update(node, freshChild)
      node = document.getElementById(freshChild.id)
    } else {
      remember(freshChild)
      node = adopt(freshChild)
      mark(node)
      enter(node)
      current.insertBefore(node, current.children[index] || null)
      settle(node)
      return
    }
    if (current.children[index] !== node)
      current.insertBefore(node, current.children[index] || null)
  })
}

function wait(current, fresh) {
  waiting.set(current.id, fresh)
  current.dataset.liveWaiting = ""
  if (!current.querySelector("[data-live-note]")) {
    const note = document.createElement("div")
    note.className = "wb-live-note"
    note.dataset.liveNote = ""
    note.setAttribute("role", "status")
    note.textContent = texts.changed
    current.prepend(note)
  }
}

// A waiting region takes over what changed once it isn't edited anymore
function release() {
  for (const [id, fresh] of [...waiting]) {
    const current = document.getElementById(id)
    if (!current?.hasAttribute("data-live-waiting")) {
      // Gone, or swapped meanwhile (the form saved or cancelled in place by
      // htmx): what it waited for is old
      waiting.delete(id)
    } else if (!editing(current)) {
      replace(current, fresh)
    }
  }
}

// For the end-to-end tests: the socket, to close it as if offline
body.live = {
  get socket() {
    return socket
  },
}

if (path && "WebSocket" in window) {
  for (const type of ["focusout", "reset", "toggle", "change"]) {
    document.addEventListener(type, () => setTimeout(release, 0), true)
  }
  connect()
}
