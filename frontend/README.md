# Tacahu Ops Dashboard — frontend

React + TypeScript + Vite SPA cho web dashboard vận hành nội bộ. Backend là FastAPI
JSON API (`../app/api`), auth qua session cookie (không JWT/OAuth).

## Dev

```bash
npm install
npm run dev   # http://localhost:5173, proxy /api sang FastAPI ở :8000
```

## Build (prod-like, FastAPI serve `dist/` từ `/`)

```bash
npm run build
```

## Test / lint

```bash
npm run test    # Vitest
npm run lint    # oxlint
```

Xem `../RUNME.md` ở gốc repo để chạy toàn bộ hệ thống (backend + DB + frontend).
