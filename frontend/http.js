// Requests the scripts make to Django

// The token of a form on the page, or the cookie where there's no form
export function csrfToken() {
  return (
    document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
    document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ||
    ""
  )
}

// POSTs the fields (an object or [name, value] pairs, a name may repeat) and
// returns the response. Fails with the request's error.
export function send(url, data = []) {
  const body = new FormData()
  for (const [name, value] of Array.isArray(data) ? data : Object.entries(data))
    body.append(name, value)
  return fetch(url, {
    method: "POST",
    body,
    headers: { "X-CSRFToken": csrfToken() },
  })
}

// For changes made on the page already (a drag): the page keeps what it
// shows, unless the request fails (offline, an error); then it reloads, so
// that it shows what the server has
export function post(url, data) {
  return send(url, data).then(
    (response) => {
      if (!response.ok) window.location.reload()
    },
    () => window.location.reload(),
  )
}
