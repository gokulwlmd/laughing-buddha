"""Add the owner's finalized storefront families to existing FortifyHP.

Catalog-only writes, journaled before submission. No order/payment mutations.
The external fulfillment system consumes the exact approved SKU. Newly defined
products use this site's existing physical/non-taxable/free-shipping defaults;
existing source objects, customer subscriptions and prices are never rewritten.
"""
import copy
import fcntl
import json
import os
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from fortifyhp_setup import FortifySetup, routing_fingerprint
from master import fingerprint, assignment_id, campaign_master_id, billing_terms, product_contract, product_contract_matches
from plans import ReadCache, choice_id
from prepaid import configuration, cycles_for, renewal_for
from catalog import resolve, quote
from demo.registry import SitePublication, load_publications
from demo.publish import site_publication
from demo.public import map_site_catalog
from refill_rules import site_rule_key
from external_fulfillment import rollout_products, fortifyhp_prepaid_supported

RUN='fortifyhp-finalized-storefront-20261026-v1'


def rows_for(admin, models):
    rows=[]
    for base,p in rollout_products().items():
        for suffix in ('','-SUB'):
            sku=base+suffix;m=copy.deepcopy(admin.get('master',sku));count=p['shipment_count'];interval=p['shipment_interval_days']
            if not m or not m.get('enabled') or m['therapy_id']!=p['therapy_id'] or m['treatment_id']!=p['treatment_id']:
                raise ValueError('Approved master missing or changed: '+sku)
            c=m.get('planning_contract') or {}
            if (c.get('shipments_per_term')!=count or c.get('term_months')!=p['duration_months']
                or c.get('renewal_months')!=(p['duration_months'] if suffix else None)
                or (count>1 and c.get('shipment_interval')!=interval) or count*interval!=p['duration_months']*30):
                raise ValueError('Approved shipment/renewal contract changed: '+sku)
            recurring=bool(suffix);mid={30:3,90:4,180:5,360:6}[interval] if count>1 or recurring else 2
            model=models[mid]
            if (mid!=2 and (model.get('days')!=interval or (model.get('type') or {}).get('id')!=1)):
                raise ValueError('Billing model changed')
            aid=assignment_id('fortifyhp',195,sku);existing=admin.get('assignment',aid)
            if existing:
                offers=existing.get('offers') or []
                if len(offers)!=1:raise ValueError('Existing assignment needs review: '+sku)
                total=Decimal(offers[0]['price']);pid=offers[0]['product_id'];oid=offers[0]['offer_id']
                if offers[0]['billing_models']!=[mid]:raise ValueError('Existing billing model changed')
            else:total=Decimal(m['offers'][0]['price']);pid=oid=None
            unit=total/count
            if not total.is_finite() or total<=0 or unit!=unit.quantize(Decimal('.01')):
                raise ValueError('Price must allocate to exact cents: '+sku)
            config=configuration(count,recurring) if count>1 else {}
            name=f"FortifyHP / {p['medication']} / {p['duration_months']}m / "+('Subscription' if recurring else 'One-time')
            # Independent, exact-SKU product. No source cost, dose change, or guessed pharmacy mapping.
            body=dict(name=name[:150],sku=sku,category_id=1,description=name,price=float(unit),cost_of_goods=0,
                      restocking_fee=0,max_quantity=1,is_shippable=1,is_taxable=0,auto_create_variants=0,attributes=[])
            rows.append(dict(sku=sku,master=m,metadata=p,model=mid,billing_terms=billing_terms(model),
                group=f'm{mid}-c{count}-r{int(recurring)}',count=count,interval=interval,recurring=recurring,
                total=format(total,'.2f'),unit=format(unit,'.2f'),configuration=config,body=body,
                existing=bool(existing),product_id=pid,offer_id=oid))
    return rows


