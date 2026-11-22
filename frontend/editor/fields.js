// Every Markdown field (`textarea[data-toolbar]`) as the rich editor
// (specs/rich-editor.md, "Everywhere"), a chunk of its own loaded on pages
// with such a field (frontend/main.js). Progressive enhancement: the
// textarea stays in the form, hidden, and gets the Markdown on every
// change, so forms post as before and work without JavaScript; while the
// document is the one the field came with, the field keeps its original
// text (opening and saving changes nothing). The toolbar (toolbar.js)
// calls ``run()``; "Markdown" shows the source in the textarea, where
// mentions, pasting and attachments work as they do without the editor.
//
// ``textarea.richEditor`` is the field's editor: ``active`` (rich, not the
// source), ``view``, ``run(action)``, ``setMarkdown(text)``,
// ``insertMarkdown(text)``, ``replaceText(placeholder, markdown)``.
import { uploadFiles } from "../attachments.js"
import { roving } from "../toolbar.js"
import { ACTIONS, active } from "./commands.js"
import { createView, EditorState, plugins } from "./editor.js"
import { askLink } from "./link.js"
import { parse, serialize } from "./markdown.js"
import { markdownSlice, mentions, pasting } from "./plugins.js"
import { setAttachmentUrl } from "./schema.js"
import { tableBar } from "./tables.js"

const template = () => document.querySelector("template[data-toolbar-template]")

