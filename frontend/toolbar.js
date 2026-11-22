// The toolbar above every Markdown field (`textarea[data-toolbar]`,
// specs/editor.md), and above the live editor of docs (`attachToEditor()`),
// and the keys that go with it. The buttons come from
// `forms/_toolbar.html`. The rich editor (frontend/editor/,
// specs/rich-editor.md) has its own actions (`field.richEditor.run()`);
// these here work on the textarea's text, the Markdown source the rich
// editor's "Markdown" switch shows, changing only what they must through
// `execCommand("insertText")`, so Ctrl+Z undoes a button as it undoes
// typing. Without JavaScript the fields stay plain.

export function replace(field, start, end, text) {
  field.focus()
  field.setSelectionRange(start, end)
  if (start === end && text === "") return
  const done =
    text === ""
      ? document.execCommand("delete")
      : document.execCommand("insertText", false, text)
  if (!done) {
    // Without execCommand (no undo): the same change
    field.setRangeText(text, start, end, "end")
    field.dispatchEvent(new Event("input", { bubbles: true }))
  }
}

// Replaces a range and selects `from`..`to` of the new text
function edit(field, start, end, text, from, to = from) {
  replace(field, start, end, text)
  field.setSelectionRange(start + from, start + to)
}

// The lines the selection touches: start of the first, end of the last
function linesAround(field) {
  const { value, selectionStart, selectionEnd } = field
  const start = value.lastIndexOf("\n", selectionStart - 1) + 1
  // A selection ending right after a line break doesn't take the next line
  const last =
    selectionEnd > selectionStart && value[selectionEnd - 1] === "\n"
      ? selectionEnd - 1
      : selectionEnd
  let end = value.indexOf("\n", last)
  if (end < 0) end = value.length
  return { start, end }
}

// Inline: wraps the selection, or takes the wrapping off again. Nothing
// selected: the marks around a placeholder, selected.
function wrap(field, before, after = before, placeholder = "") {
  const { value, selectionStart: start, selectionEnd: end } = field
  const selected = value.slice(start, end)
  if (
    selected.length >= before.length + after.length &&
    selected.startsWith(before) &&
    selected.endsWith(after)
  ) {
    const inner = selected.slice(before.length, selected.length - after.length)
    return edit(field, start, end, inner, 0, inner.length)
  }
  if (
    value.slice(start - before.length, start) === before &&
    value.slice(end, end + after.length) === after
  ) {
    return edit(
      field,
      start - before.length,
      end + after.length,
      selected,
      0,
      selected.length,
    )
  }
  const text = selected || placeholder
  edit(
    field,
    start,
    end,
    before + text + after,
    before.length,
    before.length + text.length,
  )
}

function link(field) {
  const { value, selectionStart: start, selectionEnd: end } = field
  const selected = value.slice(start, end)
  if (/^https?:\/\/\S+$/.test(selected)) {
    // A URL selected: its label to write
    edit(field, start, end, `[](${selected})`, 1)
  } else if (selected) {
    const text = `[${selected}](url)`
    edit(field, start, end, text, text.length - 4, text.length - 1)
  } else {
    edit(field, start, end, "[text](url)", 1, 5)
  }
}

function code(field) {
  const { value, selectionStart: start, selectionEnd: end } = field
  if (!value.slice(start, end).includes("\n")) return wrap(field, "`")
  const text = value.slice(start, end)
  const body = text.replace(/\n$/, "")
  const lead = start > 0 && value[start - 1] !== "\n" ? "\n" : ""
  const wrapped = `${lead}\`\`\`\n${body}\n\`\`\`${text.endsWith("\n") ? "\n" : ""}`
  edit(field, start, end, wrapped, wrapped.length)
}

// Lines. Each kind knows its prefix, how to recognise it and whether it's
// one of the list kinds, which replace each other.
const LIST = /^(\s*)(?:[-*+] \[[ xX]\] |[-*+] |\d+[.)] )/
const KINDS = {
  bullets: { has: /^\s*[-*+] (?!\[[ xX]\] )/, make: () => "- ", list: true },
  numbers: { has: /^\s*\d+[.)] /, make: (i) => `${i + 1}. `, list: true },
  tasks: { has: /^\s*[-*+] \[[ xX]\] /, make: () => "- [ ] ", list: true },
  quote: { has: /^> ?/, make: () => "> " },
  heading: { has: /^#{1,6} /, make: () => "## " },
}

function lines(field, kind) {
  const { start, end } = linesAround(field)
  const { selectionStart, selectionEnd, value } = field
  const rows = value.slice(start, end).split("\n")
  const content = rows.filter((row) => row.trim())
  const all = content.length > 0 && content.every((row) => kind.has.test(row))
  let number = 0
  const changed = rows.map((row) => {
    if (!row.trim() && rows.length > 1) return row
    if (all) {
      return row.replace(kind.list ? LIST : kind.has, kind.list ? "$1" : "")
    }
    let rest = row
    let indent = ""
    if (kind.list) {
      const match = LIST.exec(row)
      indent = match?.[1] ?? /^\s*/.exec(row)[0]
      rest = row.slice(match ? match[0].length : indent.length)
    } else if (kind.has.test(row)) {
      rest = row.replace(kind.has, "")
    }
    return indent + kind.make(number++) + rest
  })
  const text = changed.join("\n")
  if (text === value.slice(start, end)) return
  if (selectionStart === selectionEnd) {
    // The caret stays in the same place of the text
    const row = rows.length ? rows[0] : ""
    const shift = changed[0].length - row.length
    edit(field, start, end, text, selectionStart - start + shift)
  } else {
    edit(field, start, end, text, 0, text.length)
  }
}

