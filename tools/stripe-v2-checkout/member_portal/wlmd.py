"""WLMD identity assertions. Never store last-four digits or provider messages."""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from urllib import request
from urllib.parse import quote
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, SecretStr


class IdentityInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    last4: SecretStr


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WLMDClient:
    def available(self):
        return os.environ.get('WLMD_API_URL', '').rstrip('/') == 'https://api.whitelabelmd.com' and bool(os.environ.get('WLMD_AUTHTOKEN'))

    def verify(self, site, order, last4):
        if not self.available():
            return False
        url = 'https://api.whitelabelmd.com/v1/site/' + quote(site, safe='') + '/order/' + quote(order, safe='') + '/identity_ssncheck'
        body = json.dumps({'user': 'laughing-buddha', 'last4': last4}).encode()
        req = request.Request(url, data=body, method='POST', headers={
            'authtoken': os.environ['WLMD_AUTHTOKEN'], 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with request.build_opener(NoRedirect()).open(req, timeout=15) as response:
                raw = response.read(65537)
                if not 200 <= response.status < 300 or len(raw) > 65536:
                    return False
                result = json.loads(raw)
                return isinstance(result, dict) and result.get('status') == 'success'
        except Exception:
            # Provider bodies/exceptions can contain identity information.
            return False


class IdentityChecks:
    def __init__(self, service):
        self.s = service
        self.provider = WLMDClient()
        with service.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS member_identity_checks(
                id TEXT PRIMARY KEY,site_id TEXT NOT NULL,wlmd_site_id TEXT NOT NULL,
                subject TEXT NOT NULL,order_id TEXT NOT NULL,status TEXT NOT NULL,
                created REAL NOT NULL,updated REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS member_identity_subject ON member_identity_checks(site_id,wlmd_site_id,subject,status)')

    def mapping(self, site_id):
        return str((self.s.admin.get('site', site_id) or {}).get('wlmd_site_id') or '')

    def subject(self, order, patient):
        return 'receipt:' + order['order_id'] if patient.get('_reuse_allowed') is False else patient['id']

    def status(self, order, patient):
        site = self.mapping(order['site_id'])
        if not site:
            return {'required': False, 'status': 'not_required', 'verified_at': None, 'available': False}
        subject = self.subject(order, patient)
        with self.s.db() as db:
            # A signed-in, order-granted patient may adopt that receipt's assertion.
            # A guest receipt never reads account-wide verification or other orders.
            if not subject.startswith('receipt:') and db.execute('SELECT 1 FROM member_grants WHERE site_id=? AND order_id=? AND patient_id=?', (order['site_id'], order['order_id'], subject)).fetchone():
                db.execute("INSERT OR IGNORE INTO member_identity_checks SELECT id || ':account',site_id,wlmd_site_id,?,order_id,status,created,updated FROM member_identity_checks WHERE site_id=? AND wlmd_site_id=? AND order_id=? AND subject=? AND status='verified'", (subject, order['site_id'], site, order['order_id'], 'receipt:' + order['order_id']))
            verified = db.execute("SELECT updated FROM member_identity_checks WHERE site_id=? AND wlmd_site_id=? AND subject=? AND status='verified' ORDER BY updated DESC LIMIT 1", (order['site_id'], site, subject)).fetchone()
        return {'required': True, 'status': 'verified' if verified else 'needed',
                'verified_at': datetime.fromtimestamp(verified['updated'], timezone.utc).isoformat() if verified else None,
                'available': bool(self.provider.available())}

    def fact(self, db, order, patient, key, version):
        if key != 'identity.ssn_verified' or version != '1':
            return None
        site = self.mapping(order['site_id'])
        subject = self.subject(order, patient)
        row = db.execute("SELECT updated AS verified_at FROM member_identity_checks WHERE site_id=? AND wlmd_site_id=? AND subject=? AND status='verified' ORDER BY updated DESC LIMIT 1", (order['site_id'], site, subject)).fetchone()
        return row

    def require(self, order, patient):
        result = self.status(order, patient)
        if result['required'] and result['status'] != 'verified':
            if self.s.id_uploads.status(order, patient)['order_attached']:
                return
            raise HTTPException(409, {'code': 'identity_verification_required', 'message': 'Verify your identity to continue your intake.', 'identity': result})

    def verify(self, order, patient, body):
        last4 = body.last4.get_secret_value()
        if not re.fullmatch(r'[0-9]{4}', last4):
            raise HTTPException(422, 'Enter exactly the last four digits of your SSN.')
        current = self.status(order, patient)
        if not current['required'] or current['status'] == 'verified':
            return current
        if not self.provider.available():
            raise HTTPException(503, 'Identity verification is temporarily unavailable. Your order and saved answers are safe. Please try again later.')
        site, subject, now = self.mapping(order['site_id']), self.subject(order, patient), self.s.clock()
        key = (order['site_id'], site, subject)
        with self.s.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Check again under the writer lock: only one call per subject at a time.
            if db.execute("SELECT 1 FROM member_identity_checks WHERE site_id=? AND wlmd_site_id=? AND subject=? AND status='verified'", key).fetchone():
                return {'required': True, 'status': 'verified', 'available': True}
            attempts = db.execute('SELECT status,created FROM member_identity_checks WHERE site_id=? AND wlmd_site_id=? AND (subject=? OR order_id=?) AND created>?', (*key, order['order_id'], now - 900)).fetchall()
            if len(attempts) >= 5 or any(r['created'] > now - 30 for r in attempts):
                raise HTTPException(429, 'Please wait before trying again. After several attempts, wait 15 minutes or contact support.')
            check_id = uuid.uuid4().hex
            db.execute('INSERT INTO member_identity_checks VALUES(?,?,?,?,?,?,?,?)', (check_id, *key, order['order_id'], 'checking', now, now))
        try:
            verified = self.provider.verify(site, order['order_id'], last4) is True
        except Exception:
            verified = False
        finally:
            last4 = ''
        with self.s.db() as db:
            db.execute('UPDATE member_identity_checks SET status=?,updated=? WHERE id=?', ('verified' if verified else 'unconfirmed', self.s.clock(), check_id))
        if not verified:
            raise HTTPException(409, 'We couldn’t confirm your identity. Check your last four digits and try again shortly, or contact support. Your order and saved answers are safe.')
        return self.status(order, patient)

    def account(self, site_id, patient):
        with self.s.db() as db:
            orders = db.execute('SELECT order_id FROM member_grants WHERE site_id=? AND patient_id=?', (site_id, patient['id'])).fetchall()
        chosen = None
        for row in orders:
            order = self.s.order_record(site_id, row['order_id'], patient)
            result = {**self.status(order, patient), 'order_id': row['order_id'], 'id_photo': self.s.id_uploads.status(order, patient)}
            chosen = chosen or result
            if result['status'] == 'verified' or result['id_photo']['saved']:
                return result
        return chosen or {'required': bool(self.mapping(site_id)), 'status': 'no_order', 'available': False, 'verified_at': None, 'order_id': None}
