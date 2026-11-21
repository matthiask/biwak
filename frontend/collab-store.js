// Keeping the live editor's unsent changes in the browser (Yjs's IndexedDB
// storage, specs/connection.md): closing the tab, a crash or a restart while
// offline loses nothing, the changes are merged when the doc is opened
// again. This is the one place which knows about the storage.
//
// - Opening a doc reads what's stored (if anything) into the doc; the
//   provider sends it like any change.
// - Once the server has it (connected, synced), the stored copy goes.
// - Going offline starts keeping the doc again.
//
// ``name`` is per person and doc, so people sharing a browser don't mix.
import { IndexeddbPersistence } from "y-indexeddb"

import { PREFIX } from "./stored-docs.js"

// Time the server gets to take over what we send after a sync (ms)
const SETTLE = 1000

export function keepInBrowser(ydoc, provider, user, doc) {
  const name = `${PREFIX}${user}-${doc}`
  let persistence = null
  let timer = null

  const keep = () => {
    clearTimeout(timer)
    if (!persistence) persistence = new IndexeddbPersistence(name, ydoc)
  }
  const release = () => {
    clearTimeout(timer)
    timer = setTimeout(async () => {
      if (!provider.wsconnected || !provider.synced || !persistence) return
      const old = persistence
      persistence = null
      try {
        await old.clearData()
      } catch {
        // Gone already
      }
    }, SETTLE)
  }
  const follow = () =>
    provider.wsconnected && provider.synced ? release() : keep()

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
