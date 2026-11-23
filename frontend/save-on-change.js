// Forms saving themselves (specs/ui.md, "Saving on change"): a <form
// data-save-on-change> posts its fields when a choice changes (a select, a
// radio button, a checkbox) and when a text field (text, date, time, a
// textarea) loses the focus changed. Without JavaScript its Save button
// posts it.
//
// - A select is disabled while it saves and keeps the focus (the project's
//   people page, decided 2026-11-22); other fields stay usable, a change
//   meanwhile is saved when the first save is done.
// - A required field still empty waits: nothing is saved until it's filled,
//   unless it's the field just left (emptying a name is an error).
// - The view answers 2xx when saved, 400 with ``{"errors": {field:
//   [messages]}}`` when the form isn't valid: the messages are shown below
//   the fields, as Django shows them, until the next save.
// - Failing otherwise (offline, a network error, another answer), the field
//   shakes; a choice goes back to the stored value, a text keeps what was
//   typed and is saved again when it's left the next time.
// - Saved, a page with a ``[data-save-status]`` live region says so: for
//   screen readers there, and as a short "Saved" in the top right corner of
//   the field's group (``[data-saved-template]``), taking no space. The
//   people page has neither (no "saved" message, decided 2026-11-22).
// - ``data-save-reload``: the page reloads once saved (the language, the
//   keyboard shortcuts).
// - A <form data-upload-on-choose> (the profile photo) posts as always,
//   once a file is chosen.
import { send } from "./http.js"

const SHAKE = 400
const SHOWN = 2000
const NOT_TEXT = new Set([
  "radio",
  "checkbox",
  "file",
  "hidden",
  "submit",
  "button",
  "reset",
])

const isChoice = (el) =>
  el instanceof HTMLSelectElement ||
  (el instanceof HTMLInputElement &&
    (el.type === "radio" || el.type === "checkbox"))

const isText = (el) =>
  el instanceof HTMLTextAreaElement ||
  (el instanceof HTMLInputElement && !NOT_TEXT.has(el.type))

const formOf = (el) => el.form?.closest("form[data-save-on-change]")

// The field's group: its fieldset, its checkbox, or the label and field
const groupOf = (el) =>
  el.closest("fieldset") ||
  el.closest(".form-check.mb-3") ||
  el.closest(".mb-3") ||
  el

function shake(element) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return
  element.classList.remove("wb-shake")
  // Restarts the animation when it fails twice in a row
  void element.offsetWidth
  element.classList.add("wb-shake")
  setTimeout(() => element.classList.remove("wb-shake"), SHAKE)
}

// The values sent become the stored ones, for going back and for knowing
// whether a text changed; what changed meanwhile stays changed
function store(form, data) {
  const sent = new Map()
  for (const [name, value] of data) {
    if (!sent.has(name)) sent.set(name, [])
    sent.get(name).push(value)
  }
  for (const el of form.elements) {
    if (!el.name || !sent.has(el.name)) {
      // A checkbox not sent was sent unchecked
      if (el.type === "checkbox" && el.name) el.defaultChecked = false
      continue
    }
    const values = sent.get(el.name)
    if (el instanceof HTMLSelectElement)
      for (const option of el.options)
        option.defaultSelected = values.includes(option.value)
    else if (el.type === "radio" || el.type === "checkbox")
      el.defaultChecked = values.includes(el.value)
    else if (isText(el)) el.defaultValue = values[0]
  }
}

// A choice as stored again: the select, or all buttons of its name
function restore(control) {
  if (control instanceof HTMLSelectElement) {
    for (const option of control.options)
      option.selected = option.defaultSelected
    return
  }
  const form = control.form
  for (const el of form.elements)
    if (
      el.name === control.name &&
      (el.type === "radio" || el.type === "checkbox")
    )
      el.checked = el.defaultChecked
}

