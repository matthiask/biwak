// Markdown <-> the editor's document (specs/rich-editor.md), configured
// like render_markdown (biwak/templatetags/biwak.py): markdown-it
// commonmark, html off, breaks, linkify, strikethrough, tables, task lists;
// mentions as nodes. The server has the same in Python
// (biwak/richtext/parse.py, serialize.py): both give the same document and
// the same Markdown, byte for byte (the corpus and random documents in
// biwak/richtext/test_parity.py). Change both together.
import MarkdownIt from "markdown-it"
import { MarkdownParser, MarkdownSerializerState } from "prosemirror-markdown"
import { Fragment } from "prosemirror-model"
import { schema } from "./schema.js"

// --- markdown-it ----------------------------------------------------------

const TODO = /^\[[ xX]\][ \t\n\v\f\r]+/
// The server's plugin only makes a box of these (a tab after the box: no
// box, but "[ ]" dropped: a quirk of the server)
const BOX = /^\[[ xX]\] /

// A port of mdit-py-plugins' tasklists: an inline right after a list
// item's paragraph, starting with "[ ] " or "[x] "
function tasklists(state) {
  const tokens = state.tokens
  for (let i = 2; i < tokens.length - 1; i++) {
    const t = tokens[i]
    if (
      t.type === "inline" &&
      tokens[i - 1].type === "paragraph_open" &&
      tokens[i - 2].type === "list_item_open" &&
      TODO.test(t.content) &&
      BOX.test(t.content)
    ) {
      const m = TODO.exec(t.content)
      tokens[i - 2].meta = { checked: m[0][1] !== " " }
      // The server's plugin drops 3 characters of the first child; the
      // box's whitespace isn't text either
      const first = t.children[0]
      if (first && first.type === "text") {
        first.content = first.content.slice(3).replace(/^[ \t]+/, "")
      }
      t.content = t.content.slice(m[0].length)
    }
  }
}

const PERSON = /^person:(\d+)$/

// [@Ada](person:12) as one token; only with "@" (MENTION in
// biwak/activity/mentions.py)
function mentions(state) {
  for (const block of state.tokens) {
    if (block.type !== "inline" || !block.children) continue
    const out = []
    const c = block.children
    for (let i = 0; i < c.length; i++) {
      const t = c[i]
      const m = t.type === "link_open" && PERSON.exec(t.attrGet("href") || "")
      if (
        !m ||
        c[i + 1]?.type !== "text" ||
        !c[i + 1].content.startsWith("@")
      ) {
        out.push(t)
        continue
      }
      let end = i + 1
      while (c[end].type !== "link_close") end++
      const label = c
        .slice(i + 1, end)
        .map((x) => x.content)
        .join("")
      const mention = new state.Token("mention", "", 0)
      mention.meta = { id: m[1], label: label.replace(/^@/, "") }
      out.push(mention)
      i = end
    }
    block.children = out
  }
}

export function markdownIt() {
  const md = MarkdownIt("commonmark", {
    html: false,
    linkify: true,
    breaks: true,
  })
  md.enable(["linkify", "strikethrough", "table"])
  // markdown-it 15 turns fuzzy links off; the server's linkify-it-py links
  // www.example.org and example.org
  md.linkify.set({ fuzzyLink: true })
  md.core.ruler.after("inline", "github-tasklists", tasklists)
  md.core.ruler.push("mentions", mentions)
  return md
}

export const md = markdownIt()

// --- parser ---------------------------------------------------------------

function listIsTight(tokens, i) {
  while (++i < tokens.length)
    if (tokens[i].type !== "list_item_open") return tokens[i].hidden
  return false
}

function align(tok) {
  const m = /text-align:(\w+)/.exec(tok.attrGet("style") || "")
  return m ? m[1] : null
}

