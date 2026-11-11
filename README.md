# Sheco Pharmacy Backend

FastAPI API for the Sheco single-pharmacy POS, inventory, and admin system (Ghana).

Matches the frontend mock contracts in `sheco-frontend` and the Must requirements in the SRD.

## Stack

- Python + FastAPI
- SQLAlchemy 2
- SQLite by default for local dev; PostgreSQL via `DATABASE_URL` (SRD target)
- JWT bearer auth
- Money stored as integer **pesewas** (100 = GHS 1.00)

## Quick start

```bash
py -3 -m venv .venv
.\.venv\Scripts\activate
py -3 -m pip install -r requirements.txt
copy .env.example .env
py -3 -m uvicorn app.main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Frontend CORS: `http://localhost:5173`

### PostgreSQL (optional)

```bash
docker compose up -d
# set DATABASE_URL=postgresql+psycopg2://sheco:sheco@localhost:5432/sheco
```

## Demo accounts

| Role | Username | Password | PIN |
|------|----------|----------|-----|
| Super Admin | `admin` | `admin123` | `1234` |
| Salesperson | `kwame` | `sale123` | `2222` |
| Salesperson | `efua` | `sale123` | `3333` |

## Main endpoints

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/auth/login` | Returns JWT + session fields |
| GET | `/api/users` | Admin |
| POST | `/api/users` | Admin |
| GET | `/api/products` | Cost/batches redacted for salesperson |
| POST | `/api/products` | Admin create/update |
| POST | `/api/inventory/restock` | Admin |
| POST | `/api/inventory/adjustments` | Admin |
| GET | `/api/inventory/alerts` | Admin |
| GET/POST | `/api/sales` | Role-scoped list / complete sale |
| POST | `/api/sales/sync` | Idempotent offline queue upload |
| POST | `/api/sales/{id}/void` | Admin |
| GET | `/api/dashboard/stats` | Admin |
| GET | `/api/reports/sales` | Admin |
| GET | `/api/audit` | Admin |
| GET/PATCH | `/api/settings` | Admin |

Send `Authorization: Bearer <token>` and optionally `X-Device-Id`.

## Business rules enforced

- FEFO batch allocation; expired batches unsellable
- Prescription reference required for Rx products
- Salesperson cannot see cost/profit or other staff sales
- Offline sync accepts oversold stock and sets `needsReview`
- Void restores stock and writes audit
