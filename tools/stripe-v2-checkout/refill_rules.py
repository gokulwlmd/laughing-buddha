"""Per-SKU member refill policies, independent of processor billing configuration."""
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


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


class SaveRefillRules(RefillRules):
    expected_revision: int = Field(ge=0, strict=True)


def policy(admin, sku):
    saved = admin.get('refill_policy', sku)
    return saved or dict(RefillRules().model_dump(), sku=sku, revision=0)


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
