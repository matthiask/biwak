// Filters remembered (specs/ui.md, "Filters and view choices"): a filter page (its
// form or page has data-remember; view choices like the grouping and the
// order are query parameters too) stores its query in the browser, per
// path, whenever it loads: going back to the defaults (the empty choices, an
// empty query) forgets the stored one. The links marked data-restore-filters (the top bar's, the
// project page's "All to-dos") and the palette's links (through
// withFilters()) go to such a page with the stored query. "Reset filters"
// (data-reset-filters) forgets it. Other links keep their own query.
const PREFIX = "filters:"
// Where the page is, not what it filters
const NOT_FILTERS = ["page", "before", "archived"]

function read(path) {
  try {
    return localStorage.getItem(PREFIX + path) || ""
  } catch {
    return ""
  }
}

function write(path, query) {
  try {
    if (query) localStorage.setItem(PREFIX + path, query)
    else localStorage.removeItem(PREFIX + path)
  } catch {
    // Storage may be blocked: filters are just not remembered
  }
}

export function withFilters(href) {
  const url = new URL(href, window.location.href)
  if (url.origin !== window.location.origin) return href
  const stored = read(url.pathname)
  return stored ? `${url.pathname}?${stored}` : href
}

function filtersOf(search) {
  const params = new URLSearchParams(search)
  for (const name of NOT_FILTERS) params.delete(name)
  return params.toString()
}

if (document.querySelector("[data-remember]")) {
  write(window.location.pathname, filtersOf(window.location.search))
}

document.addEventListener("click", (event) => {
  const link = event.target.closest?.("[data-reset-filters]")
  if (link) write(new URL(link.href, window.location.href).pathname, "")
})

for (const link of document.querySelectorAll("a[data-restore-filters][href]")) {
  link.setAttribute("href", withFilters(link.getAttribute("href")))
}
