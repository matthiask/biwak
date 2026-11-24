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
// wider than the space on either side. Inside something scrolling, which
// cuts off what sticks out (the board's columns), it's placed on the
// screen below its button instead, and closes when anything scrolls.

const MARGIN = 8
const POPUP = ":scope > .dropdown-menu, :scope > .wb-reaction-picker"

function place(details) {
  const popup = details.querySelector(POPUP)
  if (!popup) return
  const style = popup.style
  for (const name of [
    "position",
    "top",
    "left",
    "right",
    "maxWidth",
    "minWidth",
    "translate",
  ]) {
    style[name] = ""
  }
  if (getComputedStyle(popup).position !== "absolute") return
  const screen = document.documentElement.clientWidth
  const fits = (box) => box.left >= MARGIN && box.right <= screen - MARGIN

  if (cutOff(details, popup)) {
    const button = details.querySelector("summary").getBoundingClientRect()
    style.position = "fixed"
    style.maxWidth = `${screen - 2 * MARGIN}px`
    style.top = `${button.bottom}px`
    style.right = "auto"
    const width = popup.getBoundingClientRect().width
    const left = Math.min(button.right, screen - MARGIN) - width
    style.left = `${Math.max(MARGIN, left)}px`
    return
  }

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

// The popup sticks out of an ancestor which cuts off what overflows
function cutOff(details, popup) {
  const box = popup.getBoundingClientRect()
  for (
    let el = details.parentElement;
    el && el !== document.body;
    el = el.parentElement
  ) {
    const { overflowX, overflowY } = getComputedStyle(el)
    if (overflowX === "visible" && overflowY === "visible") continue
    const clip = el.getBoundingClientRect()
    if (
      box.bottom > clip.bottom ||
      box.top < clip.top ||
      box.right > clip.right ||
      box.left < clip.left
    )
      return true
  }
  return false
}

// Placed on the screen, it would stay behind while the page or the board
// scrolls: closed instead
document.addEventListener(
  "scroll",
  () => {
    for (const details of document.querySelectorAll(OPEN)) {
      const popup = details.querySelector(POPUP)
      if (popup?.style.position === "fixed") details.open = false
    }
  },
  true,
)

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

// Menus with data-hover-open (a list's filters, specs/todos.md) open when
// the mouse rests on them a moment, and close when it leaves unless
// something inside has the focus (the select in use). A click on the
// button after that keeps it open until a click elsewhere, instead of
// closing it. Touch screens open them with a tap as before.
const HOVER = "details[data-hover-open]"
const OPEN_AFTER = 50
const CLOSE_AFTER = 300
const timers = new WeakMap()

function later(menu, action, delay) {
  clearTimeout(timers.get(menu))
  timers.set(menu, setTimeout(action, delay))
}

document.addEventListener("pointerover", (event) => {
  const menu = event.pointerType === "mouse" && event.target.closest?.(HOVER)
  if (!menu || menu.contains(event.relatedTarget)) return
  later(
    menu,
    () => {
      if (menu.open) return
      menu.dataset.hoverOpened = ""
      menu.open = true
    },
    OPEN_AFTER,
  )
})

document.addEventListener("pointerout", (event) => {
  const menu = event.pointerType === "mouse" && event.target.closest?.(HOVER)
  if (!menu || menu.contains(event.relatedTarget)) return
  later(
    menu,
    () => {
      if ("hoverOpened" in menu.dataset && !menu.matches(":focus-within"))
        menu.open = false
    },
    CLOSE_AFTER,
  )
})

document.addEventListener("click", (event) => {
  const menu = event.target.closest?.(`${HOVER} > summary`)?.parentElement
  if (!menu || !("hoverOpened" in menu.dataset)) return
  event.preventDefault()
  delete menu.dataset.hoverOpened
})

document.addEventListener(
  "toggle",
  (event) => {
    if (event.target.matches?.(HOVER) && !event.target.open)
      delete event.target.dataset.hoverOpened
  },
  true,
)
