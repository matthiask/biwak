// "Upload files" (files/upload_form.html, specs/ui-round-7.md, part 4b): the
// files chosen or dropped are listed with their names (editable, the
// extension kept) and sizes, removable; "Upload" sends them one after
// another to [data-upload] with the form's fields and the batch, a
// progress bar on each row, an error staying on its row while the others
// go on. When all went up, the page reloads (or the folder's page loads,
// from elsewhere); the tiles are there.
// Works in the modal and on the form's own page; the form isn't posted.
import { csrfToken } from "./http.js"

const files = new WeakMap()

const zoneOf = (el) => el.closest?.("[data-upload]")
const formOf = (zone) => zone.closest("form")

function size(bytes) {
  const units = ["B", "KB", "MB", "GB"]
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${unit ? value.toFixed(1) : value} ${units[unit]}`
}

function split(name) {
  const dot = name.lastIndexOf(".")
  return dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""]
}

function row(zone, file) {
  const [stem, extension] = split(file.name)
  const li = document.createElement("li")
  li.className = "wb-upload-row"
  const name = document.createElement("input")
  name.className = "form-control form-control-sm"
  name.value = stem
  name.setAttribute("aria-label", zone.dataset.uploadName)
  name.dataset.uploadTitle = ""
  const ext = document.createElement("span")
  ext.className = "wb-upload-ext"
  ext.textContent = extension
  const bytes = document.createElement("span")
  bytes.className = "wb-upload-size"
  bytes.textContent = size(file.size)
  const remove = document.createElement("button")
  remove.type = "button"
  remove.className = "btn btn-sm btn-quiet"
  remove.textContent = "×"
  remove.title = zone.dataset.uploadRemove
  remove.setAttribute(
    "aria-label",
    `${zone.dataset.uploadRemove}: ${file.name}`,
  )
  remove.dataset.uploadRemove = ""
  const progress = document.createElement("progress")
  progress.max = 100
  progress.value = 0
  progress.hidden = true
  const error = document.createElement("div")
  error.className = "wb-upload-error"
  error.dataset.uploadRowError = ""
  error.hidden = true
  li.append(name, ext, bytes, remove, progress, error)
  return li
}

// Adds files to the form's list (the input's, or dropped ones)
export function addFiles(zone, list) {
  const entries = files.get(zone) || []
  files.set(zone, entries)
  const ul = zone.querySelector("[data-upload-list]")
  for (const file of list) {
    const li = row(zone, file)
    entries.push({ file, li, extension: split(file.name)[1] })
    ul.append(li)
  }
  zone.querySelector("[data-upload-error]").hidden = true
}

function fail(entry, message) {
  const error = entry.li.querySelector("[data-upload-row-error]")
  error.textContent = message
  error.hidden = false
  entry.li.classList.add("is-failed")
  entry.li.querySelector("progress").hidden = true
}

function sendOne(zone, entry) {
  const form = formOf(zone)
  const data = new FormData(form)
  data.delete("files")
  data.set("file", entry.file)
  const stem = entry.li.querySelector("[data-upload-title]").value.trim()
  data.set("title", stem ? stem + entry.extension : "")
  const progress = entry.li.querySelector("progress")
  progress.hidden = false
  return new Promise((resolve) => {
    if (entry.file.size > Number(zone.dataset.uploadMax)) {
      fail(entry, zone.dataset.uploadTooBig)
      resolve(false)
      return
    }
    const request = new XMLHttpRequest()
    request.open("POST", zone.dataset.upload)
    request.setRequestHeader("X-CSRFToken", csrfToken())
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable)
        progress.value = Math.round((100 * event.loaded) / event.total)
    })
    request.addEventListener("load", () => {
      if (request.status === 201) {
        progress.value = 100
        entry.li.classList.add("is-done")
        entry.done = true
        resolve(true)
        return
      }
      let message = zone.dataset.uploadFailed
      try {
        message = JSON.parse(request.responseText).detail || message
      } catch {}
      fail(entry, message)
      resolve(false)
    })
    request.addEventListener("error", () => {
      fail(entry, zone.dataset.uploadFailed)
      resolve(false)
    })
    request.send(data)
  })
}

async function upload(zone) {
  const form = formOf(zone)
  const entries = (files.get(zone) || []).filter((entry) => !entry.done)
  if (!entries.length) {
    const error = zone.querySelector("[data-upload-error]")
    error.textContent = zone.dataset.uploadNone
    error.hidden = false
    return
  }
  const button = form.querySelector("button[type=submit]")
  button.disabled = true
  form.classList.add("is-uploading")
  let failed = 0
  for (const entry of entries) {
    entry.li.classList.remove("is-failed")
    entry.li.querySelector("[data-upload-row-error]").hidden = true
    if (!(await sendOne(zone, entry))) failed += 1
  }
  form.classList.remove("is-uploading")
  zone.dataset.uploaded = "true"
  if (!failed) {
    // The folder's page again, or the folder uploaded to
    if (document.querySelector("[data-tiles]")) window.location.reload()
    else window.location.href = zone.dataset.uploadDone
    return
  }
  // The failed ones stay to remove or try again; the others are done
  button.disabled = false
}

document.addEventListener("change", (event) => {
  const zone = zoneOf(event.target)
  if (!zone || event.target.type !== "file") return
  addFiles(zone, event.target.files)
  event.target.value = ""
})

document.addEventListener("click", (event) => {
  const remove = event.target.closest?.("[data-upload-remove]")
  const zone = remove && zoneOf(remove)
  if (!zone) return
  const li = remove.closest("li")
  files.set(
    zone,
    (files.get(zone) || []).filter((entry) => entry.li !== li),
  )
  li.remove()
})

// Before htmx, which would post the form to the dialog
document.addEventListener(
  "submit",
  (event) => {
    const zone = event.target.querySelector?.("[data-upload]")
    if (!zone) return
    event.preventDefault()
    event.stopPropagation()
    upload(zone)
  },
  true,
)

// More files dropped onto the form
document.addEventListener("dragover", (event) => {
  const form = event.target.closest?.("form")
  const zone = form?.querySelector("[data-upload]")
  if (!zone || !event.dataTransfer?.types.includes("Files")) return
  event.preventDefault()
  event.stopPropagation()
  event.dataTransfer.dropEffect = "copy"
})

document.addEventListener("drop", (event) => {
  const form = event.target.closest?.("form")
  const zone = form?.querySelector("[data-upload]")
  if (!zone || !event.dataTransfer?.files.length) return
  event.preventDefault()
  event.stopPropagation()
  addFiles(zone, event.dataTransfer.files)
})

// Closing the dialog after some went up: the folder as it is now
document.addEventListener(
  "close",
  (event) => {
    if (event.target.querySelector?.("[data-upload][data-uploaded]"))
      window.location.reload()
  },
  true,
)
