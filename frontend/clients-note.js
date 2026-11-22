// A note shown while the option chosen is one clients see
// (<select data-clients-note="#id">, options with data-client): filing a
// forwarded mail as a to-do in a list clients see (specs/forwarding.md)

document.addEventListener("change", (event) => {
  const select = event.target
  if (!(select instanceof HTMLSelectElement) || !select.dataset.clientsNote)
    return
  const note = document.querySelector(select.dataset.clientsNote)
  if (note) note.hidden = !select.selectedOptions[0]?.dataset.client
})
