// Completing a to-do, a little celebrated (specs/celebrations.md): the
// check pops, the title is struck through, the row fades and collapses;
// the last open to-do of a list bursts into dots and the list says
// "All done.". CSS does the moving (frontend/styles/main.css), this only
// toggles classes. The request goes out at once and the page follows when
// both the answer and the animation are there (the server never waits for
// the animation). With reduced motion nothing here runs: the form is
// submitted as it is.

import { csrfToken } from "./http.js"

const reduced = matchMedia("(prefers-reduced-motion: reduce)")
// Animations that don't run (a hidden tab, a row not shown) end anyway
const FALLBACK = 2000

// Resolves when ``element``'s own animation ``name`` ends
function ended(element, name) {
  return new Promise((resolve) => {
    const done = () => {
      element.removeEventListener("animationend", onEnd)
      clearTimeout(timer)
      resolve()
    }
    const onEnd = (event) => {
      if (event.target === element && event.animationName === name) done()
    }
    const timer = setTimeout(done, FALLBACK)
    element.addEventListener("animationend", onEnd)
  })
}

function openRows(container, except) {
  return [...container.querySelectorAll(".wb-todo")].filter(
    (row) => row !== except && !row.querySelector(".wb-check.is-done"),
  )
}

async function send(form) {
  const response = await fetch(form.action, {
    method: "POST",
    body: new FormData(form),
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken() },
  })
  if (!response.ok) throw new Error(String(response.status))
  return response.url
}

// The page after the action: where the form's redirect led
function follow(url) {
  if (url === location.href) location.reload()
  else location.assign(url)
}

async function row(form, row) {
  const completing = form.dataset.celebrate === "complete"
  const check = form.querySelector(".wb-check")
  const list = row.closest(".wb-todolist")
  const last = completing && openRows(row.parentElement, row).length === 0
  const lastOfList = completing && list && openRows(list, row).length === 0
  row.classList.add(completing ? "is-completing" : "is-reopening")
  if (!completing) check.classList.remove("is-done")
  if (completing) {
    check.classList.add("is-done", "is-popping")
    if (last) {
      check.classList.add("is-bursting")
      row.classList.add("is-last")
    }
    row.querySelector(".wb-todo-title")?.classList.add("is-striking")
  }
  const request = send(form)
  const finished = ended(row, completing ? "wb-collapse" : "wb-fade-out")
  let url
  try {
    ;[url] = await Promise.all([request, finished])
  } catch {
    // Offline or refused: the normal way, with the page's answer
    form.submit()
    return
  }
  row.remove()
  if (lastOfList) {
    const place = document.getElementById("live-completed")
    if (place && !place.querySelector(".wb-all-done")) {
      const note = document.createElement("p")
      note.className = "text-body-secondary wb-all-done is-new"
      note.textContent = list.dataset.allDone
      place.prepend(note)
    }
  }
  follow(url)
}

// Shows the end state a moment before the page follows
const HOLD = 400
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// The to-do's page: the button's check fills and pops like a row's, the
// heading gets the same moment (a check pops in before the title, the
// title is struck through), then the page follows
async function page(form) {
  const check = form.querySelector(".wb-check")
  const completing = form.dataset.celebrate === "complete"
  const animations = []
  if (!completing) check?.classList.remove("is-done")
  if (completing) {
    if (check) {
      check.classList.add("is-done", "is-popping")
      animations.push(ended(check, "wb-pop"))
    }
    const title = document.querySelector("[data-celebrate-title]")
    if (title) {
      const mark = document.createElement("span")
      mark.className = "text-body-secondary"
      mark.innerHTML =
        '<i class="bi bi-check-circle is-popping" aria-hidden="true"></i> '
      title.before(mark)
      title.classList.add("is-striking")
      animations.push(
        ended(mark.firstChild, "wb-pop"),
        ended(title, "wb-strike"),
      )
    }
  }
  let url
  try {
    ;[url] = await Promise.all([
      send(form),
      Promise.all(animations).then(() => completing && pause(HOLD)),
    ])
  } catch {
    form.submit()
    return
  }
  follow(url)
}

document.addEventListener("submit", (event) => {
  const form = event.target
  if (!form.matches?.("[data-celebrate]") || reduced.matches) return
  event.preventDefault()
  if (form.dataset.busy) return
  form.dataset.busy = "1"
  const el = form.closest(".wb-todo")
  if (el) row(form, el)
  else page(form)
})
