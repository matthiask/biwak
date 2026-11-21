// Inviting several people at once (specs/activation.md, "Inviting",
// projects/invite.html): "Add another" adds a row to the formset from its
// <template>, numbered after the others, and focuses its address. Without
// JavaScript the button stays hidden and the form has a few empty rows.

function show(root) {
  for (const button of root.querySelectorAll?.("[data-invite-add]") ?? [])
    button.hidden = false
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-invite-add]")
  if (!button) return
  const fieldset = button.closest("[data-invite-rows]")
  const form = fieldset.closest("form")
  const total = form.querySelector("[name$=-TOTAL_FORMS]")
  const max = form.querySelector("[name$=-MAX_NUM_FORMS]")
  const index = Number.parseInt(total.value, 10) || 0
  if (max && index >= Number.parseInt(max.value, 10)) return
  const template = fieldset.querySelector("template[data-invite-template]")
  const holder = document.createElement("template")
  holder.innerHTML = template.innerHTML.replaceAll("__prefix__", index)
  const row = holder.content.firstElementChild
  const rows = fieldset.querySelectorAll("[data-invite-row]")
  ;(rows[rows.length - 1] || template).after(row)
  total.value = index + 1
  row.querySelector("input")?.focus()
})

show(document)
// The form in a modal
document.addEventListener("htmx:after:process", (event) => show(event.target))
