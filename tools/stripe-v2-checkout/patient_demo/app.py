"""Durable, site-scoped patient portal demo with no payment or clinical integrations.

Every visitor gets a separate, expiring synthetic workspace. No production state,
processor credential, medical approval, or real doctor is used by this module.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .provider import SITES, THERAPIES, get_template

HERE = Path(__file__).parent
TTL_SECONDS = 24 * 60 * 60
MAX_BODY_BYTES = 65536
MAX_ACTIVE_WORKSPACES = 1000
MAX_MESSAGES = 200
bearer = HTTPBearer(auto_error=False, description='Site-specific patient or admin demo token returned by POST /api/demo/workspaces. Never use processor credentials.')


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class WorkspaceRequest(StrictBody):
    pass


class IntakePatch(StrictBody):
    revision: StrictInt = Field(ge=0)
    answers: dict = Field(default_factory=dict, max_length=100, description='Partial map of known template question IDs to typed answers. Text is limited to 1000 characters. null clears an answer.')
    current_step: StrictInt | None = Field(default=None, ge=0, le=100, description='Zero-based template section index to resume.')


class IntakeSubmit(StrictBody):
    revision: StrictInt = Field(ge=0)


class MessageBody(StrictBody):
    body: str = Field(min_length=1, max_length=2000)
    client_message_id: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')



AnswerValue = str | int | float | list[str]


class SiteModel(BaseModel):
    id: str
    name: str
    color: str


class WorkspaceSite(SiteModel):
    patient_token: str = Field(description='Opaque patient bearer token. Store only in this browser session; never put in a URL.')
    admin_token: str = Field(description='Opaque admin demo bearer token for this site. Demo-only role switch, not production authorization.')


class WorkspaceResponse(BaseModel):
    workspace_id: str
    expires_at: str
    sites: list[WorkspaceSite]
    demo: bool


class TherapyModel(BaseModel):
    id: str
    name: str


class ConfigurationResponse(BaseModel):
    site: SiteModel
    therapies: list[TherapyModel]
    demo: bool


class PatientModel(BaseModel):
    id: str
    name: str
    email: str


class MeResponse(BaseModel):
    site: SiteModel
    patient: PatientModel
    demo: bool


class OrderModel(BaseModel):
    id: str
    number: str
    site_id: str
    therapy_id: str
    therapy_name: str
    product_name: str
    sku: str
    plan_name: str
    total: str = Field(description='Exact display total in currency major units; this is a synthetic paid order.')
    currency: str
    payment_status: Literal['paid_demo']
    intake_status: Literal['not_started', 'draft', 'submitted']
    medical_status: Literal['not_submitted', 'awaiting_review']
    fulfillment_status: Literal['not_started']
    created_at: str
    demo: bool


class OrdersResponse(BaseModel):
    orders: list[OrderModel]
    demo: bool


class IntakeSection(BaseModel):
    id: str
    title: str
    description: str


class QuestionOption(BaseModel):
    value: str
    label: str


class QuestionCondition(BaseModel):
    question_id: str
    equals: AnswerValue


class IntakeQuestion(BaseModel):
    id: str
    section_id: str
    type: Literal['text', 'textarea', 'number', 'single_choice', 'multi_choice']
    label: str
    hint: str | None = None
    required: bool
    options: list[QuestionOption] | None = None
    show_if: QuestionCondition | None = None
    sample: AnswerValue | None = None
    reuse_key: str | None = None
    reuse_version: str | None = None
    reuse_policy: Literal['stable', 'confirm', 'verified', 'never'] | None = None
    reuse_max_age_days: int | None = None
    reuse_status: Literal['stable', 'confirm', 'verified'] | None = None
    saved_value: AnswerValue | None = None
    saved_at: float | None = None


class IntakeTemplate(BaseModel):
    id: str
    version: str
    title: str
    description: str
    sections: list[IntakeSection]
    questions: list[IntakeQuestion]
    demo: bool


class IntakeResponse(BaseModel):
    id: str
    order_id: str
    therapy_id: str
    status: Literal['draft', 'submitted']
    revision: int
    answers: dict[str, AnswerValue]
    current_step: int = Field(description='Zero-based index into template.sections.')
    updated_at: str
    submitted_at: str | None
    template: IntakeTemplate
    reused_fields: list[str]


class MessageModel(BaseModel):
    id: str
    sender: Literal['patient', 'demo_assistant']
    body: str
    created_at: str
    client_message_id: str
    automated: bool
    demo: bool


class MessagesResponse(BaseModel):
    messages: list[MessageModel]
    demo: bool
    provider_connected: Literal[False]


class IntakeSummary(BaseModel):
    id: str
    order_id: str
    patient_name: str
    therapy_id: str
    therapy_name: str
    status: Literal['draft', 'submitted']
    answered: int
    total: int
    updated_at: str


class LeadModel(BaseModel):
    id: str
    name: str
    email: str
    therapy_id: str
    therapy_name: str
    stage: Literal['prequalification_incomplete']
    progress: int
    updated_at: str
    demo: bool


class OverviewCounts(BaseModel):
    orders: int
    paid_orders: int
    intake_drafts: int
    intakes_submitted: int
    partial_leads: int


class OverviewResponse(BaseModel):
    site: SiteModel
    orders: list[OrderModel]
    intakes: list[IntakeSummary]
    leads: list[LeadModel]
    summaries: OverviewCounts
    demo: bool


class BoundedRequestBody:
    """Bound chunked as well as Content-Length bodies before parsing JSON."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PATCH', 'PUT'):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get('headers', []))
        declared = headers.get(b'content-length')
        if declared and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
            await JSONResponse({'detail': 'Request body is too large'}, status_code=413)(scope, receive, send)
            return
        chunks = []
        length = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            length += len(chunk)
            if length > MAX_BODY_BYTES:
                await JSONResponse({'detail': 'Request body is too large'}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, buffered_receive, send)

