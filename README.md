# AI Clinic Operations Assistant

Multi-tenant operations platform for clinics: an AI assistant that handles
patient communication on voice, WhatsApp and SMS, plus an operations
dashboard for the people who run the clinic.

- **Product requirements:** [PRD.md](PRD.md)
- **Design system:** [DESIGN_PLAN.md](DESIGN_PLAN.md)

```
/                 Landing      What the product does, and how to get in
/register         Sign up     Create an account, and optionally a clinic
/pending          Waitlisted  Your account exists; a clinic admin has to add you
/login            Sign in
/dashboard        Today       Appointments, doctor status, follow-up queue
/doctors         Roster      Status board + append-only event log
/appointments    Schedule    Book, reschedule, cancel
/patients        Register    Consents + communication preferences
/follow-ups      Queue       Work the assistant could not finish
/calls           Call log    Operational record, no transcripts
/conversations   Threads     Every patient interaction, with its turns
/settings        Configuration  Opening hours, booking rules, staff, channels
/integrations    Keys        Which provider credentials are set (clinic admins only)
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| Backend | Django 5, Django REST Framework, drf-spectacular |
| Database | PostgreSQL 16 with row-level security |
| Async | Celery + Redis (broker, results, cache) |
| Auth | JWT (staff) and service tokens (integrations) |

---

## Quick start

### With Docker (recommended)

```bash
cp .env.example .env          # fill in what you need
docker compose up --build
```

The back-office dashboard is on <http://localhost:3001>, the API on
<http://localhost:8000/api/v1/>, and the schema explorer on
<http://localhost:8000/api/docs/>. There is no patient-facing website: patients
book by messaging the clinic's WhatsApp number, and the assistant writes the
appointment straight into this dashboard. Port 3000 is reserved for the
self-hosted WAHA gateway; see `WAHA_INTEGRATION.md`.

If you also run WAHA, use the unified runner from this repo root:
`./start-all.sh start|status|logs|stop`.

Load demo data to get a clinic with doctors, patients and appointments:

```bash
docker compose exec backend python manage.py seed_demo
```

### Without Docker

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Celery (separate terminals)
celery -A config worker -l INFO
celery -A config beat -l INFO

# Frontend
cd ../frontend
pnpm install
pnpm dev
```

You need PostgreSQL and Redis running locally. The defaults in
`.env.example` expect them on `127.0.0.1`.

> **Note on the build directory.** `pnpm dev` writes to `.next-dev` and
> `pnpm build` writes to `.next` — deliberately different. Sharing one
> directory between the two makes every route fail with
> `Cannot find module './NNN.js'`, because the surviving webpack runtime
> points at chunks the other mode never wrote. If a build directory ever
> ends up corrupt, `pnpm clean` removes both.

---

## Environment

Copy `.env.example` to `.env`. Every value has a safe local default, but
production must override at least:

| Variable | Why it matters in production |
|----------|-----------------------------|
| `DJANGO_SECRET_KEY` | Signs tokens. Leaking it means anyone can mint a session. |
| `INTERNAL_SERVICE_TOKEN_PEPPER` | Hashes service tokens. Rotate together with the tokens. |
| `REDIS_PASSWORD` | Redis holds the Celery broker and cached tenant data. |
| `DB_PASSWORD` | Database credentials. |
| `CORS_ALLOWED_ORIGINS` | Must list only your real dashboard origin. |
| `SECRET_ENCRYPTION_KEY` | Encrypts each clinic's provider credentials. **Never change it** — every stored secret becomes unreadable. |

Provider keys (`SARVAM_*`, `WHATSAPP_*`, `TELEPHONY_*`) can be left empty
in development — the telephony provider falls back to a stub.

> **Restart the API after changing `.env`.** Environment variables are read
> once, at startup. Django's auto-reloader picks up changes to `.py` files,
> but a change to `.env` needs a manual restart.

### If the dashboard shows "Failed to fetch"

The dashboard is a browser application, so the browser enforces CORS. The
tenant is selected with the `X-Clinic-Id` header, and a custom header
turns every request into a preflight. If the preflight does not name
`X-Clinic-Id`, the browser refuses the *real* request — and the server log
shows a cheerful `200` for the preflight and nothing at all for the
request that followed, which makes it look like a backend problem.

Two things have to line up:

| Setting | Value |
|---------|-------|
| `CORS_ALLOW_HEADERS` (in `settings.py`) | must contain `x-clinic-id` |
| `CORS_ALLOWED_ORIGINS` (in `.env`) | must contain the exact origin the browser shows, e.g. `http://localhost:3001` |

