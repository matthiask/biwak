// Keeping the live editor's unsent changes in the browser (Yjs's IndexedDB
// storage, specs/connection.md): closing the tab, a crash or a restart while
// offline loses nothing, the changes are merged when the doc is opened
// again. This is the one place which knows about the storage.
//
// - Opening a doc reads what's stored (if anything) into the doc; the
//   provider sends it like any change.
// - While connected and synced we ask the server (MESSAGE_HAVE, at most once
//   a second) for its state vector. The stored copy goes once that covers
//   the doc's own; what it lacks is sent again meanwhile.
// - Going offline starts keeping the doc again.
// - The database is per person, doc and *history* of the server's state
//   (``history``, biwak/collab/live.py): a copy typed in another history
//   (the server's state was made again) would duplicate the text, it's
//   deleted instead of merged.
import * as decoding from "lib0/decoding"
import * as encoding from "lib0/encoding"
import { IndexeddbPersistence } from "y-indexeddb"
import * as syncProtocol from "y-protocols/sync"
import * as Y from "yjs"

import { leaving, PREFIX } from "./stored-docs.js"

// biwak/collab/consumers.py
export const MESSAGE_HAVE = 101
const MESSAGE_SYNC = 0
// How often we ask whether the server has it (ms)
const ASK_EVERY = 1000

function deleteDatabase(name) {
  return new Promise((resolve) => {
    const request = indexedDB.deleteDatabase(name)
    request.onsuccess = request.onerror = request.onblocked = resolve
  })
}

// Copies of this person and doc from other histories
async function forgetOtherHistories(own, scope) {
  try {
    const databases = (await indexedDB.databases?.()) || []
    await Promise.all(
      databases
        .filter((db) => db.name?.startsWith(scope) && db.name !== own)
        .map((db) => deleteDatabase(db.name)),
    )
  } catch {
    // No storage, nothing to forget
  }
}

// The server's clocks: {client ID: clock}
function readClocks(decoder) {
  const clocks = new Map()
  for (let n = decoding.readVarUint(decoder); n > 0; n--) {
    clocks.set(decoding.readVarUint(decoder), decoding.readVarUint(decoder))
  }
  return clocks
}

function covers(clocks, ydoc) {
  for (const [client, clock] of Y.decodeStateVector(
    Y.encodeStateVector(ydoc),
  )) {
    if ((clocks.get(client) || 0) < clock) return false
  }
  return true
}

function stateVector(clocks) {
  const encoder = encoding.createEncoder()
  encoding.writeVarUint(encoder, clocks.size)
  for (const [client, clock] of clocks) {
    encoding.writeVarUint(encoder, client)
    encoding.writeVarUint(encoder, clock)
  }
  return encoding.toUint8Array(encoder)
}

export function keepInBrowser(ydoc, provider, user, doc, history) {
  const scope = `${PREFIX}${user}-${doc}-`
  const name = `${scope}${history}`
  let persistence = null
  let timer = null
  let started = false

  const keep = async () => {
    clearTimeout(timer)
    if (persistence || started || leaving.now) return
    started = true
    await forgetOtherHistories(name, scope)
    if (!started) return
    persistence = new IndexeddbPersistence(name, ydoc)
    // Connected already: is it on the server?
    follow()
  }

  const release = async () => {
    const old = persistence
    persistence = null
    started = false
    try {
      await old?.clearData()
    } catch {
      // Gone already
    }
  }

  const ask = () => {
    clearTimeout(timer)
    if (!persistence || !provider.wsconnected || !provider.synced) return
    provider.ws.send(Uint8Array.of(MESSAGE_HAVE))
    timer = setTimeout(ask, ASK_EVERY)
  }

  provider.messageHandlers[MESSAGE_HAVE] = (_encoder, decoder) => {
    const clocks = readClocks(decoder)
    if (covers(clocks, ydoc)) {
      clearTimeout(timer)
      release()
      return
    }
    // The server lacks something we have (an update lost on the way): once
    // more, and ask again
    if (!provider.wsconnected) return
    const encoder = encoding.createEncoder()
    encoding.writeVarUint(encoder, MESSAGE_SYNC)
    syncProtocol.writeUpdate(
      encoder,
      Y.encodeStateAsUpdate(ydoc, stateVector(clocks)),
    )
    provider.ws.send(encoding.toUint8Array(encoder))
  }

  function follow() {
    if (provider.wsconnected && provider.synced) ask()
    else keep()
  }

  // What's stored comes in first
  keep()
  provider.on("sync", follow)
  provider.on("status", follow)
  return {
    get persistence() {
      return persistence
    },
  }
}
