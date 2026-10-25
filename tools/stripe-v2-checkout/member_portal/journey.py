"""Customer-facing progress from recorded evidence, never inferred approvals."""


def order_journey(order):
    paid = order.get('payment_status') in ('paid', 'approved', 'captured')
    intake = order.get('intake_status', 'not_started')
    no_form = intake == 'not_required'
    refill = order.get('intake_kind') == 'checkin' or order.get('order_role') in ('paid_renewal', 'included_refill')
    submitted = intake == 'submitted' or no_form
    medical = order.get('medical_status', 'unknown')
    reviewed = medical in ('approved', 'prescribed')
    prescribed = medical == 'prescribed'
    fulfillment = order.get('fulfillment_status', 'unknown')
    shipped = fulfillment in ('shipped', 'delivered')
    delivered = fulfillment == 'delivered'
    payment_issue = order.get('payment_status') in ('declined', 'void_or_refunded', 'voided', 'refunded', 'partially_refunded', 'chargeback')
    review_issue = medical in ('declined', 'rejected', 'needs_information')
    held = fulfillment == 'on_hold'
    stages = [
        dict(key='payment', label='Order received', done=paid, detail='Payment confirmed' if paid else 'Payment needs attention' if payment_issue else 'Confirming payment', date=order.get('created_at') if paid else None),
        dict(key='intake', label='Refill check-in' if refill else 'Health intake', done=submitted, detail='No check-in is required for this refill' if no_form else 'Your answers are saved' if submitted else 'Continue your saved health form' if intake == 'draft' else 'Complete your health form', date=None),
        dict(key='review', label='Medical review', done=reviewed, detail='Review complete' if reviewed else 'Follow-up needed' if review_issue else 'Review in progress' if medical == 'in_review' else 'Waiting for a review update', date=None),
        dict(key='prescription', label='Prescription', done=prescribed, detail='Prescription confirmed' if prescribed else 'Waiting for confirmation', date=None),
        dict(key='shipping', label='Shipping', done=shipped, detail='Delivered' if delivered else 'On its way' if shipped else 'Tracking will appear when available', date=order.get('shipping_date') if shipped else None),
    ]
    # Shipping evidence does not prove unrecorded clinical steps. Keep those
    # unknown, rather than displaying a completed review or prescribing event.
    current = next((s['key'] for s in stages if not s['done']), None)
    if shipped or payment_issue or review_issue or held:
        current = None
    for stage in stages:
        stage['state'] = 'complete' if stage.pop('done') else 'current' if stage['key'] == current else 'upcoming'
        if stage['key'] in ('review', 'prescription') and medical in ('not_connected', 'unknown', None):
            if stage['state'] != 'complete' and (submitted or shipped):
                stage['state'] = 'unconfirmed'
    if payment_issue or review_issue or held:
        title = 'Payment needs attention' if payment_issue else 'A follow-up is needed' if review_issue else 'Your order is on hold'
        detail, action = 'Contact support for help with the next step.', 'support'
    elif shipped:
        title = 'Your order has arrived' if delivered else 'Your order is on its way'
        detail, action = 'Your shipment updates are shown below.', 'shipment'
    elif not paid:
        title, detail, action = 'Confirming your order', 'We are waiting for a confirmed payment status.', 'wait'
    elif not submitted:
        title = ('Continue your refill check-in' if intake == 'draft' else 'Your refill check-in is next') if refill else ('Continue your health intake' if intake == 'draft' else 'Your health intake is next')
        detail, action = 'Your progress saves as you go. You can finish here or in your member portal.', 'intake'
    elif not reviewed:
        title, detail, action = ('Your refill order is received' if no_form else 'Your check-in is saved' if refill else 'Your intake is saved'), 'No more intake questions right now. Your care status will update here when a review update is received.', 'wait'
    else:
        title = 'Preparing for shipping' if prescribed else 'Prescription is the next step'
        detail, action = 'Your recorded progress is shown below. Tracking will appear when available.', 'wait'
    return dict(title=title, detail=detail, next_action=action, stages=stages,
                updated_at=order.get('last_synced_at'), tracking_number=order.get('tracking_number'),
                shipping_date=order.get('shipping_date'))
