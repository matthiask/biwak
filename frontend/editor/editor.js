// The rich editor itself (specs/rich-editor.md): a ProseMirror view of our
// schema with the keys, input rules and behaviour every text field and the
// live docs share. Everything ProseMirror is behind frontend/editor/;
// nothing else imports it.
import {
  baseKeymap,
  chainCommands,
  createParagraphNear,
  liftEmptyBlock,
  newlineInCode,
  splitBlock,
} from "prosemirror-commands"
import { history, redo, undo } from "prosemirror-history"
import { undoInputRule } from "prosemirror-inputrules"
import { keymap } from "prosemirror-keymap"
import {
  liftListItem,
  sinkListItem,
  splitListItem,
} from "prosemirror-schema-list"
import { EditorState, Plugin } from "prosemirror-state"
import { tableEditing } from "prosemirror-tables"
import { EditorView } from "prosemirror-view"
import { keyAction } from "../toolbar.js"
import { ACTIONS } from "./commands.js"
import { clipboardTextParser, linkify, tasks } from "./plugins.js"
import { fenceOnEnter, rules } from "./rules.js"
import { schema } from "./schema.js"

const { nodes } = schema

// A new item after a task item is a task item, unticked
function splitItem(state, dispatch) {
  const { $from } = state.selection
  let checked = null
  for (let depth = $from.depth; depth > 0; depth--)
    if ($from.node(depth).type === nodes.list_item) {
      checked = $from.node(depth).attrs.checked === null ? null : false
      break
    }
  return splitListItem(nodes.list_item, { checked })(state, dispatch)
}

function inTable(state) {
  const { $from } = state.selection
  for (let depth = $from.depth; depth > 0; depth--) {
    const type = $from.node(depth).type
    if (type === nodes.table_cell || type === nodes.table_header) return true
  }
  return false
}

// Shift+Enter: a line break; not in table cells (Markdown can't hold one)
function lineBreak(state, dispatch) {
  if (inTable(state) || state.selection.$from.parent.type.spec.code)
    return inTable(state)
  dispatch?.(
    state.tr.replaceSelectionWith(nodes.hard_break.create()).scrollIntoView(),
  )
  return true
}

const inList = (state) => {
  const { $from } = state.selection
  for (let depth = $from.depth; depth > 0; depth--)
    if ($from.node(depth).type === nodes.list_item) return true
  return false
}

// Tab and Shift+Tab indent list items; elsewhere Tab leaves the field
const indent = (outwards) => (state, dispatch) => {
  if (!inList(state)) return false
  ;(outwards ? liftListItem : sinkListItem)(nodes.list_item)(state, dispatch)
  // Can't go further: still the editor's key
  return true
}

const base = { ...baseKeymap }
// Ctrl+Enter submits the form (frontend/submit-shortcut.js)
delete base["Mod-Enter"]

// ``link(view)`` asks for a link's address (the toolbar's Ctrl+K);
// ``commands``: undo and redo (ProseMirror's history's by default)
export function keys({ commands = { undo, redo }, link } = {}) {
  return [
    // The toolbar's keys, by `event.code` like the source's
    // (frontend/toolbar.js): Ctrl+B, Ctrl+I, Ctrl+K, Ctrl+Shift+7/8/9
    new Plugin({
      props: {
        handleKeyDown(view, event) {
          if (event.isComposing) return false
          const action = keyAction(event)
          if (action) {
            // Inside a field Ctrl+K is "link", not the palette
            event.stopPropagation()
            if (action === "link") link?.(view)
            else ACTIONS[action](view.state, view.dispatch)
            return true
          }
          return false
        },
        handleDOMEvents: {
          // Ctrl+Enter submits the form, Escape closes a modal or a form
          // shown in place (and leaves the field, so that Ctrl+K reaches
          // the palette again): not the editor's, which would prevent their
          // default
          keydown(view, event) {
            if (event.key === "Escape" && !event.defaultPrevented) {
              view.dom.blur()
              return true
            }
            return (
              event.key === "Enter" &&
              (event.ctrlKey || event.metaKey) &&
              !event.shiftKey &&
              !event.altKey
            )
          },
        },
      },
    }),
    keymap({
      "Mod-z": commands.undo,
      "Shift-Mod-z": commands.redo,
      "Mod-y": commands.redo,
      Backspace: undoInputRule,
      Enter: chainCommands(
        newlineInCode,
        fenceOnEnter,
        splitItem,
        createParagraphNear,
        liftEmptyBlock,
        splitBlock,
      ),
      "Shift-Enter": lineBreak,
      Tab: indent(false),
      "Shift-Tab": indent(true),
    }),
    keymap(base),
  ]
}

// The plugins of every rich editor; ``extra`` go first (mentions take
// Enter while their list is open)
// (``undo``: other undo and redo commands, without ProseMirror's history)
export function plugins({ extra = [], undo: commands, link } = {}) {
  return [
    ...extra,
    rules(),
    ...keys({ commands, link }),
    ...(commands ? [] : [history()]),
    tableEditing(),
    linkify,
    tasks,
  ]
}

export function createView(
  place,
  { doc, plugins: all, editable, onChange, attributes },
) {
  const view = new EditorView(place, {
    state: EditorState.create({ doc, plugins: all }),
    editable,
    attributes,
    clipboardTextParser,
    // (``this``: plugins, y-prosemirror's, dispatch while the view is made)
    dispatchTransaction(tr) {
      const changed = tr.docChanged
      this.updateState(this.state.apply(tr))
      onChange?.(this, changed)
    },
  })
  return view
}

export { EditorState }
