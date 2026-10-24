"""Persistent, network-free catalog for local development and Fly staging.

This adapter has no HTTP client and rejects every payment operation.
"""
import copy
import json
from decimal import Decimal
from pathlib import Path


class SyntheticSticky:
    def __init__(self, state_dir):
        self.path = Path(state_dir) / 'synthetic-catalog.json'
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {'products':{},'offers':{},'campaigns':{}}
        self.data.setdefault('coupons',{})
        self.models = [{'id':mid,'name':name,'days':days,'type':{'id':1},'is_archived':0}
            for mid,days,name in [(2,0,'One-time'),(3,30,'Every 30 days'),(4,90,'Every 90 days'),(5,180,'Every 180 days'),(6,360,'Every 360 days')]]

    def save(self):
        draft = self.path.with_suffix('.tmp')
        draft.write_text(json.dumps(self.data));draft.chmod(0o600);draft.replace(self.path)

    def detail(self, path):
        identifier = path.rsplit('/',1)[1]
        if '/coupons/' in path and identifier in self.data['coupons']:
            return copy.deepcopy(self.data['coupons'][identifier])
        if '/providers/payment/profiles/' in path:
            return {'id':1,'account_id':250,'currency':{'code':'USD'},'fields':{'account_fields':{'publishable_key':'pk_test_synthetic_only','capture_on_shipment':False}}}
        if '/products/' in path:
            if identifier in self.data['products']:
                return copy.deepcopy(self.data['products'][identifier])
            if identifier == '2856':
                return {'id':2856,'name':'Synthetic source product','sku':'DEMO-SOURCE','price':'10.00','category_id':1,
                    'cost_of_goods':'0','restocking_fee':'0','max_quantity':1,'is_shippable':0,'taxable':0,'is_taxable':0,'archived_flag':0,'is_variant_enabled':0}
        if '/offers/' in path and identifier in self.data['offers']:
            offer = copy.deepcopy(self.data['offers'][identifier])
            offer['billing_models'] = [copy.deepcopy(next(m for m in self.models if m['id']==entry['id'])) for entry in offer['billing_models']]
            return offer
        if '/campaigns/' in path:
            raw = self.data['campaigns'].get(identifier)
            if raw is None and identifier != '422':
                raise ValueError('Synthetic campaign does not exist')
            raw = raw or {'id':422,'name':'Synthetic routing template','offers':[]}
            return {'id':int(identifier),'name':raw['name'],'is_active':1,'is_archived':0,'gateway_id':1,'tax_provider_id':0,
                'channel':{'id':1},'payment_methods':[{'value':'visa'},{'value':'stripe_link'}],
                'alternative_payments':[{'payment_method':'stripe_link','provider':{'id':1,'account_id':250}}],
                'countries':[{'id':223,'iso_2':'US','name':'United States'}],'shipping_profiles':[{'id':2,'name':'No shipping'}],
                'coupon_profiles':[{'id':pid,'name':self.data['coupons'][str(pid)]['name']} for pid in raw.get('coupon_profiles',[])],
                'offers':[self.detail('/api/v2/offers/'+str(oid)) for oid in raw['offers']]}
        raise ValueError('Synthetic object does not exist')

    def call(self, method, path, body=None):
        if method=='POST' and path=='/api/v2/coupons':
            key=str(20000+len(self.data['coupons']))
            self.data['coupons'][key]={'id':int(key),'name':body['name'],'type_id':1,'is_active':1,
                'discount_percent':body['discount']['percent'],'is_lifetime':body['is_lifetime'],
                'is_free_shipping':body['is_free_shipping'],'limits':copy.deepcopy(body['limits']),
                'expires_at':{'date':body['expiration']['date']+' 00:00:00','timezone':body['expiration']['timezone']},
                'promo_codes':[dict(p,is_active=1,is_deleted=0) for p in body['promo_codes']]}
            self.save();return {'status':'SUCCESS','data':{'id':int(key)}}
        if method=='PUT' and '/coupon-profiles/' in path:
            cid,pid=path.split('/')[4],int(path.rsplit('/',1)[1])
            if str(pid) not in self.data['coupons']:raise ValueError('Synthetic coupon does not exist')
            campaign=self.data['campaigns'].setdefault(cid,{'id':int(cid),'name':'Synthetic routing template','offers':[]})
            campaign['coupon_profiles']=list(dict.fromkeys(campaign.get('coupon_profiles',[])+[pid]))
            self.save();return {'status':'SUCCESS'}
        if path in ('/api/v1/authorize_payment','/api/v1/new_order'):
            raise RuntimeError('Payment writes are disabled in synthetic staging')
        if method == 'GET' and path == '/api/v2/billing_models':
            return {'status':'SUCCESS','data':copy.deepcopy(self.models)}
        if method == 'GET':
            return {'status':'SUCCESS','data':self.detail(path)}
        if path == '/api/v1/campaign_find_active':
            return {'response_code':'100','campaigns':{str(c['id']):{'campaign_id':str(c['id']),'campaign_name':c['name']}
                for c in [self.detail('/api/v2/campaigns/422')]+list(self.data['campaigns'].values())}}
        if path == '/api/v2/order_total/calculate':
            line=body['offers'][0];product=self.detail('/api/v2/products/'+str(line['product_id']))
            total=str(Decimal(str(product['price']))*line.get('prepaid_cycles',1))
            return {'status':'SUCCESS','data':{'total':total,'line_items':[{'id':product['id'],'qty':1}]}}
        resource=path.rsplit('/',1)[1]
        if method == 'POST' and resource in ('products','offers','campaigns'):
            key=str(10000+len(self.data[resource]));record=copy.deepcopy(body)|{'id':int(key)}
            if resource=='products':record.update(archived_flag=0,taxable=body.get('is_taxable',0))
            self.data[resource][key]=record;self.save()
            return {'status':'SUCCESS','data':{'id':int(key)}}
        if method == 'PUT' and '/campaigns/' in path and set(body)=={'offers'}:
            campaign=self.data['campaigns'].setdefault(resource,{'id':int(resource),'name':'Synthetic routing template','offers':[]})
            campaign['offers']=copy.deepcopy(body['offers']);self.save()
            return {'status':'SUCCESS','data':{'id':int(resource)}}
        raise ValueError('Operation is unavailable in synthetic staging')


