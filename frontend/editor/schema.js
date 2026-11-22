// The editor's schema: what render_markdown renders, no more
// (specs/rich-editor.md). Attributes named `markup` remember how the source
// wrote something (bullet, emphasis delimiter, fence...), so that an edited
// text changes less of what wasn't edited. The Python side has the same
// shape (biwak/richtext/tree.py): change both together.
//
// The DOM is what the page renders (`.wb-markdown`): task items with their
// box, mentions as `.wb-mention`, attachments' images by their URL.
import { Schema } from "prosemirror-model"
import { tableNodes } from "prosemirror-tables"

const table = tableNodes({
  tableGroup: "block",
  cellContent: "paragraph",
  cellAttributes: {
    align: {
      default: null,
      getFromDOM: (dom) => dom.style.textAlign || null,
      setDOMAttr: (value, attrs) => {
        if (value) attrs.style = `text-align:${value}`
      },
    },
  },
})

// ``attachment:KEY`` shown through the download URL (biwak/files/views.py
// ignores the name); the template says where (`data-attachment-url`)
let attachmentUrl = "/attachments/KEY/image"
export function setAttachmentUrl(url) {
  if (url) attachmentUrl = url
}
export function imageSource(src) {
  const match = /^attachment:([\w-]+)$/.exec(src || "")
  return match ? attachmentUrl.replace("KEY", match[1]) : src
}

const markup = { markup: { default: null } }

export const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: {
      content: "inline*",
      group: "block",
      parseDOM: [{ tag: "p" }],
      toDOM: () => ["p", 0],
    },
    heading: {
      attrs: { level: { default: 1 }, ...markup },
      content: "inline*",
      group: "block",
      defining: true,
      parseDOM: [1, 2, 3, 4, 5, 6].map((level) => ({
        tag: `h${level}`,
        attrs: { level },
      })),
      toDOM: (node) => [`h${node.attrs.level}`, 0],
    },
    blockquote: {
      content: "block+",
      group: "block",
      defining: true,
      parseDOM: [{ tag: "blockquote" }],
      toDOM: () => ["blockquote", 0],
    },
    code_block: {
      attrs: { params: { default: "" }, ...markup },
      content: "text*",
      marks: "",
      group: "block",
      code: true,
      defining: true,
      parseDOM: [{ tag: "pre", preserveWhitespace: "full" }],
      toDOM: () => ["pre", ["code", 0]],
    },
    horizontal_rule: {
      attrs: markup,
      group: "block",
      parseDOM: [{ tag: "hr" }],
      toDOM: () => ["hr"],
    },
    bullet_list: {
      attrs: { tight: { default: true }, ...markup },
      content: "list_item+",
      group: "block",
      parseDOM: [{ tag: "ul" }],
      toDOM: (node) => [
        "ul",
        { class: tasks(node) ? "contains-task-list" : null },
        0,
      ],
    },
    ordered_list: {
      attrs: { order: { default: 1 }, tight: { default: true }, ...markup },
      content: "list_item+",
      group: "block",
      parseDOM: [
        {
          tag: "ol",
          getAttrs: (dom) => ({ order: +(dom.getAttribute("start") || 1) }),
        },
      ],
      toDOM: (node) => [
        "ol",
        {
          start: node.attrs.order === 1 ? null : node.attrs.order,
          class: tasks(node) ? "contains-task-list" : null,
        },
        0,
      ],
    },
    list_item: {
      // checked: null (no box), false, true: GitHub's task lists
      attrs: { checked: { default: null } },
      content: "paragraph block*",
      defining: true,
      parseDOM: [
        {
          tag: "li",
          getAttrs: (dom) => {
            const box = dom.querySelector(":scope > input[type=checkbox]")
            return { checked: box ? box.checked : null }
          },
        },
      ],
      toDOM: (node) =>
        node.attrs.checked === null
          ? ["li", 0]
          : [
              "li",
              { class: "task-list-item", "data-checked": node.attrs.checked },
              [
                "input",
                {
                  class: "task-list-item-checkbox",
                  type: "checkbox",
                  contenteditable: "false",
                  tabindex: "-1",
                  ...(node.attrs.checked ? { checked: "" } : {}),
                },
              ],
              ["div", { class: "wb-task-body" }, 0],
            ],
    },
    ...table,
    text: { group: "inline" },
    image: {
      inline: true,
      // href: the link around the image (y-prosemirror drops marks on
      // inline nodes, so it's an attribute; specs/rich-editor.md)
      attrs: {
        src: {},
        alt: { default: null },
        title: { default: null },
        href: { default: null },
        hrefTitle: { default: null },
      },
      group: "inline",
      draggable: true,
      parseDOM: [
        {
          tag: "img[src]",
          getAttrs: (dom) => ({
            src: dom.dataset.src || dom.getAttribute("src"),
            alt: dom.getAttribute("alt") || null,
            title: dom.getAttribute("title") || null,
            href: dom.dataset.href || null,
          }),
        },
      ],
      toDOM: (node) => [
        "img",
        {
          class: "wb-attachment-image",
          src: imageSource(node.attrs.src),
          "data-src": node.attrs.src,
          "data-href": node.attrs.href,
          alt: node.attrs.alt,
          title: node.attrs.title,
        },
      ],
    },
    mention: {
      // [@Ada](person:12)
      inline: true,
      atom: true,
      attrs: { id: {}, label: { default: "" } },
      group: "inline",
      parseDOM: [
        {
          tag: "span[data-mention]",
          getAttrs: (dom) => ({
            id: dom.dataset.mention,
            label: dom.textContent.replace(/^@/, ""),
          }),
        },
      ],
      toDOM: (node) => [
        "span",
        { class: "wb-mention", "data-mention": node.attrs.id },
        `@${node.attrs.label}`,
      ],
    },
    hard_break: {
      inline: true,
      group: "inline",
      selectable: false,
      parseDOM: [{ tag: "br" }],
      toDOM: () => ["br"],
    },
  },
  marks: {
    em: {
      attrs: markup,
      parseDOM: [{ tag: "em" }, { tag: "i" }],
      toDOM: () => ["em", 0],
    },
    strong: {
      attrs: markup,
      parseDOM: [{ tag: "strong" }, { tag: "b" }],
      toDOM: () => ["strong", 0],
    },
    strikethrough: {
      parseDOM: [{ tag: "s" }, { tag: "del" }],
      toDOM: () => ["s", 0],
    },
    link: {
      attrs: {
        href: {},
        title: { default: null },
        // "linkify" (a bare URL), "autolink" (<https://...>) or null
        ...markup,
      },
      inclusive: false,
      parseDOM: [
        {
          tag: "a[href]",
          getAttrs: (dom) => ({
            href: dom.getAttribute("href"),
            title: dom.getAttribute("title"),
          }),
        },
      ],
      toDOM: (mark) => [
        "a",
        { href: mark.attrs.href, title: mark.attrs.title },
        0,
      ],
    },
    code: { parseDOM: [{ tag: "code" }], toDOM: () => ["code", 0] },
  },
})

function tasks(list) {
  let any = false
  list.forEach((item) => {
    if (item.attrs.checked !== null) any = true
  })
  return any
}
