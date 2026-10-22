"""Run backend checks and browser scenarios, recording reproducible QA evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
results=ROOT/'qa/results';results.mkdir(parents=True,exist_ok=True)
suite=unittest.defaultTestLoader.loadTestsFromNames(['test_checkout','test_admin','test_qa','test_master','test_brands','test_prepaid','test_prepaid_import','test_plans','test_purchase_options','test_sites','test_synthetic'])
result=unittest.TextTestRunner(verbosity=2).run(suite)
(results/'backend.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)},indent=2)+'\n')
if not result.wasSuccessful():raise SystemExit(1)
for script in sorted(Path('web').glob('*.js')):subprocess.run(['node','--check',str(script)],check=True)
env=os.environ.copy();env['QA_PYTHON']=sys.executable
(results/'results.json').unlink(missing_ok=True)
test=subprocess.run(['npm','--prefix','qa','test','--','--config=playwright.config.cjs'],env=env)
if not (results/'results.json').exists():
    raise SystemExit('Browser runner did not produce results; no report generated.')
subprocess.run([sys.executable,'qa/report.py'],check=True)
raise SystemExit(test.returncode)
