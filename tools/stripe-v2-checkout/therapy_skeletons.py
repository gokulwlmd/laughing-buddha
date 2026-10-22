"""Versioned planning contracts, never executable billing or priced master records."""
import copy

SKELETON_ID = 'master-therapy-1-v1'
BLOCKER = ('Draft skeleton: add prices and verify calendar-month billing, shipment schedules '
           'and prepaid renewal before activating this checkout.')


def weight_loss_skeleton():
    products = []
    for prefix, treatment in [('SEMA', 'Semaglutide'), ('TIRZ', 'Tirzepatide')]:
        for months in (1, 3, 6, 12):
            for renew in (False, True):
                products.append({
                    'sku': f'{prefix}-{months}M' + ('-SUB' if renew else ''),
                    'treatment': treatment, 'duration_months': months,
                    'price': None, 'charge': 'full_term_upfront',
                    'renewal_months': months if renew else None,
                    'shipments_per_term': {6: 2, 12: 4}.get(months),
                    'shipment_interval': None, 'later_shipment_charge': '0.00',
                })
    return {'id': SKELETON_ID, 'version': 1, 'name': 'Master Therapy 1 · Weight Loss',
            'therapy': {'id': 'weight-loss', 'name': 'Weight Loss', 'enabled': True,
                        'treatments': [{'id': 'semaglutide', 'name': 'Semaglutide'},
                                       {'id': 'tirzepatide', 'name': 'Tirzepatide'}]},
            'products': products, 'ready': False, 'reason': BLOCKER}


def skeleton_draft():
    skeleton = weight_loss_skeleton()
    return {'id': 'master-therapy-1', 'name': skeleton['name'],
            'title': 'Choose your weight loss plan', 'therapy_id': 'weight-loss',
            'new_therapy': copy.deepcopy(skeleton['therapy']),
            'skeleton_id': SKELETON_ID, 'draft': True, 'enabled': True,
            'plans': [{'id': f'weight-loss-{months}m', 'name': f'{months}-month plan',
                       'therapy_id': 'weight-loss', 'duration_months': months,
                       'skus': [], 'payment_types': ['once', 'subscription'] if months < 6 else ['prepaid', 'subscription'],
                       'enabled': True} for months in (1, 3, 6, 12)]}
