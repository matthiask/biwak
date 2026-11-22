// Docs edited live (specs/collaboration.md, specs/rich-editor.md): the rich
// editor (frontend/editor/live.js) on the doc's Yjs document, shared with the
// server's websocket (biwak/collab/), the others' cursors and names
// (awareness). The server says whether we may type (our message MODE) and
// closes with 4404 when the doc isn't ours to see anymore. Offline, typing
// goes on, kept in the browser (collab-store.js); Yjs merges it on
// reconnect.

import * as decoding from "lib0/decoding"
import { WebsocketProvider } from "y-websocket"
import * as Y from "yjs"
import { avatar } from "./avatar.js"
import { keepInBrowser } from "./collab-store.js"
import { report } from "./connection.js"
import { liveEditor } from "./editor/live.js"
import { csrfToken } from "./http.js"
import { attachToEditor } from "./toolbar.js"

// biwak/collab/consumers.py
const MESSAGE_MODE = 100
const CLOSE_NOT_FOUND = 4404

function setUp(container) {
  const texts = container.dataset
  const status = container.querySelector("[data-collab-status]")
  const people = container.querySelector("[data-collab-people]")
  const ydoc = new Y.Doc()
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
  keepInBrowser(ydoc, provider, texts.collabUser, room, texts.collabHistory)
  // The server puts in the name and color
  provider.awareness.setLocalStateField("user", {})

  let mayType = false
  let synced = false
  let gone = false
  // Before the first sync the editor is empty: typing would go before the
  // text
  const editable = () => mayType && synced && !gone
  const editorElement = container.querySelector("[data-collab-editor]")
  let upload = null
  const editor = liveEditor(editorElement, {
    ydoc,
    awareness: provider.awareness,
    mayType: editable,
    upload: (files) => {
      if (!upload) return false
      upload(files)
      return true
    },
    mentionsUrl: container.dataset.mentions,
    label: document.title,
    attachmentUrl: document.querySelector("template[data-toolbar-template]")
      ?.dataset.attachmentUrl,
  })
  container.collab = { provider, editor, ydoc }
  // The same toolbar as above every Markdown field (toolbar.js), shown
  // while one may type
  const toolbar = attachToEditor(
    editor,
    editorElement,
    container.dataset.mentions,
  )
  const bar = toolbar && editorElement.previousElementSibling

  const update = () => {
    editor.refresh()
    if (bar) bar.hidden = !editable()
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
    if (synced) startDraft()
  }
  provider.on("sync", (isSynced) => {
    if (isSynced) synced = true
    update()
    if (isSynced) startDraft()
  })

  // A new doc (specs/files.md, "Docs"): the cursor after its "# ",
  // the title is typed first; once there's text the doc exists and its
  // address replaces the draft's ("New doc") in the history
  let draft = container.dataset.collabDraft
  let started = false
  const startDraft = () => {
    if (!draft || started || !mayType) return
    started = true
    editor.focusEnd()
  }
  const fragment = ydoc.getXmlFragment("prosemirror")
  const written = () => {
    if (!draft || !editor.text().trim()) return
    history.replaceState(history.state, "", draft)
    draft = null
    fragment.unobserveDeep(written)
  }
  fragment.observeDeep(written)
  provider.on("status", update)
  provider.on("closed", ({ code }) => {
    if (code !== CLOSE_NOT_FOUND) return
    gone = true
    provider.destroy()
    editor.destroy()
    people.textContent = ""
    update()
  })

  provider.awareness.on("change", () => {
    if (gone) return
    const others = new Map()
    for (const [client, state] of provider.awareness.getStates())
      if (client !== ydoc.clientID && state.user?.name)
        others.set(state.user.name, state.user.avatar)
    people.replaceChildren(
      ...(others.size ? [`${texts.collabHere} `] : []),
      ...[...others].flatMap(([name, person], index) => [
        index ? ", " : "",
        avatar(person),
        ` ${name}`,
      ]),
    )
  })

  if (container.dataset.attachments)
    upload = attachments(container, editor, editable)
}

// Attaching files (specs/files.md): dropping, pasting or the button
// uploads them and inserts the Markdown at the cursor; returns the upload
function attachments(container, editor, editable) {
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
      if (editable()) editor.insertMarkdown(data.markdown)
      show("")
    } catch (exc) {
      show(exc.message || attachmentsFailed)
    }
  }
  const uploadAll = (files) => {
    if (!editable()) return
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
      editor.view.focus()
    })
    const wrapper = document.createElement("div")
    wrapper.className = "wb-attach"
    wrapper.append(button, input)
    error.before(wrapper)
  }
  return uploadAll
}

for (const container of document.querySelectorAll("[data-collab]")) {
  setUp(container)
}
