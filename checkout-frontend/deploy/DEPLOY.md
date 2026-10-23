# Deploy the checkout on nginx

The setup follows the member portal pattern: **one build, one JSON file per domain, one small nginx file per domain** that includes a shared snippet.

```
/var/www/html/checkout/                          ← the build (unzip wlmd-checkout-build.zip here)
├── index.html
├── assets/                                      built JS + CSS
├── sites/
│   ├── checkout.mastertherapy.example.json      ← one config per domain
│   ├── checkout.harborwellness.example.json
│   └── checkout.glowhealth.example.json
└── logos/
    ├── checkout.mastertherapy.example/logo.svg, favicon.svg
    └── …

/home/geckos/NGINX_CONF/snippets/unified_checkout.conf   ← shared nginx config
/etc/nginx/sites-available/checkout.<brand>.conf          ← 5 lines per domain
```

The app always loads `/config.json`. The snippet maps it to `sites/$host.json`, so **the domain decides the brand**. There is no central list to maintain.

## Site config: `sites/<domain>.json`

```json
{
  "name": "Master Therapy",
  "domain": "checkout.mastertherapy.example",
  "websiteUrl": "https://mastertherapy.example",
  "siteId": "payment-test",
  "siteApiUrl": "https://wlmd-site-api-demo-0f89b1bb.fly.dev/api/v1/sites",
  "plansMethod": "GET",
  "logo": "/logos/checkout.mastertherapy.example/logo.svg",
  "favicon": "/logos/checkout.mastertherapy.example/favicon.svg",
  "supportEmail": "support@mastertherapy.example",
  "supportPhone": "",
  "font": "system",
  "layout": "split",
  "therapy": "Weight loss",
  "title": "Choose your weight loss plan",
  "intro": "A plan that fits you. Choose your medication, plan length and payment option.",
  "medicationOrder": ["Semaglutide", "Tirzepatide"],
  "testNotice": true,
  "paymentsEnabled": false,
  "memberPortal": false,
  "colors": {
    "primary": "#245844",
    "primaryHover": "#1b4535",
    "primaryLight": "#e7efe9",
    "buttonText": "#ffffff",
    "background": "#f5f4ef",
    "text": "#173c36"
  }
}
```

| Field | Required | What it does |
|---|---|---|
| `name` | ✅ | Brand name in the header, browser tab and footer |
| `domain` | ✅ | Must equal the file name (without `.json`) and the nginx `server_name` |
| `siteId` | ✅ | The backend site whose plans to sell. **Must exist on the backend** (today: `payment-test`) |
| `siteApiUrl` | ✅ | Site API base URL (without the site ID) |
| `plansMethod` | | `GET` today; `POST` once the backend supports it |
| `websiteUrl` | | The logo/name in the header links here |
| `logo`, `favicon` | | `/logos/<domain>/…` (PNG, SVG or ICO). The logo is shown 40px tall next to the name |
| `supportEmail`, `supportPhone` | | Footer and the "payment check" screen |
| `font` | | `system`, `serif` or `rounded` (or set `fontFamily` + `fontUrl` for a Google Font) |
| `layout` | | `split` (summary on the right) or `stacked` (single column) |
| `therapy`, `title`, `intro` | | Plan-page eyebrow, heading and subtitle |
| `medicationOrder` | | Which medication card comes first |
| `testNotice` | | Shows "Live payment test: your card will be charged…" |
| `memberPortal` | | `true` = the thank-you page shows **Create your patient account**, which opens a one-time member-portal invitation for that order (`POST /sessions/{id}/portal`). Turn on only after the site has a portal in the admin and `portal_site` in the backend `sites.json` |
| `paymentsEnabled` | | `false` = everything works except Pay/Express (nobody can be charged). `true` = live |
| `colors.primary` | ✅ | Buttons, selected cards, accents |
| `colors.primaryHover` | | Button hover (default: slightly darker primary) |
| `colors.primaryLight` | | Light tint for selected cards and badges (default: auto-tinted primary) |
| `colors.buttonText` | | Text on primary buttons (usually `#ffffff`) |
| `colors.background`, `colors.text` | | Page background and main text |

Edit a file on the server and refresh the page. No rebuild or nginx reload is needed. Check the JSON before saving:
```sh
python3 -m json.tool /var/www/html/checkout/sites/checkout.mastertherapy.example.json > /dev/null && echo OK
```

## First-time server setup

