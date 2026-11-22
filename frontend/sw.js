// The service worker (specs/web-push.md), served at /sw.js by Django as it
// is, not bundled: it only shows push notifications and opens their URL on
// a tap. No fetch handler: nothing is cached (specs/pwa.md).

// A push: {title, body, tag, url, icon} (biwak.activity.push.content());
// the tag replaces an earlier push about the same item
self.addEventListener("push", (event) => {
  let data = {}
  try {
    data = event.data?.json() || {}
  } catch {
    // Not ours: shown as Biwak's anyway, browsers require a notification
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Biwak", {
      body: data.body || "",
      tag: data.tag,
      icon: data.icon,
      data: { url: data.url || "/" },
    }),
  )
})

// A tap: an open Biwak window goes to the URL, or a new one opens
self.addEventListener("notificationclick", (event) => {
  event.notification.close()
  const url = new URL(event.notification.data?.url || "/", self.location.origin)
  if (url.origin !== self.location.origin) return
  event.waitUntil(open(url.href))
})

async function open(url) {
  const windows = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  })
  const existing = windows.find(
    (client) => new URL(client.url).origin === self.location.origin,
  )
  if (existing) {
    try {
      const client = await existing.focus()
      await client.navigate(url)
      return
    } catch {
      // Not controlled by this worker (opened before it): a new window
    }
  }
  await self.clients.openWindow(url)
}
