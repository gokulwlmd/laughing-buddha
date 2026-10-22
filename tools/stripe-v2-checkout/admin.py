"""Owner admin, persisted configuration, and explicit Sticky change reviews."""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationError
from catalog import resolve, enabled, money
from prepaid import cycles_for, unit_price
from plans import PlanCatalog
from sites import SiteCatalog
from master import MasterCatalog, clone_product, model_rows, offer_models, product_contract, source_product, brand_campaigns, attach_campaign, record_campaign

LOCK = threading.RLock()
HERE = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value,sort_keys=True))


def password_hash(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()


class Form(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class Credentials(Form):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=False)
    email: str = Field(min_length=5,max_length=254)
    password: str = Field(min_length=1,max_length=512)


class Brand(Form):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,60}$')
    name: str = Field(min_length=1,max_length=100)
    campaign_id: int | None = Field(default=None,gt=0)
    campaign_ids: list[int] = Field(default_factory=list,max_length=500)
    logo_url: str = Field(default='',max_length=1500)
    color: str = Field(default='#245844',pattern=r'^#[A-Fa-f0-9]{6}$')
    background_color: str = Field(default='#f5f4ef',pattern=r'^#[A-Fa-f0-9]{6}$')
    text_color: str = Field(default='#173c36',pattern=r'^#[A-Fa-f0-9]{6}$')
    button_text_color: str = Field(default='#ffffff',pattern=r'^#[A-Fa-f0-9]{6}$')
    font: str = Field(default='system',pattern=r'^(system|serif|rounded)$')
    layout: str = Field(default='split',pattern=r'^(split|stacked)$')
    support_email: str = Field(default='',max_length=254)
    support_phone: str = Field(default='',max_length=40)
    custom_domain: str = Field(default='',max_length=253)

    @field_validator('campaign_ids')
    @classmethod
    def valid_campaigns(cls,value):
        if any(i<1 for i in value) or len(set(value))!=len(value):raise ValueError('Choose unique positive campaigns')
        return value

    @field_validator('logo_url')
    @classmethod
    def logo(cls,value):
        if value and (urlsplit(value).scheme!='https' or not urlsplit(value).hostname or urlsplit(value).username):
            raise ValueError('Use an HTTPS logo URL')
        return value

    @field_validator('custom_domain')
    @classmethod
    def domain(cls,value):
        if value and not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',value):
            raise ValueError('Enter a domain hostname')
        return value


class SKU(Form):
    sku: str = Field(min_length=1,max_length=200)
    name: str = Field(min_length=1,max_length=150)
    product_id: int = Field(gt=0)


class Link(Form):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,80}$')
    brand_id: str = ''
    campaign_id: int | None = Field(default=None,gt=0)
    sku: str = Field(min_length=1,max_length=200)
    title: str = Field(min_length=1,max_length=150)
    visibility: str = Field(pattern=r'^(public|private)$')
    options: list[str] = Field(min_length=1,max_length=100)
    enabled: bool = True


class Offer(Form):
    id: str | None = Field(default=None,max_length=100)
    brand_id: str
    campaign_id: int | None = Field(default=None,gt=0)
    sku: str
    name: str = Field(min_length=1,max_length=150)
    price: Decimal = Field(gt=0,max_digits=10,decimal_places=2)
    billing_models: list[int] = Field(min_length=1,max_length=30)
    configuration: dict = Field(default_factory=dict)


class Campaign(Form):
    brand_id: str
    name: str = Field(min_length=1,max_length=100)
    gateway_id: int = Field(gt=0)
    channel_id: int = Field(default=1,gt=0)
    offers: list[int] = Field(min_length=1,max_length=100)
    countries: list[int] = Field(min_length=1,max_length=100)
    shipping_profiles: list[int] = Field(min_length=1,max_length=100)


class Proposal(Form):
    kind: str = Field(pattern=r'^(brand|sku|link|offer|campaign|master|provision|campaign_setup|therapy|purchase_option|plan_checkout|checkout_template|site|site_checkout)$')
    data: dict


class Approval(Form):
    review_id: str = Field(max_length=100)
    approve: bool


def branding(brand):
    defaults={'background_color':'#f5f4ef','text_color':'#173c36','button_text_color':'#ffffff','font':'system','layout':'split'}
    return {k:brand.get(k,defaults.get(k,'')) for k in ('name','logo_url','color','support_email','support_phone',*defaults)}


