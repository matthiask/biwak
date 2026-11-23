// The rich editor on a live doc's shared Yjs document (specs/rich-editor.md,
// "Live docs"; frontend/collab.js has the connection): y-prosemirror binds
// the editor to the `Y.XmlFragment` the server reads and writes too
// (biwak/richtext/ydoc.py), shows the others' cursors and names, and undoes
// one's own changes only.
import { setBlockType } from "prosemirror-commands"
import { Plugin, Selection } from "prosemirror-state"
import { Decoration, DecorationSet } from "prosemirror-view"
import {
  redo,
  undo,
  yCursorPlugin,
  ySyncPlugin,
  yUndoPlugin,
  yUndoPluginKey,
} from "y-prosemirror"
import { ACTIONS } from "./commands.js"
import { createView, plugins } from "./editor.js"
import { askLink } from "./link.js"
import { FRAGMENT } from "./live-schema.js"
import { serialize } from "./markdown.js"
import { markdownSlice, mentions, pasting } from "./plugins.js"
import { schema, setAttachmentUrl } from "./schema.js"
import { tableBar } from "./tables.js"

export { FRAGMENT }

// The heading button in a doc's first line, its title, makes it a level-1
// heading (decided 2026-11-23), elsewhere a level-2 one as in every field
function heading(state, dispatch) {
  const { $from } = state.selection
  if ($from.depth !== 1 || $from.index(0) !== 0)
    return ACTIONS.heading(state, dispatch)
  if (
    $from.parent.type === schema.nodes.heading &&
    $from.parent.attrs.level === 1
  )
    return setBlockType(schema.nodes.paragraph)(state, dispatch)
  return setBlockType(schema.nodes.heading, { level: 1 })(state, dispatch)
}

// The hint in an empty first line, a doc's title (any doc, decided
// 2026-11-23), as the fields' placeholder (frontend/editor/fields.js): not
// text, so typing replaces it and a new doc stays a draft until something
// is written (specs/files.md, "Docs")
function emptyTitle(text) {
  return new Plugin({
    props: {
      decorations(state) {
        const first = state.doc.firstChild
        if (!first?.isTextblock || first.content.size) return null
        return DecorationSet.create(state.doc, [
          Decoration.node(0, first.nodeSize, {
            class: "is-empty",
            "data-placeholder": text,
          }),
        ])
      },
    },
  })
}

// ``place``: where the editor goes; ``mayType()`` says whether it's
// editable now; ``upload(files)`` attaches files; ``mentionsUrl`` the `@`
// list's endpoint; ``label`` for screen readers; ``titlePlaceholder`` is
// shown in an empty first line (the doc's title, decided 2026-11-23)
export function liveEditor(
  place,
  {
    ydoc,
    awareness,
    mayType,
    upload,
    mentionsUrl,
    label,
    attachmentUrl,
    titlePlaceholder,
  },
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
        pasting({
          upload: (files) => (upload ? upload(files) : false),
          // Pasted Markdown's parsing is an undo step of its own
          separate: () =>
            yUndoPluginKey
              .getState(editor.view.state)
              ?.undoManager.stopCapturing(),
        }),
        tableBar({ anchor: place }),
        ...(titlePlaceholder ? [emptyTitle(titlePlaceholder)] : []),
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
      const command = action === "heading" ? heading : ACTIONS[action]
      command?.(view.state, view.dispatch)
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
    // An empty doc's first line is its title, a level-1 heading (decided
    // 2026-11-23); only once synced, or it would merge in as a line of its
    // own, and not in Undo
    ensureTitle() {
      const { state } = view
      const first = state.doc.firstChild
      if (
        state.doc.childCount !== 1 ||
        first?.type !== schema.nodes.paragraph ||
        first.content.size
      )
        return
      view.dispatch(
        state.tr
          .setNodeMarkup(0, schema.nodes.heading, { level: 1 })
          .setMeta("addToHistory", false),
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
