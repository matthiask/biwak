// Removing one's own reaction asks first: clicking one's pill (or Enter
// or Space on it) shows a trash button inside the pill, clicking that
// removes the reaction. A click elsewhere or Escape cancels. Without
// JavaScript the pill is a link to a confirmation page.

const OWN = ".wb-reaction-own"

function confirming(pill) {
  return !pill.querySelector(".wb-reaction-remove").hidden
}

function ask(pill, on) {
  pill.querySelector(".wb-reaction-remove").hidden = !on
  pill.classList.toggle("is-confirming", on)
  pill
    .querySelector("[data-confirm-remove]")
    .setAttribute("aria-expanded", on ? "true" : "false")
}

function cancelAll(except) {
  for (const pill of document.querySelectorAll(`${OWN}.is-confirming`)) {
    if (pill !== except) ask(pill, false)
  }
}

document.addEventListener("click", (event) => {
  const label = event.target.closest?.("[data-confirm-remove]")
  const pill = label?.closest(OWN)
  cancelAll(pill)
  if (!pill) return
  event.preventDefault()
  ask(pill, !confirming(pill))
})

document.addEventListener("keydown", (event) => {
  if (event.key === " " && event.target.matches?.("[data-confirm-remove]")) {
    // Like a button: Space clicks, without scrolling the page
    event.preventDefault()
    event.target.click()
  } else if (event.key === "Escape") {
    const pill = document.querySelector(`${OWN}.is-confirming`)
    if (!pill) return
    ask(pill, false)
    pill.querySelector("[data-confirm-remove]").focus()
  }
})

// A new reaction pops in and a count that grew bumps (specs/celebrations.md).
// The reactions are swapped by htmx and by live updates (frontend/live.js)
// alike, so the script compares what was there with what arrives: by the
// reactions' id, content → count. Nothing animates on load, and with
// reduced motion the CSS turns the animations off.
const seen = new Map()

function snapshot(reactions) {
  const counts = new Map()
  for (const form of reactions.querySelectorAll(":scope > form")) {
    const content = form.querySelector("[name=content]")?.value
    const count = Number(form.querySelector(".wb-reaction-count")?.textContent)
    if (content) counts.set(content, count)
  }
  return counts
}

function animate(element) {
  element.addEventListener(
    "animationend",
    () => element.classList.remove("is-new", "is-bumped"),
    { once: true },
  )
}

function compare(reactions) {
  const before = seen.get(reactions.id)
  const now = snapshot(reactions)
  seen.set(reactions.id, now)
  if (!before) return
  for (const form of reactions.querySelectorAll(":scope > form")) {
    const content = form.querySelector("[name=content]")?.value
    if (!now.has(content)) continue
    if (!before.has(content)) {
      form.classList.add("is-new")
      animate(form)
    } else if (now.get(content) > before.get(content)) {
      const count = form.querySelector(".wb-reaction-count")
      count.classList.add("is-bumped")
      animate(count)
    }
  }
}

function remember(root) {
  const found = root.matches?.(".wb-reactions[id]") ? [root] : []
  found.push(...(root.querySelectorAll?.(".wb-reactions[id]") ?? []))
  return found
}

for (const reactions of remember(document)) {
  seen.set(reactions.id, snapshot(reactions))
}

new MutationObserver((records) => {
  for (const record of records)
    for (const node of record.addedNodes)
      for (const reactions of remember(node)) compare(reactions)
}).observe(document.body, { childList: true, subtree: true })
