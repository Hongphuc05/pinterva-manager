# Self-hosted production runtime

Production Compose is [compose.yaml](../compose.yaml). It deliberately contains prebuilt image references only; `compose.dev.yaml` is the optional local-build overlay.

## Services

| Service | Purpose |
| --- | --- |
| `api` | FastAPI, bound to `127.0.0.1:$BACKEND_PORT`; public traffic comes only through Tunnel. |
| `redis` | Celery broker/result backend with AOF persistence. |
| `celery-general` | General queue jobs. |
| `celery-assignment` | Serialized external Printerval Designer/Status writes. |
| `celery-beat` | Scheduled status synchronization; exactly one instance. |
| `cloudflared` | Optional `tunnel` profile, enabled by `DEPLOY_WITH_TUNNEL=true`. |
| `migrate` | One-shot Alembic service invoked by `scripts/deploy.sh`, never left running. |

The image includes Playwright Chromium. Production sets an empty `PLAYWRIGHT_BROWSER_CHANNEL`, so the app uses bundled Chromium rather than requiring Chrome installed on the host. Browser profiles and evidence are named volumes, not source mounts.

## Local container validation

Native development remains supported. To use the Docker development stack instead:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d db redis
docker compose -f compose.yaml -f compose.dev.yaml --profile migration run --rm migrate
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

The production-like validation uses a published immutable tag:

```bash
cp .env.example .env.production-test
# set a non-production test DATABASE_URL, SECRET_KEY and BACKEND_VERSION
ENV_FILE=.env.production-test ./scripts/deploy.sh
ENV_FILE=.env.production-test ./scripts/status.sh
```

Do not point a development test at the production database unless the test has been explicitly approved.

## Required production configuration

`DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, `BACKEND_IMAGE` and immutable `BACKEND_VERSION` are validated by `deploy.sh`. `CLOUDFLARE_TUNNEL_TOKEN` is additionally required only when `DEPLOY_WITH_TUNNEL=true`.

`CORS_ORIGINS` must include the canonical frontend origin `https://tacahu-ops.vercel.app`. Set `CORS_ORIGIN_REGEX` only for temporary preview validation, then clear it. This avoids authorizing every Vercel project by default.