class Admin(MasterCatalog,PlanCatalog,SiteCatalog):
    def __init__(self,store,cfg,api,invite,payment_lock=None):
        self.store,self.cfg,self.api,self.invite=store,cfg,api,invite
        self.payment_lock=payment_lock or threading.RLock()
        path=cfg.state_dir/'admin-setup-token'
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32));path.chmod(0o600)
        self.setup_token=path.read_text().strip()
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS admin_owner(id INTEGER PRIMARY KEY CHECK(id=1),email TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admin_sessions(token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS admin_config(kind TEXT NOT NULL,id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS admin_reviews(id TEXT PRIMARY KEY,kind TEXT NOT NULL,data TEXT NOT NULL,before_hash TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,preview TEXT NOT NULL,result TEXT);
            CREATE TABLE IF NOT EXISTS admin_auth_failures(created REAL NOT NULL);
            ''')

    def owner(self):
        with self.store.db() as db:
            return db.execute('SELECT email,salt,password_hash FROM admin_owner WHERE id=1').fetchone()

    def get(self,kind,key):
        with self.store.db() as db:
            row=db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?',(kind,key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self,kind,key,data):
        with self.store.db() as db:
            db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',(kind,key,json.dumps(data)))

    def records(self,kind):
        with self.store.db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM admin_config WHERE kind=? ORDER BY id',(kind,))]

    def origin(self,req):
        if not self.cfg.public_url or req.headers.get('origin')!=self.cfg.public_url:
            raise HTTPException(403,'Admin origin could not be verified')

    def authenticated(self,req,mutation=False):
        value=req.cookies.get('__Host-admin','')
        with self.store.db() as db:
            row=db.execute('SELECT csrf,expires FROM admin_sessions WHERE token_hash=?',(digest(value),)).fetchone()
        if not value or not row or row[1]<time.time():
            raise HTTPException(401,'Sign into the admin panel')
        if mutation:
            self.origin(req)
            if not hmac.compare_digest(req.headers.get('x-csrf-token',''),row[0]):
                raise HTTPException(403,'Refresh the admin panel before submitting changes')
        return row[0]

    def issue_session(self):
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        with self.store.db() as db:
            db.execute('DELETE FROM admin_sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO admin_sessions VALUES(?,?,?)',(digest(token),csrf,time.time()+86400))
        response=JSONResponse({'authenticated':True,'csrfToken':csrf})
        response.set_cookie('__Host-admin',token,secure=True,httponly=True,samesite='strict',max_age=86400,path='/')
        response.delete_cookie('__Host-admin-setup',secure=True,httponly=True,samesite='strict',path='/')
        return response

    def private_token(self,link):
        return hmac.new(self.invite.encode(),f"managed-link:{link['id']}:{link.get('revision',1)}".encode(),hashlib.sha256).hexdigest()

    def link(self,key):
        link=self.get('link',key)
        if not link or not link.get('enabled'):
            raise HTTPException(404,'This checkout link is unavailable')
        if link.get('plan_checkout_id'):
            plan,_,_=self.plan_record(link['plan_checkout_id'])
            if link['sku'] not in {e['sku'] for e in plan['entries']} or link['brand_id']!=plan['brand_id'] or link.get('campaign_id')!=plan['campaign_id']:raise HTTPException(404,'This plan is unavailable')
            master=self.get('master',link['sku']) or {}
            self.therapy_for(master,plan['therapy_id'])
            if link.get('purchase_option_id'):
                purchase=self.get('purchase_option',link['purchase_option_id'])
                snapshot=next((p for p in plan.get('purchase_options',[]) if p['id']==link['purchase_option_id']),None)
                if not purchase or not purchase['enabled'] or not snapshot or master['product_duration_months']!=snapshot['duration_months'] or link['sku'] not in snapshot['skus']:raise HTTPException(404,'This purchase option is unavailable')
        brand=self.get('brand',link['brand_id'])
        cid=record_campaign(link,brand)
        if not brand or cid not in brand_campaigns(brand):
            raise HTTPException(409,'This brand needs a Sticky campaign')
        return dict(link,campaign_id=cid),dict(brand,campaign_id=cid)

    def link_access(self,req,mutation=False):
        key=req.query_params.get('link_id')
        if not key:
            return None
        link,brand=self.link(key)
        token=self.private_token(link)
        if link['visibility']=='private' and not hmac.compare_digest(req.cookies.get('link_access_'+key,''),token):
            raise HTTPException(401,'Open the private checkout invitation')
        if mutation:
            allowed={self.cfg.public_url}
            if req.headers.get('origin') not in allowed or not hmac.compare_digest(req.headers.get('x-csrf-token',''),self.checkout_csrf(link)):
                raise HTTPException(403,'Checkout origin could not be verified')
        return link,brand

    def checkout_csrf(self,link):
        return hmac.new(self.invite.encode(),('csrf:'+self.private_token(link)).encode(),hashlib.sha256).hexdigest()

    def filter_catalog(self,c,link,brand):
        c['options']=[o for o in c['options'] if o['key'] in link['options']]
        if not c['options']:
            raise HTTPException(409,'No enabled offers remain available on this link')
        c['fingerprint']=fingerprint([c['fingerprint'],link,branding(brand)])
        c['branding']=branding(brand)
        c['checkoutTitle']=link['title']
        return c

    def identity(self,kind,data):
        return data['sku'] if kind=='sku' else data['id']

    def prepare(self,kind,data):
        if kind in ('master','provision','campaign_setup','therapy','purchase_option','plan_checkout','checkout_template','site','site_checkout'):
            try:
                if kind in ('checkout_template','site','site_checkout'):return self.prepare_site(kind,data)
                if kind=='plan_checkout' and (self.get('plan_checkout',data.get('id','')) or {}).get('site_id'):
                    raise HTTPException(422,'Customize this checkout from its Site to preserve template inheritance')
                if kind in ('therapy','purchase_option','plan_checkout'):return self.prepare_plan(kind,data)
                return self.prepare_setup(data) if kind=='campaign_setup' else self.prepare_master(kind,data)
            except ValidationError as exc:
                fields=', '.join(sorted({str(e['loc'][0]).replace('_',' ') for e in exc.errors() if e['loc']}))
                raise HTTPException(422,'Please check: '+fields) from None
        models={'brand':Brand,'sku':SKU,'link':Link,'offer':Offer,'campaign':Campaign}
        try:
            data=models[kind].model_validate(data).model_dump(mode='json')
        except ValidationError as exc:
            fields=', '.join(sorted({str(e['loc'][0]).replace('_',' ') for e in exc.errors() if e['loc']}))
            raise HTTPException(422,'Please check: '+fields) from None
        guards=[];preview={};operations=[]
        def watch(path,keys=None):
            obj=self.api.detail(path)
            selected={k:obj.get(k) for k in keys} if keys else obj
            guards.append({'path':path,'keys':keys,'hash':fingerprint(selected)})
            return obj
        if kind in ('brand','sku','link'):
            key=self.identity(kind,data)
            before=self.get(kind,key)
            preview={'before':before,'after':data,'stickyWrites':[]}
            if kind=='brand':
                ids=list(dict.fromkeys(brand_campaigns(before)+brand_campaigns(data)))
                data['campaign_ids']=ids
                data['campaign_id']=(before or {}).get('campaign_id') or data['campaign_id'] or (ids[0] if ids else None)
                for cid in ids:
                    campaign=watch(f'/api/v2/campaigns/{cid}',['id','name','is_active','is_archived'])
                    if enabled(campaign.get('is_archived')) or campaign.get('is_active') in (False,0,'0'):raise HTTPException(422,'Select an active campaign')
                preview['impact']='Updates the shared design for all checkout links under this brand. Existing campaign memberships and checkout destinations are preserved.'
                preview['affectedCheckoutLinks']=[l['id'] for l in self.records('link') if l['brand_id']==data['id']]
            if kind=='sku':
                product=watch(f"/api/v2/products/{data['product_id']}")
                if product.get('sku')!=data['sku']:raise HTTPException(422,'The Sticky product does not match this exact SKU')
                if enabled(product.get('archived_flag')):raise HTTPException(422,'Select an active product')
            if kind=='link':
                if before and before.get('plan_checkout_id'):raise HTTPException(422,'Edit this choice through its plan checkout builder')
                brand=self.get('brand',data['brand_id'])
                cid=data.get('campaign_id') or record_campaign(before or {},brand)
                if cid:
                    if data['brand_id'] and (not brand or cid not in brand_campaigns(brand)):
                        raise HTTPException(422,'The selected brand does not belong to this campaign')
                    campaign=watch(f'/api/v2/campaigns/{cid}',['id','name','is_active','is_archived'])
                    if enabled(campaign.get('is_archived')) or campaign.get('is_active') in (False,0,'0'):
                        raise HTTPException(422,'Select an active campaign')
                    matches=[b for b in self.records('brand') if cid in brand_campaigns(b)]
                    if not brand and len(matches)>1:raise HTTPException(422,'Select the intended brand for this campaign')
                    brand=brand or (matches[0] if matches else None)
                    if not brand:
                        bid='campaign-'+str(cid)
                        if self.get('brand',bid):raise HTTPException(409,'This identifier belongs to another campaign; resolve its mapping first')
                        brand=Brand(id=bid,name=(campaign.get('name') or 'Campaign '+str(cid))[:100],campaign_id=cid).model_dump(mode='json')
                        data['_link_brand']=brand
                        preview['impact']='Creates a local campaign mapping and this checkout link together. No Sticky configuration is changed.'
                    data['brand_id']=brand['id']
                if not brand or not brand.get('campaign_id'):raise HTTPException(422,'Select a brand with a campaign')
                data['campaign_id']=cid or brand['campaign_id']
                if not self.get('sku',data['sku']):raise HTTPException(422,'Add this SKU to your catalog first')
                c=resolve(self.api,data['campaign_id'],data['sku'])
                if not set(data['options']).issubset({o['key'] for o in c['options']}):raise HTTPException(422,'Select options belonging to this campaign and SKU')
                selected=[o for o in c['options'] if o['key'] in data['options']]
                if data['enabled'] and (c['blockedReason'] or any(o['blockedReason'] for o in selected)):
                    raise HTTPException(422,'This selection is not ready for payment. Choose available options, or save the link as inactive until setup is complete.')
                preview['paymentReadiness']={'campaign':c['blockedReason'],'options':[{k:o[k] for k in ('key','modelName','blockedReason')} for o in c['options'] if o['key'] in data['options']]}
                guards.append({'catalog':[data['campaign_id'],data['sku']],'hash':c['fingerprint']})
                data['revision']=(before or {}).get('revision',0)+1
                preview['after']={k:v for k,v in data.items() if k!='_link_brand'}
        elif kind=='offer':
            brand=self.get('brand',data['brand_id']);sku=self.get('sku',data['sku'])
            if not brand or not brand.get('campaign_id') or not sku:raise HTTPException(422,'Configure the brand campaign and SKU first')
            old=self.get('offering',data['id']) if data.get('id') else None
            cid=data.get('campaign_id') or record_campaign(old or {},brand)
            if cid not in brand_campaigns(brand):raise HTTPException(422,'Select a campaign attached to this brand')
            if old and cid!=record_campaign(old,brand):raise HTTPException(422,'An existing offer cannot be moved to another campaign')
            data['campaign_id']=cid
            if data.get('id') and (not old or old['brand_id']!=data['brand_id'] or old['sku']!=data['sku']):
                raise HTTPException(422,'Select the existing brand and SKU for this offer')
            data['id']=data.get('id') or secrets.token_urlsafe(12)
            p=watch(f"/api/v2/products/{old['product_id']}") if old else source_product(self.get('master',data['sku']) or sku,watch)
            if p.get('sku')!=data['sku'] or enabled(p.get('is_bundle')) or enabled(p.get('is_variant_enabled')):
                raise HTTPException(422,'A matching simple source product is required; bundle/variant cloning needs additional configuration')
            c=watch(f"/api/v2/campaigns/{cid}",['id','offers','gateway_id','is_archived'])
            all_models=self.api.call('GET','/api/v2/billing_models').get('data',[])
            if isinstance(all_models,dict):all_models=list(all_models.values())
            valid={int(m['id']) for m in all_models if isinstance(m,dict) and not enabled(m.get('is_archived'))}
            if not set(data['billing_models']).issubset(valid):raise HTTPException(422,'Select configured billing models')
            config=data['configuration']
            if set(config)-{'type_id','is_trial','trial','recurring','prepaid','prepaid_profile','is_prepaid','cycle_products','seasonal_products'}:
                raise HTTPException(422,'Unsupported offer configuration field')
            cycles=cycles_for(config)
            if cycles and (len(data['billing_models'])!=1 or data['billing_models'][0]==2):raise HTTPException(422,'Prepaid needs one recurring shipment interval')
            product=clone_product(p,brand['name']+' / '+data['name'],data['sku'],unit_price(data['price'],cycles))
            payload={'type_id':1,'is_trial':0,'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2},**config,
                'name':data['name'],'products':[{'id':{'$ref':'product'}}],'billing_models':[{'id':i} for i in data['billing_models']]}
            operations=[{'method':'POST','path':'/api/v2/products','body':product,'save':'product'},
                {'method':'POST','path':'/api/v2/offers','body':payload,'save':'offer'},
                {'method':'PUT','path':f"/api/v2/campaigns/{cid}",'body':{'offers':[int(o['id']) for o in c['offers']]+[{'$ref':'offer'}]}}]
            affected=[]
            if old:
                for link in self.records('link'):
                    if link['brand_id']!=data['brand_id'] or link['sku']!=data['sku'] or record_campaign(link,brand)!=cid:continue
                    selected=[key for key in link['options'] if key.startswith(f"{old['offer_id']}:{old['product_id']}:")]
                    if selected and not {int(key.split(':')[2]) for key in selected}.issubset(set(data['billing_models'])):
                        raise HTTPException(422,'Remove the affected billing choices from checkout links before removing their models')
                    if selected:affected.append(link['id'])
            preview={'before':old or {'sourceProductId':sku['product_id'],'sourcePrice':p['price'],'campaignId':cid},
                'after':data,'stickyWrites':operations,'affectedCheckoutLinks':affected,'impact':'Creates a separate product with the same SKU and its own price, then a new offer. Attaches it to this campaign without modifying shared product prices. When editing an existing managed offer, its enabled choices on the listed brand links move to the new offer. Existing purchases and subscriptions retain their original offer.',
                'paymentReadiness':'Standard one-time/day-based recurring payments work. Fixed prepaid test plans are supported. Physical prepaid fulfillment, trials and other complex plans still require verification.'}
        else:
            brand=self.get('brand',data['brand_id'])
            if not brand:raise HTTPException(422,'Create the brand first')
            gateway=self.api.detail(f"/api/v2/providers/payment/profiles/{data['gateway_id']}")
            if int(gateway.get('account_id',0))!=250:raise HTTPException(422,'Select a Stripe Connect v2 gateway profile')
            for oid in data['offers']:watch(f'/api/v2/offers/{oid}',['id','products','billing_models'])
            body={'name':data['name'],'description':'Managed through WLMD Core admin','gateway_id':data['gateway_id'],
                'channel_id':data['channel_id'],'offers':data['offers'],'countries':data['countries'],'shipping_profiles':data['shipping_profiles'],
                'payment_methods':['visa','stripe_link'],'alternative_payments':[{'id':data['gateway_id'],'payment_method':'stripe_link'}],
                'return_profiles':[],'coupon_profiles':[],'postback_profiles':[],'is_prepaid_blocked':0}
            operations=[{'method':'POST','path':'/api/v2/campaigns','body':body,'save':'campaign'}]
            preview={'before':brand,'after':data,'stickyWrites':operations,'impact':'Create campaign and map it to this brand. Sticky may require granting this API user access and enabling its Stripe Link mapping before checkout becomes ready.'}
        local_hash=self.local_fingerprint()
        return data,guards,preview,operations,local_hash

    def _review_preview(self,key):
        with self.store.db() as db:
            return db.execute('SELECT preview FROM admin_reviews WHERE id=?',(key,)).fetchone()[0]

    def attach(self,app):
        self.attach_plans(app)
        @app.get('/admin')
        def page(req:Request):
            setup=req.query_params.get('setup')
            if setup:
                r=RedirectResponse('/admin',status_code=303)
                if self.owner() or not hmac.compare_digest(setup,self.setup_token):return r
                r.set_cookie('__Host-admin-setup',self.setup_token,secure=True,httponly=True,samesite='strict',max_age=1800,path='/')
                return r
            return FileResponse(HERE/'web/admin.html')

        @app.get('/api/admin/auth')
        def auth(req:Request):
            configured=bool(self.owner())
            try:
                csrf=self.authenticated(req)
                return {'configured':configured,'authenticated':True,'csrfToken':csrf,'email':self.owner()[0]}
            except HTTPException:
                can_setup=not configured and hmac.compare_digest(req.cookies.get('__Host-admin-setup',''),self.setup_token)
                csrf=hmac.new(self.setup_token.encode(),b'owner-setup',hashlib.sha256).hexdigest() if can_setup else ''
                return {'configured':configured,'authenticated':False,'canSetup':can_setup,'csrfToken':csrf}

        @app.post('/api/admin/setup')
        def setup(body:Credentials,req:Request):
            self.origin(req)
            csrf=hmac.new(self.setup_token.encode(),b'owner-setup',hashlib.sha256).hexdigest()
            if not hmac.compare_digest(req.cookies.get('__Host-admin-setup',''),self.setup_token) or not hmac.compare_digest(req.headers.get('x-csrf-token',''),csrf):
                raise HTTPException(403,'Use the private owner setup link')
            if len(body.password)<12 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',body.email):raise HTTPException(422,'Enter a valid email and a password of at least 12 characters')
            with LOCK,self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM admin_owner').fetchone():raise HTTPException(409,'Owner is already configured; sign in')
                salt=secrets.token_hex(16)
                db.execute('INSERT INTO admin_owner VALUES(1,?,?,?)',(body.email.strip().lower(),salt,password_hash(body.password,salt)))
            return self.issue_session()

        @app.post('/api/admin/login')
        def login(body:Credentials,req:Request):
            self.origin(req)
            with LOCK:
                with self.store.db() as db:
                    db.execute('DELETE FROM admin_auth_failures WHERE created<?',(time.time()-900,))
                    if db.execute('SELECT count(*) FROM admin_auth_failures').fetchone()[0]>=10:raise HTTPException(429,'Too many failed sign-ins; try again in 15 minutes')
                owner=self.owner();salt=owner[1] if owner else '0'*32
                correct=password_hash(body.password,salt)
                if not owner or not hmac.compare_digest(body.email.strip().lower().encode(),owner[0].encode()) or not hmac.compare_digest(correct,owner[2]):
                    with self.store.db() as db:db.execute('INSERT INTO admin_auth_failures VALUES(?)',(time.time(),))
                    raise HTTPException(401,'Email or password is incorrect')
                with self.store.db() as db:db.execute('DELETE FROM admin_auth_failures')
            return self.issue_session()

        @app.post('/api/admin/logout')
        def logout(req:Request):
            self.authenticated(req,True)
            with self.store.db() as db:db.execute('DELETE FROM admin_sessions WHERE token_hash=?',(digest(req.cookies.get('__Host-admin','')),))
            r=JSONResponse({'authenticated':False});r.delete_cookie('__Host-admin',secure=True,httponly=True,samesite='strict',path='/');return r

        @app.get('/api/admin/state')
        def state(req:Request):
            self.authenticated(req)
            links=[l for l in self.records('link') if not l.get('plan_checkout_id')]
            for link in links:
                link['url']=self.cfg.public_url+'/c/'+link['id']
                if link['visibility']=='private':link['url']+='?access='+self.private_token(link)
            with self.store.db() as db:
                reviews=[{'id':r[0],'kind':r[1],'status':r[2],'created':r[3],'preview':json.loads(r[4]),'result':json.loads(r[5]) if r[5] else None}
                    for r in db.execute('SELECT id,kind,status,created,preview,result FROM admin_reviews ORDER BY created DESC LIMIT 30')]
            return {'synthetic':self.cfg.synthetic,'sites':self.site_state(),'checkoutTemplates':self.records('checkout_template'),'therapies':self.records('therapy'),'purchaseOptions':self.records('purchase_option'),'planCheckouts':self.plan_state(),'masters':self.records('master'),'assignments':self.records('assignment'),'brands':self.records('brand'),'skus':self.records('sku'),'offers':self.records('offering'),'links':links,'reviews':reviews,'owner':self.owner()[0]}

        @app.get('/api/admin/campaigns')
        def campaigns(req:Request):
            self.authenticated(req)
            obj=self.api.call('POST','/api/v1/campaign_find_active',{})
            if str(obj.get('response_code'))!='100':raise HTTPException(502,'Sticky did not return an accessible campaign list')
            values=obj.get('campaigns',{});values=values.values() if isinstance(values,dict) else values
            return {'campaigns':[{'id':int(x['campaign_id']),'name':x['campaign_name']} for x in values]}

        @app.get('/api/admin/models')
        def models(req:Request):
            self.authenticated(req)
            data=self.api.call('GET','/api/v2/billing_models').get('data',[])
            if isinstance(data,dict):data=list(data.values())
            return {'models':[{k:m.get(k) for k in ('id','name','days','description','type')} for m in data if isinstance(m,dict) and not enabled(m.get('is_archived'))]}

        @app.get('/api/admin/inspect')
        def inspect(req:Request,campaign_id:int,sku:str):
            self.authenticated(req)
            if campaign_id<=0 or not sku or len(sku)>200:raise HTTPException(422,'Enter a campaign and SKU')
            c=resolve(self.api,campaign_id,sku)
            return {k:c[k] for k in ('campaignId','campaignName','sku','options','shipping','countries','currency','blockedReason')}

        @app.get('/api/admin/master-preset')
        def master_preset(req:Request,prepaid:bool=False):
            self.authenticated(req)
            if prepaid:return {'sku':'WLMD-PREPAY-cfef3de8','name':'Prepaid test — 360 days, 4 shipment orders','category':'Test plans','product_id':55098,'currency':'USD','enabled':True,'offers':[{'id':'prepaid-four','name':'Pay upfront — 4 shipments every 90 days','price':'1200.00','billing_models':[4],'prepaid_cycles':4}]}
            return {'sku':'TIRZ-1M','name':'Compounded Tirzepatide - 1 month supply','product_duration_months':1,'product_id':2856,'currency':'USD','enabled':True,
                'offers':[{'id':'standard','name':'Standard subscription','price':'449.00','billing_models':[3,4,5,7,6]}]}

        @app.post('/api/admin/master-validation')
        def master_validation(req:Request,body:dict):
            self.authenticated(req,True)
            brand_id=body.get('brand_id');location=body.get('location')
            if not isinstance(brand_id,str):raise HTTPException(422,'Select a brand')
            if location is not None:
                if not isinstance(location,dict) or set(location)-{'country','region','postal_code','shipping_id'}:
                    raise HTTPException(422,'Use country, state, postal code and shipping method only')
                if not re.fullmatch('[A-Z]{2}',str(location.get('country',''))) or not all(isinstance(location.get(k),str) and 0<len(location[k])<=40 for k in ('region','postal_code')):
                    raise HTTPException(422,'Enter a quote country, state and postal code')
                if location.get('shipping_id') is not None and (type(location['shipping_id']) is not int or location['shipping_id']<=0):
                    raise HTTPException(422,'Select a valid shipping method ID')
            with LOCK,self.payment_lock:return self.validate_assignments(brand_id,location,body.get('campaign_id'))

        @app.post('/api/admin/reviews')
        def review(body:Proposal,req:Request):
            self.authenticated(req,True)
            with LOCK:
                data,guards,preview,ops,local_hash=self.prepare(body.kind,body.data)
                key=secrets.token_urlsafe(20)
                internal={'version':2,'request':body.data,'data':data,'guards':guards,'operations':ops}
                with self.store.db() as db:db.execute('INSERT INTO admin_reviews VALUES(?,?,?,?,?,?,?,NULL)',
                    (key,body.kind,json.dumps(internal),local_hash,'draft',time.time(),json.dumps(preview)))
            return {'id':key,'preview':preview}

        @app.post('/api/admin/reviews/{review_id}/refresh')
        def refresh_review(req:Request,review_id:str):
            self.authenticated(req,True)
            with LOCK:
                with self.store.db() as db:
                    old=db.execute('SELECT kind,data,status FROM admin_reviews WHERE id=?',(review_id,)).fetchone()
                if not old:raise HTTPException(404,'Review not found')
                if old[2]!='draft':raise HTTPException(409,'Only an unapplied draft can be refreshed')
                plan=json.loads(old[1]);payload=plan.get('request')
                if payload is None:
                    payload=dict(plan['data']);payload.pop('revision',None)
                    if old[0]=='offer' and not self.get('offering',payload.get('id')):payload.pop('id',None)
                data,guards,preview,ops,local_hash=self.prepare(old[0],payload)
                internal={'version':2,'request':payload,'data':data,'guards':guards,'operations':ops}
                with self.store.db() as db:
                    db.execute('UPDATE admin_reviews SET data=?,before_hash=?,created=?,preview=? WHERE id=? AND status=\'draft\'',
                        (json.dumps(internal),local_hash,time.time(),json.dumps(preview),review_id))
            return {'id':review_id,'kind':old[0],'status':'draft','preview':preview}

        @app.post('/api/admin/reviews/{review_id}/discard')
        def discard_review(req:Request,review_id:str):
            self.authenticated(req,True)
            with LOCK,self.store.db() as db:
                changed=db.execute("UPDATE admin_reviews SET status='discarded' WHERE id=? AND status='draft'",(review_id,)).rowcount
            if not changed:raise HTTPException(409,'Only an unapplied draft can be discarded')
            return {'status':'discarded'}

        @app.get('/api/admin/campaign-template')
        def campaign_template(req:Request,campaign_id:int):
            self.authenticated(req)
            if campaign_id<=0:raise HTTPException(422,'Select a campaign')
            c=self.api.detail(f'/api/v2/campaigns/{campaign_id}')
            alternatives=[x.get('provider',{}) for x in c.get('alternative_payments',[]) if x.get('payment_method')=='stripe_link']
            gateway=next((x.get('id') for x in alternatives if int(x.get('account_id') or 0)==250),None)
            return {'gateway_id':gateway,'channel_id':(c.get('channel') or {}).get('id',1),
                'offers':[int(x['id']) for x in c.get('offers',[])],
                'countries':[int(x['id']) for x in c.get('countries',[]) if x.get('id')],
                'shipping_profiles':[int(x['id']) for x in c.get('shipping_profiles',[])],
                'description':'Copies payment, country, shipping and offer selections. Review the new campaign before applying; fulfillment, email and other integrations are not copied.'}

        @app.post('/api/admin/apply')
        def apply(body:Approval,req:Request):
            self.authenticated(req,True)
            if not body.approve:raise HTTPException(422,'Explicit approval is required')
            with LOCK,self.payment_lock:
                with self.store.db() as db:
                    row=db.execute('SELECT kind,data,before_hash,status,created,result FROM admin_reviews WHERE id=?',(body.review_id,)).fetchone()
                if not row:raise HTTPException(404,'Review not found')
                if row[3]=='applied':return json.loads(row[5])
                if row[3]!='draft':raise HTTPException(409,'This operation needs reconciliation before it can be retried')
                if row[4]<time.time()-1800:raise HTTPException(409,'This preview expired; prepare another review')
                if self.local_fingerprint()!=row[2]:raise HTTPException(409,'Configuration changed; review again')
                plan=json.loads(row[1]);kind=row[0];data=plan['data']
                for guard in plan['guards']:
                    if 'models' in guard:current=fingerprint(model_rows(self.api))
                    elif 'gateway_currency' in guard:
                        gid=guard['gateway_currency'];g=self.api.detail(f'/api/v2/providers/payment/profiles/{gid}');raw=g.get('currency')
                        currency=str((raw.get('code') or raw.get('name','')) if isinstance(raw,dict) else raw or '').upper()
                        current=fingerprint({'id':gid,'account_id':g.get('account_id'),'currency':currency})
                    elif 'catalog' in guard:current=resolve(self.api,*guard['catalog'])['fingerprint']
                    else:
                        obj=self.api.detail(guard['path']);current=fingerprint({k:obj.get(k) for k in guard['keys']} if guard['keys'] else obj)
                    if current!=guard['hash']:raise HTTPException(409,'Sticky changed after this preview; review again')
                if kind in ('offer','campaign','provision','campaign_setup','site'):
                    brand=self.get('brand',data['brand_id']) or data.get('setup_brand')
                    campaign_id=data.get('campaign_id') or (brand or {}).get('campaign_id')
                    if campaign_id:
                        if isinstance(campaign_id,dict):campaign_id=0
                        with self.store.db() as db:
                            if db.execute("SELECT 1 FROM checkouts WHERE campaign=? AND status NOT IN ('new','captured') LIMIT 1",(campaign_id,)).fetchone():
                                raise HTTPException(409,'This campaign has an open payment; reconcile it before changing its offers or mapping')
                affected_links=[data['id']] if kind=='link' else [l['id'] for l in self.records('link') if l['brand_id']==data['id']] if kind=='brand' else []
                if kind in ('offer','provision','campaign_setup','therapy','purchase_option','plan_checkout','master','site','site_checkout'):
                    affected_links=json.loads(self._review_preview(body.review_id)).get('affectedCheckoutLinks',[])
                for affected_link in affected_links:
                    with self.store.db() as db:
                        if db.execute("SELECT 1 FROM checkouts WHERE link_id=? AND status NOT IN ('new','captured') LIMIT 1",(affected_link,)).fetchone():raise HTTPException(409,'This link has an open payment; reconcile it before editing')
                with self.store.db() as db:db.execute("UPDATE admin_reviews SET status='applying' WHERE id=?",(body.review_id,))
                completed={}
                try:
                    def references(value):
                        if isinstance(value,dict) and set(value)=={'$ref'}:
                            return completed[value['$ref']]
                        if plan.get('version',1)==1 and isinstance(value,str) and value in ('$product','$offer','$campaign'):
                            return completed[value[1:]]
                        if isinstance(value,list):return [references(x) for x in value]
                        if isinstance(value,dict):return {k:references(v) for k,v in value.items()}
                        return value
                    for op in plan['operations']:
                        payload=references(op['body']);obj=self.api.call(op['method'],op['path'],payload)
                        if str(obj.get('status','')).upper()!='SUCCESS':raise ValueError('Sticky did not confirm the write')
                        if op.get('save'):
                            oid=obj.get('data',{}).get('id') or obj.get('data',{}).get('c_id')
                            if not oid:raise ValueError('Sticky did not return the new object ID')
                            completed[op['save']]=int(oid)
                        with self.store.db() as db:db.execute('UPDATE admin_reviews SET result=? WHERE id=?',(json.dumps({'created':completed}),body.review_id))
                        if op.get('save'):
                            checked=self.api.detail(op['path']+'/'+str(completed[op['save']]))
                            if op.get('verify'):
                                expected=references(op['verify'])
                                if expected['kind']=='product' and (checked.get('sku')!=expected['sku'] or money(checked.get('price'))!=money(expected['price'])):
                                    raise ValueError('Master product read-back did not match')
                                if expected['kind']=='product' and expected.get('contract')!=product_contract(checked):
                                    raise ValueError('Master shipping/tax product read-back did not match')
                                if expected['kind']=='offer' and ({int(p['id']) for p in checked.get('products',[])}!={expected['product']} or offer_models(checked)!=set(expected['models'])):
                                    raise ValueError('Master offer read-back did not match')
                                if expected['kind']=='offer' and cycles_for(checked)!=expected.get('prepaid_cycles'):raise ValueError('Prepaid terms read-back did not match')
                                if expected['kind']=='campaign':
                                    routes=[p.get('provider',{}) for p in checked.get('alternative_payments',[]) if p.get('payment_method')=='stripe_link']
                                    if (set(expected['offers'])!={int(o['id']) for o in checked.get('offers',[])} or
                                        len(routes)!=1 or int(routes[0].get('id') or 0)!=expected['gateway'] or int(routes[0].get('account_id') or 0)!=250 or
                                        set(expected['countries'])!={int(x['id']) for x in checked.get('countries',[])} or
                                        set(expected['shipping'])!={int(x['id']) for x in checked.get('shipping_profiles',[])}):
                                        raise ValueError('Campaign payment, offers or fulfillment read-back did not match')
                            if op['save']=='product' and (checked.get('sku')!=payload['sku'] or money(checked.get('price'))!=money(payload['price'])):
                                raise ValueError('Product price/SKU read-back did not match')
                            if op['save']=='offer' and cycles_for(checked)!=cycles_for(data.get('configuration',{})):raise ValueError('Prepaid terms read-back did not match')
                            if op['save']=='offer' and (set(int(p['id']) for p in checked.get('products',[]))!={completed['product']} or set(int(m['id']) for m in checked.get('billing_models',[]))!=set(data['billing_models'])):
                                raise ValueError('Offer read-back did not match')
                        elif op['method']=='PUT':
                            checked=self.api.detail(op['path'])
                            if 'offers' in payload and not set(payload['offers']).issubset({int(o['id']) for o in checked.get('offers',[])}):raise ValueError('Offer attachment read-back did not match')
                    if kind in ('brand','sku','link'):
                        if kind=='link' and data.get('_link_brand'):
                            brand=data.pop('_link_brand');self.put('brand',brand['id'],brand)
                        self.put(kind,self.identity(kind,data),data)
                    elif kind in ('therapy','purchase_option','plan_checkout'):
                        self.finalize_plan(kind,data)
                    elif kind=='checkout_template':
                        self.put(kind,data['id'],data)
                    elif kind=='site_checkout':
                        self.finalize_plan('plan_checkout',data)
                    elif kind=='offer':
                        old=self.get('offering',data['id'])
                        if old:
                            for link in self.records('link'):
                                if link['brand_id']!=data['brand_id'] or link['sku']!=data['sku'] or record_campaign(link,self.get('brand',data['brand_id']))!=data['campaign_id']:continue
                                updated=[f"{completed['offer']}:{completed['product']}:{key.split(':')[2]}" if key.startswith(f"{old['offer_id']}:{old['product_id']}:") else key for key in link['options']]
                                if updated!=link['options']:
                                    link['options']=updated;link['revision']=link.get('revision',1)+1;self.put('link',link['id'],link)
                        self.put('offering',data['id'],data|{'product_id':completed['product'],'offer_id':completed['offer']})
                    elif kind=='campaign':
                        brand=attach_campaign(self.get('brand',data['brand_id']),completed['campaign']);self.put('brand',brand['id'],brand)
                    extra=self.finalize_site(data,references) if kind=='site' else self.finalize_master(kind,data,references) if kind in ('master','provision','campaign_setup') else {}
                    result={'status':'applied','created':completed,**extra}
                    with self.store.db() as db:db.execute("UPDATE admin_reviews SET status='applied',result=? WHERE id=?",(json.dumps(result),body.review_id))
                    return result
                except Exception:
                    with self.store.db() as db:db.execute("UPDATE admin_reviews SET status='reconcile',result=? WHERE id=?",(json.dumps({'status':'reconcile','created':completed}),body.review_id))
                    raise HTTPException(502,'The change is held for reconciliation. Inspect the recorded object IDs before retrying; no automatic retry was made.') from None