function showErrors(form, errors) {
  for (const old of form.querySelectorAll("[data-save-error]")) old.remove()
  for (const el of form.querySelectorAll("[data-save-invalid]")) {
    el.classList.remove("is-invalid")
    el.removeAttribute("aria-invalid")
    el.removeAttribute("data-save-invalid")
  }
  for (const [name, messages] of Object.entries(errors)) {
    const field = name === "__all__" ? null : form.elements.namedItem(name)
    const first = field instanceof RadioNodeList ? field[0] : field
    for (const message of messages) {
      const feedback = document.createElement("div")
      feedback.className = "invalid-feedback d-block"
      feedback.dataset.saveError = ""
      feedback.textContent = message
      if (first) groupOf(first).append(feedback)
      else form.prepend(feedback)
    }
    if (first && isText(first)) {
      first.classList.add("is-invalid")
      first.setAttribute("aria-invalid", "true")
      first.dataset.saveInvalid = ""
    }
  }
}

function announce(control) {
  const status = document.querySelector("[data-save-status]")
  if (!status) return
  // Emptied first, so that saving twice is announced twice
  status.textContent = ""
  requestAnimationFrame(() => {
    status.textContent = status.dataset.saved
  })
  const template = document.querySelector("[data-saved-template]")
  if (!template) return
  const group = groupOf(control)
  let shown = group.querySelector(":scope > .wb-saved")
  if (!shown) {
    shown = template.content.firstElementChild.cloneNode(true)
    group.classList.add("wb-saved-host")
    group.append(shown)
  }
  clearTimeout(shown.hideTimer)
  shown.classList.add("is-shown")
  shown.hideTimer = setTimeout(() => shown.classList.remove("is-shown"), SHOWN)
}

const saving = new WeakMap()

function save(form, control) {
  const state = saving.get(form) || {}
  saving.set(form, state)
  if (state.busy) {
    state.again = control
    return
  }
  for (const el of form.elements)
    if (el !== control && el.willValidate && el.validity.valueMissing) return
  const data = [...new FormData(form)]
  const select = control instanceof HTMLSelectElement ? control : null
  const focused = document.activeElement === control
  state.busy = true
  if (select) select.disabled = true
  send(form.action, data, { "X-Biwak-Fragment": "1" })
    .then(
      async (response) => {
        if (response.ok) return { saved: true }
        const json = response.headers.get("Content-Type")?.includes("json")
        if (response.status === 400 && json)
          return { errors: (await response.json()).errors }
        return {}
      },
      () => ({}),
    )
    .then(({ saved, errors }) => {
      state.busy = false
      if (select) {
        select.disabled = false
        if (focused) select.focus()
      }
      showErrors(form, errors || {})
      if (saved) {
        store(form, data)
        if (form.hasAttribute("data-save-reload")) {
          window.location.reload()
          return
        }
        announce(control)
      } else if (!errors) {
        if (isChoice(control)) {
          restore(control)
          // For what shows the choice (the appearance's preview)
          form.dispatchEvent(new CustomEvent("wb:restored"))
        }
        shake(
          select || control.closest(".form-check, .wb-chip, label") || control,
        )
      }
      const next = state.again
      state.again = null
      if (next) save(form, next)
    })
}

document.addEventListener("change", (event) => {
  const control = event.target
  if (!isChoice(control)) return
  const form = formOf(control)
  if (form) save(form, control)
})

// Enter in a text field saves it the same way, without leaving the page
document.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-save-on-change]")
  if (!form) return
  event.preventDefault()
  const control = form.contains(document.activeElement)
    ? document.activeElement
    : form.elements[0]
  save(form, control)
})

// Text fields when they're left changed; ``focusout`` bubbles, ``blur`` doesn't
document.addEventListener("focusout", (event) => {
  const control = event.target
  if (!isText(control)) return
  // Unchanged, unless it shows an error: typing the stored value again fixes it
  if (
    control.value === control.defaultValue &&
    !control.hasAttribute("data-save-invalid")
  )
    return
  const form = formOf(control)
  if (form) save(form, control)
})

// Choosing the file is the upload: posted as always, the page answers
document.addEventListener("change", (event) => {
  const input = event.target
  if (!(input instanceof HTMLInputElement) || input.type !== "file") return
  const form = input.form?.closest("form[data-upload-on-choose]")
  if (form && input.files.length) form.submit()
})
