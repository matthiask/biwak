// Pasting into Markdown fields (`textarea[data-toolbar]`, specs/editor.md):
// rich text (HTML on the clipboard) becomes Markdown, converted by the
// server (`paste_markdown`, the importer's converter: one in Python, none
// here); a URL pasted over selected text makes a link of it; images are
// attachments (attachments.js); Ctrl+Shift+V and plain text paste as they
// are.
import { send } from "./http.js"
import { replace } from "./toolbar.js"

// HTML with something worth keeping. Plain text copied from an editor comes
// as HTML too (a div per line), which must stay as it is.
const MARKUP =
  /<(a|b|strong|i|em|h[1-6]|ul|ol|li|blockquote|pre|code|table|del|s|strike)[\s>]|font-weight:\s*(bold|[6-9]00)|font-style:\s*italic|line-through/i
const URL_ONLY = /^https?:\/\/\S+$/

async function toMarkdown(url, html) {
  const response = await send(url, { html })
  if (!response.ok) throw new Error(response.status)
  return (await response.json()).markdown
}

function attach(field, url) {
  let plain = false
  field.addEventListener("keydown", (event) => {
    plain =
      (event.ctrlKey || event.metaKey) &&
      event.shiftKey &&
      event.key.toLowerCase() === "v"
  })
  field.addEventListener("paste", async (event) => {
    const asPlain = plain
    plain = false
    const data = event.clipboardData
    // Files: attachments.js
    if (asPlain || !data || data.files?.length) return
    const { selectionStart: start, selectionEnd: end, value } = field
    const text = data.getData("text/plain").trim()
    if (start !== end && URL_ONLY.test(text)) {
      event.preventDefault()
      const label = value.slice(start, end)
      const markdown = `[${label}](${text})`
      replace(field, start, end, markdown)
      field.setSelectionRange(start + markdown.length, start + markdown.length)
      return
    }
    const html = data.getData("text/html")
    // The clipboard is gone after the first await
    const fallback = data.getData("text/plain")
    if (!html || !MARKUP.test(html)) return
    event.preventDefault()
    let markdown
    try {
      markdown = await toMarkdown(url, html)
    } catch {
      // Offline or an error: what the clipboard has as text
      markdown = fallback
    }
    if (!markdown) return
    // Where the person pasted, unless the text changed meanwhile
    if (field.value === value) replace(field, start, end, markdown)
    else replace(field, field.selectionStart, field.selectionEnd, markdown)
  })
}

function attachAll(root) {
  const url = document.querySelector("template[data-toolbar-template]")?.dataset
    .pasteUrl
  if (!url) return
  for (const field of root.querySelectorAll("textarea[data-toolbar]")) {
    if (field.dataset.pasteAttached) continue
    field.dataset.pasteAttached = "true"
    attach(field, url)
  }
}

attachAll(document)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
