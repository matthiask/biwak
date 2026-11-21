// Ticking the checkboxes of a text in place (specs/editor.md): the wrapper
// (`checklist_markdown`) knows where to post and which version of the text
// the page showed. The server changes the text through the item's
// operation. A refusal (409) says why in a small status next to the box:
// somebody has the edit form open, or the text changed meanwhile, and then
// the text is loaded again.
import { send } from "./http.js"

function show(box, message) {
  const item = box.closest("li") || box.parentElement
  for (const old of document.querySelectorAll(".wb-tick-note")) old.remove()
  const note = document.createElement("span")
  note.className = "wb-tick-note small text-danger ms-2"
  note.setAttribute("role", "status")
  note.textContent = message
  item.append(note)
}

// Replaces the text with what the page shows now, the message next to the
// box that was ticked
async function reload(wrapper, index, message) {
  const response = await fetch(window.location.href, {
    headers: { "X-Requested-With": "fetch" },
  })
  const html = new DOMParser().parseFromString(
    await response.text(),
    "text/html",
  )
  const fresh = [...html.querySelectorAll(".wb-checklist")].find(
    (el) =>
      el.dataset.tickUrl === wrapper.dataset.tickUrl &&
      el.dataset.comment === wrapper.dataset.comment,
  )
  if (!fresh) return window.location.reload()
  wrapper.replaceWith(fresh)
  const boxes = fresh.querySelectorAll("input.task-list-item-checkbox")
  show(boxes[index] || boxes[0] || fresh, message)
}

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
    if (response.status === 409) {
      const refusal = await response.json().catch(() => ({}))
      const message = refusal.message || ""
      if (refusal.reload === false) {
        box.checked = !box.checked
        box.disabled = false
        return show(box, message)
      }
      return await reload(wrapper, Number(box.dataset.index), message)
    }
    if (!response.ok) throw new Error(response.status)
    wrapper.dataset.version = (await response.json()).version
    for (const old of document.querySelectorAll(".wb-tick-note")) old.remove()
  } catch {
    box.checked = !box.checked
  }
  box.disabled = false
})
