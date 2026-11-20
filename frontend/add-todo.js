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
    if (!response.ok) {
      error.textContent = await response.text()
      error.hidden = false
      return
    }
    // The new to-do at the end of its group, like the server puts it
    const todos = form.closest(".wb-group").querySelector("[data-todos]")
    todos.insertAdjacentHTML("beforeend", await response.text())
    error.hidden = true
    const group = form.querySelector("[name=group]")?.value
    form.reset()
    if (group) form.querySelector("[name=group]").value = group
    form.querySelector("[name=title]").focus()
  } catch {
    error.textContent = error.dataset.offline || "Not saved, please try again."
    error.hidden = false
  } finally {
    button.disabled = false
  }
}

// "Repeat": the custom rule, the end and the count only when they matter
function syncRepeat(form) {
  const value = form.querySelector("[data-repeat-select]").value
  form.querySelector("[data-repeat-custom]").hidden = value !== "custom"
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
