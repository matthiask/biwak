// The editor's behaviour beyond typing (specs/rich-editor.md): bare URLs
// becoming links while typing, ticking task items, the `@` list, pasting.
import { Fragment, Slice } from "prosemirror-model"
import { Plugin, PluginKey, Selection } from "prosemirror-state"
import { Mapping } from "prosemirror-transform"
import { mentionList, mentionQuery } from "../mentions.js"
import { MARKUP, pasteUrl, toMarkdown, URL_ONLY } from "../paste.js"
import { md, parse } from "./markdown.js"
import { schema } from "./schema.js"

const { nodes, marks } = schema
const OBJECT = "￼"

// --- Bare URLs ------------------------------------------------------------

// The links the server's linkify would make in a textblock: [from, to, url]
function linkified(block, start) {
  let text = ""
  const code = []
  block.forEach((child, offset) => {
    const t = child.isText ? child.text : OBJECT.repeat(child.nodeSize)
    if (child.isText && marks.code.isInSet(child.marks))
      code.push([offset, offset + t.length])
    text += t
  })
  const matches = md.linkify.test(text) ? md.linkify.match(text) || [] : []
  return matches
    .filter(
      (m) =>
        md.validateLink(m.url) &&
        !code.some(([a, b]) => m.index < b && m.lastIndex > a),
    )
    .map((m) => [start + m.index, start + m.lastIndex, md.normalizeLink(m.url)])
}

// Typed bare URLs become links, as the page shows them (and links that
// stopped being URLs plain text again): the textblocks a change touched
export const linkify = new Plugin({
  appendTransaction(transactions, _old, state) {
    if (!transactions.some((tr) => tr.docChanged)) return null
    // The changed ranges, in the new document's positions
    const maps = transactions.flatMap((tr) => tr.mapping.maps)
    const ranges = []
    maps.forEach((map, i) => {
      const after = new Mapping(maps.slice(i + 1))
      map.forEach((_a, _b, from, to) => {
        ranges.push([after.map(from, -1), after.map(to, 1)])
      })
    })
    const tr = state.tr
    const seen = new Set()
    for (const [from, to] of ranges) {
      const a = Math.max(0, Math.min(from, state.doc.content.size))
      const b = Math.max(a, Math.min(to, state.doc.content.size))
      state.doc.nodesBetween(a, b, (node, pos) => {
        if (!node.isTextblock) return true
        if (seen.has(pos) || node.type.spec.code) return false
        seen.add(pos)
        const start = pos + 1
        const want = linkified(node, start)
        const have = []
        node.forEach((child, offset) => {
          const mark = marks.link.isInSet(child.marks)
          if (mark?.attrs.markup === "linkify")
            have.push([
              start + offset,
              start + offset + child.nodeSize,
              mark.attrs.href,
            ])
        })
        // Adjacent pieces of one link are one
        const merged = []
        for (const h of have) {
          const last = merged[merged.length - 1]
          if (last && last[1] === h[0] && last[2] === h[2]) last[1] = h[1]
          else merged.push([...h])
        }
        const same = (x, y) => x[0] === y[0] && x[1] === y[1] && x[2] === y[2]
        for (const h of merged)
          if (!want.some((w) => same(w, h)))
            tr.removeMark(h[0], h[1], marks.link)
        for (const w of want) {
          if (merged.some((h) => same(w, h))) continue
          // Not over a link somebody made
          if (state.doc.rangeHasMark(w[0], w[1], marks.link)) {
            let other = false
            state.doc.nodesBetween(w[0], w[1], (child) => {
              const mark = marks.link.isInSet(child.marks)
              if (mark && mark.attrs.markup !== "linkify") other = true
            })
            if (other) continue
          }
          tr.addMark(
            w[0],
            w[1],
            marks.link.create({ href: w[2], markup: "linkify" }),
          )
        }
        return false
      })
    }
    return tr.docChanged ? tr : null
  },
})

// --- Task items -----------------------------------------------------------

// Clicking a task item's box ticks it (in the document: saving saves it)
export const tasks = new Plugin({
  props: {
    handleDOMEvents: {
      mousedown(_view, event) {
        if (event.target.matches?.("input.task-list-item-checkbox"))
          event.preventDefault()
        return false
      },
      click(view, event) {
        const box = event.target
        if (!box.matches?.("input.task-list-item-checkbox")) return false
        event.preventDefault()
        if (!view.editable) return true
        const body = box.parentElement.querySelector(".wb-task-body")
        const $pos = view.state.doc.resolve(view.posAtDOM(body, 0))
        for (let depth = $pos.depth; depth > 0; depth--) {
          const node = $pos.node(depth)
          if (node.type === nodes.list_item) {
            view.dispatch(
              view.state.tr.setNodeMarkup($pos.before(depth), null, {
                checked: !node.attrs.checked,
              }),
            )
            break
          }
        }
        return true
      },
    },
  },
})

// --- Mentions -------------------------------------------------------------

const MENTION = /\[@((?:[^\]\\]|\\.)*)\]\(person:(\d+)\) ?/g

// "[@Ada](person:12) " as nodes
function mentionNodes(markdown) {
  const out = []
  for (const m of markdown.matchAll(MENTION)) {
    out.push(
      nodes.mention.create({ id: m[2], label: m[1].replace(/\\(.)/g, "$1") }),
    )
    out.push(schema.text(" "))
  }
  return out
}

export function mentionIds(doc) {
  const ids = new Set()
  doc.descendants((node) => {
    if (node.type === nodes.mention) ids.add(String(node.attrs.id))
  })
  return ids
}