Note that `http://localhost:3001` and `http://127.0.0.1:3001` are
*different* origins to a browser. If the dashboard is open on one and the
server allows the other, every request fails.

Check it with:

```bash
python ops/scripts/check_cors.py http://127.0.0.1:8000 http://localhost:3001
```

---

## Getting started as a person

There are two ways to end up with a usable account, and `/register` asks you
to pick one deliberately:

| Path | What happens | Who ends up with access |
|------|--------------|-------------------------|
| **Join a clinic** | The account is created; you land on `/pending` | A clinic administrator adds your email to their staff list |
| **Start a clinic** | The account and the clinic are created together | You, as that clinic's administrator |

The demo data creates a clinic you can sign into straight away:

```
admin@sunriseclinic.test
demo-password-123
```

---

## Provider credentials

Each clinic brings its own provider accounts: its own WhatsApp business
number, its own voice agent, its own telephony account. Those credentials
live in the database, encrypted with Fernet, and are **never** returned by
the API — the interface only ever says whether a key is set.

A clinic admin manages them at **`/integrations`**, which lists every key
the platform needs with a *Set by your clinic* / *Platform default* /
*Not set* status, and lets them set the ones that are missing. The status
table is per clinic: what one clinic sets never affects another.

The environment variables (`SARVAM_API_KEY`, `WHATSAPP_ACCESS_TOKEN`, …)
are the **platform-wide fallback**, used by any clinic that has not set
its own.

`SECRET_ENCRYPTION_KEY` encrypts the stored values. When it is empty the
key is derived from `INTERNAL_SERVICE_TOKEN_PEPPER`, which is fine for
local development but means rotating the pepper would invalidate every
stored secret. Set it explicitly in production.

---

## Docker layout

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local development: source bind-mounts, hot reload, exposed ports |
| `docker-compose.prod.yml` | Production overrides: built images, no mounts, resource limits, TLS termination |
| `backend/Dockerfile` | `base` → `development` / `production` stages |
| `frontend/Dockerfile` | `deps` → `builder` → `runner` / `development` stages |
| `nginx/` | Reverse proxy, rate limiting, security headers, ACME/Let's Encrypt |
| `ops/` | Runtime state: certificates, certbot webroot, database bootstrap |

### Production deployment

```bash
export $(grep -v '^#' .env | xargs)   # or use your secret manager
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The production stack runs a one-shot `migrate` job before the API starts, so
a new schema is always applied before the new code serves traffic.

**Before the first run**, put the database bootstrap SQL in
`ops/postgres-backup/` and the TLS certificates in `ops/certs/`.

---

## Operational scripts

| Script | What it does |
|--------|--------------|
| `ops/scripts/smoke_test.py <url>` | Calls every endpoint the dashboard uses and fails on any 5xx |
| `ops/scripts/check_cors.py <url> [origin]` | Performs the CORS preflight a browser performs, and checks the response |
| `ops/scripts/test_signup_path.py <url>` | register → memberships → create clinic → dashboard |
| `ops/scripts/test_register_flow.py <url>` | Walks the whole sign-up path: register → login → create clinic → membership |

Both run against a live server, so start the stack first.

```bash
python ops/scripts/smoke_test.py http://127.0.0.1:8000
python ops/scripts/test_register_flow.py http://127.0.0.1:8000
```

---

## API

Base path `/api/v1/`. Interactive docs at `/api/docs/`, OpenAPI schema at
`/api/schema/`.

```bash
# Authenticate
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"..."}'

# Every tenant-scoped call carries the clinic
curl http://localhost:8000/api/v1/appointments/ \
  -H "Authorization: Bearer $ACCESS" \
  -H "X-Clinic-Id: $CLINIC_ID"
```

Health endpoints for orchestrators:

| Path | Purpose |
|------|---------|
| `GET /api/v1/health/` | Liveness — no dependencies checked |
| `GET /api/v1/health/ready/` | Readiness — checks the database |

---

## Tenant isolation

Every tenant-owned row carries a `clinic_id`, and PostgreSQL row-level
security enforces it independently of the application code:

```sql
USING (clinic_id = current_setting('app.current_clinic')::uuid)
```

The API resolves the clinic from the `X-Clinic-Id` header but only ever
after checking that the signed-in user is a member of it. A user cannot
widen their access by editing the header.

`backend/tests/test_rls.py` and `test_tenant_isolation_api.py` cover this.

---

## Testing

```bash
cd backend && pytest                    # 107 tests
cd backend && pytest --cov=apps         # with coverage
cd frontend && npm run typecheck
cd frontend && npm run build
```

---

## License

Proprietary. All rights reserved.
