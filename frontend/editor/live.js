// The rich editor on a live doc's shared Yjs document (specs/rich-editor.md,
// "Live docs"; frontend/collab.js has the connection): y-prosemirror binds
// the editor to the `Y.XmlFragment` the server reads and writes too
// (biwak/richtext/ydoc.py), shows the others' cursors and names, and undoes
// one's own changes only.
import { Selection } from "prosemirror-state"
import {
  redo,
  undo,
  yCursorPlugin,
  ySyncPlugin,
  yUndoPlugin,
} from "y-prosemirror"
import { ACTIONS } from "./commands.js"
import { createView, plugins } from "./editor.js"
import { askLink } from "./link.js"
import { FRAGMENT } from "./live-schema.js"
import { serialize } from "./markdown.js"
import { markdownSlice, mentions, pasting } from "./plugins.js"
import { schema, setAttachmentUrl } from "./schema.js"

export { FRAGMENT }

// ``place``: where the editor goes; ``mayType()`` says whether it's
// editable now; ``upload(files)`` attaches files; ``mentionsUrl`` the `@`
// list's endpoint; ``label`` for screen readers
export function liveEditor(
  place,
  { ydoc, awareness, mayType, upload, mentionsUrl, label, attachmentUrl },
) {
  setAttachmentUrl(attachmentUrl)
  const fragment = ydoc.getXmlFragment(FRAGMENT)
  const editor = { active: true }
  const view = createView(place, {
    doc: schema.topNodeType.createAndFill(),
    plugins: plugins({
      extra: [
        ySyncPlugin(fragment),
        yCursorPlugin(awareness),
        yUndoPlugin(),
        ...(mentionsUrl ? [mentions({ url: mentionsUrl, anchor: place })] : []),
        pasting({ upload: (files) => (upload ? upload(files) : false) }),
      ],
      // Yjs' undo: one's own changes only
      undo: { undo, redo },
      link: (view) => askLink(view, place.parentElement),
    }),
    editable: () => mayType(),
    attributes: {
      role: "textbox",
      "aria-multiline": "true",
      "aria-label": label || "",
    },
    onChange: (current) => editor.onChange?.(current),
  })
  Object.assign(editor, {
    view,
    run(action) {
      if (action === "link") return askLink(view, place.parentElement)
      ACTIONS[action]?.(view.state, view.dispatch)
      view.focus()
    },
    // The editable state changed
    refresh() {
      if (!view.isDestroyed) view.setProps({ editable: () => mayType() })
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
    // The caret at the end, focused (a new doc's title)
    focusEnd() {
      const { state } = view
      const first = state.doc.firstChild
      const end = first ? first.nodeSize - 1 : 0
      view.dispatch(
        state.tr.setSelection(Selection.near(state.doc.resolve(end), -1)),
      )
      view.focus()
    },
    text: () => view.state.doc.textContent,
    markdown: () => serialize(view.state.doc),
    destroy: () => view.destroy(),
  })
  return editor
}
