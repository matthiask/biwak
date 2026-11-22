// A choice saving itself (specs/organizations.md, the notification choice
// on a project's people page, decided 2026-11-22): a <form
// data-save-on-change> posts when its select changes. While it saves, the
// select is disabled; saved, it's enabled with the new value; when the save
// fails (offline, a network error, an answer other than 2xx) it shakes, goes
// back to the stored value and is enabled again. The focus stays on it.
// Without JavaScript the form's Save button posts it.
import { send } from "./http.js"

const SHAKE = 400

function shake(element) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return
  element.classList.remove("wb-shake")
  // Restarts the animation when it fails twice in a row
  void element.offsetWidth
  element.classList.add("wb-shake")
  setTimeout(() => element.classList.remove("wb-shake"), SHAKE)
}

document.addEventListener("change", (event) => {
  const select = event.target
  if (!(select instanceof HTMLSelectElement)) return
  const form = select.closest("form[data-save-on-change]")
  if (!form) return
  const data = [...new FormData(form)]
  const focused = document.activeElement === select
  select.disabled = true
  const done = (saved) => {
    for (const option of select.options) {
      if (saved) option.defaultSelected = option.selected
      else option.selected = option.defaultSelected
    }
    select.disabled = false
    if (focused) select.focus()
    if (!saved) shake(select)
  }
  send(form.action, data).then(
    (response) => done(response.ok),
    () => done(false),
  )
})
