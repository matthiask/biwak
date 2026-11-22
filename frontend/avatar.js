// The mark of a person (specs/people.md) for lists the scripts build, like
// {% avatar person size %} on the server: the image, or the drawn mark in
// white on the palette color chosen from the ID (data from
// User.avatar_data; the drawing is a CSS mask, frontend/styles/marks.css).
// An image which doesn't load (the person isn't known to the viewer) falls
// back to the drawn mark.

// Inactive people's marks are greyed (specs/handover.md)
function className(person, size) {
  return `wb-avatar wb-avatar-${size}${person.inactive ? " wb-avatar-inactive" : ""}`
}

// The name, and until when they're away (specs/quiet-hours.md)
const title = (person) =>
  person.away ? `${person.name}\n${person.away}` : person.name

// Away: the small moon on the mark, like {% avatar %}
function withAwaySign(person, mark) {
  if (!person.away || person.inactive) return mark
  const wrapper = document.createElement("span")
  wrapper.className = "wb-away-mark"
  const sign = document.createElement("span")
  sign.className = "wb-away-sign"
  sign.setAttribute("aria-hidden", "true")
  const icon = document.createElement("i")
  icon.className = "bi bi-moon-fill"
  sign.append(icon)
  wrapper.append(mark, sign)
  return wrapper
}

function plainDrawnMark(person, size) {
  const name = title(person)
  const mark = document.createElement("span")
  mark.className = `${className(person, size)} wb-mark wb-mark-${person.mark}`
  mark.dataset.avatarColor = person.color
  mark.title = name
  mark.setAttribute("role", "img")
  mark.setAttribute("aria-label", name)
  return mark
}

export function drawnMark(person, size = "sm") {
  return withAwaySign(person, plainDrawnMark(person, size))
}

export function avatar(person, size = "sm") {
  if (!person) return document.createDocumentFragment()
  if (!person.image_url) return drawnMark(person, size)
  const image = document.createElement("img")
  image.className = className(person, size)
  image.src = person.image_url
  image.alt = title(person)
  image.title = title(person)
  image.addEventListener(
    "error",
    () => image.replaceWith(plainDrawnMark(person, size)),
    {
      once: true,
    },
  )
  return withAwaySign(person, image)
}

// The data of an <option data-avatar="{…}">, or null
export function optionAvatar(option) {
  try {
    return JSON.parse(option.dataset.avatar)
  } catch {
    return null
  }
}

// The mark of a team (specs/teams.md) in the people picker and the @ list,
// like {% team_mark %} on the server
export function teamMark(size = "sm") {
  const mark = document.createElement("span")
  mark.className = `wb-avatar wb-avatar-${size} wb-team-mark`
  const icon = document.createElement("i")
  icon.className = "bi bi-people"
  icon.setAttribute("aria-hidden", "true")
  mark.append(icon)
  return mark
}
