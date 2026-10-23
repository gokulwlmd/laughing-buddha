"""Loopback-only browser QA server with an offline Sticky contract fixture."""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from test_member_portal import build_member_fixture


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--care-plan', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged port')
    app, fake, attempt = build_member_fixture(args.state_dir, origin=f'http://127.0.0.1:{args.port}')
    # This fixture is the sole source of order data. No network-capable Sticky
    # client is used. A shippable offline product exercises eligible UI actions.
    if args.care_plan:
        from test_member_care import configure_native_care_fixture
        fake = configure_native_care_fixture(app, months=12)
    else:
        fake.order['shippable'] = '1'
        fake.order['products'][0]['is_shippable'] = '1'
        admin = app.state.admin
        plan = deepcopy(admin.get('plan_checkout', 'plan-a'))
        plan['payment_test_only'] = False
        admin.put('plan_checkout', 'plan-a', plan)
        admin.put('refill_policy', 'SEMA-1M-SUB', {
            'enabled': True, 'minimum_days': 0, 'request_window_days': 14,
            'check_in_required': False, 'review_required': True,
            'test_requests_enabled': False, 'revision': 1,
            'allow_early_requests': True, 'early_request_minimum_days': 0,
            'early_request_cooldown_days': 7, 'early_reason_required': True,
        })

    @app.post('/__member_identity', include_in_schema=False)
    def enable_identity():
        from test_wlmd_identity import FakeIdentity
        raw=app.state.admin.get('site','site-a');raw['wlmd_site_id']='qa-wlmd'
        app.state.admin.put('site','site-a',raw)
        app.state.member_portal.identity_checks.provider=FakeIdentity()
        from test_id_uploads import FakeUpload
        app.state.member_portal.id_uploads.provider=FakeUpload()
        return {'enabled': True}

    @app.get('/__member_qa', include_in_schema=False)
    def proof():
        counts = {}
        for method, path, _body in fake.calls:
            key = method + ' ' + path
            counts[key] = counts.get(key, 0) + 1
        native_orders = [{
            'id': order['order_id'], 'total': order['order_total'],
            'next_cycle_date': order['products'][0].get('recurring_date'),
        } for order in getattr(fake, 'orders', {}).values()]
        return {'calls': counts, 'native_orders': native_orders, 'shipping_state': fake.order.get('shipping_state'), 'subscription_state': fake.subscription.get('shipping', {}).get('state')}

    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False, proxy_headers=False)
