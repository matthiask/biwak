// What the JavaScript side makes of the corpus and of random documents, as
// JSON for the Python side to compare (biwak/richtext/test_parity.py):
//
//   node frontend/editor/tests/dump.js           the corpus and random docs
//   node frontend/editor/tests/dump.js load DIR  Y documents Python made
//                                                (DIR/*.bin) read through
//                                                y-prosemirror, serialized
import fs from "node:fs"
import path from "node:path"
import { prosemirrorToYDoc, yXmlFragmentToProsemirror } from "y-prosemirror"
import * as Y from "yjs"
import { FRAGMENT } from "../live-schema.js"
import { boxes, parse, serialize } from "../markdown.js"
import { schema } from "../schema.js"
import { corpus } from "./corpus.js"
import { randomDocs } from "./random.js"

const base64 = (bytes) => Buffer.from(bytes).toString("base64")
const ydoc = (doc) => Y.encodeStateAsUpdate(prosemirrorToYDoc(doc, FRAGMENT))
const fromY = (ydoc) =>
  yXmlFragmentToProsemirror(schema, ydoc.getXmlFragment(FRAGMENT))

const [mode, dir] = process.argv.slice(2)
if (mode === "load") {
  const out = {}
  for (const name of fs.readdirSync(dir).sort()) {
    const doc = new Y.Doc()
    Y.applyUpdate(doc, fs.readFileSync(path.join(dir, name)))
    const pm = fromY(doc)
    pm.check()
    out[name] = { doc: pm.toJSON(), markdown: serialize(pm) }
  }
  process.stdout.write(JSON.stringify(out))
} else {
  const count = Number(mode || 300)
  process.stdout.write(
    JSON.stringify({
      corpus: corpus().map(([name, text]) => {
        const doc = parse(text)
        const y = ydoc(doc)
        const back = new Y.Doc()
        Y.applyUpdate(back, y)
        return {
          name,
          doc: doc.toJSON(),
          markdown: serialize(doc),
          boxes: boxes(doc),
          y: base64(y),
          // y-prosemirror drops marks on inline nodes (a bold mention)
          ymarkdown: serialize(fromY(back)),
        }
      }),
      random: randomDocs(count, 7).map((doc) => ({
        markdown: serialize(doc),
        // (a list can need a blank line it didn't have: loose then)
        again: serialize(parse(serialize(doc))),
        y: base64(ydoc(doc)),
      })),
    }),
  )
}
