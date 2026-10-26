"""Sticky-owned member credentials. Receipt-bound bootstrap; no email/reset writes.

Official JSON Members API inspected 2026-10-24. API credentials and bootstrap
passwords never reach browsers. Provider write uncertainty is durable and fails
closed. Existing members must authenticate; a receipt cannot reset a password.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import weakref
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException


class StickyIdentity:
    def __init__(self, service):
        self.service = service
        self.guard = threading.Lock()
        self.locks = weakref.WeakValueDictionary()
        key_path = Path(service.cfg.state_dir) / 'member-identity.key'
        # The same private volume backs the encrypted records and key. Back up
        # both; the key is excluded from the image, repository and API responses.
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(Fernet.generate_key())
        self.cipher = Fernet(key_path.read_bytes())
        with service.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS member_identity_bootstrap(
                    email_hash TEXT PRIMARY KEY,site_id TEXT NOT NULL,order_id TEXT NOT NULL,
                    state TEXT NOT NULL,secret TEXT,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS member_identity_sessions(
                    session_hash TEXT PRIMARY KEY,secret TEXT NOT NULL,checked REAL NOT NULL);
            """)

    def lock_for(self, identity):
        with self.guard:
            lock = self.locks.get(identity)
            if lock is None:
                lock = threading.RLock()
                self.locks[identity] = lock
            return lock

    def encrypt(self, value):
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value):
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except (InvalidToken, AttributeError):
            raise HTTPException(401, 'Please sign in again.') from None

    def call(self, method, body):
        try:
            result = self.service.admin.api.call('POST', '/api/v1/' + method, body)
        except Exception:
            raise HTTPException(502, 'Member account service is unavailable. Your purchase is saved.') from None
        if not isinstance(result, dict):
            raise HTTPException(502, 'Member account service returned an unexpected response.')
        return result

    def view(self, email):
        result = self.call('member_view', {'email': email})
        code = str(result.get('response_code'))
        if code in ('4001', '4003'):
            return None
        if code != '100' or not isinstance(result.get('data'), dict):
            raise HTTPException(502, 'Member account access could not be verified.')
        return result['data']

    @staticmethod
    def ids(member):
        return {str(i) for i in [member.get('customer_id'), *(member.get('customer_ids') or [])] if i is not None}

    def login(self, email, password, customer_id=None):
        result = self.call('member_login', {'email': email, 'member_password': password})
        if str(result.get('response_code')) != '100':
            raise HTTPException(401, 'Use your existing Sticky member password. This purchase cannot reset it.')
        member = result.get('data') or {}
        if str(member.get('email', '')).strip().lower() != email or not member.get('member_token'):
            raise HTTPException(502, 'Member identity could not be verified.')
        if customer_id is not None and str(customer_id) not in self.ids(member):
            raise HTTPException(409, 'This order is not linked to that Sticky member. Please contact support.')
        return member

    def setup_state(self, email, site_id, order_id):
        key = hashlib.sha256(email.encode()).hexdigest()
        with self.service.db() as db:
            row = db.execute('SELECT * FROM member_identity_bootstrap WHERE email_hash=?', (key,)).fetchone()
        if row and row['site_id'] == site_id and row['order_id'] == order_id:
            if row['state'] in ('created', 'updating') and row['secret']:
                return 'set_password'
            if row['state'] == 'creating':
                return 'needs_review'
        return 'sign_in' if self.view(email) else 'set_password'

    def setup(self, email, password, site_id, order_id, customer_id):
        key = hashlib.sha256(email.encode()).hexdigest()
        with self.lock_for(email):
            with self.service.db() as db:
                row = db.execute('SELECT * FROM member_identity_bootstrap WHERE email_hash=?', (key,)).fetchone()
            if row and (row['site_id'] != site_id or row['order_id'] != order_id):
                return self.login(email, password, customer_id)
            if row and row['state'] == 'creating':
                raise HTTPException(409, 'Account setup needs review. Your order is saved; no password was reset.')
            if not row:
                if self.view(email) is not None:
                    return self.login(email, password, customer_id)
                with self.service.db() as db:
                    db.execute('INSERT INTO member_identity_bootstrap VALUES(?,?,?,?,?,?)',
                               (key, site_id, order_id, 'creating', None, self.service.clock()))
                # Omit event_id: no membership email is requested. Never retry an
                # ambiguous creation or regenerate credentials for an existing member.
                result = self.call('member_create', {'email': email, 'customer_id': customer_id})
                secret = result.get('temp_password')
                if str(result.get('response_code')) != '100' or not isinstance(secret, str) or not secret:
                    raise HTTPException(409, 'Account setup needs review. Your purchase is saved.')
                with self.service.db() as db:
                    db.execute("UPDATE member_identity_bootstrap SET state='created',secret=? WHERE email_hash=?",
                               (self.encrypt(secret), key))
                    row = db.execute('SELECT * FROM member_identity_bootstrap WHERE email_hash=?', (key,)).fetchone()
            if row['state'] == 'ready':
                return self.login(email, password, customer_id)
            if row['state'] == 'updating':
                # A previous response may have been lost. Read through login;
                # never replay a password-changing write after uncertainty.
                member = self.login(email, password, customer_id)
            else:
                if len(password) < 12:
                    raise HTTPException(422, 'Use at least 12 characters for your new password.')
                with self.service.db() as db:
                    db.execute("UPDATE member_identity_bootstrap SET state='updating' WHERE email_hash=?", (key,))
                result = self.call('member_update', {'email': email,
                    'current_member_password': self.decrypt(row['secret']), 'new_member_password': password})
                if str(result.get('response_code')) != '100':
                    # Explicit invalid-password rejection guarantees no update.
                    if str(result.get('response_code')) == '4009':
                        with self.service.db() as db:
                            db.execute("UPDATE member_identity_bootstrap SET state='created' WHERE email_hash=?", (key,))
                        raise HTTPException(422, 'Sticky could not accept that password. Choose a stronger password.')
                    raise HTTPException(409, 'Password setup needs review. Your purchase is saved.')
                member = self.login(email, password, customer_id)
            with self.service.db() as db:
                db.execute("UPDATE member_identity_bootstrap SET state='ready',secret=NULL WHERE email_hash=?", (key,))
            return member

    def save_session(self, session_hash, member):
        try:
            expires = datetime.fromisoformat(member['token_expires_at'].replace('Z', '+00:00'))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            expires = expires.timestamp()
        except (KeyError, ValueError, TypeError):
            raise HTTPException(502, 'Member session expiration could not be verified.') from None
        if expires <= self.service.clock():
            raise HTTPException(401, 'Your member session expired. Please sign in again.')
        with self.service.db() as db:
            db.execute('DELETE FROM member_identity_sessions WHERE session_hash NOT IN (SELECT token_hash FROM member_sessions) AND checked<=?', (self.service.clock(),))
            db.execute('INSERT INTO member_identity_sessions VALUES(?,?,?)',
                       (session_hash, self.encrypt(member['member_token']), self.service.clock()))
            db.execute('UPDATE member_sessions SET expires=MIN(expires,?) WHERE token_hash=?', (expires, session_hash))
        return expires

    def check_session(self, session_hash, force=False):
        with self.lock_for(session_hash):
            with self.service.db() as db:
                row = db.execute('SELECT * FROM member_identity_sessions WHERE session_hash=?', (session_hash,)).fetchone()
            if not row:
                raise HTTPException(401, 'Please sign in with your Sticky member password.')
            if not force and self.service.clock() - row['checked'] < 30:
                return
            result = self.call('member_check_session', {'token': self.decrypt(row['secret'])})
            if str(result.get('response_code')) != '100':
                with self.service.db() as db:
                    db.execute('DELETE FROM member_sessions WHERE token_hash=?', (session_hash,))
                    db.execute('DELETE FROM member_identity_sessions WHERE session_hash=?', (session_hash,))
                raise HTTPException(401, 'Your member session expired. Please sign in again.')
            with self.service.db() as db:
                db.execute('UPDATE member_identity_sessions SET checked=? WHERE session_hash=?', (self.service.clock(), session_hash))

    def logout(self, session_hash):
        with self.service.db() as db:
            row = db.execute('SELECT secret FROM member_identity_sessions WHERE session_hash=?', (session_hash,)).fetchone()
            db.execute('DELETE FROM member_identity_sessions WHERE session_hash=?', (session_hash,))
            db.execute('DELETE FROM member_sessions WHERE token_hash=?', (session_hash,))
        if row:
            self.call('member_logout', {'token': self.decrypt(row['secret'])})
