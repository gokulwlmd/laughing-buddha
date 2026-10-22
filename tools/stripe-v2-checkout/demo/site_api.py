"""Two-call, network-free site API demo. No Sticky/Stripe clients or credentials.

This is deliberately separate from app.py and the production state directory.
"""
from dataclasses import dataclass
from decimal import Decimal
import html
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from therapy_skeletons import weight_loss_skeleton

HERE = Path(__file__).parent
SITES = {
    'willow-health': {'name':'Willow Health','color':'#245844','multiplier':'1.00'},
    'harbor-wellness': {'name':'Harbor Wellness','color':'#4355a3','multiplier':'1.10'},
}


@dataclass(frozen=True)
class DemoSettings:
    api_origin: str = 'http://127.0.0.1:8871'
    frontend_origin: str = 'http://127.0.0.1:8872'
    session_seconds: int = 900


class Plan(BaseModel):
    plan_id: str
    name: str
    medication: str
    duration_months: int
    purchase_type: str
    price: str
    currency: str = 'USD'
    renewal_days: int | None
    shipment_days: list[int]
    terms: str


class Catalog(BaseModel):
    site_id: str
    site_name: str
    color: str
    demo: bool = True
    plans: list[Plan]


class CreateCheckout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_id: str = Field(min_length=1, max_length=80)
    return_url: str = Field(max_length=300)


class CheckoutLink(BaseModel):
    checkout_url: str


def catalog(site_id):
    site = SITES.get(site_id)
    if not site:
        raise HTTPException(404, 'Site not found')
    plans = []
    for product in weight_loss_skeleton()['products']:
        months = product['duration_months']
        subscription = product['renewal_days'] is not None
        price = f"{Decimal(product['price']) * Decimal(site['multiplier']):.2f}"
        deliveries = [n * product['shipment_interval'] for n in range(product['shipments_per_term'])] if product['shipments_per_term'] else [0]
        days = product['renewal_days']
        terms = f'Pay ${price} upfront. ' + (f'Renews every {days} days.' if subscription else 'One-time purchase. No automatic renewal.')
        if len(deliveries) > 1:
            terms += f' Includes {len(deliveries)} shipments, 90 days apart, with no additional product charges.'
        plans.append(Plan(plan_id=product['sku'].lower(),name=f"{product['treatment']} — {months}-month "+('subscription' if subscription else 'one-time plan'),
            medication=product['treatment'],duration_months=months,purchase_type='subscription' if subscription else 'once',
            price=price,renewal_days=days,shipment_days=deliveries,terms=terms))
    return Catalog(site_id=site_id,site_name=site['name'],color=site['color'],plans=plans)


