"""Explicit SKU bindings for mock intake/check-in content, not clinical rules."""
from copy import deepcopy
from patient_demo.provider import get_template as initial_template, question, YES_NO

PRODUCTS = {
    'SEMA': ('weight-loss', 'Semaglutide'),
    'TIRZ': ('weight-loss', 'Tirzepatide'),
    'SERM': ('sermorelin', 'Sermorelin'),
    'METFORM': ('metformin', 'Metformin'),
    'PT141': ('pt-141', 'PT-141'),
}
SKU_BINDINGS = {
    f'{prefix}-{months}M{suffix}': {'template_id': template_id, 'product_name': name, 'duration_months': months}
    for prefix, (template_id, name) in PRODUCTS.items()
    for months in (1, 3, 6, 12)
    for suffix in ('', '-SUB')
}


def binding_for_sku(sku):
    from catalog_refill_policies import source_binding
    return deepcopy(SKU_BINDINGS.get(sku) or source_binding(sku))


def get_template(template_id, *, sku, kind='initial'):
    binding = binding_for_sku(sku)
    if not binding or binding['template_id'] != template_id or kind not in ('initial', 'checkin'):
        raise ValueError('No mock intake is assigned to this product')
    name = binding['product_name']
    if kind == 'initial':
        if template_id in ('hair-growth', 'nad-plus', 'glutathione'):
            from patient_demo.provider import COMMON
            result = {'sections': [
                {'id': 'goals', 'title': 'Your treatment', 'description': 'Tell us what brought you here.'},
                {'id': 'health', 'title': 'Health background', 'description': 'Review your current health information.'},
                {'id': 'review', 'title': 'Review & submit', 'description': 'Check your answers before submitting.'}],
                'questions': [question('treatment_goals', 'goals', f'What would you like to discuss about {name}?'),
                    question('previous_treatment', 'goals', f'Have you used {name} before?', 'single_choice', 'no', options=YES_NO),
                    question('previous_treatment_details', 'goals', 'Tell us about your previous treatment and experience.',
                        show_if={'question_id': 'previous_treatment', 'equals': 'yes'}), *deepcopy(COMMON)]}
        else:
            result = initial_template(template_id)
        result['questions'] = [q for q in result['questions'] if q['id'] != 'demo_confirmation']
    else:
        specific = {
            'weight-loss': [
                question('current_weight_pounds', 'progress', 'What is your current weight in pounds?', 'number', 180),
                question('weight_progress', 'progress', 'What would you like to discuss about your weight-management progress?',
                         sample='MOCK TEST: I would like to review the example plan.'),
            ],
            'sermorelin': [
                question('sermorelin_progress', 'progress', 'What changes in your day-to-day wellbeing would you like to discuss?',
                         sample='MOCK TEST: No real health information supplied.'),
            ],
            'metformin': [
                question('metformin_progress', 'progress', 'How has your experience with Metformin been since your last check-in?',
                         sample='MOCK TEST: No real medication has been supplied.'),
                question('new_measurements', 'progress', 'Are there any recent health measurements you would like to share?',
                         sample='MOCK TEST: No measurements to share.', required=False),
            ],
            'pt-141': [
                question('pt141_progress', 'progress', 'Have your sexual health concerns changed since your last check-in?',
                         sample='MOCK TEST: No real health information supplied.'),
            ],
        }.get(template_id, [question('treatment_progress', 'progress', f'What would you like to discuss about your experience with {name}?')])
        result = {
            'sections': [
                {'id': 'progress', 'title': 'Your progress', 'description': 'Tell us how things have been going.'},
                {'id': 'changes', 'title': 'Health updates', 'description': 'Review what has changed since your last intake.'},
                {'id': 'review', 'title': 'Review & submit', 'description': 'Check your answers before submitting.'},
            ],
            'questions': [
                question('treatment_started', 'progress', f'Have you started the {name} treatment listed in this plan?',
                         'single_choice', 'no', options=YES_NO),
                *specific,
                question('treatment_experience', 'progress', f'What would you like the care team to know about your experience with {name}?',
                         sample='MOCK TEST: This is a Dry Run order; no medication was supplied.'),
                question('new_symptoms', 'changes', 'Have you noticed any new symptoms or concerns?',
                         sample='MOCK TEST: No real symptoms are being reported.'),
                question('medication_changes', 'changes', 'Have your medications or supplements changed?',
                         sample='MOCK TEST: No real medication history supplied.'),
                question('allergy_changes', 'changes', 'Have you had any new allergies or reactions?',
                         sample='MOCK TEST: No real allergy information supplied.'),
                question('health_changes', 'changes', 'Have there been other changes to your health or medical care?',
                         sample='MOCK TEST: No real health history supplied.'),
                question('checkin_notes', 'review', 'Is there anything else you would like to discuss?',
                         sample='MOCK TEST: End-to-end portal verification only.', required=False),
            ],
        }
    result.update(id=f'{template_id}-{sku}-{kind}-mock', version='mock-care-1',
                  title=f'{name} '+('health intake' if kind == 'initial' else 'check-in'),
                  demo=True, mock=True, sku=sku, product_name=name, kind=kind,
                  description='Mock questions for testing this care journey. The medical intake provider is not connected; these answers are not sent to clinicians.')
    return result
