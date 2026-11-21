// Filter forms apply themselves (specs/ui-round-3.md): a form with
// data-autosubmit (GET only) submits when a select, checkbox or radio
// changes and, after a short pause, when a text field does (Enter submits as
// always). The button stays for people without JavaScript (hidden by CSS
// under .js). The page reloads with the new query; the focused field and the
// scroll position come back after the reload.
const PAUSE = 400
const KEY = "autosubmit"

function remember(form) {
  const field = document.activeElement
  try {
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        path: location.pathname,
        form: [...document.querySelectorAll("[data-autosubmit]")].indexOf(form),
        name: field && form.contains(field) ? field.name : "",
        y: window.scrollY,
      }),
    )
  } catch {
    // No storage: the page still reloads, without the focus
  }
}

function restore() {
  let saved
  try {
    saved = JSON.parse(sessionStorage.getItem(KEY))
    sessionStorage.removeItem(KEY)
  } catch {
    return
  }
  if (!saved || saved.path !== location.pathname) return
  window.scrollTo(0, saved.y)
  const form = document.querySelectorAll("[data-autosubmit]")[saved.form]
  const field = saved.name && form?.elements[saved.name]
  const element = field?.length ? field[0] : field
  if (!element) return
  element.focus({ preventScroll: true })
  if (element.setSelectionRange && element.type === "text") {
    const end = element.value.length
    element.setSelectionRange(end, end)
  }
}

document.addEventListener("submit", (event) => {
  if (event.target.matches?.("[data-autosubmit]")) remember(event.target)
})

document.addEventListener("change", (event) => {
  const field = event.target
  const form = field.form
  if (
    !form?.matches("[data-autosubmit]") ||
    field.matches("[data-no-autosubmit]")
  )
    return
  if (field.matches("input[type=text], input[type=search], input:not([type])"))
    return
  form.requestSubmit()
})

const timers = new WeakMap()
document.addEventListener("input", (event) => {
  const field = event.target
  const form = field.form
  if (
    !form?.matches("[data-autosubmit]") ||
    field.matches("[data-no-autosubmit]")
  )
    return
  if (!field.matches("input[type=text], input[type=search], input:not([type])"))
    return
  clearTimeout(timers.get(form))
  timers.set(
    form,
    setTimeout(() => form.requestSubmit(), PAUSE),
  )
})

restore()
