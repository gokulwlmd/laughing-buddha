"""Verified fixed-term prepaid contract. Renewal and discounts remain unsupported."""
from decimal import Decimal


def active(value):return value not in (None,False,0,'0','')


def profile(cycles):
    return {'is_subscription':0,'is_cancel_immediate':0,'is_refund_allowed':1,
        'is_initial_shipping_on_restart':0,'terms':[{'cycles':cycles,'discount_type_id':1,'discount_value':0}]}


def configuration(cycles):
    return {'type_id':2,'recurring':{'cycle_type_id':1,'terminating_cycle_type_id':2},'prepaid':profile(cycles)} if cycles else {}


def cycles_for(offer):
    """Fail closed on unverified/multiple/renewing/discounted prepaid terms."""
    if not (active(offer.get('is_prepaid')) or offer.get('type_id')==2 or (offer.get('type') or {}).get('id')==2):return None
    p=offer.get('prepaid_profile') or offer.get('prepaid') or {}
    if 'is_subscription' not in p or any(active(p.get(k)) for k in ('is_subscription','is_convert_to_standard')):
        raise ValueError('Prepaid renewal and conversion need additional verification')
    terms=p.get('terms',[])
    if len(terms)!=1:raise ValueError('Choose one fixed prepaid term per purchase option')
    term=terms[0];cycles=term.get('cycles')
    if type(cycles) is not int or not 2<=cycles<=36 or Decimal(str(term.get('discount_value',-1)))!=0:
        raise ValueError('Use 2–36 prepaid shipments with an explicit total and no additional discount')
    if any(active(offer.get(k)) for k in ('is_trial','is_seasonal','is_series')):
        raise ValueError('Combined prepaid offer types need additional setup')
    cycle=offer.get('cycle_type_id',(offer.get('cycle_type') or {}).get('id',(offer.get('recurring') or {}).get('cycle_type_id')))
    if cycle!=1 or active(offer.get('expire_cycles')):raise ValueError('Prepaid requires a fixed self-recurring product without a separate expiry rule')
    return cycles


def unit_price(total,cycles=None):
    total=Decimal(str(total));unit=total/Decimal(cycles or 1)
    if unit<=0 or unit!=unit.quantize(Decimal('.01')):
        raise ValueError('Upfront price must divide into an exact cent amount per shipment')
    return unit


def order_terms_match(product,cycles):
    rows=product.get('prepaid') or []
    return len(rows)==1 and str(rows[0].get('total_cycles'))==str(cycles) and str(rows[0].get('current_cycle'))=='1' and str(rows[0].get('is_renew'))=='0'
