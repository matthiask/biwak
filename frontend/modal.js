// Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
// frontend/modal.js, see NOTICE)
//
// Forms in a modal with a <dialog> and htmx (biwak/modals.py): links with
// data-modal load their form with the HX-Modal header into the dialog, the
// form posts there (modal_form.html), saving loads the page the view
// redirects to (HX-Redirect), errors render the form again in the dialog.
// Without JavaScript, or with a modifier key, the links open the form's own
// page. Escape closes a form nobody changed, a changed one needs it twice.
// The focus goes back to the link (or its menu's button) when it closes.
import htmx from "htmx.org"

const HEADERS = { "HX-Modal": "true" }

let dialog = null
let initial = null
let opener = null
let lastEscape = Number.NEGATIVE_INFINITY

const serialize = () => {
  const form = dialog.querySelector("form")
  return form ? new URLSearchParams(new FormData(form)).toString() : null
}

function getDialog() {
  if (dialog) return dialog
  dialog = document.createElement("dialog")
  dialog.id = "modal"
  dialog.className = "wb-modal"
  dialog.setAttribute("aria-labelledby", "modal-title")
  document.body.append(dialog)

  dialog.addEventListener("close", () => {
    dialog.replaceChildren()
    initial = null
    lastEscape = Number.NEGATIVE_INFINITY
    // The browser returns the focus to what had it, which may be gone or
    // closed in a menu: the link, or the button of the menu it's in
    const target =
      opener?.isConnected && opener.checkVisibility()
        ? opener
        : opener?.closest("details")?.querySelector(":scope > summary")
    target?.focus()
    opener = null
  })
  dialog.addEventListener("click", (event) => {
    if (event.target.closest("[data-modal-close]")) dialog.close()
  })
  // Escape (the dialog's close request, not when the mentions' list takes
  // it) closes the form as long as nothing has been changed, pressing it
  // again shortly after closes changed forms anyway
  dialog.addEventListener("cancel", (event) => {
    const repeated = event.timeStamp - lastEscape < 1500
    lastEscape = event.timeStamp
    if (initial !== null && serialize() !== initial && !repeated) {
      event.preventDefault()
      dialog.classList.add("wb-modal-shake")
      setTimeout(() => dialog.classList.remove("wb-modal-shake"), 300)
    }
  })
  return dialog
}

function focusFirstField() {
  const field =
    dialog.querySelector("[autofocus]") ||
    dialog.querySelector(
      ":is(input, select, textarea):not([type=hidden]):not([disabled])",
    ) ||
    dialog.querySelector("button[type=submit]")
  field?.focus()
}

// Opens the form at ``url`` (the link's) in the dialog; ``from`` is what
// gets the focus back
export function openModal(url, from = document.activeElement) {
  opener = from
  // A menu's entry closes the menu
  from?.closest?.("details[open]")?.removeAttribute("open")
  return htmx.ajax("GET", url, {
    target: getDialog(),
    swap: "innerHTML",
    headers: HEADERS,
  })
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-modal]")
  if (
    !link ||
    event.defaultPrevented ||
    event.button !== 0 ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return
  }
  event.preventDefault()
  openModal(link.href, link)
})

const isModal = (event) => dialog && event.detail.ctx?.target === dialog

document.addEventListener("htmx:after:swap", (event) => {
  if (!isModal(event)) return
  if (!dialog.open) {
    dialog.showModal()
    focusFirstField()
    initial = serialize()
  } else {
    // The form again, with its errors
    focusFirstField()
  }
})

// Errors (no permission, a server error) show the form's page
document.addEventListener("htmx:after:request", (event) => {
  if (!isModal(event) || event.detail.ctx.response.status < 400) return
  event.preventDefault()
  window.location.href = event.detail.ctx.request.action
})
document.addEventListener("htmx:error", (event) => {
  if (!isModal(event)) return
  window.location.href = event.detail.ctx.request.action
})
