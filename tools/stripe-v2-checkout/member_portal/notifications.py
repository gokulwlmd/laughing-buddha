"""Patient updates from already-authorized order snapshots; no provider calls."""
import hashlib
import json

from pydantic import BaseModel


class Notification(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    created_at: str | None = None
    read_at: str | None = None
    order_id: str
    task_id: str | None = None
    action: str


class NotificationsResult(BaseModel):
    notifications: list[Notification]
    unread_count: int


def order_notifications(orders, site_id, patient_id):
    """Current actionable updates, one care journey per paid term.

    Tracking and clinical status are independent. An imported tracking number
    alone must not turn an unshipped order into a shipment announcement.
    """
    result = []

    def add(order, kind, title, body, action='order-detail', task=None, event=None):
        task_id = task['id'] if task else None
        key = [site_id, patient_id, kind, str(order['id']), task_id, event]
        result.append({'id': hashlib.sha256(json.dumps(key).encode()).hexdigest(),
            'kind': kind, 'title': title, 'body': body, 'action': action,
            'order_id': str(order['id']), 'task_id': task_id,
            'created_at': event if kind == 'refill_available' else order.get('shipping_date')
                if kind in ('shipped', 'delivered') else order.get('created_at'),
            'read_at': None})

    terms = {}
    for order in orders:
        product = str(order.get('product_name') or 'Your treatment').split(' · ')[0]
        shipping = order.get('fulfillment_status')
        if shipping in ('shipped', 'delivered'):
            verb = 'has arrived' if shipping == 'delivered' else 'has shipped'
            tracking = order.get('tracking_number')
            add(order, shipping, f'{product} {verb}',
                f'Order {order["id"]}. ' + (f'Tracking number: {tracking}' if tracking else 'View your delivery details.'),
                event=tracking or order.get('shipping_date'))
        plan = order.get('care_plan') or {}
        term_id = str(plan.get('term_order_id') or order['id'])
        if term_id not in terms or str(order['id']) == term_id:
            terms[term_id] = order

    for order in terms.values():
        product = str(order.get('product_name') or 'Your treatment').split(' · ')[0]
        if order.get('payment_status') not in ('paid', 'captured', 'approved'):
            continue
        tasks = (order.get('care_plan') or {}).get('tasks', [])
        if not order.get('care_plan') and order.get('intake_status') not in ('submitted', 'not_required'):
            add(order, 'intake_needed', f'Complete your {product} health form',
                'Your answers save as you go. Open your order to continue.')
        for task in tasks:
            claim = task.get('claim') or {}
            if task.get('kind') == 'initial' and task.get('status') != 'submitted' and task.get('can_open'):
                add(order, 'intake_needed', f'Complete your {product} health form',
                    'Your answers save as you go. Continue when you are ready.', 'open-care-task', task)
            elif task.get('kind') == 'renewal_check_in' and task.get('status') != 'submitted' and task.get('can_open'):
                add(order, 'check_in_needed', f'Your {product} renewal needs a check-in',
                    'Complete the short health update for your renewed plan.', 'open-care-task', task)
            elif claim.get('status') == 'claimed' and task.get('status') != 'submitted' and task.get('can_open'):
                add(order, 'check_in_needed', f'Your {product} refill needs a check-in',
                    'Your included refill is claimed. Complete its health check-in.', 'open-care-task', task)
            elif claim.get('available') and claim.get('status') not in ('claimed', 'processing', 'pending', 'submitting', 'uncertain', 'reconciliation_required'):
                add(order, 'refill_available', f'Your {product} refill is available',
                    'Included in your plan · $0. Review and claim your next refill.',
                    'claim-refill', task, claim.get('opens_at') or task.get('opens_at'))
    return result