export const parser = new MarkdownParser(schema, md, {
  blockquote: { block: "blockquote" },
  paragraph: { block: "paragraph" },
  list_item: {
    block: "list_item",
    getAttrs: (tok) => ({ checked: tok.meta ? tok.meta.checked : null }),
  },
  bullet_list: {
    block: "bullet_list",
    getAttrs: (tok, tokens, i) => ({
      tight: listIsTight(tokens, i),
      markup: tok.markup,
    }),
  },
  ordered_list: {
    block: "ordered_list",
    getAttrs: (tok, tokens, i) => ({
      order: +tok.attrGet("start") || 1,
      tight: listIsTight(tokens, i),
      markup: tok.markup,
    }),
  },
  heading: {
    block: "heading",
    getAttrs: (tok) => ({ level: +tok.tag.slice(1), markup: tok.markup }),
  },
  code_block: {
    block: "code_block",
    noCloseToken: true,
    getAttrs: () => ({ markup: "indent" }),
  },
  fence: {
    block: "code_block",
    getAttrs: (tok) => ({ params: tok.info || "", markup: tok.markup }),
    noCloseToken: true,
  },
  hr: { node: "horizontal_rule", getAttrs: (tok) => ({ markup: tok.markup }) },
  image: { node: "image" },
  hardbreak: { node: "hard_break" },
  softbreak: { node: "hard_break" },
  mention: { node: "mention", getAttrs: (tok) => tok.meta },
  em: { mark: "em", getAttrs: (tok) => ({ markup: tok.markup }) },
  strong: { mark: "strong", getAttrs: (tok) => ({ markup: tok.markup }) },
  s: { mark: "strikethrough" },
  link: {
    mark: "link",
    getAttrs: (tok) => ({
      href: tok.attrGet("href"),
      title: tok.attrGet("title") || null,
      markup:
        tok.markup === "linkify" || tok.markup === "autolink"
          ? tok.markup
          : null,
    }),
  },
  code_inline: { mark: "code", noCloseToken: true },
  table: { block: "table" },
  thead: { ignore: true },
  tbody: { ignore: true },
  tr: { block: "table_row" },
  th: { block: "table_header" },
  td: { block: "table_cell" },
})

// Cells hold one paragraph: open and close it around the cell's inline
for (const [cell, type] of [
  ["th", "table_header"],
  ["td", "table_cell"],
]) {
  parser.tokenHandlers[`${cell}_open`] = (state, tok) => {
    state.openNode(schema.nodes[type], { align: align(tok) })
    state.openNode(schema.nodes.paragraph, null)
  }
  parser.tokenHandlers[`${cell}_close`] = (state) => {
    state.closeNode()
    state.closeNode()
  }
}

// A linked image: the link is the image's attribute, not a mark
parser.tokenHandlers.image = (state, tok) => {
  const marks = state.top().marks
  const link = marks.find((m) => m.type === schema.marks.link)
  state.top().marks = link ? link.removeFromSet(marks) : marks
  state.addNode(schema.nodes.image, {
    src: tok.attrGet("src"),
    title: tok.attrGet("title") || null,
    alt: tok.children.map((c) => c.content).join("") || null,
    href: link ? link.attrs.href : null,
    hrefTitle: link ? link.attrs.title : null,
  })
  state.top().marks = marks
}

export function parse(text) {
  return parser.parse(text || "")
}

// --- serializer -----------------------------------------------------------

function backticksFor(node, side) {
  const ticks = /`+/g
  let m
  let len = 0
  if (node.isText)
    while ((m = ticks.exec(node.text))) len = Math.max(len, m[0].length)
  let result = len > 0 && side > 0 ? " `" : "`"
  for (let i = 0; i < len; i++) result += "`"
  if (len > 0 && side < 0) result += " "
  return result
}

// Whether the link is written as its URL: its only text is what
// linkify-it would turn into this href
function linkifies(mark, parent, index) {
  const content = parent.child(index)
  if (!content.isText || mark.attrs.title) return false
  const t = content.text
  const href = mark.attrs.href
  if (!(t === href || `http://${t}` === href || `mailto:${t}` === href))
    return false
  if (content.marks[content.marks.length - 1] !== mark) return false
  return (
    index === parent.childCount - 1 ||
    !mark.isInSet(parent.child(index + 1).marks)
  )
}

// Images with a link attribute get their link mark back, so that a link
// around text and an image stays one link
function relink(parent) {
  let changed = false
  const children = []
  parent.forEach((child) => {
    if (child.type.name === "image" && child.attrs.href) {
      changed = true
      const link = schema.marks.link.create({
        href: child.attrs.href,
        title: child.attrs.hrefTitle,
      })
      children.push(
        child.type
          .create({ ...child.attrs, href: null, hrefTitle: null })
          .mark(link.addToSet(child.marks)),
      )
    } else children.push(child)
  })
  return changed ? parent.copy(Fragment.from(children)) : parent
}

