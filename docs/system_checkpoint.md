# Pinterval System Checkpoint & Knowledge Persistent Summary

> **Document Type**: Persistent System Checkpoint for AI Agents & Developers  
> **Last Updated**: 2026-09-08  
> **Repository**: Hongphuc05/pinterva-manager (`pinterval`)

---

## 1. Project Overview & Architecture
Tacahu Ops Dashboard is a management system for e-commerce Print-on-Demand (POD) fulfillment operations. It connects with Printerval's outsource POD portal to crawl waiting design jobs, manage order statuses, parse product templates/PSD links, assign jobs to designers, and track fulfillment lifecycles.

### Tech Stack:
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (PostgreSQL), Alembic migrations, PyJWT & Passlib/Bcrypt, Playwright / HTTPX.
- **Frontend**: React 18, Vite 8, TypeScript, TailwindCSS, Lucide-react icons, React Router DOM v6.
- **Database**: PostgreSQL (`postgresql+psycopg://postgres:postgres@localhost:5432/pinterval`).

---

## 2. Completed Features & Capabilities

### A. Printerval Data Crawling & Asset Storage
- **API & DOM Adapter**: Server-side client (`PrintervalApiClient`) & Playwright adapter (`PlaywrightPrintervalAdapter`) fetching Waiting orders.
- **Asset Download**: Product thumbnail images downloaded locally to `crawled_assets/{order_id}.png` and served via `/crawled_assets/{filename}` API static route.
- **CSV Log**: Full order info exported to `crawled_orders.csv`.

### B. Template Jobs & PSD Preview Modal
- **Database Schema**: Added `template_jobs` column (`JSONB`) to `orders` table (Alembic migration: `5e912a789bc0_add_template_jobs_to_orders.py`).
- **Template Details Modal**: [`TemplateModal.tsx`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/components/TemplateModal.tsx) matching Printerval's native popup UI with Provider name badges, Note badges, PSD Drive/Inkedjoy links, and PSD preview images.
- **Order ID Flexible Matching**: Handles both numeric IDs (e.g., `3968925`) and prefixed codes (e.g., `DJ3968925`).

### C. UI/UX Polish & Localization
- **Image Zoom Modal**: [`ImageModal.tsx`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/components/ImageModal.tsx) for clicking thumbnail images to view high-res previews.
- **Columns Update**: Removed SKU & Batch ID columns from Orders table; replaced with "DES Đảm Nhận" (Designer assigned).
- **Status Translations**: Module [`statusTranslation.ts`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/utils/statusTranslation.ts) translating all states (`DISCOVERED`, `CLAIMED`, `PROCESSING`, `DESIGN_READY`, `SUBMITTED`, `WAITING`, `PRINTED`, `FAILED`) into friendly Vietnamese badge badges.
- **Selection Highlight**: CSS `::selection` in `index.css` set to `#0052cc` background with `#ffffff` text.

---

## 3. Database Schema Overview

```mermaid
erDiagram
    users {
        uuid id PK
        string username UK
        string full_name
        string role "admin | designer"
        string password_hash
        boolean active
        int capacity
        datetime created_at
    }
    orders {
        uuid id PK
        string external_order_id UK
        uuid batch_id FK
        string state
        string product_name
        string thumbnail_url
        string assigned_designer_name
        jsonb template_jobs
        boolean has_template
        datetime created_at
    }
    batches {
        uuid id PK
        string source
        string owner
        int count
        string lifecycle_state
    }
    assignments {
        uuid id PK
        uuid order_id FK
        uuid designer_id FK
        string status "pending | approved | rejected"
        datetime assigned_at
    }

    users ||--o{ assignments : "assigned to"
    orders ||--o{ assignments : "has"
    batches ||--o{ orders : "contains"
```

---

## 4. Default Credentials & Roles

| Username | Password | Role | Description |
| :--- | :--- | :--- | :--- |
| `admin` | `admin123` | `admin` | System Administrator with full access (Create/Delete users, Assign orders, Re-crawl, Change Printerval credentials) |
| `designer` | `designer123` | `designer` | Designer / Regular User processing assigned orders |

---

## 5. Key File Locations

- Backend Router Main: [`app/api/main.py`](file:///Users/hongphuc/Documents/01_congViec/pinterval/app/api/main.py)
- Auth Dependencies: [`app/api/deps.py`](file:///Users/hongphuc/Documents/01_congViec/pinterval/app/api/deps.py)
- Users API Route: [`app/api/routes/users_api.py`](file:///Users/hongphuc/Documents/01_congViec/pinterval/app/api/routes/users_api.py)
- Auth Logic: [`app/application/auth.py`](file:///Users/hongphuc/Documents/01_congViec/pinterval/app/application/auth.py)
- Frontend App Entry: [`frontend/src/App.tsx`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/App.tsx)
- Frontend Auth Context: [`frontend/src/auth/AuthContext.tsx`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/auth/AuthContext.tsx)
- Frontend Orders List: [`frontend/src/pages/OrdersListPage.tsx`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/pages/OrdersListPage.tsx)
- Frontend User Management: [`frontend/src/pages/UsersPage.tsx`](file:///Users/hongphuc/Documents/01_congViec/pinterval/frontend/src/pages/UsersPage.tsx)
