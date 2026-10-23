"""Multi-site public Site API; real payments remain on the existing Stripe v2 app.

No processor credentials, production DB, card widget or payment write client.
Each site maps to one PUBLIC plan-checkout publication on the live app
(GET /api/plans/<catalog>); only those publications can be read or selected.
Sites are listed in a registry file (demo/sites.json by default), so adding a
site is a configuration change, not a code change.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import html
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import quote, urlencode
from urllib.request import Request as URLRequest, build_opener, HTTPRedirectHandler
from decimal import Decimal, InvalidOperation
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from demo.session_api import SessionStore, CheckoutTransport, install_session_api, PUBLIC_UPSTREAM
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, ConfigDict, Field
from demo.site_api import Catalog, Plan, Branding, SiteInfo, DomainSite

HERE = Path(__file__).parent
LIVE_ORIGIN = 'https://wlmd-stripe-test-0f89b1bb.fly.dev'
# The original single site; kept as the built-in default and for compatibility.
PUBLISHED_PLAN = 'site-api-public-weight-loss'
SITE_ID = 'payment-test'
DEFAULT_SITES = {SITE_ID: {'name': 'Master Therapy Payment Test', 'catalog': PUBLISHED_PLAN, 'payment_test_only': True}}
DEFAULT_SITES_FILE = HERE / 'sites.json'
CATALOG_FRESH_SECONDS = 60
CATALOG_MAX_AGE_SECONDS = 120
SITE_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,60}$')
CATALOG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,60}$')
DOMAIN_PATTERN = re.compile(r'^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$')
CURRENCY_SYMBOLS = {'USD': '$', 'CAD': 'CA$', 'AUD': 'A$', 'NZD': 'NZ$', 'EUR': '€', 'GBP': '£', 'CHF': 'CHF '}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Unexpected catalog redirect')


def read_live_catalog(catalog=PUBLISHED_PLAN):
    if not CATALOG_PATTERN.fullmatch(catalog):
        raise ValueError('Invalid catalog key')
    req = URLRequest(LIVE_ORIGIN+'/api/plans/'+quote(catalog,safe=''),headers={'Accept':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=25) as response:
        return json.load(response)


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str = Field(min_length=1,max_length=80)

class CheckoutURL(BaseModel):
    checkout_url: str


def validate_sites(raw):
    """Validate a registry mapping and return a normalised copy (fail closed)."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError('The site registry must be a non-empty object')
    sites, domains = {}, {}
    for site_id, entry in raw.items():
        if site_id.startswith('_'):
            continue  # "_readme"-style comments
        if not SITE_ID_PATTERN.fullmatch(site_id) or not isinstance(entry, dict):
            raise ValueError(f'Invalid site id: {site_id!r}')
        name, catalog = entry.get('name'), entry.get('catalog')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError(f'Site {site_id} needs a name')
        if not isinstance(catalog, str) or not CATALOG_PATTERN.fullmatch(catalog):
            raise ValueError(f'Site {site_id} needs the id of its public plan checkout in "catalog"')
        site_domains = [d.strip().lower() for d in entry.get('domains', [])]
        for domain in site_domains:
            if not DOMAIN_PATTERN.fullmatch(domain):
                raise ValueError(f'Site {site_id} has an invalid domain: {domain!r}')
            if domain in domains:
                raise ValueError(f'Domain {domain} is assigned to both {domains[domain]} and {site_id}')
            domains[domain] = site_id
        portal_site = entry.get('portal_site')
        if portal_site is not None and (not isinstance(portal_site, str) or not SITE_ID_PATTERN.fullmatch(portal_site)):
            raise ValueError(f'Site {site_id} has an invalid "portal_site" (the member portal site id from the admin)')
        sites[site_id] = {'name': name.strip(), 'catalog': catalog, 'payment_test_only': entry.get('payment_test_only') is True,
            'domains': site_domains, 'enabled': entry.get('enabled', True) is not False, 'portal_site': portal_site}
    if not sites:
        raise ValueError('The site registry has no sites')
    return sites


