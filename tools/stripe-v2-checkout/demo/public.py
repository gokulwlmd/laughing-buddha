"""Public two-call frontend; real payments remain on the existing Stripe v2 app.

No processor credentials, production DB, card widget or payment write client.
Only the explicitly published demo parent can be read/selected.
"""
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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, ConfigDict, Field
from demo.site_api import Catalog, Plan

HERE = Path(__file__).parent
LIVE_ORIGIN = 'https://wlmd-stripe-test-0f89b1bb.fly.dev'
PUBLISHED_PLAN = 'site-api-demo-weight-loss'
SITE_ID = 'payment-test'
CATALOG_FRESH_SECONDS = 60
CATALOG_MAX_AGE_SECONDS = 120

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Unexpected catalog redirect')


def read_live_catalog():
    req = URLRequest(LIVE_ORIGIN+'/api/plans/'+PUBLISHED_PLAN,headers={'Accept':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=25) as response:
        return json.load(response)


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str = Field(min_length=1,max_length=80)

class CheckoutURL(BaseModel):
    checkout_url: str


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
        routes[pid] = LIVE_ORIGIN+'/plans/'+PUBLISHED_PLAN+'/choose?'+urlencode({
            'sku':entry['sku'],'option':option['key'],'purchase_option_id':entry.get('purchaseOptionId','')})
    if len(plans) != 16:
        raise ValueError('The complete approved payment-test catalog is required')
    return Catalog(site_id=SITE_ID,site_name='Master Therapy Payment Test',color=data['branding']['color'],plans=plans), routes


def create_public_app(origin=None, read_catalog=read_live_catalog, clock=time.time):
    origin = origin or os.environ['DEMO_PUBLIC_ORIGIN']
    if not origin.startswith('https://') or origin.rstrip('/') != origin or '/' in origin[8:]:
        raise ValueError('DEMO_PUBLIC_ORIGIN must be an HTTPS origin')
    app = FastAPI(title='Site API · live checkout demo',docs_url=None,redoc_url=None,openapi_url=None)
    app.mount('/assets',StaticFiles(directory=HERE/'web'),name='assets')
    cache = {}; sessions = {}; lock = threading.Lock(); refresh_lock = threading.Lock()

    def refresh(background=False):
        # Only catalog reads run here. Never cache authorization or payment state.
        if not refresh_lock.acquire(blocking=not background):
            return
        try:
            with lock:
                if cache.get('expires',0) > clock():
                    return
            try:
                value = map_catalog(read_catalog())
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

    def current():
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
                threading.Thread(target=refresh,kwargs={'background':True},daemon=True).start()
            return value
        refresh()
        with lock:
            return cache['value']

    def site(site_id):
        if site_id != SITE_ID:
            raise HTTPException(404,'Site not found')

    @app.middleware('http')
    async def headers(req,call_next):
        response = await call_next(req)
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
        return response

    @app.get('/health',include_in_schema=False)
    def health():
        return {'status':'running','mode':'real-checkout-handoff','processor_credentials':False}

    @app.get('/',include_in_schema=False,response_class=HTMLResponse)
    def frontend():
        source = (HERE/'web/index.html').read_text().replace('__API_ORIGIN__',html.escape(origin,quote=True))
        source = source.replace('INTERACTIVE DEMO · NO PAYMENTS','LIVE PAYMENT DEMO · REAL CHARGES')
        source = source.replace('<label class="site-switch">Sample site<select id="site"><option value="willow-health">Willow Health</option><option value="harbor-wellness">Harbor Wellness</option></select></label>',
            '<label class="site-switch">Connected site<select id="site"><option value="payment-test">Payment Test</option></select></label>')
        source = source.replace('This demo never asks for your card.','Opens our real Stripe v2 checkout.<br>Payment tests only. No medication is shipped.')
        source = source.replace('Sample plans · No orders or charges','Live gateway · Real charges if you pay')
        source = source.replace('<meta name="api-origin"','<meta name="payment-mode" content="real"><meta name="api-origin"')
        return HTMLResponse(source)

    @app.get('/api/v1/sites/{site_id}/plans',response_model=Catalog,tags=['1. Get plans'])
    def get_plans(site_id:str):
        """Current approved demo plans. Prices are checked again by the hosted checkout. Real-charge payment tests; no medication fulfillment."""
        site(site_id)
        return current()[0]

    @app.post('/api/v1/sites/{site_id}/checkout',response_model=CheckoutURL,status_code=201,tags=['2. Open checkout'])
    def checkout(site_id:str,body:Selection,req:Request):
        """Send only plan_id. Open checkout_url to enter details and pay on the existing Stripe v2 checkout. This call does not authorize or charge. The receipt stays on that checkout; custom return URLs are not supported in this demo."""
        site(site_id)
        if req.headers.get('origin') not in (None,origin):
            raise HTTPException(403,'Frontend origin is not registered')
        routes = current()[1]
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
        site(site_id)
        spec = get_openapi(title='Payment Test · Site API',version='0.2.0-demo',routes=app.routes,
            description='Two calls, no processor credentials. Connects to the existing live Stripe v2 checkout. Real charges if you choose to pay; no medication is shipped. Receipt stays on the hosted checkout.')
        paths = {}
        for path,item in spec['paths'].items():
            if not path.startswith('/api/v1/sites/{site_id}/'):
                continue
            for op in item.values():
                op['parameters'] = [p for p in op.get('parameters',[]) if p['name'] != 'site_id']
            paths[path.replace('{site_id}',SITE_ID)] = item
        spec['paths'] = paths
        spec['servers'] = [{'url':origin}]
        spec['components']['schemas']['Selection']['example'] = {'plan_id':'sema-1m'}
        return spec

    @app.get('/sites/{site_id}/docs',include_in_schema=False)
    def docs(site_id:str):
        site(site_id)
        return get_swagger_ui_html(openapi_url=f'/sites/{SITE_ID}/openapi.json',title='Payment Test · API docs',
            swagger_favicon_url='data:,',swagger_ui_parameters={'defaultModelsExpandDepth':-1,'tryItOutEnabled':True,'persistAuthorization':False})

    return app
