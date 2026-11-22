// People away (specs/quiet-hours.md): assigning or mentioning someone away
// shows their note once in the form ("Ada is away until 3 Dec: back on
// the 4th"), below the field it happened in. The texts come from the
// server (data-away-note on the picker's options, away_note in the @
// list's JSON). They can still be assigned and mentioned.

const shown = new WeakMap()

export function awayNote(anchor, id, text) {
  if (!text || !anchor?.isConnected) return
  const scope = anchor.closest("form, dialog") || document.body
  let seen = shown.get(scope)
  if (!seen) {
    seen = new Set()
    shown.set(scope, seen)
  }
  if (seen.has(String(id))) return
  seen.add(String(id))
  // Below the field: the last of its parent's children, so that the
  // field's own siblings (the rich editor and its textarea) stay as they are
  const parent = anchor.parentElement
  let notes = [...parent.children].find((child) =>
    child.classList.contains("wb-away-notes"),
  )
  if (!notes) {
    notes = document.createElement("div")
    notes.className = "wb-away-notes form-text"
    notes.setAttribute("role", "status")
    parent.append(notes)
  }
  const note = document.createElement("div")
  note.className = "wb-away-note"
  note.textContent = text
  notes.append(note)
}
