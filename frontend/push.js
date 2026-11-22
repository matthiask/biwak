// Push notifications on this device (specs/web-push.md), in the settings'
// Notifications section: "Notify me on this device" asks the browser's
// permission (only after the click), registers the service worker
// (frontend/sw.js at /sw.js) and sends the subscription to Django; the list
// of devices marks this one, whose "Remove" also unsubscribes the browser.
// The texts are on the page (data-push-state); without support the button
// stays hidden, on an iPhone not on the home screen the page says why.
import { csrfToken } from "./http.js"

const section = document.querySelector("[data-push]")
if (section) setUp()

function supported() {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  )
}

// Safari on an iPhone or iPad offers pushes only to apps on the home screen
function onIPhone() {
  return /iPhone|iPad|iPod/.test(navigator.userAgent)
}

function show(state) {
  for (const element of section.querySelectorAll("[data-push-state]"))
    element.hidden = element.dataset.pushState !== state
}

// The VAPID public key (base64url) as the bytes PushManager takes
function keyBytes(key) {
  const base64 = (key + "=".repeat((4 - (key.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/")
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0))
}

// The JSON of PushSubscription.toJSON()
function sendSubscription(method, json) {
  return fetch(section.dataset.pushUrl, {
    method,
    body: JSON.stringify(json),
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken(),
    },
  })
}

async function setUp() {
  const button = section.querySelector("[data-push-subscribe]")
  if (!supported()) {
    if (onIPhone()) show("home-screen")
    return
  }
  // Not registering anything before the click: only looking
  const registration = await navigator.serviceWorker.getRegistration("/")
  const subscription = await registration?.pushManager.getSubscription()
  const row =
    subscription &&
    [...section.querySelectorAll("[data-push-endpoint]")].find(
      (row) => row.dataset.pushEndpoint === subscription.endpoint,
    )
  if (row) {
    row.querySelector("[data-push-this]").hidden = false
    row.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault()
      remove(subscription)
    })
  } else if (Notification.permission === "denied") {
    show("blocked")
  } else {
    button.hidden = false
  }
  button.addEventListener("click", () => subscribe(button))
}

async function subscribe(button) {
  button.disabled = true
  show(null)
  try {
    const permission = await Notification.requestPermission()
    if (permission !== "granted") {
      show(permission === "denied" ? "blocked" : null)
      return
    }
    await navigator.serviceWorker.register("/sw.js")
    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(section.dataset.push),
    })
    const response = await sendSubscription("POST", subscription.toJSON())
    if (!response.ok) throw new Error(`${response.status}`)
    window.location.reload()
  } catch {
    show("failed")
  } finally {
    button.disabled = false
  }
}

async function remove(subscription) {
  try {
    const json = subscription.toJSON()
    await subscription.unsubscribe()
    const response = await sendSubscription("DELETE", json)
    if (!response.ok) throw new Error(`${response.status}`)
    window.location.reload()
  } catch {
    show("failed")
  }
}
