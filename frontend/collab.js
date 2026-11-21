// Docs edited live (specs/collaboration.md): the Markdown in CodeMirror,
// shared through Yjs with the server's websocket (biwak/collab/), the
// others' cursors and names (awareness). The server says whether we may
// type (our message MODE) and closes with 4404 when the doc isn't ours to
// see anymore. Offline, typing goes on, kept in the browser (collab-store.js);
// Yjs merges it on reconnect.

import { defaultKeymap, indentWithTab } from "@codemirror/commands"
import { markdownLanguage } from "@codemirror/lang-markdown"
import {
  defaultHighlightStyle,
  LanguageSupport,
  syntaxHighlighting,
} from "@codemirror/language"
import { Compartment, EditorState } from "@codemirror/state"
import { drawSelection, EditorView, keymap } from "@codemirror/view"
import * as decoding from "lib0/decoding"
import { yCollab, yUndoManagerKeymap } from "y-codemirror.next"
import { WebsocketProvider } from "y-websocket"
import * as Y from "yjs"
import { keepInBrowser } from "./collab-store.js"
import { report } from "./connection.js"
import { csrfToken } from "./http.js"

// biwak/collab/consumers.py
const MESSAGE_MODE = 100
const CLOSE_NOT_FOUND = 4404

function setUp(container) {
  const texts = container.dataset
  const status = container.querySelector("[data-collab-status]")
  const people = container.querySelector("[data-collab-people]")
  const ydoc = new Y.Doc()
  const ytext = ydoc.getText("content")
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const [base, room] = container.dataset.collab
    .match(/^(.*)\/([^/]+)$/)
    .slice(1)
  const provider = new WebsocketProvider(
    `${scheme}//${location.host}${base}`,
    room,
    ydoc,
    // Other tabs go through the server too, which decides what they get
    { disableBc: true },
  )
  keepInBrowser(ydoc, provider, texts.collabUser, room)
  // The server puts in the name and color
  provider.awareness.setLocalStateField("user", {})

  let mayType = false
  let synced = false
  let gone = false
  const editable = new Compartment()
  const editableNow = () => {
    // Before the first sync the editor is empty: typing would go before
    // the text
    const yes = mayType && synced && !gone
    return [EditorState.readOnly.of(!yes), EditorView.editable.of(yes)]
  }
  const view = new EditorView({
    parent: container.querySelector("[data-collab-editor]"),
    state: EditorState.create({
      doc: ytext.toString(),
      extensions: [
        drawSelection(),
        EditorView.lineWrapping,
        // Not markdown(): it brings HTML, CSS and JavaScript along
        new LanguageSupport(markdownLanguage),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        keymap.of([...yUndoManagerKeymap, ...defaultKeymap, indentWithTab]),
        editable.of(editableNow()),
        yCollab(ytext, provider.awareness),
        EditorView.contentAttributes.of({ "aria-label": document.title }),
      ],
    }),
  })
  container.collab = { provider, view, ydoc }

  const update = () => {
    view.dispatch({ effects: editable.reconfigure(editableNow()) })
    let text = texts.collabConnecting
    if (gone) text = texts.collabGone
    else if (synced && !mayType) text = texts.collabWatching
    else if (synced && provider.wsconnected) text = texts.collabConnected
    else if (synced) text = texts.collabOffline
    status.textContent = text
    report("collab", gone || provider.wsconnected)
    container.dataset.collabState = gone
      ? "gone"
      : !synced
        ? "connecting"
        : !mayType
          ? "watching"
          : provider.wsconnected
            ? "connected"
            : "offline"
  }

  provider.messageHandlers[MESSAGE_MODE] = (_encoder, decoder) => {
    mayType = decoding.readVarUint(decoder) === 1
    update()
  }
  provider.on("sync", (isSynced) => {
    if (isSynced) synced = true
    update()
  })
  provider.on("status", update)
  provider.on("closed", ({ code }) => {
    if (code !== CLOSE_NOT_FOUND) return
    gone = true
    provider.destroy()
    view.destroy()
    people.textContent = ""
    update()
  })

  provider.awareness.on("change", () => {
    if (gone) return
    const names = [...provider.awareness.getStates()]
      .filter(([client, state]) => client !== ydoc.clientID && state.user?.name)
      .map(([, state]) => state.user.name)
    people.textContent = names.length
      ? `${texts.collabHere} ${[...new Set(names)].join(", ")}`
      : ""
  })

  if (container.dataset.attachments) attachments(container, view)
}

// Attaching files (specs/files.md): dropping, pasting or the button
// uploads them and inserts the Markdown at the cursor
function attachments(container, view) {
  const {
    attachments: url,
    attachmentsMax,
    attachmentsTooLarge,
    attachmentsUploading,
    attachmentsFailed,
  } = container.dataset
  const error = document.createElement("div")
  error.className = "small text-danger"
  error.setAttribute("role", "alert")
  error.hidden = true
  container.append(error)
  const show = (message) => {
    error.textContent = message
    error.hidden = !message
  }

  async function upload(file) {
    if (attachmentsMax && file.size > Number(attachmentsMax)) {
      show(attachmentsTooLarge)
      return
    }
    show(`${attachmentsUploading} ${file.name}…`)
    const body = new FormData()
    body.append("file", file, file.name)
    try {
      const response = await fetch(url, {
        method: "POST",
        body,
        headers: { "X-CSRFToken": csrfToken() },
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail)
      const { from, to } = view.state.selection.main
      const before = view.state.sliceDoc(from - 1, from)
      const text = (before && !/\s/.test(before) ? " " : "") + data.markdown
      view.dispatch({
        changes: { from, to, insert: text },
        selection: { anchor: from + text.length },
      })
      show("")
    } catch (exc) {
      show(exc.message || attachmentsFailed)
    }
  }
  const uploadAll = (files) => {
    for (const file of files) upload(file)
  }

  const template = container.querySelector("template[data-attach-template]")
  if (template) {
    const button = template.content.firstElementChild.cloneNode(true)
    const input = document.createElement("input")
    input.type = "file"
    input.multiple = true
    input.hidden = true
    button.addEventListener("click", () => input.click())
    input.addEventListener("change", () => {
      uploadAll(input.files)
      input.value = ""
      view.focus()
    })
    const wrapper = document.createElement("div")
    wrapper.className = "wb-attach"
    wrapper.append(button, input)
    error.before(wrapper)
  }
  view.dom.addEventListener("drop", (event) => {
    if (
      !event.dataTransfer?.files.length ||
      !view.state.facet(EditorView.editable)
    )
      return
    event.preventDefault()
    const position = view.posAtCoords({ x: event.clientX, y: event.clientY })
    if (position != null) view.dispatch({ selection: { anchor: position } })
    uploadAll(event.dataTransfer.files)
  })
  view.dom.addEventListener("paste", (event) => {
    const files = event.clipboardData?.files
    if (!files?.length || !view.state.facet(EditorView.editable)) return
    event.preventDefault()
    uploadAll(files)
  })
}

for (const container of document.querySelectorAll("[data-collab]")) {
  setUp(container)
}
