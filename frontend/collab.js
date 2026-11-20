// SPIKE: a doc edited together (specs/collaboration.md)
import { markdown } from "@codemirror/lang-markdown"
import { EditorState } from "@codemirror/state"
import { EditorView } from "@codemirror/view"
import { HocuspocusProvider } from "@hocuspocus/provider"
import { basicSetup } from "codemirror"
import { yCollab } from "y-codemirror.next"
import { WebsocketProvider } from "y-websocket"
import * as Y from "yjs"

for (const el of document.querySelectorAll("[data-collab]")) {
  const ydoc = new Y.Doc()
  const ytext = ydoc.getText("content")
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const provider = el.dataset.hocuspocus
    ? new HocuspocusProvider({
        url: el.dataset.hocuspocus,
        name: el.dataset.collab,
        document: ydoc,
      })
    : new WebsocketProvider(
        `${scheme}//${location.host}/ws/docs`,
        el.dataset.collab,
        ydoc,
        { disableBc: true },
      )
  provider.awareness.setLocalStateField("user", {
    name: el.dataset.name,
    color: "#3366cc",
  })
  const readOnly = el.dataset.readonly === "1"
  window.collab = { ydoc, provider }
  new EditorView({
    parent: el,
    state: EditorState.create({
      doc: ytext.toString(),
      extensions: [
        basicSetup,
        markdown(),
        EditorState.readOnly.of(readOnly),
        EditorView.editable.of(!readOnly),
        yCollab(ytext, provider.awareness),
      ],
    }),
  })
}
