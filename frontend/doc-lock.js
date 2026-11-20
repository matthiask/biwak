// Editing a doc holds its lock (specs/files.md): the form with
// [data-doc-lock] renews it every minute; it expires after five minutes
// without renewal. Another person editing answers 409, nothing else to do
// here: saving shows who is editing.

const RENEW_EVERY = 60 * 1000

for (const form of document.querySelectorAll("[data-doc-lock]")) {
  const token = form.querySelector("[name=csrfmiddlewaretoken]")?.value || ""
  setInterval(() => {
    fetch(form.dataset.docLock, {
      method: "POST",
      headers: { "X-CSRFToken": token },
    }).catch(() => {})
  }, RENEW_EVERY)
}
