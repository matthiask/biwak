// Attaching files to texts (specs/files.md): dropping or pasting files
// into a text field inside [data-attachments], or its "Attach files"
// button, uploads them to the URL in data-attachments and inserts the
// Markdown the server answers with at the cursor. Saving the text links
// the attachments to the item.

import { csrfToken } from "./http.js"

// The error message below each text field
const errors = new WeakMap()

// The rich editor (frontend/editor/) inserts into its document while the
// field is hidden behind it
const rich = (textarea) =>
  textarea.richEditor?.active ? textarea.richEditor : null

function insert(textarea, text) {
  if (rich(textarea)) return rich(textarea).insertMarkdown(text)
  const { selectionStart: start, selectionEnd: end, value } = textarea
  const before = start > 0 && !/\s$/.test(value.slice(0, start)) ? " " : ""
  textarea.setRangeText(before + text, start, end, "end")
  textarea.dispatchEvent(new Event("input", { bubbles: true }))
}

function replace(textarea, placeholder, text) {
  if (rich(textarea)) return rich(textarea).replaceText(placeholder, text)
  const index = textarea.value.indexOf(placeholder)
  if (index < 0) {
    insert(textarea, text)
    return
  }
  // "preserve" would select the new text when the caret was at the end of
  // the placeholder, so that typing replaced it; the caret follows the text
  const end = index + placeholder.length
  const shift = (position) =>
    position >= end ? position + text.length - placeholder.length : position
  const { selectionStart, selectionEnd } = textarea
  textarea.setRangeText(text, index, end, "preserve")
  textarea.setSelectionRange(shift(selectionStart), shift(selectionEnd))
  textarea.dispatchEvent(new Event("input", { bubbles: true }))
}

function showError(textarea, message) {
  const error = errors.get(textarea)
  error.textContent = message
  error.hidden = !message
}

async function upload(container, textarea, file) {
  const {
    attachments: url,
    attachmentsMax,
    attachmentsTooLarge,
  } = container.dataset
  if (attachmentsMax && file.size > Number(attachmentsMax)) {
    showError(textarea, attachmentsTooLarge)
    return
  }
  const placeholder = `[${container.dataset.attachmentsUploading || "Uploading"} ${file.name}…]`
  insert(textarea, placeholder)
  const body = new FormData()
  body.append("file", file, file.name)
  try {
    const response = await fetch(url, {
      method: "POST",
      body,
      headers: { "X-CSRFToken": csrfToken() },
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail)
    replace(textarea, placeholder, data.markdown)
    showError(textarea, "")
  } catch (exc) {
    replace(textarea, placeholder, "")
    showError(textarea, exc.message || container.dataset.attachmentsFailed)
  }
}

function uploadAll(container, textarea, files) {
  for (const file of files) upload(container, textarea, file)
}

// Files dropped or pasted into the rich editor of ``textarea``; whether it
// takes files at all
export function uploadFiles(textarea, files) {
  const container = textarea.closest("[data-attachments]")
  if (!container || !errors.has(textarea)) return false
  uploadAll(container, textarea, files)
  return true
}

function enhance(container, textarea) {
  const wrapper = document.createElement("div")
  wrapper.className = "wb-attach"
  const template = container.querySelector("template[data-attach-template]")
  if (template) {
    const button = template.content.firstElementChild.cloneNode(true)
    const input = document.createElement("input")
    input.type = "file"
    input.multiple = true
    input.hidden = true
    button.addEventListener("click", () => input.click())
    input.addEventListener("change", () => {
      uploadAll(container, textarea, input.files)
      input.value = ""
      textarea.focus()
    })
    // The toolbar above the field has the button (specs/editor.md)
    const bar = textarea.toolbar
    if (bar) {
      button.tabIndex = -1
      // Before the rich editor's "Markdown" switch, the last
      const source = bar.querySelector('[data-toolbar-action="source"]')
      bar.insertBefore(button, source)
      bar.insertBefore(input, source)
    } else {
      wrapper.append(button)
      wrapper.append(input)
    }
  }
  const error = document.createElement("div")
  error.className = "small text-danger"
  error.setAttribute("role", "alert")
  error.hidden = true
  wrapper.append(error)
  errors.set(textarea, error)
  textarea.after(wrapper)

  textarea.addEventListener("dragover", (event) => {
    if (event.dataTransfer?.types.includes("Files")) {
      event.preventDefault()
      textarea.classList.add("wb-drop-target")
    }
  })
  textarea.addEventListener("dragleave", () => {
    textarea.classList.remove("wb-drop-target")
  })
  textarea.addEventListener("drop", (event) => {
    textarea.classList.remove("wb-drop-target")
    if (!event.dataTransfer?.files.length) return
    event.preventDefault()
    textarea.focus()
    uploadAll(container, textarea, event.dataTransfer.files)
  })
  textarea.addEventListener("paste", (event) => {
    const files = event.clipboardData?.files
    if (!files?.length) return
    event.preventDefault()
    uploadAll(container, textarea, files)
  })
}

function setUpAll(root) {
  const containers = [
    ...(root.matches?.("[data-attachments]") ? [root] : []),
    ...(root.querySelectorAll?.("[data-attachments]") ?? []),
  ]
  for (const container of containers) {
    for (const textarea of container.querySelectorAll("textarea")) {
      if (textarea.dataset.attachReady) continue
      textarea.dataset.attachReady = "true"
      enhance(container, textarea)
    }
  }
}

setUpAll(document)
// Forms htmx brings in later (the edit form in place of a view)
document.addEventListener("htmx:after:process", (event) =>
  setUpAll(event.target),
)
