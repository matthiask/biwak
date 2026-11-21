// Being offline (specs/connection.md): one banner under the navigation
// ([data-connection] in base.html) and what the scripts do meanwhile.
//
// Offline is when the browser says so (navigator.onLine, the offline event)
// or when a websocket of the page (live.js, collab.js) has been down for
// more than GRACE ms, so short reconnects don't flicker. Back is when the
// browser is online and the sockets are connected, or a request succeeds.
// The banner says "Back online." for BACK ms and goes.
//
// What the page does offline follows navigator.onLine only: a websocket
// that's blocked on the way to a working server must not keep anyone from
// saving their forms.

// How long a websocket may be down before the banner shows (ms)
const GRACE = 3000
// How long "Back online." stays (ms)
const BACK = 3000

const bar = document.querySelector("[data-connection]")
// Websocket name → connected
const sources = new Map()
let browserOffline = navigator.onLine === false
let socketsDown = false
let offline = false
let graceTimer = null
let backTimer = null

function texts() {
  const data = bar?.dataset || {}
  return {
    editor: data.connectionEditor || "",
    page: data.connectionPage || "",
    back: data.connectionBack || "",
    notSent: data.connectionNotSent || "Not sent: you’re offline.",
  }
}

function render() {
  if (!bar) return
  clearTimeout(backTimer)
  const t = texts()
  if (offline) {
    bar.textContent = document.querySelector("[data-collab]")
      ? t.editor
      : t.page
    bar.dataset.connectionState = "offline"
  } else if (bar.dataset.connectionState === "offline") {
    bar.textContent = t.back
    bar.dataset.connectionState = "back"
    backTimer = setTimeout(() => {
      bar.textContent = ""
      delete bar.dataset.connectionState
    }, BACK)
  }
}

function update() {
  const now = browserOffline || socketsDown
  if (now === offline) return
  offline = now
  render()
  document.body.dataset.wbConnection = offline ? "offline" : "online"
  document.dispatchEvent(
    new CustomEvent("biwak:connection", { detail: { offline } }),
  )
}

// A websocket of the page says whether it's connected
export function report(name, connected) {
  sources.set(name, connected)
  if ([...sources.values()].every(Boolean)) {
    clearTimeout(graceTimer)
    graceTimer = null
    socketsDown = false
    update()
  } else if (!graceTimer && !socketsDown) {
    graceTimer = setTimeout(() => {
      graceTimer = null
      socketsDown = true
      update()
    }, GRACE)
  }
}

// A request got through: we're back, whatever the sockets say
export function succeeded() {
  if (navigator.onLine === false) return
  browserOffline = false
  clearTimeout(graceTimer)
  graceTimer = null
  socketsDown = false
  update()
}

export function isOffline() {
  return navigator.onLine === false
}

addEventListener("offline", () => {
  browserOffline = true
  update()
})
addEventListener("online", () => {
  browserOffline = false
  update()
})

// Forms ---------------------------------------------------------------------

// Held back: the form keeps its text, a message says why. Nothing is queued.
function hold(form, submitter) {
  for (const old of document.querySelectorAll("[data-not-sent]")) old.remove()
  const note = document.createElement("span")
  note.className = "small text-danger ms-2"
  note.setAttribute("role", "status")
  note.dataset.notSent = ""
  note.textContent = texts().notSent
  const anchor =
    submitter || form.querySelector("button[type=submit], input[type=submit]")
  if (anchor) anchor.after(note)
  else form.append(note)
}

// Capturing and stopping, so that htmx and the scripts submitting forms
// never see it
document.addEventListener(
  "submit",
  (event) => {
    if (!isOffline()) return
    const form = event.target
    if (form.method?.toLowerCase() === "get") return
    event.preventDefault()
    event.stopImmediatePropagation()
    hold(form, event.submitter)
  },
  true,
)

document.addEventListener("biwak:connection", (event) => {
  if (!event.detail.offline)
    for (const note of document.querySelectorAll("[data-not-sent]"))
      note.remove()
})

function dirty(field) {
  if (field.type === "checkbox" || field.type === "radio")
    return field.checked !== field.defaultChecked
  if (field.tagName === "SELECT")
    return [...field.options].some((o) => o.selected !== o.defaultSelected)
  if (["hidden", "submit", "button", "file"].includes(field.type)) return false
  return "defaultValue" in field && field.value !== field.defaultValue
}

// Leaving a page with typed text while offline asks first
addEventListener("beforeunload", (event) => {
  if (!isOffline()) return
  const typed = [...document.querySelectorAll("form")].some(
    (form) =>
      form.method?.toLowerCase() !== "get" &&
      [...form.elements].some((field) => dirty(field)),
  )
  if (!typed) return
  event.preventDefault()
  event.returnValue = ""
})

// For the end-to-end tests
document.body.connection = { offline: () => offline }
