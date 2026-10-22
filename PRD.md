# AI Clinic Operations Assistant — Product Requirements Document

**Version:** 1.0  
**Last Updated:** 2026-10-22  
**Status:** Active Development

---

## 1. Executive Summary

The **AI Clinic Operations Assistant** is a multi-tenant SaaS platform that automates patient communication and clinic operations for healthcare providers. It combines an AI-powered conversational agent (voice, WhatsApp, SMS) with an operations dashboard for clinic staff to manage doctors, appointments, and follow-up work.

**Core Value Proposition:** Reduce no-shows, automate routine patient communication, and give clinic operations teams real-time visibility into doctor availability and patient interactions — all while maintaining strict data isolation between clinics.

---

## 2. Target Users

| Role | Description | Key Needs |
|------|-------------|-----------|
| **Clinic Admin** | Manages clinic settings, staff, and operations | Full dashboard access, doctor roster management, clinic configuration |
| **Doctor** | Medical practitioner at the clinic | Update own status, view own schedule, manage availability |
| **Receptionist** | Front-desk staff handling bookings and patient queries | Book/reschedule/cancel appointments, view dashboard, manage follow-ups |
| **Platform Admin** (Nueve internal) | Manages platform-level tenants and billing | Cross-tenant visibility, user management, clinic onboarding |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js 15)                    │
│  • Dashboard (React 19, Tailwind CSS 4)                        │
│  • Auth Provider (JWT in localStorage)                         │
│  • API Client (auto-refresh, tenant header)                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS /api/v1/
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Backend (Django 5.x)                      │
│  • REST API (DRF + drf-spectacular)                            │
│  • Multi-tenancy via Row-Level Security (PostgreSQL RLS)       │
│  • Celery + Redis for async tasks (reminders, webhooks, AI)    │
│  • Service-token auth for internal/integration calls           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
    ┌─────────┐      ┌──────────┐      ┌───────────┐
    │PostgreSQL│      │  Redis   │      │ Providers │
    │(RLS)     │      │(Celery,  │      │(Sarvam,   │
    │          │      │ cache)   │      │ WhatsApp, │
    └─────────┘      └──────────┘      │ Telephony)│
                                       └───────────┘
```

**Key Architectural Decisions:**
- **Tenant isolation:** Every model inherits `ClinicOwnedModel`; PostgreSQL RLS policies enforce `WHERE clinic_id = current_setting('app.current_clinic')` at the database level.
- **Auth:** Staff users → JWT (access/refresh). Integrations → Service tokens (hashed, peppered, validated via `ClinicServiceTokenAuthentication`).
- **Doctor status:** Explicit, append-only events (`DoctorStatusEvent`). Current pointer (`DoctorStatusCurrent`) updated transactionally with row locking. Status is **never inferred** from the rota.
- **Appointments:** Conflict prevention via PostgreSQL exclusion constraint + application-level re-check in `BookingService`.

---

## 4. Core Domains & Features

### 4.1 Authentication & Tenancy

**The chain of custody.** A person's account, a clinic, and a session are
three separate things, and the order in which they come together is what
makes the whole thing work:

```
1. IDENTITY      POST /auth/register/  or  POST /auth/login/
                 → { user, tokens }

2. MEMBERSHIP    GET  /auth/me/        (with the token from step 1)
                 → { user, clinics: [{ clinic_id, name, timezone, role }] }
                 A clinic that has not added you yet simply is not in
                 this list. The list is empty, not an error.

3. SCOPE         the client stores one clinic_id and sends it as
                 X-Clinic-Id on every subsequent request
                 → the server checks the membership again, every time

4. TENANT ROWS   the database session is scoped with
                 app.current_clinic_id, and the row-level security
                 policies hide every other clinic's rows
