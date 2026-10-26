"""Care role from server-verified order lineage, never a SKU suffix."""
import json
from decimal import Decimal, InvalidOperation


def order_role(row, root=None):
    snap, raw = json.loads(row['snapshot']), json.loads(row['payload'])
    root_id = str(snap.get('root_order_id') or row['order_id'])
    if root_id == str(row['order_id']):
        return 'initial'
    if not root or str(root['order_id']) != root_id:
        return 'unconfirmed'
    original = json.loads(root['payload'])
    lines, originals = raw.get('products', []), original.get('products', [])
    if (any(row[k] != root[k] for k in ('site_id', 'customer_id', 'sku'))
            or len(lines) != 1 or len(originals) != 1
            or str(raw.get('ancestor_id')) != root_id
            or raw.get('campaign_id') != original.get('campaign_id')
            or not lines[0].get('subscription_id')
            or any(lines[0].get(k) != originals[0].get(k) for k in ('product_id', 'sku', 'subscription_id'))):
        return 'unconfirmed'
    try:
        total = Decimal(str(raw['total']))
    except (InvalidOperation, KeyError):
        return 'unconfirmed'
    prepaid = lines[0].get('prepaid') or {}
    if prepaid.get('current_cycle', 0) > 1 and total == 0:
        return 'included_refill'
    if (str(snap.get('term_order_id')) == str(row['order_id']) and total > 0
            and (not prepaid or prepaid.get('current_cycle') == 1)):
        return 'paid_renewal'
    return 'unconfirmed'
