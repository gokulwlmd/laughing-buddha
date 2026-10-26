import copy,json,unittest
from types import SimpleNamespace
from decimal import Decimal
from pydantic import ValidationError
from fortifyhp_rollout import rows_for
from external_fulfillment import rollout_products
from master import planned_product_setup,assignment_id
from demo.registry import SitePublication,ApprovedPlan
from demo.public import map_site_catalog
from member_portal.intake_templates import get_template
MODELS={n:{'id':n,'days':d,'type':{'id':1}} for n,d in [(2,0),(3,30),(4,90),(5,180),(6,360)]}
def fixture():
 data={}
 for p in rollout_products().values():
  for suffix in ('','-SUB'):
   sku=p['sku']+suffix;c=dict(charge='full_term_upfront',term_months=p['duration_months'],renewal_months=p['duration_months'] if suffix else None,shipments_per_term=p['shipment_count'],shipment_interval=p['shipment_interval_days'] if p['shipment_count']>1 else None,later_shipment_charge='0.00')
   m=dict(sku=sku,name=p['medication'],enabled=True,therapy_id=p['therapy_id'],treatment_id=p['treatment_id'],currency='USD',revision=1,product_duration_months=p['duration_months'],planning_contract=c,offers=[dict(id='upfront',price=p['price'])]);m['product_setup']=planned_product_setup(m);data['master',sku]=m
 return SimpleNamespace(get=lambda k,i:data.get((k,i))),data
class RolloutTests(unittest.TestCase):
 def test_all_pairs_and_intakes(self):
  a,data=fixture();rows=rows_for(a,MODELS);self.assertEqual(len(rows),542)
  for r in rows:
   self.assertEqual(Decimal(r['unit'])*r['count'],Decimal(r['total']));self.assertEqual(r['count']*r['interval'],r['metadata']['duration_months']*30)
   self.assertTrue(get_template(r['metadata']['therapy_id'],sku=r['sku'])['questions'])
  self.assertEqual([r['sku'] for r in rows if r['sku'].startswith('ASTV')],['ASTV-5P-1M','ASTV-5P-1M-SUB'])
  self.assertFalse(any('MIN-1MG-FINA' in r['sku'] for r in rows))
 def test_master_changes_block(self):
  for field,value in [('shipments_per_term',3),('renewal_months',3),('shipment_interval',30)]:
   a,data=fixture();data['master','NAD-INJ-12M']['planning_contract'][field]=value
   with self.assertRaises(ValueError):rows_for(a,MODELS)
 def test_existing_price_preserved(self):
  a,data=fixture();data['assignment',assignment_id('fortifyhp',195,'NAD-INJ-12M-SUB')]={'offers':[dict(price='2000.00',product_id=555,offer_id=666,billing_models=[4])]}
  r=next(r for r in rows_for(a,MODELS) if r['sku']=='NAD-INJ-12M-SUB');self.assertTrue(r['existing']);self.assertEqual(r['total'],'2000.00');self.assertEqual(r['product_id'],555)
 def test_monthly_api_schedule_and_identity(self):
  site=SitePublication.model_validate(dict(site_id='fortifyhp',site_name='FortifyHP',brand_id='fortifyhp',campaign_id=195,portal_site_id='fortifyhp',color='#A2563F',therapies=[dict(therapy_id='hrt',name='HRT',source_plan_id='source',published_plan_id='public',plans=[dict(sku='DIVIGEL-0.1%-12M-SUB',selection='1:2:3',purchase_option_id='term')])]))
  e=dict(sku='DIVIGEL-0.1%-12M-SUB',purchaseOptionId='term',available=True,durationMonths=12,currency='USD',treatmentId='divigel-0-1',options=[dict(key='1:2:3',recurring=True,renewal=True,renewalDays=360,days=30,prepaidCycles=12,upfrontPrice='708.00')],productSetup=dict(shipment_count=12,shipment_interval_days=30,shipment_days=list(range(0,360,30))),storefrontIdentity=dict(sku='DIVIGEL-0.1%-12M-SUB',family_id='divigel',treatment_id='divigel-0-1',medication='Divigel 0.1%',format='Gel'))
  catalog=dict(id='public',paymentTestOnly=False,treatments=[dict(id='divigel-0-1',name='Divigel')],entries=[e]);result,_=map_site_catalog(site,lambda _:catalog)
  self.assertEqual(result.plans[0].shipment_days,list(range(0,360,30)));self.assertEqual(result.plans[0].renewal_days,360)
  for field,value in [('days',90),('renewalDays',30),('prepaidCycles',4)]:
   saved=copy.deepcopy(e['options']);e['options'][0][field]=value
   with self.assertRaises(ValueError):map_site_catalog(site,lambda _:catalog)
   e['options']=saved
  e['storefrontIdentity']['sku']='another'
  with self.assertRaises(ValueError):map_site_catalog(site,lambda _:catalog)
 def test_sku_punctuation_without_paths(self):
  ApprovedPlan(sku='TADA-2.5MG-30-30-1B-SUB',selection='1:2:3')
  for sku in ('../private','foo/bar','a?token=x'):
   with self.assertRaises(ValidationError):ApprovedPlan(sku=sku,selection='1:2:3')

