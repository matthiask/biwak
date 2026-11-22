// Random documents of our schema, as an editor could make them, for the
// tests of both serializers (markdown.test.js, dump.js; adapted from the
// spike's fuzz.js). Seeded: the same documents every run.
import { Fragment } from "prosemirror-model"
import { schema } from "../schema.js"

let seed = 42
const rand = () => {
  // mulberry32
  seed |= 0
  seed = (seed + 0x6d2b79f5) | 0
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}
const pick = (a) => a[Math.floor(rand() * a.length)]
const chance = (p) => rand() < p

const WORDS = [
  "tent",
  "stove",
  "Ada",
  "Zürich",
  "snake_case",
  "2*3",
  "a*b*c",
  "[note]",
  "x]y",
  "`tick`",
  "back\\slash",
  "~tilde~",
  "#hash",
  "- dash",
  "1. one",
  "3) three",
  "|pipe|",
  "<b>",
  "&amp;",
  "&copy;",
  "a < b",
  "!",
  "![",
  "50%",
  "under_",
  "_lead",
  "**",
  "__",
  "+",
  ">",
  "=",
  "===",
  "---",
  "émoji 🏔️",
  "https://example.org/a_b?c=1",
  "www.example.com",
  "ada@example.org",
  "<https://example.org>",
  "tab\there",
  "@Bob",
  "person:3",
  "\\*",
]
// Bare URLs in text become links when parsed (linkify), as they do on the
// page and while typing: not in random text
for (const w of [
  "https://example.org/a_b?c=1",
  "www.example.com",
  "ada@example.org",
  "<https://example.org>",
])
  WORDS.splice(WORDS.indexOf(w), 1)
const MARKS = ["em", "strong", "strikethrough", "code", "link"]

function words(n) {
  const out = []
  for (let i = 0; i < n; i++) out.push(pick(WORDS))
  return out.join(" ")
}

function inline(allowBreaks = true) {
  const nodes = []
  const n = 1 + Math.floor(rand() * 5)
  for (let i = 0; i < n; i++) {
    const r = rand()
    if (r < 0.08) {
      nodes.push(
        schema.nodes.mention.create({
          id: String(1 + Math.floor(rand() * 50)),
          label: pick(["Ada Example", "Bob", "Cleo [x]"]),
        }),
      )
    } else if (r < 0.12) {
      nodes.push(
        schema.nodes.image.create({
          src: `attachment:${Math.floor(rand() * 1e6).toString(16)}`,
          alt: pick(["plan.png", "a [b].png", ""]),
          href: chance(0.3) ? "https://example.org/big" : null,
        }),
      )
    } else if (r < 0.2 && allowBreaks && nodes.length) {
      nodes.push(schema.nodes.hard_break.create())
    } else {
      const marks = []
      for (const m of MARKS) {
        if (!chance(0.18)) continue
        if (m === "link")
          marks.push(
            schema.marks.link.create({
              href: pick([
                "https://example.org/x",
                "attachment:ab12",
                "mailto:ada@example.org",
              ]),
            }),
          )
        else marks.push(schema.marks[m].create())
      }
      const set = marks.some((m) => m.type.name === "code")
        ? marks.filter((m) => ["code", "link"].includes(m.type.name))
        : marks
      nodes.push(schema.text(words(1 + Math.floor(rand() * 4)), set))
      if (i + 1 < n) nodes.push(schema.text(" "))
    }
  }
  return nodes
}

function paragraph(allowBreaks) {
  return schema.nodes.paragraph.create(null, inline(allowBreaks))
}

function list(depth) {
  const ordered = chance(0.4)
  const tasks = chance(0.4)
  const items = []
  for (let i = 0; i < 1 + Math.floor(rand() * 3); i++) {
    const content = [paragraph(true)]
    if (depth < 2 && chance(0.25)) content.push(list(depth + 1))
    if (chance(0.1))
      content.push(schema.nodes.code_block.create(null, schema.text("x = 1")))
    items.push(
      schema.nodes.list_item.create(
        { checked: tasks ? chance(0.5) : null },
        content,
      ),
    )
  }
  return (
    ordered ? schema.nodes.ordered_list : schema.nodes.bullet_list
  ).create(
    ordered
      ? { order: pick([1, 1, 3, 10]), tight: chance(0.8) }
      : { tight: chance(0.8) },
    items,
  )
}