def iso(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace('+00:00', 'Z')


def encoded(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def opaque(prefix):
    return prefix + '_' + secrets.token_urlsafe(18)


def token_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def visible(question, answers):
    condition = question.get('show_if')
    return not condition or answers.get(condition['question_id']) == condition['equals']


def clean_answers(template, incoming):
    known = {q['id']: q for q in template['questions']}
    cleaned = {}
    for key, value in incoming.items():
        question = known.get(key)
        if question is None:
            raise HTTPException(422, 'Unknown intake question')
        if value is None:
            cleaned[key] = None
            continue
        kind = question['type']
        if kind in ('text', 'textarea'):
            valid = isinstance(value, str) and len(value) <= 1000
        elif kind == 'number':
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) <= 1000000 and math.isfinite(value)
        elif kind == 'single_choice':
            valid = isinstance(value, str) and value in {o['value'] for o in question.get('options', [])}
        elif kind == 'multi_choice':
            valid = (isinstance(value, list) and len(value) <= 50 and all(isinstance(v, str) for v in value)
                     and len(set(value)) == len(value) and set(value) <= {o['value'] for o in question.get('options', [])})
        else:
            valid = False
        if not valid:
            raise HTTPException(422, 'Invalid answer for intake question: ' + key)
        cleaned[key] = value.strip() if isinstance(value, str) else value
    return cleaned


def create_app(state_dir=None, clock=time.time):
    """Create an app whose SQLite database is independent from checkout storage."""
    directory = Path(state_dir or os.environ.get('PATIENT_DEMO_STATE_DIR', '/tmp/laughing-buddha-patient-demo'))
    directory.mkdir(parents=True, exist_ok=True)
    # This argument is the dedicated demo-state directory, never the checkout DB directory.
    directory.chmod(0o700)
    database = directory / 'patient-demo.sqlite3'

    @contextmanager
    def connect():
        db = sqlite3.connect(database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with connect() as db:
        db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY, created_at REAL NOT NULL, expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tokens (
                digest TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                site_id TEXT NOT NULL, role TEXT NOT NULL, patient_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                site_id TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                site_id TEXT NOT NULL, patient_id TEXT NOT NULL, therapy_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intakes (
                id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
                status TEXT NOT NULL, revision INTEGER NOT NULL, answers TEXT NOT NULL,
                current_step INTEGER NOT NULL, template TEXT NOT NULL, updated_at REAL NOT NULL,
                submitted_at REAL, submitted_answers TEXT, reused_fields TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                site_id TEXT NOT NULL, patient_id TEXT NOT NULL, sender TEXT NOT NULL,
                body TEXT NOT NULL, created_at REAL NOT NULL, client_message_id TEXT,
                UNIQUE(workspace_id, site_id, patient_id, client_message_id, sender)
            );
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                site_id TEXT NOT NULL, therapy_id TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS orders_scope ON orders(workspace_id,site_id,patient_id);
            CREATE INDEX IF NOT EXISTS messages_scope ON messages(workspace_id,site_id,patient_id);
        ''')
        db.commit()
    try:
        database.chmod(0o600)
    except OSError:
        pass

    app = FastAPI(title='Patient portal demo', version='0.1.0-demo', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.database = database
    app.add_middleware(BoundedRequestBody)

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default error includes the original submitted answer/body.
        return JSONResponse({'detail': 'Invalid request fields'}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return JSONResponse({'detail': 'Demo data is temporarily unavailable. Please retry.'}, status_code=503)

    def site(site_id):
        value = SITES.get(site_id)
        if value is None:
            raise HTTPException(404, 'Site not found')
        return {'id': site_id, **value}

    def auth(site_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        site(site_id)
        if not credentials or len(credentials.credentials) > 200:
            raise HTTPException(401, 'A site-specific demo token is required', headers={'WWW-Authenticate': 'Bearer'})
        with connect() as db:
            row = db.execute('SELECT t.*, w.expires_at FROM tokens t JOIN workspaces w ON w.id=t.workspace_id WHERE t.digest=?',
                             (token_digest(credentials.credentials),)).fetchone()
        if not row or row['expires_at'] <= clock():
            raise HTTPException(401, 'Demo session is invalid or expired', headers={'WWW-Authenticate': 'Bearer'})
        if row['site_id'] != site_id:
            raise HTTPException(403, 'This token does not have access to this site')
        return dict(row)

    def patient_auth(scope=Depends(auth)):
        if scope['role'] != 'patient':
            raise HTTPException(403, 'A patient token is required')
        return scope

    def admin_auth(scope=Depends(auth)):
        if scope['role'] != 'admin':
            raise HTTPException(403, 'An admin token is required')
        return scope

    def order_record(db, scope, order_id):
        row = db.execute('SELECT * FROM orders WHERE id=? AND workspace_id=? AND site_id=? AND patient_id=?',
                         (order_id, scope['workspace_id'], scope['site_id'], scope['patient_id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Order not found')
        return row

    def serialize_order(db, row):
        result = json.loads(row['payload'])
        intake = db.execute('SELECT status FROM intakes WHERE order_id=?', (row['id'],)).fetchone()
        result['intake_status'] = intake['status'] if intake else 'not_started'
        result['medical_status'] = 'awaiting_review' if intake and intake['status'] == 'submitted' else 'not_submitted'
        return result

    def get_draft(db, order):
        row = db.execute('SELECT * FROM intakes WHERE order_id=?', (order['id'],)).fetchone()
        if row:
            return row
        template = get_template(order['therapy_id'])
        db.execute('INSERT INTO intakes (id,order_id,status,revision,answers,current_step,template,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   (opaque('intake'), order['id'], 'draft', 0, '{}', 0, encoded(template), clock()))
        return db.execute('SELECT * FROM intakes WHERE order_id=?', (order['id'],)).fetchone()

    def serialize_intake(row, therapy_id):
        return {'id': row['id'], 'order_id': row['order_id'], 'therapy_id': therapy_id, 'status': row['status'],
                'revision': row['revision'], 'answers': json.loads(row['answers']), 'current_step': int(row['current_step']),
                'updated_at': iso(row['updated_at']), 'submitted_at': iso(row['submitted_at']) if row['submitted_at'] else None,
                'template': json.loads(row['template']), 'reused_fields': json.loads(row['reused_fields'])}

    def check_revision(row, revision):
        if row['status'] == 'submitted':
            raise HTTPException(409, 'This intake has already been submitted and cannot be edited')
        if row['revision'] != revision:
            raise HTTPException(409, {'code': 'revision_conflict', 'message': 'This intake changed. Reload before saving.', 'current_revision': row['revision']})

    @app.post('/api/demo/workspaces', status_code=201, response_model=WorkspaceResponse, tags=['Demo setup'])
    def create_workspace(body: WorkspaceRequest, request: Request):
        """Create isolated synthetic records and patient/admin demo tokens lasting 24 hours. This is not production registration."""
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Open the demo on its own origin to create a workspace')
        now = clock()
        workspace_id = opaque('workspace')
        result_sites = []
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM workspaces WHERE expires_at<=?', (now,))
            if db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0] >= MAX_ACTIVE_WORKSPACES:
                raise HTTPException(429, 'Demo workspace capacity reached. Please try again later.')
            db.execute('INSERT INTO workspaces VALUES (?,?,?)', (workspace_id, now, now + TTL_SECONDS))
            for index, site_id in enumerate(SITES):
                patient_id = opaque('patient')
                name = 'Alex Demo' if index == 0 else 'Jordan Demo'
                db.execute('INSERT INTO patients VALUES (?,?,?,?,?)', (patient_id, workspace_id, site_id, name, f'patient-{index + 1}@example.invalid'))
                tokens = {role: secrets.token_urlsafe(32) for role in ('patient', 'admin')}
                for role, token in tokens.items():
                    db.execute('INSERT INTO tokens VALUES (?,?,?,?,?)', (token_digest(token), workspace_id, site_id, role, patient_id))
                result_sites.append({**site(site_id), 'patient_token': tokens['patient'], 'admin_token': tokens['admin']})
                for order_index, (therapy_id, therapy) in enumerate(THERAPIES.items()):
                    order_id = opaque('order')
                    order = {'id': order_id, 'number': f'DEMO-{index + 1}{order_index + 1}01', 'site_id': site_id,
                             'therapy_id': therapy_id, 'therapy_name': therapy['name'], 'product_name': therapy['product_name'],
                             'sku': therapy['sku'], 'plan_name': therapy['plan_name'], 'total': therapy['total'],
                             'currency': therapy.get('currency', 'USD'), 'payment_status': 'paid_demo',
                             'intake_status': 'not_started', 'medical_status': 'not_submitted', 'fulfillment_status': 'not_started',
                             'created_at': iso(now - order_index * 3600), 'demo': True}
                    db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?)', (order_id, workspace_id, site_id, patient_id, therapy_id, encoded(order)))
                for lead_index, therapy_id in enumerate(list(THERAPIES)[:2]):
                    lead_id = opaque('lead')
                    lead = {'id': lead_id, 'name': f'Sample lead {lead_index + 1}', 'email': f'lead-{lead_index + 1}@example.invalid',
                            'therapy_id': therapy_id, 'therapy_name': THERAPIES[therapy_id]['name'], 'stage': 'prequalification_incomplete',
                            'progress': 25 + 25 * lead_index, 'updated_at': iso(now - 600 * (lead_index + 1)), 'demo': True}
                    db.execute('INSERT INTO leads VALUES (?,?,?,?,?)', (lead_id, workspace_id, site_id, therapy_id, encoded(lead)))
            db.commit()
        return {'workspace_id': workspace_id, 'expires_at': iso(now + TTL_SECONDS), 'sites': result_sites, 'demo': True}

    @app.get('/api/v1/sites/{site_id}/configuration', response_model=ConfigurationResponse, tags=['Configuration'])
    def configuration(site_id: str):
        return {'site': site(site_id), 'therapies': [{'id': key, 'name': value['name']} for key, value in THERAPIES.items()], 'demo': True}

    @app.get('/api/v1/sites/{site_id}/me', response_model=MeResponse, tags=['Patient'])
    def me(site_id: str, scope=Depends(patient_auth)):
        with connect() as db:
            row = db.execute('SELECT id,name,email FROM patients WHERE id=? AND workspace_id=? AND site_id=?',
                             (scope['patient_id'], scope['workspace_id'], site_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Patient not found')
        return {'site': site(site_id), 'patient': dict(row), 'demo': True}

    def list_orders(db, scope, therapy_id=None):
        query = 'SELECT * FROM orders WHERE workspace_id=? AND site_id=?'
        params = [scope['workspace_id'], scope['site_id']]
        if scope['role'] == 'patient':
            query += ' AND patient_id=?'
            params.append(scope['patient_id'])
        if therapy_id:
            if therapy_id not in THERAPIES:
                raise HTTPException(422, 'Unknown therapy')
            query += ' AND therapy_id=?'
            params.append(therapy_id)
        return [serialize_order(db, row) for row in db.execute(query + ' ORDER BY rowid', params).fetchall()]

    @app.get('/api/v1/sites/{site_id}/orders', response_model=OrdersResponse, tags=['Orders'])
    def orders(site_id: str, therapy_id: str | None = None, scope=Depends(auth)):
        with connect() as db:
            return {'orders': list_orders(db, scope, therapy_id), 'demo': True}

    @app.get('/api/v1/sites/{site_id}/intakes/{order_id}', response_model=IntakeResponse, tags=['Intake'])
    def intake(site_id: str, order_id: str, scope=Depends(patient_auth)):
        """Get a resumable draft and its versioned backend question template. Creates a draft on first access."""
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            order = order_record(db, scope, order_id)
            result = serialize_intake(get_draft(db, order), order['therapy_id'])
            db.commit()
            return result

    @app.patch('/api/v1/sites/{site_id}/intakes/{order_id}', response_model=IntakeResponse, tags=['Intake'])
    def save_intake(site_id: str, order_id: str, body: IntakePatch, scope=Depends(patient_auth)):
        """Merge valid answers and save progress. Pass the last revision; stale writes return 409. Submitted answers cannot be overwritten."""
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            order = order_record(db, scope, order_id)
            row = get_draft(db, order)
            check_revision(row, body.revision)
            template = json.loads(row['template'])
            answers = json.loads(row['answers'])
            patch = clean_answers(template, body.answers)
            for key, value in patch.items():
                if value is None:
                    answers.pop(key, None)
                else:
                    answers[key] = value
            step = int(row['current_step']) if body.current_step is None else body.current_step
            if step < 0 or step >= len(template.get('sections', [])):
                raise HTTPException(422, 'Unknown intake step')
            db.execute('UPDATE intakes SET answers=?,current_step=?,revision=revision+1,updated_at=? WHERE id=?',
                       (encoded(answers), step, clock(), row['id']))
            updated = db.execute('SELECT * FROM intakes WHERE id=?', (row['id'],)).fetchone()
            db.commit()
            return serialize_intake(updated, order['therapy_id'])

    @app.post('/api/v1/sites/{site_id}/intakes/{order_id}/submit', response_model=IntakeResponse, tags=['Intake'])
    def submit_intake(site_id: str, order_id: str, body: IntakeSubmit, scope=Depends(patient_auth)):
        """Freeze complete answers for the demonstration review queue. No eligibility, prescription, provider transmission, or medical approval occurs."""
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            order = order_record(db, scope, order_id)
            row = get_draft(db, order)
            check_revision(row, body.revision)
            template = json.loads(row['template'])
            answers = json.loads(row['answers'])
            active_questions = [q for q in template['questions'] if visible(q, answers)]
            missing = [q['id'] for q in active_questions if q.get('required') and answers.get(q['id']) in (None, '', [])]
            if missing:
                raise HTTPException(422, {'code': 'required_answers_missing', 'question_ids': missing})
            snapshot = {q['id']: answers[q['id']] for q in active_questions if q['id'] in answers}
            now = clock()
            db.execute('UPDATE intakes SET status=?,revision=revision+1,answers=?,submitted_answers=?,updated_at=?,submitted_at=? WHERE id=?',
                       ('submitted', encoded(snapshot), encoded(snapshot), now, now, row['id']))
            updated = db.execute('SELECT * FROM intakes WHERE id=?', (row['id'],)).fetchone()
            db.commit()
            return serialize_intake(updated, order['therapy_id'])

    def serialized_messages(db, scope):
        rows = db.execute('SELECT id,sender,body,created_at,client_message_id FROM messages WHERE workspace_id=? AND site_id=? AND patient_id=? ORDER BY created_at,rowid',
                          (scope['workspace_id'], scope['site_id'], scope['patient_id'])).fetchall()
        return [{**dict(row), 'created_at': iso(row['created_at']), 'automated': row['sender'] == 'demo_assistant', 'demo': True} for row in rows]

    @app.get('/api/v1/sites/{site_id}/messages', response_model=MessagesResponse, tags=['Messages'])
    def messages(site_id: str, scope=Depends(patient_auth)):
        with connect() as db:
            return {'messages': serialized_messages(db, scope), 'demo': True, 'provider_connected': False}

    @app.post('/api/v1/sites/{site_id}/messages', response_model=MessagesResponse, tags=['Messages'])
    def send_message(site_id: str, body: MessageBody, scope=Depends(patient_auth)):
        """Save a demo message once per client_message_id. The response is explicitly automated; no clinician receives it."""
        text = body.body.strip()
        if not text:
            raise HTTPException(422, 'Write a message before sending')
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT body FROM messages WHERE workspace_id=? AND site_id=? AND patient_id=? AND client_message_id=? AND sender=?',
                                  (scope['workspace_id'], site_id, scope['patient_id'], body.client_message_id, 'patient')).fetchone()
            if existing and existing['body'] != text:
                raise HTTPException(409, 'This message ID was already used with different content')
            if not existing:
                count = db.execute('SELECT COUNT(*) FROM messages WHERE workspace_id=? AND site_id=? AND patient_id=?',
                                   (scope['workspace_id'], site_id, scope['patient_id'])).fetchone()[0]
                if count >= MAX_MESSAGES:
                    raise HTTPException(429, 'Demo message limit reached')
                now = clock()
                for sender, content in [('patient', text), ('demo_assistant', 'Automated demo acknowledgement: your sample message was saved. No doctor has received or reviewed it. Clinical messaging will be connected through the future provider API.')]:
                    db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)', (opaque('message'), scope['workspace_id'], site_id,
                               scope['patient_id'], sender, content, now, body.client_message_id))
            result = serialized_messages(db, scope)
            db.commit()
        return {'messages': result, 'demo': True, 'provider_connected': False}

    @app.get('/api/v1/sites/{site_id}/admin/overview', response_model=OverviewResponse, tags=['Admin'])
    def overview(site_id: str, therapy_id: str | None = None, scope=Depends(admin_auth)):
        """Site-scoped operational view. Intake summaries expose progress, not medical answers."""
        with connect() as db:
            order_list = list_orders(db, scope, therapy_id)
            intake_list = []
            for order in order_list:
                row = db.execute('SELECT i.*,p.name AS patient_name FROM intakes i JOIN orders o ON o.id=i.order_id JOIN patients p ON p.id=o.patient_id WHERE i.order_id=?',
                                 (order['id'],)).fetchone()
                if not row:
                    continue
                answers = json.loads(row['answers'])
                questions = [q for q in json.loads(row['template'])['questions'] if visible(q, answers)]
                intake_list.append({'id': row['id'], 'order_id': row['order_id'], 'patient_name': row['patient_name'],
                                    'therapy_id': order['therapy_id'], 'therapy_name': order['therapy_name'], 'status': row['status'],
                                    'answered': sum(answers.get(q['id']) not in (None, '', []) for q in questions), 'total': len(questions),
                                    'updated_at': iso(row['updated_at'])})
            lead_list = [json.loads(row['payload']) for row in db.execute('SELECT * FROM leads WHERE workspace_id=? AND site_id=? ORDER BY rowid',
                         (scope['workspace_id'], site_id)).fetchall() if not therapy_id or row['therapy_id'] == therapy_id]
        return {'site': site(site_id), 'orders': order_list, 'intakes': intake_list, 'leads': lead_list,
                'summaries': {'orders': len(order_list), 'paid_orders': len(order_list), 'intake_drafts': sum(i['status'] == 'draft' for i in intake_list),
                              'intakes_submitted': sum(i['status'] == 'submitted' for i in intake_list), 'partial_leads': len(lead_list)}, 'demo': True}

    @app.get('/sites/{site_id}/openapi.json', include_in_schema=False)
    def openapi(site_id: str):
        current_site = site(site_id)
        schema = get_openapi(title=current_site['name'] + ' · Patient portal demo API', version='0.1.0-demo', routes=app.routes,
                             description='Synthetic, isolated 24-hour workspaces. All patient/admin endpoints require the matching site and role bearer token. No real payments, doctors, prescriptions, or fulfillment. Create a demo workspace to obtain tokens. Production patient authentication is not implemented by this demo.')
        paths = {}
        for path, operations in schema['paths'].items():
            if path == '/api/demo/workspaces':
                paths[path] = operations
            elif path.startswith('/api/v1/sites/{site_id}/'):
                for operation in operations.values():
                    operation['parameters'] = [p for p in operation.get('parameters', []) if p.get('name') != 'site_id']
                paths[path.replace('{site_id}', site_id)] = operations
        schema['paths'] = paths
        schema['servers'] = [{'url': '/'}]
        return schema

    @app.get('/sites/{site_id}/docs', include_in_schema=False)
    def docs(site_id: str):
        current_site = site(site_id)
        return get_swagger_ui_html(openapi_url=f'/sites/{site_id}/openapi.json', title=current_site['name'] + ' · Patient API docs',
                                  swagger_favicon_url='data:,', swagger_ui_parameters={'persistAuthorization': False, 'defaultModelsExpandDepth': -1})

    @app.get('/health', include_in_schema=False)
    def health():
        return {'ok': True, 'mode': 'patient-demo', 'payments_enabled': False}

    @app.get('/', include_in_schema=False)
    @app.get('/portal/{site_id}', include_in_schema=False)
    @app.get('/admin-demo/{site_id}', include_in_schema=False)
    def page(site_id: str | None = None):
        if site_id:
            site(site_id)
        return FileResponse(HERE / 'web' / 'index.html', media_type='text/html')

    app.mount('/assets', StaticFiles(directory=HERE / 'web', check_dir=False), name='assets')
    return app
