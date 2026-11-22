// Click to edit (specs/ui.md, "Click to edit"): an item's page shows the
// item to read. Clicking what says [data-edit-focus] (the title, the text, a
// field) inside an element with [data-edit-url] fetches the item's edit
// page and swaps the form in place of the view's region
// ([data-edit-region], default "live-text"), focused on what was clicked.
// The form saves and cancels through htmx (its own hx-* attributes) and the
// view comes back. Escape cancels a form nobody changed, a changed one needs
// it twice. Without JavaScript "Edit" is a link to the form's own page.
//
// When the form goes (Save, Cancel, Escape), the focus goes back to what
// opened it, else the page's "Edit" button ([data-edit-open]), instead of
// being lost on the page.
//
// Never when the click is on a link, a button, a box of the checklist (they
// do their own thing) or ends a text selection.
//
// A double click opens the form with its first click; its second one must
// not land on whatever moved under the pointer (the page's "Complete" where
// the title was): for a moment after opening, the further clicks of a
// double click on buttons, links and boxes do nothing (decided 2026-11-22). The title keeps its place while
// hidden (main.css), so nothing moves there in the first place.
import htmx from "htmx.org"

const INTERACTIVE =
  "a, button, input, textarea, select, label, summary, details"
const ESCAPE_AGAIN = 1500
// How long after opening clicks on actions are ignored
const SETTLE = 400
const ACTIONS =
  "a, button, summary, label, input[type=checkbox], input[type=radio], input[type=submit]"

let settlingUntil = Number.NEGATIVE_INFINITY

function settle() {
  settlingUntil = performance.now() + SETTLE
}

// Before everything else: the click never reaches the action
document.addEventListener(
  "click",
  (event) => {
    // Only the further clicks of a double (or triple) click: a single
    // click right after opening is meant
    if (event.detail < 2 || event.timeStamp > settlingUntil) return
    if (!event.target.closest?.(ACTIONS)) return
    event.preventDefault()
    event.stopImmediatePropagation()
  },
  true,
)

function focusField(region, name) {
  const field = region?.querySelector(`[name="${name}"]`)
  if (!field) return
  const target = field.dataset.pickerInput
    ? document.getElementById(field.dataset.pickerInput)
    : field
  target?.focus()
  if (
    target?.setSelectionRange &&
    target.matches("input[type=text], textarea")
  ) {
    const end = target.value.length
    target.setSelectionRange(end, end)
  }
}

// What to focus when the form goes
let opener = null
let formShown = false
let returningUntil = Number.NEGATIVE_INFINITY

function returnFocus() {
  const active = document.activeElement
  if (active && active !== document.body) return
  const target = [opener, document.querySelector("[data-edit-open]")].find(
    (el) => el?.isConnected && el.checkVisibility(),
  )
  target?.focus()
}

export async function openEdit(source) {
  const hit = source.closest("[data-edit-focus]")
  const owner = hit?.closest("[data-edit-url]")
  if (!hit || !owner) return
  const active = document.activeElement
  // Opening again while open keeps the first one's
  if (!active?.closest("[data-view-edit-form]"))
    opener = active && active !== document.body ? active : null
  const regionId = owner.dataset.editRegion || "live-text"
  const region = document.getElementById(regionId)
  // Open already
  if (!region || region.hasAttribute("data-view-form")) {
    focusField(region, hit.dataset.editFocus)
    return
  }
  try {
    await htmx.ajax("GET", owner.dataset.editUrl, {
      target: `#${regionId}`,
      swap: "outerHTML",
      select: `#${regionId}`,
    })
  } catch {
    // Not possible here: the link's page
    window.location.assign(owner.dataset.editUrl)
    return
  }
  focusField(document.getElementById(regionId), hit.dataset.editFocus)
}

document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0) return
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  const hit = event.target.closest("[data-edit-focus]")
  if (!hit) return
  // A link, button or box inside the text does its own thing (the "Edit"
  // link is the hit itself: its click edits)
  const inner = event.target.closest(INTERACTIVE)
  if (inner && inner !== hit) return
  if (window.getSelection().toString()) return
  event.preventDefault()
  settle()
  openEdit(hit)
})

// A double click on the view doesn't select a word either
document.addEventListener("dblclick", (event) => {
  if (event.target.closest?.("[data-edit-focus]")) {
    event.preventDefault()
    window.getSelection().removeAllRanges()
  }
})

// Escape in a form shown in place
let lastEscape = Number.NEGATIVE_INFINITY
const serialized = new WeakMap()

document.addEventListener("htmx:after:process", (event) => {
  const forms = [
    ...(event.target.matches?.("[data-view-edit-form]") ? [event.target] : []),
    ...(event.target.querySelectorAll?.("[data-view-edit-form]") ?? []),
  ]
  for (const form of forms)
    serialized.set(form, new URLSearchParams(new FormData(form)).toString())
  if (forms.length && !formShown) settle()
  if (forms.length) formShown = true
  else if (formShown && !document.querySelector("[data-view-edit-form]")) {
    formShown = false
    returningUntil = event.timeStamp + 1000
    returnFocus()
  } else if (event.timeStamp < returningUntil) {
    // The header swapped after the text (Save): its new "Edit"
    returnFocus()
  }
})

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || event.defaultPrevented) return
  const form = event.target.closest?.("[data-view-edit-form]")
  if (!form || document.querySelector("dialog[open]")) return
  const changed =
    new URLSearchParams(new FormData(form)).toString() !== serialized.get(form)
  const repeated = event.timeStamp - lastEscape < ESCAPE_AGAIN
  lastEscape = event.timeStamp
  if (changed && !repeated) return
  event.preventDefault()
  form.querySelector("[data-editing-release]")?.click()
})
