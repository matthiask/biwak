// A to-do's start date (specs/start-dates.md): its field shows once the due
// date is set (or when it has a date already, so a start date left without
// a due date can be seen and its error read), and can't be after the due
// date. Without this script both fields show; the server checks either way.
// Delegated, so forms htmx or live updates bring in work too.

const STARTS = "[data-starts-on]"

function sync(form) {
  const due = form.querySelector("[name=due_on]")
  const starts = form.querySelector(STARTS)
  if (!due || !starts) return
  // The field's wrapper: the label of the inline form, the field's block in
  // the to-do's edit form
  starts.parentElement.hidden = !(due.value || starts.value)
  if (due.value) starts.max = due.value
  else starts.removeAttribute("max")
}

function syncAll(root) {
  for (const starts of root.querySelectorAll?.(STARTS) ?? []) {
    const form = starts.closest("form")
    if (form) sync(form)
  }
}

for (const name of ["input", "change"]) {
  document.addEventListener(name, (event) => {
    if (event.target.matches?.(`[name=due_on], ${STARTS}`)) {
      const form = event.target.closest("form")
      if (form) sync(form)
    }
  })
}
// After a reset the fields have their old values only once it's done
document.addEventListener("reset", (event) => {
  if (event.target.querySelector?.(STARTS)) setTimeout(() => sync(event.target))
})

syncAll(document)
document.addEventListener("htmx:after:process", (event) =>
  syncAll(event.target),
)
document.addEventListener("biwak:live", (event) => syncAll(event.detail))
