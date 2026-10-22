"""Therapy catalog and branded multi-SKU plan selection; no payment writes."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from catalog import resolve, CatalogError, enabled
from master import brand_campaigns

HERE=Path(__file__).resolve().parent

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def choice_id(plan_id,sku,purchase_option_id=''):
    value=plan_id+'\0'+sku+('\0'+purchase_option_id if purchase_option_id else '')
    return 'choice-'+hashlib.sha256(value.encode()).hexdigest()[:32]

def payment_type(option):
    return 'prepaid' if option.get('prepaidCycles') else 'subscription' if option['recurring'] else 'once'

class Form(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class Treatment(Form):
    id:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{0,60}$')
    name:str=Field(min_length=1,max_length=100)
class Therapy(Form):
    id:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{0,60}$')
    name:str=Field(min_length=1,max_length=100)
    treatments:list[Treatment]=Field(min_length=1,max_length=20)
    enabled:bool=True
    @field_validator('treatments')
    @classmethod
    def unique(cls,items):
        if len({x.id for x in items})!=len(items):raise ValueError('Treatment identifiers must be unique')
        return items
class PurchaseOption(Form):
    id:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{0,80}$')
    name:str=Field(min_length=1,max_length=100)
    therapy_id:str=Field(min_length=1,max_length=61)
    duration_months:int=Field(ge=1,le=36,strict=True)
    skus:list[str]=Field(default_factory=list,max_length=20)
    payment_types:list[str]=Field(min_length=1,max_length=3)
    enabled:bool=True
    @field_validator('skus','payment_types')
    @classmethod
    def unique(cls,items):
        if len(set(items))!=len(items):raise ValueError('Choose each item once')
        return items
    @field_validator('payment_types')
    @classmethod
    def valid_types(cls,items):
        if not set(items).issubset({'once','subscription','prepaid'}):raise ValueError('Choose supported payment types')
        return items

class PlanEntry(Form):
    purchase_option_id:str=Field(default='',max_length=81)
    sku:str=Field(min_length=1,max_length=200)
    options:list[str]=Field(min_length=1,max_length=100)
    @field_validator('options')
    @classmethod
    def unique(cls,items):
        if len(set(items))!=len(items):raise ValueError('Choose each purchase option once')
        return items
class PlanCheckout(Form):
    id:str=Field(pattern=r'^[a-z0-9][a-z0-9-]{1,80}$')
    brand_id:str=Field(min_length=1,max_length=61)
    campaign_id:int=Field(gt=0)
    therapy_id:str=Field(min_length=1,max_length=61)
    title:str=Field(min_length=1,max_length=150)
    visibility:str=Field(pattern=r'^(public|private)$')
    enabled:bool=True
    purchase_option_ids:list[str]=Field(default_factory=list,max_length=20)
    entries:list[PlanEntry]=Field(default_factory=list,max_length=100)
    @field_validator('entries')
    @classmethod
    def unique(cls,items):
        if len({(x.purchase_option_id,x.sku) for x in items})!=len(items):raise ValueError('Choose each SKU once per purchase option')
        return items

    @model_validator(mode='after')
    def source(self):
        if not self.entries and not self.purchase_option_ids:raise ValueError('Select at least one purchase option')
        if len(set(self.purchase_option_ids))!=len(self.purchase_option_ids):raise ValueError('Choose each purchase option once')
        return self

class ReadCache:
    """Request-local catalog reuse across SKUs, never a cross-request price cache."""
    def __init__(self,api):self.api,self.cache=api,{}
    def detail(self,path):
        if path not in self.cache:self.cache[path]=self.api.detail(path)
        return self.cache[path]
    def prefetch_choices(self,campaign_id,keys):
        if not keys:return
        allowed={tuple(int(part) for part in key.split(':')) for key in keys}
        c=self.detail(f'/api/v2/campaigns/{campaign_id}')
        offers=[o for o in c.get('offers',[]) if int(o['id']) in {key[0] for key in allowed}]
        with ThreadPoolExecutor(max_workers=8) as pool:
            offers=list(pool.map(lambda o:o if 'products' in o else self.detail('/api/v2/offers/'+str(o['id'])),offers))
        products={int(p['id']) for o in offers if not enabled(o.get('is_archived')) for p in o.get('products',[]) if any(key[:2]==(int(o['id']),int(p['id'])) for key in allowed)}
        paths=[f'/api/v2/products/{pid}' for pid in sorted(products)]
        links=[x.get('provider',{}) for x in c.get('alternative_payments',[]) if x.get('payment_method')=='stripe_link']
        if len(links)==1 and int(links[0].get('account_id') or 0)==250:paths.append(f"/api/v2/providers/payment/profiles/{int(links[0]['id'])}")
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(self.detail,paths))

class PlanCatalog:
    def plan_token(self,plan):
        return hmac.new(self.invite.encode(),f"plan-checkout:{plan['id']}:{plan.get('revision',1)}".encode(),hashlib.sha256).hexdigest()

    def therapy_for(self,master,therapy_id=None):
        therapy=self.get('therapy',master.get('therapy_id',''))
        if not therapy or not therapy['enabled'] or (therapy_id and therapy['id']!=therapy_id):raise HTTPException(422,'Assign this SKU to an active therapy first')
        treatment=next((x for x in therapy['treatments'] if x['id']==master.get('treatment_id')),None)
        if not treatment:raise HTTPException(422,'Choose a treatment for this SKU')
        if not master.get('product_duration_months'):raise HTTPException(422,'Set the product duration before adding this SKU to a plan checkout')
        return therapy,treatment

    def plan_record(self,key):
        plan=self.get('plan_checkout',key)
        if not plan or not plan['enabled']:raise HTTPException(404,'This plan checkout is unavailable')
        brand=self.get('brand',plan['brand_id']);therapy=self.get('therapy',plan['therapy_id'])
        if not brand or plan['campaign_id'] not in brand_campaigns(brand) or not therapy or not therapy['enabled']:raise HTTPException(409,'This plan checkout needs configuration')
        return plan,brand,therapy

    def plan_access(self,req,key):
        plan,brand,therapy=self.plan_record(key)
        if plan['visibility']=='private' and not hmac.compare_digest(req.cookies.get('plan_access_'+key,''),self.plan_token(plan)):raise HTTPException(401,'Open the private plan checkout invitation')
        return plan,brand,therapy

    def plan_state(self):
        plans=self.records('plan_checkout')
        for plan in plans:
            # Managed price replacement updates child choices; expose their current mappings.
            plan['entries']=[dict(entry,options=(self.get('link',choice_id(plan['id'],entry['sku'],entry.get('purchase_option_id',''))) or entry)['options']) for entry in plan['entries']]
            plan['purchaseOptionsCurrent']=all((self.get('purchase_option',o['id']) or {}).get('revision')==o.get('revision') for o in plan.get('purchase_options',[]))
            plan['url']=self.cfg.public_url+'/plans/'+plan['id']
            if plan['visibility']=='private':plan['url']+='?access='+self.plan_token(plan)
        return plans

    def managed_choices(self,brand_id,campaign_id,sku,catalog,payment_types):
        assignment=next((a for a in self.records('assignment') if a['brand_id']==brand_id and a['campaign_id']==campaign_id and a['sku']==sku),None)
        allowed=set()
        for slot in (assignment or {}).get('offers',[]):
            current=self.get('offering',slot['id']) or {}
            if current.get('brand_id')!=brand_id or current.get('sku')!=sku or current.get('campaign_id',campaign_id)!=campaign_id:continue
            allowed.update(f"{current['offer_id']}:{current['product_id']}:{mid}" for mid in current['billing_models'])
        return [o for o in catalog['options'] if o['key'] in allowed and payment_type(o) in payment_types and not o['blockedReason']]

    def prepare_plan(self,kind,payload):
        data={'therapy':Therapy,'purchase_option':PurchaseOption,'plan_checkout':PlanCheckout}[kind].model_validate(payload).model_dump(mode='json')
        before=self.get(kind,data['id']);guards=[];children=[]
        if kind=='purchase_option':
            therapy=self.get('therapy',data['therapy_id'])
            if not therapy or not therapy['enabled']:raise HTTPException(422,'Choose an active therapy')
            if before and before['therapy_id']!=data['therapy_id']:raise HTTPException(422,'Create a new purchase option to change its therapy')
            for sku in data['skus']:
                master=self.get('master',sku)
                self.therapy_for(master or {},data['therapy_id'])
                if master['product_duration_months']!=data['duration_months']:raise HTTPException(422,sku+': product duration must match the purchase option')
                supported=({'subscription' if master['planning_contract']['renewal_months'] else 'once'} if master.get('planning_contract') else set())
                if master.get('planning_contract') and (master['planning_contract']['shipments_per_term'] or 0)>1:supported.add('prepaid')
                for offer in master['offers']:
                    if offer.get('prepaid_cycles'):supported.add('prepaid')
                    else:
                        if 2 in offer['billing_models']:supported.add('once')
                        if any(mid!=2 for mid in offer['billing_models']):supported.add('subscription')
                if not supported.intersection(data['payment_types']):raise HTTPException(422,sku+': no configured payment choice matches this purchase option')
            data['revision']=(before or {}).get('revision',0)+1
            affected=[l['id'] for l in self.records('link') if l.get('purchase_option_id')==data['id']]
            impact='Saves a reusable duration purchase option and its assigned SKU alternatives. SKU prices and billing rules are retained. Existing checkouts keep their published selection until you review and publish them again. Disabling this purchase option immediately disables its choices in existing checkouts.'
        elif kind=='therapy':
            wanted={t['id'] for t in data['treatments']}
            if any(m.get('therapy_id')==data['id'] and m.get('treatment_id') not in wanted for m in self.records('master')):raise HTTPException(422,'A treatment is used by a master SKU. Reassign that SKU before removing it.')
            affected=[l['id'] for l in self.records('link') if l.get('plan_checkout_id') and (self.get('plan_checkout',l['plan_checkout_id']) or {}).get('therapy_id')==data['id']]
            impact='Saves therapy and treatment organization locally. Treatment selection expresses customer preference; dose, clinical eligibility and refill approval are separate.'
        else:
            brand=self.get('brand',data['brand_id']);therapy=self.get('therapy',data['therapy_id'])
            if not brand or data['campaign_id'] not in brand_campaigns(brand):raise HTTPException(422,'Choose a campaign belonging to this brand')
            if not therapy or not therapy['enabled']:raise HTTPException(422,'Choose an active therapy')
            if before and any(before[k]!=data[k] for k in ('brand_id','campaign_id')):raise HTTPException(422,'Create a new plan checkout to change its brand or campaign')
            cache=ReadCache(self.api)
            data['revision']=(before or {}).get('revision',0)+1
            if data['purchase_option_ids']:
                if payload.get('entries'):raise HTTPException(422,'Select purchase options; their assigned SKUs and payment choices are resolved by the server')
                data['purchase_options']=[];data['entries']=[]
                for pid in data['purchase_option_ids']:
                    purchase=self.get('purchase_option',pid)
                    if not purchase or not purchase['enabled'] or purchase['therapy_id']!=data['therapy_id']:raise HTTPException(422,'Choose active purchase options belonging to this therapy')
                    if not purchase['skus']:raise HTTPException(422,purchase['name']+': assign matching-duration SKUs first')
                    data['purchase_options'].append(purchase)
                    for sku in purchase['skus']:
                        master=self.get('master',sku) or {}
                        self.therapy_for(master,data['therapy_id'])
                        if master['product_duration_months']!=purchase['duration_months']:raise HTTPException(422,sku+': product duration must match the purchase option')
                        try:c=resolve(cache,data['campaign_id'],sku)
                        except CatalogError:raise HTTPException(422,sku+': assign this SKU to the campaign before publishing') from None
                        choices=[o['key'] for o in self.managed_choices(data['brand_id'],data['campaign_id'],sku,c,purchase['payment_types'])]
                        if c['blockedReason'] or not choices:raise HTTPException(422,sku+': no supported payment choices are available on this campaign')
                        data['entries'].append({'purchase_option_id':pid,'sku':sku,'options':choices})
            elif before and before.get('purchase_option_ids'):
                raise HTTPException(422,'Select purchase options for this checkout')
            elif any(e.get('purchase_option_id') for e in data['entries']):
                raise HTTPException(422,'Select saved purchase options before assigning their choices')
            if len(data['entries'])>100:raise HTTPException(422,'Choose at most 100 SKU alternatives per checkout')
            for entry in data['entries']:
                master=self.get('master',entry['sku'])
                if not master:raise HTTPException(422,'Save this master SKU first: '+entry['sku'])
                self.therapy_for(master,data['therapy_id'])
                try:c=resolve(cache,data['campaign_id'],entry['sku'])
                except CatalogError:raise HTTPException(422,entry['sku']+': assign this SKU to the selected campaign and verify its purchase options') from None
                available={o['key']:o for o in c['options']}
                if not set(entry['options']).issubset(available):raise HTTPException(422,'Choose purchase options belonging to '+entry['sku'])
                if data['enabled'] and (c['blockedReason'] or any(available[k]['blockedReason'] for k in entry['options'])):raise HTTPException(422,entry['sku']+': one or more selected purchase options are not ready for checkout')
                guards.append({'catalog':[data['campaign_id'],entry['sku']],'hash':c['fingerprint']})
                key=choice_id(data['id'],entry['sku'],entry.get('purchase_option_id',''));old=self.get('link',key)
                if old and old.get('plan_checkout_id')!=data['id']:raise HTTPException(409,'The generated checkout identifier is already in use')
                children.append({'id':key,'brand_id':data['brand_id'],'campaign_id':data['campaign_id'],'sku':entry['sku'],
                    'title':(data['title']+' · '+master['name'])[:150],'visibility':'private','enabled':data['enabled'],'options':entry['options'],
                    'revision':(old or {}).get('revision',0)+1,'plan_checkout_id':data['id'],'purchase_option_id':entry.get('purchase_option_id','')})
            affected=[l['id'] for l in self.records('link') if l.get('plan_checkout_id')==data['id']]
            impact='Publishes one branded plan-selection link for these SKUs and purchase options. Customers compare duration purchase options with each treatment’s price, choose one SKU and a payment choice, then enter secure checkout. A public link makes all selected choices publicly accessible. Existing standalone links, Sticky prices, subscriptions and clinical rules are unchanged.'
        preview={'before':before,'after':dict(data),'stickyWrites':[],'affectedCheckoutLinks':affected,'impact':impact}
        if children:data['_children']=children
        return data,guards,preview,[],self.local_fingerprint()

    def finalize_plan(self,kind,data):
        if kind in ('therapy','purchase_option'):self.put(kind,data['id'],data);return
        data=dict(data);children=data.pop('_children');wanted={c['id'] for c in children}
        # Local records are committed atomically; no partially published collections.
        with self.store.db() as db:
            for link in self.records('link'):
                if link.get('plan_checkout_id')==data['id'] and link['id'] not in wanted:
                    children.append(dict(link,enabled=False,revision=link.get('revision',1)+1))
            for record_kind,record in [('plan_checkout',data)]+[('link',c) for c in children]:
                db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',(record_kind,record['id'],json.dumps(record)))

    def plan_options(self,plan,brand,therapy):
        from admin import branding
        cache=ReadCache(self.api);entries=[];children={}
        for entry in plan['entries']:
            key=choice_id(plan['id'],entry['sku'],entry.get('purchase_option_id',''))
            try:children[key]=self.link(key)[0]
            except HTTPException:pass
        # Warm only published, campaign-attached choices concurrently. Without
        # this, narrowing each SKU would serialize a large multi-plan page.
        cache.prefetch_choices(plan['campaign_id'],{option for child in children.values() for option in child['options']})
        for entry in plan['entries']:
            master=self.get('master',entry['sku']);item={'sku':entry['sku'],'purchaseOptionId':entry.get('purchase_option_id',''),'available':False,'reason':'This plan is temporarily unavailable.'}
            try:
                _,treatment=self.therapy_for(master or {},therapy['id'])
                item.update(name=master['name'],durationMonths=master['product_duration_months'],treatmentId=treatment['id'])
                child,_=self.link(choice_id(plan['id'],entry['sku'],entry.get('purchase_option_id','')))
                c=self.filter_catalog(resolve(cache,plan['campaign_id'],entry['sku'],allowed_keys=child['options']),child,brand)
                options=[{k:o[k] for k in ('key','recurring','days','basePrice','blockedReason','prepaidCycles','upfrontPrice','renewal','renewalDays') if k in o} for o in c['options'] if o['key'] in child['options'] and not o['blockedReason']]
                if c['blockedReason'] or not options:raise ValueError('Not ready')
                item.update(available=True,reason='',currency=c['currency'],options=options)
            except (HTTPException,CatalogError,ValueError):pass
            entries.append(item)
        return {'id':plan['id'],'title':plan['title'],'paymentTestOnly':bool(plan.get('payment_test_only')),'therapy':therapy['name'],'treatments':therapy['treatments'],'branding':branding(brand),'entries':entries,'purchaseOptions':[{'id':p['id'],'name':p['name'],'durationMonths':p['duration_months']} for p in plan.get('purchase_options',[])]}

    def attach_plans(self,app):
        @app.get('/api/admin/plan-options')
        def options(req:Request,brand_id:str,campaign_id:int,therapy_id:str):
            self.authenticated(req)
            brand=self.get('brand',brand_id)
            if not brand or campaign_id not in brand_campaigns(brand):raise HTTPException(422,'Choose a campaign belonging to this brand')
            therapy=self.get('therapy',therapy_id)
            if not therapy or not therapy['enabled']:raise HTTPException(422,'Choose an active therapy')
            entries=[];cache=ReadCache(self.api)
            for master in self.records('master'):
                if master.get('therapy_id')!=therapy_id:continue
                item={'sku':master['sku'],'name':master['name'],'durationMonths':master.get('product_duration_months'),'treatmentId':master.get('treatment_id'),'options':[]}
                try:
                    self.therapy_for(master,therapy_id);c=resolve(cache,campaign_id,master['sku'])
                    item.update(options=c['options'],currency=c['currency'],reason=c['blockedReason'])
                except (HTTPException,CatalogError):item['reason']='Set treatment and duration, assign the SKU to this campaign, then verify its checkout options.'
                entries.append(item)
            purchases=[]
            for purchase in self.records('purchase_option'):
                if purchase['therapy_id']!=therapy_id:continue
                items=[]
                for sku in purchase['skus']:
                    entry=next((e for e in entries if e['sku']==sku),None)
                    if not entry:items.append({'sku':sku,'reason':'Reassign this SKU to the therapy','options':[]});continue
                    entry=dict(entry)
                    entry['options']=self.managed_choices(brand_id,campaign_id,sku,entry,purchase['payment_types'])
                    if entry['durationMonths']!=purchase['duration_months']:entry['reason']='Product duration must match the purchase option'
                    if not entry['options']:entry['reason']=entry.get('reason') or 'Assign this master SKU and its payment choices to the campaign first'
                    items.append(entry)
                ready=purchase['enabled'] and bool(items) and all(not e.get('reason') and e['options'] for e in items)
                purchases.append(dict(purchase,entries=items,ready=ready))
            return {'entries':entries,'purchaseOptions':purchases}

        @app.get('/plans/{key}')
        def page(req:Request,key:str):
            try:
                plan,_,_=self.plan_record(key);token=req.query_params.get('access')
                if token:
                    if not hmac.compare_digest(token,self.plan_token(plan)):raise HTTPException(401,'Private invitation required')
                    response=RedirectResponse('/plans/'+key,status_code=303);response.set_cookie('plan_access_'+key,token,secure=True,httponly=True,samesite='lax',max_age=86400);return response
                self.plan_access(req,key)
                return FileResponse(HERE/'web/plans.html')
            except HTTPException as exc:return FileResponse(HERE/'web'/('access.html' if exc.status_code==401 else 'unavailable.html'),status_code=exc.status_code)

        @app.get('/api/plans/{key}')
        def config(req:Request,key:str):return self.plan_options(*self.plan_access(req,key))

        @app.get('/plans/{key}/choose')
        def choose(req:Request,key:str,sku:str,option:str,purchase_option_id:str=''):
            plan,brand,therapy=self.plan_access(req,key)
            if (purchase_option_id,sku) not in {(e.get('purchase_option_id',''),e['sku']) for e in plan['entries']}:raise HTTPException(404,'Plan not found')
            master=self.get('master',sku);self.therapy_for(master or {},therapy['id'])
            child,_=self.link(choice_id(key,sku,purchase_option_id))
            if option not in child['options']:raise HTTPException(422,'Choose an enabled purchase option')
            # This handoff grants only an already-published child. Its config,
            # quote and Pay endpoints perform the live availability checks.
            response=RedirectResponse('/c/'+child['id']+'?'+urlencode({'selection':option}),status_code=303)
            response.set_cookie('link_access_'+child['id'],self.private_token(child),secure=True,httponly=True,samesite='lax',max_age=86400)
            return response
