"""Owner-requested additive FortifyHP NAD+ annual subscription setup.

No order or payment APIs. Private journal prevents repeating uncertain writes.
Existing site records, campaign routing, offers, patients and prices are retained.
"""
import copy
import json
import os
import fcntl
from pathlib import Path
from decimal import Decimal

from fortifyhp_setup import FortifySetup, routing_fingerprint
from fortifyhp_provisioning import fingerprint
from master import clone_product, product_contract, product_contract_matches, assignment_id, campaign_master_id, billing_terms
from prepaid import configuration, cycles_for, renewal_for
from external_fulfillment import fortifyhp_prepaid_supported
from catalog import resolve, quote
from plans import choice_id
from sites import checkout_id
from demo.registry import SitePublication, load_publications
from demo.publish import site_publication
from refill_rules import site_rule_key

SKU = 'NAD-INJ-12M-SUB'
SOURCE_ID = 33363
SOURCE_SKU = 'NADINJ-12M'  # Verified legacy campaign source alias, not a new master code.
RUN = 'fortifyhp-nad-annual-subscription-20261026-v1'
TEMPLATE = 'fortifyhp-nad-plus-annual-test'
PURCHASE = TEMPLATE + '-12m'
PUBLIC_PLAN = 'site-api-fortifyhp-nad-plus'


def local_records(admin, source_body, source_contract, model, pid, oid):
    """Prepare one exact purchase, preserving all unrelated tenant configuration."""
    master = copy.deepcopy(admin.get('master', SKU))
    site = admin.get('site', 'fortifyhp')
    if not master or not site or site.get('campaign_id') != 195 or site.get('brand_id') != 'fortifyhp':
        raise ValueError('Verified FortifyHP site and approved master are required')
    setup = master['product_setup']
    if setup['shipment_days'] != [0,90,180,270] or setup['renewal_days'] != 360 or setup['upfront_price'] != '1668.00':
        raise ValueError('Approved master changed; review before setup')
    selection = f'{oid}:{pid}:4'
    aid = assignment_id('fortifyhp', 195, SKU)
    master.update(product_id=None, fulfillment_product_id=SOURCE_ID, product_template=dict(source_body, price=0),
        offers=[{'id':'upfront','name':'12 months upfront','price':'1668.00','billing_models':[4],'prepaid_cycles':4,'prepaid_renewal':True}],
        billing_terms={'4':billing_terms(model)}, revision=1)
    master.pop('planning_contract', None)
    master['product_setup'].update(processor_verified=True, processor_configuration=configuration(4,True))
    slot = {'id':'master-'+aid+'-upfront','brand_id':'fortifyhp','campaign_id':195,'sku':SKU,
        'name':'12 months upfront','price':'1668.00','billing_models':[4],'configuration':configuration(4,True),'product_id':pid,'offer_id':oid}
    assignment = {'id':aid,'brand_id':'fortifyhp','campaign_id':195,'sku':SKU,'master_revision':1,'currency':'USD',
        'name':master['name'],'offers':[dict(slot,master_offer_id='upfront')],'link_id':'master-'+aid,
        'source_hash':fingerprint(master['product_template']),'source_contract':source_contract,'billing_terms':master['billing_terms']}
    overlay_id=campaign_master_id('fortifyhp',195,SKU)
    records={('campaign_master',overlay_id):{'id':overlay_id,'brand_id':'fortifyhp','campaign_id':195,'sku':SKU,'master':master},
        ('offering',slot['id']):slot,('assignment',aid):assignment}
    purchase={'id':PURCHASE,'name':'12-month plan','therapy_id':'nad-plus','duration_months':12,'skus':[SKU],
        'payment_types':['prepaid'],'enabled':True,'revision':1}
    template={'id':TEMPLATE,'name':'NAD+ Injectable','title':'Your 12-month NAD+ plan','therapy_id':'nad-plus',
        'purchase_option_ids':[PURCHASE],'site_id':'fortifyhp','enabled':True,'revision':1}
    records['purchase_option',PURCHASE]=purchase;records['checkout_template',TEMPLATE]=template
    view=copy.copy(admin);view.get=lambda k,i:records.get((k,i),admin.get(k,i))
    snapshot=view.template_source(template,site)
    source_id=checkout_id('fortifyhp',TEMPLATE)
    source={'id':source_id,'brand_id':'fortifyhp','campaign_id':195,'therapy_id':'nad-plus','title':template['title'],
        'visibility':'private','enabled':True,'revision':1,'purchase_option_ids':[PURCHASE],'purchase_options':[purchase],
        'entries':[{'purchase_option_id':PURCHASE,'sku':SKU,'options':[selection]}],
        'site_id':'fortifyhp','template_id':TEMPLATE,'template_snapshot':snapshot,'template_source_hash':fingerprint(snapshot),
        'site_override':None,'payment_test_only':False}
    records['plan_checkout',source_id]=source
    for link_id, plan_id in [('master-'+aid,None),(choice_id(source_id,SKU,PURCHASE),source_id)]:
        link={'id':link_id,'brand_id':'fortifyhp','campaign_id':195,'sku':SKU,'title':master['name'],
            'visibility':'private','enabled':True,'options':[selection],'revision':1,'payment_test_only':False}
        if plan_id:link.update(plan_checkout_id=plan_id,purchase_option_id=PURCHASE)
        records['link',link_id]=link
    rule=copy.deepcopy(admin.get('refill_policy',SKU))
    if not rule or rule['check_in_required'] or rule['claim_window_days']!=20 or not rule['included_refills_enabled']:
        raise ValueError('Approved no-check-in refill policy is missing or changed')
    rule.update(site_id='fortifyhp',revision=1)
    records['site_refill_policy',site_rule_key('fortifyhp',SKU)]=rule
    therapy={'therapy_id':'nad-plus','name':'NAD+','source_plan_id':source_id,'published_plan_id':PUBLIC_PLAN,
        'plans':[{'sku':SKU,'selection':selection,'purchase_option_id':PURCHASE}]}
    return records,therapy


