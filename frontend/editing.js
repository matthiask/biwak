// An open edit form announces itself (specs/editor.md, "Ticking while
// someone edits"): nobody ticks the item's text while it's open. The form
// has [data-editing] with the URL. Pages whose server already announced
// the form (an edit page, the form shown in place of the view) renew every
// minute; a form that's always on the page starts at the first focus
// ([data-editing-lazy]) and ends when the page is left. [data-editing-release]
// (Cancel) gives up. Forms which htmx brings in later are watched too, and
// stop renewing when they're gone (saved or cancelled in place).
import { csrfToken } from "./http.js"

const RENEW_EVERY = 60 * 1000

function announce(url, release = false) {
  const data = new FormData()
  data.append("csrfmiddlewaretoken", csrfToken())
  if (release) data.append("release", "1")
  // Survives leaving the page
  navigator.sendBeacon(url, data)
}

function watch(form) {
  if (form.dataset.editingWatched) return
  form.dataset.editingWatched = "true"
  const url = form.dataset.editing
  let timer = null
  const stop = () => {
    clearInterval(timer)
    timer = null
  }
  const renew = () => {
    // Swapped out by saving or cancelling: the server knows
    if (!form.isConnected) return stop()
    announce(url)
  }
  const begin = () => {
    if (timer) return
    announce(url)
    timer = setInterval(renew, RENEW_EVERY)
  }
  if ("editingLazy" in form.dataset) {
    form.addEventListener("focusin", begin)
    form.addEventListener("input", begin)
    addEventListener("pagehide", () => timer && announce(url, true))
  } else {
    timer = setInterval(renew, RENEW_EVERY)
    // Leaving a form shown in place gives the item back at once
    if ("viewEditForm" in form.dataset)
      addEventListener(
        "pagehide",
        () => form.isConnected && announce(url, true),
      )
  }
  for (const cancel of form.querySelectorAll("[data-editing-release]"))
    cancel.addEventListener("click", () => {
      stop()
      announce(url, true)
    })
}

function watchAll(root) {
  if (root.matches?.("[data-editing]")) watch(root)
  for (const form of root.querySelectorAll?.("[data-editing]") ?? [])
    watch(form)
}

watchAll(document)
document.addEventListener("htmx:after:process", (event) =>
  watchAll(event.target),
)
