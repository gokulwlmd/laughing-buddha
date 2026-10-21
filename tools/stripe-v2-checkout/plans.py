"""Therapy catalog and branded multi-SKU plan selection; no payment writes."""
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from catalog import resolve, CatalogError
from master import brand_campaigns

HERE=Path(__file__).resolve().parent

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def choice_id(plan_id,sku):return 'choice-'+hashlib.sha256((plan_id+'\0'+sku).encode()).hexdigest()[:32]

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
class PlanEntry(Form):
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
    entries:list[PlanEntry]=Field(min_length=1,max_length=20)
    @field_validator('entries')
    @classmethod
    def unique(cls,items):
        if len({x.sku for x in items})!=len(items):raise ValueError('Choose each SKU once')
        return items

class ReadCache:
    """Request-local catalog reuse across SKUs, never a cross-request price cache."""
    def __init__(self,api):self.api,self.cache=api,{}
    def detail(self,path):
        if path not in self.cache:self.cache[path]=self.api.detail(path)
        return self.cache[path]

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
            plan['entries']=[{'sku':entry['sku'],'options':(self.get('link',choice_id(plan['id'],entry['sku'])) or entry)['options']} for entry in plan['entries']]
            plan['url']=self.cfg.public_url+'/plans/'+plan['id']
            if plan['visibility']=='private':plan['url']+='?access='+self.plan_token(plan)
        return plans

    def prepare_plan(self,kind,payload):
        data=(Therapy if kind=='therapy' else PlanCheckout).model_validate(payload).model_dump(mode='json')
        before=self.get(kind,data['id']);guards=[];children=[]
        if kind=='therapy':
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
                key=choice_id(data['id'],entry['sku']);old=self.get('link',key)
                if old and old.get('plan_checkout_id')!=data['id']:raise HTTPException(409,'The generated checkout identifier is already in use')
                children.append({'id':key,'brand_id':data['brand_id'],'campaign_id':data['campaign_id'],'sku':entry['sku'],
                    'title':(data['title']+' · '+master['name'])[:150],'visibility':'private','enabled':data['enabled'],'options':entry['options'],
                    'revision':(old or {}).get('revision',0)+1,'plan_checkout_id':data['id']})
            affected=[l['id'] for l in self.records('link') if l.get('plan_checkout_id')==data['id']]
            impact='Publishes one branded plan-selection link for these SKUs and purchase options. Customers choose a treatment, product duration and payment option, then enter secure checkout. A public link makes all selected choices publicly accessible. Existing standalone links, Sticky prices, subscriptions and clinical rules are unchanged.'
        preview={'before':before,'after':dict(data),'stickyWrites':[],'affectedCheckoutLinks':affected,'impact':impact}
        if children:data['_children']=children
        return data,guards,preview,[],self.local_fingerprint()

    def finalize_plan(self,kind,data):
        if kind=='therapy':self.put(kind,data['id'],data);return
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
        cache=ReadCache(self.api);entries=[]
        for entry in plan['entries']:
            master=self.get('master',entry['sku']);item={'sku':entry['sku'],'available':False,'reason':'This plan is temporarily unavailable.'}
            try:
                _,treatment=self.therapy_for(master or {},therapy['id'])
                item.update(name=master['name'],durationMonths=master['product_duration_months'],treatmentId=treatment['id'])
                child,_=self.link(choice_id(plan['id'],entry['sku']))
                c=resolve(cache,plan['campaign_id'],entry['sku'])
                options=[{k:o[k] for k in ('key','recurring','days','basePrice','blockedReason','prepaidCycles','upfrontPrice') if k in o} for o in c['options'] if o['key'] in child['options'] and not o['blockedReason']]
                if c['blockedReason'] or not options:raise ValueError('Not ready')
                item.update(available=True,reason='',currency=c['currency'],options=options)
            except (HTTPException,CatalogError,ValueError):pass
            entries.append(item)
        return {'id':plan['id'],'title':plan['title'],'therapy':therapy['name'],'treatments':therapy['treatments'],'branding':branding(brand),'entries':entries}

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
            return {'entries':entries}

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
        def choose(req:Request,key:str,sku:str,option:str):
            plan,brand,therapy=self.plan_access(req,key)
            if sku not in {e['sku'] for e in plan['entries']}:raise HTTPException(404,'Plan not found')
            master=self.get('master',sku);self.therapy_for(master or {},therapy['id'])
            child,_=self.link(choice_id(key,sku))
            if option not in child['options']:raise HTTPException(422,'Choose an enabled purchase option')
            c=resolve(self.api,plan['campaign_id'],sku)
            selected=next((o for o in c['options'] if o['key']==option),None)
            if c['blockedReason'] or not selected or selected['blockedReason']:raise HTTPException(409,'This purchase option is unavailable; choose another plan')
            response=RedirectResponse('/c/'+child['id']+'?'+urlencode({'selection':option}),status_code=303)
            response.set_cookie('link_access_'+child['id'],self.private_token(child),secure=True,httponly=True,samesite='lax',max_age=86400)
            return response
