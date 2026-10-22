"""User-authorized additive starter catalog import for local/synthetic staging only.

No owner/session, Sticky writes, payment operations or existing-price replacement.
Run explicitly: python -m import_master_therapies (with synthetic settings).
"""
import copy
import json
import time
from urllib.parse import urlparse
from therapy_skeletons import all_skeletons, skeleton_draft

RUN_ID = 'master-therapies-starter-v1'


def _import(application, skeletons, run_id, *, authorized_live=False):
    expected=sum(len(s['products']) for s in skeletons)
    admin = application.state.admin
    host = urlparse(admin.cfg.public_url).hostname
    live = authorized_live and not admin.cfg.synthetic and host == 'wlmd-stripe-test-0f89b1bb.fly.dev'
    if not live and (not admin.cfg.synthetic or host not in ('localhost', '127.0.0.1', 'wlmd-checkout-staging-0f89b1bb.fly.dev')):
        raise ValueError('Import is restricted to local development and isolated synthetic staging')
    with admin.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
        marker = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (run_id,)).fetchone()
        if marker:
            details = json.loads(marker[0])
            if not all(db.execute('SELECT 1 FROM admin_config WHERE kind=? AND id=?', key).fetchone() for key in details['created_records']):
                raise ValueError('An imported record is missing; reconcile without overwriting')
            return {'already_imported': True, 'master_skus': expected, 'created_records': 0}
        existing = {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}
        pending = {}
        view = copy.copy(admin)
        view.get = lambda kind, key: pending.get((kind,key), existing.get((kind,key)))
        view.records = lambda kind: [v for (k,i),v in {**existing, **pending}.items() if k == kind]
        def add(kind, key, value):
            if (kind,key) in existing or (kind,key) in pending:
                raise ValueError(f'Existing {kind} {key}; no records were overwritten')
            pending[(kind,key)] = value
        for skeleton in skeletons:
            therapy = skeleton['therapy']
            saved = existing.get(('therapy',therapy['id']))
            if saved:
                if not saved.get('enabled') or any(t not in saved['treatments'] for t in therapy['treatments']):
                    raise ValueError('Existing therapy differs: '+therapy['id'])
            else:
                add('therapy',therapy['id'],therapy|{'revision':1})
            for product in skeleton['products']:
                term = product['duration_months']
                contract = {k:product[k] for k in ('charge','renewal_months','shipments_per_term','shipment_interval','later_shipment_charge')}
                contract['term_months'] = term
                master = {'sku':product['sku'],'name':f"{product['treatment']} · {term} months · "+('Subscription' if product['renewal_months'] else 'One-time'),
                          'category':therapy['name'],'therapy_id':therapy['id'],'treatment_id':product['treatment_id'],
                          'product_duration_months':term,'currency':'USD','enabled':True,'planning_contract':contract,
                          'offers':[{'id':'upfront','name':'Full-term upfront price','price':product['price'],'billing_models':[]}]}
                data, guards, _, operations, _ = view.prepare_master('master',master)
                assert not guards and not operations
                add('master',product['sku'],data)
                add('sku',product['sku'],{k:data[k] for k in ('sku','name','product_id')})
            draft = skeleton_draft(skeleton, assigned=True)
            draft['new_therapy'] = None
            for plan in draft['plans']:
                if ('purchase_option',plan['id']) in existing:
                    raise ValueError('Existing purchase option '+plan['id']+'; no records were overwritten')
                data, *_ = view.prepare_plan('purchase_option',plan)
                add('purchase_option',plan['id'],data)
            # Keep any owner-created draft, including its name, choices and edits.
            if ('template_draft',draft['id']) not in existing:
                add('template_draft',draft['id'],draft)
        for (kind,key),value in pending.items():
            db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)',(kind,key,json.dumps(value)))
        details = {'authorization':'User requested these master therapy SKUs with editable starter pricing',
                   'created_records':[list(key) for key in pending], 'master_skus':expected,
                   'starter_monthly_usd':{'SEMA':'249.00','TIRZ':'449.00','SERM':'199.00','METFORM':'49.00','PT141':'199.00'},
                   'price_rule':'Full-term upfront = monthly starter rate × duration; no discount',
                   'sticky_writes':0,'payment_writes':0,'owner_session_created':False}
        db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)',(run_id,time.time(),json.dumps(details)))
        return {'already_imported':False,'master_skus':expected,'created_records':len(pending),'sticky_writes':0,'payment_writes':0}


