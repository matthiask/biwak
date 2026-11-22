// The Markdown layer on its own (node --test, biwak/richtext/test_js.py
// runs it): the corpus and random documents round-trip
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { test } from "node:test"
import { boxes, parse, serialize } from "../markdown.js"
import { corpus } from "./corpus.js"
import { comparable, randomDocs } from "./random.js"

test("the corpus serializes stably to the same document", () => {
  for (const [name, text] of corpus()) {
    const doc = parse(text)
    const out = serialize(doc)
    assert.ok(parse(out).eq(doc), `${name}: another document after saving`)
    assert.equal(serialize(parse(out)), out, `${name}: not stable`)
    assert.deepEqual(boxes(parse(out)), boxes(doc), name)
  }
})

test("texts in our style stay as they are", () => {
  for (const text of [
    "Hello *you* and **them**",
    "- one\n- two\n  - three",
    "1. one\n2. two",
    "- [ ] open\n- [x] done",
    "A line\nand a break",
    "See https://example.org and www.example.com",
    "Thanks [@Ada](person:12)",
    "[![plan.png](attachment:ab12)](https://example.org/big)",
    "| a | b |\n| --- | ---: |\n| 1 | 2 |",
    "```js\nlet a = 1\n```",
    "> quoted\n\n---\n\n# Title",
  ])
    assert.equal(serialize(parse(text)), text)
})

test("random documents parse back to themselves", () => {
  for (const [i, doc] of randomDocs(500).entries()) {
    const markdown = serialize(doc)
    const back = parse(markdown)
    assert.equal(
      comparable(back),
      comparable(doc),
      `document ${i}:\n${markdown}`,
    )
  }
})

test("the corpus folder is where the Python tests read it", () => {
  assert.ok(
    fs.existsSync(
      path.join(import.meta.dirname, "../../../biwak/richtext/corpus"),
    ),
  )
})
