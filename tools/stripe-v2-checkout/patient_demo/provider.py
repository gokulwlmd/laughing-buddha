"""Replaceable sample intake provider; no clinical decision or eligibility rules.

These questions are layout/content examples awaiting the owner's intake API.
They must not be used to prescribe, diagnose, approve, or release medication.
"""
from copy import deepcopy

SITES = {
    'willow-health': {'name': 'Willow Health', 'color': '#245844'},
    'harbor-wellness': {'name': 'Harbor Wellness', 'color': '#4355a3'},
}

THERAPIES = {
    'weight-loss': {'name': 'Weight Loss', 'product_name': 'Semaglutide', 'sku': 'SEMA-6M-SUB', 'plan_name': '6-month subscription', 'total': '1494.00', 'currency': 'USD'},
    'sermorelin': {'name': 'Sermorelin', 'product_name': 'Sermorelin', 'sku': 'SERM-3M', 'plan_name': '3-month one-time plan', 'total': '597.00', 'currency': 'USD'},
    'metformin': {'name': 'Metformin', 'product_name': 'Metformin', 'sku': 'METFORM-3M', 'plan_name': '3-month one-time plan', 'total': '147.00', 'currency': 'USD'},
    'pt-141': {'name': 'PT-141', 'product_name': 'PT-141', 'sku': 'PT141-1M', 'plan_name': '1-month one-time plan', 'total': '199.00', 'currency': 'USD'},
}


def question(key, section, label, kind='textarea', sample='', **extra):
    return {'id': key, 'section_id': section, 'label': label, 'type': kind,
            'required': True, 'sample': sample, **extra}


YES_NO = [{'value': 'no', 'label': 'No'}, {'value': 'yes', 'label': 'Yes'},
          {'value': 'not_sure', 'label': 'Not sure'}]

SPECIFIC = {
    'weight-loss': [
        question('weight_goals', 'goals', 'What would you like to discuss about your weight?',
                 sample='I would like to discuss my weight-management goals.',
                 hint='Describe your goals in your own words.'),
        question('height_inches', 'goals', 'What is your height in inches?', 'number', 68,
                 hint='Example: 5 feet 8 inches is 68 inches.'),
        question('weight_pounds', 'goals', 'What is your current weight in pounds?', 'number', 180,
                 hint='Use your most recent measurement.'),
        question('previous_weight_treatment', 'goals', 'Have you used prescription weight-management treatment before?',
                 'single_choice', 'no', options=YES_NO),
        question('previous_weight_details', 'goals', 'Which treatment did you use, and when?',
                 sample='Example treatment history for this demo.',
                 show_if={'question_id': 'previous_weight_treatment', 'equals': 'yes'}),
    ],
    'sermorelin': [
        question('sermorelin_goals', 'goals', 'What would you like to discuss about Sermorelin?',
                 sample='I would like to discuss whether an evaluation is appropriate.',
                 hint='Tell the care team what brought you here. No treatment recommendation is made by this form.'),
        question('previous_hormone_review', 'goals', 'Have you previously had a hormone-related medical evaluation?',
                 'single_choice', 'no', options=YES_NO),
        question('hormone_review_details', 'goals', 'What was discussed in that evaluation?',
                 sample='Example evaluation history for this demo.',
                 show_if={'question_id': 'previous_hormone_review', 'equals': 'yes'}),
        question('previous_sermorelin', 'goals', 'Have you used Sermorelin before?',
                 'single_choice', 'no', options=YES_NO),
    ],
    'metformin': [
        question('metformin_goals', 'goals', 'What would you like to discuss about Metformin?',
                 sample='I would like to discuss my health goals and current care.'),
        question('previous_metformin', 'goals', 'Have you taken Metformin before?',
                 'single_choice', 'no', options=YES_NO),
        question('metformin_experience', 'goals', 'Tell us about your previous experience with Metformin.',
                 sample='Example treatment history for this demo.',
                 show_if={'question_id': 'previous_metformin', 'equals': 'yes'}),
        question('blood_sugar_care', 'goals', 'Are you currently receiving medical care for your blood sugar?',
                 'single_choice', 'no', options=YES_NO),
    ],
    'pt-141': [
        question('sexual_health_goals', 'goals', 'What would you like to discuss about your sexual health?',
                 sample='I would like to discuss a change in sexual desire.',
                 hint='Share only sample information while exploring this demo.'),
        question('concern_duration', 'goals', 'How long have you noticed this concern?',
                 'single_choice', 'months', options=[
                     {'value': 'weeks', 'label': 'A few weeks'},
                     {'value': 'months', 'label': 'A few months'},
                     {'value': 'longer', 'label': 'Longer than a year'},
                     {'value': 'unsure', 'label': 'Not sure / I would prefer to discuss it'},
                 ]),
        question('previous_pt141', 'goals', 'Have you used PT-141 before?', 'single_choice', 'no', options=YES_NO),
        question('pt141_experience', 'goals', 'Tell us about your previous experience with PT-141.',
                 sample='Example treatment history for this demo.',
                 show_if={'question_id': 'previous_pt141', 'equals': 'yes'}),
    ],
}

COMMON = [
    question('current_medications', 'health', 'Which medications and supplements do you currently take?',
             sample='No medications or supplements in this fictional example.',
             hint='Include prescription medicines, over-the-counter products and supplements.'),
    question('allergies', 'health', 'Do you have any medication allergies or past reactions?',
             sample='No known medication allergies in this fictional example.',
             hint='If there are none, say so. Include the reaction if known.'),
    question('health_history', 'health', 'What should the care team know about your medical history?',
             sample='No medical conditions or past procedures in this fictional example.',
             hint='Include conditions, past procedures and any concerns you would like to discuss.'),
    question('additional_notes', 'review', 'Is there anything else you would like the care team to know?',
             sample='This is a sample intake for reviewing the portal.', required=False),
    question('demo_confirmation', 'review', 'Confirm your sample submission', 'single_choice', 'sample_only',
             options=[{'value': 'sample_only', 'label': 'I used sample information and understand this will not reach a medical team.'}]),
]


def get_template(therapy_id):
    therapy = THERAPIES[therapy_id]
    return deepcopy({
        'id': f'{therapy_id}-demo-intake', 'version': 'demo-1',
        'title': therapy['name'] + ' intake', 'demo': True,
        'description': 'A sample questionnaire to preview the experience. Your medical team’s approved questions will be supplied by the intake API.',
        'sections': [
            {'id': 'goals', 'title': 'Your goals', 'description': 'A few questions about why you are here.'},
            {'id': 'health', 'title': 'Health background', 'description': 'Help the care team understand the full picture.'},
            {'id': 'review', 'title': 'Review & submit', 'description': 'Check your sample answers before submitting.'},
        ],
        'questions': SPECIFIC[therapy_id] + COMMON,
    })


def get_sample_answers(therapy_id):
    questions = get_template(therapy_id)['questions']
    values = {q['id']: q['sample'] for q in questions}
    return {q['id']: values[q['id']] for q in questions
            if not q.get('show_if') or values.get(q['show_if']['question_id']) == q['show_if']['equals']}
