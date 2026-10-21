"""Versioned master SKU presets and explicitly approved campaign assignments."""
import hashlib
import json
import secrets
from decimal import Decimal
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from catalog import CatalogError,enabled,money,resolve,quote
from prepaid import configuration as prepaid_configuration, cycles_for, unit_price


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


class MasterOffer(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,39}$')
    name: str = Field(min_length=1,max_length=100)
    price: Decimal = Field(gt=0,max_digits=10,decimal_places=2)
    billing_models: list[int] = Field(min_length=1,max_length=30)

    prepaid_cycles: int | None = Field(default=None,ge=2,le=36,strict=True)

    @model_validator(mode='after')
    def prepaid_valid(self):
        if self.prepaid_cycles:
            if len(self.billing_models)!=1 or self.billing_models[0]==2:raise ValueError('Prepaid needs one shipment interval')
            unit_price(self.price,self.prepaid_cycles)
        return self

    @field_validator('billing_models')
    @classmethod
    def unique_models(cls,value):
        if any(i<1 for i in value) or len(set(value))!=len(value):raise ValueError('Choose unique positive billing models')
        return value


class MasterSKU(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    sku: str = Field(min_length=1,max_length=200)
    name: str = Field(min_length=1,max_length=150)
    category: str = Field(default='',max_length=80)
    therapy_id: str = Field(default='',max_length=61)
    treatment_id: str = Field(default='',max_length=61)
    product_duration_months: int | None = Field(default=None,ge=1,le=36,strict=True)
    product_id: int | None = Field(default=None,gt=0)
    fulfillment_product_id: int = Field(default=2856,gt=0)
    currency: str = Field(default='USD',pattern=r'^(USD|EUR|GBP|CAD|AUD|NZD|CHF)$')
    enabled: bool = True
    offers: list[MasterOffer] = Field(min_length=1,max_length=10)

    @field_validator('offers')
    @classmethod
    def unique_offers(cls,value):
        if len({o.id for o in value})!=len(value):raise ValueError('Offer identifiers must be unique')
        return value


class Provision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    brand_id: str = Field(min_length=1,max_length=61)
    campaign_id: int | None = Field(default=None,gt=0)
    skus: list[str] | None = Field(default=None,min_length=1,max_length=100)


class CampaignSetup(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    campaign_id: int | None = Field(default=None,gt=0)
    brand_id: str | None = Field(default=None,min_length=1,max_length=61)
    name: str = Field(default='',max_length=100)
    template_id: int = Field(default=422,gt=0)


def source_product(master,watch):
    return watch(f"/api/v2/products/{master['product_id']}") if master.get('product_id') else master['product_template']


def brand_campaigns(brand):
    return list(dict.fromkeys(([brand['campaign_id']] if brand and brand.get('campaign_id') else [])+list((brand or {}).get('campaign_ids',[]))))


def attach_campaign(brand,cid):
    ids=brand_campaigns(brand)
    if cid not in ids:ids.append(cid)
    return dict(brand,campaign_id=brand.get('campaign_id') or cid,campaign_ids=ids)


def record_campaign(record,brand):
    return record.get('campaign_id') or (brand or {}).get('campaign_id')


def clone_product(p,name,sku,price):
    if p.get('sku')!=sku or enabled(p.get('archived_flag')) or enabled(p.get('is_bundle')) or enabled(p.get('is_variant_enabled')):
        raise HTTPException(422,'A matching active simple source product is required')
    product={'name':name[:150],'sku':sku,'category_id':p['category_id'],
        'description':p.get('description') or name,'price':float(money(price)),
        'cost_of_goods':float(money(p.get('cost_of_goods',0))),'restocking_fee':float(money(p.get('restocking_fee',0))),
        'max_quantity':p.get('max_quantity') or 1,'is_shippable':int(enabled(p.get('is_shippable'))),
        'is_taxable':int(enabled(p.get('taxable',p.get('is_taxable')))),'auto_create_variants':0,'attributes':[]}
    for field in ('weight','tax_code','is_delivery_confirm','is_signature_confirm','is_qty_preserved','is_collections_enabled'):
        if p.get(field) is not None:product[field]=p[field]
    if isinstance(p.get('weight_unit'),dict) and p['weight_unit'].get('id'):product['weight_unit_id']=p['weight_unit']['id']
    elif p.get('weight_unit_id') is not None:product['weight_unit_id']=p['weight_unit_id']
    if p.get('shipping_restrictions'):
        restrictions=p['shipping_restrictions']
        if any(not isinstance(r,dict) or not r.get('country_id') or not isinstance(r.get('values'),list) for r in restrictions):
            raise HTTPException(422,'This product has shipping restrictions that need an explicit mapping before copying')
        product['shipping_restrictions']=[{'country_id':r['country_id'],'values':r['values']} for r in restrictions]
    return product


def product_contract(p):
    return {'sku':p.get('sku'),'category_id':int(p['category_id']),
        'is_shippable':int(enabled(p.get('is_shippable'))),'taxable':int(enabled(p.get('taxable',p.get('is_taxable')))),
        'max_quantity':int(p.get('max_quantity') or 1),'is_variant_enabled':int(enabled(p.get('is_variant_enabled'))),
        'is_bundle':int(enabled(p.get('is_bundle'))),
        'weight':str(Decimal(str(p['weight'])).normalize()) if p.get('weight') is not None else None,
        'weight_unit_id':(p.get('weight_unit') or {}).get('id') if isinstance(p.get('weight_unit'),dict) else p.get('weight_unit_id'),
        'tax_code':p.get('tax_code'),'shipping_restrictions':p.get('shipping_restrictions') or []}


def model_rows(api):
    obj=api.call('GET','/api/v2/billing_models')
    if str(obj.get('status','')).upper()!='SUCCESS':raise HTTPException(502,'Sticky billing models could not be verified')
    rows=obj.get('data',[])
    return list(rows.values()) if isinstance(rows,dict) else rows


def offer_models(o):
    return {int(m['id']) for m in (o.get('offer_billing_models') or o.get('billing_models',[]))}


def billing_terms(model):
    return {'days':int(model.get('days') or 0),'type_id':int((model.get('type') or {}).get('id') or 0),
        'frequency':model.get('frequency'),'frequency_type_id':model.get('frequency_type_id')}


def assignment_id(brand,campaign,sku):
    return hashlib.sha256(f'{brand}:{campaign}:{sku}'.encode()).hexdigest()[:24]


class MasterCatalog:
    def local_fingerprint(self):
        return fingerprint([self.records(k) for k in ('brand','sku','link','offering','master','assignment','therapy','plan_checkout')])

    def prepare_setup(self,payload):
        request=CampaignSetup.model_validate(payload).model_dump(mode='json')
        cid=request['campaign_id'];creating=cid is None
        if creating and not request['name']:raise HTTPException(422,'Enter a campaign name')
        if creating and not request['brand_id'] and any(b['name'].casefold()==request['name'].casefold() for b in self.records('brand')):
            raise HTTPException(409,'A campaign with this name is already managed. Select the existing campaign or use a different name.')
        with self.store.db() as db:
            held=db.execute("SELECT data,result FROM admin_reviews WHERE kind='campaign_setup' AND status IN ('applying','reconcile')").fetchall()
        for row in held:
            prior=json.loads(row[0])['request']
            created=json.loads(row[1] or '{}').get('created',{})
            if (cid and cid in (prior.get('campaign_id'),created.get('campaign'))) or (creating and not prior.get('campaign_id') and prior.get('name','').casefold()==request['name'].casefold()):
                raise HTTPException(409,'This campaign setup needs reconciliation. Inspect its recorded objects before trying again.')
        template=self.api.detail(f"/api/v2/campaigns/{request['template_id'] if creating else cid}")
        matches=[b for b in self.records('brand') if cid and cid in brand_campaigns(b)]
        selected=self.get('brand',request['brand_id']) if request['brand_id'] else None
        if request['brand_id'] and not selected:raise HTTPException(422,'Save the brand first')
        if len(matches)>1 and not selected:raise HTTPException(422,'Select the brand for this campaign')
        brand=selected or (matches[0] if matches else {'id':'campaign-'+(str(cid) if cid else secrets.token_hex(10)),
            'name':request['name'] if creating else template.get('name') or 'Campaign '+str(cid),
            'campaign_id':None,'logo_url':'','color':'#245844','support_email':'','support_phone':'','custom_domain':''})
        if not selected and not matches and self.get('brand',brand['id']):raise HTTPException(409,'This campaign identifier is already mapped. Resolve it in advanced settings.')
        campaign=dict(template)
        if creating:campaign.update(id=0,offers=[])
        data,guards,preview,ops,local=self.prepare_master('provision',{'brand_id':brand['id']},context=(dict(brand,campaign_id=cid or 0),campaign))
        if creating:
            guards.append({'path':f"/api/v2/campaigns/{request['template_id']}",'keys':None,'hash':fingerprint(template)})
            routing=[p['provider']['id'] for p in template.get('alternative_payments',[]) if p.get('payment_method')=='stripe_link' and int(p.get('provider',{}).get('account_id') or 0)==250]
            countries=[int(x['id']) for x in template.get('countries',[]) if x.get('id')]
            shipping=[int(x['id']) for x in template.get('shipping_profiles',[]) if x.get('id')]
            if len(routing)!=1 or not countries or not shipping:raise HTTPException(422,'Choose a template with Stripe v2, countries and shipping configured')
            attach=ops.pop()['body']['offers']
            body={'name':request['name'],'description':'Managed through WLMD Core master catalog','gateway_id':routing[0],
                'channel_id':(template.get('channel') or {}).get('id',1),'offers':attach,'countries':countries,'shipping_profiles':shipping,
                'payment_methods':['visa','stripe_link'],'alternative_payments':[{'id':routing[0],'payment_method':'stripe_link'}],
                'return_profiles':[],'coupon_profiles':[],'postback_profiles':[],'is_prepaid_blocked':0}
            ops.append({'method':'POST','path':'/api/v2/campaigns','body':body,'save':'campaign','verify':{'kind':'campaign','offers':attach,'gateway':routing[0],'countries':countries,'shipping':shipping}})
            data['campaign_id']={'$ref':'campaign'}
            for a in data['assignments']:a['campaign_id']={'$ref':'campaign'}
        # The primary legacy campaign remains stable; append new memberships only.
        data['setup_brand']=brand
        preview.update(after={'name':request['name'] if creating else template.get('name'),'brand_id':brand['id'],'brand_name':brand['name'],'campaign_id':cid or 'New campaign','skus':[a['sku'] for a in data['assignments']]},stickyWrites=ops,
            impact=('Creates a campaign using payment, country and shipping settings from campaign '+str(request['template_id'])+'. Other integrations are not copied. Sticky may require API access or Stripe Link setup before links become payable. ' if creating else 'Assigns every enabled master SKU to this campaign, preserving its routing and existing brand prices. ')+
            'Creates private checkout links automatically. Review all prices and billing intervals below.')
        return data,guards,preview,ops,local

    def prepare_master(self,kind,payload,context=None):
        data=(MasterSKU if kind=='master' else Provision).model_validate(payload).model_dump(mode='json')
        if kind=='master':
            for o in data['offers']:
                if o.get('prepaid_cycles') is None:o.pop('prepaid_cycles',None)
        guards=[];operations=[]
        def watch(path):
            obj=self.api.detail(path);guards.append({'path':path,'keys':None,'hash':fingerprint(obj)});return obj
        models=model_rows(self.api)
        guards.append({'models':True,'hash':fingerprint(models)})
        available={int(m['id']):m for m in models if not enabled(m.get('is_archived'))}
        if kind=='master':
            p=watch(f"/api/v2/products/{data['product_id'] or data['fulfillment_product_id']}")
            if not data['product_id']:
                p=dict(p,sku=data['sku'],name=data['name'],description=data['name'],cost_of_goods=0,restocking_fee=0)
                # Fulfillment defaults are independent of each offer's selling price.
                data['product_template']=clone_product(p,data['name'],data['sku'],0)
            clone_product(p,data['name'],data['sku'],data['offers'][0]['price'])
            for o in data['offers']:
                for mid in o['billing_models']:
                    m=available.get(mid)
                    if not m:raise HTTPException(422,'Choose active configured billing models')
                    if mid!=2 and (int(m.get('days') or 0)<=0 or int((m.get('type') or {}).get('id') or 0)!=1):
                        raise HTTPException(422,'Master provisioning currently supports standard one-time and day-based recurring models')
            data['billing_terms']={str(mid):billing_terms(available[mid]) for o in data['offers'] for mid in o['billing_models']}
            before=self.get('master',data['sku'])
            presentation=('category','product_duration_months','therapy_id','treatment_id')
            for field in presentation:
                if before and field not in payload:data[field]=before.get(field,None if field=='product_duration_months' else '')
            defaults={'fulfillment_product_id':2856,'category':'','product_duration_months':None,'therapy_id':'','treatment_id':''}
            if data['therapy_id']:
                therapy=self.get('therapy',data['therapy_id'])
                if not therapy or not therapy['enabled'] or data['treatment_id'] not in {t['id'] for t in therapy['treatments']}:raise HTTPException(422,'Choose an active therapy and one of its treatments')
            elif data['treatment_id']:raise HTTPException(422,'Choose a therapy before its treatment')
            old=dict(defaults,**(before or {}))
            metadata_only=bool(before) and any(old[k]!=data[k] for k in presentation) and all(old.get(k)==v for k,v in data.items() if k not in presentation)
            data['revision']=(before or {}).get('revision',0)+(0 if metadata_only else 1)
            preview={'before':before,'after':data,'stickyWrites':[],
                'impact':'Category and product duration describe the catalog; they do not change charges, quantities, doses or refill rules. Saves this master preset and its source SKU mapping only. Existing campaigns, prices and subscriptions stay on their approved setup until a campaign assignment is separately reviewed.',
                'affectedCampaigns':[a['campaign_id'] for a in self.records('assignment') if a['sku']==data['sku']]}
            if before and any(before.get(k)!=data.get(k) for k in ('therapy_id','treatment_id','product_duration_months')):
                preview['affectedCheckoutLinks']=[l['id'] for l in self.records('link') if l['sku']==data['sku'] and l.get('plan_checkout_id')]
            if any(o.get('prepaid_cycles') for o in data['offers']) and (enabled(p.get('is_shippable')) or enabled(p.get('taxable',p.get('is_taxable')))):
                preview['readinessNote']='This prepaid plan can be saved in your catalog. Campaign assignment is blocked until prepaid shipping and tax support is verified for this product. Existing checkouts keep their approved options.'
        else:
            brand=context[0] if context else self.get('brand',data['brand_id'])
            if not brand or (not context and not brand.get('campaign_id')):raise HTTPException(422,'Create a brand and map its campaign first')
            cid=brand['campaign_id'] if context else data.get('campaign_id') or brand['campaign_id']
            if not context and cid not in brand_campaigns(brand):raise HTTPException(422,'Select a campaign attached to this brand')
            with self.store.db() as db:
                held=db.execute("SELECT data,result FROM admin_reviews WHERE kind IN ('provision','campaign_setup') AND status IN ('applying','reconcile')").fetchall()
            if any(json.loads(r[0])['data'].get('campaign_id')==cid or (cid and json.loads(r[1] or '{}').get('created',{}).get('campaign')==cid) for r in held):
                raise HTTPException(409,'This campaign has an unresolved master assignment. Reconcile its recorded object IDs before preparing another.')
            c=context[1] if context else watch(f'/api/v2/campaigns/{cid}')
            if context and cid:guards.append({'path':f'/api/v2/campaigns/{cid}','keys':None,'hash':fingerprint(c)})
            if enabled(c.get('is_archived')) or c.get('is_active') in (False,0,'0'):raise HTTPException(422,'Select an active campaign')
            masters=[m for m in self.records('master') if m['enabled']]
            if data['skus'] is not None:
                if len(set(data['skus']))!=len(data['skus']):raise HTTPException(422,'Choose each SKU once')
                if not set(data['skus']).issubset({m['sku'] for m in masters}):raise HTTPException(422,'Select enabled master SKUs')
                masters=[m for m in masters if m['sku'] in data['skus']]
            if not masters:raise HTTPException(422,'Save at least one enabled master SKU first')
            if len(masters)>100:raise HTTPException(422,'Assign at most 100 master SKUs in one reviewed batch')
            # Currency is part of the price contract, never infer it from a SKU.
            providers=[x.get('provider',{}) for x in c.get('alternative_payments',[]) if x.get('payment_method')=='stripe_link']
            currency=None
            if len(providers)==1 and int(providers[0].get('account_id') or 0)==250:
                g=self.api.detail(f"/api/v2/providers/payment/profiles/{int(providers[0]['id'])}")
                raw=g.get('currency');currency=str((raw.get('code') or raw.get('name','')) if isinstance(raw,dict) else raw or '').upper()
                # Never persist gateway credential fields in a review.
                safe={'id':providers[0]['id'],'account_id':g.get('account_id'),'currency':currency}
                guards.append({'gateway_currency':providers[0]['id'],'hash':fingerprint(safe)})
            if not currency:raise HTTPException(422,'Configure this campaign with a Stripe Connect v2 currency before assigning prices')
            attached=[int(o['id']) for o in c.get('offers',[])];attach=list(attached)
            entries=[];assignments=[];affected=set();replacements=[]
            for index,master in enumerate(masters):
                if master['currency']!=currency:raise HTTPException(422,'Master and campaign currencies differ; configure an explicit preset for this currency')
                source=source_product(master,watch)
                if any(o.get('prepaid_cycles') for o in master['offers']) and (enabled(source.get('is_shippable')) or enabled(source.get('taxable',source.get('is_taxable')))):
                    raise HTTPException(422,master['sku']+': prepaid plan saved, but campaign assignment needs verified prepaid shipping and tax support. Existing campaigns are unchanged. Use a non-shippable, non-taxable test product to test this plan now.')
                old_assignment=next((a for a in self.records('assignment') if a['brand_id']==brand['id'] and a['campaign_id']==cid and a['sku']==master['sku']),None)
                aid=old_assignment['id'] if old_assignment else assignment_id(brand['id'],cid or secrets.token_hex(12),master['sku'])
                slots=[];entry={'sku':master['sku'],'revision':master['revision'],'offers':[]}
                # Removing an offer must never silently disable an existing link.
                wanted_ids={o['id'] for o in master['offers']}
                removed=[o for o in (old_assignment or {}).get('offers',[]) if o['master_offer_id'] not in wanted_ids]
                for old in removed:
                    old=self.get('offering',old['id']) or old
                    prefix=f"{old['offer_id']}:{old['product_id']}:"
                    if any(l['brand_id']==brand['id'] and any(k.startswith(prefix) for k in l['options']) for l in self.records('link')):
                        raise HTTPException(422,'Remove retired master offer choices from checkout links before assigning this revision')
                for number,preset in enumerate(master['offers']):
                    for mid in preset['billing_models']:
                        m=available.get(mid)
                        if m and master['billing_terms'].get(str(mid))!=billing_terms(m):
                            raise HTTPException(409,'Master billing terms changed in Sticky; review and save the master before assigning it')
                        if not m or (mid!=2 and (int(m.get('days') or 0)<=0 or int((m.get('type') or {}).get('id') or 0)!=1)):
                            raise HTTPException(422,'A master billing model changed or is no longer supported; review the master first')
                    oid='master-'+aid+'-'+preset['id']
                    old=self.get('offering',oid)
                    desired={'id':oid,'brand_id':brand['id'],'campaign_id':cid,'sku':master['sku'],'name':preset['name'],
                        'price':(old or {}).get('price',preset['price']),'billing_models':preset['billing_models'],'configuration':prepaid_configuration(preset.get('prepaid_cycles'))}
                    reuse=False
                    if old:
                        product=watch(f"/api/v2/products/{old['product_id']}");offer=watch(f"/api/v2/offers/{old['offer_id']}")
                        if product.get('sku')!=master['sku'] or enabled(product.get('archived_flag')) or money(product.get('price'))!=unit_price(old['price'],cycles_for(old.get('configuration',{}))):
                            raise HTTPException(409,'An assigned product changed in Sticky; reconcile its SKU/price before provisioning again')
                        if {int(p['id']) for p in offer.get('products',[])}!={old['product_id']} or offer_models(offer)!=set(old['billing_models']):
                            raise HTTPException(409,'An assigned offer changed in Sticky; reconcile its products/models before provisioning again')
                        if any(enabled(offer.get(k)) for k in ('is_archived','is_trial','is_series','is_seasonal')):
                            raise HTTPException(409,'An assigned offer has unsupported or archived terms; reconcile it first')
                        if cycles_for(offer)!=cycles_for(old.get('configuration',{})):raise HTTPException(409,'Assigned prepaid terms changed; reconcile before applying')
                        if (old_assignment or {}).get('source_hash')==fingerprint(source) and product_contract(product)!=product_contract(source):
                            raise HTTPException(409,'An assigned product shipping/tax configuration changed; reconcile it before assigning again')
                        reuse=all((record_campaign(old,brand) if k=='campaign_id' else old.get(k))==v for k,v in desired.items()) and (old_assignment or {}).get('source_hash')==fingerprint(source)
                    if reuse:
                        pid,offerid=old['product_id'],old['offer_id'];action='Reuse existing managed offer'
                    else:
                        pk,ok=f'product_{index}_{number}',f'offer_{index}_{number}'
                        pid,offerid={'$ref':pk},{'$ref':ok}
                        product=clone_product(source,brand['name']+' / '+master['name']+' / '+preset['name'],master['sku'],unit_price(desired['price'],preset.get('prepaid_cycles')))
                        body={'type_id':1,'is_trial':0,**desired['configuration'],'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2},'name':brand['name']+' / '+preset['name'],
                            'products':[{'id':pid}],'billing_models':[{'id':mid} for mid in preset['billing_models']]}
                        operations.extend([{'method':'POST','path':'/api/v2/products','body':product,'save':pk,'verify':{'kind':'product','sku':master['sku'],'price':str(unit_price(desired['price'],preset.get('prepaid_cycles'))),'contract':product_contract(source)}},
                            {'method':'POST','path':'/api/v2/offers','body':body,'save':ok,'verify':{'kind':'offer','product':pid,'models':preset['billing_models'],'prepaid_cycles':preset.get('prepaid_cycles')}}])
                        action='Create replacement managed offer' if old else 'Create managed offer'
                        if old:
                            prefix=f"{old['offer_id']}:{old['product_id']}:"
                            for link in self.records('link'):
                                if link['brand_id']!=brand['id'] or link['sku']!=master['sku']:continue
                                keys=[key for key in link['options'] if key.startswith(prefix)]
                                if any(int(key.rsplit(':',1)[1]) not in preset['billing_models'] for key in keys):
                                    raise HTTPException(422,'Remove retired billing choices from checkout links before assigning this revision')
                                if keys:affected.add(link['id'])
                            replacements.append({'oldPrefix':prefix,'product':pid,'offer':offerid,'sku':master['sku']})
                    if offerid not in attach:attach.append(offerid)
                    slots.append(desired|{'product_id':pid,'offer_id':offerid,'master_offer_id':preset['id']})
                    entry['offers'].append({'prepaid_cycles':preset.get('prepaid_cycles'),'name':preset['name'],'price':desired['price'],'currency':currency,'billing_models':preset['billing_models'],
                        'billing_days':[available[mid].get('days') for mid in preset['billing_models']], 'action':action,'price_source':'Existing brand price' if old else 'Master default'})
                link_id='master-'+aid
                existing_link=self.get('link',link_id)
                if existing_link and (existing_link['brand_id']!=brand['id'] or existing_link['sku']!=master['sku'] or record_campaign(existing_link,brand)!=cid):raise HTTPException(409,'The generated link identifier is already used by another checkout')
                entry['checkout_link']=link_id;entry['checkout_action']='Keep existing access and enabled choices' if existing_link else 'Create private checkout with all master choices'
                assignments.append({'id':aid,'brand_id':brand['id'],'campaign_id':cid,'sku':master['sku'],'master_revision':master['revision'],
                    'currency':currency,'name':master['name'],'offers':slots,'link_id':link_id,'source_hash':fingerprint(source),'source_contract':product_contract(source),'billing_terms':master['billing_terms']})
                entries.append(entry)
            if attach!=attached:operations.append({'method':'PUT','path':f'/api/v2/campaigns/{cid}','body':{'offers':attach}})
            data.update(campaign_id=cid,assignments=assignments,replacements=replacements)
            preview={'before':{'campaign_id':cid,'assigned_skus':[a['sku'] for a in self.records('assignment') if a['campaign_id']==cid and a['brand_id']==brand['id']]},
                'after':{'brand_id':brand['id'],'campaign_id':cid,'skus':[m['sku'] for m in masters]},'entries':entries,'stickyWrites':operations,'affectedCheckoutLinks':sorted(affected),
                'impact':'Assigns master presets to this campaign. Existing brand prices, unrelated offers, gateway routing and integrations are preserved. New checkouts are private. Existing customer choices and access settings are retained; removed choices must be adjusted explicitly first.',
                'paymentReadiness':'Configuration is checked after attachment. Real processor payments and future rebills are not tested by this operation.'}
        return data,guards,preview,operations,self.local_fingerprint()

    def finalize_master(self,kind,data,refs):
        if kind=='master':
            self.put('master',data['sku'],data)
            self.put('sku',data['sku'],{k:data[k] for k in ('sku','name','product_id')})
            return {'masterRevision':data['revision']}
        data=refs(data)
        if data.get('setup_brand'):self.put('brand',data['brand_id'],attach_campaign(data['setup_brand'],data['campaign_id']))
        for replacement in data['replacements']:
            for link in self.records('link'):
                if link['brand_id']!=data['brand_id'] or link['sku']!=replacement['sku'] or record_campaign(link,self.get('brand',data['brand_id']))!=data['campaign_id']:continue
                keys=[f"{replacement['offer']}:{replacement['product']}:{key.rsplit(':',1)[1]}" if key.startswith(replacement['oldPrefix']) else key for key in link['options']]
                if keys!=link['options']:
                    link['options']=keys;link['revision']=link.get('revision',1)+1;self.put('link',link['id'],link)
        new_links=[]
        for assignment in data['assignments']:
            for slot in assignment['offers']:
                record={k:v for k,v in slot.items() if k!='master_offer_id'};record['campaign_id']=assignment['campaign_id']
                self.put('offering',slot['id'],record)
            self.put('assignment',assignment['id'],assignment)
            if not self.get('link',assignment['link_id']):
                new_links.append(assignment['link_id'])
                choices=[f"{o['offer_id']}:{o['product_id']}:{mid}" for o in assignment['offers'] for mid in o['billing_models']]
                self.put('link',assignment['link_id'],{'id':assignment['link_id'],'brand_id':assignment['brand_id'],'campaign_id':assignment['campaign_id'],'sku':assignment['sku'],'title':assignment['name'],
                    'visibility':'private','options':choices,'enabled':False,'revision':1})
        validation=self.validate_assignments(data['brand_id'],campaign_id=data['campaign_id'])
        for item in validation['skus']:
            if item['link_id'] in new_links and item['ready']:
                link=self.get('link',item['link_id']);link['enabled']=True;self.put('link',link['id'],link)
        return {'validation':validation,'checkoutLinks':[a['link_id'] for a in data['assignments']]}

    def validate_assignments(self,brand_id,location=None,campaign_id=None):
        brand=self.get('brand',brand_id)
        if not brand or not brand.get('campaign_id'):raise HTTPException(422,'Select a mapped brand')
        cid=campaign_id or brand['campaign_id']
        if type(cid) is not int or cid not in brand_campaigns(brand):raise HTTPException(422,'Select a campaign attached to this brand')
        rows=[]
        for assignment in self.records('assignment'):
            if assignment['brand_id']!=brand_id or assignment['campaign_id']!=cid:continue
            master=self.get('master',assignment['sku']);item={'sku':assignment['sku'],'revision':assignment['master_revision'],
                'masterCurrent':bool(master and master['enabled'] and master['revision']==assignment['master_revision']),'link_id':assignment['link_id'],'checks':[]}
            try:
                current_models={int(m['id']):m for m in model_rows(self.api)}
                c=resolve(self.api,cid,assignment['sku'])
                for slot in assignment['offers']:
                    current=self.get('offering',slot['id']) or slot
                    product=self.api.detail(f"/api/v2/products/{current['product_id']}")
                    for mid in slot['billing_models']:
                        key=f"{current['offer_id']}:{current['product_id']}:{mid}";o=next((o for o in c['options'] if o['key']==key),None)
                        error=c['blockedReason'] or (o or {}).get('blockedReason') or ('The assigned option is missing' if not o else '')
                        if mid not in current_models or assignment['billing_terms'].get(str(mid))!=billing_terms(current_models[mid]) or enabled(current_models[mid].get('is_archived')):
                            error='Billing terms changed after this master revision was assigned'
                        if o and money(o.get('upfrontPrice',o['basePrice']))!=money(current['price']):error='Assigned price differs from Sticky'
                        if o and o.get('prepaidCycles')!=cycles_for(current.get('configuration',{})):error='Assigned prepaid terms differ from Sticky'
                        if product_contract(product)!=assignment['source_contract']:error='Assigned shipping/tax product settings changed'
                        if (c['currency'] or '').upper()!=assignment['currency']:error='Campaign currency changed'
                        if not c['countries']:error='Campaign countries are missing'
                        if o and o['shippable'] and not c['shipping']:error='Campaign shipping options are missing'
                        check={'prepaid_cycles':(o or {}).get('prepaidCycles'),'offer':slot['name'],'model_id':mid,'days':(o or {}).get('days'),'price':current['price'],'currency':assignment['currency'],'ready':not bool(error),'detail':error or 'Configuration ready; payment not submitted'}
                        if location and not error:
                            try:
                                q=quote(self.api,c,key,location.get('shipping_id'),location)
                                check.update(quote_total=q['total'],quote_currency=q['currency'],detail='Server quote verified; payment not submitted')
                            except Exception:
                                check.update(ready=False,detail='Sticky quote could not be verified for this location and shipping method')
                        item['checks'].append(check)
            except Exception:
                item['checks']=[{'ready':False,'detail':'Campaign/SKU read-back could not be verified. Check Sticky access and configuration.'}]
            item['ready']=bool(item['checks']) and all(x['ready'] for x in item['checks']);rows.append(item)
        return {'campaign_id':cid,'skus':rows,'ready':bool(rows) and all(x['ready'] for x in rows),'payment_submitted':False}
