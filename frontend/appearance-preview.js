// The settings page applies the chosen theme and accent color at once; the
// form saves itself meanwhile (frontend/save-on-change.js), and when that
// fails the stored choice comes back, applied again.
import { setTheme } from "./theme.js"

const form = document.querySelector("[data-appearance-preview]")
const root = document.documentElement

const chosen = (name) =>
  form.querySelector(`input[name="${name}"]:checked`)?.value

const preview = () => {
  const theme = chosen("theme")
  const accent = chosen("accent")
  if (theme) {
    root.dataset.themeMode = theme
    setTheme(theme)
  }
  if (accent) root.dataset.accent = accent
}

form.addEventListener("change", preview)
// A failed save restores the stored choice without a change event
form.addEventListener("wb:restored", preview)
