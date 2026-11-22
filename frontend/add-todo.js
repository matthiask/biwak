// Adding to-dos inline (items/_add_todo.html, specs/todos.md): the form
// opens in place, saves without leaving the page and stays open for the
// next one. Ctrl+Enter (or Cmd+Enter) saves, Escape or a click elsewhere
// closes; what was typed stays until it's saved.

// Every form on the page, also those live updates bring (frontend/live.js)
const forms = () => document.querySelectorAll("[data-add-todo]")

function close(details, { focus = false } = {}) {
  if (!details.open) return
  details.open = false
  if (focus) details.querySelector("summary").focus()
}

const isText = (response) =>
  response.headers.get("Content-Type")?.startsWith("text/plain")

function showFailure(error) {
  error.textContent = error.dataset.offline || "Not saved, please try again."
  error.hidden = false
}

async function submit(form) {
  if (!form.reportValidity()) return
  const error = form.querySelector("[data-add-todo-error]")
  const button = form.querySelector("[type=submit]")
  button.disabled = true
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Biwak-Fragment": "1" },
    })
    // Only the new row is a 201. A 200 is a login page after a redirect, a
    // 403 or 500 an error page: none of them belongs into the list or the
    // error line, only the form's own 422 says what is wrong
    if (response.status === 422 && isText(response)) {
      error.textContent = await response.text()
      error.hidden = false
      return
    }
    if (response.status !== 201) {
      showFailure(error)
      return
    }
    // The new to-do at the end of its group, like the server puts it
    const todos = form.closest(".wb-group").querySelector("[data-todos]")
    todos.insertAdjacentHTML("beforeend", await response.text())
    // htmx doesn't watch the page for new elements
    window.htmx?.process(todos.lastElementChild)
    error.hidden = true
    form.reset()
    form.querySelector("[name=title]").focus()
  } catch {
    showFailure(error)
  } finally {
    button.disabled = false
  }
}

const ready = new WeakSet()

function setUp(details) {
  if (ready.has(details)) return
  ready.add(details)
  const form = details.querySelector("[data-add-todo-form]")

  details.addEventListener("toggle", () => {
    if (!details.open) return
    // One open at a time
    for (const other of forms()) if (other !== details) close(other)
    form.querySelector("[name=title]").focus()
  })

  form.addEventListener("submit", (event) => {
    event.preventDefault()
    submit(form)
  })

  form.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      submit(form)
    } else if (event.key === "Escape") {
      event.preventDefault()
      close(details, { focus: true })
    }
  })

  form
    .querySelector("[data-add-todo-close]")
    .addEventListener("click", () => close(details, { focus: true }))
}

for (const details of forms()) setUp(details)
document.addEventListener("biwak:live", (event) => {
  const node = event.detail
  for (const details of [
    ...(node.matches("[data-add-todo]") ? [node] : []),
    ...node.querySelectorAll("[data-add-todo]"),
  ])
    setUp(details)
})

// The event's path, not the target's place now: a click that removed its
// own target (a pill's ×) still happened inside the form
document.addEventListener("click", (event) => {
  const path = event.composedPath()
  for (const details of forms()) {
    if (details.open && !path.includes(details)) close(details)
  }
})