```

**Why step 2 must carry the token from step 1.** The session's token lives
in a ref that is updated when the session changes. A request that depends
on that ref having been updated *before* the request goes out is a race.
When it loses, the server answers `{"user": null, "clinics": []}` and the
user is told they belong to no clinic -- even though they do. The client
therefore passes the token explicitly on the step-2 request rather than
relying on the ref's timing, and the `ApiClient` accepts a per-request
token override for exactly this reason.

**Two ways a person ends up in a clinic:**

| Path | Who acts | Result |
|------|----------|--------|
| **Join** | A clinic administrator adds their email to the staff list | The clinic appears in step 2 on their next sign-in |
| **Start** | They create a clinic themselves | They become its `clinic_admin`; the clinic appears in step 2 immediately |

A signed-in person who belongs to no clinic gets a screen that explains
this and offers to create a clinic -- not a dead end.

- **Login:** Email/password → JWT pair (access 30 min, refresh 7 days, rotating)
- **Clinic selection:** User may belong to multiple clinics; `X-Clinic-Id` header selects active clinic per request
- **Session persistence:** Tokens in `localStorage`; auto-refresh on 401; redirect to `/login` on unrecoverable expiry
- **Roles:** `clinic_admin` | `doctor` | `receptionist` (enforced via `IsClinicAdmin`, `IsStaffMember` permissions)
- **Failure messages:** The permission classes say *which* thing was wrong -- no clinic selected, invalid clinic reference, not a member, or above your role -- rather than a generic refusal

### 4.1.1 CORS (the browser's half of the contract)

The dashboard is a browser application, so the browser enforces CORS
before Django sees anything. The tenant is selected with the
``X-Clinic-Id`` header, and a custom header makes every request a
**preflight**.

The rule that catches people out: the preflight answering ``200`` is not
enough. The browser reads ``Access-Control-Allow-Headers`` and refuses the
real request unless the preflight *names* every header the real request
carries. django-cors-headers' default allow-list contains no custom
headers, so an unconfigured deployment answers the preflight with a
cheerful ``200``, omits ``X-Clinic-Id``, and every screen in the
dashboard shows "Failed to fetch" with nothing in the server log but a
200.

Three rules keep this honest:

1. **One owner.** Django owns CORS. The reverse proxy must not add
   ``Access-Control-*`` headers of its own -- a duplicated
   ``Access-Control-Allow-Headers`` is invalid, and the browser rejects
   it. The preflight is proxied through to Django rather than answered
   at the edge.
2. **The allow-list names the header.** ``CORS_ALLOW_HEADERS`` (the name
   django-cors-headers 4.4+ reads -- *not* ``CORS_ALLOWED_HEADERS``)
   contains ``x-clinic-id``.
3. **The origin is exact.** ``http://localhost:3000`` and
   ``http://127.0.0.1:3000`` are different origins to a browser. The
   local configuration allows both, because which one the browser uses
   depends on how the developer typed the address.

``ops/scripts/check_cors.py`` performs the preflight a browser performs
and checks the response the browser would read.

### 4.1.2 Per-clinic provider credentials

Every clinic brings its own provider accounts. Those credentials are
stored per clinic, encrypted, and are **never** returned by the API.

**The status model.** Each key the platform knows about reports one of
three states:

| Status | Meaning |
|--------|---------|
| `set` | The clinic has set its own value. It wins over everything else. |
| `platform` | The clinic has not set one; the platform-wide environment variable applies. |
| `missing` | Neither is set. The feature that needs it will not work for this clinic. |

**Scope.** A key is either `clinic` (a clinic admin can set it) or
`platform` (the operator sets it; a clinic admin can only see whether it
is set). Platform-scoped keys are read-only through the API.

**The rules:**

1. The value is encrypted at rest with Fernet, keyed by
   `SECRET_ENCRYPTION_KEY` (or derived from the service-token pepper
   when that is unset).
2. The value is **never** returned. The API reports whether a key is set
   and a non-reversible fingerprint -- `...4f2a (3a91c0be)` -- so a
   clinic can confirm they pasted the key they meant to.
3. A clinic only ever sees and changes its own keys. The `clinic_secrets`
   table has the same row-level security policy as every other tenant
   table.
4. The audit trail records *which* key was set, never the value.
5. The platform environment variable is a **fallback**, not the source: a
   clinic that has set its own key is never silently overridden.

**Screens.** `/integrations` shows the table, grouped by provider, with
a *Set* / *Not set* column and a way to add a missing key. It is visible
to clinic administrators only -- and the API enforces that, so hiding the
link is a courtesy rather than the security boundary.

### 4.2 Doctors & Availability
| Feature | Description |
|---------|-------------|
| **Roster** | CRUD for doctors (name, specialization, phone, languages, sort order) |
| **Recurring schedules** | Weekly windows (Mon–Sun, start/end time, slot interval, effective dates) |
| **Schedule exceptions** | Ad-hoc unavailable/available overrides for specific dates |
| **Status board** | Explicit status: `scheduled` → `present` → `running_late` / `unavailable` / `on_leave` / `finished_for_day` → `unknown` |
| **Status sources** | `dashboard`, `voice`, `whatsapp`, `telephony`, `integration`, `scheduler`, `system` (auditable) |
| **Freshness thresholds** | Per-status TTL (e.g., `present`: 60 min, `running_late`: 30 min); stale → `unknown` in dashboard |
| **Availability API** | Computed slots from rota + exceptions + existing bookings + current status |

### 4.3 Patients & Consents
- **Patient record:** Name, phone (unique per clinic), preferred language, communication preferences (opt-outs per channel), notes
- **Consents:** Purpose × channel × status (`pending`, `granted`, `withdrawn`); evidence reference for audit
- **Communication preferences:** Per-channel opt-out respected by reminder/notification services

### 4.4 Appointments
| Feature | Description |
|---------|-------------|
| **Booking** | `BookingService.book()` — atomic conflict check + create + reminder scheduling |
| **Status lifecycle** | `booked` → `confirmed` → `checked_in` → `completed` \| `cancelled` \| `no_show` \| `reschedule_pending` |
| **Transitions** | Enforced via `APPOINTMENT_TRANSITIONS` constant; invalid transitions rejected |
| **Reschedule/Cancel** | `BookingService.reschedule()` / `cancel()` with audit trail |
| **Reminders** | Configurable offsets (default: 24h, 2h), channels (SMS, WhatsApp), retry with backoff |
| **Waitlist** | Not yet implemented (future) |

### 4.5 Conversations & AI Agent
- **Channels:** `voice` (Sarvam), `whatsapp` (Meta Graph API), `sms` (via telephony provider)
- **Conversation model:** Patient + channel + provider conversation ID + status (`open`, `escalated`, `closed`, `handed_off`)
- **Messages:** Direction, type, excerpt (280 chars), content reference (full transcript not retained indefinitely)
- **Call logs:** Provider call ID, duration, outcome, failure reason, transcript/recording references
- **AI Agent:** Sarvam voice agent with configurable greeting, instructions, enabled channels per clinic
- **Webhooks:** Voice (Sarvam), WhatsApp (Meta), Telephony (generic) — signature/secret validation

### 4.6 Follow-Up Tasks (Human-in-the-Loop)
- **Trigger:** Created automatically when AI cannot resolve (e.g., booking failed, clinical question, escalation keywords)
- **Deduplication:** `dedupe_key` per triggering event prevents duplicate tasks from retried webhooks
- **Types:** `booking_request`, `reschedule_request`, `clinical_question`, `prescription_refill`, `callback_request`, `complaint`, `insurance_verification`, `other`
- **Priority:** `low` | `normal` | `high` | `urgent`
- **Status:** `open` → `in_progress` → `resolved` \| `declined` \| `not_required`
- **Assignment:** Optional assignee (user); due date with overdue detection
- **Dashboard queue:** Filterable, sortable, bulk actions

### 4.7 Notifications & Reminders
- **NotificationLog:** Delivery record per message (channel, template, provider message ID, status, attempts, errors)
- **ReminderLog:** Scheduled reminders per appointment (idempotency key guarantees exactly-once)
- **Channels:** SMS, WhatsApp, Voice (provider-agnostic via `ProviderConnection`)
- **Retry policy:** Configurable max attempts + exponential backoff
- **Delivery status:** `queued` → `sent` → `delivered` / `read` \| `failed`

### 4.8 Dashboard (Operations UI)
**Single-page "Today" view** with:
- **Stat cards:** Appointments today, open follow-ups, overdue tasks, unresolved calls, doctors present, open conversations, reminders pending, cancelled/no-show today
- **Doctor status table:** Name, specialization, current status (badge), last confirmed, expected arrival
- **Upcoming appointments:** Next 8 booked/confirmed/checked-in with time, patient, doctor, status
- **Follow-up queue:** Next 8 tasks with type, patient, priority, due, status
- **Auto-refresh** + manual refresh button

**Public pages:**
- `/` — Landing page. What the product does, and the two ways to get in.
- `/login` — Sign in. Links to `/register`.
- `/register` — Create an account, and choose: *join a clinic* (an admin
  adds your email to their staff list) or *start a clinic* (you become its
  administrator).
- `/pending` — Shown after registering without a clinic. Explains that an
  administrator has to add you, and points at sign-in.

**Additional pages:**
- `/doctors` — Full roster with inline status editing (doctor/admin only), status history
- `/appointments` — Full list with filters, booking modal
- `/patients` — Patient list, consent management
- `/follow-ups` — Full task queue with filters, assignment, resolution
- `/calls` — Call log, grouped by outcome
- `/conversations` — Conversation list, transcripts
- `/settings` — Clinic config (operating hours, reminder policy, escalation policy, status freshness)

---

## 5. API Reference (v1)

**Base URL:** `/api/v1/`

### Auth & Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login/` | Email/password → tokens |
| POST | `/auth/register/` | Create a user account (a clinic membership is granted separately) |
| GET | `/auth/me/` | Current user + clinic memberships |
| POST | `/auth/refresh/` | Refresh access token |
| GET | `/health/` | Liveness — no dependencies checked |
| GET | `/health/ready/` | Readiness — checks the database |

