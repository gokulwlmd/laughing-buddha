// Site config: one flat JSON file per domain in sites/<domain>.json.
// The app loads "config.json"; nginx maps it to sites/$host.json (see deploy/),
// and the Vite dev server does the same locally. Edit a file + refresh, no rebuild.

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);
const OVERRIDE_KEY = 'wlmd:site-override';
const DOMAIN = /^[a-z0-9.-]{1,253}$/;

export class SiteConfigError extends Error {}

async function fetchConfig(path) {
  const res = await fetch(new URL(path, document.baseURI), { cache: 'no-store' });
  if (!res.ok || !(res.headers.get('content-type') || '').includes('json')) return null;
  try {
    return await res.json();
  } catch {
    throw new SiteConfigError(`${path} is not valid JSON.`);
  }
}

// ?site=<domain> loads sites/<domain>.json. Only honoured on localhost, or on a
// host that has no config of its own (e.g. testing by server IP); a real brand
// domain always shows its own brand. Remembered for the browser tab.
function requestedSite() {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('site');
    if (fromUrl) sessionStorage.setItem(OVERRIDE_KEY, fromUrl.toLowerCase());
    return (fromUrl || sessionStorage.getItem(OVERRIDE_KEY) || '').toLowerCase() || null;
  } catch {
    return null;
  }
}

export async function loadSiteConfig(hostname = window.location.hostname) {
  const host = hostname.toLowerCase();
  let raw = await fetchConfig('config.json');
  const requested = requestedSite();
  if (requested && (!raw || LOCAL_HOSTS.has(host))) {
    if (!DOMAIN.test(requested)) throw new SiteConfigError(`"${requested}" is not a valid site.`);
    raw = await fetchConfig(`sites/${requested}.json`);
    if (!raw) throw new SiteConfigError(`No site config found for ${requested}.`);
  }
  // Never fall back to another brand for an unknown domain.
  if (!raw) throw new SiteConfigError(`No site is configured for ${hostname}.`);
  return normalize(raw, host);
}

// "/logos/x.png" is relative to the app folder, so the build also works in a subfolder.
function asset(path) {
  if (!path) return '';
  if (/^(https?:)?\/\//.test(path) || path.startsWith('data:')) return path;
  return new URL('.' + (path.startsWith('/') ? path : '/' + path), document.baseURI).href;
}

// Flat per-domain file → the shape the views use.
export function normalize(c, host = '') {
  // "name", colours, logo and support details are optional: anything left out
  // comes from the brand design saved in the admin (returned by GET /plans).
  for (const field of ['siteId', 'siteApiUrl']) {
    if (!c[field]) throw new SiteConfigError(`Site config for ${c.domain || host} is missing "${field}".`);
  }
  const colors = c.colors || {};
  return {
    key: (c.domain || host).toLowerCase(),
    domain: c.domain || host,
    siteId: c.siteId,
    api: { baseUrl: c.siteApiUrl, plansMethod: c.plansMethod || 'GET' },
    favicon: asset(c.favicon || c.logo),
    brand: {
      name: c.name,
      logo_url: asset(c.logo),
      website_url: c.websiteUrl || '',
      color: colors.primary,
      hover_color: colors.primaryHover,
      light_color: colors.primaryLight,
      button_text_color: colors.buttonText,
      background_color: colors.background,
      text_color: colors.text,
      font: c.font,
      font_family: c.fontFamily,
      font_url: c.fontUrl,
      layout: c.layout,
      support_email: c.supportEmail || '',
      support_phone: c.supportPhone || '',
    },
    plans: {
      therapy: c.therapy,
      title: c.title,
      intro: c.intro,
      medicationOrder: c.medicationOrder || [],
      testNotice: c.testNotice === true,
    },
    checkout: { paymentsEnabled: c.paymentsEnabled === true, memberPortal: c.memberPortal === true },
  };
}

// Same defaults and fonts as the original checkout (web/brand-design-v2.js).
const DEFAULTS = {
  color: '#245844',
  background_color: '#f5f4ef',
  text_color: '#173c36',
  button_text_color: '#ffffff',
  font: 'system',
  layout: 'split',
};
export const FONTS = {
  system: '"Red Hat Display", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  serif: 'Georgia, "Times New Roman", serif',
  rounded: '"Trebuchet MS", Arial, sans-serif',
};
const HEX = /^#[0-9a-f]{6}$/i;

const filled = (o) => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ''));

// Priority: this domain's JSON → the admin's brand design (from GET /plans) → defaults.
export function brandOf(site, catalog) {
  const admin = filled(catalog?.branding);
  if (admin.logo_url) admin.logo_url = asset(admin.logo_url);
  const b = { ...DEFAULTS, ...admin, ...filled(site.brand) };
  if (!b.name) b.name = catalog?.site_name || 'Checkout';
  return b;
}

// Plan-page wording and the test notice fall back to the catalog the same way.
export function withCatalog(site, catalog) {
  if (!catalog) return site;
  const p = site.plans || {};
  return {
    ...site,
    plans: {
      ...p,
      title: p.title || catalog.title || undefined,
      therapy: p.therapy || catalog.therapy || undefined,
      testNotice: p.testNotice || catalog.demo === true,
    },
  };
}

// Inline CSS variables for a view root (the ported CSS defines its own defaults
// on that root, so the brand must be applied on the same element).
export function brandStyle(brand) {
  const style = {};
  for (const [field, prop] of [
    ['color', '--brand-color'],
    ['background_color', '--brand-bg'],
    ['text_color', '--brand-text'],
    ['button_text_color', '--brand-button-text'],
    ['hover_color', '--brand-hover'],
    ['light_color', '--brand-light'],
  ]) {
    if (HEX.test(brand[field] || '')) style[prop] = brand[field];
  }
  style['--brand-font'] = brand.font_family || FONTS[brand.font] || FONTS.system;
  return style;
}

// data-* flags turn on the optional hover/light colour overrides in base.css.
export function brandFlags(brand) {
  return {
    'data-hover': HEX.test(brand.hover_color || '') ? '' : undefined,
    'data-light': HEX.test(brand.light_color || '') ? '' : undefined,
  };
}

export function layoutOf(brand) {
  return brand.layout === 'stacked' ? 'stacked' : 'split';
}

export function applyDocument(site, brand) {
  document.title = `${brand.name} · Secure checkout`;
  document.body.style.background = HEX.test(brand.background_color || '') ? brand.background_color : DEFAULTS.background_color;
  if (brand.font_url && !document.querySelector('link[data-brand-font]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = brand.font_url;
    link.dataset.brandFont = '1';
    document.head.append(link);
  }
  const favicon = site.favicon || brand.logo_url;
  if (favicon) {
    let icon = document.querySelector('link[rel="icon"]');
    if (!icon) {
      icon = document.createElement('link');
      icon.rel = 'icon';
      document.head.append(icon);
    }
    icon.href = favicon;
  }
}
