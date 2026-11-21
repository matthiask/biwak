// Ticking the checkboxes of a text in place (specs/editor.md): the wrapper
// (`checklist_markdown`) knows where to post and which version of the text
// the page showed. The server changes the text through the item's
// operation; a text that changed meanwhile (409) is reloaded.
import { send } from "./http.js"

document.addEventListener("change", async (event) => {
  const box = event.target
  const wrapper = box.closest?.(".wb-checklist")
  if (!wrapper || !box.matches("input.task-list-item-checkbox")) return
  box.disabled = true
  const data = {
    index: box.dataset.index,
    version: wrapper.dataset.version,
    checked: box.checked ? "1" : "0",
  }
  if (wrapper.dataset.comment) data.comment = wrapper.dataset.comment
  try {
    const response = await send(wrapper.dataset.tickUrl, data)
    if (response.status === 409) return window.location.reload()
    if (!response.ok) throw new Error(response.status)
    wrapper.dataset.version = (await response.json()).version
  } catch {
    box.checked = !box.checked
  }
  box.disabled = false
})
