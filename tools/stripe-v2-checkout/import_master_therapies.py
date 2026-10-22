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


def run(application):
    admin = application.state.admin
    host = urlparse(admin.cfg.public_url).hostname
    if not admin.cfg.synthetic or host not in ('localhost', '127.0.0.1', 'wlmd-checkout-staging-0f89b1bb.fly.dev'):
        raise ValueError('Import is restricted to local development and isolated synthetic staging')
    with admin.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS admin_setup_runs(id TEXT PRIMARY KEY,created REAL NOT NULL,details TEXT NOT NULL)')
        marker = db.execute('SELECT details FROM admin_setup_runs WHERE id=?', (RUN_ID,)).fetchone()
        if marker:
            details = json.loads(marker[0])
            if not all(db.execute('SELECT 1 FROM admin_config WHERE kind=? AND id=?', key).fetchone() for key in details['created_records']):
                raise ValueError('An imported record is missing; reconcile without overwriting')
            return {'already_imported': True, 'master_skus': 32, 'created_records': 0}
        existing = {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}
        pending = {}
        view = copy.copy(admin)
        view.get = lambda kind, key: pending.get((kind,key), existing.get((kind,key)))
        view.records = lambda kind: [v for (k,i),v in {**existing, **pending}.items() if k == kind]
        def add(kind, key, value):
            if (kind,key) in existing or (kind,key) in pending:
                raise ValueError(f'Existing {kind} {key}; no records were overwritten')
            pending[(kind,key)] = value
        for skeleton in all_skeletons():
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
                data, *_ = view.prepare_plan('purchase_option',plan)
                add('purchase_option',plan['id'],data)
            # Keep any owner-created draft, including its name, choices and edits.
            if ('template_draft',draft['id']) not in existing:
                add('template_draft',draft['id'],draft)
        for (kind,key),value in pending.items():
            db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)',(kind,key,json.dumps(value)))
        details = {'authorization':'User requested Weight Loss, Sermorelin and Metformin SKUs with editable starter pricing',
                   'created_records':[list(key) for key in pending], 'master_skus':32,
                   'starter_monthly_usd':{'SEMA':'249.00','TIRZ':'449.00','SERM':'199.00','METFORM':'49.00'},
                   'price_rule':'Full-term upfront = monthly starter rate × duration; no discount',
                   'sticky_writes':0,'payment_writes':0,'owner_session_created':False}
        db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)',(RUN_ID,time.time(),json.dumps(details)))
        return {'already_imported':False,'master_skus':32,'created_records':len(pending),'sticky_writes':0,'payment_writes':0}


if __name__ == '__main__':
    from app import app
    print(json.dumps(run(app)))
