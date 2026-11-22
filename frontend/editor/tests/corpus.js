// The texts both serializers are tested on (biwak/richtext/corpus/, made
// up: our shapes, the help, the paste converter's and importer's output)
import fs from "node:fs"
import path from "node:path"

export const CORPUS = path.join(
  import.meta.dirname,
  "../../../biwak/richtext/corpus",
)

export function corpus() {
  const out = []
  for (const dir of fs.readdirSync(CORPUS).sort())
    for (const f of fs.readdirSync(path.join(CORPUS, dir)).sort())
      out.push([
        `${dir}/${f}`,
        fs.readFileSync(path.join(CORPUS, dir, f), "utf8"),
      ])
  return out
}
