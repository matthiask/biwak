// Copy buttons: data-copy="#selector" copies the value of that field

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]")
  if (!button) return
  const field = document.querySelector(button.dataset.copy)
  if (!field) return
  field.select()
  try {
    await navigator.clipboard.writeText(field.value)
  } catch {
    // Selected, so Ctrl+C works
  }
})