class NadSetup(FortifySetup):
    def __init__(self,application):
        super().__init__(application)
        self.path=self.admin.cfg.state_dir/(RUN+'.json')
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'run_id':RUN,'operations':{}}

    def prepare(self):
        campaign=self.campaign()
        if SOURCE_ID not in {int(p['id']) for o in campaign.get('offers',[]) for p in o.get('products',[])}:
            raise ValueError('NAD source is no longer attached to FortifyHP')
        source=self.api.detail(f'/api/v2/products/{SOURCE_ID}')
        if source.get('sku')!=SOURCE_SKU or source.get('is_shippable')!=1 or source.get('taxable')!=0:
            raise ValueError('NAD source identity/shipping/tax changed')
        model=self.api.detail('/api/v2/billing_models/4')
        if model.get('days')!=90 or (model.get('type') or {}).get('id')!=1:
            raise ValueError('Quarterly billing model changed')
        body=clone_product(dict(source,sku=SKU),'FortifyHP / NAD+ Injectable / 12 months / Subscription',SKU,Decimal('417.00'))
        if not fortifyhp_prepaid_supported(campaign,body,dict(configuration(4,True),billing_models=[model])):
            raise ValueError('NAD annual fulfillment scope is not enabled in this release')
        contract=product_contract(dict(source,sku=SKU))
        review={'body':body,'contract':contract,'model':model,'source_hash':fingerprint(source),
            'routing_hash':routing_fingerprint(campaign),'original_offers':[int(o['id']) for o in campaign['offers']]}
        if self.state.get('review'):
            review['original_offers']=self.state['review']['original_offers']
            if review!=self.state['review']:raise ValueError('Prepared provider data changed; reconcile before continuing')
        else:
            if self.admin.get('plan_checkout',PUBLIC_PLAN):raise ValueError('An existing NAD publication needs reconciliation')
            self.state['review']=review;self.save()
        return {'sku':SKU,'source_product_id':SOURCE_ID,'upfront_total':'1668.00','renewal_days':360,
            'deliveries':4,'delivery_interval_days':90,'included_refills':3,'claim_window_days':20,'check_in_required':False}

    def apply(self):
        self.prepare();r=self.state['review']
        pid=self.write('product:'+SKU,'POST','/api/v2/products',r['body'])
        p=self.api.detail(f'/api/v2/products/{pid}')
        if Decimal(str(p['price']))!=Decimal('417.00') or not product_contract_matches(r['contract'],product_contract(p)):
            raise ValueError('New product readback mismatch')
        body={'type_id':1,'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2},**configuration(4,True),
            'name':'FortifyHP / NAD+ / annual subscription','is_trial':0,'products':[{'id':pid}],'billing_models':[{'id':4}]}
        oid=self.write('offer:'+SKU,'POST','/api/v2/offers',body)
        offer=self.api.detail(f'/api/v2/offers/{oid}')
        if ({int(p['id']) for p in offer['products']}!={pid} or cycles_for(offer)!=4 or not renewal_for(offer)
            or {int(m['id']) for m in offer.get('offer_billing_models',offer.get('billing_models',[]))}!={4}):
            raise ValueError('New offer readback mismatch')
        campaign=self.campaign();current=[int(o['id']) for o in campaign['offers']];target=r['original_offers']+[oid]
        if routing_fingerprint(campaign)!=r['routing_hash'] or current not in (r['original_offers'],target):
            raise ValueError('Campaign changed; preserve its current configuration')
        self.write('attach:195','PUT','/api/v2/campaigns/195',{'offers':target})
        campaign=self.campaign()
        if [int(o['id']) for o in campaign['offers']]!=target or routing_fingerprint(campaign)!=r['routing_hash']:
            raise ValueError('Campaign attachment readback mismatch')
        selection=f'{oid}:{pid}:4'
        catalog=resolve(self.api,195,SKU,allowed_keys=[selection])
        total=quote(self.api,catalog,selection,2,{'country':'US','region':'CA','postal_code':'94105'})
        if total['currency']!='usd' or Decimal(total['total'])!=Decimal('1668.00'):
            raise ValueError('Authoritative full-term quote mismatch')
        records,therapy=local_records(self.admin,r['body'],r['contract'],r['model'],pid,oid)
        manifest_path=self.admin.cfg.state_dir/'site-api-publications.json'
        with manifest_path.with_suffix('.json.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            manifest=json.loads(manifest_path.read_text());sites=load_publications(manifest)
            existing=sites['fortifyhp'];value=existing.model_dump(mode='json')
            matches=[t for t in value['therapies'] if t['therapy_id']=='nad-plus']
            if matches and matches!=[therapy]:raise ValueError('Existing NAD manifest differs')
            one=dict(value,therapies=[therapy]);view=copy.copy(self.admin)
            view.get=lambda k,i:records.get((k,i),self.admin.get(k,i))
            for k,record in site_publication(view,one):records[k,record['id']]=record
            with self.admin.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for (k,i),v in records.items():
                    old=db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?',(k,i)).fetchone()
                    if old and json.loads(old[0])!=v:raise ValueError('Existing configuration preserved: '+k+'/'+i)
                for (k,i),v in records.items():db.execute('INSERT OR IGNORE INTO admin_config VALUES(?,?,?)',(k,i,json.dumps(v)))
            if not matches:
                value['therapies'].append(therapy);sites['fortifyhp']=SitePublication.model_validate(value)
                updated={'version':1,'sites':[s.model_dump(mode='json') for s in sites.values()]}
                temp=manifest_path.with_suffix('.nad.tmp');temp.write_text(json.dumps(updated,sort_keys=True,indent=2));temp.chmod(0o600)
                owner=manifest_path.stat();os.chown(temp,owner.st_uid,owner.st_gid);temp.replace(manifest_path)
        self.state['published']={'product_id':pid,'offer_id':oid,'selection':selection,'records':len(records),
            'plan_id':PUBLIC_PLAN,'sku':SKU,'upfront_total':'1668.00','orders_created':0,'payments_submitted':0}
        self.save();return self.state['published']

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','apply']);args=parser.parse_args()
    from app import app
    print(json.dumps(getattr(NadSetup(app),args.action)()))
