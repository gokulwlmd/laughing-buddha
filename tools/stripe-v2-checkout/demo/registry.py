"""Deployment-owned publication allowlist; never populated from customer input.

Only verified, explicitly selected checkout choices belong in this manifest.
Prices and current availability always come from the checkout service.
"""
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ApprovedPlan(StrictManifest):
    sku: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    selection: str = Field(pattern=r'^[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*$')
    purchase_option_id: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,100}$')


class TherapyPublication(StrictManifest):
    therapy_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,79}$')
    name: str = Field(min_length=1, max_length=100)
    source_plan_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    published_plan_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    plans: list[ApprovedPlan] = Field(min_length=1, max_length=100)


class SitePublication(StrictManifest):
    site_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,79}$')
    site_name: str = Field(min_length=1, max_length=100)
    brand_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    campaign_id: int = Field(gt=0)
    portal_site_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    therapies: list[TherapyPublication] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def unique_mapping(self):
        if self.site_id == 'payment-test':
            raise ValueError('The existing payment-test publication is reserved')
        for values in ([t.therapy_id for t in self.therapies],
                       [t.published_plan_id for t in self.therapies],
                       [p.sku.lower() for t in self.therapies for p in t.plans]):
            if len(values) != len(set(values)):
                raise ValueError('Each therapy, publication and plan must have a unique mapping')
        return self


class PublicationManifest(StrictManifest):
    version: int = Field(default=1, ge=1, le=1)
    sites: list[SitePublication] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def unique_sites(self):
        for values in ([s.site_id for s in self.sites],
                       [s.portal_site_id for s in self.sites],
                       [t.published_plan_id for s in self.sites for t in s.therapies]):
            if len(values) != len(set(values)):
                raise ValueError('Publications and patient portals cannot be shared across sites')
        return self


def load_publications(manifest=None):
    if manifest is None:
        path = os.environ.get('SITE_API_MANIFEST')
        manifest = json.loads(Path(path).read_text()) if path else {}
    value = PublicationManifest.model_validate(manifest)
    return {site.site_id: site for site in value.sites}