def create_demo_app(settings=None, clock=time.time):
    cfg = settings or DemoSettings()
    app = FastAPI(title='Site API demo',docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(CORSMiddleware,allow_origins=[cfg.frontend_origin],allow_methods=['GET','POST'],allow_headers=['Content-Type'])
    sessions = {}
    app.state.sessions = sessions

    @app.middleware('http')
    async def headers(req, call_next):
        response = await call_next(req)
        response.headers['Cache-Control'] = 'no-store'
        # Keep checkout tokens off cross-origin return requests while allowing
        # same-origin form POSTs to retain their Origin header.
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/api/v1/sites/{site_id}/plans',response_model=Catalog,tags=['1. Get plans'],summary='Get this site’s plans')
    def get_plans(site_id: str):
        """Returns sample site prices and exact upfront/renewal terms. No credentials required in this local demo."""
        return catalog(site_id)

    @app.post('/api/v1/sites/{site_id}/checkout',response_model=CheckoutLink,status_code=201,tags=['2. Open checkout'],summary='Create a branded checkout link')
    def create_checkout(site_id: str, body: CreateCheckout, req: Request):
        """Send only the selected plan and your registered return URL. No amounts or processor credentials are accepted. This demo cannot charge a card."""
        origin = req.headers.get('origin')
        if origin and origin not in (cfg.frontend_origin,cfg.api_origin):
            raise HTTPException(403, 'Frontend origin is not registered for this demo')
        site = catalog(site_id)
        plan = next((p for p in site.plans if p.plan_id == body.plan_id),None)
        if not plan:
            raise HTTPException(404, 'Plan not found for this site')
        target = urlsplit(body.return_url)
        if (target.scheme+'://'+target.netloc != cfg.frontend_origin or target.path != '/complete'
                or target.query or target.fragment or target.username or target.password):
            raise HTTPException(422, 'Use the registered frontend return URL: '+cfg.frontend_origin+'/complete')
        # Sessions are independent, expire, and never represent financial orders.
        now = clock()
        for key in [key for key,value in sessions.items() if value['expires'] <= now]:
            del sessions[key]
        if len(sessions) >= 1000:
            raise HTTPException(429, 'Demo session limit reached; wait for older sessions to expire')
        token = secrets.token_urlsafe(32)
        sessions[token] = {'site':site,'plan':plan,'return_url':body.return_url,'expires':now+cfg.session_seconds,'complete':False}
        return CheckoutLink(checkout_url=cfg.api_origin+'/demo/checkout/'+token)

    @app.get('/sites/{site_id}/openapi.json',include_in_schema=False)
    def schema(site_id: str):
        site = catalog(site_id)
        spec = get_openapi(title=site.site_name+' · Site API demo',version='0.1.0-demo',routes=app.routes,
            description='Two calls. Get plans, then create a hosted checkout link. Local sample data only; no payments or credentials. Registered return URL: '+cfg.frontend_origin+'/complete')
        scoped = {}
        for path,item in spec['paths'].items():
            if not path.startswith('/api/v1/sites/{site_id}/'):
                continue
            for operation in item.values():
                operation['parameters'] = [p for p in operation.get('parameters',[]) if p['name'] != 'site_id']
            scoped[path.replace('{site_id}',site_id)] = item
        spec['paths'] = scoped
        spec['servers'] = [{'url':cfg.api_origin}]
        spec['components']['schemas']['CreateCheckout']['example'] = {'plan_id':'sema-6m-sub','return_url':cfg.frontend_origin+'/complete'}
        return spec

    @app.get('/sites/{site_id}/docs',include_in_schema=False)
    def docs(site_id: str):
        site = catalog(site_id)
        return get_swagger_ui_html(openapi_url=f'/sites/{site_id}/openapi.json',title=site.site_name+' · API docs',
            swagger_favicon_url='data:,',swagger_ui_parameters={'defaultModelsExpandDepth':-1,'tryItOutEnabled':True,'persistAuthorization':False})

    def session(token):
        value = sessions.get(token)
        if not value or value['expires'] <= clock():
            raise HTTPException(410, 'This demo checkout expired. Return to the frontend and create another.')
        return value

    @app.get('/demo/checkout/{token}',response_class=HTMLResponse,include_in_schema=False)
    def checkout_page(token: str):
        value = session(token)
        page = (HERE/'web/checkout.html').read_text()
        data = {'site_name':value['site'].site_name,'color':value['site'].color,'plan':value['plan'].model_dump(),'complete':value['complete']}
        encoded = json.dumps(data).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        return HTMLResponse(page.replace('__CHECKOUT_DATA__',encoded))

    @app.post('/demo/checkout/{token}/finish',include_in_schema=False)
    def finish_demo(token: str, req: Request):
        if req.headers.get('origin') not in (None,cfg.api_origin):
            raise HTTPException(403, 'Open this demo checkout to finish')
        value = session(token)
        value['complete'] = True
        return RedirectResponse(value['return_url'],status_code=303)

    @app.get('/demo/assets/checkout.js',include_in_schema=False)
    def checkout_js():
        from fastapi.responses import FileResponse
        return FileResponse(HERE/'web/checkout.js',media_type='application/javascript')

    @app.get('/demo/assets/style.css',include_in_schema=False)
    def style():
        from fastapi.responses import FileResponse
        return FileResponse(HERE/'web/style.css',media_type='text/css')

    return app


def create_frontend_app(settings=None):
    cfg = settings or DemoSettings()
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.mount('/assets',StaticFiles(directory=HERE/'web'),name='assets')

    @app.get('/')
    @app.get('/complete')
    def page():
        source = (HERE/'web/index.html').read_text().replace('__API_ORIGIN__',html.escape(cfg.api_origin,quote=True))
        return HTMLResponse(source,headers={'Cache-Control':'no-store'})

    return app
