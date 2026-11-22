// Filter forms apply themselves (specs/ui.md, "Filters and view choices"): a form with
// data-autosubmit (GET only) submits when a select, checkbox or radio
// changes and, after a short pause, when a text field does (Enter submits as
// always). The button stays for people without JavaScript (hidden by CSS
// under .js). The page reloads with the new query, without empty values;
// the focused field and the scroll position come back after the reload.
const PAUSE = 400
const KEY = "autosubmit"

// The field that made the form submit: the one the person changed, which
// has the focus unless a script (or a click on a select's option) changed it
let changed = null

function remember(form) {
  const field = changed || document.activeElement
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
  const element = field instanceof RadioNodeList ? field[0] : field
  if (!element) return
  element.focus({ preventScroll: true })
  if (element.setSelectionRange && element.type === "text") {
    const end = element.value.length
    element.setSelectionRange(end, end)
  }
}

// The query without empty values (like Workbench's): an empty choice is
// the page's default, and the URL stays short
export function query(form, submitter) {
  const params = new URLSearchParams()
  for (const [name, value] of new FormData(form, submitter)) {
    if (typeof value === "string" && value) params.append(name, value)
  }
  return params.toString()
}

document.addEventListener("submit", (event) => {
  const form = event.target
  if (!form.matches?.("[data-autosubmit]")) return
  remember(form)
  // The attributes, not form.method and form.action: a field named
  // "action" (the activity's filter) hides the property
  if ((form.getAttribute("method") || "get").toLowerCase() !== "get") return
  event.preventDefault()
  const url = new URL(form.getAttribute("action") || "", location.href)
  url.search = query(form, event.submitter)
  location.assign(url)
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
  changed = field
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
    setTimeout(() => {
      changed = field
      form.requestSubmit()
    }, PAUSE),
  )
})

restore()