### Clinics & Membership
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/clinics/` | List clinics / create one (the creator becomes its admin) |
| GET/PATCH | `/clinics/{id}/` | Retrieve/update clinic |
| GET/PATCH | `/clinics/{id}/settings/` | Operating hours, booking rules, reminder policy, status freshness |
| GET/POST | `/clinics/{id}/members/` | List/add members by email |
| GET | `/clinics/{id}/channel-numbers/` | The numbers patients can reach this clinic on |
| GET | `/clinics/{id}/agent-config/` | The AI agent's greeting and instructions |
| GET | `/clinics/{id}/provider-connections/` | Connected providers (admin only) |
| GET | `/clinics/{id}/configuration/` | Which provider keys are set for this clinic (admin only) |
| PUT | `/clinics/{id}/configuration/{key}/` | Set a provider key for this clinic (admin only) |
| DELETE | `/clinics/{id}/configuration/{key}/` | Remove a provider key (admin only) |

### Doctors
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/doctors/` | List/create doctors |
| GET/PATCH/DELETE | `/doctors/{id}/` | CRUD single doctor |
| GET | `/doctors/{id}/availability/` | Current effective availability |
| GET/POST | `/doctors/{id}/availability-events/` | Status history / record new status |
| GET | `/doctors/{id}/status-history/` | Current pointer + full event log |
| GET/POST | `/doctors/{id}/schedules/` | Recurring weekly schedules |
| GET/POST | `/doctors/{id}/schedule-exceptions/` | Ad-hoc exceptions |

