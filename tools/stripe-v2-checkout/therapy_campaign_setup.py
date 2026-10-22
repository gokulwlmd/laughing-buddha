"""Explicit owner-authorized campaign 422 payment-test catalog, never real-card QA.

Journal every external write on the existing Fly volume. Uncertain writes stop;
reruns reuse confirmed IDs and never retry a pending operation automatically.
"""
import copy
import hashlib
import json
import os
import time
from decimal import Decimal
from pathlib import Path

RUN = 'master-therapy-422-20261022-v1'
ORIGIN = 'https://wlmd-stripe-test-0f89b1bb.fly.dev'
BRAND = 'master-therapy-test-422'
LOCATION = {'country':'US','region':'CA','postal_code':'94105','shipping_id':2}


def offer_config(cycles=None, renewal=False):
    return {'type_id':2,'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2},
            'prepaid':{'is_subscription':int(renewal),'is_convert_to_standard':0,
            'is_cancel_immediate':0,'is_refund_allowed':1,'is_initial_shipping_on_restart':0,
            'terms':[{'cycles':cycles,'discount_type_id':1,'discount_value':0}]}} if cycles else {
            'type_id':1,'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2}}


def specification(product, master):
    c=master.get('planning_contract') or product
    months=product['duration_months'];count=c.get('shipments_per_term')
    cycles=count if count and count>1 else None
    renewal=bool(c.get('renewal_months'))
    days=c.get('shipment_interval') if cycles else months*30 if renewal else 0
    if cycles and renewal and cycles*days!=months*30:
        raise ValueError('Shipment cycles must match the agreed full-term renewal: '+product['sku'])
    if days not in (0,30,90,180,360):raise ValueError('Unsupported configured billing interval')
    total=Decimal(master['offers'][0]['price'])
    unit=total/Decimal(cycles or 1)
    if unit!=unit.quantize(Decimal('.01')):raise ValueError('Price needs exact-cent shipment units')
    return {'sku':product['sku'],'name':master['name'],'total':str(total),'unit':str(unit),
            'cycles':cycles,'renewal':renewal,'days':days,'model':{0:2,30:3,90:4,180:5,360:6}[days],
            'configuration':offer_config(cycles,renewal)}


def routing(campaign):
    return {k:v for k,v in campaign.items() if k not in ('offers','updated_at','updator')}


class Setup:
    def __init__(self, application):
        self.admin=application.state.admin;self.api=self.admin.api
        if self.admin.cfg.synthetic or self.admin.cfg.public_url!=ORIGIN or self.admin.cfg.state_dir!=Path('/data'):
            raise ValueError('Run only on the existing live Fly application')
        self.path=Path('/data',RUN+'.json')
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'id':RUN,'operations':{}}

    def save(self):
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.state));os.chmod(temp,0o600);temp.replace(self.path)

    def write(self,key,method,path,body):
        digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        previous=self.state['operations'].get(key)
        if previous:
            if previous['body_hash']!=digest or previous['status']!='confirmed':
                raise ValueError('Reconcile recorded operation before retry: '+key)
            return previous['result']
        self.state['operations'][key]={'status':'pending','method':method,'path':path,'body_hash':digest,'created':time.time()};self.save()
        response=self.api.call(method,path,body)
        result={k:response[k] for k in ('status','response_code','error_found','order_id','new_order_id','resp_msg') if k in response}
        if isinstance(response.get('data'),dict):result['data']={k:v for k,v in response['data'].items() if k in ('id','c_id')}
        self.state['operations'][key].update(status='confirmed',result=result);self.save()
        return result

    def create(self,key,path,body):
        r=self.write(key,'POST',path,body)
        if str(r.get('status')).upper()!='SUCCESS':raise ValueError('Sticky did not confirm '+key)
        return int(r.get('data',{}).get('id') or r.get('data',{}).get('c_id'))

    def check_campaign(self):
        c=self.api.detail('/api/v2/campaigns/422')
        routes=[p.get('provider',{}) for p in c.get('alternative_payments',[]) if p.get('payment_method')=='stripe_link']
        if len(routes)!=1 or int(routes[0]['id'])!=254 or int(routes[0]['account_id'])!=250:
            raise ValueError('Campaign 422 routing changed')
        if any(c.get(k) not in (0,'0',None,[]) for k in ('fulfillment_id','tax_provider_id','email_provider_id','membership_provider_id','postback_profiles')):
            raise ValueError('Payment-test campaign must have no external fulfillment/notification integrations')
        gateway=self.api.detail('/api/v2/providers/payment/profiles/254')
        fields=gateway.get('fields',{}).get('account_fields',{})
        if gateway.get('currency',{}).get('code')!='USD' or not str(fields.get('publishable_key','')).startswith('pk_live_'):
            raise ValueError('Expected existing live USD connection')
        if any(fields.get(k) not in (None,False,0,'0','') for k in ('capture_on_shipment','enable_delayed_capture')):
            raise ValueError('Delayed capture is unsupported')
        return c

    def product(self,key,sku,name,unit):
        body={'name':name[:150],'sku':sku,'category_id':113,'description':'Owner-authorized payment test only; no medication fulfillment.',
              'price':float(Decimal(unit)),'cost_of_goods':0,'restocking_fee':0,'max_quantity':1,
              'is_shippable':0,'is_taxable':0,'auto_create_variants':0,'attributes':[]}
        pid=self.create(key,'/api/v2/products',body)
        p=self.api.detail('/api/v2/products/'+str(pid))
        if p['sku']!=sku or Decimal(str(p['price']))!=Decimal(unit) or p.get('is_shippable') not in (0,'0',False) or p.get('taxable',p.get('is_taxable')) not in (0,'0',False):
            raise ValueError('New test product read-back mismatch: '+sku)
        return pid

    def offer(self,key,pid,spec):
        oid=self.create(key,'/api/v2/offers',dict(spec['configuration'],name='WLMD payment test / '+spec['sku'],is_trial=0,
                        products=[{'id':pid}],billing_models=[{'id':spec['model']}]))
        o=self.api.detail('/api/v2/offers/'+str(oid))
        if {int(p['id']) for p in o['products']}!={pid} or {int(m['id']) for m in o['billing_models']}!={spec['model']}:
            raise ValueError('Offer product/model mismatch')
        if spec['cycles']:
            p=o.get('prepaid_profile') or o.get('prepaid') or {}
            if int(p.get('is_subscription',-1))!=int(spec['renewal']) or p.get('terms',[{}])[0].get('cycles')!=spec['cycles']:
                raise ValueError('Offer prepaid term mismatch')
        return oid

    def view_order(self,oid,cid,pid,cycles):
        o=self.api.call('POST','/api/v1/order_view',{'order_id':[str(oid)]})
        if str(o.get('response_code'))!='100' or str(o.get('is_test_cc'))!='1' or int(o.get('gateway_id',0))!=1 or int(o.get('campaign_id',0))!=cid:
            raise ValueError('Unverified dry-run order; stop')
        p=o['products'][0]
        if int(p['product_id'])!=pid or str(o.get('shippable',p.get('is_shippable','0')))!='0':raise ValueError('Unexpected dry-run product or shipping')
        terms=p.get('prepaid',[{}])[0]
        if int(terms.get('total_cycles',0))!=cycles or str(terms.get('is_renew'))!='1':raise ValueError('Prepaid renewal read-back mismatch')
        return {'order_id':str(oid),'total':str(o['order_total']),'cycle':int(terms['current_cycle']),
                'cycles':cycles,'recurring':str(p.get('is_recurring',o.get('is_recurring'))),
                'next_date':p.get('recurring_date',o.get('recurring_date')),'ancestor':o.get('ancestor_id'),
                'subscription':p.get('subscription_id'),'gateway_id':1,'test':True,'child':o.get('child_id')}

    def verify_renewal(self):
        dry=self.api.detail('/api/v2/providers/payment/profiles/1')
        if int(dry.get('account_id',0))!=10 or dry.get('account_name')!='Dry Run Testing':raise ValueError('Dry-run gateway identity changed')
        self.check_campaign()
        fixtures=[]
        for count in (2,4):
            spec={'sku':RUN+'-'+str(count),'model':4,'cycles':count,'renewal':True,'configuration':offer_config(count,True)}
            pid=self.product('proof-product-'+str(count),spec['sku'],'WLMD synthetic renewing prepaid proof', '10.00')
            oid=self.offer('proof-offer-'+str(count),pid,spec);fixtures.append((count,pid,oid))
        cid=self.create('proof-campaign','/api/v2/campaigns',{'name':RUN+' Dry Run ONLY','description':'Synthetic renewal verification; no live payments or fulfillment.',
            'channel_id':1,'gateway_id':1,'payment_methods':['visa'],'offers':[x[2] for x in fixtures],
            'countries':[223],'shipping_profiles':[2],'return_profiles':[],'coupon_profiles':[],'postback_profiles':[],'is_prepaid_blocked':0})
        c=self.api.detail('/api/v2/campaigns/'+str(cid))
        if int(c.get('gateway_id',0))!=1 or any(c.get(k) not in (None,0,'0',[]) for k in ('fulfillment_id','email_provider_id','membership_provider_id','tax_provider_id','postback_profiles')):
            raise ValueError('Dry-run campaign isolation failed')
        proof=[]
        for count,pid,oid in fixtures:
            body={'firstName':'WLMD','lastName':'SyntheticTest','shippingAddress1':'1 Synthetic Test Way','shippingCity':'San Francisco','shippingState':'CA','shippingZip':'94105','shippingCountry':'US',
                'phone':'2025550100','email':RUN+'-'+str(count)+'@example.invalid','creditCardType':'visa','creditCardNumber':'1444444444444440','expirationDate':'1230','CVV':'123',
                'tranType':'Sale','ipAddress':'192.0.2.1','campaignId':cid,'shippingId':2,'billingSameAsShipping':'YES','forceGatewayId':1,'preserve_force_gateway':1,
                'offers':[{'offer_id':oid,'product_id':pid,'billing_model_id':4,'quantity':1,'prepaid_cycles':count}], 'notes':RUN+' synthetic renewal proof; no fulfillment.'}
            r=self.write('proof-order-'+str(count),'POST','/api/v1/new_order',body)
            if str(r.get('response_code'))!='100' or str(r.get('error_found'))!='0':raise ValueError('Dry-run order not approved')
            current=self.view_order(r['order_id'],cid,pid,count);chain=[current]
            for step in range(count):
                r=self.write('proof-advance-'+str(count)+'-'+str(step),'POST','/api/v1/order_force_bill',{'order_id':current['order_id'],'forceGatewayId':1,'preserve_force_gateway':1})
                if str(r.get('response_code'))!='100' or str(r.get('error_found','0'))!='0':raise ValueError('Dry-run advance not approved')
                parent=self.view_order(current['order_id'],cid,pid,count)
                child=r.get('new_order_id') or r.get('order_id')
                if not child or str(child)==current['order_id']:child=parent['child']
                if not child:raise ValueError('No verified next dry-run order')
                current=self.view_order(child,cid,pid,count);chain.append(current)
            expected=[Decimal('10')*count]+[Decimal('0')]*(count-1)+[Decimal('10')*count]
            if [Decimal(x['total']) for x in chain]!=expected or [x['cycle'] for x in chain]!=list(range(1,count+1))+[1]:
                raise ValueError('Prepaid full-term renewal amounts/cycles did not match')
            if len({x['subscription'] for x in chain})!=1 or len({x['ancestor'] for x in chain})!=1:raise ValueError('Renewal subscription chain changed')
            proof.append({'cycles':count,'interval_days':90,'renewal_days':count*90,'orders':chain})
        self.state['renewal_proof']={'campaign_id':cid,'gateway_id':1,'chains':proof,'real_payments':0,'physical_shipments':0};self.save()
        return self.state['renewal_proof']

    def provision(self):
        if self.state.get('published'):return {'already_provisioned':True,'products':40,'offers':40,'attached_to_live_campaign':True}
        from therapy_skeletons import all_skeletons
        from master import fingerprint
        c=self.check_campaign()
        if 'original' not in self.state:
            offers={str(o['id']):self.api.detail('/api/v2/offers/'+str(o['id'])) for o in c['offers']}
            products={str(p['id']):self.api.detail('/api/v2/products/'+str(p['id'])) for o in offers.values() for p in o['products']}
            self.state['original']={'routing_hash':fingerprint(routing(c)),
                'offers':{i:fingerprint(o) for i,o in offers.items()},'products':{i:fingerprint(p) for i,p in products.items()}}
            self.save()
        models={int(m['id']):m for m in self.api.call('GET','/api/v2/billing_models')['data']}
        for mid,days in ((3,30),(4,90),(5,180),(6,360)):
            if int(models[mid].get('days',0))!=days or int((models[mid].get('type') or {}).get('id',0))!=1:
                raise ValueError('Configured billing model changed')
        catalog=self.state.setdefault('catalog',{})
        for skeleton in all_skeletons():
            for product in skeleton['products']:
                master=self.admin.get('master',product['sku'])
                if not master:raise ValueError('Missing authorized master SKU')
                spec=specification(product,master)
                spec['name']=product['treatment']+' / '+str(product['duration_months'])+' months / '+('Subscription' if spec['renewal'] else 'One-time')
                pid=self.product('product-'+spec['sku'],spec['sku'],'WLMD payment test / '+spec['name'],spec['unit'])
                oid=self.offer('offer-'+spec['sku'],pid,spec)
                catalog[spec['sku']]=dict(spec,product_id=pid,offer_id=oid,master_hash=fingerprint(master),therapy_id=skeleton['therapy']['id'])
                self.save()
        return {'created_products':len(catalog),'created_offers':len(catalog),'attached_to_live_campaign':False,'real_payments':0}

    def publish(self):
        """Add only new offers; preserve all existing terms, routing and held attempts."""
        from master import fingerprint, assignment_id, billing_terms, product_contract
        from catalog import resolve,quote
        from plans import ReadCache
        from sites import checkout_id
        from therapy_skeletons import all_skeletons
        if self.state.get('published'):return dict(self.state['published'],already_published=True)
        if not self.state.get('renewal_proof'):raise ValueError('Complete isolated renewal verification before enabling payment choices')
        catalog=self.state.get('catalog',{})
        if len(catalog)!=40:raise ValueError('Provision all 40 products/offers first')
        local_before=self.admin.local_fingerprint()
        c=self.check_campaign();original=self.state['original']
        if fingerprint(routing(c))!=original['routing_hash']:raise ValueError('Campaign routing/integrations changed; review again')
        for kind in ('offers','products'):
            for identifier,digest in original[kind].items():
                if fingerprint(self.api.detail('/api/v2/'+kind+'/'+identifier))!=digest:raise ValueError('Existing catalog changed; stop before attachment')
        for sku,spec in catalog.items():
            if fingerprint(self.admin.get('master',sku))!=spec['master_hash']:raise ValueError('Master changed during setup: '+sku)
        # This operator action is deliberately additive. It cannot replace/remove
        # an offer or touch a gateway, product, historical quote or held attempt.
        old_ids=[int(o['id']) for o in c['offers']]
        desired=list(dict.fromkeys(old_ids+[s['offer_id'] for s in catalog.values()]))
        if set(old_ids)!=set(desired):
            result=self.write('attach-live-offers','PUT','/api/v2/campaigns/422',{'offers':desired})
            if str(result.get('status')).upper()!='SUCCESS':raise ValueError('Offer attachment not confirmed')
        actual=self.check_campaign()
        if fingerprint(routing(actual))!=original['routing_hash'] or not set(desired).issubset({int(o['id']) for o in actual['offers']}):
            raise ValueError('Campaign attachment read-back failed')
        # Read through one cache: all 40 quotes are calculated by Sticky, never
        # by a client price override, and never followed by authorization.
        cache=ReadCache(self.api);verified=[]
        for sku,spec in catalog.items():
            c=resolve(cache,422,sku);key=f"{spec['offer_id']}:{spec['product_id']}:{spec['model']}"
            q=quote(self.api,c,key,2,LOCATION)
            if Decimal(q['total'])!=Decimal(spec['total']):raise ValueError('Full upfront quote mismatch: '+sku)
            option=q['option']
            if option.get('prepaidCycles')!=spec['cycles'] or bool(option.get('renewal'))!=bool(spec['cycles'] and spec['renewal']):raise ValueError('Payment term mismatch')
            if option['days']!=spec['days']:raise ValueError('Billing interval mismatch')
            verified.append({'sku':sku,'product_id':spec['product_id'],'offer_id':spec['offer_id'],'billing_model_id':spec['model'],
                'upfront_total':q['total'],'cycles':spec['cycles'],'renewal_days':(spec['days']*(spec['cycles'] or 1)) if spec['renewal'] else None})
        models={int(m['id']):m for m in self.api.call('GET','/api/v2/billing_models')['data']}
        records=[]
        existing_brand=self.admin.get('brand',BRAND)
        source=self.admin.get('brand','campaign-422')
        brand=existing_brand or dict(copy.deepcopy(source),id=BRAND,name='Master Therapy Payment Test',campaign_id=422,campaign_ids=[422],revision=1)
        if not source:raise ValueError('Existing campaign brand is missing')
        if not existing_brand:records.append(('brand',BRAND,brand))
        # TIRZ-1M retains its original approved offers; add only organization
        # metadata so the new independently priced payment test can be grouped.
        old=self.admin.get('master','TIRZ-1M')
        organized=dict(old,therapy_id='weight-loss',treatment_id='tirzepatide',product_duration_months=1)
        records.append(('master','TIRZ-1M',organized))
        for sku,spec in catalog.items():
            master=organized if sku=='TIRZ-1M' else self.admin.get('master',sku)
            pid=spec['product_id'];oid=spec['offer_id'];aid=assignment_id(BRAND,422,sku);slot_id='master-'+aid+'-upfront'
            slot={'id':slot_id,'brand_id':BRAND,'campaign_id':422,'sku':sku,'name':spec['name'],'price':spec['total'],
                'billing_models':[spec['model']],'configuration':spec['configuration'],'product_id':pid,'offer_id':oid}
            product=cache.detail('/api/v2/products/'+str(pid))
            template={k:v for k,v in product.items() if k in ('sku','name','category_id','description','cost_of_goods','restocking_fee','max_quantity','is_shippable','taxable','is_taxable','archived_flag')}
            active=dict(master,payment_test_only=True,product_id=None,product_template=template,offers=[{'id':'upfront','name':spec['name'],'price':spec['total'],
                'billing_models':[spec['model']],**({'prepaid_cycles':spec['cycles'],'prepaid_renewal':spec['renewal']} if spec['cycles'] else {})}],
                billing_terms={str(spec['model']):billing_terms(models[spec['model']])})
            active.pop('planning_contract',None);active.pop('product_setup',None)
            activation={'sku':sku,'master_hash':fingerprint(master),'master':active,'campaign_id':422,'payment_test_only':True,
                'product_id':pid,'offer_id':oid,'configuration':spec['configuration'],'verified_quote':spec['total'],'run_id':RUN}
            assignment={'id':aid,'brand_id':BRAND,'campaign_id':422,'sku':sku,'master_revision':master['revision'],'currency':'USD','name':spec['name'],
                'offers':[slot|{'master_offer_id':'upfront'}],'link_id':'master-'+aid,'source_hash':fingerprint(template),'source_contract':product_contract(product),
                'billing_terms':active['billing_terms']}
            records.extend([('offering',slot_id,slot),('assignment',aid,assignment),('test_catalog_activation',sku,activation)])
        for skeleton in all_skeletons():
            tid=skeleton['id'].removesuffix('-v1')
            template={'id':tid,'name':skeleton['name'],'title':'Choose your '+skeleton['therapy']['name'].lower()+' plan',
                'therapy_id':skeleton['therapy']['id'],'purchase_option_ids':[skeleton['therapy']['id']+'-'+str(m)+'m' for m in (1,3,6,12)],'enabled':True,'revision':1}
            records.append(('checkout_template',tid,template))
            if skeleton['therapy']['id']=='weight-loss':
                plan=self.admin.get('purchase_option','weight-loss-1m')
                if 'TIRZ-1M' not in plan['skus']:records.append(('purchase_option',plan['id'],dict(plan,skus=plan['skus']+['TIRZ-1M'],revision=plan.get('revision',1)+1)))
        site={'id':BRAND,'name':'Master Therapy Payment Test','brand_id':BRAND,'campaign_id':422,'routing_template_id':422,'revision':1}
        records.append(('site',BRAND,site))
        # Build complete site checkouts against a request-local record view, then
        # commit the new managed catalog and all four parent/child sets together.
        view=copy.copy(self.admin);pending={(k,i):v for k,i,v in records};get=self.admin.get
        view.get=lambda k,i:pending.get((k,i),get(k,i))
        view.records=lambda k:list({v.get('id',v.get('sku')):v for v in self.admin.records(k)}.values()) if not any(a==k for a,_ in pending) else list({**{v.get('id',v.get('sku')):v for v in self.admin.records(k)},**{i:v for (a,i),v in pending.items() if a==k}}.values())
        view.api=cache
        plans=[]
        for skeleton in all_skeletons():
            template=view.get('checkout_template',skeleton['id'].removesuffix('-v1'))
            source=view.template_source(template);plan,*_=view.site_plan(site,source)
            plan['payment_test_only']=True
            for child in plan['_children']:child['payment_test_only']=True
            plans.append(plan)
        with self.admin.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.admin.local_fingerprint()!=local_before:raise ValueError('Owner configuration changed during setup; review again')
            for kind,identifier,data in records:
                existing=self.admin.get(kind,identifier)
                if existing and kind not in ('master','purchase_option','test_catalog_activation'):
                    if existing!=data:raise ValueError('Existing owner configuration conflicts: '+kind+' '+identifier)
                db.execute('INSERT INTO admin_config VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',(kind,identifier,json.dumps(data)))
            for plan in plans:
                children=plan.pop('_children')
                for kind,data in [('plan_checkout',plan)]+[('link',child) for child in children]:
                    if self.admin.get(kind,data['id']):raise ValueError('Do not overwrite an existing checkout during first activation')
                    db.execute('INSERT INTO admin_config VALUES(?,?,?)',(kind,data['id'],json.dumps(data)))
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)',(RUN,time.time(),json.dumps({'authorization':'Owner explicitly requested 40 master SKUs and four therapy checkouts on connected live campaign 422','new_real_payments':0,'existing_offers_preserved':True,'quote_checks':verified})))
        self.state['published']={'campaign_id':422,'site_id':BRAND,'brand_id':BRAND,'checkouts':[p['id'] for p in plans],'quote_checks':verified,'real_payments':0};self.save()
        return self.state['published']

    def report(self):
        return {k:self.state.get(k) for k in ('renewal_proof','published')}

