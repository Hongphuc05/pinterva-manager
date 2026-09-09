# One self-contained runtime image for API, migrations, Celery workers and Beat.
# It intentionally contains no frontend build: the React SPA remains on Vercel.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1. First copy only dependency definition files to maximize Docker Layer Cache
COPY pyproject.toml ./

# 2. Extract dependencies from pyproject.toml and install them + Playwright Chromium
# This layer is heavily cached and will NOT be invalidated when application code changes.
RUN python -c "import tomllib; f = open('pyproject.toml', 'rb'); data = tomllib.load(f); print('\n'.join(data['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && playwright install --with-deps chromium \
    && rm /tmp/requirements.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/crawled_assets /app/order_assets /app/platform_data \
        /app/playwright-evidence /app/chrome-profiles /app/credentials \
    && chown -R app:app /app /ms-playwright

# 3. Copy application source and migrations AFTER dependencies are installed
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# 4. Install the package itself without re-resolving dependencies
RUN pip install --no-deps -e . && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