### Appointments
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/appointments/` | List (filter: status, doctor, from, to) / book |
| GET/PATCH | `/appointments/{id}/` | Retrieve/update (notes only) |
| POST | `/appointments/{id}/reschedule/` | Reschedule |
| POST | `/appointments/{id}/cancel/` | Cancel |
| GET | `/availability/slots/` | Bookable slots (query: doctor, specialization, date) |

### Patients
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/patients/` | List/create patients |
| GET/PATCH/DELETE | `/patients/{id}/` | CRUD patient |
| GET/POST | `/patients/{id}/consents/` | List/create consents |
| GET | `/patients/{id}/appointments/` | The patient's appointments |
| POST | `/patients/{id}/communication-preferences/` | Update channel opt-outs |

### Conversations & Tasks
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/conversations/` | List conversations |
| GET | `/conversations/{id}/` | Conversation detail + messages |
| GET | `/call-logs/` | List call logs |
| GET/POST | `/follow-ups/` | List/create follow-up tasks |
| PATCH | `/follow-ups/{id}/` | Update task (status, priority, assignee, due, notes) |
| POST | `/follow-ups/{id}/resolve/` | Resolve with reason |

### Dashboard & AI Tools
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard/summary/` | Operational summary (see §4.8) |
| GET | `/tools/` | List available AI tools |
| POST | `/tools/{name}/invoke/` | Invoke tool (service token only) |

