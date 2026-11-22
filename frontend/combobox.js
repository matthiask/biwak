// A search field in front of a long select (specs/ui.md, "Forms"),
// adapted from Workbench's initCombobox: <select data-combobox>
// (ComboboxSelect in biwak/forms.py) gets a field which lists the options
// on a click or the arrow keys and finds the typed words anywhere in an
// option, its group and its data-search (an address, say). Up and Down,
// Page Up and Page Down, Home and End move, Enter or a click chooses,
// Escape closes the list (not the modal around it), clicking elsewhere too.
// The select stays the form's field (hidden): choosing dispatches its
// change event, so filter forms submit as before, and without JavaScript
// it's the plain select.

let counter = 0

function attach(select) {
  const id = select.id || `combobox-${++counter}`
  const listId = `${id}-list`
  const texts = {
    placeholder: select.dataset.placeholder || "Search…",
    empty: select.dataset.empty || "Nothing found",
  }

  const root = document.createElement("div")
  root.className = "wb-combobox"
  const input = document.createElement("input")
  input.type = "text"
  input.id = `${id}-combobox`
  input.className = "form-select"
  input.autocomplete = "off"
  input.disabled = select.disabled
  input.placeholder = texts.placeholder
  // Typing searches, it doesn't submit a filter form (autosubmit.js)
  input.dataset.noAutosubmit = ""
  input.setAttribute("role", "combobox")
  input.setAttribute("aria-autocomplete", "list")
  input.setAttribute("aria-expanded", "false")
  input.setAttribute("aria-controls", listId)
  const label = select.getAttribute("aria-label")
  if (label) input.setAttribute("aria-label", label)
  const list = document.createElement("ul")
  list.id = listId
  list.className = "wb-mentions list-group wb-combobox-list"
  list.setAttribute("role", "listbox")
  list.hidden = true

  select.before(root)
  root.append(input, list, select)
  // Still validated and posted, but neither shown nor focused
  select.classList.add("visually-hidden")
  select.tabIndex = -1
  // The field is the control for screen readers, its label moves to it
  select.setAttribute("aria-hidden", "true")
  select.dataset.comboboxInput = input.id
  // Focusing the select (its label, a restored focus) focuses the field
  select.addEventListener("focus", () => input.focus())
  if (select.id)
    for (const forLabel of document.querySelectorAll(
      `label[for="${select.id}"]`,
    ))
      forLabel.htmlFor = input.id
  if (select.autofocus) {
    select.autofocus = false
    input.autofocus = true
  }

  let items = []
  let active = -1

  const reset = () => {
    input.value = select.value ? select.selectedOptions[0]?.text || "" : ""
  }
  reset()
  select.addEventListener("change", reset)
  select.form?.addEventListener("reset", () => setTimeout(reset))

  const isOpen = () => !list.hidden

  const close = () => {
    list.hidden = true
    input.setAttribute("aria-expanded", "false")
    input.removeAttribute("aria-activedescendant")
    active = -1
  }

  const highlight = (index) => {
    active = index
    items.forEach((item, i) => {
      item.classList.toggle("active", i === active)
      item.setAttribute("aria-selected", i === active ? "true" : "false")
    })
    if (active >= 0 && items[active]) {
      input.setAttribute("aria-activedescendant", items[active].id)
      items[active].scrollIntoView({ block: "nearest" })
    } else input.removeAttribute("aria-activedescendant")
  }

  const choose = (option) => {
    select.value = option.value
    close()
    select.dispatchEvent(new Event("change", { bubbles: true }))
  }

  const render = (term) => {
    const words = term.toLowerCase().split(/\s+/).filter(Boolean)
    const matches = (text) => words.every((word) => text.includes(word))
    const children = []
    items = []
    let selected = -1
    const addOption = (option, group) => {
      if (option.disabled) return
      // The empty option only when browsing
      if (!option.value && words.length) return
      const text = `${group} ${option.text} ${option.dataset.search || ""}`
      if (!matches(text.toLowerCase())) return
      const item = document.createElement("li")
      item.id = `${listId}-${items.length}`
      item.className = "list-group-item list-group-item-action"
      item.setAttribute("role", "option")
      item.setAttribute("aria-selected", "false")
      item.textContent = option.text
      if (option.selected && option.value) {
        item.classList.add("wb-combobox-selected")
        selected = items.length
      }
      // mousedown keeps the focus in the field
      item.addEventListener("mousedown", (event) => {
        event.preventDefault()
        choose(option)
      })
      children.push(item)
      items.push(item)
    }
    for (const child of select.children) {
      if (child.tagName === "OPTGROUP") {
        const header = document.createElement("li")
        header.className = "list-group-item wb-combobox-group"
        header.setAttribute("role", "presentation")
        header.textContent = child.label
        const count = items.length
        children.push(header)
        for (const option of child.children) addOption(option, child.label)
        if (items.length === count) children.pop()
      } else {
        addOption(child, "")
      }
    }
    if (!items.length) {
      const empty = document.createElement("li")
      empty.className = "list-group-item text-body-secondary"
      empty.textContent = texts.empty
      children.push(empty)
    }
    list.replaceChildren(...children)
    list.hidden = false
    input.setAttribute("aria-expanded", "true")
    // Browsing starts at the selected option, searching at the first match
    if (words.length) highlight(items.length ? 0 : -1)
    else highlight(selected)
  }

  // Opening on focus would cover the form when the field is the first one
  // of a modal: the list opens when typing, clicking or with the keys
  input.addEventListener("focus", () => input.select())
  input.addEventListener("click", () => {
    if (!isOpen()) render("")
  })
  input.addEventListener("input", () => render(input.value))
  input.addEventListener("blur", () => {
    close()
    reset()
  })
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      if (!isOpen()) return render("")
      if (!items.length) return
      const step = event.key === "ArrowDown" ? 1 : -1
      highlight(
        active < 0
          ? step > 0
            ? 0
            : items.length - 1
          : (active + step + items.length) % items.length,
      )
    } else if (
      (event.key === "PageDown" || event.key === "PageUp") &&
      isOpen() &&
      items.length
    ) {
      event.preventDefault()
      // By the height of the list, stopping at the first or last option
      const down = event.key === "PageDown"
      const current = items[active >= 0 ? active : down ? 0 : items.length - 1]
      const target = current.offsetTop + (down ? 1 : -1) * list.clientHeight
      const index = down
        ? items.findLastIndex((item) => item.offsetTop <= target)
        : items.findIndex((item) => item.offsetTop >= target)
      highlight(Math.max(index, 0))
    } else if (event.key === "Home" || event.key === "End") {
      // Opens the list like the arrow keys instead of moving the cursor
      event.preventDefault()
      if (!isOpen()) render("")
      if (items.length) highlight(event.key === "Home" ? 0 : items.length - 1)
    } else if (event.key === "Enter" && isOpen()) {
      // Not submitting the form
      event.preventDefault()
      event.stopPropagation()
      if (active >= 0) items[active].dispatchEvent(new MouseEvent("mousedown"))
    } else if (event.key === "Escape" && isOpen()) {
      // Not closing the modal (its cancel) or the form around it
      event.preventDefault()
      event.stopPropagation()
      close()
      reset()
      input.select()
    }
  })
}

function attachAll(root) {
  const selects = [
    ...(root.matches?.("select[data-combobox]") ? [root] : []),
    ...(root.querySelectorAll?.("select[data-combobox]") ?? []),
  ]
  for (const select of selects) {
    if (select.dataset.comboboxReady || select.multiple) continue
    select.dataset.comboboxReady = "true"
    attach(select)
  }
}

attachAll(document)
// Forms htmx inserts later (modals, the edit form in place of a view)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
