"""Private campaign/SKU checkout through Sticky Stripe Connect v2."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from functools import wraps
from catalog import CatalogError, CouponError, RoutingHints, resolve, quote
from prepaid import order_terms_match
from admin import Admin, branding as brand_presentation
from dataclasses import dataclass
from decimal import Decimal
from urllib import error, parse, request as urlrequest

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator

HERE = Path(__file__).resolve().parent
ROUTE_LOCK = threading.Lock()


class StickyError(Exception):
    pass


class NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StickyError('Unexpected API redirect')


class Sticky:
    def call(self, method, path, body=None):
        if not path.startswith('/api/') or '?' in path:
            raise StickyError('Unexpected API path')
        username = os.environ.get('STICKY_API_USERNAME')
        password = os.environ.get('STICKY_API_PASSWORD')
        if not username or not password:
            raise StickyError('Sticky credentials are unavailable')
        auth = base64.b64encode((username + ':' + password).encode()).decode()
        req = urlrequest.Request('https://whitelabelmd.sticky.io' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json', 'Accept': 'application/json'}, method=method)
        try:
            with urlrequest.build_opener(NoRedirect()).open(req, timeout=40) as response:
                obj = json.load(response)
        except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
            raise StickyError('Sticky request failed; reconcile its state before retrying') from None
        if obj.get('status') == 'FAILURE':
            raise StickyError('Sticky rejected the API operation')
        return obj

    def detail(self, path):
        obj = self.call('GET', path).get('data')
        if not isinstance(obj, dict):
            raise StickyError('Sticky configuration could not be verified')
        return obj


@dataclass
class Settings:
    public_url: str = ''
    state_dir: Path = HERE / '.state'
    campaign_id: int = 422
    product_id: int = 54537
    offer_id: int = 706
    gateway_id: int = 254
    sku: str = 'WLMD-CORE-2USD-0f89b1bb'
    # Set only after verifying the live authorize_payment contract for this fixture.
    authorization_verified: bool = False
    synthetic: bool = False
    deferred_gateway_ids: tuple[int, ...] = ()

    @classmethod
    def environment(cls):
        origin = os.environ.get('CHECKOUT_PUBLIC_URL', '').rstrip('/')
        if origin:
            url = parse.urlsplit(origin)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
                raise RuntimeError('CHECKOUT_PUBLIC_URL must be an HTTPS origin')
        synthetic = os.environ.get('CHECKOUT_ENVIRONMENT') in ('staging','development')
        return cls(public_url=origin,
            state_dir=Path(os.environ.get('CHECKOUT_STATE_DIR', HERE / '.state')),
            authorization_verified=not synthetic and os.environ.get('CHECKOUT_AUTHORIZATION_VERIFIED') == '1', synthetic=synthetic,
            deferred_gateway_ids=tuple(int(i.strip()) for i in os.environ.get('CHECKOUT_DEFERRED_GATEWAY_IDS','').split(',') if i.strip()))


class Contact(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    phone: str = Field(min_length=7, max_length=30)
    address: str = Field(min_length=2, max_length=150)
    city: str = Field(min_length=1, max_length=80)
    region: str = Field(min_length=1, max_length=80)
    postal_code: str = Field(min_length=2, max_length=20)
    country: str = Field(pattern=r'^[A-Z]{2}$')

    @field_validator('phone')
    @classmethod
    def valid_phone(cls,value):
        if not 7 <= len(re.sub(r'\D','',value)) <= 15:
            raise ValueError('Enter a valid phone number')
        return value

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email')
        return value


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class NewPurchaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    previous_attempt_id: str = Field(min_length=1, max_length=100)


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    contact: Contact
    selection: str = Field(max_length=80)
    shipping_id: int | None = Field(default=None, gt=0)
    dollar_test: bool = False
    coupon_code: str = Field(default='', max_length=30, pattern=r'^[A-Za-z0-9_% .-]*$')


class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_id: str = Field(max_length=100)
    recurring_consent: bool = False


class Store:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'checkout.sqlite3'
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS purchase (id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL, contact TEXT, intent_id TEXT, order_id TEXT)')
            db.execute("INSERT OR IGNORE INTO purchase(id,status) VALUES(1,'new')")
            db.execute('CREATE TABLE IF NOT EXISTS checkouts (id TEXT PRIMARY KEY, campaign INTEGER NOT NULL, sku TEXT NOT NULL, status TEXT NOT NULL, contact TEXT, intent_id TEXT, order_id TEXT, quote TEXT)')
            if 'link_id' not in {row[1] for row in db.execute('PRAGMA table_info(checkouts)')}:
                db.execute('ALTER TABLE checkouts ADD COLUMN link_id TEXT')
            db.execute('CREATE TABLE IF NOT EXISTS purchase_successors (previous_id TEXT PRIMARY KEY, next_id TEXT NOT NULL UNIQUE)')
            db.execute('CREATE TABLE IF NOT EXISTS checkout_visitors (checkout_id TEXT PRIMARY KEY, browser_hash TEXT NOT NULL)')
            # Preserve the paid receipt and any uncertain legacy attempt; never reset it.
            old = db.execute('SELECT status,contact,intent_id,order_id FROM purchase WHERE id=1').fetchone()
            db.execute('INSERT OR IGNORE INTO checkouts(id,campaign,sku,status,contact,intent_id,order_id) VALUES(?,?,?,?,?,?,?)',
                ('legacy',422,'WLMD-CORE-2USD-0f89b1bb',*old))
        self.path.chmod(0o600)

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, campaign, sku, link_id=None):
        key = secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute("INSERT INTO checkouts(id,campaign,sku,status,link_id) VALUES(?,?,?,'new',?)", (key,campaign,sku,link_id))
        return key

    def visitor(self, key):
        with self.db() as db:
            row=db.execute('SELECT browser_hash FROM checkout_visitors WHERE checkout_id=?',(key,)).fetchone()
            return row[0] if row else None

    def create_visit(self, campaign, sku, link_id, browser):
        key=secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute("INSERT INTO checkouts(id,campaign,sku,status,link_id) VALUES(?,?,?,'new',?)",(key,campaign,sku,link_id))
            db.execute('INSERT INTO checkout_visitors VALUES(?,?)',(key,hashlib.sha256(browser.encode()).hexdigest()))
        return key

    def bind_successor(self, previous, current):
        owner=self.visitor(previous)
        if owner:
            with self.db() as db:
                db.execute('INSERT OR IGNORE INTO checkout_visitors VALUES(?,?)',(current,owner))
                assert db.execute('SELECT browser_hash FROM checkout_visitors WHERE checkout_id=?',(current,)).fetchone()[0]==owner

    def successor(self, previous):
        with self.db() as db:
            row = db.execute('SELECT next_id FROM purchase_successors WHERE previous_id=?', (previous,)).fetchone()
            return row[0] if row else None

    def start_next(self, previous):
        # One successor per completed attempt makes repeated clicks/requests idempotent.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT campaign,sku,status,link_id FROM checkouts WHERE id=?', (previous,)).fetchone()
            if not old or old[2] != 'captured':
                raise ValueError('Only a completed purchase can start another purchase')
            existing = db.execute('SELECT next_id FROM purchase_successors WHERE previous_id=?', (previous,)).fetchone()
            if existing:
                return existing[0]
            key = secrets.token_urlsafe(24)
            db.execute("INSERT INTO checkouts(id,campaign,sku,status,link_id) VALUES(?,?,?,'new',?)", (key, old[0], old[1], old[3]))
            db.execute('INSERT INTO purchase_successors(previous_id,next_id) VALUES(?,?)', (previous,key))
            return key

    def read(self, key='legacy'):

        with self.db() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM checkouts WHERE id=?',(key,)).fetchone()
            return dict(row) if row else None

    def claim(self, before, after, key='legacy', **values):
        assert set(values).issubset({'contact', 'intent_id', 'order_id', 'quote'})
        fields = ['status=?'] + [column + '=?' for column in values]
        with self.db() as db:
            result = db.execute('UPDATE checkouts SET ' + ','.join(fields) + ' WHERE id=? AND status=?', [after, *values.values(), key, before])
            return result.rowcount == 1


def create_app(settings=None, sticky=None):
    cfg = settings or Settings.environment()
    store = Store(cfg.state_dir)
    if cfg.synthetic:
        from synthetic import SyntheticSticky
        cfg.authorization_verified = False
        api = SyntheticSticky(cfg.state_dir)
    else:
        api = sticky or Sticky()
    invite_path = cfg.state_dir / 'access-token'
    if not invite_path.exists():
        invite_path.write_text(secrets.token_urlsafe(32))
        invite_path.chmod(0o600)
    invite = invite_path.read_text().strip()
    cached = {}  # Client secrets remain in memory, never in source, DB, or logs.
    routing_hints = RoutingHints()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.settings = cfg
    app.state.invite = invite
    app.state.routing_hints = routing_hints
    admin = Admin(store,cfg,api,invite,ROUTE_LOCK)
    if cfg.synthetic:
        from synthetic import seed_demo
        seed_demo(admin)
    app.state.admin = admin
    admin.attach(app)
    from refill_rules import install_refill_admin
    install_refill_admin(app, admin)
    from dollar_testing import install_testing_admin, available as dollar_test_available, test_catalog
    install_testing_admin(app, admin)

    def csrf():
        return hmac.new(invite.encode(), b'checkout-csrf', hashlib.sha256).hexdigest()

    def access(req, mutation=False):
        if req.query_params.get('link_id'):
            admin.link_access(req,mutation)
            return
        cookie = req.cookies.get('checkout_access', '')
        if not hmac.compare_digest(cookie, invite):
            try:
                admin.authenticated(req)
            except HTTPException:
                raise HTTPException(401, 'Use the private checkout link') from None
        if mutation and (not cfg.public_url or req.headers.get('origin') != cfg.public_url or not hmac.compare_digest(req.headers.get('x-csrf-token', ''), csrf())):
            raise HTTPException(403, 'Checkout origin could not be verified')

    def context(req):
        if req.query_params.get('link_id'):
            link, brand = admin.link_access(req)
            return brand['campaign_id'], link['sku']
        try:
            campaign = int(req.query_params.get('campaign_id', cfg.campaign_id))
        except ValueError:
            raise HTTPException(422, 'Invalid campaign ID') from None
        sku = req.query_params.get('sku', cfg.sku)
        if campaign <= 0 or not sku or len(sku) > 200:
            raise HTTPException(422, 'Invalid campaign or SKU')
        return campaign, sku

    def cookie_name(campaign, sku, link_id=None):
        if link_id:
            return 'purchase_' + hashlib.sha256(f'{campaign}:{sku}:{link_id}'.encode()).hexdigest()[:20]
        return 'purchase_' + hashlib.sha256(f'{campaign}:{sku}'.encode()).hexdigest()[:20]

    def browser_cookie(req,response):
        browser=req.cookies.get('__Host-checkout-browser','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',browser):
            response.set_cookie('__Host-checkout-browser',secrets.token_urlsafe(32),secure=True,httponly=True,samesite='lax',max_age=86400*30)

    def session(req, allow_previous=False):
        campaign, sku = context(req)
        expected = req.headers.get('x-checkout-attempt')
        owner=store.visitor(expected) if expected else None
        if owner is not None:
            browser=req.cookies.get('__Host-checkout-browser','')
            row=store.read(expected)
            if not hmac.compare_digest(owner,hashlib.sha256(browser.encode()).hexdigest()) or not row or row['campaign']!=campaign or row['sku']!=sku or row.get('link_id')!=req.query_params.get('link_id'):
                raise HTTPException(409,'This checkout belongs to another visit. Open the checkout link to start your own.')
            return expected,row
        key = req.cookies.get(cookie_name(campaign, sku, req.query_params.get('link_id')))
        row = store.read(key) if key else None
        if not row or row['campaign'] != campaign or row['sku'] != sku or row.get('link_id') != req.query_params.get('link_id'):
            raise HTTPException(409, 'Open this campaign/SKU checkout link first')
        if not allow_previous and ((expected and expected != key) or (req.method == 'POST' and not expected)):
            raise HTTPException(409, 'This tab refers to another purchase. Reload the checkout before continuing.')
        return key, row

    def catalog(req, legacy=False):
        if req.query_params.get('link_id'):
            link, brand = admin.link_access(req)
            allowed = None if legacy else link['options']
            cache_key = (*context(req), tuple(sorted(allowed or [])))
            c = resolve(api, *context(req), allowed_keys=allowed, gateway_hint=routing_hints.get(cache_key) if allowed else None)
            routing_hints.remember(cache_key, c.get("gatewayId"))
            # The hint only schedules fresh reads; all restrictions remain fresh.
            return admin.filter_catalog(c,link,brand)
        return resolve(api, *context(req))

    def customer(contact):
        parts = contact['name'].split(maxsplit=1)
        first, last = parts[0], parts[1] if len(parts) > 1 else parts[0]
        return {'firstName': first, 'lastName': last,
            'email': contact['email'].lower(), 'phone': re.sub(r'\D', '', contact['phone']),
            'shippingAddress1': contact['address'], 'shippingAddress2': '',
            'shippingCity': contact['city'], 'shippingState': contact['region'], 'shippingZip': contact['postal_code'],
            'shippingCountry': contact['country'], 'billingSameAsShipping': 'YES',
            'billingFirstName': first, 'billingLastName': last,
            'billingAddress1': contact['address'], 'billingAddress2': '',
            'billingCity': contact['city'], 'billingState': contact['region'],
            'billingZip': contact['postal_code'], 'billingCountry': contact['country']}

    def common_payload(req, contact, q):
        # Fly-Client-IP is set by Fly's edge; ignore arbitrary forwarded headers locally.
        candidate = req.headers.get('fly-client-ip') if cfg.public_url.endswith('.fly.dev') else None
        try:
            address = str(ipaddress.ip_address(candidate or req.client.host))
        except ValueError:
            address = '127.0.0.1'
        return {**customer(contact), 'creditCardType': 'stripe_link',
            'forceGatewayId': q['gatewayId'], 'campaignId': q['campaignId'], 'ipAddress': address}

    def checkout_html(token):
        html=(HERE/'web/index.html').read_text().replace('<!--CHECKOUT_CONTEXT-->', '<meta name="checkout-csrf" content="'+token+'">')
        return HTMLResponse(html)

    def checkout_path(campaign, sku):
        return f'/checkout/{campaign}/' + parse.quote(sku, safe='')

    @app.middleware('http')
    async def headers(req, call_next):
        if req.headers.get('content-length', '0').isdigit() and int(req.headers.get('content-length', '0')) > 16384:
            return JSONResponse({'detail': 'Request too large'}, status_code=413)
        response = await call_next(req)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://js.stripe.com; style-src 'self' 'unsafe-inline'; frame-src https://*.stripe.com https://*.stripe.network; connect-src 'self' https://*.stripe.com https://*.stripe.network; img-src 'self' data: https:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        if req.url.path.startswith('/portal/') and req.url.path.endswith('/docs'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(CatalogError)
    @app.exception_handler(StickyError)
    async def sticky_error(req, exc):
        return JSONResponse({'detail': str(exc)}, status_code=502)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(req, exc):
        # Do not echo billing data, unexpected card fields, or request bodies.
        safe={'name','email','phone','address','city','region','postal_code','country','quote_id','selection','shipping_id'}
        fields=sorted({str(e['loc'][-1]).replace('_',' ') for e in exc.errors() if e['loc'] and e['loc'][-1] in safe})
        return JSONResponse({'detail': 'Please check: '+', '.join(fields)+'.' if fields else 'Please check the form fields and try again.'}, status_code=422)

    @app.get('/health')
    def health():
        return {'status': 'running', 'public_url_configured': bool(cfg.public_url), 'authorization_contract_verified': cfg.authorization_verified,
            'synthetic': cfg.synthetic, 'payments_blocked': not cfg.authorization_verified}

    @app.get('/')
    @app.get('/return')
    def root(req: Request):
        token = req.query_params.get('access')
        target = checkout_path(cfg.campaign_id, cfg.sku)
        if token:
            target += '?access=' + parse.quote(token, safe='')
        return RedirectResponse(target, status_code=303)

    @app.get('/checkout/{campaign_id}/{sku:path}')
    def page(req: Request, campaign_id: int, sku: str):
        if campaign_id <= 0 or not sku or len(sku) > 200:
            raise HTTPException(422, 'Invalid campaign or SKU')
        token = req.query_params.get('access')
        if token:
            if not hmac.compare_digest(token, invite):
                raise HTTPException(401, 'Invalid private link')
            response = RedirectResponse(checkout_path(campaign_id, sku), status_code=303)
            response.set_cookie('checkout_access', invite, secure=True, httponly=True, samesite='lax', max_age=3600)
            return response
        try:
            access(req)
        except HTTPException as exc:
            if exc.status_code==401:return FileResponse(HERE/'web/access.html',status_code=401)
            raise
        response = checkout_html(csrf())
        browser_cookie(req,response)
        if not hmac.compare_digest(req.cookies.get('checkout_access',''),invite):
            response.set_cookie('checkout_access',invite,secure=True,httponly=True,samesite='lax',max_age=3600)
        name = cookie_name(campaign_id, sku)
        key = req.cookies.get(name)
        row = store.read(key) if key else None
        if not row or row['campaign'] != campaign_id or row['sku'] != sku:
            key = store.create(campaign_id,sku)
            response.set_cookie(name, key, secure=True, httponly=True, samesite='lax', max_age=86400*30)
        return response

    @app.get('/c/{link_id}')
    def managed_page(req: Request, link_id: str):
        try:
            link, brand = admin.link(link_id)
        except HTTPException as exc:
            if exc.status_code in (404,409):return FileResponse(HERE/'web/unavailable.html',status_code=exc.status_code)
            raise
        token = req.query_params.get('access')
        if token:
            if not hmac.compare_digest(token, admin.private_token(link)):
                return FileResponse(HERE/'web/access.html',status_code=401)
            response = RedirectResponse('/c/'+link_id, status_code=303)
            response.set_cookie('link_access_'+link_id,token,secure=True,httponly=True,samesite='lax',max_age=86400)
            return response
        if link['visibility']=='private' and not hmac.compare_digest(req.cookies.get('link_access_'+link_id,''),admin.private_token(link)):
            return FileResponse(HERE/'web/access.html',status_code=401)
        response = checkout_html(admin.checkout_csrf(link))
        browser_cookie(req,response)
        name = cookie_name(brand['campaign_id'],link['sku'],link_id)
        key = req.cookies.get(name)
        row = store.read(key) if key else None
        if not row or row.get('link_id')!=link_id or row['campaign']!=brand['campaign_id'] or row['sku']!=link['sku']:
            key=store.create(brand['campaign_id'],link['sku'],link_id)
            response.set_cookie(name,key,secure=True,httponly=True,samesite='lax',max_age=86400*30)
        return response

    @app.get('/api/checkout-context')
    def checkout_context(req:Request):
        access(req)
        return {'csrfToken':admin.checkout_csrf(admin.link(req.query_params['link_id'])[0]) if req.query_params.get('link_id') else csrf()}

    @app.post('/api/start-checkout')
    def start_checkout(body:CaptureRequest,req:Request):
        access(req,True)
        browser=req.cookies.get('__Host-checkout-browser','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',browser):raise HTTPException(409,'Open the checkout link first.')
        campaign,sku=context(req)
        key=store.create_visit(campaign,sku,req.query_params.get('link_id'),browser)
        return {'status':'new','attemptId':key}

    @app.get('/api/config')
    def configuration(req: Request):
        access(req)
        _, row = session(req)
        c = catalog(req)
        ready = bool(cfg.public_url and cfg.authorization_verified and not c['blockedReason'])
        return {k: c[k] for k in ('campaignId','campaignName','sku','options','shipping','countries','currency','publishableKey')} | {
            'csrfToken': admin.checkout_csrf(admin.link(req.query_params['link_id'])[0]) if req.query_params.get('link_id') else csrf(), 'branding': c.get('branding'), 'checkoutTitle': c.get('checkoutTitle'), 'ready': ready, 'blockedReason': c['blockedReason'] or ('' if ready else 'The secure checkout connection is still being configured.'),
            'status': row['status'], 'attemptId': row['id'],'paymentTestOnly':c.get('paymentTestOnly',False), 'dollarTestAvailable':dollar_test_available(admin,req,c),
            'deferredPayment': {'captureMethod':'manual','setupFutureUsage':'off_session'} if c['gatewayId'] in cfg.deferred_gateway_ids else None}

    @app.get('/api/status')
    def status(req: Request):
        access(req)
        _, row = session(req)
        q = json.loads(row['quote']) if row['quote'] else {}
        branding = None
        if req.query_params.get('link_id'):
            _, brand = admin.link(req.query_params['link_id'])
            branding = brand_presentation(brand)
        return {'status': row['status'], 'attemptId': row['id'], 'orderId': row['order_id'], 'intentId': row['intent_id'], 'branding': branding,
            'amount': q.get('amount', 200 if row['id'] == 'legacy' else None), 'currency': q.get('currency','usd')}

    def serialized(fn):
        @wraps(fn)
        def locked(*args, **kwargs):
            with ROUTE_LOCK:
                return fn(*args, **kwargs)
        return locked

    @app.post('/api/new-purchase')
    @serialized
    def new_purchase(body: NewPurchaseRequest, req: Request):
        access(req, True)
        key, row = session(req, allow_previous=True)
        previous = body.previous_attempt_id
        if req.headers.get('x-checkout-attempt') != previous:
            raise HTTPException(409, 'Reload the completed purchase before starting another')
        if previous != key:
            if store.successor(previous) != key:
                raise HTTPException(409, 'This purchase is no longer current. Reload the checkout.')
        elif row['status'] != 'captured':
            raise HTTPException(409, 'Complete or reconcile the current payment before starting another purchase')
        new_key = store.start_next(previous)
        store.bind_successor(previous,new_key)
        next_row = store.read(new_key)
        response = JSONResponse({'status': next_row['status'], 'attemptId': new_key})
        response.set_cookie(cookie_name(row['campaign'],row['sku'],row.get('link_id')), new_key,
            secure=True, httponly=True, samesite='lax', max_age=86400*30)
        return response

    @app.post('/api/quote')
    def calculate(body: QuoteRequest, req: Request):
        access(req, True)
        key, row = session(req)
        if row['status'] != 'new':
            raise HTTPException(409, 'An existing payment must be reconciled before changing this checkout')
        c = catalog(req)
        if body.dollar_test:
            if not dollar_test_available(admin,req,c):
                raise HTTPException(403, '$1 testing is not enabled for this checkout')
            c = test_catalog(c)
        try:
            q = quote(api, c, body.selection, body.shipping_id, body.contact.model_dump(), body.coupon_code.strip())
        except CouponError as exc:
            raise HTTPException(422, str(exc)) from None
        q.update({'id': secrets.token_urlsafe(24), 'expires': time.time()+600})
        # Read-only Sticky calculations can overlap across cart items. Keep
        # the final quote/contact write mutually exclusive with authorization
        # so a concurrent quote cannot change contact beneath an active intent.
        with ROUTE_LOCK:
            if not store.claim('new','new',key,quote=json.dumps(q),contact=json.dumps(body.contact.model_dump())):
                raise HTTPException(409, 'Checkout state changed')
        return {k:q[k] for k in ('id','amount','currency','option','total','coupon','discountAmount','subtotalAmount','renewalPrice') if k in q}

    @app.post('/api/authorize')
    @serialized
    def authorize(body: AuthorizeRequest, req: Request):
        access(req, True)
        if not cfg.authorization_verified:
            raise HTTPException(503, 'The Sticky authorization contract has not been verified')
        key, row = session(req)
        if row['status'] == 'awaiting_card' and key in cached:
            return cached[key]
        if row['status'] != 'new':
            raise HTTPException(409, 'A payment attempt already exists. Check its status before retrying.')
        q = json.loads(row['quote']) if row['quote'] else {}
        if q.get('id') != body.quote_id or q.get('expires',0) < time.time():
            raise HTTPException(409, 'Review a fresh total before authorizing payment')
        if q['option']['recurring'] and not body.recurring_consent:
            raise HTTPException(422, 'Accept the displayed recurring billing terms to continue')
        contact = json.loads(row['contact'])
        c = catalog(req, legacy=q.get('catalogVersion',1)!=2)
        if q.get('option',{}).get('dollarTest'):
            if not dollar_test_available(admin,req,c):
                raise HTTPException(409, '$1 testing was disabled. Review a fresh total before paying.')
            c = test_catalog(c)
        current = quote(api,c,q['selection'],q['shippingId'],contact,q.get('coupon',{}).get('code',''))
        if any(current.get(k) != q.get(k) for k in ('amount','currency','fingerprint','option','coupon','renewalPrice')):
            raise HTTPException(409, 'Campaign configuration or price changed. Review a fresh quote.')
        if not store.claim('new', 'authorization_pending', key, quote=json.dumps(q | {'consented_at':time.time(),'recurring_consent':body.recurring_consent})):
            raise HTTPException(409, 'A payment attempt already exists')
        obj = api.call('POST', '/api/v1/authorize_payment', {**common_payload(req,contact,q),
            'productId':q['option']['productId'], 'auth_amount':q['total']})
        token = obj.get('digitalWalletToken')
        if str(obj.get('response_code')) != '100' or not isinstance(token, str) or not re.fullmatch(r'pi_[A-Za-z0-9]+_secret_[A-Za-z0-9]+', token):
            raise StickyError('Sticky did not return a verified payment authorization. The attempt is held for review.')
        intent = obj.get('transactionID') or obj.get('transId')
        if not isinstance(intent, str) or intent != token.split('_secret_')[0]:
            raise StickyError('Sticky returned inconsistent payment identifiers. The attempt is held for review.')
        store.claim('authorization_pending', 'awaiting_card', key, intent_id=intent)
        cached[key] = {'clientSecret': token, 'intentId': intent, 'amount':q['amount'], 'currency':q['currency']}
        return cached[key]

    @app.post('/api/resume')
    @serialized
    def resume(body: CaptureRequest, req: Request):
        access(req, True)
        if not cfg.authorization_verified:
            raise HTTPException(503, 'The payment connection is unavailable')
        key, row = session(req)
        if row['status'] != 'awaiting_card' or key not in cached:
            raise HTTPException(409, 'This payment needs review before continuing. Please contact support; do not start another payment.')
        q=json.loads(row['quote'])
        c=catalog(req, legacy=q.get('catalogVersion',1)!=2)
        if c['fingerprint']!=q['fingerprint'] or c['blockedReason']:
            raise HTTPException(409, 'The payment configuration changed. Please contact support before continuing.')
        return cached[key] | {'contact':json.loads(row['contact']),'option':q['option']}

    @app.post('/api/capture')
    @serialized
    def capture(body: CaptureRequest, req: Request):
        access(req, True)
        if not cfg.authorization_verified:
            raise HTTPException(503, 'The Sticky authorization contract has not been verified')
        key, row = session(req)
        q = json.loads(row['quote']) if row['quote'] else {'amount':200}
        if row['status'] == 'captured':
            return {'status':'captured','orderId':row['order_id'],'amount':q['amount']}
        if row['status'] != 'awaiting_card' or not row.get('intent_id'):
            raise HTTPException(409, 'No capturable payment is available. Check its status before retrying.')
        c = catalog(req, legacy=q.get('catalogVersion',1)!=2)
        if q.get('option',{}).get('dollarTest'):c = test_catalog(c)
        current = quote(api,c,q['selection'],q['shippingId'],json.loads(row['contact']),q.get('coupon',{}).get('code','')) if not c['blockedReason'] else None
        if not current or any(current.get(k) != q.get(k) for k in ('fingerprint','amount','currency','option','coupon','renewalPrice')):
            raise HTTPException(409, 'Campaign configuration or price changed; reconcile this authorization before capture')
        if not store.claim('awaiting_card', 'capture_pending', key):
            raise HTTPException(409, 'Capture is already in progress')
        option = q['option']
        payload = {**common_payload(req,json.loads(row['contact']),q),
            'three_d_redirect_url':cfg.public_url+('/c/'+row['link_id'] if row.get('link_id') else checkout_path(q['campaignId'],q['sku'])),
            'offers':[{'offer_id':option['offerId'],'product_id':option['productId'],
                'billing_model_id':option['billingModelId'],'quantity':1}],
            'creditCardNumber':'','expirationDate':'','CVV':'',
            'tranType':'Capture','transactionId':row['intent_id']}
        if option.get('prepaidCycles'):payload['offers'][0]['prepaid_cycles']=option['prepaidCycles']
        if option.get('dollarTest'):
            payload['offers'][0].update(price=option['testUnitPrice'],preserve_price=1)
        if q['shippingId'] is not None:
            payload['shippingId'] = q['shippingId']
        if q.get('coupon'):
            payload['promoCode'] = q['coupon']['code']
        # Only the explicitly enabled, server-calculated $1 test path overrides
        # price. It preserves that same price for subscription renewals.
        obj = api.call('POST','/api/v1/new_order',payload)
        order_id = obj.get('order_id')
        if order_id:
            store.claim('capture_pending','capture_pending',key,order_id=str(order_id))
        if str(obj.get('response_code')) == '101':
            raise StickyError('Additional Sticky 3DS completion is required. Do not submit another order.')
        if str(obj.get('response_code')) != '100' or not order_id:
            raise StickyError('Capture was not confirmed. The attempt is held for reconciliation.')
        raw = api.call('POST','/api/v1/order_view',{'order_id':[str(order_id)]})
        order = raw.get('data',{}).get(str(order_id),raw)
        products = order.get('products',[])
        valid = (str(order.get('response_code')) == '100' and str(order.get('order_status')) == '2' and
            Decimal(str(order.get('order_total',-1))) == Decimal(q['total']) and
            str(order.get('gateway_id')) == str(q['gatewayId']) and str(order.get('campaign_id')) == str(q['campaignId']) and
            len(products) == 1 and str(products[0].get('product_id')) == str(option['productId']) and
            str(products[0].get('billing_model',{}).get('id')) == str(option['billingModelId']) and
            str(products[0].get('product_qty')) == '1' and str(products[0].get('offer',{}).get('id')) == str(option['offerId']) and
            str(products[0].get('is_recurring')) == ('1' if option['recurring'] else '0'))
        if option.get('prepaidCycles'):valid=valid and order_terms_match(products[0],option['prepaidCycles'],option.get('renewal',False)) if valid else False
        renews_payment = option.get('renewal', False) if option.get('prepaidCycles') else option['recurring']
        if valid and q.get('coupon'):
            try:
                # Sticky retains the coupon separately from the subscription's
                # base product price. Verify that the captured order owns the
                # exact validated lifetime/initial-only coupon and discount.
                valid = (str(order.get('coupon_id')) == str(q['coupon']['profileId']) and
                    Decimal(str(order.get('coupon_discount_amount'))) == Decimal(q['discountAmount']) / 100)
            except Exception:
                valid = False
        if valid and option.get('dollarTest') and renews_payment:
            # A correct initial total alone does not prove that the subscription
            # retained the agreed testing price. Sticky reports the full prepaid
            # renewal price here (not the per-cycle quote/capture override).
            # Non-renewing prepaid plans use recurring shipment cycles but have
            # no next full-term payment; order_terms_match verifies is_renew=0.
            try:
                valid = Decimal(str(products[0].get('next_subscription_product_price'))) == Decimal('1.00')
            except Exception:
                valid = False
        if not valid:
            raise StickyError('The payment result needs reconciliation; no second capture will be submitted')
        store.claim('capture_pending','captured',key,order_id=str(order_id))
        cached.pop(key,None)
        return {'status':'captured','orderId':str(order_id),'amount':q['amount']}

    def member_receipt(req, mutation=True):
        access(req, mutation)
        _, row = session(req)
        return row

    from member_portal import install as install_member_portal
    members = install_member_portal(app, admin, store, cfg, receipt_access=member_receipt)

    @app.post('/api/portal-enrollment')
    def portal_enrollment(body: CaptureRequest, req: Request):
        return members.receipt_invite(member_receipt(req))
    if os.environ.get('SITE_API_MANIFEST'):
        from demo.runtime import install_site_api
        install_site_api(app)
    app.mount('/assets', StaticFiles(directory=HERE / 'web'), name='assets')
    return app


app = create_app()
