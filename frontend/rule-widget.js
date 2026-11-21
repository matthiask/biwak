// The rule widget (biwak/templates/forms/rule_widget.html,
// specs/rule-widget.md): shows the parts of the chosen frequency, and the
// end date and count (when the form has them) only for a rule that repeats.
// Without this script all parts show and the form still posts all of them;
// the description comes from the server through htmx (hx-* attributes in
// the template). Widgets htmx brings in later are set up too.

function sync(widget) {
  const select = widget.querySelector("[data-rule-frequency]")
  const replace = widget.querySelector("[data-rule-replace]")
  for (const part of widget.querySelectorAll("[data-rule-part]")) {
    part.hidden = !part.dataset.rulePart.split(" ").includes(select.value)
  }
  // A rule set elsewhere stays as it is until "Replace" is pressed
  const elsewhere = replace && !replace.checked
  widget.querySelector("[data-rule-parts]").hidden = elsewhere
  // ... and it repeats, so its end shows
  for (const ends of widget.querySelectorAll("[data-rule-ends]"))
    ends.hidden = !(elsewhere || select.value)
}

function setUp(widget) {
  if (widget.dataset.ruleReady) return
  widget.dataset.ruleReady = "true"
  sync(widget)
  widget.addEventListener("change", () => sync(widget))
  widget.closest("form")?.addEventListener("reset", () =>
    setTimeout(() => {
      sync(widget)
      widget.dispatchEvent(new Event("change", { bubbles: true }))
    }),
  )
}

function setUpAll(root) {
  if (root.matches?.("[data-rule-widget]")) setUp(root)
  for (const widget of root.querySelectorAll?.("[data-rule-widget]") ?? [])
    setUp(widget)
}

setUpAll(document)
document.addEventListener("htmx:after:process", (event) =>
  setUpAll(event.target),
)
