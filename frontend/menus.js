// What opens in a <details> and isn't needed often (details.wb-menu, and
// those with data-dismiss: the reaction picker, the form for a link) closes
// when clicking elsewhere and with Escape, like Bootstrap's dropdowns; other
// elements with data-dismiss get a "dismiss" event on a click elsewhere

const OPEN = "details.wb-menu[open], details[data-dismiss][open]"

document.addEventListener("click", (event) => {
  for (const menu of document.querySelectorAll(OPEN)) {
    if (!menu.contains(event.target)) menu.open = false
  }
  // Other floating things with data-dismiss (the people picker's list)
  // close themselves on a "dismiss" event
  for (const other of document.querySelectorAll(
    "[data-dismiss]:not(details)",
  )) {
    if (!other.contains(event.target)) other.dispatchEvent(new Event("dismiss"))
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

// Keep an open menu on the screen. The CSS aligns it to the right edge of
// its button, which isn't enough when the button sits elsewhere (a header
// wrapping on a phone puts it at the left): align it to the other edge of
// the button if it overflows, and cap its width and shift it if it's
// wider than the space on either side

const MARGIN = 8
const POPUP = ":scope > .dropdown-menu, :scope > .wb-reaction-picker"

function place(details) {
  const popup = details.querySelector(POPUP)
  if (!popup) return
  const style = popup.style
  for (const name of ["left", "right", "maxWidth", "minWidth", "translate"]) {
    style[name] = ""
  }
  if (getComputedStyle(popup).position !== "absolute") return
  const screen = document.documentElement.clientWidth
  const fits = (box) => box.left >= MARGIN && box.right <= screen - MARGIN

  if (fits(popup.getBoundingClientRect())) return

  // Aligned to the other edge of the button
  const box = popup.getBoundingClientRect()
  if (box.left < MARGIN) {
    style.left = "0"
    style.right = "auto"
  } else {
    style.right = "0"
    style.left = "auto"
  }
  if (fits(popup.getBoundingClientRect())) return

  // Still too wide, or too close to the screen's edge: cap and shift
  style.maxWidth = `${screen - 2 * MARGIN}px`
  style.minWidth = "0"
  const moved = popup.getBoundingClientRect()
  const shift = Math.max(
    MARGIN - moved.left,
    Math.min(0, screen - MARGIN - moved.right),
  )
  style.translate = `${shift}px`
}

document.addEventListener(
  "toggle",
  (event) => {
    if (event.target.matches?.(OPEN)) place(event.target)
  },
  true,
)

window.addEventListener("resize", () => {
  for (const details of document.querySelectorAll(OPEN)) place(details)
})
