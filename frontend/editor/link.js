// Asking for a link's address in the rich editor (Ctrl+K, the link button)
import { linkAt, setLink } from "./commands.js"

const label = () =>
  document.querySelector("template[data-toolbar-template]")?.dataset.linkLabel

// A small field below the selection for a link's address (Ctrl+K, the
// link button): Enter sets it, an empty one removes the link, Escape or
// leaving it cancels
export function askLink(view, container) {
  container.querySelector(":scope > .wb-link-ask")?.remove()
  const ask = document.createElement("div")
  ask.className = "wb-link-ask"
  const input = document.createElement("input")
  input.type = "url"
  input.className = "form-control form-control-sm"
  input.setAttribute("aria-label", label() || "Link address")
  input.placeholder = "https://"
  const link = linkAt(view.state)
  input.value = link ? link[2].attrs.href : ""
  ask.append(input)
  container.classList.add("position-relative")
  container.append(ask)
  const box = container.getBoundingClientRect()
  const at = view.coordsAtPos(view.state.selection.from)
  ask.style.top = `${at.bottom - box.top + 4}px`
  ask.style.left = `${Math.max(0, Math.min(at.left - box.left, box.width - ask.offsetWidth))}px`
  let done = false
  const close = (href) => {
    if (done) return
    done = true
    ask.remove()
    if (href !== undefined) setLink(view, href)
    else view.focus()
  }
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault()
      event.stopPropagation()
      close(input.value.trim())
    } else if (event.key === "Escape") {
      event.preventDefault()
      event.stopPropagation()
      close()
    }
  })
  input.addEventListener("blur", () => close())
  input.focus()
  input.select()
}