class SnapshotTests(unittest.TestCase):
 def test_changes_invalidate_saved_catalog(self):
  import sqlite3,tempfile
  from publication_snapshot import digest,read_snapshot
  with tempfile.TemporaryDirectory() as d:
   path=d+'/db';store=SimpleNamespace(db=lambda:sqlite3.connect(path))
   with store.db() as db:db.execute('CREATE TABLE admin_config(kind TEXT,id TEXT,data TEXT,PRIMARY KEY(kind,id))')
   plan=dict(id='public',brand_id='fortifyhp',campaign_id=195,therapy_id='hrt',entries=[dict(sku='SKU',purchase_option_id='term')])
   def get(k,i):
    with store.db() as db:row=db.execute('SELECT data FROM admin_config WHERE kind=? AND id=?',(k,i)).fetchone()
    return json.loads(row[0]) if row else None
   a=SimpleNamespace(store=store,get=get)
   with store.db() as db:db.execute('INSERT INTO admin_config VALUES(?,?,?)',('plan_checkout','public',json.dumps(plan)))
   snapshot=dict(source_hash=digest(a,plan),catalog={'id':'public','entries':[]})
   with store.db() as db:db.execute('INSERT INTO admin_config VALUES(?,?,?)',('public_catalog_snapshot','public',json.dumps(snapshot)))
   self.assertEqual(read_snapshot(a,plan)['id'],'public')
   with store.db() as db:db.execute('INSERT INTO admin_config VALUES(?,?,?)',('master','SKU',json.dumps({'price':'changed'})))
   self.assertIsNone(read_snapshot(a,plan))
 def test_monthly_prepaid_scope_retains_site_gateway_and_interval(self):
  from test_external_fulfillment import FortifyCatalog
  from external_fulfillment import fortifyhp_prepaid_supported
  from prepaid import configuration
  f=FortifyCatalog();f.product['sku']='DIVIGEL-0.1%-12M-SUB'
  offer=dict(configuration(12,True),billing_models=[dict(id=3,days=30,type={'id':1})])
  self.assertTrue(fortifyhp_prepaid_supported(f.campaign,f.product,offer))
  offer['billing_models'][0]['days']=90
  self.assertFalse(fortifyhp_prepaid_supported(f.campaign,f.product,offer))

class ExpandedAdminCatalogTests(unittest.TestCase):
 def test_full_hrt_and_ed_sets_remain_editable(self):
  from plans import PurchaseOption,PlanCheckout
  from collections import Counter
  grouped={}
  for p in rollout_products().values():
   for suffix in ('','-SUB'):grouped.setdefault((p['therapy_id'],p['duration_months']),[]).append(p['sku']+suffix)
  entries=[]
  for (therapy,months),skus in grouped.items():
   PurchaseOption(id=therapy+'-'+str(months),name='Plan',therapy_id=therapy,duration_months=months,skus=skus,payment_types=['once','subscription','prepaid'])
   entries.extend(dict(sku=sku,options=['1:2:3']) for sku in skus)
  PlanCheckout(id='catalog',brand_id='fortifyhp',campaign_id=195,therapy_id='hrt',title='Plan',visibility='public',entries=entries)
  with self.assertRaises(ValidationError):PlanCheckout(id='catalog',brand_id='fortifyhp',campaign_id=195,therapy_id='hrt',title='Plan',visibility='public',entries=[dict(sku='SKU'+str(i),options=['1:2:3']) for i in range(1001)])

class ProvisioningTests(unittest.TestCase):
 def test_all_billing_groups_and_resume_without_duplicate_writes(self):
  import tempfile
  from pathlib import Path
  from fortifyhp_rollout import Rollout
  from fortifyhp_setup import routing_fingerprint
  from test_fortifyhp_setup import FortifySticky
  class Provider(FortifySticky):
   def detail(self,path):
    d=super().detail(path)
    if '/products/' in path:d=dict(d,weight=0,weight_unit_id=1)
    return d
  with tempfile.TemporaryDirectory() as d:
   provider=Provider();r=Rollout.__new__(Rollout);r.api=provider;r.path=Path(d)/'journal.json'
   a,_=fixture();rows=rows_for(a,MODELS);c=r.campaign()
   r.state=dict(operations={},review=dict(rows=rows,original_offers=[o['id'] for o in c['offers']],routing_hash=routing_fingerprint(c)))
   r.prepare=lambda:None
   result=r.provision();self.assertEqual(result['products'],542);self.assertEqual(result['offers'],len({v['group'] for v in rows}));self.assertEqual(result['orders_created'],0)
   self.assertTrue(r.state['attached']);self.assertTrue(all(v['status']=='confirmed' for v in r.state['operations'].values()))
   count=len(provider.calls);r.provision();self.assertEqual(len(provider.calls),count)
   self.assertTrue(all(path in ('/api/v2/products','/api/v2/offers','/api/v2/campaigns/195') for method,path,body in provider.calls))

class PublicCompatibilityTests(unittest.TestCase):
 def test_legacy_nullable_renewal_is_preserved_without_new_identity(self):
  from demo.public import PublishedPlan
  p=PublishedPlan(plan_id='sema-1m',name='Plan',medication='Semaglutide',duration_months=1,purchase_type='once',price='249.00',renewal_days=None,shipment_days=[0],terms='Once',therapy_id='weight-loss',therapy_name='Weight Loss')
  value=p.model_dump(mode='json')
  self.assertIn('renewal_days',value);self.assertIsNone(value['renewal_days'])
  self.assertFalse(set(('sku','family_id','treatment_id','format'))&value.keys())