// Typing "@" lists people (frontend/mentions.js's list and endpoints);
// choosing inserts a mention node, a team one per member
export function mentions({ url, visible, anchor }) {
  let list = null
  const key = new PluginKey("mentions")
  return new Plugin({
    key,
    view(view) {
      list = mentionList({
        url,
        visible,
        anchor,
        owner: view.dom,
        position(start) {
          const box = anchor.parentElement.getBoundingClientRect()
          const at = view.coordsAtPos(start)
          return { top: at.bottom - box.top, left: at.left - box.left }
        },
        mentioned: () => mentionIds(view.state.doc),
        onPick(typed, markdown) {
          const { state } = view
          const to = state.selection.from
          if (typed.start > to) return
          const tr = state.tr.replaceWith(
            typed.start,
            to,
            Fragment.from(mentionNodes(markdown)),
          )
          view.dispatch(tr.scrollIntoView())
          view.focus()
        },
      })
      const blur = () => list.close()
      view.dom.addEventListener("blur", blur)
      return {
        update(view) {
          const { $from, empty } = view.state.selection
          if (!empty || !view.hasFocus() || $from.parent.type.spec.code) {
            list.update(null)
            return
          }
          const before = $from.parent.textBetween(
            0,
            $from.parentOffset,
            null,
            OBJECT,
          )
          const typed = mentionQuery(before)
          list.update(
            typed && { query: typed.query, start: $from.start() + typed.start },
          )
        },
        destroy() {
          view.dom.removeEventListener("blur", blur)
          list.close()
        },
      }
    },
    props: {
      // Before the editor's own keys (and the form's): Enter and the arrows
      // pick, Escape closes
      handleDOMEvents: {
        keydown: (_view, event) => list?.keydown(event) || false,
      },
    },
  })
}

// --- Pasting --------------------------------------------------------------

// Plain text: a blank line starts a paragraph, a line break is a break
// (our Markdown's), not parsed as Markdown; in code as it is
export function clipboardTextParser(text, $context) {
  text = text.replace(/\r\n?/g, "\n")
  if ($context.parent.type.spec.code)
    return new Slice(Fragment.from(schema.text(text)), 0, 0)
  const paragraphs = text.split(/\n{2,}/).map((block) => {
    const content = []
    block.split("\n").forEach((line, i) => {
      if (i) content.push(nodes.hard_break.create())
      if (line) content.push(schema.text(line))
    })
    return nodes.paragraph.create(null, content)
  })
  return new Slice(Fragment.from(paragraphs), 1, 1)
}

// The Markdown's content as a slice to insert (one paragraph: inline)
export function markdownSlice(markdown) {
  const doc = parse(markdown)
  if (doc.childCount === 1 && doc.firstChild.type === nodes.paragraph)
    return new Slice(doc.firstChild.content, 0, 0)
  return new Slice(doc.content, 0, 0)
}

// Files are attachments (``upload``), a URL over selected text makes a
// link, rich text goes through the server's converter (/paste/markdown/,
// specs/editor.md) and is parsed; the editor's own copies paste as
// themselves; Ctrl+Shift+V pastes plain text
export function pasting({ upload }) {
  return new Plugin({
    props: {
      handleDOMEvents: {
        // Dropped files are attachments, where they were dropped
        drop(view, event) {
          if (!event.dataTransfer?.files.length || !view.editable) return false
          event.preventDefault()
          let at = null
          try {
            at = view.posAtCoords({ x: event.clientX, y: event.clientY })
          } catch {
            // Not over the text (a drop without coordinates): the caret's
          }
          if (at)
            view.dispatch(
              view.state.tr.setSelection(
                Selection.near(view.state.doc.resolve(at.pos)),
              ),
            )
          upload(event.dataTransfer.files)
          return true
        },
      },
      handlePaste(view, event) {
        const data = event.clipboardData
        if (!data) return false
        if (data.files?.length) return upload(data.files)
        const { state } = view
        const { from, to, empty } = state.selection
        const text = data.getData("text/plain").trim()
        if (!empty && URL_ONLY.test(text)) {
          view.dispatch(
            state.tr.addMark(from, to, marks.link.create({ href: text })),
          )
          return true
        }
        const html = data.getData("text/html")
        // Plain text pasting (Ctrl+Shift+V) and plain text: ProseMirror's
        // own (clipboardTextParser); the editor's own copies too
        if (view.input?.shiftKey || !html || /data-pm-slice/.test(html))
          return false
        if (!MARKUP.test(html)) {
          // HTML without formatting (code from an editor: a div per line)
          const slice = clipboardTextParser(
            data.getData("text/plain"),
            state.selection.$from,
          )
          view.dispatch(state.tr.replaceSelection(slice).scrollIntoView())
          return true
        }
        if ($inCode(state)) return false
        const url = pasteUrl()
        if (!url) return false
        const fallback = data.getData("text/plain")
        const before = state.doc
        toMarkdown(url, html)
          .catch(() => null)
          .then((markdown) => {
            if (view.isDestroyed) return
            const slice =
              markdown === null
                ? clipboardTextParser(fallback, view.state.selection.$from)
                : markdownSlice(markdown)
            if (!slice.content.size) return
            // Where the person pasted, unless the text changed meanwhile
            const tr = view.state.tr
            if (view.state.doc.eq(before)) tr.replaceRange(from, to, slice)
            else tr.replaceSelection(slice)
            view.dispatch(tr.scrollIntoView())
          })
        return true
      },
    },
  })
}

const $inCode = (state) => state.selection.$from.parent.type.spec.code