// A 2×2 table with a header row, on lines of its own
function table(field) {
  const { value, selectionEnd: end } = field
  const lead = end > 0 && value[end - 1] !== "\n" ? "\n\n" : ""
  const text = `${lead}|  |  |\n| --- | --- |\n|  |  |\n`
  edit(field, end, end, text, lead.length + 2)
}

function mention(field) {
  const { value, selectionStart: start, selectionEnd: end } = field
  const lead = start > 0 && !/[\s(]/.test(value[start - 1]) ? " " : ""
  edit(field, start, end, `${lead}@`, lead.length + 1)
}

// Tab and Shift+Tab on list lines: in or out one level
function indent(field, outwards) {
  const { start, end } = linesAround(field)
  const { value, selectionStart, selectionEnd } = field
  const rows = value.slice(start, end).split("\n")
  if (!rows.some((row) => LIST.test(row))) return false
  const changed = rows.map((row) => {
    if (!LIST.test(row)) return row
    if (!outwards) return `${/^\s*\d/.test(row) ? "   " : "  "}${row}`
    return row.replace(/^(?: {1,3}|\t)/, "")
  })
  const text = changed.join("\n")
  if (text === rows.join("\n")) return true
  const shift = changed[0].length - rows[0].length
  if (selectionStart === selectionEnd) {
    edit(field, start, end, text, Math.max(0, selectionStart - start + shift))
  } else {
    edit(field, start, end, text, 0, text.length)
  }
  return true
}

const ACTIONS = {
  bold: (field) => wrap(field, "**", "**", "bold"),
  italic: (field) => wrap(field, "_", "_", "italic"),
  link,
  code,
  mention,
  heading: (field) => lines(field, KINDS.heading),
  bullets: (field) => lines(field, KINDS.bullets),
  numbers: (field) => lines(field, KINDS.numbers),
  tasks: (field) => lines(field, KINDS.tasks),
  quote: (field) => lines(field, KINDS.quote),
  table,
}

// What the keys do, by `event.code` (Shift+7 is "&" on some layouts)
export function keyAction(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return null
  if (event.shiftKey) {
    return { Digit7: "numbers", Digit8: "bullets", Digit9: "tasks" }[event.code]
  }
  return { KeyB: "bold", KeyI: "italic", KeyK: "link" }[event.code]
}

function buttons(bar) {
  return [...bar.querySelectorAll("button")].filter((b) => !b.hidden)
}

// One tab stop for the toolbar; arrows move within it
export function roving(bar) {
  const all = buttons(bar)
  all.forEach((button, index) => {
    button.tabIndex = index === 0 ? 0 : -1
  })
}

function build(field, template) {
  const bar = document.createElement("div")
  bar.className = "wb-toolbar"
  bar.setAttribute("role", "toolbar")
  bar.setAttribute("aria-label", template.dataset.label || "Formatting")
  bar.append(template.content.cloneNode(true))
  if (!field.dataset.mentions)
    bar.querySelector('[data-toolbar-action="mention"]').hidden = true
  // The rich editor's "Markdown" switch, shown once it's there
  const source = bar.querySelector('[data-toolbar-action="source"]')
  if (source) source.hidden = true
  roving(bar)
  // Clicking a button keeps the field's focus and selection
  bar.addEventListener("mousedown", (event) => {
    if (event.target.closest("button")) event.preventDefault()
  })
  bar.addEventListener("click", (event) => {
    const button = event.target.closest("[data-toolbar-action]")
    if (!button) return
    // The rich editor (frontend/editor/) has its own actions, also while
    // its source is shown (the switch)
    const editor = field.richEditor
    if (editor && (editor.active || button.dataset.toolbarAction === "source"))
      editor.run(button.dataset.toolbarAction)
    else ACTIONS[button.dataset.toolbarAction](field)
  })
  bar.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return
    const all = buttons(bar)
    const index = all.indexOf(document.activeElement)
    if (index < 0) return
    event.preventDefault()
    const next =
      all[
        (index + (event.key === "ArrowRight" ? 1 : -1) + all.length) %
          all.length
      ]
    for (const button of all) button.tabIndex = button === next ? 0 : -1
    next.focus()
  })
  field.before(bar)
  field.toolbar = bar

  field.addEventListener("keydown", (event) => {
    if (event.isComposing) return
    const action = keyAction(event)
    if (action) {
      // Inside a field Ctrl+K is "link", not the palette
      event.preventDefault()
      event.stopPropagation()
      ACTIONS[action](field)
    } else if (
      event.key === "Tab" &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      indent(field, event.shiftKey)
    ) {
      event.preventDefault()
    } else if (event.key === "Escape" && !event.defaultPrevented) {
      // Leaves the field, so that Ctrl+K reaches the palette again
      field.blur()
    }
  })
}

// The live editor of docs (collab.js, the rich editor's ``liveEditor()``)
// gets the same toolbar above it, without the "Markdown" switch (the
// shared document is the editor's); its keys are the editor's own
export function attachToEditor(editor, element, mentions) {
  const template = document.querySelector("template[data-toolbar-template]")
  if (!template) return null
  const field = {
    richEditor: editor,
    dataset: { mentions: mentions || "" },
    addEventListener() {
      // The keys: the editor's
    },
    before(bar) {
      element.before(bar)
    },
  }
  build(field, template)
  return field
}

export function attachAll(root) {
  const template = document.querySelector("template[data-toolbar-template]")
  if (!template) return
  for (const field of root.querySelectorAll("textarea[data-toolbar]")) {
    if (field.dataset.toolbarAttached) continue
    field.dataset.toolbarAttached = "true"
    build(field, template)
  }
}

attachAll(document)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
