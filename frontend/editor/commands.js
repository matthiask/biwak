// What the toolbar's buttons and keys do in the rich editor (specs/editor.md,
// specs/rich-editor.md): the same buttons as for the Markdown source
// (frontend/toolbar.js), here on the document. Each toggles: pressed again
// it takes the formatting off.
import { lift, setBlockType, toggleMark, wrapIn } from "prosemirror-commands"
import { liftListItem, wrapInList } from "prosemirror-schema-list"
import { TextSelection } from "prosemirror-state"
import { schema } from "./schema.js"
import { insertTable } from "./tables.js"

const { nodes, marks } = schema

// The innermost ancestor of the selection's start of one of these types
function ancestor(state, ...types) {
  const { $from } = state.selection
  for (let depth = $from.depth; depth > 0; depth--) {
    const node = $from.node(depth)
    if (types.includes(node.type))
      return { node, depth, pos: $from.before(depth) }
  }
  return null
}

function markActive(state, type) {
  const { from, $from, to, empty } = state.selection
  if (empty) return !!type.isInSet(state.storedMarks || $from.marks())
  return state.doc.rangeHasMark(from, to, type)
}

// The kind of list the selection is in: "bullets", "numbers", "tasks"
function listKind(state) {
  const item = ancestor(state, nodes.list_item)
  if (!item) return null
  if (item.node.attrs.checked !== null) return "tasks"
  const list = state.selection.$from.node(item.depth - 1)
  return list.type === nodes.ordered_list ? "numbers" : "bullets"
}

// Sets every item of the list around the selection (and the list's type)
function retypeList(state, dispatch, listType, checked) {
  const item = ancestor(state, nodes.list_item)
  const listDepth = item.depth - 1
  const $from = state.selection.$from
  const list = $from.node(listDepth)
  const pos = $from.before(listDepth)
  if (!dispatch) return true
  const tr = state.tr
  if (list.type !== listType)
    tr.setNodeMarkup(pos, listType, { tight: list.attrs.tight })
  list.forEach((child, offset) => {
    tr.setNodeMarkup(pos + 1 + offset, null, { ...child.attrs, checked })
  })
  dispatch(tr)
  return true
}

function toggleList(kind) {
  const listType = kind === "numbers" ? nodes.ordered_list : nodes.bullet_list
  const checked = kind === "tasks" ? false : null
  return (state, dispatch) => {
    const current = listKind(state)
    if (current === kind) return liftListItem(nodes.list_item)(state, dispatch)
    if (current) return retypeList(state, dispatch, listType, checked)
    if (checked === null) return wrapInList(listType)(state, dispatch)
    // Wrapped, then its items made task items
    return wrapInList(listType)(state, (tr) => {
      const range = tr.selection.$from.blockRange(tr.selection.$to)
      tr.doc.nodesBetween(range?.start ?? 0, range?.end ?? 0, (node, pos) => {
        if (node.type === nodes.list_item && node.attrs.checked === null)
          tr.setNodeMarkup(pos, null, { checked })
      })
      dispatch?.(tr)
    })
  }
}

function toggleHeading(state, dispatch) {
  const { $from } = state.selection
  if ($from.parent.type === nodes.heading)
    return setBlockType(nodes.paragraph)(state, dispatch)
  return setBlockType(nodes.heading, { level: 2 })(state, dispatch)
}

function toggleQuote(state, dispatch) {
  if (ancestor(state, nodes.blockquote)) return lift(state, dispatch)
  return wrapIn(nodes.blockquote)(state, dispatch)
}

// Inline code in a line, a code block for several or an empty line
function toggleCode(state, dispatch) {
  const { $from, $to, empty } = state.selection
  if ($from.parent.type === nodes.code_block)
    return setBlockType(nodes.paragraph)(state, dispatch)
  if (!$from.sameParent($to)) {
    // The blocks' lines in one code block
    const range = $from.blockRange($to)
    if (!range) return false
    let text = ""
    state.doc.nodesBetween(range.start, range.end, (node) => {
      if (!node.isTextblock) return true
      text += `${text ? "\n" : ""}${node.textContent}`
      return false
    })
    dispatch?.(
      state.tr
        .replaceWith(
          range.start,
          range.end,
          nodes.code_block.create(null, text ? schema.text(text) : null),
        )
        .scrollIntoView(),
    )
    return true
  }
  if (empty && $from.parent.content.size === 0)
    return setBlockType(nodes.code_block)(state, dispatch)
  return toggleMark(marks.code)(state, dispatch)
}

// "@" at the caret, with a space before it where needed: the list opens
function startMention(state, dispatch) {
  const { $from } = state.selection
  const before = $from.parent.textBetween(0, $from.parentOffset, null, "￼")
  const lead = before && !/[\s(]$/.test(before) ? " " : ""
  dispatch?.(state.tr.insertText(`${lead}@`).scrollIntoView())
  return true
}

// The link around the selection or the caret: [from, to, mark]
export function linkAt(state) {
  const { $from, from, to, empty } = state.selection
  const type = marks.link
  if (!empty) {
    let found = null
    state.doc.nodesBetween(from, to, (node) => {
      found ||= type.isInSet(node.marks)
    })
    return found ? [from, to, found] : null
  }
  const mark =
    type.isInSet($from.marks()) || type.isInSet($from.nodeAfter?.marks || [])
  if (!mark) return null
  // The whole link around the caret: the run of children with the mark
  let pos = $from.start()
  let begin = null
  let found = null
  $from.parent.forEach((child) => {
    const end = pos + child.nodeSize
    if (mark.isInSet(child.marks)) {
      begin ??= pos
      if (begin <= $from.pos && $from.pos <= end) found = [begin, end, mark]
    } else begin = null
    pos = end
  })
  return found
}

export function setLink(view, href) {
  const { state } = view
  const { from, to, empty } = state.selection
  const tr = state.tr
  if (!href) {
    const link = linkAt(state)
    if (link) tr.removeMark(link[0], link[1], marks.link)
  } else if (empty) {
    const mark = marks.link.create({ href })
    tr.insert(from, schema.text(href, [mark]))
  } else {
    tr.removeMark(from, to, marks.link)
    tr.addMark(from, to, marks.link.create({ href }))
    tr.setSelection(TextSelection.create(tr.doc, to))
  }
  view.dispatch(tr.scrollIntoView())
  view.focus()
}

export const ACTIONS = {
  bold: toggleMark(marks.strong),
  italic: toggleMark(marks.em),
  heading: toggleHeading,
  bullets: toggleList("bullets"),
  numbers: toggleList("numbers"),
  tasks: toggleList("tasks"),
  quote: toggleQuote,
  code: toggleCode,
  mention: startMention,
  table: insertTable,
}

// Which buttons show as pressed (aria-pressed)
export function active(state) {
  const kind = listKind(state)
  return {
    bold: markActive(state, marks.strong),
    italic: markActive(state, marks.em),
    link: !!linkAt(state),
    code:
      markActive(state, marks.code) ||
      state.selection.$from.parent.type === nodes.code_block,
    heading: state.selection.$from.parent.type === nodes.heading,
    bullets: kind === "bullets",
    numbers: kind === "numbers",
    tasks: kind === "tasks",
    quote: !!ancestor(state, nodes.blockquote),
  }
}