class SiteRegistry:
    """site_id -> {name, catalog, payment_test_only, domains, enabled}.

    Static when created from a dict (tests); otherwise read from a JSON file and
    re-read when the file changes. A broken edit keeps the last valid registry.
    """
    def __init__(self, sites=None, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.mtime = None
        self.sites = validate_sites(sites if sites is not None else DEFAULT_SITES)
        self.error = None
        if self.path:
            self._reload(initial=True)

    def _reload(self, initial=False):
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            if initial:
                raise ValueError(f'Site registry not found: {self.path}') from None
            return
        if mtime == self.mtime:
            return
        try:
            sites = validate_sites(json.loads(self.path.read_text()))
        except (ValueError, json.JSONDecodeError) as exc:
            if initial:
                raise
            self.error = str(exc)  # keep serving the last valid registry
            return
        self.sites, self.mtime, self.error = sites, mtime, None

    def all(self):
        if self.path:
            with self.lock:
                self._reload()
        return self.sites

    def get(self, site_id):
        site = self.all().get(site_id)
        return site if site and site['enabled'] else None

    def by_domain(self, domain):
        domain = domain.strip().lower().removeprefix('www.')
        for site_id, site in self.all().items():
            if site['enabled'] and domain in site['domains']:
                return site_id
        return None


def registry_from_environment():
    raw = os.environ.get('SITE_API_SITES')
    if raw:
        return SiteRegistry(sites=json.loads(raw))
    path = os.environ.get('SITE_API_SITES_FILE')
    if path:
        return SiteRegistry(path=path)
    if DEFAULT_SITES_FILE.exists():
        return SiteRegistry(path=DEFAULT_SITES_FILE)
    return SiteRegistry()


def _money(price, currency):
    symbol = CURRENCY_SYMBOLS.get(currency)
    return f'{symbol}{price}' if symbol else f'{price} {currency}'


def _plan_for(entry, option, medication):
    months = entry.get('durationMonths')
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 120:
        raise ValueError('Invalid product duration')
    currency = str(entry.get('currency', '')).upper()
    if not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('Invalid currency')
    try:
        price = Decimal(str(option.get('upfrontPrice') or option['basePrice'])).quantize(Decimal('0.01'))
    except (InvalidOperation, KeyError):
        raise ValueError('Invalid price') from None
    if not price.is_finite() or price <= 0:
        raise ValueError('Invalid price')
    days = int(option.get('days') or 0)
    if 'prepaidCycles' in option and option.get('prepaidCycles'):
        # Prepaid: N deliveries `days` apart, paid upfront; optional renewal of the whole plan.
        cycles = int(option['prepaidCycles'])
        subscription = bool(option.get('renewal'))
        renewal = option.get('renewalDays') if subscription else None
        if cycles < 1 or cycles > 52 or (cycles > 1 and days <= 0) or (subscription and (not isinstance(renewal, int) or renewal <= 0)):
            raise ValueError('Invalid prepaid schedule')
        shipments = [n * days for n in range(cycles)]
    else:
        cycles = 1
        subscription = bool(option.get('recurring'))
        renewal = days if subscription else None
        if subscription and days <= 0:
            raise ValueError('Invalid renewal schedule')
        shipments = [0]
    amount = _money(f'{price}', currency)
    terms = f'Pay {amount} upfront. ' + (f'Renews every {renewal} days.' if subscription else 'One-time purchase. No automatic renewal.')
    if cycles > 1:
        terms += f' {cycles} prepaid cycles, {days} days apart, with no additional product charges.'
    return dict(name=f'{medication} — {months}-month plan', medication=medication, duration_months=months,
        purchase_type='subscription' if subscription else 'once', price=f'{price}', currency=currency,
        renewal_days=renewal, shipment_days=shipments, terms=terms)


def _plan_id(sku, option, multiple):
    base = re.sub(r'[^a-z0-9-]+', '-', sku.lower()).strip('-')
    if not multiple:
        return base
    # Several payment choices on one SKU: keep ids stable and readable.
    return f"{base}-{hashlib.sha256(option['key'].encode()).hexdigest()[:6]}"


def map_catalog(data, site_id=SITE_ID, site=None):
    """Published plan checkout -> (Catalog, {plan_id: hosted child checkout URL}).

    Fails closed: an unexpected catalog id, missing fields or an invalid price or
    schedule rejects the whole catalog rather than showing a wrong plan.
    """
    site = site or DEFAULT_SITES.get(site_id) or {'name': site_id, 'catalog': data.get('id'), 'payment_test_only': False}
    if data.get('id') != site['catalog']:
        raise ValueError('Unexpected catalog for this site')
    if site.get('payment_test_only') and not data.get('paymentTestOnly'):
        raise ValueError('Expected a payment-test catalog')
    names = {t['id']:t['name'] for t in data.get('treatments', [])}
    plans, routes = [], {}
    for entry in data.get('entries', []):
        if not entry.get('available'):
            continue
        options = [o for o in entry.get('options', []) if not o.get('blockedReason')]
        medication = names.get(entry.get('treatmentId'))
        if not medication:
            raise ValueError('Unknown treatment')
        purchase_id = entry.get('purchaseOptionId', '')
        # Same identity as plans.choice_id on the live app: one public child per SKU choice.
        identity = data['id']+'\0'+entry['sku']+('\0'+purchase_id if purchase_id else '')
        child_id = 'choice-'+hashlib.sha256(identity.encode()).hexdigest()[:32]
        for option in options:
            pid = _plan_id(entry['sku'], option, len(options) > 1)
            if pid in routes:
                continue  # the same SKU choice listed under another purchase option
            plans.append(Plan(plan_id=pid, **_plan_for(entry, option, medication)))
            # Public children: the final URL works in a fresh browser without cookies.
            routes[pid] = LIVE_ORIGIN+'/c/'+child_id+'?'+urlencode({'selection':option['key']})
    if not plans:
        raise ValueError('No plans are currently available for this site')
    b = data.get('branding') or {}
    color = b.get('color') if re.fullmatch(r'#[0-9a-fA-F]{6}', str(b.get('color', ''))) else '#245844'
    branding = Branding(**{k: v for k, v in b.items() if k in Branding.model_fields and isinstance(v, str)})
    return Catalog(site_id=site_id, site_name=site['name'], color=color, demo=bool(data.get('paymentTestOnly')),
        title=data.get('title') or None, therapy=data.get('therapy') or None, branding=branding, plans=plans), routes


def _catalog_reader(read_catalog):
    """Accept read_catalog(catalog_key) or the older single-site read_catalog()."""
    try:
        params = [p for p in inspect.signature(read_catalog).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)]
    except (TypeError, ValueError):
        return read_catalog
    if params:
        return read_catalog
    return lambda catalog: read_catalog()


