// Pasting plain text that is clearly Markdown (specs/rich-editor.md): the
// detection, with both kinds of examples
import assert from "node:assert/strict"
import { test } from "node:test"
import { isMarkdown } from "../detect.js"

const MARKDOWN = {
  heading: "# Packing list\n\nTents and stoves.",
  "a lower heading": "Intro\n\n## Details\nmore",
  list: "- tent\n- stove\n- rope",
  "a numbered list": "1. pack\n2. drive",
  "a task list": "- [ ] tent\n- [x] stove",
  "a fenced block": "Run this:\n\n```\nmake test\n```",
  "a fenced block with comments": "```python\n# set up\nx = 1\n```",
  table: "| Day | Place |\n| --- | :---: |\n| Mon | Hut |",
  "a table without outer pipes": "a | b\n--- | ---\n1 | 2",
  link: "See [the plan](https://example.org/plan) first.",
}

const TEXT = {
  "a sentence": "Just a sentence.",
  "emphasis characters": "This is *really* important and __urgent__.",
  "code with # comments":
    "# set up the tent\nx = pitch(tent)\n# then the stove\nlight(stove)",
  "a shell script": "#!/bin/sh\n# clean up\nrm -rf build",
  "a Python function": "def pack(items):\n    # one each\n    return items",
  "a mail with a dash line": "Hi Ada,\n\nsee you on Monday.\n\n-- \nBob",
  "a mail with a single star line": "Hi,\n* the tent is ordered\nThanks, Bob",
  "a path with underscores": "/home/ada/camp_plan/final_v2.md",
  "snake case names": "set max_items and min_items",
  "a URL": "https://example.org/a_b?c=1",
  "a single item": "- just one thing",
  "a hashtag": "#camp is trending",
  "brackets without a URL": "[x] done and [y](not a url)",
}

test("clear Markdown is Markdown", () => {
  for (const [name, text] of Object.entries(MARKDOWN))
    assert.equal(isMarkdown(text), true, name)
})

test("everything else stays text", () => {
  for (const [name, text] of Object.entries(TEXT))
    assert.equal(isMarkdown(text), false, name)
})