// What would start a block (or a table, setext heading) at the start of
// a line after a break
const LINE_START = [
  [/^(\s*)([-+*>=])/, "$1\\$2"],
  [/^(\s*)(#{1,6})(\s|$)/, "$1\\$2$3"],
  [/^(\s*\d+)([.)])(\s|$)/, "$1\\$2$3"],
  [/^(\s*)(\|)/, "$1\\$2"],
]

function esc(str, startOfLine) {
  str = str.replace(/[`*\\~[\]_]/g, (m, i) =>
    m === "_" &&
    i > 0 &&
    i + 1 < str.length &&
    /\w/.test(str[i - 1]) &&
    /\w/.test(str[i + 1])
      ? m
      : `\\${m}`,
  )
  // entities (&amp;) and autolinks (<https://...>) would be read as such
  str = str
    .replace(/&(?=#?\w+;)/g, "\\&")
    .replace(/<(?=[a-zA-Z][\w+.-]*:|[^\s@<>]+@)/g, "\\<")
  if (startOfLine) for (const [re, to] of LINE_START) str = str.replace(re, to)
  return str
}

// Our style (decided 2026-11-22): `-` bullets, `*` emphasis, `**` strong,
// a newline for a break, bare URLs bare, backtick fences, `---` rules, and
// the source's choices where the document remembers them (`preserve`)
export const STYLE = {
  bullet: "-",
  em: "*",
  strong: "**",
  linkify: true,
  preserve: true,
  fence: "```",
  hr: "---",
}

export function createSerializer(options = {}) {
  const o = { ...STYLE, ...options }
  // The marker each list got, by node (one serialization)
  let used = new WeakMap()
  const pick = (markup, fallback) => (o.preserve && markup) || fallback

  const nodes = {
    blockquote(state, node) {
      state.wrapBlock("> ", null, node, () => state.renderContent(node))
    },
    code_block(state, node) {
      if (o.preserve && node.attrs.markup === "indent" && node.textContent) {
        state.wrapBlock("    ", null, node, () =>
          state.text(node.textContent, false),
        )
        return
      }
      const base =
        o.preserve && node.attrs.markup && node.attrs.markup !== "indent"
          ? node.attrs.markup
          : o.fence
      const ch = base[0]
      const runs = node.textContent.match(ch === "`" ? /`{3,}/gm : /~{3,}/gm)
      let fence = base
      if (runs) {
        const longest = runs.sort((a, b) => b.length - a.length)[0]
        if (longest.length >= fence.length)
          fence = ch.repeat(longest.length + 1)
      }
      state.write(`${fence}${node.attrs.params || ""}\n`)
      state.text(node.textContent, false)
      state.ensureNewLine()
      state.write(fence)
      state.closeBlock(node)
    },
    heading(state, node) {
      const markup = o.preserve ? node.attrs.markup : null
      if ((markup === "=" || markup === "-") && node.childCount) {
        state.renderInline(node, false)
        state.ensureNewLine()
        state.write(markup === "=" ? "===" : "---")
        state.closeBlock(node)
        return
      }
      state.write(`${"#".repeat(node.attrs.level)} `)
      state.renderInline(node, false)
      state.closeBlock(node)
    },
    horizontal_rule(state, node) {
      state.write(pick(node.attrs.markup, o.hr))
      state.closeBlock(node)
    },
    bullet_list(state, node, parent, index) {
      let b = pick(node.attrs.markup, o.bullet)
      // A list right after another of the same kind needs another marker,
      // else they become one (loose) list
      const prev = index > 0 ? parent.child(index - 1) : null
      if (prev?.type === node.type && used.get(prev) === b)
        b = b === "-" ? "*" : "-"
      used.set(node, b)
      state.renderList(node, "  ", () => `${b} `)
    },
    ordered_list(state, node, parent, index) {
      const start = node.attrs.order ?? 1
      let delim = pick(node.attrs.markup, ".")
      const prev = index > 0 ? parent.child(index - 1) : null
      if (prev?.type === node.type && used.get(prev) === delim)
        delim = delim === "." ? ")" : "."
      used.set(node, delim)
      const maxW = String(start + node.childCount - 1).length
      const space = " ".repeat(maxW + 2)
      state.renderList(node, space, (i) => {
        const n = String(start + i)
        return `${" ".repeat(maxW - n.length) + n + delim} `
      })
    },
    list_item(state, node) {
      if (node.attrs.checked !== null)
        state.write(node.attrs.checked ? "[x] " : "[ ] ")
      // In a tight list the blocks of an item follow without a blank line
      // (a blank line would make the list loose)
      node.forEach((child, _, i) => {
        // (but an ordered list not starting at 1 can't interrupt a
        // paragraph: it needs the blank line)
        if (i && state.inTightList && child.type.name !== "paragraph")
          state.flushClose(
            child.type.name === "ordered_list" && child.attrs.order !== 1
              ? 2
              : 1,
          )
        state.render(child, node, i)
      })
    },
    paragraph(state, node) {
      state.renderInline(node)
      state.closeBlock(node)
    },
    image(state, node) {
      const src = node.attrs.src.replace(/[()\s]/g, (c) =>
        c === " " ? "%20" : `\\${c}`,
      )
      const title = node.attrs.title
        ? ` "${node.attrs.title.replace(/"/g, '\\"')}"`
        : ""
      state.write(`![${state.esc(node.attrs.alt || "")}](${src}${title})`)
    },
    mention(state, node) {
      state.write(
        `[@${node.attrs.label.replace(/[\\[\]]/g, "\\$&")}](person:${node.attrs.id})`,
      )
    },
    hard_break(state, node, parent, index) {
      // a trailing break would vanish anyway
      for (let i = index + 1; i < parent.childCount; i++)
        if (parent.child(i).type !== node.type) {
          // an empty line would end the paragraph: a backslash break
          const empty =
            index === 0 || parent.child(index - 1).type === node.type
          state.write(empty ? "\\\n" : "\n")
          return
        }
    },
    text(state, node, parent, index) {
      const afterBreak =
        index > 0 && parent.child(index - 1).type.name === "hard_break"
      if (afterBreak) state.atBlockStart = true
      state.text(node.text, !state.inAutolink)
    },
    table(state, node) {
      const rows = []
      node.forEach((row) => {
        const cells = []
        row.forEach((cell) => {
          const sub = newState()
          sub.renderInline(cell.firstChild)
          // every pipe in a cell is content, also in code (GFM)
          const text = sub.out.replace(/\n/g, " ").replace(/\|/g, "\\|")
          cells.push({ text, align: cell.attrs.align })
        })
        rows.push(cells)
      })
      const head = rows[0]
      const line = (cells) => `| ${cells.map((c) => c.text).join(" | ")} |`
      const sep = head.map(
        (c) =>
          ({ left: ":---", right: "---:", center: ":---:" })[c.align] || "---",
      )
      const out = [
        line(head),
        `| ${sep.join(" | ")} |`,
        ...rows.slice(1).map(line),
      ]
      out.forEach((l, i) => {
        if (i) state.ensureNewLine()
        state.write(l)
      })
      state.closeBlock(node)
    },
  }

  const marks = {
    em: {
      open: (_s, m) => pick(m.attrs.markup, o.em),
      close: (_s, m) => pick(m.attrs.markup, o.em),
      mixable: true,
      expelEnclosingWhitespace: true,
    },
    strong: {
      open: (_s, m) => pick(m.attrs.markup, o.strong),
      close: (_s, m) => pick(m.attrs.markup, o.strong),
      mixable: true,
      expelEnclosingWhitespace: true,
    },
    strikethrough: {
      open: "~~",
      close: "~~",
      mixable: true,
      expelEnclosingWhitespace: true,
    },
    link: {
      open(state, mark, parent, index) {
        if (
          o.linkify &&
          mark.attrs.markup !== "autolink" &&
          linkifies(mark, parent, index)
        ) {
          state.inAutolink = "bare"
          return ""
        }
        const plain =
          !mark.attrs.title &&
          /^\w+:/.test(mark.attrs.href) &&
          parent.child(index).isText &&
          (parent.child(index).text === mark.attrs.href ||
            `mailto:${parent.child(index).text}` === mark.attrs.href) &&
          (mark.attrs.markup === "autolink" || !o.linkify)
        state.inAutolink = plain ? "angle" : undefined
        return plain ? "<" : "["
      },
      close(state, mark) {
        const how = state.inAutolink
        state.inAutolink = undefined
        if (how === "bare") return ""
        if (how === "angle") return ">"
        const href = mark.attrs.href.replace(/[()"\s]/g, (c) =>
          c === " " ? "%20" : `\\${c}`,
        )
        return `](${href}${mark.attrs.title ? ` "${mark.attrs.title.replace(/"/g, '\\"')}"` : ""})`
      },
      mixable: true,
    },
    code: {
      open: (_s, _m, parent, index) => backticksFor(parent.child(index), -1),
      close: (_s, _m, parent, index) =>
        backticksFor(parent.child(index - 1), 1),
      escape: false,
    },
  }

  function newState() {
    const state = new MarkdownSerializerState(nodes, marks, {
      tightLists: true,
    })
    state.esc = (s, start) => esc(s, start)
    const renderInline = state.renderInline
    state.renderInline = (parent, fromBlockStart) =>
      renderInline.call(state, relink(parent), fromBlockStart)
    return state
  }

  function serialize(doc) {
    used = new WeakMap()
    const state = newState()
    state.renderContent(doc)
    return state.out
  }
  return { serialize }
}

export const serializer = createSerializer()

export function serialize(doc) {
  return serializer.serialize(doc)
}

// The task list boxes in reading order (biwak/richtext/checklists.py names
// them so)
export function boxes(doc) {
  const out = []
  doc.descendants((node) => {
    if (node.type.name === "list_item" && node.attrs.checked !== null)
      out.push(node.attrs.checked)
  })
  return out
}
