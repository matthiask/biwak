// The command palette (specs/keyboard.md): Ctrl+K (Cmd+K) opens a dialog with
// a field and a list, the combobox and listbox pattern. With an empty field
// the actions of the page (which the server decided: base.html's JSON script),
// the person's bookmarks and the pages visited last; typing filters the
// actions here and asks the server for jumps (GET /palette/?q=, after a short
// pause, the latest answer wins), "Search for ..." is always last.
//
// Actions are run here, never decided: the palette only shows what the server
// rendered for this page.
import { send } from "./http.js"
import { cycleTheme } from "./theme.js"

const script = document.getElementById("wb-palette-data")
export const data = script ? JSON.parse(script.textContent) : null

let openFn = null
const DEBOUNCE = 150
const RECENT = "recent-pages"
const RECENT_LIMIT = 20

// What the person visited last in this browser: a convenience per browser,
// so localStorage is fine
function recentPages() {
  try {
    return JSON.parse(window.localStorage.getItem(RECENT)) || []
  } catch {
    return []
  }
}

function remember() {
  const url = window.location.pathname + window.location.search
  const title = document.title.replace(/ – Biwak$/, "")
  const pages = recentPages().filter((page) => page.url !== url)
  pages.unshift({ url, title })
  try {
    window.localStorage.setItem(
      RECENT,
      JSON.stringify(pages.slice(0, RECENT_LIMIT)),
    )
  } catch {
    // Private mode: nothing to remember
  }
}

// Opening what's inside a closed <details> (the inline form for a to-do) and
// focusing it
export function focusElement(element) {
  for (
    let details = element.closest("details");
    details;
    details = details.parentElement?.closest("details")
  )
    details.open = true
  element.scrollIntoView({ block: "center" })
  element.focus()
}

export function runAction(action, { status } = {}) {
  switch (action.type) {
    case "link":
      window.location.assign(action.url)
      break
    case "post":
      send(action.url, action.data).then(
        (response) => {
          if (!response.ok) return status?.(data.texts.failed)
          if (response.redirected) window.location.assign(response.url)
          else window.location.reload()
        },
        () => status?.(data.texts.failed),
      )
      break
    case "focus": {
      const element = document.querySelector(action.selector)
      if (element) focusElement(element)
      else if (action.url) window.location.assign(action.url)
      break
    }
    case "copy":
      navigator.clipboard.writeText(action.text).then(
        () => status?.(data.texts.copied),
        () => status?.(data.texts.failed),
      )
      break
    case "theme":
      cycleTheme()
      break
  }
}

// A page which opens at a field (#new-list) focuses it
function focusHash() {
  const id = decodeURIComponent(window.location.hash.slice(1))
  const element = id && document.getElementById(id)
  if (element?.matches("input, textarea, select")) focusElement(element)
}

