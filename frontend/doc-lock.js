// Editing a doc holds its lock (specs/files.md): the form with
// [data-doc-lock] renews it every minute; it expires after five minutes
// without renewal. Another person editing answers 409, nothing else to do
// here: saving shows who is editing.

import { csrfToken } from "./http.js"

const RENEW_EVERY = 60 * 1000

for (const form of document.querySelectorAll("[data-doc-lock]")) {
  setInterval(() => {
    fetch(form.dataset.docLock, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
    }).catch(() => {})
  }, RENEW_EVERY)
}
