// The lantern's menu (specs/lantern.md): the number of unread notifications
// on its button, the menu's content fetched when it opens, its buttons
// (read, unread, pin) without leaving the page, and with the setting on a
// dot on the tab's icon. frontend/live.js says when something changed
// ("biwak:lantern"). Without JavaScript the menu links to the page.

import { csrfToken } from "./http.js"

const menu = document.querySelector("[data-lantern]")
const count = menu?.querySelector("[data-lantern-count]")
const content = menu?.querySelector("[data-lantern-menu]")
const favicon = document.querySelector("link[rel=icon]")
const withFavicon = "lanternFavicon" in document.body.dataset
const original = favicon?.href
let dotted = null

async function updateCount() {
  try {
    const response = await fetch(menu.dataset.lanternCountUrl, {
      credentials: "same-origin",
    })
    if (!response.ok) return
    const { unread } = await response.json()
    count.textContent = unread > 99 ? "99+" : String(unread)
    count.hidden = !unread
    menu.dataset.lanternUnread = String(unread)
    if (withFavicon) showDot(unread > 0)
  } catch {
    // Offline: the next change tries again
  }
}

async function load() {
  try {
    const response = await fetch(menu.dataset.lantern, {
      credentials: "same-origin",
    })
    if (response.ok) {
      content.innerHTML = await response.text()
      menu.dataset.lanternLoaded = String(Date.now())
    }
  } catch {
    // Offline: the link to the page stays
  }
}

// The normal icon with a dot, drawn once
async function dot() {
  if (dotted) return dotted
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = 64
  const context = canvas.getContext("2d")
  const image = new Image()
  image.src = original
  try {
    await image.decode()
    context.drawImage(image, 0, 0, 64, 64)
  } catch {
    // Without the icon (not loaded): the dot alone
  }
  context.beginPath()
  context.arc(48, 16, 14, 0, 2 * Math.PI)
  context.fillStyle = "#d63384"
  context.fill()
  dotted = canvas.toDataURL("image/png")
  return dotted
}

async function showDot(show) {
  if (!favicon) return
  try {
    favicon.href = show ? await dot() : original
    favicon.type = show ? "image/png" : "image/svg+xml"
    document.documentElement.dataset.lanternDot = show ? "1" : "0"
  } catch {
    favicon.href = original
  }
}

if (menu) {
  updateCount()
  menu.addEventListener("toggle", () => {
    if (menu.open) load()
  })
  document.addEventListener("biwak:lantern", () => {
    updateCount()
    if (menu.open) load()
  })
  // Reading, marking as unread and pinning stay in the menu
  content.addEventListener("submit", async (event) => {
    const form = event.target
    event.preventDefault()
    try {
      // The views answer 204 instead of redirecting
      await fetch(form.action, {
        method: "POST",
        body: new FormData(form, event.submitter),
        headers: { "X-CSRFToken": csrfToken(), "HX-Request": "true" },
      })
    } catch {
      form.submit()
      return
    }
    await Promise.all([load(), updateCount()])
  })
}
