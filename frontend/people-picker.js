// The people picker (specs/todos.md, "Assignees"): a <select multiple
// data-people-picker> of people (assignees, subscribers, whom to notify)
// becomes pills, each with × to remove, and
// a field which opens the list of the others on a click, typing or Down and
// filters while typing. Up and Down choose, Enter or a click picks, Escape closes,
// Backspace in the empty field takes the last pill away. The list floats
// over what's below, so it closes after a pick (typing opens it again),
// when nobody is left to pick, when the field loses the focus and on a click
// elsewhere (``data-dismiss``, frontend/menus.js). The options come
// members first (the server's order, ``assignable_people()``); a person who
// isn't a member yet says so, since assigning makes them one. The select
// stays in the form (hidden), so the form posts it as it always did and
// without JavaScript it's usable as it is.
// Keyboard handling as in mentions.js.
//
// Teams (specs/teams.md, staff only): data-teams lists them with their
// members, each with the reason the server knows for leaving them out; the
// options disabled now (clients while a post is internal) are left out too.
// Matching teams come last, saying how many of their members they'd add
// and why the others are left out; picking one picks its members, as if
// picked one by one. A team with nobody left to add isn't offered.

import { avatar, optionAvatar, teamMark } from "./avatar.js"

function parse(json) {
  try {
    return JSON.parse(json || "[]")
  } catch {
    return []
  }
}

let counter = 0

