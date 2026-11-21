// The theme toggle, from Governance:
// auto -> light -> dark -> auto. The choice belongs to the person
// (User.theme, <html data-theme-mode>, saved by POST so that it follows them
// to other devices); the browser's localStorage only serves pages without
// a person (the login). The inline script in base.html sets the theme before
// the page renders.
import { send } from "./http.js"

const root = document.documentElement
const person = () => root.dataset.themeMode !== undefined

const storage = {
  get() {
    try {
      return window.localStorage.getItem("theme")
    } catch {
      return null
    }
  },
  set(theme) {
    try {
      if (theme === "auto") window.localStorage.removeItem("theme")
      else window.localStorage.setItem("theme", theme)
    } catch {
      // Private mode: the theme only lasts for this page
    }
  },
}

const getSystemTheme = () =>
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
const getThemeMode = () =>
  person() ? root.dataset.themeMode : storage.get() || "auto"

const setTheme = (mode) => {
  const active = mode === "auto" ? getSystemTheme() : mode
  root.setAttribute("data-bs-theme", active)
  for (const button of document.querySelectorAll("[data-theme-toggle]")) {
    for (const icon of button.querySelectorAll("[data-theme-icon]"))
      icon.hidden = icon.dataset.themeIcon !== mode
    // The titles come translated from the template
    button.setAttribute(
      "title",
      button.dataset[`title${mode[0].toUpperCase()}${mode.slice(1)}`],
    )
  }
}

// Also for the palette's action
export function cycleTheme() {
  const next = { auto: "light", light: "dark", dark: "auto" }[getThemeMode()]
  if (person()) {
    root.dataset.themeMode = next
    send(
      "/accounts/settings/appearance/",
      { theme: next },
      { "X-Biwak-Fragment": "1" },
    ).catch(() => {})
  } else {
    storage.set(next)
  }
  setTheme(next)
}

setTheme(getThemeMode())

document.body.addEventListener("click", (event) => {
  if (event.target.closest("[data-theme-toggle]")) {
    event.preventDefault()
    cycleTheme()
  }
})

// System changes only matter in auto mode
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => {
    if (getThemeMode() === "auto") setTheme("auto")
  })
