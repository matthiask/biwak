// Who will be told of a new message or upload at the top level follows
// "Visible to clients" (specs/notifications.md, decided 2026-11-22): the
// line of the state ticked (both rendered, ``files.common.NotifyForm``)
// and the clients in "Also tell…" (<select data-clients-follow="#id">,
// options with data-client) offered only while it's ticked; unticking
// takes the clients picked away.

document.addEventListener("change", (event) => {
  const checkbox = event.target
  if (!(checkbox instanceof HTMLInputElement) || !checkbox.id) return
  const form = checkbox.form
  if (!form) return
  for (const select of form.querySelectorAll(
    `select[data-clients-follow="#${CSS.escape(checkbox.id)}"]`,
  )) {
    const visible = checkbox.checked
    const field = select.closest(".mb-3")
    for (const line of field?.querySelectorAll("[data-told]") ?? [])
      line.hidden = line.dataset.told !== (visible ? "visible" : "internal")
    for (const option of select.querySelectorAll("option[data-client]")) {
      option.disabled = !visible
      if (!visible) option.selected = false
    }
    select.dispatchEvent(new Event("picker:refresh"))
  }
})
