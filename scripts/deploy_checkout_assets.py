"""Deploy the customer checkout UI without restarting the payment process.

Upload new versioned assets first, then atomically replace the two HTML entry
points. Existing pages retain their original assets and in-memory payment state.
Uses the operator's existing Fly login; never reads application credentials.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

APP='wlmd-stripe-test-0f89b1bb'
BASE='ab1da3645398fdb5833947d8e229118121a17b53'
ASSETS=['checkout-v3.css','plan-selector-v3.css','checkout-v9.js','plan-selector-v3.js','index.html','plans.html']
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Apply the explicitly requested live UI update')
    args=parser.parse_args()
    files={name:(ROOT/'tools/stripe-v2-checkout/web'/name).read_text() for name in ASSETS}
    before={name:hashlib.sha256(subprocess.check_output(['git','show',BASE+':tools/stripe-v2-checkout/web/'+name],cwd=ROOT)).hexdigest() for name in ('index.html','plans.html')}
    bundle=base64.b64encode(json.dumps({'files':files,'before':before,'apply':args.apply}).encode()).decode()
    code="""import base64,json,hashlib,os,sqlite3,tempfile
from pathlib import Path
payload=json.loads(base64.b64decode(__BUNDLE__))
root=Path('/app/web');backup=Path('/data/ui-backups/customer-checkout-v9-20261022')
def digest(data):return hashlib.sha256(data).hexdigest()
def processes():
 result={}
 for process in Path('/proc').iterdir():
  if not process.name.isdigit():continue
  try:
   command=(process/'cmdline').read_bytes().split(b'\\0')
   if len(command)>2 and command[1:3]==[b'-m',b'uvicorn']:
    result[process.name]=(process/'stat').read_text().rsplit(')',1)[1].split()[19]
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
 return result
def state_hashes():
 c=sqlite3.connect('file:/data/checkout.sqlite3?mode=ro',uri=True)
 result={t:digest(repr(c.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall()).encode()) for t in ('admin_owner','admin_reviews','admin_config','checkouts','purchase','purchase_successors')}
 c.close();return result
running=processes();assert len(running)==1,'Expected one running payment worker'
state_before=state_hashes();wanted={name:digest(content.encode()) for name,content in payload['files'].items()}
for name in ('index.html','plans.html'):
 current=digest((root/name).read_bytes())
 assert current in (payload['before'][name],wanted[name]),'Entry point changed outside this release: '+name
for name in payload['files']:
 if name not in ('index.html','plans.html') and (root/name).exists():assert digest((root/name).read_bytes())==wanted[name],'Versioned asset already exists with other contents'
if payload['apply']:
 backup.mkdir(parents=True,exist_ok=True,mode=0o700)
 for name,content in payload['files'].items():
  destination=root/name
  if destination.exists() and digest(destination.read_bytes())==wanted[name]:continue
  if name in ('index.html','plans.html') and not (backup/name).exists():
   (backup/name).write_bytes(destination.read_bytes());os.chmod(backup/name,0o600)
  with tempfile.NamedTemporaryFile(dir=root,prefix='.customer-ui-',delete=False) as temp:
   temp.write(content.encode());temporary=Path(temp.name)
  os.chown(temporary,10001,10001);os.chmod(temporary,0o644);os.replace(temporary,destination)
 assert all(digest((root/name).read_bytes())==expected for name,expected in wanted.items())
assert processes()==running,'The payment worker changed during the update'
print(json.dumps({'app':'wlmd-stripe-test-0f89b1bb','applied':payload['apply'],'worker_unchanged':True,'database_unchanged':state_hashes()==state_before,'asset_hashes':wanted,'legacy_assets_preserved':True,'payment_requests_submitted':0}))
""".replace('__BUNDLE__',repr(bundle))
    result=subprocess.run([str(Path.home()/'.fly/bin/flyctl'),'ssh','console','--app',APP,'--command',shlex.join(['python','-c',code])],capture_output=True,text=True,timeout=90)
    if result.returncode:
        raise SystemExit(result.stderr)
    proof=json.loads(result.stdout)
    if args.apply:(Path('/private/tmp')/'customer-checkout-live-proof.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(proof))


if __name__=='__main__':main()