function attach(select) {
  const id = select.id || `people-${++counter}`
  const listId = `${id}-list`
  const inputId = `${id}-picker`
  const texts = {
    placeholder: select.dataset.placeholder || "Assign…",
    empty: select.dataset.empty || "Nobody found",
    remove: select.dataset.remove || "Remove %(name)s",
    new: select.dataset.new || "not in the project yet",
    team: select.dataset.team || "team",
    teamOne: select.dataset.teamOne || "%(count)s member",
    teamMany: select.dataset.teamMany || "%(count)s members",
    teamPartial:
      select.dataset.teamPartial || "%(count)s of %(total)s: %(reasons)s",
    teamInternal: select.dataset.teamInternal || "can't see internal items",
  }
  const teams = parse(select.dataset.teams)

  const root = document.createElement("div")
  root.className = "wb-picker"
  root.dataset.dismiss = ""
  const pills = document.createElement("span")
  pills.className = "wb-picker-pills"
  const input = document.createElement("input")
  input.type = "text"
  input.id = inputId
  input.className = "wb-picker-input"
  input.placeholder = texts.placeholder
  input.autocomplete = "off"
  input.setAttribute("role", "combobox")
  input.setAttribute("aria-autocomplete", "list")
  input.setAttribute("aria-expanded", "false")
  input.setAttribute("aria-controls", listId)
  const label = select.getAttribute("aria-label")
  if (label) input.setAttribute("aria-label", label)
  const list = document.createElement("ul")
  list.id = listId
  list.className = "wb-mentions list-group wb-picker-list"
  list.setAttribute("role", "listbox")
  list.hidden = true
  root.append(pills, input, list)
  select.after(root)
  select.hidden = true
  select.dataset.pickerInput = inputId
  // The label of the form field focuses the new field
  if (select.id)
    for (const forLabel of document.querySelectorAll(
      `label[for="${select.id}"]`,
    ))
      forLabel.htmlFor = inputId

  const options = [...select.options]
  const byId = new Map(options.map((option) => [option.value, option]))
  let shown = []
  let active = -1

  const chosen = () => options.filter((option) => option.selected)

  const renderPills = () => {
    pills.replaceChildren(
      ...chosen().map((option) => {
        const pill = document.createElement("span")
        pill.className = "wb-pill"
        const name = document.createElement("span")
        name.textContent = option.textContent
        const remove = document.createElement("button")
        remove.type = "button"
        remove.className = "wb-pill-remove"
        remove.textContent = "×"
        remove.setAttribute(
          "aria-label",
          texts.remove.replace("%(name)s", option.textContent),
        )
        remove.addEventListener("click", () => {
          option.selected = false
          changed()
          input.focus()
        })
        pill.append(avatar(optionAvatar(option)), name, remove)
        return pill
      }),
    )
  }

  const changed = () => {
    select.dispatchEvent(new Event("change", { bubbles: true }))
    renderPills()
    if (!list.hidden) renderList()
  }

  // What picking the team would do now: the options it adds, how many
  // members are in then and why the others are left out
  const teamState = (team) => {
    const add = []
    const leftOut = new Map()
    let inside = 0
    for (const member of team.members) {
      const option = byId.get(String(member.id))
      let reason = member.reason
      if (!(reason || member.already) && (!option || option.disabled))
        reason = texts.teamInternal
      if (reason) {
        leftOut.set(reason, (leftOut.get(reason) || 0) + 1)
        continue
      }
      inside++
      if (option && !member.already && !option.selected) add.push(option)
    }
    return { add, inside, leftOut, total: team.members.length }
  }

  const teamDetail = ({ inside, leftOut, total }) => {
    if (!leftOut.size)
      return (total === 1 ? texts.teamOne : texts.teamMany).replace(
        "%(count)s",
        total,
      )
    const reasons = [...leftOut]
      .map(([reason, count]) => `${count} ${reason}`)
      .join(", ")
    return texts.teamPartial
      .replace("%(count)s", inside)
      .replace("%(total)s", total)
      .replace("%(reasons)s", reasons)
  }

  // The people (options), then the teams ({team, state}; decided
  // 2026-11-22: teams are a special case)
  const matches = () => {
    const query = input.value.trim().toLowerCase()
    const found = options.filter(
      (option) =>
        !option.selected &&
        !option.disabled &&
        option.textContent.toLowerCase().includes(query),
    )
    for (const team of teams) {
      if (!team.name.toLowerCase().includes(query)) continue
      const state = teamState(team)
      if (state.add.length) found.push({ team, state })
    }
    return found
  }

  const renderList = () => {
    shown = matches()
    if (active >= shown.length) active = shown.length - 1
    if (active < 0 && shown.length) active = 0
    list.replaceChildren(
      ...(shown.length
        ? shown.map((option, index) => {
            if (option.team) return teamItem(option, index)
            const item = document.createElement("li")
            item.id = `${listId}-${index}`
            item.className = `list-group-item list-group-item-action${index === active ? " active" : ""}`
            item.setAttribute("role", "option")
            item.setAttribute(
              "aria-selected",
              index === active ? "true" : "false",
            )
            const name = document.createElement("span")
            name.textContent = option.textContent
            item.append(avatar(optionAvatar(option)), " ", name)
            if (option.dataset.member === "false") {
              const detail = document.createElement("small")
              detail.className = "wb-mentions-detail"
              detail.textContent = texts.new
              item.append(" ", detail)
            }
            // mousedown keeps the focus in the field
            item.addEventListener("mousedown", (event) => {
              event.preventDefault()
              pick(option)
            })
            return item
          })
        : [emptyItem()]),
    )
    if (active >= 0 && shown.length) {
      input.setAttribute("aria-activedescendant", `${listId}-${active}`)
      list.children[active]?.scrollIntoView({ block: "nearest" })
    } else input.removeAttribute("aria-activedescendant")
  }

  const teamItem = (entry, index) => {
    const item = document.createElement("li")
    item.id = `${listId}-${index}`
    item.className = `list-group-item list-group-item-action${index === active ? " active" : ""}`
    item.setAttribute("role", "option")
    item.setAttribute("aria-selected", index === active ? "true" : "false")
    item.dataset.team = entry.team.id
    const name = document.createElement("span")
    name.textContent = entry.team.name
    const detail = document.createElement("small")
    detail.className = "wb-mentions-detail"
    detail.textContent = `${texts.team} · ${teamDetail(entry.state)}`
    item.append(teamMark(), " ", name, " ", detail)
    item.addEventListener("mousedown", (event) => {
      event.preventDefault()
      pick(entry)
    })
    return item
  }

  const emptyItem = () => {
    const item = document.createElement("li")
    item.className = "list-group-item text-body-secondary"
    item.textContent = texts.empty
    return item
  }

  const open = () => {
    // Nobody left to pick: nothing to show ("Nobody found" is for typing)
    if (!input.value.trim() && !matches().length) return close()
    list.hidden = false
    input.setAttribute("aria-expanded", "true")
    renderList()
  }

  const close = () => {
    list.hidden = true
    input.setAttribute("aria-expanded", "false")
    input.removeAttribute("aria-activedescendant")
    active = -1
  }

  const pick = (option) => {
    if (option.team) {
      for (const member of option.state.add) member.selected = true
    } else option.selected = true
    input.value = ""
    close()
    changed()
  }

  root.addEventListener("click", (event) => {
    if (event.target === root || event.target === pills) {
      input.focus()
      open()
    }
  })
  // Not on focus alone (a modal focusing its first field, a label): a click,
  // typing or Down opens the list (decided 2026-11-21)
  input.addEventListener("click", open)
  input.addEventListener("input", () => {
    active = 0
    open()
  })
  input.addEventListener("blur", () => {
    input.value = ""
    close()
  })
  root.addEventListener("dismiss", close)
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      if (list.hidden) return open()
      if (!shown.length) return
      const step = event.key === "ArrowDown" ? 1 : -1
      active = (active + step + shown.length) % shown.length
      renderList()
    } else if (event.key === "Enter") {
      // Not submitting the form, and not Ctrl+Enter of the inline form
      if (!list.hidden && active >= 0 && shown[active]) {
        event.preventDefault()
        event.stopPropagation()
        pick(shown[active])
      } else if (!list.hidden) {
        event.preventDefault()
      }
    } else if (event.key === "Escape") {
      if (list.hidden) return
      event.preventDefault()
      // Not closing the inline form or the edit form as well
      event.stopPropagation()
      input.value = ""
      close()
    } else if (event.key === "Backspace" && !input.value) {
      const last = chosen().at(-1)
      if (last) {
        last.selected = false
        changed()
      }
    }
  })

  // A reset puts the form's own selection back
  select.form?.addEventListener("reset", () => setTimeout(renderPills))
  // Options changed from outside (frontend/told.js)
  select.addEventListener("picker:refresh", () => {
    renderPills()
    if (!list.hidden) renderList()
  })
  renderPills()
}

function attachAll(root) {
  const selects = [
    ...(root.matches?.("select[data-people-picker]") ? [root] : []),
    ...(root.querySelectorAll?.("select[data-people-picker]") ?? []),
  ]
  for (const select of selects) {
    if (select.dataset.pickerReady) continue
    select.dataset.pickerReady = "true"
    attach(select)
  }
}

attachAll(document)
// Forms htmx inserts later (the edit form in place of a view, live updates)
document.addEventListener("htmx:after:process", (event) =>
  attachAll(event.target),
)