class Rollout(FortifySetup):
    def __init__(self, application):
        super().__init__(application)
        self.path=self.admin.cfg.state_dir/(RUN+'.json')
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'run_id':RUN,'operations':{}}

    def prepare(self):
        campaign=self.campaign()
        models={int(m['id']):m for m in self.api.call('GET','/api/v2/billing_models')['data']}
        rows=rows_for(self.admin,models)
        for r in rows:
            if r['count']>1 and not fortifyhp_prepaid_supported(campaign,r['body'],dict(r['configuration'],billing_models=[models[r['model']]])):
                raise ValueError('Physical delivery scope unavailable: '+r['sku'])
        review=dict(rows=rows,routing_hash=routing_fingerprint(campaign),original_offers=[o['id'] for o in campaign['offers']],
                    original_manifest=json.load(open('/data/site-api-publications.json')))
        old=self.state.get('review')
        if old:
            review['original_offers']=old['original_offers'];review['original_manifest']=old['original_manifest']
            if review!=old:raise ValueError('Prepared configuration changed; reconcile before continuing')
        else:
            self.state['review']=review;self.save()
            backup=self.admin.cfg.state_dir/(RUN+'-before.sqlite3')
            with self.admin.store.db() as src,sqlite3.connect(backup) as target:src.backup(target)
            backup.chmod(0o600)
        return dict(plans=len(rows),new_products=sum(not r['existing'] for r in rows),families=len({r['metadata']['family_id'] for r in rows}),orders_created=0)

    def provision(self):
        self.prepare();review=self.state['review'];rows=review['rows']
        for r in rows:
            if r['existing']:continue
            pid=self.write('product:'+r['sku'],'POST','/api/v2/products',r['body'])
            key='verified_product:'+r['sku']
            if key not in self.state:
                product=self.api.detail(f'/api/v2/products/{pid}')
                expected=product_contract(dict(r['body'],weight=0,weight_unit_id=1))
                if (Decimal(str(product['price']))!=Decimal(r['unit']) or not product_contract_matches(expected,product_contract(product))):
                    raise ValueError('Product readback mismatch: '+r['sku'])
                self.state[key]=True;self.save()
        groups=defaultdict(list)
        for r in rows:
            if not r['existing']:groups[r['group']].append(r)
        for key,group in groups.items():
            first=group[0];pids=[self.state['operations']['product:'+r['sku']]['object_id'] for r in group]
            body={'type_id':1,'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2},**first['configuration']}
            body.update(name='FortifyHP / finalized catalog / '+key,is_trial=0,products=[{'id':pid} for pid in pids],billing_models=[{'id':first['model']}])
            oid=self.write('offer:'+key,'POST','/api/v2/offers',body)
            offer=self.api.detail(f'/api/v2/offers/{oid}')
            if ({p['id'] for p in offer['products']}!=set(pids)
                or {m['id'] for m in offer.get('offer_billing_models',offer.get('billing_models',[]))}!={first['model']}
                or cycles_for(offer)!=(first['count'] if first['count']>1 else None)
                or renewal_for(offer)!=(first['recurring'] if first['count']>1 else False)):
                raise ValueError('Offer readback mismatch: '+key)
        campaign=self.campaign();current=[o['id'] for o in campaign['offers']]
        target=review['original_offers']+[self.state['operations']['offer:'+key]['object_id'] for key in groups]
        if routing_fingerprint(campaign)!=review['routing_hash'] or current not in (review['original_offers'],target):
            raise ValueError('Campaign changed; preserve concurrent configuration')
        self.write('attach:195','PUT','/api/v2/campaigns/195',{'offers':target})
        c=self.campaign()
        if [o['id'] for o in c['offers']]!=target or routing_fingerprint(c)!=review['routing_hash']:
            raise ValueError('Campaign attachment readback mismatch')
        self.state['attached']=True;self.save()
        return dict(products=len(rows),offers=len(groups),orders_created=0)

    def mapped_rows(self):
        rows=copy.deepcopy(self.state['review']['rows'])
        for r in rows:
            if not r['existing']:
                r['product_id']=self.state['operations']['product:'+r['sku']]['object_id']
                r['offer_id']=self.state['operations']['offer:'+r['group']]['object_id']
            r['selection']=f"{r['offer_id']}:{r['product_id']}:{r['model']}"
        return rows

    def verify_quotes(self):
        if not self.state.get('attached'):raise ValueError('Provisioning must complete first')
        rows=self.mapped_rows();cache=ReadCache(self.api);cache.prefetch_choices(195,{r['selection'] for r in rows})
        def check(r):
            catalog=resolve(cache,195,r['sku'],allowed_keys=[r['selection']])
            q=quote(cache,catalog,r['selection'],2,{'country':'US','region':'CA','postal_code':'94105'})
            if q['currency']!='usd' or Decimal(q['total'])!=Decimal(r['total']):raise ValueError('Quote mismatch: '+r['sku'])
            return r['sku']
        with ThreadPoolExecutor(max_workers=4) as pool:verified=list(pool.map(check,rows))
        self.state['quotes_verified']=sorted(verified);self.save()
        return dict(verified=len(verified),orders_created=0)

    def records(self):
        rows=self.mapped_rows();pending={};therapies=[]
        for r in rows:
            sku=r['sku'];aid=assignment_id('fortifyhp',195,sku);p=r['metadata']
            identity={k:p[k] for k in ('family_id','treatment_id','medication','format')};identity['sku']=sku
            if r['existing']:
                old=self.admin.get('campaign_master',campaign_master_id('fortifyhp',195,sku));master=copy.deepcopy(old['master'])
            else:
                master=copy.deepcopy(r['master']);master.pop('planning_contract',None)
                mo=dict(id='upfront',name='Full-term upfront',price=r['total'],billing_models=[r['model']])
                if r['count']>1:mo.update(prepaid_cycles=r['count'],prepaid_renewal=r['recurring'])
                master.update(product_id=None,fulfillment_product_id=r['product_id'],product_template=dict(r['body'],price=0),offers=[mo],billing_terms={str(r['model']):r['billing_terms']})
                slot=dict(id='master-'+aid+'-upfront',brand_id='fortifyhp',campaign_id=195,sku=sku,name='Full-term upfront',price=r['total'],billing_models=[r['model']],configuration=r['configuration'],product_id=r['product_id'],offer_id=r['offer_id'])
                assign=dict(id=aid,brand_id='fortifyhp',campaign_id=195,sku=sku,master_revision=master['revision'],currency='USD',name=master['name'],offers=[dict(slot,master_offer_id='upfront')],link_id='master-'+aid,
                    source_hash=fingerprint(master['product_template']),source_contract=product_contract(dict(r['body'],weight=0,weight_unit_id=1)),billing_terms=master['billing_terms'])
                pending['offering',slot['id']]=slot;pending['assignment',aid]=assign
                pending['link','master-'+aid]=dict(id='master-'+aid,brand_id='fortifyhp',campaign_id=195,sku=sku,title=master['name'],visibility='private',enabled=True,options=[r['selection']],revision=1,payment_test_only=False)
            master['storefront_identity']=identity
            if not r['existing']:master['product_setup'].update(processor_verified=True,processor_configuration=r['configuration'],shipment_interval_days=r['interval'])
            overlay_id=campaign_master_id('fortifyhp',195,sku)
            pending['campaign_master',overlay_id]=dict(id=overlay_id,brand_id='fortifyhp',campaign_id=195,sku=sku,master=master)
            key=site_rule_key('fortifyhp',sku)
            if not self.admin.get('site_refill_policy',key):
                rule=copy.deepcopy(self.admin.get('refill_policy',sku))
                if not rule:
                    from catalog_refill_policies import proposed_policy
                    rule=proposed_policy(dict(p,shipments_per_term=r['count'],supply_days_per_shipment=r['interval']),sku)
                rule.update(site_id='fortifyhp');pending['site_refill_policy',key]=rule
        view=copy.copy(self.admin);view.get=lambda k,i:pending.get((k,i),self.admin.get(k,i))
        site=self.admin.get('site','fortifyhp')
        for tid in sorted({r['metadata']['therapy_id'] for r in rows}):
            selected=[r for r in rows if r['metadata']['therapy_id']==tid];template_id='fortifyhp-catalog-'+tid;options=[]
            for term in sorted({r['metadata']['duration_months'] for r in selected}):
                skus=[r['sku'] for r in selected if r['metadata']['duration_months']==term]
                purchase=dict(id=template_id+'-'+str(term)+'m',name=str(term)+'-month plan',therapy_id=tid,duration_months=term,skus=skus,payment_types=['once','subscription','prepaid'],enabled=True,revision=1)
                options.append(purchase);pending['purchase_option',purchase['id']]=purchase
            therapy=self.admin.get('therapy',tid)
            template=dict(id=template_id,name=therapy['name'],title='Choose your '+therapy['name']+' plan',therapy_id=tid,purchase_option_ids=[p['id'] for p in options],site_id='fortifyhp',enabled=True,revision=1)
            pending['checkout_template',template_id]=template
            source_id='fortifyhp-catalog-source-'+tid;public_id='site-api-fortifyhp-catalog-'+tid;entries=[];approved=[]
            for r in selected:
                purchase=next(p['id'] for p in options if r['sku'] in p['skus'])
                entries.append(dict(sku=r['sku'],purchase_option_id=purchase,options=[r['selection']]))
                approved.append(dict(sku=r['sku'],purchase_option_id=purchase,selection=r['selection']))
                cid=choice_id(source_id,r['sku'],purchase)
                pending['link',cid]=dict(id=cid,brand_id='fortifyhp',campaign_id=195,sku=r['sku'],title=r['master']['name'],visibility='private',enabled=True,options=[r['selection']],revision=1,payment_test_only=False,plan_checkout_id=source_id,purchase_option_id=purchase)
            snapshot=view.template_source(template,site)
            plan=dict(id=source_id,brand_id='fortifyhp',campaign_id=195,therapy_id=tid,title=template['title'],visibility='private',enabled=True,revision=1,purchase_option_ids=template['purchase_option_ids'],purchase_options=options,entries=entries,site_id='fortifyhp',template_id=template_id,template_snapshot=snapshot,template_source_hash=fingerprint(snapshot),site_override=None,payment_test_only=False)
            pending['plan_checkout',source_id]=plan
            therapies.append(dict(therapy_id=tid,name=therapy['name'],source_plan_id=source_id,published_plan_id=public_id,plans=approved))
        return pending,therapies

    def publish(self):
        rows=self.mapped_rows()
        if self.state.get('quotes_verified')!=sorted(r['sku'] for r in rows):raise ValueError('Every quote must pass first')
        pending,therapies=self.records();view=copy.copy(self.admin);view.get=lambda k,i:pending.get((k,i),self.admin.get(k,i))
        path=Path('/data/site-api-publications.json')
        with path.with_suffix('.json.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            original=self.state['review']['original_manifest'];sites=load_publications(original)
            config=sites['fortifyhp'].model_dump(mode='json');new_ids={t['therapy_id'] for t in therapies}
            config['therapies']=[t for t in config['therapies'] if t['therapy_id'] not in new_ids]+therapies
            catalogs={}
            original_options=view.plan_options
            def cached_options(plan,brand,therapy):
                key=plan['id']
                if key not in catalogs:catalogs[key]=original_options(plan,brand,therapy)
                return catalogs[key]
            view.plan_options=cached_options
            for kind,value in site_publication(view,dict(config,therapies=therapies)):pending[kind,value['id']]=value
            for t in therapies:catalogs[t['published_plan_id']]=dict(catalogs[t['source_plan_id']],id=t['published_plan_id'])
            # Validate the API's exact identity, delivery and renewal contract before exposing it.
            new_catalog,_=map_site_catalog(SitePublication.model_validate(dict(config,therapies=therapies)),lambda key:view.plan_options(*view.plan_record(key)))
            if len(new_catalog.plans)!=len(rows):raise ValueError('Publication is incomplete')
            sites['fortifyhp']=SitePublication.model_validate(config)
            replacement={'version':1,'sites':[v.model_dump(mode='json') for v in sites.values()]}
            current=json.loads(path.read_text())
            if current not in (original,replacement):raise ValueError('Concurrent site publication changed')
            with self.admin.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for (k,i),v in pending.items():
                    old=db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?',(k,i)).fetchone()
                    if old and json.loads(old[0])!=v:
                        before=json.loads(old[0]);after=copy.deepcopy(v)
                        if k=='campaign_master':after['master'].pop('storefront_identity',None)
                        if k!='campaign_master' or before!=after:raise ValueError('Existing record preserved: '+k+'/'+i)
                for (k,i),v in pending.items():db.execute('INSERT INTO admin_config VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',(k,i,json.dumps(v)))
            from publication_snapshot import digest
            with self.admin.store.db() as db:
                for t in therapies:
                    pid=t['published_plan_id'];plan=self.admin.get('plan_checkout',pid)
                    value=dict(id=pid,catalog=catalogs[pid],source_hash=digest(self.admin,plan))
                    db.execute('INSERT INTO admin_config VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',('public_catalog_snapshot',pid,json.dumps(value)))
            temp=path.with_suffix('.rollout.tmp');temp.write_text(json.dumps(replacement,indent=2));temp.chmod(0o600)
            owner=path.stat();os.chown(temp,owner.st_uid,owner.st_gid);temp.replace(path)
        self.state['published']=dict(plans=len(rows),families=len({r['metadata']['family_id'] for r in rows}),records=len(pending),orders_created=0);self.save()
        return self.state['published']


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','provision','verify_quotes','publish']);args=p.parse_args()
    from app import app
    with (Path('/data')/(RUN+'.lock')).open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(json.dumps(getattr(Rollout(app),args.action)()))