function table() {
  const cols = 1 + Math.floor(rand() * 3)
  const rows = []
  for (let r = 0; r < 1 + Math.floor(rand() * 3); r++) {
    const cells = []
    for (let c = 0; c < cols; c++) {
      const type = r === 0 ? schema.nodes.table_header : schema.nodes.table_cell
      cells.push(
        type.create(
          { align: pick([null, "left", "right", "center"]) },
          paragraph(false),
        ),
      )
    }
    rows.push(schema.nodes.table_row.create(null, cells))
  }
  // alignment is per column
  const aligns = rows[0].content.content.map((c) => c.attrs.align)
  return schema.nodes.table.create(
    null,
    rows.map((row) =>
      schema.nodes.table_row.create(
        null,
        row.content.content.map((c, i) =>
          c.type.create({ align: aligns[i] }, c.content),
        ),
      ),
    ),
  )
}

function block(depth = 0) {
  const r = rand()
  if (r < 0.4) return paragraph(true)
  if (r < 0.5)
    return schema.nodes.heading.create(
      { level: 1 + Math.floor(rand() * 3) },
      inline(false),
    )
  if (r < 0.7) return list(0)
  if (r < 0.78 && depth < 1)
    return schema.nodes.blockquote.create(null, [
      block(depth + 1),
      ...(chance(0.5) ? [block(depth + 1)] : []),
    ])
  if (r < 0.85)
    return schema.nodes.code_block.create(
      { params: pick(["", "js"]) },
      schema.text(pick(["a\n  b", "```\nfence inside\n```", "~~~"])),
    )
  if (r < 0.9) return schema.nodes.horizontal_rule.create()
  return table()
}

// Markdown can't hold whitespace at the edges of a paragraph or around a
// break, nor an empty heading: what the editor would lose on saving anyway
function strip(json) {
  if (json.attrs && "markup" in json.attrs)
    json.attrs = { ...json.attrs, markup: null }
  // tight or loose is spacing; FUZZ_TIGHT=1 compares it
  if (json.attrs && "tight" in json.attrs)
    json.attrs = { ...json.attrs, tight: null }
  if (json.type === "image" && !json.attrs.alt)
    json.attrs = { ...json.attrs, alt: null }
  if (json.marks)
    json.marks = json.marks.map((m) =>
      m.attrs && "markup" in m.attrs
        ? { ...m, attrs: { ...m.attrs, markup: null } }
        : m,
    )
  if (json.content) json.content.forEach(strip)
  return json
}

// Whitespace Markdown can't hold: at the start and end of a textblock and
// around breaks; trailing breaks
function trim(node) {
  if (!node.isTextblock || node.type.spec.code) {
    if (node.isLeaf || node.isTextblock) return node
    const kids = []
    node.forEach((c) => {
      kids.push(trim(c))
    })
    return node.copy(
      node.type.contentMatch ? Fragment.from(kids) : node.content,
    )
  }
  const kids = []
  node.forEach((c) => {
    kids.push(c)
  })
  const out = []
  kids.forEach((c, i) => {
    if (!c.isText) {
      out.push(c)
      return
    }
    let t = c.text
    const prev = kids[i - 1]
    const next = kids[i + 1]
    if (!prev || prev.type.name === "hard_break") t = t.replace(/^[ \t]+/, "")
    if (!next || next.type.name === "hard_break") t = t.replace(/[ \t]+$/, "")
    if (t) out.push(c.withText(t))
  })
  while (out.length && out[out.length - 1].type.name === "hard_break") out.pop()
  while (out.length && out[0].type.name === "hard_break") out.shift()
  return node.copy(Fragment.from(out))
}

// ``count`` documents from ``start``
export function randomDocs(count, start = 42) {
  seed = start
  const docs = []
  for (let i = 0; i < count; i++) {
    const blocks = []
    for (let b = 0; b < 1 + Math.floor(rand() * 5); b++) blocks.push(block())
    docs.push(trim(schema.nodes.doc.create(null, blocks)))
  }
  return docs
}

// The document's JSON without what Markdown keeps only as spacing or style
export function comparable(doc) {
  return JSON.stringify(strip(doc.toJSON()))
}
