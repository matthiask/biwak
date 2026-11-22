// Typing Markdown still works (specs/rich-editor.md, "Input rules"):
// `**bold**`, `*italic*`, `` `code` ``, `~~struck~~`, `# `, `- `, `1. `,
// `[ ] `, `> `, three backticks, `---`. Backspace right after a rule
// takes it back.
import {
  InputRule,
  inputRules,
  textblockTypeInputRule,
  wrappingInputRule,
} from "prosemirror-inputrules"
import { schema } from "./schema.js"

const { nodes, marks } = schema

// `before` + text + `after` typed: the text gets the mark, the delimiters go
function markRule(regexp, type) {
  return new InputRule(regexp, (state, match, start, end) => {
    const [whole, lead, text] = match
    // Not inside code, and not across what isn't text
    const from = start + lead.length
    if (state.doc.resolve(start).parent.type.spec.code) return null
    if (type !== marks.code && state.doc.rangeHasMark(from, end, marks.code))
      return null
    const delimiter = (whole.length - lead.length - text.length) / 2
    // What was typed last isn't in the document yet
    const tr = state.tr.insertText(whole.slice(end - start), end, end)
    const to = start + whole.length
    tr.delete(to - delimiter, to)
    tr.delete(from, from + delimiter)
    tr.addMark(from, to - 2 * delimiter, type.create())
    tr.removeStoredMark(type)
    return tr
  })
}

// "[ ] " or "[x] " at the start of a list item's first paragraph makes it a
// task item; elsewhere a list with a task item
function taskRule() {
  return new InputRule(/^\[([ xX]?)\]\s$/, (state, match, start, end) => {
    const $start = state.doc.resolve(start)
    const checked = match[1] === "x" || match[1] === "X"
    if ($start.parent.type !== nodes.paragraph) return null
    const item = $start.node(-1)
    const tr = state.tr.delete(start, end)
    if (item?.type === nodes.list_item && $start.index(-1) === 0) {
      tr.setNodeMarkup($start.before(-1), null, { checked })
      return tr
    }
    const $pos = tr.doc.resolve(start)
    const range = $pos.blockRange()
    if (!range) return null
    tr.wrap(range, [
      { type: nodes.bullet_list },
      { type: nodes.list_item, attrs: { checked } },
    ])
    return tr
  })
}

function ruleRule() {
  return new InputRule(/^(?:---|\*\*\*|___)$/, (state, _match, start, end) => {
    const $start = state.doc.resolve(start)
    if ($start.parent.type !== nodes.paragraph || $start.depth !== 1)
      return null
    if ($start.parent.content.size !== end - start) return null
    const pos = $start.before()
    return state.tr.replaceWith(pos, $start.after(), [
      nodes.horizontal_rule.create(),
      nodes.paragraph.create(),
    ])
  })
}

export function rules() {
  return inputRules({
    rules: [
      wrappingInputRule(/^\s*>\s$/, nodes.blockquote),
      wrappingInputRule(/^\s*[-+*]\s$/, nodes.bullet_list),
      wrappingInputRule(
        /^(\d+)[.)]\s$/,
        nodes.ordered_list,
        (match) => ({ order: +match[1] }),
        (match, node) => node.childCount + node.attrs.order === +match[1],
      ),
      textblockTypeInputRule(/^(#{1,6})\s$/, nodes.heading, (match) => ({
        level: match[1].length,
      })),
      textblockTypeInputRule(/^```([\w-]*)\s$/, nodes.code_block, (match) => ({
        params: match[1],
      })),
      taskRule(),
      ruleRule(),
      markRule(/(^|[^*\w])\*\*([^*\s](?:[^*]*[^*\s])?)\*\*$/, marks.strong),
      markRule(/(^|[^_\w])__([^_\s](?:[^_]*[^_\s])?)__$/, marks.strong),
      markRule(/(^|[^*\w])\*([^*\s](?:[^*]*[^*\s])?)\*$/, marks.em),
      markRule(/(^|[^_\w])_([^_\s](?:[^_]*[^_\s])?)_$/, marks.em),
      markRule(/(^|[^~\w])~~([^~\s](?:[^~]*[^~\s])?)~~$/, marks.strikethrough),
      markRule(/(^|[^`])`([^`]+)`$/, marks.code),
    ],
  })
}

// Enter after three backticks (and a language) makes a code block
export function fenceOnEnter(state, dispatch) {
  const { $from, empty } = state.selection
  if (!empty || $from.parent.type !== nodes.paragraph) return false
  const match = /^```([\w-]*)$/.exec($from.parent.textContent)
  if (!match || $from.parentOffset !== $from.parent.content.size) return false
  if (dispatch) {
    const tr = state.tr.delete($from.start(), $from.end())
    tr.setBlockType($from.start(), $from.start(), nodes.code_block, {
      params: match[1],
    })
    dispatch(tr.scrollIntoView())
  }
  return true
}
