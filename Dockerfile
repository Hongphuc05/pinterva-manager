# One self-contained runtime image for API, migrations, Celery workers and Beat.
# It intentionally contains no frontend build: the React SPA remains on Vercel.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./
COPY app ./app
COPY migrations ./migrations

RUN pip install . \
    && playwright install --with-deps chromium \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/crawled_assets /app/order_assets /app/platform_data \
        /app/playwright-evidence /app/chrome-profiles \
    && chown -R app:app /app /ms-playwright

USER app

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
