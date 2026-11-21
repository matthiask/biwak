// The theme toggle, from Governance:
// auto -> light -> dark -> auto, stored in localStorage. The inline script
// in base.html sets the theme before the page renders.
const getStoredTheme = () => window.localStorage.getItem("theme")
const setStoredTheme = (theme) => {
  if (theme === "auto") {
    window.localStorage.removeItem("theme")
  } else {
    window.localStorage.setItem("theme", theme)
  }
}
const getSystemTheme = () =>
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
const getThemeMode = () => getStoredTheme() || "auto"

const setTheme = (mode) => {
  const active = mode === "auto" ? getSystemTheme() : mode
  document.documentElement.setAttribute("data-bs-theme", active)
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

setTheme(getThemeMode())

document.body.addEventListener("click", (event) => {
  if (event.target.closest("[data-theme-toggle]")) {
    event.preventDefault()
    const next = { auto: "light", light: "dark", dark: "auto" }[getThemeMode()]
    setStoredTheme(next)
    setTheme(next)
  }
})

// System changes only matter in auto mode
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => {
    if (getThemeMode() === "auto") setTheme("auto")
  })