const dialog = document.getElementById("wb-palette")
if (data && dialog) {
  const input = document.getElementById("wb-palette-input")
  const list = document.getElementById("wb-palette-list")
  const live = document.getElementById("wb-palette-status")
  let entries = []
  let active = -1
  let opener = null
  let bookmarks = []
  let jumps = []
  let request = 0
  let timer = null
  let controller = null

  const words = (text) => text.toLowerCase().split(/\s+/).filter(Boolean)
  const matches = (label, query) => {
    const text = label.toLowerCase()
    return words(query).every((word) => text.includes(word))
  }

  const say = (message) => {
    live.textContent = message
  }

  function entry(label, { hint = "", badge = "", run, group }) {
    return { label, hint, badge, run, group }
  }

  function actionEntry(action) {
    return entry(action.label, {
      hint: action.shortcut,
      group: data.texts.actions,
      run: () => runAction(action, { status: say }),
    })
  }

  function resultEntry(result, group) {
    return entry(result.title, {
      hint: [result.label, result.context].filter(Boolean).join(" · "),
      badge: result.archived
        ? data.texts.archived
        : result.visible_to_clients
          ? data.texts.clients
          : "",
      group,
      run: () => window.location.assign(result.url),
    })
  }

  function build() {
    const query = input.value.trim()
    const result = []
    if (query) {
      for (const action of data.actions)
        if (matches(action.label, query)) result.push(actionEntry(action))
      for (const jump of jumps) result.push(resultEntry(jump, data.texts.jumps))
      result.push(
        entry(data.texts.search_for.replace("%s", query), {
          group: "",
          run: () =>
            window.location.assign(
              `${data.search_url}?q=${encodeURIComponent(query)}`,
            ),
        }),
      )
    } else {
      for (const action of data.actions) result.push(actionEntry(action))
      for (const bookmark of bookmarks)
        result.push(resultEntry(bookmark, data.texts.bookmarks))
      const here = window.location.pathname + window.location.search
      for (const page of recentPages())
        if (page.url !== here)
          result.push(
            entry(page.title, {
              group: data.texts.recent,
              run: () => window.location.assign(page.url),
            }),
          )
    }
    return result
  }

  function render({ keep = false } = {}) {
    const before = keep ? entries[active]?.label : null
    entries = build()
    active = Math.max(
      0,
      before ? entries.findIndex((e) => e.label === before) : 0,
    )
    list.replaceChildren()
    let group = null
    entries.forEach((item, index) => {
      if (item.group && item.group !== group) {
        const heading = document.createElement("li")
        heading.setAttribute("role", "presentation")
        heading.className = "wb-palette-group"
        heading.textContent = item.group
        list.append(heading)
      }
      group = item.group
      const row = document.createElement("li")
      row.id = `wb-palette-option-${index}`
      row.setAttribute("role", "option")
      row.className = "wb-palette-option"
      const label = document.createElement("span")
      label.className = "wb-palette-label"
      label.textContent = item.label
      row.append(label)
      if (item.badge) {
        const badge = document.createElement("span")
        badge.className = "badge wb-tone-neutral"
        badge.textContent = item.badge
        row.append(badge)
      }
      if (item.hint) {
        const hint = document.createElement("span")
        hint.className = "wb-palette-hint"
        hint.textContent = item.hint
        row.append(hint)
      }
      row.addEventListener("click", () => choose(index))
      row.addEventListener("mousemove", () => {
        if (active !== index) mark(index, { scroll: false })
      })
      list.append(row)
    })
    mark(active)
  }

  function mark(index, { scroll = true } = {}) {
    active = index
    list.querySelectorAll("[role=option]").forEach((row, i) => {
      row.setAttribute("aria-selected", String(i === index))
      row.classList.toggle("is-active", i === index)
    })
    const row = document.getElementById(`wb-palette-option-${index}`)
    if (row) {
      input.setAttribute("aria-activedescendant", row.id)
      if (scroll) row.scrollIntoView({ block: "nearest" })
    } else {
      input.removeAttribute("aria-activedescendant")
    }
  }

  function choose(index) {
    const item = entries[index]
    if (!item) return
    close()
    item.run()
  }

  function close() {
    if (dialog.open) dialog.close()
  }

  async function load(query) {
    controller?.abort()
    controller = new AbortController()
    const mine = ++request
    try {
      const response = await fetch(
        `${data.jumps_url}?q=${encodeURIComponent(query)}`,
        { signal: controller.signal, headers: { Accept: "application/json" } },
      )
      if (!response.ok || mine !== request) return
      const answer = await response.json()
      if (mine !== request) return
      if (query) jumps = answer.results
      else bookmarks = answer.bookmarks
      render({ keep: true })
      say(`${entries.length}`)
    } catch {
      // Aborted or offline: what is shown stays
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer)
    const query = input.value.trim()
    if (!query) jumps = []
    render()
    timer = setTimeout(() => load(query), query ? DEBOUNCE : 0)
  })

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      const step = event.key === "ArrowDown" ? 1 : -1
      if (entries.length)
        mark((active + step + entries.length) % entries.length)
    } else if (event.key === "Enter") {
      event.preventDefault()
      choose(active)
    }
  })

  // A click on the backdrop closes
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close()
  })

  dialog.addEventListener("close", () => {
    request++
    clearTimeout(timer)
    controller?.abort()
    opener?.focus?.()
  })

  function open() {
    if (dialog.open) return
    opener = document.activeElement
    input.value = ""
    jumps = []
    dialog.showModal()
    render()
    load("")
    input.focus()
  }

  openFn = open
  remember()
  focusHash()

  // Ctrl+K (Cmd+K on a Mac) always opens, also while typing and with the
  // shortcuts turned off
  document.addEventListener("keydown", (event) => {
    if (
      (event.ctrlKey || event.metaKey) &&
      !event.altKey &&
      event.key.toLowerCase() === "k"
    ) {
      event.preventDefault()
      if (dialog.open) close()
      else open()
    }
  })
}

export function openPalette() {
  openFn?.()
}

// Dialogs with a close button and a click on the backdrop
document.addEventListener("click", (event) => {
  const dialogEl = event.target.closest?.("dialog.wb-dialog")
  if (event.target.closest?.("[data-close-dialog]")) dialogEl?.close()
  else if (event.target.matches?.("dialog.wb-dialog")) event.target.close()
})
