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
