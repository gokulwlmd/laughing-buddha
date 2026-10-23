"""Per-SKU member refill policies, independent of processor billing configuration."""
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class RefillRules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    minimum_days: int = Field(default=0, ge=0, le=730, strict=True)
    request_window_days: int = Field(default=14, ge=1, le=90, strict=True)
    check_in_required: bool = True
    review_required: Literal[True] = True
    test_requests_enabled: bool = False
    allow_early_requests: bool = False
    early_request_minimum_days: int = Field(default=0, ge=0, le=730, strict=True)
    early_request_cooldown_days: int = Field(default=7, ge=1, le=90, strict=True)
    early_reason_required: Literal[True] = True
    intake_template_id: Literal['', 'weight-loss', 'sermorelin', 'metformin', 'pt-141'] = ''
    initial_intake_required: bool = True
    check_in_days: list[StrictInt] = Field(default_factory=list, max_length=24)
    included_refills_enabled: bool = False
    claim_window_days: int = Field(default=20, ge=1, le=30, strict=True)

    @field_validator('check_in_days')
    @classmethod
    def valid_check_in_days(cls, value):
        if value != sorted(set(value)) or any(day < 1 or day > 730 for day in value):
            raise ValueError('Use distinct check-in days in increasing order, from 1 to 730')
        return value


class SaveRefillRules(RefillRules):
    expected_revision: int = Field(ge=0, strict=True)


def site_rule_key(site_id, sku):
    return site_id + ':' + sku


def policy(admin, sku):
    saved = admin.get('refill_policy', sku)
    return dict(RefillRules().model_dump(), sku=sku, revision=0) | (saved or {})


def migrate_claim_window(store):
    """Owner's 24 Oct decision: open included claims 20 days before supply ends.

    One local policy migration; no Sticky schedules, care snapshots or orders
    are changed. Later per-site/master edits remain authoritative.
    """
    import json
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS member_policy_migrations(id TEXT PRIMARY KEY)')
        db.execute('BEGIN IMMEDIATE')
        key = 'included-claim-window-20-days-v1'
        if db.execute('SELECT 1 FROM member_policy_migrations WHERE id=?', (key,)).fetchone():
            return
        for kind, identifier, raw in db.execute("SELECT kind,id,data FROM admin_config WHERE kind IN ('refill_policy','site_refill_policy')").fetchall():
            value = json.loads(raw)
            if value.get('included_refills_enabled') and value.get('claim_window_days') != 20:
                value.update(claim_window_days=20, revision=value.get('revision', 0) + 1)
                db.execute('UPDATE admin_config SET data=? WHERE kind=? AND id=?', (json.dumps(value), kind, identifier))
        db.execute('INSERT INTO member_policy_migrations VALUES(?)', (key,))


def install_refill_admin(app, admin):
    @app.get('/api/admin/master-refill-rules/{sku}')
    def read(sku: str, req: Request):
        admin.authenticated(req)
        if not admin.get('master', sku):
            raise HTTPException(404, 'Master SKU not found')
        return policy(admin, sku)

    @app.put('/api/admin/master-refill-rules/{sku}')
    def save(sku: str, body: SaveRefillRules, req: Request):
        admin.authenticated(req, True)
        if not admin.get('master', sku):
            raise HTTPException(404, 'Master SKU not found')
        from member_portal.intake_templates import binding_for_sku
        binding = binding_for_sku(sku)
        if body.intake_template_id and (not binding or binding['template_id'] != body.intake_template_id):
            raise HTTPException(422, 'Choose the mock intake assigned to this product')
        if body.check_in_days and not body.intake_template_id:
            raise HTTPException(422, 'Choose a product intake before scheduling check-ins')
        if body.included_refills_enabled and (not body.intake_template_id or not body.initial_intake_required
                or not body.check_in_required or not body.check_in_days):
            raise HTTPException(422, 'Included refill claims need an initial intake and scheduled check-ins')
        # A policy edit must not invalidate a verified payment mapping, overwrite
        # brand pricing, or silently edit a previously submitted refill request.
        import json
        with admin.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT data FROM admin_config WHERE kind='refill_policy' AND id=?", (sku,)).fetchone()
            previous = json.loads(row[0]) if row else {'revision': 0}
            if previous['revision'] != body.expected_revision:
                raise HTTPException(409, 'These refill settings changed. Reload before saving.')
            value = dict(body.model_dump(exclude={'expected_revision'}), sku=sku, revision=previous['revision'] + 1)
            db.execute("INSERT INTO admin_config(kind,id,data) VALUES('refill_policy',?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data", (sku, json.dumps(value)))
        return value
