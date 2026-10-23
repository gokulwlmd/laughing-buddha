"""Private, order-owned ID photo uploads. Uploading is not identity verification."""
import base64
import io
import json
import os
import threading
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib import request
from urllib.parse import quote
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, SecretStr
from PIL import Image, ImageOps
from .wlmd import NoRedirect

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_BODY_BYTES = 7 * 1024 * 1024
IMAGE_WORKERS = threading.BoundedSemaphore(2)


class IDPhotoInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_contents: SecretStr


def normalize_photo(contents):
    """Validate actual image bytes, cap decoding, and discard EXIF/GPS metadata."""
    if len(contents) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise HTTPException(413, 'Choose an image smaller than 5 MB.')
    try:
        raw = base64.b64decode(contents, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('size')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as original:
                if original.width * original.height > 24_000_000 or min(original.size) < 200 or getattr(original, 'n_frames', 1) != 1:
                    raise ValueError('dimensions')
                original.load()
                oriented = ImageOps.exif_transpose(original)
                oriented.thumbnail((2400, 2400))
                clean = Image.new('RGB', oriented.size, 'white')
                rgba = oriented.convert('RGBA')
                clean.paste(rgba, mask=rgba.getchannel('A'))
                output = io.BytesIO()
                clean.save(output, format='JPEG', quality=92)
                return base64.b64encode(output.getvalue()).decode('ascii')
    except Exception:
        raise HTTPException(422, 'Choose a clear JPG, PNG or WebP photo of your ID. The image must be at least 200 pixels on each side.') from None


class UploadProvider:
    def available(self):
        return os.environ.get('WLMD_API_URL', '').rstrip('/') == 'https://api.whitelabelmd.com' and bool(os.environ.get('WLMD_AUTHTOKEN'))

    def parse_result(self, result):
        if not isinstance(result, dict) or result.get('status') != 'success':
            return None
        data = result.get('data')
        if not isinstance(data, dict) or type(data.get('db_id')) is not int or data['db_id'] <= 0 or not isinstance(data.get('s3_key'), str) or not 0 < len(data['s3_key']) <= 2048 or data.get('orders_dictionary_key') != 'FUT:ID':
            return None
        return json.dumps({'db_id': data['db_id'], 's3_key': data['s3_key']})

    def upload(self, site, order, contents):
        url = 'https://api.whitelabelmd.com/v1/site/' + quote(site, safe='') + '/order/' + quote(order, safe='') + '/upload-file-s3'
        payload = {'user': 'laughing-buddha', 'upload_name': 'ID', 'file_name': 'ID.jpg', 'file_ext': 'jpg', 'file_contents': contents}
        req = request.Request(url, data=json.dumps(payload).encode(), method='POST', headers={
            'authtoken': os.environ['WLMD_AUTHTOKEN'], 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with request.build_opener(NoRedirect()).open(req, timeout=25) as response:
                raw = response.read(65537)
                if not 200 <= response.status < 300 or len(raw) > 65536:
                    return None
                return self.parse_result(json.loads(raw))
        except Exception:
            return None


class IDUploads:
    def __init__(self, service):
        self.s = service
        self.provider = UploadProvider()
        key_path = Path(service.cfg.state_dir) / 'member-id-uploads.key'
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as file:
                file.write(Fernet.generate_key())
        self.cipher = Fernet(key_path.read_bytes())
        with service.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS member_id_uploads(
                id TEXT PRIMARY KEY,site_id TEXT NOT NULL,wlmd_site_id TEXT NOT NULL,
                subject TEXT NOT NULL,order_id TEXT NOT NULL,status TEXT NOT NULL,
                reference TEXT,photo TEXT,created REAL NOT NULL,updated REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS member_id_upload_subject ON member_id_uploads(site_id,wlmd_site_id,subject,status)')

    def status(self, order, patient):
        site = self.s.identity_checks.mapping(order['site_id'])
        subject = self.s.identity_checks.subject(order, patient)
        with self.s.db() as db:
            if not subject.startswith('receipt:') and db.execute('SELECT 1 FROM member_grants WHERE site_id=? AND order_id=? AND patient_id=?', (order['site_id'], order['order_id'], subject)).fetchone():
                db.execute("INSERT OR IGNORE INTO member_id_uploads SELECT id || ':account',site_id,wlmd_site_id,?,order_id,status,reference,photo,created,updated FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND order_id=? AND subject=? AND status='uploaded'", (subject, order['site_id'], site, order['order_id'], 'receipt:' + order['order_id']))
            saved = db.execute("SELECT updated,order_id FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND subject=? AND status='uploaded' ORDER BY updated DESC LIMIT 1", (order['site_id'], site, subject)).fetchone()
            attached = db.execute("SELECT 1 FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND subject=? AND order_id=? AND status='uploaded'", (order['site_id'], site, subject, order['order_id'])).fetchone()
            pending = db.execute("SELECT 1 FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND subject=? AND order_id=? AND status IN ('sending','unconfirmed')", (order['site_id'], site, subject, order['order_id'])).fetchone()
        return {'status': 'uploaded' if attached else 'needs_review' if pending else 'uploaded' if saved else 'needed', 'order_attached': bool(attached), 'saved': bool(saved),
                'uploaded_at': datetime.fromtimestamp(saved['updated'], timezone.utc).isoformat() if saved else None,
                'alternative_to_ssn': bool(site),
                'available': bool(site) and self.provider.available(), 'order_id': order['order_id']}

    def upload(self, order, patient, body=None):
        current = self.status(order, patient)
        if current['order_attached']:
            return current
        if not current['available']:
            raise HTTPException(503, 'ID uploads are temporarily unavailable. Your order and saved answers are safe.')
        if not IMAGE_WORKERS.acquire(blocking=False):
            raise HTTPException(429, 'Please try again in a moment.')
        try:
            site = self.s.identity_checks.mapping(order['site_id'])
            subject = self.s.identity_checks.subject(order, patient)
            key = (order['site_id'], site, subject)
            if body is None:
                # Only authenticated, same-site account assertions can supply a
                # saved photo to a different order. Never merge by email.
                with self.s.db() as db:
                    saved = db.execute("SELECT photo FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND subject=? AND status IN ('uploaded','unconfirmed','sending') AND photo IS NOT NULL ORDER BY updated DESC LIMIT 1", key).fetchone()
                if not saved:
                    raise HTTPException(409, 'Add a photo of your ID first.')
                try:
                    contents = self.cipher.decrypt(saved['photo'].encode()).decode()
                except Exception:
                    raise HTTPException(503, 'Your saved ID could not be opened. Please contact support.') from None
            else:
                contents = normalize_photo(body.file_contents.get_secret_value())
            now, upload_id = self.s.clock(), uuid.uuid4().hex
            with self.s.db() as db:
                db.execute('BEGIN IMMEDIATE')
                attempts = db.execute("SELECT created FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND order_id=? AND created>?", (order['site_id'], site, order['order_id'], now - 900)).fetchall()
                if len(attempts) >= 5 or any(row['created'] > now - 30 for row in attempts):
                    raise HTTPException(429, 'Please wait a moment before retrying your upload. After several attempts, wait 15 minutes.')
                if db.execute("SELECT 1 FROM member_id_uploads WHERE site_id=? AND wlmd_site_id=? AND order_id=? AND status='uploaded'", (order['site_id'], site, order['order_id'])).fetchone():
                    raise HTTPException(409, 'An ID photo has already been submitted. Refresh its status before continuing.')
                db.execute('INSERT INTO member_id_uploads VALUES(?,?,?,?,?,?,?,?,?,?)', (upload_id, *key, order['order_id'], 'sending', None, self.cipher.encrypt(contents.encode()).decode(), now, now))
            try:
                reference = self.provider.upload(site, order['order_id'], contents)
            except Exception:
                reference = None
            finally:
                contents = ''
            confirmed = isinstance(reference, str) and 0 < len(reference) <= 4096
            with self.s.db() as db:
                db.execute('UPDATE member_id_uploads SET status=?,reference=?,updated=? WHERE id=?',
                    ('uploaded' if confirmed else 'unconfirmed', self.cipher.encrypt(reference.encode()).decode() if confirmed else None, self.s.clock(), upload_id))
            if not confirmed:
                raise HTTPException(409, 'We couldn’t confirm your upload. Your photo is saved securely. You can retry it in a moment; your order and intake answers are safe.')
            return self.status(order, patient)
        finally:
            IMAGE_WORKERS.release()
