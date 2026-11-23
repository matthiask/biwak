// A field belonging to one choice of a radio group (data-shown-for="name=value"
// on the field's wrapper, a form field's `shown_for` in forms/field.html):
// shown only while that choice is checked, e.g. "Due date…" for several
// to-dos (specs/handover.md). Without JavaScript every field stays visible
// and the server ignores the ones not belonging to the choice. Delegated,
// so forms htmx brings in (modals) work too.

const SELECTOR = "[data-shown-for]"

function sync(form) {
  for (const wrapper of form.querySelectorAll(SELECTOR)) {
    const [name, value] = wrapper.dataset.shownFor.split("=")
    const choice = form.elements[name]
    if (!choice) continue
    wrapper.hidden = choice.value !== value
  }
}

function syncAll(root) {
  const forms = new Set()
  for (const wrapper of root.querySelectorAll?.(SELECTOR) ?? []) {
    const form = wrapper.closest("form")
    if (form) forms.add(form)
  }
  for (const form of forms) sync(form)
}

document.addEventListener("change", (event) => {
  const form = event.target.form
  if (event.target.type === "radio" && form?.querySelector(SELECTOR)) sync(form)
})
// After a reset the radios have their old values only once it's done
document.addEventListener("reset", (event) => {
  if (event.target.querySelector?.(SELECTOR))
    setTimeout(() => sync(event.target))
})

syncAll(document)
document.addEventListener("htmx:after:process", (event) =>
  syncAll(event.target),
)
