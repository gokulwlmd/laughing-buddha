"""Verified display catalogs, invalidated by local configuration edits.

No payment state, card data or credentials. Checkout still reads Sticky and
requotes the selected option before any authorization/capture.
"""
import json
from master import assignment_id,campaign_master_id,fingerprint
from plans import choice_id


def keys_for(plan):
    keys={('plan_checkout',plan['id']),('brand',plan['brand_id']),('therapy',plan['therapy_id'])}
    for entry in plan['entries']:
        sku=entry['sku'];aid=assignment_id(plan['brand_id'],plan['campaign_id'],sku)
        keys.update({('master',sku),('campaign_master',campaign_master_id(plan['brand_id'],plan['campaign_id'],sku)),
            ('assignment',aid),('offering','master-'+aid+'-upfront'),('link',choice_id(plan['id'],sku,entry.get('purchase_option_id','')))})
        if entry.get('purchase_option_id'):keys.add(('purchase_option',entry['purchase_option_id']))
    return keys


def digest(admin,plan):
    keys=keys_for(plan);ids=sorted({i for k,i in keys})
    with admin.store.db() as db:
        rows=db.execute('SELECT kind,id,data FROM admin_config WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
    return fingerprint(sorted((k,i,json.loads(data)) for k,i,data in rows if (k,i) in keys))


def read_snapshot(admin,plan):
    row=admin.get('public_catalog_snapshot',plan['id'])
    if row and row.get('source_hash')==digest(admin,plan):return row['catalog']
    return None
