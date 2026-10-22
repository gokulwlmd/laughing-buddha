# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHECKOUT_STATE_DIR=/data \
    CHECKOUT_AUTHORIZATION_VERIFIED=1

WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=build_ca_bundle \
    if [ -f /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi; \
    python -m pip install --no-cache-dir -r requirements.txt
COPY --chown=10001:10001 app.py catalog.py admin.py master.py plans.py sites.py therapy_skeletons.py synthetic.py prepaid.py entrypoint.py ./
COPY --chown=10001:10001 web ./web

EXPOSE 8080
ENTRYPOINT ["python", "entrypoint.py"]
