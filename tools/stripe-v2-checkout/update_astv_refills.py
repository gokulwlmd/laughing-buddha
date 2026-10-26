"""Keep only the finalized ASTV 5-pack sheet row selectable; defer longer drafts."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time
from import_astv_masters import CatalogView, PRODUCTS
from master import MasterSKU
from plans import PurchaseOption
from catalog_contracts import validate_purchase_pairs
from catalog_refill_policies import astv_source_products, proposed_policy, source_binding
from refill_rules import SaveRefillRules, validate_included_policy

RUN_ID = 'owner-approved-astv-sheet-only-20261026-v2'


def prepare(existing):
    view = CatalogView(copy.deepcopy(existing))
    pending = {}
    for months, _, _ in PRODUCTS:
        p = dict(sku=f'ASTV-5P-{months}M', therapy_id='erectile-dysfunction', treatment_id='astv-5pack')
        if months == 1:p.update(astv_source_products()[0])
        for suffix in ('', '-SUB'):
            sku = p['sku'] + suffix
            old = view.get('master', sku)
            contract = (old or {}).get('planning_contract') or {}
            if (not old or old['therapy_id'] != p['therapy_id'] or old['treatment_id'] != p['treatment_id']
                    or old['product_duration_months'] != months
                    or contract.get('charge') != 'full_term_upfront'
                    or contract.get('term_months') != months
                    or contract.get('renewal_months') != (months if suffix else None)
                    or contract.get('shipments_per_term') != (1 if months == 1 else None)
                    or contract.get('shipment_interval') is not None
                    or view.get('refill_policy', sku)
                    or any(v.get('sku') == sku for v in view.records('campaign_master') + view.records('assignment'))):
                raise ValueError('ASTV draft changed or assigned; reconcile: ' + sku)
            payload = {k: copy.deepcopy(v) for k,v in old.items() if k in MasterSKU.model_fields}
            payload['enabled'] = months == 1
            value, guards, _, operations, _ = view.prepare_master('master', payload)
            if guards or operations:raise ValueError('Unexpected provider operation')
            view.saved['master',sku] = pending['master',sku] = value
            if months == 1:
                policy = proposed_policy(p, sku)
                body = SaveRefillRules.model_validate({k:v for k,v in policy.items() if k not in ('sku','revision')} | {'expected_revision':0})
                validate_included_policy(body, source_binding(sku), value['product_setup'])
                pending['refill_policy',sku] = policy
        key = ('purchase_option',f'astv-5pack-{months}m')
        plan = copy.deepcopy(existing[key])
        expected = [p['sku'],p['sku']+'-SUB']
        if plan['skus'] != expected:raise ValueError('ASTV plan changed; reconcile')
        plan['payment_types'] = ['once','subscription']
        plan['enabled'] = months == 1
        if months == 1:
            pending[key] = view.prepare_plan('purchase_option',{k:v for k,v in plan.items() if k in PurchaseOption.model_fields})[0]
        else:
            PurchaseOption.model_validate({k:v for k,v in plan.items() if k in PurchaseOption.model_fields})
            plan['revision'] = plan.get('revision',0)+1
            pending[key] = plan
        view.saved[key] = pending[key]
    key = ('template_draft','master-therapy-astv-5pack')
    draft = copy.deepcopy(existing[key])
    if {p['id'] for p in draft['plans']} != {f'astv-5pack-{m}m' for m,_,_ in PRODUCTS}:
        raise ValueError('ASTV template changed; reconcile')
    draft['plans'] = [{k:v for k,v in pending['purchase_option',f'astv-5pack-{m}m'].items() if k in PurchaseOption.model_fields} for m in (1,)]
    value, guards, _, operations, _ = view.prepare_template_editor(draft)
    if guards or operations:raise ValueError('Unexpected template provider operation')
    pending[key] = value['request']
    key = ('therapy_variant_catalog','astv-5pack')
    variants = copy.deepcopy(existing[key])
    products = {p['sku']:p for p in astv_source_products()}
    for p in variants['products']:
        p['enabled'] = p['sku'] in products
        if p['enabled']:p.update(products[p['sku']])
        else:p['deferred_reason'] = 'Exact SKU absent from the source sheet; await clarification.'
    variants['source'] += ' Final owner decision 2026-10-26: use only exact finalized sheet rows; 3/6/12-month 5-pack drafts deferred.'
    variants['activation'] = 'Only the 1-month 5-pack is selectable. Longer terms disabled pending clarification. Site-specific Sticky mappings still required; ingredient strengths remain unconfirmed.'
    pending[key] = variants
    validate_purchase_pairs([v for (k,_),v in pending.items() if k=='master'], [f'ASTV-5P-{m}M' for m,_,_ in PRODUCTS])
    return pending


def install(path, apply=False):
    path = Path(path).resolve(strict=True)
    with sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        existing = {(k,i):json.loads(v) for k,i,v in db.execute('SELECT kind,id,data FROM admin_config')}
        row = db.execute('SELECT details FROM admin_setup_runs WHERE id=?',(RUN_ID,)).fetchone()
        if row:
            if any(tuple(k) not in existing for k in json.loads(row[0])['records']):
                raise ValueError('Incomplete ASTV delivery import; reconcile')
            return {'already_imported':True}
        pending = prepare(existing)
        if apply:
            for (k,i),v in pending.items():
                if (k,i) in existing:db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?',(json.dumps(v),k,i))
                else:db.execute('INSERT INTO admin_config(kind,id,data) VALUES(?,?,?)',(k,i,json.dumps(v)))
            db.execute('INSERT INTO admin_setup_runs VALUES(?,?,?)',(RUN_ID,time.time(),json.dumps({'records':list(pending),'provider_writes':0})))
        return {'applied':apply,'enabled_masters':2,'disabled_masters':6,'refill_policies':2,'selectable_terms':[1],'provider_writes':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    print(json.dumps(install(args.database,args.apply)))
