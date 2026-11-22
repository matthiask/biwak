// Inviting several people at once (specs/activation.md, "Inviting",
// projects/invite.html): "Add another" adds a row to the formset from its
// <template>, numbered after the others, and focuses its address. Without
// JavaScript the button stays hidden and the form has a few empty rows.
// Leaving an address fills in the row's organization and, for admins, the
// role from its domain ("Filled in from the address", invite_address), as
// long as the inviter hasn't changed those fields in that row.

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

// The fields the inviter changed: setting a value from the script fires no
// events, so every input or change event is the inviter's
const touched = new WeakSet()
// The latest lookup per row: an older answer arriving later is ignored
const latest = new WeakMap()

document.addEventListener("input", (event) => {
  if (event.target.closest("[data-invite-row]")) touched.add(event.target)
})

document.addEventListener("change", async (event) => {
  const field = event.target
  const row = field.closest("[data-invite-row]")
  if (!row) return
  touched.add(field)
  if (!field.name.endsWith("-email")) return
  const url = new URL(
    row.closest("[data-invite-address]").dataset.inviteAddress,
    location.href,
  )
  url.searchParams.set("email", field.value)
  const lookup = {}
  latest.set(row, lookup)
  const response = await fetch(url, { headers: { Accept: "application/json" } })
  if (!response.ok || latest.get(row) !== lookup) return
  const { organization, role } = await response.json()
  if (latest.get(row) !== lookup) return
  const org = row.querySelector("[name$=-organization]")
  if (org && !touched.has(org)) org.value = organization?.name ?? ""
  const isClient = row.querySelector("[name$=-is_client]")
  if (isClient && role && !touched.has(isClient))
    isClient.value = role === "staff" ? "" : "1"
})

show(document)
// The form in a modal
document.addEventListener("htmx:after:process", (event) => show(event.target))
