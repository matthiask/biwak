// Tables in the rich editor (specs/rich-editor.md, "Tables"): "Insert
// table" (a 2×2 table with a header row), the bar of the table the cursor
// is in (rows, columns, deleting, the column's alignment) and the shape
// Markdown can hold: the first row is the header, the others aren't, and
// every cell of a column has the column's alignment (the header's), so
// what's saved is one alignment per column.
import { Plugin, TextSelection } from "prosemirror-state"
import {
  addColumnAfter,
  addColumnBefore,
  addRowAfter,
  addRowBefore,
  deleteColumn,
  deleteRow,
  deleteTable,
  isInTable,
  selectedRect,
} from "prosemirror-tables"
import { schema } from "./schema.js"

const { nodes } = schema

function cell(type, text = "") {
  return type.create(
    null,
    nodes.paragraph.create(null, text ? schema.text(text) : null),
  )
}

// A 2×2 table with a header row, the cursor in its first cell
export function insertTable(state, dispatch) {
  if (isInTable(state) || state.selection.$from.parent.type.spec.code)
    return false
  if (dispatch) {
    const table = nodes.table.create(null, [
      nodes.table_row.create(null, [
        cell(nodes.table_header),
        cell(nodes.table_header),
      ]),
      nodes.table_row.create(null, [
        cell(nodes.table_cell),
        cell(nodes.table_cell),
      ]),
    ])
    const tr = state.tr.replaceSelectionWith(table)
    // The first cell of the table just inserted: the last one starting
    // before the selection, which is in it or follows it
    let found = null
    tr.doc.nodesBetween(0, tr.selection.from, (node, pos) => {
      if (node.type !== nodes.table) return !node.isTextblock
      if (pos < tr.selection.from) found = pos + 4
      return false
    })
    if (found !== null) tr.setSelection(TextSelection.create(tr.doc, found))
    dispatch(tr.scrollIntoView())
  }
  return true
}

// The row and column of the cell with the cursor, and the table's size
function where(state) {
  if (!isInTable(state)) return null
  const rect = selectedRect(state)
  return {
    rect,
    row: rect.top,
    column: rect.left,
    rows: rect.map.height,
    columns: rect.map.width,
    align: rect.table.child(0).child(rect.left)?.attrs.align ?? null,
  }
}

function setAlign(value) {
  return (state, dispatch) => {
    const at = where(state)
    if (!at) return false
    if (dispatch) {
      const align = at.align === value ? null : value
      const tr = state.tr
      at.rect.table.forEach((row, rowOffset) => {
        let offset = 0
        row.forEach((_child, cellOffset, index) => {
          if (index === at.column) offset = cellOffset
        })
        const pos = at.rect.tableStart + rowOffset + 1 + offset
        const node = tr.doc.nodeAt(pos)
        if (node) tr.setNodeMarkup(pos, null, { ...node.attrs, align })
      })
      dispatch(tr)
    }
    return true
  }
}

const inBody = (state) => (where(state)?.row ?? 0) > 0

// The bar's actions: [command, whether it applies here]
export const TABLE_ACTIONS = {
  "row-above": [addRowBefore, inBody],
  "row-below": [addRowAfter, () => true],
  "column-left": [addColumnBefore, () => true],
  "column-right": [addColumnAfter, () => true],
  // Markdown tables need their header row
  "delete-row": [deleteRow, inBody],
  // The last column takes the table with it
  "delete-column": [
    (state, dispatch) =>
      where(state)?.columns === 1
        ? deleteTable(state, dispatch)
        : deleteColumn(state, dispatch),
    () => true,
  ],
  "delete-table": [deleteTable, () => true],
  "align-left": [setAlign("left"), () => true],
  "align-center": [setAlign("center"), () => true],
  "align-right": [setAlign("right"), () => true],
}