def seed_demo(admin):
    """Seed synthetic catalog once, without an owner, session, approval or customer."""
    if admin.get('synthetic_seed','v1'):
        return
    admin.put('therapy','demo-therapy',{'id':'demo-therapy','name':'Demo Therapy','enabled':True,
        'treatments':[{'id':'example-a','name':'Example treatment A'},{'id':'example-b','name':'Example treatment B'}]})
    skus=[]
    for months in (1,3,6,12):
        assigned=[]
        for treatment in ('a','b'):
            sku=f'DEMO-{treatment.upper()}-{months}M';assigned.append(sku);skus.append(sku)
            master={'sku':sku,'name':f'Example {treatment.upper()} · {months} months','therapy_id':'demo-therapy','treatment_id':'example-'+treatment,
                'product_duration_months':months,'currency':'USD','offers':[{'id':'standard','name':'Demo payment choices','price':str(months*10),'billing_models':[2,3]}]}
            data,*_=admin.prepare_master('master',master);admin.finalize_master('master',data,lambda x:x)
        pid=f'demo-{months}m'
        admin.put('purchase_option',pid,{'id':pid,'name':f'{months}-month plan','therapy_id':'demo-therapy','duration_months':months,
            'skus':assigned,'payment_types':['once','subscription'],'enabled':True,'revision':1})
    admin.put('checkout_template','demo-checkout',{'id':'demo-checkout','name':'Demo Therapy','title':'Choose an example plan','therapy_id':'demo-therapy',
        'purchase_option_ids':['demo-1m','demo-3m','demo-6m','demo-12m'],'enabled':True,'revision':1})
    admin.put('brand','demo-brand',{'id':'demo-brand','name':'Demo Brand','campaign_id':None,'campaign_ids':[],'color':'#245844',
        'logo_url':'','support_email':'support@example.invalid','support_phone':'','custom_domain':''})
    admin.put('synthetic_seed','v1',{'id':'v1'})
