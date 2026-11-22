// Whether pasted plain text is clearly Markdown (specs/rich-editor.md,
// "Pasting plain text that is clearly Markdown"): only unmistakable
// structure counts, a heading line, a list of several items, a fenced
// code block, a table, `[text](url)` links. Emphasis characters, single
// `-` or `*` lines (a mail's), `_` in paths and code with `#` comments
// stay text. No imports: tested on its own (tests/detect.test.js).

const HEADING = /^#{1,6}[ \t]+\S/
const ITEM = /^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\S/
const FENCE = /^[ \t]{0,3}(`{3,}|~{3,})/
const DELIMITER =
  /^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$/
const LINK = /\[[^\]\n]+\]\((?:https?:\/\/|mailto:|\/)[^)\s]*\)/
// What code looks like (where `#` starts comments)
const CODE = [
  /[;{}][ \t]*$/,
  /^[ \t]*(?:def|class|import|from|return|if|for|while|function|const|let|var|elif|else:)\b/,
  /^#!|^#include|^#define|^#\[/,
  /\b\w+\([^)]*\)\s*(?::|=>|\{)?\s*$/,
  /^[ \t]*[\w.]+\s*[-+*/]?=\s*\S/,
]

function looksLikeCode(lines) {
  return lines.some(
    (line) => !HEADING.test(line) && CODE.some((re) => re.test(line)),
  )
}

function fenced(lines) {
  const open = lines.findIndex((line) => FENCE.test(line))
  if (open < 0) return false
  const marker = FENCE.exec(lines[open])[1]
  return lines
    .slice(open + 1)
    .some((line) => line.trim().startsWith(marker[0].repeat(marker.length)))
}

function list(lines) {
  for (let i = 0; i + 1 < lines.length; i++)
    if (ITEM.test(lines[i]) && ITEM.test(lines[i + 1])) return true
  return false
}

function table(lines) {
  for (let i = 0; i + 1 < lines.length; i++)
    if (
      lines[i].includes("|") &&
      DELIMITER.test(lines[i + 1]) &&
      /\|/.test(lines[i + 1] + lines[i])
    )
      return true
  return false
}

export function isMarkdown(text) {
  const lines = (text || "").replace(/\r\n?/g, "\n").split("\n")
  if (fenced(lines) || table(lines) || LINK.test(text)) return true
  if (looksLikeCode(lines)) return false
  return lines.some((line) => HEADING.test(line)) || list(lines)
}