```sh
# 1. Build (on your Mac) — or use the wlmd-checkout-build.zip already in the folder
npm run package

# 2. Upload
scp wlmd-checkout-build.zip deploy/snippets/unified_checkout.conf deploy/sites-available/*.conf user@SERVER_IP:/tmp/

# 3. On the server
sudo mkdir -p /var/www/html/checkout
sudo unzip -o /tmp/wlmd-checkout-build.zip -d /var/www/html/checkout
sudo chown -R www-data:www-data /var/www/html/checkout

sudo cp /tmp/unified_checkout.conf /home/geckos/NGINX_CONF/snippets/unified_checkout.conf
sudo cp /tmp/checkout.*.conf /etc/nginx/sites-available/
for f in /etc/nginx/sites-available/checkout.*.conf; do sudo ln -sf "$f" /etc/nginx/sites-enabled/; done
sudo nginx -t && sudo systemctl reload nginx
```

If you keep the build somewhere else, change `root` at the top of `unified_checkout.conf`.

## Each domain's nginx file (like `member.trtcentral.com`)

```nginx
server {
    listen 80;
    server_name checkout.mastertherapy.example;
    include /home/geckos/NGINX_CONF/snippets/unified_checkout.conf;
    error_log /var/log/nginx/checkout.mastertherapy.example-error.log;
}
```

## Add a new brand

1. Create `sites/checkout.newbrand.com.json`. Copy an existing file and change `name`, `domain`, `siteId`, `logo`, `favicon` and `colors`.
2. Add the logo: `logos/checkout.newbrand.com/logo.png` (+ `favicon.ico`).
3. Add `/etc/nginx/sites-available/checkout.newbrand.com.conf` (the 5-line block above), symlink it into `sites-enabled`, then run `sudo nginx -t && sudo systemctl reload nginx`.
4. Point DNS at the server, then run `sudo certbot --nginx -d checkout.newbrand.com`.

Put new configs and logos in the repo too (`public/sites/`, `public/logos/`), so the next build includes them. Unzipping a build adds and overwrites files but never deletes server-only ones.

## Testing before DNS (by server IP)

Enable `checkout-ip-test.conf`. It answers requests for hosts nginx doesn't know, such as the server IP:

```
http://SERVER_IP/?site=checkout.mastertherapy.example
http://SERVER_IP/?site=checkout.harborwellness.example
http://SERVER_IP/?site=checkout.glowhealth.example
```

`?site=` only works on hosts without their own config. On a real brand domain it's ignored, so a customer can never switch brands. Remove the IP test file once the domains work. If another site already uses `default_server`, change its `listen` to another port such as `8080`.

Over plain http you can test the plan page, details, review and the live quote. **The payment step needs HTTPS**: Stripe's live card form and Apple Pay / Google Pay don't load on http.

## HTTPS

```sh
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d checkout.mastertherapy.example -d checkout.harborwellness.example -d checkout.glowhealth.example
```

## What the snippet does

| Path | Behaviour |
|---|---|
| `/` | the app (`no-cache`, so a new build shows immediately) |
| `/config.json` | `sites/$host.json`, never cached; 404 if the domain has no file |
| `/sites/*.json` | never cached (used by `?site=` testing) |
| `/assets/*` | cached for a year (hashed file names) |
| `/logos/*` | cached for 1 hour |
| anything else | 404 |

It also gzips responses and sends basic security headers. This exact config was tested with nginx 1.24 using the three example domains and an IP test host.

## Before going live

- [ ] Real domains in the file names, `domain`, `server_name` and the logo folders
- [ ] `siteId` matches each brand's site on the backend
- [ ] `"testNotice": false`
- [ ] `"paymentsEnabled": true`
- [ ] HTTPS on every domain; IP test block removed
- [ ] Apple Pay: each domain registered with Stripe
- [ ] One real low-value order per brand, confirmed in Sticky

## Troubleshooting

| You see | Cause / fix |
|---|---|
| "No site is configured for …" | No `sites/<that host>.json`. The file name must match the domain exactly (including `www.` if used) |
| "… is not valid JSON" | Run the `json.tool` check above |
| "These plans are temporarily unavailable" | Site API unreachable, or `siteId` doesn't exist on the backend |
| Logo missing | Check the `logo` path and that the file is in `logos/<domain>/` |
| Blank page | Upload the *contents* of the zip, not a `dist` folder inside it. Check the browser console |
| Payment form doesn't load | The page is on http (needs https), or Apple Pay domain isn't registered |
| 403 Forbidden | `sudo chown -R www-data:www-data /var/www/html/checkout` |
| Check nginx logs | `/var/log/nginx/<domain>-error.log` |
