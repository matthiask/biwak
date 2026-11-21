// The lantern's menu (specs/lantern.md): the number of unread notifications
// on its button, the menu's content fetched when it opens, its buttons
// (read, unread, bookmark) without leaving the page, and with the setting on a
// dot on the tab's icon. frontend/live.js says when something changed
// ("biwak:lantern"). Entries are links to where they apply; following one
// reads its item's notifications in the background (below). Without
// JavaScript the menu links to the page, and "Mark as read" reads.

import { csrfToken } from "./http.js"

const menu = document.querySelector("[data-lantern]")
const count = menu?.querySelector("[data-lantern-count]")
const button = menu?.querySelector("summary")
const lanternTitle = button?.title
const countText = menu?.dataset.lanternUnreadText || "unread"
const content = menu?.querySelector("[data-lantern-menu]")
const favicon = document.querySelector("link[rel=icon]")
const withFavicon = "lanternFavicon" in document.body.dataset
const original = favicon?.href
let dotted = null

// Something new arrived live: the dot pulses once (specs/celebrations.md)
function pulse() {
  count.classList.remove("is-pulsing")
  void count.offsetWidth
  count.classList.add("is-pulsing")
  count.addEventListener(
    "animationend",
    () => count.classList.remove("is-pulsing"),
    { once: true },
  )
}

async function updateCount(arriving = false) {
  try {
    const response = await fetch(menu.dataset.lanternCountUrl, {
      credentials: "same-origin",
    })
    if (!response.ok) return
    const { unread } = await response.json()
    // A dot, as on the tab's icon; the number for screen readers and in
    // the button's tooltip
    const text = unread ? `${unread > 99 ? "99+" : unread} ${countText}` : ""
    count.querySelector("[data-lantern-count-text]").textContent = text
    count.hidden = !unread
    const before = Number(menu.dataset.lanternUnread ?? unread)
    if (arriving && unread > before) pulse()
    button.title = unread ? `${lanternTitle}: ${text}` : lanternTitle
    menu.dataset.lanternUnread = String(unread)
    if (withFavicon) showDot(unread > 0)
  } catch {
    // Offline: the next change tries again
  }
}

function entries() {
  return new Set(
    [...content.querySelectorAll("[data-lantern-item]")].map(
      (el) => el.dataset.lanternItem + el.classList.contains("is-unread"),
    ),
  )
}

async function load(arriving = false) {
  try {
    const response = await fetch(menu.dataset.lantern, {
      credentials: "same-origin",
    })
    if (response.ok) {
      const before = entries()
      content.innerHTML = await response.text()
      // New entries slide in, only while the menu is open and something
      // arrives (not when it opens or a button changes it)
      if (arriving && menu.open && menu.dataset.lanternLoaded)
        for (const el of content.querySelectorAll("[data-lantern-item]"))
          if (
            !before.has(
              el.dataset.lanternItem + el.classList.contains("is-unread"),
            )
          )
            el.classList.add("is-new")
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
  // The same red as the dot on the lantern's button (--wb-lantern-dot)
  context.fillStyle =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--wb-lantern-dot")
      .trim() || "#e03131"
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
    updateCount(true)
    if (menu.open) load(true)
  })
  // Reading, marking as unread and bookmarking stay in the menu
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

// Following an entry (a link, so its address shows and it opens in a new
// tab) reads its item: a post in the background which survives leaving
// the page (keepalive), for a click and a middle click (decided
// 2026-11-21). The lantern's page has the entries too.
function readOnFollow(event) {
  if (event.type === "auxclick" && event.button !== 1) return
  if (event.type === "click" && event.button !== 0) return
  const link = event.target.closest?.("a[data-lantern-read]")
  if (!link) return
  fetch(link.dataset.lanternRead, {
    method: "POST",
    keepalive: true,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken(), "HX-Request": "true" },
  })
    .then(() => document.dispatchEvent(new CustomEvent("biwak:lantern")))
    .catch(() => {
      // Offline: it stays unread, "Mark as read" is there
    })
}
document.addEventListener("click", readOnFollow)
document.addEventListener("auxclick", readOnFollow)
