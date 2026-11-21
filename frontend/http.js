// Requests the scripts make to Django
import { isOffline, succeeded } from "./connection.js"

// The token of a form on the page, or the cookie where there's no form
export function csrfToken() {
  return (
    document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
    document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ||
    ""
  )
}

// POSTs the fields (an object or [name, value] pairs, a name may repeat) and
// returns the response. Fails with the request's error, and without sending
// anything while the browser is offline (specs/connection.md). ``headers``
// ask for a fragment or the like.
export function send(url, data = [], headers = {}) {
  if (isOffline()) return Promise.reject(new Error("offline"))
  const body = new FormData()
  for (const [name, value] of Array.isArray(data) ? data : Object.entries(data))
    body.append(name, value)
  return fetch(url, {
    method: "POST",
    body,
    headers: { "X-CSRFToken": csrfToken(), ...headers },
  }).then((response) => {
    succeeded()
    return response
  })
}

// Remembers the order of the children of containers (a drag moves them);
// the returned function puts them back
export function remember(containers) {
  const saved = [...containers].map((el) => [el, [...el.children]])
  return () => {
    for (const [container, children] of saved)
      for (const [index, child] of children.entries())
        container.insertBefore(child, container.children[index] || null)
  }
}

// For changes made on the page already (a drag): the page keeps what it
// shows, unless the request fails. Offline, the change is undone with
// ``undo`` (the banner says why); after an error, or without ``undo``, the
// page reloads so that it shows what the server has.
export function post(url, data, undo) {
  const fail = () => {
    if (undo && isOffline()) undo()
    else window.location.reload()
  }
  return send(url, data).then((response) => {
    if (!response.ok) window.location.reload()
  }, fail)
}
