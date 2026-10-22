"""Versioned master therapy recipes; starter prices are editable catalog defaults."""
import copy
from decimal import Decimal

SKELETON_ID = 'master-therapy-1-v1'
BLOCKER = ('Catalog draft: verify calendar-month billing, shipment schedules '
           'and prepaid renewal before activating this checkout.')
# Explicit implementation-selected starter prices, not market or clinical claims.
RECIPES = [
    (1, 'weight-loss', 'Weight Loss', [('SEMA', 'Semaglutide', '249.00'), ('TIRZ', 'Tirzepatide', '449.00')]),
    (2, 'sermorelin', 'Sermorelin', [('SERM', 'Sermorelin', '199.00')]),
    (3, 'metformin', 'Metformin', [('METFORM', 'Metformin', '49.00')]),
]


def all_skeletons():
    result = []
    for number, therapy_id, name, treatments in RECIPES:
        products = []
        for prefix, treatment, monthly in treatments:
            for months in (1, 3, 6, 12):
                for renew in (False, True):
                    products.append({
                        'sku': f'{prefix}-{months}M' + ('-SUB' if renew else ''),
                        'treatment': treatment, 'treatment_id': treatment.lower(),
                        'duration_months': months,
                        'price': format(Decimal(monthly) * months, '.2f'), 'currency': 'USD',
                        'price_basis': 'Editable starter price; monthly reference multiplied by term',
                        'charge': 'full_term_upfront',
                        'renewal_months': months if renew else None,
                        'shipments_per_term': {6: 2, 12: 4}.get(months) if number == 1 else None,
                        'shipment_interval': None, 'later_shipment_charge': '0.00',
                    })
        result.append({'id': f'master-therapy-{number}-v1', 'version': 1,
                       'name': f'Master Therapy {number} · {name}',
                       'therapy': {'id': therapy_id, 'name': name, 'enabled': True,
                                   'treatments': [{'id': t.lower(), 'name': t} for _, t, _ in treatments]},
                       'products': products, 'ready': False, 'reason': BLOCKER})
    return result


def weight_loss_skeleton():
    return all_skeletons()[0]


def skeleton_draft(skeleton=None, assigned=False):
    skeleton = skeleton or weight_loss_skeleton()
    therapy_id = skeleton['therapy']['id']
    return {'id': skeleton['id'].removesuffix('-v1'), 'name': skeleton['name'],
            'title': 'Choose your ' + skeleton['therapy']['name'].lower() + ' plan',
            'therapy_id': therapy_id, 'new_therapy': copy.deepcopy(skeleton['therapy']),
            'skeleton_id': skeleton['id'], 'draft': True, 'enabled': True,
            'plans': [{'id': f'{therapy_id}-{months}m', 'name': f'{months}-month plan',
                       'therapy_id': therapy_id, 'duration_months': months,
                       'skus': [p['sku'] for p in skeleton['products'] if p['duration_months'] == months] if assigned else [],
                       'payment_types': ['once', 'subscription'], 'enabled': True}
                      for months in (1, 3, 6, 12)]}
