// Per-tab checkout persistence so refreshes and bank redirects resume the
// same session. sessionStorage clears when the tab closes. The session token
// is scoped to this one checkout (see API docs); never put it in a URL.

const key = (site) => `wlmd:checkout:${site.key}`;

export function loadCheckout(site) {
  try {
    const raw = sessionStorage.getItem(key(site));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveCheckout(site, data) {
  try {
    if (data) sessionStorage.setItem(key(site), JSON.stringify(data));
    else sessionStorage.removeItem(key(site));
  } catch {
    /* storage unavailable: checkout still works, just won't survive refresh */
  }
}
