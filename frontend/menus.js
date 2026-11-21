// What opens in a <details> and isn't needed often (details.wb-menu, and
// those with data-dismiss: the reaction picker, the form for a link) closes
// when clicking elsewhere and with Escape, like Bootstrap's dropdowns

const OPEN = "details.wb-menu[open], details[data-dismiss][open]"

document.addEventListener("click", (event) => {
  for (const menu of document.querySelectorAll(OPEN)) {
    if (!menu.contains(event.target)) menu.open = false
  }
})

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return
  const menu = event.target.closest?.(OPEN)
  if (menu) {
    menu.open = false
    menu.querySelector("summary").focus()
  }
})
