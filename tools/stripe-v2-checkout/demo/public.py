"""Site-scoped checkout API using explicitly approved backend publications.

Processor credentials stay on the existing checkout engine. Customer input
cannot select a campaign, product/offer mapping, gateway or payment amount.
"""
import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, build_opener, HTTPRedirectHandler
from decimal import Decimal
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
from demo.site_api import Catalog, Plan
from demo.registry import load_publications

HERE = Path(__file__).parent
LIVE_ORIGIN = 'https://wlmd-stripe-test-0f89b1bb.fly.dev'
PUBLISHED_PLAN = 'site-api-public-weight-loss'
SITE_ID = 'payment-test'
CATALOG_FRESH_SECONDS = 60
CATALOG_MAX_AGE_SECONDS = 120

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Unexpected catalog redirect')


def read_live_catalog():
    return read_live_publication(PUBLISHED_PLAN)


def read_live_publication(publication_id):
    req = URLRequest(LIVE_ORIGIN+'/api/plans/'+publication_id,headers={'Accept':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=25) as response:
        return json.load(response)


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str = Field(min_length=1,max_length=80)

class CheckoutURL(BaseModel):
    checkout_url: str


class Therapy(BaseModel):
    therapy_id: str
    name: str
    plan_count: int


class PublishedPlan(Plan):
    therapy_id: str
    therapy_name: str


class PublishedCatalog(Catalog):
    demo: bool = False
    payment_test_only: bool = False
    plans: list[PublishedPlan]
    therapies: list[Therapy]


def map_catalog(data):
    if data.get('id') != PUBLISHED_PLAN or not data.get('paymentTestOnly'):
        raise ValueError('Expected the published payment-test catalog')
    names = {t['id']:t['name'] for t in data['treatments']}
    plans, routes = [], {}
    for entry in data['entries']:
        if not entry.get('available'):
            continue
        months = entry['durationMonths']
        if months not in (1,3,6,12) or str(entry.get('currency','')).upper() != 'USD':
            raise ValueError('Unsupported payment-test terms')
        if len(entry['options']) != 1:
            raise ValueError('Each API plan must map to one approved payment choice')
        option = entry['options'][0]
        if option.get('blockedReason'):
            continue
        recurring = bool(option['renewal'] if 'renewal' in option else option.get('recurring'))
        days = (option.get('renewalDays') or option.get('days')) if recurring else None
        if days is not None and days != months*30:
            raise ValueError('Unexpected renewal schedule')
        count = int(option.get('prepaidCycles') or 1)
        expected = {1:1,3:1,6:2,12:4}[months]
        if count != expected:
            raise ValueError('Unexpected prepaid shipment count')
        price = f"{Decimal(str(option.get('upfrontPrice') or option['basePrice'])):.2f}"
        if Decimal(price) <= 0 or not Decimal(price).is_finite():
            raise ValueError('Invalid price')
        pid = entry['sku'].lower()
        if pid in routes:
            raise ValueError('Duplicate API plan')
        medication = names[entry['treatmentId']]
        terms = f'Pay ${price} upfront. '+(f'Renews every {days} days.' if recurring else 'One-time purchase. No automatic renewal.')
        if count > 1:
            terms += f' {count} prepaid cycles, 90 days apart, with no additional product charges.'
        plans.append(Plan(plan_id=pid,name=f'{medication} — {months}-month plan',medication=medication,
            duration_months=months,purchase_type='subscription' if recurring else 'once',price=price,
            renewal_days=days,shipment_days=[n*90 for n in range(count)],terms=terms))
        # This dedicated publication has public children. Opening the final URL
        # must work in a fresh browser, without cookies from an earlier redirect.
        purchase_id = entry.get('purchaseOptionId','')
        identity = PUBLISHED_PLAN+'\0'+entry['sku']+('\0'+purchase_id if purchase_id else '')
        child_id = 'choice-'+hashlib.sha256(identity.encode()).hexdigest()[:32]
        routes[pid] = LIVE_ORIGIN+'/c/'+child_id+'?'+urlencode({'selection':option['key']})
    if len(plans) != 16:
        raise ValueError('The complete approved payment-test catalog is required')
    return PublishedCatalog(site_id=SITE_ID,site_name='Master Therapy Payment Test',color=data['branding']['color'],
        payment_test_only=True,plans=[PublishedPlan(**p.model_dump(),therapy_id='weight-loss',therapy_name='Weight Loss') for p in plans],
        therapies=[Therapy(therapy_id='weight-loss',name='Weight Loss',plan_count=len(plans))]), routes


def map_site_catalog(site, read_publication, checkout_origin=LIVE_ORIGIN):
    """Fail closed on missing/changed choices; never borrow another site's plans."""
    plans, routes, therapies = [], {}, []
    # Independent read-only therapy catalogs can load together. Payment writes
    # never use this executor or the display cache.
    with ThreadPoolExecutor(max_workers=min(4,len(site.therapies))) as readers:
        pending = {therapy.published_plan_id:readers.submit(read_publication,therapy.published_plan_id)
            for therapy in site.therapies}
        catalogs = {key:future.result() for key,future in pending.items()}
    for therapy in site.therapies:
        data = catalogs[therapy.published_plan_id]
        if data.get('id') != therapy.published_plan_id or data.get('paymentTestOnly') is not False:
            raise ValueError('Expected the approved client publication')
        names = {t['id']:t['name'] for t in data['treatments']}
        for approved in therapy.plans:
            entries = [entry for entry in data['entries'] if entry.get('sku') == approved.sku
                and entry.get('purchaseOptionId','') == approved.purchase_option_id]
            if len(entries) != 1 or not entries[0].get('available'):
                raise ValueError('Approved plan is unavailable')
            entry = entries[0]
            options = entry.get('options',[])
            if len(options) != 1 or options[0].get('key') != approved.selection or options[0].get('blockedReason'):
                raise ValueError('Approved payment choice changed')
            option = options[0]
            months = entry['durationMonths']
            if months not in (1,3,6,12) or str(entry.get('currency','')).upper() != 'USD':
                raise ValueError('Unsupported plan terms')
            recurring = bool(option['renewal'] if 'renewal' in option else option.get('recurring'))
            days = (option.get('renewalDays') or option.get('days')) if recurring else None
            count = int(option.get('prepaidCycles') or 1)
            if (days is not None and days != months*30) or count != {1:1,3:1,6:2,12:4}[months]:
                raise ValueError('Unexpected renewal or shipment schedule')
            if count > 1 and option.get('days') != 90:
                raise ValueError('Included shipments must be 90 days apart')
            price_value = Decimal(str(option.get('upfrontPrice') or option['basePrice']))
            if not price_value.is_finite() or price_value <= 0 or price_value != price_value.quantize(Decimal('.01')):
                raise ValueError('Invalid price')
            price = f'{price_value:.2f}'
            medication = names[entry['treatmentId']]
            terms = f'Pay ${price} upfront. '+(f'Renews every {days} days.' if recurring else 'One-time purchase. No automatic renewal.')
            if count > 1:
                terms += f' Includes {count} shipments, 90 days apart, with no additional product charges.'
            pid = approved.sku.lower()
            plans.append(PublishedPlan(plan_id=pid,name=f'{medication} — {months}-month plan',medication=medication,
                therapy_id=therapy.therapy_id,therapy_name=therapy.name,duration_months=months,
                purchase_type='subscription' if recurring else 'once',price=price,renewal_days=days,
                shipment_days=[n*90 for n in range(count)],terms=terms))
            identity = therapy.published_plan_id+'\0'+approved.sku+('\0'+approved.purchase_option_id if approved.purchase_option_id else '')
            child_id = 'choice-'+hashlib.sha256(identity.encode()).hexdigest()[:32]
            routes[pid] = checkout_origin+'/c/'+child_id+'?'+urlencode({'selection':approved.selection})
        therapies.append(Therapy(therapy_id=therapy.therapy_id,name=therapy.name,plan_count=len(therapy.plans)))
    return PublishedCatalog(site_id=site.site_id,site_name=site.site_name,color=site.color,plans=plans,therapies=therapies),routes


def create_public_app(origin=None, read_catalog=read_live_catalog, clock=time.time, session_store=None, transport=None, warm_catalog=None,
                      manifest=None, read_publication=read_live_publication, include_payment_test=True,
                      checkout_origin=LIVE_ORIGIN, serve_frontend=True, include_legacy_redirect=True, manifest_loader=None):
    if manifest_loader is not None:
        manifest=manifest_loader()
    current_manifest=manifest
    publications = load_publications(manifest)
    site_ids = ((SITE_ID,) if include_payment_test else ()) + tuple(publications)
    origin = origin or os.environ['DEMO_PUBLIC_ORIGIN']
    if not origin.startswith('https://') or origin.rstrip('/') != origin or '/' in origin[8:]:
        raise ValueError('DEMO_PUBLIC_ORIGIN must be an HTTPS origin')
    @asynccontextmanager
    async def lifespan(app):
        stop=threading.Event()
        def maintain_catalog():
            # Read-only display data. Keep the existing freshness/hard-age limits;
            # an upstream outage never extends the lifetime of an old catalog.
            while not stop.is_set():
                try:
                    sync_publications()
                    for site_id in site_ids:
                        refresh(site_id,background=True)
                except HTTPException:
                    pass
                if stop.wait(15):break
        enabled=warm_catalog if warm_catalog is not None else (read_catalog is read_live_catalog and session_store is not None)
        worker=threading.Thread(target=maintain_catalog,daemon=True) if enabled else None
        if worker:worker.start()
        try:yield
        finally:
            stop.set()
            if worker:await asyncio.to_thread(worker.join,30)
            if hasattr(transport,'close'):transport.close()

    app = FastAPI(title='Site checkout API',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.publications=publications
    if serve_frontend:
        app.mount('/assets',StaticFiles(directory=HERE/'web'),name='assets')
    caches = {site_id:{} for site_id in site_ids}
    refresh_locks = {site_id:threading.Lock() for site_id in caches}
    sessions = {}; lock = threading.Lock()
    manifest_lock=threading.Lock()
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

    def sync_publications():
        nonlocal site_ids,current_manifest
        if manifest_loader is None:
            return
        with manifest_lock:
            try:
                candidate=manifest_loader()
                if candidate is current_manifest:
                    return
                updated=load_publications(candidate)
            except Exception:
                raise HTTPException(503,'Site publication configuration needs review') from None
            with lock:
                for site_id,configuration in updated.items():
                    if publications.get(site_id)!=configuration:
                        caches[site_id]={}
                        refresh_locks.setdefault(site_id,threading.Lock())
                publications.clear();publications.update(updated)
                site_ids=((SITE_ID,) if include_payment_test else ())+tuple(publications)
                current_manifest=candidate

    def refresh(site_id=SITE_ID,background=False):
        # Only catalog reads run here. Never cache authorization or payment state.
        cache,refresh_lock = caches[site_id],refresh_locks[site_id]
        if not refresh_lock.acquire(blocking=not background):
            return
        try:
            with lock:
                if cache.get('expires',0) > clock():
                    return
            try:
                value = map_catalog(read_catalog()) if site_id == SITE_ID else map_site_catalog(publications[site_id],read_publication,checkout_origin)
            except Exception:
                with lock:
                    cache['retry_at'] = clock()+3
                if not background:
                    raise HTTPException(503,'The connected checkout is temporarily unavailable. Please try again shortly.') from None
                return
            with lock:
                cache.update(value=value,expires=clock()+CATALOG_FRESH_SECONDS,usable_until=clock()+CATALOG_MAX_AGE_SECONDS,retry_at=0)
        finally:
            refresh_lock.release()

    def current(site_id=SITE_ID):
        site(site_id)
        cache,refresh_lock = caches[site_id],refresh_locks[site_id]
        with lock:
            now=clock()
            value=cache.get('value')
            fresh=cache.get('expires',0)>now
            usable=cache.get('usable_until',0)>now
            retry=cache.get('retry_at',0)>now
        if value and fresh:
            return value
        if value and usable:
            # A periodic upstream read must not freeze the customer page.
            # Display data has a hard 120-second age limit; the real checkout
            # still recalculates/revalidates before any authorization/capture.
            if not retry and not refresh_lock.locked():
                threading.Thread(target=refresh,kwargs={'site_id':site_id,'background':True},daemon=True).start()
            return value
        refresh(site_id)
        with lock:
            return cache['value']

    def site(site_id):
        sync_publications()
        if site_id not in site_ids:
            raise HTTPException(404,'Site not found')
        return publications.get(site_id)

    @app.middleware('http')
    async def headers(req,call_next):
        started=time.perf_counter()
        response = await call_next(req)
        response.headers['Server-Timing']=f'app;dur={(time.perf_counter()-started)*1000:.1f}'
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
        return response

    @app.get('/health',include_in_schema=False)
    def health():
        return {'status':'running','mode':'site-payment-api','processor_credentials':False,'session_storage_configured':session_store is not None}

    @app.get('/',include_in_schema=False,response_class=HTMLResponse)
    def frontend():
        if not serve_frontend:
            raise HTTPException(404,'Page not found')
        source = (HERE/'web/index.html').read_text().replace('__API_ORIGIN__',html.escape(origin,quote=True))
        source = source.replace('INTERACTIVE DEMO · NO PAYMENTS','LIVE PAYMENT DEMO · REAL CHARGES')
        source = source.replace('<label class="site-switch">Sample site<select id="site"><option value="willow-health">Willow Health</option><option value="harbor-wellness">Harbor Wellness</option></select></label>',
            '<label class="site-switch">Connected site<select id="site"><option value="payment-test">Payment Test</option></select></label>')
        source = source.replace('This demo never asks for your card.','Opens our real Stripe v2 checkout.<br>Payment tests only. No medication is shipped.')
        source = source.replace('Sample plans · No orders or charges','Live gateway · Real charges if you pay')
        source = source.replace('<meta name="api-origin"','<meta name="payment-mode" content="real"><meta name="api-origin"')
        return HTMLResponse(source)

    @app.get('/api/v1/sites/{site_id}/plans',response_model=PublishedCatalog,tags=['1. Get plans'])
    def get_plans(site_id:str,therapy_id:str|None=None):
        """This site's approved plans and upfront/renewal terms. The checkout rechecks current pricing before payment."""
        site(site_id)
        catalog = current(site_id)[0]
        if therapy_id is None:
            return catalog
        if therapy_id not in {t.therapy_id for t in catalog.therapies}:
            raise HTTPException(404,'Therapy not found for this site')
        return catalog.model_copy(update={'plans':[p for p in catalog.plans if p.therapy_id==therapy_id],
            'therapies':[t for t in catalog.therapies if t.therapy_id==therapy_id]})

    @app.get('/api/v1/sites/{site_id}/therapies',response_model=list[Therapy],tags=['1. Get plans'])
    def get_therapies(site_id:str):
        return current(site_id)[0].therapies

    @app.post('/api/v1/sites/{site_id}/checkout',response_model=CheckoutURL,status_code=201,tags=['Legacy hosted checkout'],deprecated=True)
    def checkout(site_id:str,body:Selection,req:Request):
        """Send only plan_id. Open checkout_url to enter details and pay on the existing Stripe v2 checkout. This call does not authorize or charge. The receipt stays on that checkout; custom return URLs are not supported."""
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
                raise HTTPException(429,'Checkout is busy; try again later')
            token = secrets.token_urlsafe(32)
            sessions[token] = {'target':routes[body.plan_id],'expires':clock()+900}
        return CheckoutURL(checkout_url=origin+'/go/'+token)

    @app.get('/go/{token}',include_in_schema=False)
    def go(token:str):
        with lock:
            session = sessions.get(token)
            if not session or session['expires'] <= clock():
                raise HTTPException(410,'This checkout link expired. Choose a plan again.')
            target = session['target']
        return RedirectResponse(target,status_code=303)

    @app.get('/sites/{site_id}/openapi.json',include_in_schema=False)
    def schema(site_id:str):
        configured = site(site_id)
        name = configured.site_name if configured else 'Payment Test'
        notice = ' Real-charge payment tests only; no medication is shipped.' if not configured else ''
        spec = get_openapi(title=name+' · Site API',version='0.4.0',routes=app.routes,
            description='Build checkout in your own frontend: get plans, create a session, calculate a quote, prepare Stripe Payment Element, confirm with Stripe.js, then complete the order. Use the session_token as Bearer authorization. No account secret keys or raw card data.'+notice+' The older redirect endpoint remains for compatibility.')
        paths = {}
        for path,item in spec['paths'].items():
            if not path.startswith('/api/v1/sites/{site_id}/'):
                continue
            for op in item.values():
                op['parameters'] = [p for p in op.get('parameters',[]) if p['name'] != 'site_id']
            paths[path.replace('{site_id}',site_id)] = item
        spec['paths'] = paths
        spec['servers'] = [{'url':origin}]
        if 'Selection' in spec['components']['schemas']:
            spec['components']['schemas']['Selection']['example'] = {'plan_id':'sema-1m'}
        return spec

    @app.get('/sites/{site_id}/docs',include_in_schema=False)
    def docs(site_id:str):
        configured = site(site_id)
        return get_swagger_ui_html(openapi_url=f'/sites/{site_id}/openapi.json',title=(configured.site_name if configured else 'Payment Test')+' · API docs',
            swagger_favicon_url='data:,',swagger_ui_parameters={'defaultModelsExpandDepth':-1,'tryItOutEnabled':True,'persistAuthorization':False})

    install_session_api(app,site,current,session_store,transport,origin,allowed_origins,clock=clock,
        portal_site_for=lambda site_id:publications[site_id].portal_site_id if site_id in publications else None,
        checkout_origin=checkout_origin)
    if not include_legacy_redirect:
        app.router.routes=[route for route in app.router.routes if getattr(route,'path',None) not in
            ('/api/v1/sites/{site_id}/checkout','/go/{token}')]
    return app
