// Adding to-dos from text (specs/todos-from-text.md).
//
// Dropping text files onto a list's page ([data-drop-text-page]) or onto a
// list on the project's page ([data-drop-text]) reads them here, in the
// browser (nothing is uploaded), joins them in order with a blank line
// between and opens "Add from text…" with their text. Other files are
// refused with the message of [data-drop-text-error], as are files over
// the limit.
//
// In the modal ([data-from-text], items/from_text_form.html): a chosen
// file (or one dropped onto the form) is read into the text field; the
// preview comes from the server as the text or the list changes, and the
// button says what it adds, disabled while there's nothing to add.
import { send } from "./http.js"
import { openModal } from "./modal.js"

const TEXT_EXTENSIONS = [".md", ".markdown", ".txt"]
const DROPPING = "is-drop-target"
const WAIT = 300

const hasFiles = (event) => event.dataTransfer?.types.includes("Files")
const isText = (file) =>
  TEXT_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext)) ||
  file.type.startsWith("text/")

// The messages and the limit: the drop's page, or the modal's form
function settings(el) {
  const source =
    el?.closest?.("[data-from-text]") ||
    document.querySelector("[data-drop-text-error]")
  return {
    onlyText: source?.dataset.onlyText || "Only text files can be added.",
    tooBig: source?.dataset.tooBig || "This file is too large.",
    max: Number(source?.dataset.maxBytes || 204800),
  }
}

// The text of the files in order, or an error message
async function read(files, el) {
  const { onlyText, tooBig, max } = settings(el)
  if (!files.every(isText)) throw new Error(onlyText)
  if (files.some((file) => file.size > max)) throw new Error(tooBig)
  const texts = await Promise.all(files.map((file) => file.text()))
  return texts
    .map((text) => text.replace(/^﻿/, "").replace(/\s+$/, ""))
    .filter(Boolean)
    .join("\n\n")
}

function showError(message) {
  const error = document.querySelector("[data-drop-text-error]")
  if (!error) return
  error.textContent = message
  error.hidden = !message
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

// Where a drop of files goes: a list on the project's page, else the
// list's page; not into dialogs and text fields (they attach files)
function zoneOf(event) {
  const target = event.target
  if (
    target.closest?.("dialog, textarea, [contenteditable], [data-attachments]")
  )
    return null
  return (
    target.closest?.("[data-drop-text]") ||
    document.querySelector("[data-drop-text-page]")
  )
}

const urlOf = (zone) => zone.dataset.dropText || zone.dataset.dropTextPage

function stopDropping() {
  for (const el of document.querySelectorAll(`.${DROPPING}[data-drop-text]`))
    el.classList.remove(DROPPING)
}

document.addEventListener("dragover", (event) => {
  if (event.defaultPrevented || !hasFiles(event)) return
  const zone = zoneOf(event)
  if (!zone) return
  event.preventDefault()
  event.dataTransfer.dropEffect = "copy"
  for (const el of document.querySelectorAll(`.${DROPPING}[data-drop-text]`))
    if (el !== zone) el.classList.remove(DROPPING)
  if (zone.matches("[data-drop-text]")) zone.classList.add(DROPPING)
})

document.addEventListener("dragleave", (event) => {
  if (hasFiles(event) && !event.relatedTarget) stopDropping()
})

document.addEventListener("drop", async (event) => {
  if (event.defaultPrevented || !hasFiles(event)) return
  const zone = zoneOf(event)
  if (!zone) return
  event.preventDefault()
  stopDropping()
  const files = [...event.dataTransfer.files]
  if (!files.length) return
  let text
  try {
    text = await read(files, zone)
  } catch (exc) {
    showError(exc.message)
    return
  }
  showError("")
  openModal(urlOf(zone), document.activeElement)
  const field = await waitFor("#modal [data-from-text-field]")
  if (!field) return
  field.value = text
  field.dispatchEvent(new Event("input", { bubbles: true }))
})

// The modal

const timers = new WeakMap()
const latest = new WeakMap()

function button(root) {
  return root.closest("form")?.querySelector("button[type=submit]")
}

// The button as the preview says
function sync(root) {
  const plan = root.querySelector("[data-from-text-plan]")
  const submit = button(root)
  if (!plan || !submit) return
  submit.textContent = plan.dataset.label
  submit.disabled = plan.dataset.ready !== "true"
}

async function preview(root) {
  const form = root.closest("form")
  const data = [...new FormData(form)].filter(
    ([, value]) => !(value instanceof File),
  )
  const number = (latest.get(root) || 0) + 1
  latest.set(root, number)
  let response
  try {
    response = await send(root.dataset.fromText, data)
  } catch {
    return
  }
  if (!response.ok || latest.get(root) !== number) return
  const html = await response.text()
  if (latest.get(root) !== number) return
  root.querySelector("[data-from-text-preview]").innerHTML = html
  sync(root)
}

function schedule(root) {
  clearTimeout(timers.get(root))
  timers.set(
    root,
    setTimeout(() => preview(root), WAIT),
  )
}

// Files chosen or dropped onto the form: their text into the field, after
// what's there
async function addFiles(root, files) {
  const field = root.querySelector("[data-from-text-field]")
  const error = root.querySelector("[data-from-text-error]")
  try {
    const text = await read(files, root)
    field.value = [field.value.replace(/\s+$/, ""), text]
      .filter(Boolean)
      .join("\n\n")
    error.hidden = true
    field.dispatchEvent(new Event("input", { bubbles: true }))
  } catch (exc) {
    error.textContent = exc.message
    error.hidden = false
  }
}

function setUp(root) {
  if (root.dataset.fromTextReady) return
  root.dataset.fromTextReady = "true"
  const error = document.createElement("div")
  error.className = "small text-danger mb-2"
  error.setAttribute("role", "alert")
  error.dataset.fromTextError = ""
  error.hidden = true
  root.querySelector("[data-from-text-preview]").before(error)
  sync(root)
  root.addEventListener("input", (event) => {
    if (event.target.matches("[data-from-text-field]")) schedule(root)
  })
  root.addEventListener("change", (event) => {
    const input = event.target
    if (input.matches("[data-from-text-file]")) {
      const files = [...input.files]
      // Read here: the file isn't posted
      input.value = ""
      if (files.length) addFiles(root, files)
    } else if (input.matches("select")) {
      schedule(root)
    }
  })
  root.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "copy"
  })
  root.addEventListener("drop", (event) => {
    if (!event.dataTransfer?.files.length) return
    event.preventDefault()
    addFiles(root, [...event.dataTransfer.files])
  })
}

function setUpAll(target) {
  if (target.matches?.("[data-from-text]")) setUp(target)
  for (const root of target.querySelectorAll?.("[data-from-text]") ?? [])
    setUp(root)
}

setUpAll(document)
document.addEventListener("htmx:after:process", (event) =>
  setUpAll(event.target),
)
