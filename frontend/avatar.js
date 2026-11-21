// The mark of a person (specs/people.md) for lists the scripts build, like
// {% avatar person size %} on the server: the image, or the initials on the
// palette color chosen from the ID (data from User.avatar_data). An image
// which doesn't load (the person isn't known to the viewer) falls back to
// the initials.

export function initialsMark({ name, initials, color }, size = "sm") {
  const mark = document.createElement("span")
  mark.className = `wb-avatar wb-avatar-${size}`
  mark.dataset.avatarColor = color
  mark.title = name
  mark.setAttribute("role", "img")
  mark.setAttribute("aria-label", name)
  mark.textContent = initials
  return mark
}

export function avatar(person, size = "sm") {
  if (!person) return document.createDocumentFragment()
  if (!person.image_url) return initialsMark(person, size)
  const image = document.createElement("img")
  image.className = `wb-avatar wb-avatar-${size}`
  image.src = person.image_url
  image.alt = person.name
  image.title = person.name
  image.addEventListener(
    "error",
    () => image.replaceWith(initialsMark(person, size)),
    {
      once: true,
    },
  )
  return image
}

// The data of an <option data-avatar="{…}">, or null
export function optionAvatar(option) {
  try {
    return JSON.parse(option.dataset.avatar)
  } catch {
    return null
  }
}
