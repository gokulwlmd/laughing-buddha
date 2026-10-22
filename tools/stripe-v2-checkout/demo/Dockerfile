FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY therapy_skeletons.py ./
COPY demo/__init__.py demo/site_api.py demo/public.py ./demo/
COPY demo/web ./demo/web
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "demo.public:create_public_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
