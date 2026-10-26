# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHECKOUT_STATE_DIR=/data \
    CHECKOUT_AUTHORIZATION_VERIFIED=1

WORKDIR /app
COPY --chown=10001:10001 commerce_admin.py ./
COPY --chown=10001:10001 catalog_refill_policies.py wellness_master_catalog.json additional_master_catalog.json ./
COPY requirements.txt ./
RUN --mount=type=secret,id=build_ca_bundle \
    if [ -f /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi; \
    python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 app.py catalog.py admin.py master.py plans.py sites.py reconcile_site.py therapy_skeletons.py import_master_therapies.py therapy_campaign_setup.py synthetic.py prepaid.py refill_rules.py dollar_testing.py external_fulfillment.py fortifyhp_setup.py fortifyhp_provisioning.py fortifyhp_publish_api.py entrypoint.py ./
COPY --chown=10001:10001 member_portal ./member_portal
COPY --chown=10001:10001 patient_demo/provider.py patient_demo/app.py patient_demo/__init__.py ./patient_demo/
COPY --chown=10001:10001 demo/__init__.py demo/public.py demo/session_api.py demo/site_api.py demo/registry.py demo/publish.py demo/runtime.py ./demo/
COPY --chown=10001:10001 web ./web

EXPOSE 8080
ENTRYPOINT ["python", "entrypoint.py"]
