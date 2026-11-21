// The live editor keeps unsent changes in the browser (specs/connection.md,
// frontend/collab.js): one IndexedDB database per person and doc. Logging
// out removes them all, so that the next person on this browser finds
// nothing.

export const PREFIX = "biwak-doc-"

export async function clearStoredDocs() {
  try {
    const databases = (await indexedDB.databases?.()) || []
    await Promise.all(
      databases
        .filter((db) => db.name?.startsWith(PREFIX))
        .map(
          (db) =>
            new Promise((resolve) => {
              const request = indexedDB.deleteDatabase(db.name)
              request.onsuccess = request.onerror = request.onblocked = resolve
            }),
        ),
    )
  } catch {
    // No storage, nothing to remove
  }
}

// The logout form clears first, then logs out
document.addEventListener("submit", async (event) => {
  const form = event.target
  if (event.defaultPrevented || !form.matches?.('form[action$="/logout/"]'))
    return
  event.preventDefault()
  await Promise.race([
    clearStoredDocs(),
    new Promise((resolve) => setTimeout(resolve, 2000)),
  ])
  form.submit()
})
