// Filters remembered (specs/ui-round-3.md, section 4): a filter page (its
// form has data-remember) stores its query in the browser, per path, when it
// loads with one. The links of the top bar (and the palette's links, through
// withFilters()) go to such a page with the stored query. "Reset filters"
// (data-reset-filters) forgets it. Other links keep their own query.
const PREFIX = "filters:"
// Where the page is, not what it filters
const NOT_FILTERS = ["page", "before", "grouping"]

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

if (document.querySelector("form[data-remember]")) {
  const query = filtersOf(window.location.search)
  if (query) write(window.location.pathname, query)
}

document.addEventListener("click", (event) => {
  const link = event.target.closest?.("[data-reset-filters]")
  if (link) write(new URL(link.href, window.location.href).pathname, "")
})

for (const link of document.querySelectorAll(".wb-nav-links a[href]")) {
  link.setAttribute("href", withFilters(link.getAttribute("href")))
}
