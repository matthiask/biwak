// Fields shown only while another field of the form has a value:
// data-shown-when="notify=chosen" on the field's group (forms/field.html,
// a form field's ``shown_when``), e.g. "These people" only with "Only these
// people" (specs/notifications.md). Without JavaScript they're always shown.

function current(form, name) {
  const fields = [...form.elements].filter((field) => field.name === name)
  const checked = fields.find(
    (field) =>
      (field.type !== "radio" && field.type !== "checkbox") || field.checked,
  )
  return checked?.value ?? ""
}

function update(form) {
  for (const group of form.querySelectorAll("[data-shown-when]")) {
    const [name, value] = group.dataset.shownWhen.split("=")
    group.hidden = current(form, name) !== value
  }
}

function attachAll(root) {
  const groups = [
    ...(root.matches?.("[data-shown-when]") ? [root] : []),
    ...(root.querySelectorAll?.("[data-shown-when]") ?? []),
  ]
  for (const form of new Set(groups.map((group) => group.closest("form"))))
    if (form) update(form)
}

document.addEventListener("change", (event) => {
  const form = event.target.form
  if (form?.querySelector("[data-shown-when]")) update(form)
})
// A reset puts the form's own choice back
document.addEventListener("reset", (event) =>
  setTimeout(() => update(event.target)),
)

attachAll(document)
// Forms htmx inserts later (modals)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
