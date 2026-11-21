// An open edit form announces itself (specs/editor.md, "Ticking while
// someone edits"): nobody ticks the item's text while it's open. The form
// has [data-editing] with the URL. Pages whose server already announced
// the form (an edit page) renew every minute; a form that's always on the
// page (the to-do's) starts at the first focus ([data-editing-lazy]) and
// ends when the page is left. [data-editing-release] (Cancel) gives up.
import { csrfToken } from "./http.js"

const RENEW_EVERY = 60 * 1000

function announce(url, release = false) {
  const data = new FormData()
  data.append("csrfmiddlewaretoken", csrfToken())
  if (release) data.append("release", "1")
  // Survives leaving the page
  navigator.sendBeacon(url, data)
}

for (const form of document.querySelectorAll("[data-editing]")) {
  const url = form.dataset.editing
  let timer = null
  const begin = () => {
    if (timer) return
    announce(url)
    timer = setInterval(() => announce(url), RENEW_EVERY)
  }
  if ("editingLazy" in form.dataset) {
    form.addEventListener("focusin", begin)
    form.addEventListener("input", begin)
    addEventListener("pagehide", () => timer && announce(url, true))
  } else {
    timer = setInterval(() => announce(url), RENEW_EVERY)
  }
  for (const cancel of form.querySelectorAll("[data-editing-release]"))
    cancel.addEventListener("click", () => announce(url, true))
}