def promote_live(application):
    """Explicit owner-authorized additive promotion; never replace existing live SKUs."""
    if application.state.admin.cfg.synthetic or urlparse(application.state.admin.cfg.public_url).hostname != 'wlmd-stripe-test-0f89b1bb.fly.dev':
        raise ValueError('Live promotion requires the existing live application')
    skeletons=all_skeletons()
    preserved=[]
    for skeleton in skeletons:
        products=[]
        for product in skeleton['products']:
            if application.state.admin.get('master',product['sku']) or application.state.admin.get('sku',product['sku']):
                preserved.append(product['sku'])
            else:products.append(product)
        skeleton['products']=products
    result=_import(application,skeletons,'owner-authorized-live-master-catalog-v1',authorized_live=True)
    return result|{'preserved_existing_skus':preserved,'catalog_activation':'Drafts only; existing offers and payment records unchanged'}


def run(application):
    # Keep the historical import scope stable when new recipes are added.
    return _import(application, all_skeletons()[:3], RUN_ID)


def add_pt141(application):
    return _import(application, [s for s in all_skeletons() if s['therapy']['id']=='pt-141'], 'master-therapy-4-starter-v1')


def upgrade_shipments(application):
    """Apply the explicit 6/12-month shipment defaults once; preserve later owner edits."""
    from master import MasterSKU
    admin=application.state.admin
    host=urlparse(admin.cfg.public_url).hostname
    if not admin.cfg.synthetic or host not in ('localhost','127.0.0.1','wlmd-checkout-staging-0f89b1bb.fly.dev'):
        raise ValueError('Shipment defaults are restricted to local development and synthetic staging')
    run_id='master-therapy-prepaid-shipments-v1'
    with admin.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
        if db.execute('SELECT 1 FROM admin_setup_runs WHERE id=?',(run_id,)).fetchone():
            return {'already_applied':True,'updated_masters':0,'updated_plans':0}
        updates=[]
        for skeleton in all_skeletons():
            for product in skeleton['products']:
                months=product['duration_months']
                if months not in (6,12):continue
                before=admin.get('master',product['sku'])
                if not before:raise ValueError('Import the requested master catalog before setting shipments: '+product['sku'])
                contract=before.get('planning_contract')
                if not contract or any(a['sku']==product['sku'] for a in admin.records('assignment')):
                    raise ValueError('Only unassigned catalog drafts can receive these defaults')
                desired=2 if months==6 else 4
                if contract['shipment_interval'] is not None:
                    # Already-configured schedules are owner settings; leave them alone.
                    continue
                if contract['shipments_per_term'] not in (None,desired):
                    raise ValueError('Custom shipment count needs review: '+product['sku'])
                request={k:v for k,v in before.items() if k in MasterSKU.model_fields}
                request['planning_contract']=dict(contract,shipments_per_term=desired,shipment_interval=90)
                data,guards,_,ops,_=admin.prepare_master('master',request)
                assert not guards and not ops
                updates.append(('master',product['sku'],data))
            for months in (6,12):
                key=f"{skeleton['therapy']['id']}-{months}m"
                plan=admin.get('purchase_option',key)
                if not plan:raise ValueError('Missing imported duration plan: '+key)
                if 'prepaid' not in plan['payment_types']:
                    updates.append(('purchase_option',key,dict(plan,payment_types=plan['payment_types']+['prepaid'],revision=plan.get('revision',0)+1)))
        for kind,key,data in updates:
            db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?',(json.dumps(data),kind,key))
        details={'authorization':'User requested editable prepaid shipments: 6 months = 2 shipments; 12 months = 4; every 90 days, first at purchase',
                 'updated_records':[[k,i] for k,i,_ in updates],'sticky_writes':0,'payment_writes':0}
        db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)',(run_id,time.time(),json.dumps(details)))
        return {'already_applied':False,'updated_masters':sum(k=='master' for k,_,_ in updates),'updated_plans':sum(k=='purchase_option' for k,_,_ in updates)}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--all',action='store_true',help='Import all four master therapies and apply shipment defaults')
    args=parser.parse_args()
    from app import app
    result={'starter_catalog':run(app)}
    if args.all:
        result['pt141']=add_pt141(app)
        result['shipment_defaults']=upgrade_shipments(app)
    print(json.dumps(result))
