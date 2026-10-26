FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY therapy_skeletons.py ./
COPY demo/__init__.py demo/site_api.py demo/public.py demo/session_api.py demo/registry.py demo/entrypoint.py ./demo/
COPY demo/web ./demo/web
EXPOSE 8080
CMD ["python", "demo/entrypoint.py"]