// The shape Markdown can hold, after every change
export const tableShape = new Plugin({
  appendTransaction(transactions, _old, state) {
    if (!transactions.some((tr) => tr.docChanged)) return null
    const tr = state.tr
    state.doc.descendants((table, tablePos) => {
      if (table.type !== nodes.table) return !table.isTextblock
      const header = table.child(0)
      const aligns = []
      header.forEach((c) => {
        aligns.push(c.attrs.align)
      })
      table.forEach((row, rowOffset, rowIndex) => {
        row.forEach((c, cellOffset, index) => {
          const type = rowIndex === 0 ? nodes.table_header : nodes.table_cell
          const align = aligns[index] ?? null
          if (c.type !== type || c.attrs.align !== align)
            tr.setNodeMarkup(tablePos + 1 + rowOffset + 1 + cellOffset, type, {
              ...c.attrs,
              align,
            })
        })
      })
      return false
    })
    return tr.docChanged ? tr : null
  },
})

const template = () =>
  document.querySelector("template[data-table-bar-template]")

// The bar, after ``after`` (the editor's element, or what follows it
// right away) in the page, so that Tab from the table reaches it; placed
// above the table, inside ``anchor``'s parent (the editor's)
export function tableBar({ anchor, after = anchor }) {
  return new Plugin({
    view(view) {
      const source = template()
      if (!source) return {}
      const bar = document.createElement("div")
      bar.className = "wb-table-bar"
      bar.setAttribute("role", "toolbar")
      bar.setAttribute("aria-label", source.dataset.label || "Table")
      bar.append(source.content.cloneNode(true))
      bar.hidden = true
      after.after(bar)
      anchor.parentElement.classList.add("position-relative")
      const buttons = [...bar.querySelectorAll("[data-table-action]")]
      buttons.forEach((button, index) => {
        button.tabIndex = index === 0 ? 0 : -1
      })

      const show = () => {
        const inBar = bar.contains(document.activeElement)
        const at = where(view.state)
        if (!at || !view.editable || !(view.hasFocus() || inBar)) {
          if (inBar && !at) view.focus()
          bar.hidden = true
          return
        }
        for (const button of buttons) {
          const [, applies] = TABLE_ACTIONS[button.dataset.tableAction]
          button.setAttribute("aria-disabled", String(!applies(view.state)))
          if (button.hasAttribute("aria-pressed"))
            button.setAttribute(
              "aria-pressed",
              String(button.dataset.tableAction === `align-${at.align}`),
            )
        }
        bar.hidden = false
        // Above the table, at its left edge
        const dom = view.nodeDOM(at.rect.tableStart - 1)
        const table =
          dom?.nodeName === "TABLE" ? dom : dom?.querySelector?.("table")
        if (!table) return
        const box = anchor.parentElement.getBoundingClientRect()
        const rect = table.getBoundingClientRect()
        bar.style.left = `${Math.max(0, rect.left - box.left)}px`
        bar.style.top = `${Math.max(0, rect.top - box.top - bar.offsetHeight - 2)}px`
      }

      // Clicking keeps the editor's focus and selection
      bar.addEventListener("mousedown", (event) => {
        if (event.target.closest("button")) event.preventDefault()
      })
      bar.addEventListener("click", (event) => {
        const button = event.target.closest("[data-table-action]")
        if (!button || button.getAttribute("aria-disabled") === "true") return
        const [command] = TABLE_ACTIONS[button.dataset.tableAction]
        command(view.state, view.dispatch)
        if (!bar.contains(document.activeElement)) view.focus()
        show()
      })
      bar.addEventListener("keydown", (event) => {
        const index = buttons.indexOf(document.activeElement)
        if (event.key === "Escape") {
          event.preventDefault()
          event.stopPropagation()
          view.focus()
          return
        }
        let next = null
        if (event.key === "ArrowRight") next = index + 1
        else if (event.key === "ArrowLeft") next = index - 1
        else if (event.key === "Home") next = 0
        else if (event.key === "End") next = buttons.length - 1
        if (next === null || index < 0) return
        event.preventDefault()
        const target = buttons[(next + buttons.length) % buttons.length]
        for (const button of buttons)
          button.tabIndex = button === target ? 0 : -1
        target.focus()
      })
      const later = () => setTimeout(show)
      bar.addEventListener("focusout", later)
      view.dom.addEventListener("blur", later)
      view.dom.addEventListener("focus", later)
      return {
        update: show,
        destroy() {
          view.dom.removeEventListener("blur", later)
          view.dom.removeEventListener("focus", later)
          bar.remove()
        },
      }
    },
  })
}
