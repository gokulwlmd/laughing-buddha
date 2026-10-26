import json, sqlite3, unittest
from pathlib import Path
from unittest.mock import Mock
from fastapi import HTTPException
from member_portal.intake_presentation import upgrade, prepare_record, contact_defaults, REVISION
from patient_demo.app import visible, clean_answers, IntakeQuestion

TEMPLATE=json.loads((Path(__file__).parent/'member_portal/weight_loss_questions.json').read_text())
class IntakePresentationTests(unittest.TestCase):
 def setUp(self):
  self.s=Mock();self.s.captured.return_value=[{'contact':json.dumps({'phone':'2025550100'})}]
  self.order={'site_id':'site-a','order_id':'owned-1','payload':json.dumps({'customer':{'name':'Synthetic Patient','email':'patient@example.test'},'shipping_address':{'address':'1 Example St','city':'Test City','region':'CA','postal_code':'90001','country':'US'}})}
 def test_scoped_checkout_prefill_and_state_mapping(self):
  values=contact_defaults(self.s,self.order,TEMPLATE)
  self.assertEqual(values['ca_196'],'California (CA)');self.assertEqual(values['ca_202'],'2025550100')
  self.s.captured.assert_called_once_with('site-a','owned-1')
 def test_array_branch_and_hidden_legacy_followups(self):
  questions={q['id']:q for q in TEMPLATE['questions']}
  self.assertFalse(visible(questions['ca_249'],{'ca_248':['NONE of the below']}))
  self.assertTrue(visible(questions['ca_249'],{'ca_248':['Medullary thyroid cancer']}))
  for key in ('ca_240','ca_241','ca_242','ca_243','ca_247','ca_442','ca_252'):
   self.assertFalse(visible(questions[key],{}))
  self.assertTrue(visible(questions['ca_541'],{'ca_538':'Yes','ca_545':'Tirzepatide (Compound, Mounjaro, Zepbound)'}))
  self.assertFalse(visible(questions['ca_541'],{'ca_538':'No','ca_545':'Tirzepatide (Compound, Mounjaro, Zepbound)'}))
 def test_none_is_exclusive_server_side(self):
  q=next(q for q in TEMPLATE['questions'] if q.get('exclusive_options') and len(q['options'])>1)
  none=q['exclusive_options'][0];other=next(o['value'] for o in q['options'] if o['value'] not in q['exclusive_options'])
  with self.assertRaises(HTTPException):clean_answers(TEMPLATE,{q['id']:[none,other]})
  self.assertEqual(clean_answers(TEMPLATE,{q['id']:[none]})[q['id']],[none])
 def test_api_keeps_form_control_metadata(self):
  q=next(q for q in TEMPLATE['questions'] if q['id']=='ca_196')
  self.assertEqual(IntakeQuestion(**dict(q,prefill_source='checkout')).model_dump()['presentation'],'select')
 def test_draft_upgrade_preserves_answers_and_is_idempotent(self):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.execute('CREATE TABLE member_intakes(id TEXT PRIMARY KEY,status TEXT,template TEXT,answers TEXT,current_step INT,revision INT)')
  old=dict(TEMPLATE,version='coreage-reference-2026-10-26');old['sections']=[{'id':'treatment','title':'Treatment'}]
  old['questions']=[dict(q,section_id='treatment') for q in TEMPLATE['questions']]
  db.execute('INSERT INTO member_intakes VALUES(?,?,?,?,?,?)',('draft','draft',json.dumps(old),json.dumps({'ca_199':'Already edited','ca_538':'No'}),0,4))
  row=dict(db.execute('SELECT * FROM member_intakes').fetchone());new=prepare_record(self.s,db,self.order,row,'member_intakes')
  self.assertEqual(new['revision'],5);self.assertEqual(json.loads(new['answers'])['ca_199'],'Already edited');self.assertEqual(json.loads(new['template'])['version'],REVISION)
  again=prepare_record(self.s,db,self.order,new,'member_intakes');self.assertEqual(again,new)
  db.execute("UPDATE member_intakes SET status='submitted'");submitted=dict(db.execute('SELECT * FROM member_intakes').fetchone())
  self.assertEqual(prepare_record(self.s,db,self.order,submitted,'member_intakes'),submitted)
 def test_unrelated_template_untouched(self):
  original={'version':'mock-care-1','questions':[],'sections':[]};self.assertEqual(upgrade(original),original)
if __name__=='__main__':unittest.main()