### Webhooks (Provider Callbacks)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhooks/voice/{provider}/` | Sarvam voice webhook |
| POST | `/webhooks/voice/{provider}/{secret}/` | Signed Sarvam webhook |
| POST | `/webhooks/whatsapp/{provider}/` | WhatsApp/Meta webhook |
| POST | `/webhooks/telephony/{provider}/` | Generic telephony webhook |

---

## 6. Data Models (Key Entities)

### ClinicOwnedModel (Base)
```python
id: UUID (PK)
clinic: FK → Clinic (RLS-enforced)
created_at: DateTime
updated_at: DateTime
```

### Doctor
```python
name, slug (unique per clinic), specialization, phone, languages[], is_active, sort_order
user: FK → User (optional, for doctor login)
```

### DoctorStatusEvent (Append-only)
```python
doctor: FK
status: Enum[DoctorStatus]
effective_from, effective_until: DateTime
expected_arrival_at, expected_departure_at: DateTime
source: Enum[STATUS_SOURCES]
updated_by: FK → User (human)
updated_by_identifier: string (system/integration)
notes: string
sequence: integer (monotonic per doctor)
```

### DoctorStatusCurrent (Pointer, row-locked updates)
```python
doctor: OneToOne
current_status, last_confirmed_at, current_event: FK
expected_arrival_at, expected_departure_at, source, version
```

### Appointment
```python
doctor: FK, patient: FK
start_at, end_at: DateTime
status: Enum[AppointmentStatus]
booking_source: Enum[BookingSource]
reference: string (human-readable, unique)
notes, cancellation_reason
confirmed_at, checked_in_at, completed_at
```

### Patient
```python
name, phone (unique per clinic), preferred_language
communication_preferences: JSON {opt_out_sms, opt_out_whatsapp, opt_out_voice}
notes, is_active
```

### FollowUpTask
```python
patient?, related_appointment?, conversation?
task_type: Enum[FollowUpTaskType]
priority: Enum[TaskPriority]
assigned_to: FK → User?
due_at, status: Enum[TaskStatus]
resolution_reason, notes
attempts, max_attempts
dedupe_key: string (unique per clinic)
```

### Conversation / CallLog / NotificationLog / ReminderLog
(See `backend/apps/conversations/models.py` and `backend/apps/appointments/models.py`)

---

## 7. Business Rules & Constraints

| Rule | Enforcement |
|------|-------------|
| **Tenant isolation** | PostgreSQL RLS + `ClinicOwnedModel` base + `TenantScopedViewSet` |
| **Doctor status = explicit** | Only `DoctorStatusEvent` creates status; `DoctorStatusCurrent` updated via `DoctorStatusService.record()` with `SELECT FOR UPDATE` |
| **Appointment conflicts impossible** | Exclusion constraint `appointments_conflict_guards` + `BookingService` re-check in transaction |
| **Status freshness** | `DEFAULT_STATUS_FRESHNESS_MINUTES` per status; stale → `unknown` in dashboard |
| **Reminder idempotency** | `ReminderLog.idempotency_key` unique; scheduler uses key to prevent duplicates |
| **Task deduplication** | `FollowUpTask.dedupe_key` unique per clinic; webhook retries safe |
| **Consent gating** | `Patient.prefers(channel)` checked before sending any notification |
| **Role-based permissions** | `IsClinicAdmin`, `IsStaffMember`, doctor-only-own-profile in `DoctorViewSet.get_queryset()` |

---

## 8. Configuration (Environment-Driven)

All settings in `backend/config/settings.py` via `django-environ`. Key categories:

| Category | Examples |
|----------|----------|
| **Database** | `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` |
| **Redis/Celery** | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| **Auth** | `ACCESS_TOKEN_LIFETIME_MINUTES`, `REFRESH_TOKEN_LIFETIME_DAYS`, `INTERNAL_SERVICE_TOKEN_PEPPER` |
| **CORS** | `CORS_ALLOWED_ORIGINS` |
| **Providers** | `SARVAM_BASE_URL`, `SARVAM_API_KEY`, `SARVAM_VOICE_AGENT_ID`, `SARVAM_WEBHOOK_SECRET`, `WHATSAPP_*`, `TELEPHONY_*` |
| **Defaults** | `DEFAULT_APPOINTMENT_RULES`, `DEFAULT_REMINDER_POLICY`, `DEFAULT_ESCALATION_POLICY`, `DEFAULT_STATUS_FRESHNESS_MINUTES`, `RETENTION` |

