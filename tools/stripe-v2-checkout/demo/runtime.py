"""Optional shared-app site APIs; no extra app, database copy or payment engine.

Set SITE_API_MANIFEST to an on-volume, deployment-owned publication allowlist.
Adding valid publications hot-reloads the catalog without restarting payments.
"""
import asyncio
import copy
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import threading

from demo.public import create_public_app
from demo.session_api import CheckoutTransport, SessionStore


class ManifestFile:
    def __init__(self,path):
        self.path=Path(path)
        if not self.path.is_absolute():
            raise ValueError('SITE_API_MANIFEST must be an absolute path')
        self.signature=object();self.value=None;self.lock=threading.Lock()

    def __call__(self):
        with self.lock:
            try:
                stat=self.path.stat();signature=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
            except FileNotFoundError:
                signature=None
            if signature!=self.signature:
                value=json.loads(self.path.read_text()) if signature is not None else {'version':1,'sites':[]}
                self.value=value;self.signature=signature
            return self.value


class SiteAPIPath:
    """Forward only the mounted API/docs prefixes with their original URL path."""
    def __init__(self,app):
        self.app=app;self.sessions=asyncio.Semaphore(8)

    async def __call__(self,scope,receive,send):
        forwarded=dict(scope)
        forwarded['root_path']=scope.get('app_root_path','')
        if '/sessions' in scope.get('path',''):
            # Avoid filling the worker pool with calls waiting for same-process
            # engine requests. This is a resource bound, not a scale guarantee.
            async with self.sessions:
                await self.app(forwarded,receive,send)
        else:
            await self.app(forwarded,receive,send)


class PricedManifest:
    """Follow only owner-approved, exact brand/campaign price replacements."""
    def __init__(self, source, admin):
        self.source,self.admin=source,admin
        self.signature=None;self.value=None;self.lock=threading.Lock()

    def __call__(self):
        with self.lock:
            source=self.source();rows=self.admin.records('price_replacement')
            signature=json.dumps([source,rows],sort_keys=True)
            if signature==self.signature:return self.value
            value=copy.deepcopy(source)
            for site in value.get('sites',[]):
                replacements={f"{r['old_offer']}:{r['old_product']}":r for r in rows
                    if r['brand_id']==site['brand_id'] and r['campaign_id']==site['campaign_id']}
                for therapy in site.get('therapies',[]):
                    for plan in therapy.get('plans',[]):
                        offer,product,model=plan['selection'].split(':');seen=set()
                        while (key:=offer+':'+product) in replacements:
                            if key in seen:raise ValueError('Cyclic price replacement')
                            seen.add(key);r=replacements[key]
                            if int(model) not in r['billing_models']:raise ValueError('Published billing option removed')
                            offer,product=str(r['offer']),str(r['product'])
                        plan['selection']=':'.join((offer,product,model))
            self.value=value;self.signature=signature
            return value


def install_site_api(engine, manifest_path=None, transport=None):
    if getattr(engine.state,'site_api',None) is not None:
        return engine.state.site_api
    manifest_path=manifest_path or os.environ.get('SITE_API_MANIFEST')
    if not manifest_path:
        return None
    cfg=engine.state.settings;admin=engine.state.admin
    if not cfg.public_url.startswith('https://'):
        raise ValueError('Site payment APIs require the configured HTTPS checkout origin')
    manifest=PricedManifest(ManifestFile(manifest_path),admin)
    store=SessionStore(cfg.state_dir/'site-api-sessions')
    transport=transport or CheckoutTransport(cfg.public_url,approved_origins=(cfg.public_url,),
        loopback_port=int(os.environ.get('SITE_API_INTERNAL_PORT','8080')))

    def read_catalog(publication_id):
        configured=next((site for site in facade.state.publications.values()
            if publication_id in {t.published_plan_id for t in site.therapies}),None)
        if not configured:
            raise ValueError('Unpublished site catalog')
        plan,brand,therapy=admin.plan_record(publication_id)
        if (plan.get('campaign_id')!=configured.campaign_id or plan.get('brand_id')!=configured.brand_id
                or plan.get('site_id')!=configured.portal_site_id or plan.get('visibility')!='public'
                or plan.get('payment_test_only')):
            raise ValueError('Site publication membership changed')
        from publication_snapshot import read_snapshot
        saved=read_snapshot(admin,plan)
        return saved if saved is not None else admin.plan_options(plan,brand,therapy)

    facade=create_public_app(origin=cfg.public_url,manifest_loader=manifest,read_publication=read_catalog,
        session_store=store,transport=transport,warm_catalog=True,include_payment_test=False,
        checkout_origin=cfg.public_url,serve_frontend=False,include_legacy_redirect=False)
    engine.state.site_api=facade;engine.state.site_api_store=store
    # Existing patient portal routes were installed first and retain their own
    # same-origin authentication. These mounts catch only otherwise unmatched
    # site-payment API and Swagger paths. Other engine paths stay unchanged.
    dispatcher=SiteAPIPath(facade)
    engine.mount('/api/v1/sites',dispatcher,name='site-payment-api')
    engine.mount('/sites',dispatcher,name='site-payment-docs')
    previous_lifespan=engine.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        async with previous_lifespan(app):
            async with facade.router.lifespan_context(facade):
                yield
    engine.router.lifespan_context=lifespan
    return facade