def create_public_app(origin=None, read_catalog=read_live_catalog, clock=time.time, session_store=None, transport=None, warm_catalog=None, sites=None):
    """read_catalog(catalog_key) returns a published plan checkout; sites is a SiteRegistry,
    a {site_id: {...}} dict, or None for the environment/default registry."""
    origin = origin or os.environ['DEMO_PUBLIC_ORIGIN']
    if not origin.startswith('https://') or origin.rstrip('/') != origin or '/' in origin[8:]:
        raise ValueError('DEMO_PUBLIC_ORIGIN must be an HTTPS origin')
    registry = sites if isinstance(sites, SiteRegistry) else SiteRegistry(sites=sites) if sites is not None else registry_from_environment()
    live_reader = read_catalog is read_live_catalog
    read_catalog = _catalog_reader(read_catalog)
    @asynccontextmanager
    async def lifespan(app):
        stop=threading.Event()
        def maintain_catalog():
            # Read-only display data for every enabled site. Keep the existing
            # freshness/hard-age limits; an upstream outage never extends the
            # lifetime of an old catalog, and one failing site never blocks others.
            while not stop.is_set():
                for site_id, config in list(registry.all().items()):
                    if stop.is_set():break
                    if not config['enabled']:continue
                    try:refresh(site_id,background=True)
                    except HTTPException:pass  # site disabled/removed meanwhile
                if stop.wait(15):break
        enabled=warm_catalog if warm_catalog is not None else (live_reader and session_store is not None)
        worker=threading.Thread(target=maintain_catalog,daemon=True) if enabled else None
        if worker:worker.start()
        try:yield
        finally:
            stop.set()
            if worker:await asyncio.to_thread(worker.join,30)
            if hasattr(transport,'close'):transport.close()

    app = FastAPI(title='Site API · live checkout demo',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.mount('/assets',StaticFiles(directory=HERE/'web'),name='assets')
    caches = {}; sessions = {}; lock = threading.Lock()
    state_dir=os.environ.get('DEMO_SESSION_STATE_DIR')
    session_store=session_store or (SessionStore(state_dir) if state_dir else None)
    transport=transport or CheckoutTransport(os.environ.get('CHECKOUT_UPSTREAM_ORIGIN',PUBLIC_UPSTREAM))
    allowed_origins=tuple(x.strip() for x in os.environ.get('SITE_API_ALLOWED_ORIGINS','').split(',') if x.strip())
    for allowed in allowed_origins:
        if allowed != '*' and (not allowed.startswith('https://') or allowed.rstrip('/')!=allowed or '/' in allowed[8:]):
            raise ValueError('SITE_API_ALLOWED_ORIGINS must contain HTTPS origins or *')
    app.add_middleware(CORSMiddleware,allow_origins=[origin,*allowed_origins],allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'],expose_headers=['Server-Timing'])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(req,exc):
        return JSONResponse({'detail':'Invalid checkout request. Use the documented fields; do not send card details.'},status_code=422)

    def site(site_id):
        config = registry.get(site_id) if SITE_ID_PATTERN.fullmatch(site_id or '') else None
        if not config:
            raise HTTPException(404,'Site not found')
        return config

    def cache_for(site_id):
        with lock:
            return caches.setdefault(site_id, {'refresh_lock': threading.Lock()})

    def refresh(site_id, background=False):
        # Only catalog reads run here. Never cache authorization or payment state.
        config = site(site_id); cache = cache_for(site_id); refresh_lock = cache['refresh_lock']
        if not refresh_lock.acquire(blocking=not background):
            return
        try:
            with lock:
                if cache.get('expires',0) > clock() and cache.get('catalog') == config['catalog']:
                    return
            try:
                value = map_catalog(read_catalog(config['catalog']), site_id, config)
            except Exception:
                with lock:
                    cache['retry_at'] = clock()+3
                if not background:
                    raise HTTPException(503,'The connected checkout is temporarily unavailable. Please try again shortly.') from None
                return
            with lock:
                cache.update(value=value,catalog=config['catalog'],expires=clock()+CATALOG_FRESH_SECONDS,usable_until=clock()+CATALOG_MAX_AGE_SECONDS,retry_at=0)
        finally:
            refresh_lock.release()

    def current(site_id=SITE_ID):
        config = site(site_id); cache = cache_for(site_id)
        with lock:
            now=clock()
            same=cache.get('catalog')==config['catalog']  # the registry may point a site at a new catalog
            value=cache.get('value') if same else None
            fresh=same and cache.get('expires',0)>now
            usable=same and cache.get('usable_until',0)>now
            retry=cache.get('retry_at',0)>now
        if value and fresh:
            return value
        if value and usable:
            # A periodic upstream read must not freeze the customer page.
            # Display data has a hard 120-second age limit; the real checkout
            # still recalculates/revalidates before any authorization/capture.
            if not retry and not cache['refresh_lock'].locked():
                threading.Thread(target=refresh,args=(site_id,),kwargs={'background':True},daemon=True).start()
            return value
        refresh(site_id)
        with lock:
            return cache['value']

    @app.middleware('http')
    async def headers(req,call_next):
        started=time.perf_counter()
        response = await call_next(req)
        response.headers['Server-Timing']=f'app;dur={(time.perf_counter()-started)*1000:.1f}'
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
        return response

    @app.get('/health',include_in_schema=False)
    def health():
        return {'status':'running','mode':'site-payment-api','processor_credentials':False,'session_storage_configured':session_store is not None,
            'sites':len([1 for s in registry.all().values() if s['enabled']]),'registry_error':registry.error}

    @app.get('/',include_in_schema=False,response_class=HTMLResponse)
    def frontend():
        source = (HERE/'web/index.html').read_text().replace('__API_ORIGIN__',html.escape(origin,quote=True))
        source = source.replace('INTERACTIVE DEMO · NO PAYMENTS','LIVE PAYMENT DEMO · REAL CHARGES')
        options = ''.join(f'<option value="{html.escape(k,quote=True)}">{html.escape(v["name"])}</option>'
            for k,v in registry.all().items() if v['enabled'])
        source = source.replace('<label class="site-switch">Sample site<select id="site"><option value="willow-health">Willow Health</option><option value="harbor-wellness">Harbor Wellness</option></select></label>',
            f'<label class="site-switch">Connected site<select id="site">{options}</select></label>')
        source = source.replace('This demo never asks for your card.','Opens our real Stripe v2 checkout.<br>Payment tests only. No medication is shipped.')
        source = source.replace('Sample plans · No orders or charges','Live gateway · Real charges if you pay')
        source = source.replace('<meta name="api-origin"','<meta name="payment-mode" content="real"><meta name="api-origin"')
        return HTMLResponse(source)

    @app.get('/api/v1/domains/{domain}',response_model=DomainSite,tags=['0. Find your site'])
    def site_for_domain(domain:str):
        """Which site serves this checkout domain (from the site registry's "domains"). Use the returned site_id in every other call."""
        site_id = registry.by_domain(domain) if len(domain) <= 253 else None
        if not site_id:
            raise HTTPException(404,'No site is configured for this domain')
        return DomainSite(domain=domain.strip().lower().removeprefix('www.'),site_id=site_id)

    @app.get('/api/v1/sites/{site_id}',response_model=SiteInfo,tags=['0. Find your site'])
    def site_info(site_id:str):
        """Site name, brand design from the admin (logo, colours, font, layout, support details) and how many plans are available."""
        config = site(site_id); catalog = current(site_id)[0]
        return SiteInfo(site_id=site_id,site_name=catalog.site_name,color=catalog.color,demo=catalog.demo,title=catalog.title,
            therapy=catalog.therapy,branding=catalog.branding or Branding(),plan_count=len(catalog.plans),domains=config['domains'],
            portal_url=(getattr(transport,'upstream',PUBLIC_UPSTREAM)+'/portal/'+config['portal_site']) if config.get('portal_site') else None)

    @app.get('/api/v1/sites/{site_id}/plans',response_model=Catalog,tags=['1. Get plans'])
    def get_plans(site_id:str):
        """This site's currently available plans: medication, duration, purchase type, price and terms. Prices are checked again by the checkout before payment."""
        site(site_id)
        return current(site_id)[0]

    @app.post('/api/v1/sites/{site_id}/checkout',response_model=CheckoutURL,status_code=201,tags=['Legacy redirect demo'],deprecated=True)
    def checkout(site_id:str,body:Selection,req:Request):
        """Send only plan_id. Open checkout_url to enter details and pay on the existing Stripe v2 checkout. This call does not authorize or charge. The receipt stays on that checkout; custom return URLs are not supported in this demo."""
        site(site_id)
        if '*' not in allowed_origins and req.headers.get('origin') not in (None,origin,*allowed_origins):
            raise HTTPException(403,'Frontend origin is not registered')
        routes = current(site_id)[1]
        if body.plan_id not in routes:
            raise HTTPException(404,'Plan not found')
        with lock:
            for token in [k for k,v in sessions.items() if v['expires'] <= clock()]:
                del sessions[token]
            if len(sessions) >= 1000:
                raise HTTPException(429,'Demo is busy; try again later')
            token = secrets.token_urlsafe(32)
            sessions[token] = {'target':routes[body.plan_id],'expires':clock()+900}
        return CheckoutURL(checkout_url=origin+'/go/'+token)

    @app.get('/go/{token}',include_in_schema=False)
    def go(token:str):
        with lock:
            session = sessions.get(token)
            if not session or session['expires'] <= clock():
                raise HTTPException(410,'This demo link expired. Choose a plan again.')
            target = session['target']
        return RedirectResponse(target,status_code=303)

    @app.get('/sites/{site_id}/openapi.json',include_in_schema=False)
    def schema(site_id:str):
        config = site(site_id)
        payment_note = ' Real-charge payment tests only; no medication is shipped.' if config['payment_test_only'] else ''
        spec = get_openapi(title=f"{config['name']} · Site API",version='0.4.0',routes=app.routes,
            description='Build checkout in your own frontend: get plans, create a session, calculate a quote, prepare Stripe Payment Element, confirm with Stripe.js, then complete the order. Use the session_token as Bearer authorization. No account secret keys or raw card data.'+payment_note+' The older redirect endpoint remains for compatibility.')
        paths = {}
        for path,item in spec['paths'].items():
            if path.startswith('/api/v1/domains/'):
                paths[path] = item
                continue
            if not path.startswith('/api/v1/sites/{site_id}'):
                continue
            for op in item.values():
                op['parameters'] = [p for p in op.get('parameters',[]) if p['name'] != 'site_id']
            paths[path.replace('{site_id}',site_id)] = item
        spec['paths'] = paths
        spec['servers'] = [{'url':origin}]
        example = 'sema-1m'
        with lock:
            cached = caches.get(site_id,{}).get('value')
        if cached and cached[0].plans:
            example = cached[0].plans[0].plan_id
        spec['components']['schemas']['Selection']['example'] = {'plan_id':example}
        if 'CreateSession' in spec['components']['schemas']:
            spec['components']['schemas']['CreateSession']['example'] = {'plan_id':example}
        return spec

    @app.get('/sites/{site_id}/docs',include_in_schema=False)
    def docs(site_id:str):
        config = site(site_id)
        return get_swagger_ui_html(openapi_url=f'/sites/{site_id}/openapi.json',title=html.escape(config['name'])+' · API docs',
            swagger_favicon_url='data:,',swagger_ui_parameters={'defaultModelsExpandDepth':-1,'tryItOutEnabled':True,'persistAuthorization':False})

    install_session_api(app,site,current,session_store,transport,origin,allowed_origins,clock=clock)
    return app
