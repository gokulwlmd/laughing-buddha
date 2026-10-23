import unittest
from member_portal.intake_templates import SKU_BINDINGS, get_template
from patient_demo.app import clean_answers, visible


class ProductIntakeTests(unittest.TestCase):
    def test_all_known_product_forms_accept_their_mock_examples(self):
        for sku, binding in SKU_BINDINGS.items():
            for kind in ('initial', 'checkin'):
                with self.subTest(sku=sku, kind=kind):
                    template = get_template(binding['template_id'], sku=sku, kind=kind)
                    self.assertIn(binding['product_name'], template['title'])
                    self.assertNotIn('demo_confirmation', [q['id'] for q in template['questions']])
                    answers = {q['id']: q['sample'] for q in template['questions'] if 'sample' in q}
                    cleaned = clean_answers(template, answers)
                    for question in template['questions']:
                        if question.get('required') and visible(question, cleaned):
                            self.assertNotIn(cleaned.get(question['id']), (None, '', []))

    def test_unmapped_and_wrong_product_forms_are_not_substituted(self):
        for template, sku in [('weight-loss', 'UNKNOWN-12M-SUB'), ('metformin', 'SEMA-12M-SUB'), ('pt-141', 'SERM-6M')]:
            with self.subTest(template=template, sku=sku):
                with self.assertRaises(ValueError):
                    get_template(template, sku=sku)
        weight = get_template('weight-loss', sku='SEMA-12M-SUB', kind='checkin')
        other = get_template('pt-141', sku='PT141-12M-SUB', kind='checkin')
        self.assertIn('current_weight_pounds', {q['id'] for q in weight['questions']})
        self.assertNotIn('current_weight_pounds', {q['id'] for q in other['questions']})
        self.assertIn('pt141_progress', {q['id'] for q in other['questions']})
