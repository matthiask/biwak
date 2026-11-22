// The table tools on the document (specs/rich-editor.md, "Tables"): what's
// saved is one alignment per column and one header row
import assert from "node:assert/strict"
import { test } from "node:test"
import { EditorState, TextSelection } from "prosemirror-state"
import { tableEditing } from "prosemirror-tables"
import { parse, serialize } from "../markdown.js"
import { insertTable, TABLE_ACTIONS, tableShape } from "../tables.js"

function state(markdown, text) {
  const doc = parse(markdown)
  let pos = 1
  if (text)
    doc.descendants((node, at) => {
      if (node.isText && node.text.includes(text) && pos === 1)
        pos = at + node.text.indexOf(text)
    })
  return EditorState.create({
    doc,
    selection: TextSelection.create(doc, pos),
    plugins: [tableEditing(), tableShape],
  })
}

function run(st, action) {
  let next = st
  const [command] = TABLE_ACTIONS[action]
  assert.ok(
    command(st, (tr) => (next = st.apply(tr))),
    action,
  )
  return next
}

const TABLE = "| a | b |\n| --- | --- |\n| 1 | 2 |"

test("inserting a table", () => {
  let st = state("Intro")
  insertTable(st, (tr) => (st = st.apply(tr)))
  assert.match(
    serialize(st.doc),
    /\| {2}\| {2}\|\n\| --- \| --- \|\n\| {2}\| {2}\|/,
  )
  // The cursor in the first cell
  assert.equal(st.selection.$from.parent.type.name, "paragraph")
  assert.equal(st.selection.$from.node(-1).type.name, "table_header")
})

test("rows and columns", () => {
  let st = run(state(TABLE, "1"), "row-below")
  assert.equal(
    serialize(st.doc),
    "| a | b |\n| --- | --- |\n| 1 | 2 |\n|  |  |",
  )
  st = run(state(TABLE, "1"), "row-above")
  assert.equal(
    serialize(st.doc),
    "| a | b |\n| --- | --- |\n|  |  |\n| 1 | 2 |",
  )
  st = run(state(TABLE, "a"), "column-right")
  assert.equal(
    serialize(st.doc),
    "| a |  | b |\n| --- | --- | --- |\n| 1 |  | 2 |",
  )
  st = run(state(TABLE, "1"), "delete-row")
  assert.equal(serialize(st.doc), "| a | b |\n| --- | --- |")
})

test("the header row stays", () => {
  const st = state(TABLE, "a")
  const [, applies] = TABLE_ACTIONS["delete-row"]
  assert.equal(applies(st), false)
  assert.equal(TABLE_ACTIONS["row-above"][1](st), false)
  assert.equal(applies(state(TABLE, "1")), true)
})

test("the last column deletes the table", () => {
  let st = run(state("Before\n\n| a |\n| --- |\n| 1 |", "1"), "delete-column")
  assert.equal(serialize(st.doc), "Before")
  st = run(state(TABLE, "2"), "delete-column")
  assert.equal(serialize(st.doc), "| a |\n| --- |\n| 1 |")
})

test("alignment is the column's", () => {
  let st = run(state(TABLE, "2"), "align-right")
  assert.equal(serialize(st.doc), "| a | b |\n| --- | ---: |\n| 1 | 2 |")
  st = run(st, "align-center")
  assert.equal(serialize(st.doc), "| a | b |\n| --- | :---: |\n| 1 | 2 |")
  // Pressed again: none
  st = run(st, "align-center")
  assert.equal(serialize(st.doc), TABLE)
  // New rows take the column's
  st = run(run(state(TABLE, "a"), "align-left"), "row-below")
  // Every cell of the first column (the new row's too)
  st.doc.firstChild.forEach((row) => {
    assert.equal(row.child(0).attrs.align, "left")
    assert.equal(row.child(1).attrs.align, null)
  })
  assert.equal(
    serialize(st.doc),
    "| a | b |\n| :--- | --- |\n|  |  |\n| 1 | 2 |",
  )
})