function upgrade(textarea) {
  setAttachmentUrl(template()?.dataset.attachmentUrl)
  let original = textarea.value
  let originalDoc = parse(original)
  const place = document.createElement("div")
  place.className = `wb-editor wb-markdown form-control${
    textarea.classList.contains("form-control-sm") ? " form-control-sm" : ""
  }`
  place.style.setProperty("--wb-editor-rows", textarea.rows || 2)
  textarea.before(place)
  const bar = textarea.toolbar
  const label =
    textarea.getAttribute("aria-label") ||
    (textarea.id &&
      document
        .querySelector(`label[for="${CSS.escape(textarea.id)}"]`)
        ?.textContent.trim()) ||
    ""

  const editor = { active: true }
  const showPressed = (state) => {
    if (!bar) return
    const pressed = editor.active ? active(state) : {}
    for (const button of bar.querySelectorAll("[data-toolbar-action]")) {
      const name = button.dataset.toolbarAction
      if (name === "source")
        button.setAttribute("aria-pressed", String(!editor.active))
      else if (name in pressed || !editor.active)
        button.setAttribute("aria-pressed", String(!!pressed[name]))
    }
  }

  const write = (doc) => {
    const value = doc.eq(originalDoc) ? original : serialize(doc)
    if (value === textarea.value) return
    textarea.value = value
    textarea.dispatchEvent(new Event("input", { bubbles: true }))
  }

  const upload = (files) => uploadFiles(textarea, files)
  const all = plugins({
    extra: [
      ...(textarea.dataset.mentions
        ? [
            mentions({
              url: textarea.dataset.mentions,
              visible: textarea.dataset.mentionsVisible,
              anchor: place,
            }),
          ]
        : []),
      pasting({ upload }),
      // (after the hidden field: the editor stays right before it)
      tableBar({ anchor: place, after: textarea }),
    ],
    link: (view) => askLink(view, place.parentElement),
  })
  const view = createView(place, {
    doc: originalDoc,
    plugins: all,
    editable: () => !textarea.disabled && !textarea.readOnly,
    attributes: (state) => ({
      role: "textbox",
      "aria-multiline": "true",
      "aria-label": label,
      "data-placeholder": textarea.placeholder || "",
      class:
        state.doc.childCount === 1 &&
        state.doc.firstChild.isTextblock &&
        state.doc.firstChild.content.size === 0
          ? "is-empty"
          : "",
    }),
    onChange(view, changed) {
      showPressed(view.state)
      if (changed) write(view.state.doc)
    },
  })
  view.dom.addEventListener("focus", () => place.classList.remove("is-invalid"))

  const load = (text) => {
    original = text
    originalDoc = parse(text)
    view.updateState(EditorState.create({ doc: originalDoc, plugins: all }))
    showPressed(view.state)
  }

  const showSource = (source) => {
    editor.active = !source
    place.hidden = source
    textarea.hidden = !source
    showPressed(view.state)
  }

  Object.assign(editor, {
    view,
    run(action) {
      if (action === "source") {
        if (editor.active) {
          showSource(true)
          HTMLTextAreaElement.prototype.focus.call(textarea)
        } else {
          // The source parsed again; the original stays the original
          const text = textarea.value
          const doc = text === original ? originalDoc : parse(text)
          view.updateState(EditorState.create({ doc, plugins: all }))
          showSource(false)
          view.focus()
        }
        return
      }
      if (action === "link") return askLink(view, place.parentElement)
      ACTIONS[action]?.(view.state, view.dispatch)
      view.focus()
    },
    setMarkdown(text) {
      const doc = parse(text)
      // (not undone: it's the starting point, e.g. of a test)
      view.dispatch(
        view.state.tr
          .replaceWith(0, view.state.doc.content.size, doc.content)
          .setMeta("addToHistory", false),
      )
    },
    insertMarkdown(markdown) {
      const { state } = view
      const { $from } = state.selection
      const before = $from.parent.textBetween(0, $from.parentOffset, null, "￼")
      const tr = state.tr
      // (a space before what follows a word: not in the Markdown, which
      // would drop it)
      if (before && !/\s$/.test(before)) tr.insertText(" ")
      view.dispatch(
        tr.replaceSelection(markdownSlice(markdown)).scrollIntoView(),
      )
    },
    replaceText(placeholder, markdown) {
      let found = null
      view.state.doc.descendants((node, pos) => {
        if (found || !node.isText) return !found
        const index = node.text.indexOf(placeholder)
        if (index >= 0) found = [pos + index, pos + index + placeholder.length]
        return false
      })
      if (!found) {
        if (markdown) editor.insertMarkdown(markdown)
        return
      }
      const tr = view.state.tr
      if (markdown) tr.replaceRange(found[0], found[1], markdownSlice(markdown))
      else tr.delete(found[0], found[1])
      view.dispatch(tr)
    },
  })
  textarea.richEditor = editor
  textarea.hidden = true
  // Who focuses the field (modals, click to edit, the palette) gets the
  // editor
  textarea.focus = function focus(options) {
    if (editor.active) view.focus()
    else HTMLTextAreaElement.prototype.focus.call(this, options)
  }
  // A required field left empty: the editor says so (the hidden field can't)
  textarea.addEventListener("invalid", (event) => {
    if (!editor.active) return
    event.preventDefault()
    place.classList.add("is-invalid")
    view.focus()
  })
  // Resetting the form (the inline "Add a to-do" after saving) empties it
  textarea.form?.addEventListener("reset", () => {
    setTimeout(() => load(textarea.value))
  })
  if (textarea.id)
    for (const labelElement of document.querySelectorAll(
      `label[for="${CSS.escape(textarea.id)}"]`,
    ))
      labelElement.addEventListener(
        "click",
        () => editor.active && view.focus(),
      )

  if (bar) {
    const source = bar.querySelector('[data-toolbar-action="source"]')
    if (source) {
      source.hidden = false
      bar.append(source)
    }
    roving(bar)
    showPressed(view.state)
  }
  if (textarea.autofocus || document.activeElement === textarea) view.focus()
}

export function upgradeAll(root) {
  const fields = [
    ...(root.matches?.("textarea[data-toolbar]") ? [root] : []),
    ...(root.querySelectorAll?.("textarea[data-toolbar]") ?? []),
  ]
  for (const field of fields) {
    if (field.richEditor) continue
    upgrade(field)
  }
}

upgradeAll(document)
document.addEventListener("htmx:after:process", (event) =>
  upgradeAll(event.target),
)
