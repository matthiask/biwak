# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

- **Wording of the project choice** (`notifications.md`, 2026-11-22):
  with "only when tagged" the default, "Notified by default" became
  "Notified of everything new" ("Über alles Neue benachrichtigt"),
  listed second.
- **Push notifications' content** (`web-push.md`, 2026-11-22): the
  lantern's entry: title the item's title ("To-dos" for one "Assign…"),
  body the lantern's line ("Ada commented: You were mentioned."), its
  excerpt (about 200 characters, not strictly the first line) and the
  project.
- **Only what came after subscribing** (`web-push.md`, 2026-11-22): a
  notification pushes only to people with a device subscribed before it,
  so turning pushes on doesn't bring old mentions.
- **Push failures** (`web-push.md`, 2026-11-22): when every device of a
  person fails (not 404/410), the push is tried again on the next runs,
  until 12 hours (the TTL) have passed.
- **Push wording** (`web-push.md`, 2026-11-22): "Push notifications"
  (heading), "When you're mentioned or assigned, also while Biwak isn't
  open; not in your quiet hours or while you're away.", "Notify me on
  this device", "Notifications are blocked for Biwak in this browser's
  settings.", "Push notifications on this device are off." after
  signing out; German "Push-Benachrichtigungen", "Auf diesem Gerät
  benachrichtigen", "Benachrichtigungen sind für Biwak in den
  Einstellungen dieses Browsers blockiert.", "Push-Benachrichtigungen
  auf diesem Gerät sind aus."
