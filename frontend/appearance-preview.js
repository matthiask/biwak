// The settings page applies the chosen theme and accent color at once; only
// saving stores them. The next page renders the stored choice anyway.
import { setTheme } from "./theme.js"

const form = document.querySelector("[data-appearance-preview]")
const reset = form.querySelector("[data-appearance-reset]")
const root = document.documentElement

const stored = (name) =>
  form.querySelector(`input[name="${name}"][checked]`)?.value
const chosen = (name) =>
  form.querySelector(`input[name="${name}"]:checked`)?.value

const apply = (theme, accent) => {
  if (theme) {
    root.dataset.themeMode = theme
    setTheme(theme)
  }
  if (accent) root.dataset.accent = accent
}

const preview = () => {
  apply(chosen("theme"), chosen("accent"))
  reset.hidden =
    chosen("theme") === stored("theme") && chosen("accent") === stored("accent")
}

form.addEventListener("change", preview)

reset.addEventListener("click", () => {
  for (const name of ["theme", "accent"])
    for (const input of form.querySelectorAll(`input[name="${name}"]`))
      input.checked = input.defaultChecked
  preview()
})
