// Ctrl+Enter (Cmd+Enter on a Mac) submits the form the focus is in, every
// form (specs/keyboard.md, decided 2026-11-22): comments, modals, edit forms,
// new messages and docs. One handler for all, on the document, so a form's
// own handling comes first: the inline add-to-do form submits itself and
// the people picker's and the mention list's Enter pick, both prevent the
// default, and then nothing happens here. Like pressing the form's default
// button (the first submit button), through requestSubmit(), so htmx and the
// form's checks run as with a click. Held down or pressed twice quickly it
// submits once.

const AGAIN = 1000
const submitted = new WeakMap()

function defaultButton(form) {
  return [...form.elements].find(
    (element) =>
      (element instanceof HTMLButtonElement && element.type === "submit") ||
      (element instanceof HTMLInputElement && element.type === "submit"),
  )
}

document.addEventListener("keydown", (event) => {
  if (
    event.key !== "Enter" ||
    !(event.ctrlKey || event.metaKey) ||
    event.altKey ||
    event.shiftKey ||
    event.isComposing ||
    event.defaultPrevented
  )
    return
  const form = event.target.form || event.target.closest?.("form")
  if (!(form instanceof HTMLFormElement)) return
  event.preventDefault()
  if (event.repeat) return
  const last = submitted.get(form)
  if (last !== undefined && event.timeStamp - last < AGAIN) return
  const button = defaultButton(form)
  if (button?.disabled) return
  submitted.set(form, event.timeStamp)
  form.requestSubmit(button)
})