---

## 9. Celery Beat Schedule (Periodic Tasks)

| Task | Schedule | Purpose |
|------|----------|---------|
| `scan_appointment_reminders` | 60s | Find due reminders, dispatch |
| `scan_stale_doctor_status` | 300s | Mark stale statuses as `unknown` |
| `scan_unresolved_calls` | 300s | Create follow-up tasks for unresolved calls |
| `publish_outbox` | 5s | Process outbox pattern for reliable events |
| `aggregate_daily_usage` | 3600s | Roll up usage metrics per clinic |

---

## 10. Frontend Structure

```
frontend/
├── src/
│   ├── app/
│   │   ├── page.tsx       # Landing page (public)
│   │   ├── login/         # Sign in
│   │   ├── register/      # Sign up — join a clinic or start one
│   │   ├── pending/       # Account created, awaiting a clinic
│   │   ├── error.tsx      # Root error boundary
│   │   ├── not-found.tsx  # 404
│   │   ├── (ops)/         # Authenticated routes
│   │   │   ├── layout.tsx   # Auth check, nav, clinic switcher
│   │   │   ├── error.tsx    # Route-segment error boundary
│   │   │   ├── dashboard/   # "Today" view
│   │   │   ├── doctors/     # Roster + status board
│   │   │   ├── appointments/# Book, reschedule, cancel
│   │   │   ├── patients/    # Register, consents, preferences
│   │   │   ├── follow-ups/  # Work queue
│   │   │   ├── calls/       # Call log
│   │   │   ├── conversations/# Threads with their turns
│   │   │   └── settings/    # Hours, rules, staff, channels
│   │   ├── layout.tsx     # Root layout, AuthProvider
│   │   ├── icon.svg       # Favicon
│   │   └── globals.css    # Tailwind v4 + the design tokens
│   ├── components/
│   │   ├── auth-provider.tsx  # Session, tokens, API client
│   │   ├── ui.tsx             # Card, StatCard, Badge, StatusBadge, Table, Button, Field, Modal, Toast
│   │   ├── nav.tsx            # Sidebar navigation
│   │   ├── landing-cta.tsx    # Auth-aware call to action
│   │   ├── clinic-switcher.tsx
│   │   └── require-auth.tsx
│   └── lib/
│       ├── api.ts         # ApiClient, ApiError, token refresh
│       ├── types.ts       # TypeScript mirrors of DRF serializers
│       ├── format.ts      # Timezone-aware formatting, label/tone maps
│       └── use-api-data.ts # SWR-like hook for data fetching
```

**Key Frontend Patterns:**
- `useApiData` hook: loading/error/data/reload, abort on unmount. The second
  argument is a filter key; changing it re-fetches.
- `AuthProvider`: single `ApiClient` instance via refs (never stale)
- Timezone-aware formatting: all times rendered in clinic's timezone (`en-IN` locale)
- Clinic switcher in nav: updates `X-Clinic-Id` header instantly
- Public pages stay server components; only the interactive bits
  (`LandingCta`) are client components.

---

## 11. Deployment & Operations

### With Docker (the normal path)
```bash
cp .env.example .env
docker compose up --build            # dashboard :3000, API :8000
docker compose exec backend python manage.py seed_demo
```

The development stack runs the source from bind mounts, so a code change is
live on the next reload.

