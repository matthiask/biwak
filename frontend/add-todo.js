// Adding to-dos inline (items/_add_todo.html, specs/todos.md): the form
// opens in place, saves without leaving the page and stays open for the
// next one. Ctrl+Enter (or Cmd+Enter) saves, Escape or a click elsewhere
// closes; what was typed stays until it's saved.

const forms = document.querySelectorAll("[data-add-todo]")

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

// "Repeat": the end and the count only for rules that repeat (the rule
// widget shows its own parts, rule-widget.js)
function syncRepeat(form) {
  const value = form.querySelector("[data-rule-frequency]").value
  for (const element of form.querySelectorAll("[data-repeat-ends]"))
    element.hidden = !value
}

for (const details of forms) {
  const form = details.querySelector("[data-add-todo-form]")
  syncRepeat(form)
  form.addEventListener("change", () => syncRepeat(form))
  form.addEventListener("reset", () => setTimeout(() => syncRepeat(form)))

  details.addEventListener("toggle", () => {
    if (!details.open) return
    // One open at a time
    for (const other of forms) if (other !== details) close(other)
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

document.addEventListener("click", (event) => {
  for (const details of forms) {
    if (details.open && !details.contains(event.target)) close(details)
  }
})
