// The rule widget (biwak/templates/forms/rule_widget.html,
// specs/rule-widget.md): shows the parts of the chosen frequency. Without
// this script all parts show and the form still posts all of them; the
// description comes from the server through htmx (hx-* attributes in the
// template).

function sync(widget) {
  const select = widget.querySelector("[data-rule-frequency]")
  const replace = widget.querySelector("[data-rule-replace]")
  for (const part of widget.querySelectorAll("[data-rule-part]")) {
    part.hidden = !part.dataset.rulePart.split(" ").includes(select.value)
  }
  // A rule set elsewhere stays as it is until "Replace" is pressed
  widget.querySelector("[data-rule-parts]").hidden = replace && !replace.checked
}

for (const widget of document.querySelectorAll("[data-rule-widget]")) {
  sync(widget)
  widget.addEventListener("change", () => sync(widget))
  widget.closest("form")?.addEventListener("reset", () =>
    setTimeout(() => {
      sync(widget)
      widget.dispatchEvent(new Event("change", { bubbles: true }))
    }),
  )
}