### Local Development (no Docker)
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
npm install
npm run dev  # http://localhost:3000
```

### Required Services
- PostgreSQL 16 (with RLS support)
- Redis 7+ (Celery broker + cache + results)
- Sarvam API account (voice agent)
- Meta WhatsApp Business API (optional)
- Telephony provider (Twilio, Plivo, etc. — optional)

### Containers
| Image | Stages | Notes |
|-------|--------|-------|
| `backend/Dockerfile` | `base` → `development` / `production` | Non-root `app` user in production; the dev stage runs as root so the bind mount stays writable |
| `frontend/Dockerfile` | `deps` → `builder` → `runner` / `development` | `output: standalone`; the runner serves `server.js` |

`docker-compose.prod.yml` layers on top of the base file: no bind mounts, a
one-shot `migrate` job that gates the API's start, a password-protected
Redis, resource limits, and nginx terminating TLS.

### Production Considerations
- **Secrets:** AWS Secrets Manager / environment variables (never `.env` in prod)
- **Static files:** WhiteNoise (Django) or CDN
- **Migrations:** Run before deploy; backward-compatible only
- **RLS:** Verify policies after every schema change
- **Monitoring:** Sentry (errors), Prometheus/Grafana (metrics), structured JSON logs
- **Health:** `/api/v1/health/` for liveness, `/api/v1/health/ready/` for readiness

---

## 12. Testing Strategy

| Layer | Tool | Coverage Target |
|-------|------|-----------------|
| Unit (Python) | pytest + Django test runner | ≥80% services/models |
| Unit (TypeScript) | Vitest | ≥70% lib/ components |
| Integration | pytest + DRF test client | All API endpoints |
| E2E | Playwright | Critical paths (login, book appt, update status) |
| Contract | drf-spectacular + openapi-typescript | Schema ↔ types sync |

**Key Test Files:**
- `backend/tests/test_booking.py` — Appointment conflict, transitions
- `backend/tests/test_rls.py` — Tenant isolation
- `backend/tests/test_ai_tools.py` — Tool registry, safety
- `backend/tests/test_reminders.py` — Idempotency, retry
- `backend/tests/test_consent.py` — Opt-out enforcement

---

## 13. Open Questions / Future Work

| Area | Question |
|------|----------|
| **Waitlist** | Auto-offer cancelled slots to waitlisted patients? |
| **Multi-clinic doctors** | Doctor shared across clinics — unified status or per-clinic? |
| **Patient portal** | Self-serve booking/cancellation via WhatsApp/Web? |
| **Analytics** | Clinic-level dashboards (no-show rate, utilization, response time) |
| **Billing/Subscriptions** | Usage-based pricing, Stripe integration |
| **Audit export** | GDPR/Right-to-access: export all patient data |
| **Offline mode** | PWA for receptionists with intermittent connectivity |
| **Voice agent v2** | Function calling for booking directly in call |

---

## 14. Glossary

| Term | Meaning |
|------|---------|
| **RLS** | Row-Level Security (PostgreSQL) |
| **RLS Policy** | `USING (clinic_id = current_setting('app.current_clinic')::uuid)` |
| **Service Token** | Long-lived token for server-to-server calls (hashed + peppered) |
| **Dedupe Key** | Stable hash of triggering event (e.g., `call:{provider_call_id}:followup`) |
| **Idempotency Key** | Unique per reminder schedule (e.g., `reminder:{appointment_id}:24h:sms`) |
| **Status Freshness** | Max age before a status is considered stale/unknown |
| **Occupying Statuses** | `booked`, `confirmed`, `checked_in`, `reschedule_pending` — block slots |

---

## 15. Appendix: Key Files Reference

| File | Purpose |
|------|---------|
| `backend/config/settings.py` | All configuration, env-driven |
| `backend/apps/core/models.py` | `ClinicOwnedModel`, `TimeStampedModel`, `UUIDModel` |
| `backend/apps/core/rls.py` | RLS policy helpers |
| `backend/apps/core/tenant.py` | `set_current_clinic()`, middleware |
| `backend/apps/doctors/services/status.py` | `DoctorStatusService.record()`, `get_current()` |
| `backend/apps/appointments/services/booking.py` | `BookingService.book/reschedule/cancel()` |
| `backend/apps/appointments/services/availability.py` | `AvailabilityService.slots()` |
| `backend/apps/appointments/services/reminders.py` | Reminder scheduling + dispatch |
| `backend/apps/conversations/services/followups.py` | Follow-up task creation |
| `backend/apps/api/v1/views/dashboard.py` | Dashboard summary endpoint |
| `frontend/src/components/auth-provider.tsx` | Session + API client |
| `frontend/src/lib/use-api-data.ts` | Data fetching hook |
| `frontend/src/lib/format.ts` | Timezone-aware formatting |

---

*End of PRD*