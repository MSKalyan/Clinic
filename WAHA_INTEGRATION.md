# WAHA ↔ Clinic backend integration

Minimal, additive integration between the self-hosted WAHA WhatsApp API
(`~/projects/waha`) and the Django/DRF clinic backend (`~/projects/Clinic`).

No existing Meta WhatsApp Cloud code was changed. No WAHA session data was
reset or modified.

## Architecture

```
WhatsApp phone ──▶ WAHA (container "waha", host :3000)
                     │  POST /api/v1/webhooks/waha/
                     │  (shared network clinic-waha-net)
                     ▼
Django backend (container "backend", host :8000)
   ├─ verify shared secret + body HMAC
   ├─ parse & filter event (incoming, private, text only)
   ├─ dedupe by WhatsApp message id (DB unique constraint)
   ├─ log message in waha_message_log + link to a patient conversation
   ├─ acknowledge the FIRST message per chat only (never a spam loop)
   └─ enqueue delivery ──▶ Redis ──▶ Celery worker
                                       └─ POST /api/sendText ──▶ WAHA ──▶ WhatsApp

Browser dashboard (host :3001)
   └─ WebSocket /ws/clinic/<id>/?token=<JWT> ──▶ Django Channels (daphne)
        └─ live Conversations + Dashboard updates, no polling
```

* WAHA engine `WEBJS`, session `session_01`, version 2026.10.1. The compose
  file pins the public `devlikeapro/waha:latest-2026.10.1` image: WAHA Plus
  was merged into the free public image in 2026.6.1, so no patron login is
  needed and the engine/version are unchanged.
* Network: external Docker network `clinic-waha-net`; WAHA is `http://waha:3000`
  from Django, and WAHA calls `http://backend:8000`.
* Host ports: WAHA `3000` (unchanged), Clinic frontend `3001` (moved from 3000
  to avoid the conflict), Django `8000`, Postgres `5432`, Redis `6379`.

## Environment variables

All values live in gitignored `.env` files only.

| Django (`.env`) | WAHA (`waha/.env`) | Purpose |
| --- | --- | --- |
| `WAHA_BASE_URL=http://waha:3000` | — | Backend → WAHA API base URL |
| `WAHA_API_KEY` | `WAHA_API_KEY` | WAHA admin key (same value, `X-Api-Key` header) |
| `WAHA_SESSION=session_01` | `WHATSAPP_START_SESSION=session_01` | Session used for send/status |
| `WAHA_WEBHOOK_SECRET` | `WHATSAPP_HOOK_CUSTOM_HEADERS=X-Webhook-Secret:<same>` | Shared webhook secret |
| `WAHA_WEBHOOK_HMAC_KEY` | `WHATSAPP_HOOK_HMAC_KEY=<same>` | HMAC-SHA512 body signature |
| — | `WHATSAPP_HOOK_URL=http://backend:8000/api/v1/webhooks/waha/` | Callback URL |
| — | `WHATSAPP_HOOK_EVENTS=message` | Only inbound messages |

The webhook secret and HMAC key were generated locally and are written only
to the two `.env` files. `.env.example` files contain placeholders only.

## HTTP endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/v1/webhooks/waha/` | `X-Webhook-Secret` + HMAC | WAHA callback |
| POST | `/api/v1/integrations/waha/messages/` | JWT + clinic membership | Queue a staff reply (`{"conversation_id"\|"chat_id","text"}`) → `202` |
| GET | `/api/v1/integrations/waha/status/` | JWT + clinic membership | WAHA health + session status |
| WS | `/ws/clinic/<clinic-id>/?token=<jwt>` | JWT + membership | Live dashboard + conversation events |

There is deliberately **no anonymous booking endpoint**. The website is a back
office for clinic staff; patients interact only through WhatsApp.

Ignored events: `message.ack`, `message.reaction`, `session.status`, all other
event names, outbound (`fromMe: true`), group messages (`@g.us`) and
non-text/media messages.

## WhatsApp booking assistant

This is the only patient-facing booking channel. Each chat is a small state
machine stored in `WhatsAppFlow` (`waha_flows` table, unique per clinic + chat).
`apps/integrations/services/bot_flow.py` renders every prompt from **live clinic
data**: clinic name, distinct doctor specialities, opening hours and the next
real free slot from `AvailabilityService`.

```
patient: Hi
bot:     clinic name, specialities, hours, next availability + numbered menu
         1. Book an appointment   2. Online consultation
         3. Doctors & specialities   4. Talk to our team

patient: 1            -> full name -> phone number
bot:     numbered list of active doctors (name + speciality)
patient: 1            -> YYYY-MM-DD (today/tomorrow also accepted)
bot:     numbered free slots for that doctor and date
patient: 1 (or 09:00) -> confirmation summary
patient: YES          -> BookingService.book(source=whatsapp) -> APT reference
```

* **Only the exact message `Hi` starts (or restarts) the conversation.** Other
  messages — including `hello`, `start`, `menu` or `hi there` — produce no bot
  reply when no flow is active; they are still logged and visible in the back
  office. After a booking or a handoff the bot also stays quiet until a fresh
  `Hi`.
* Option 2 follows the same path and records "Online consultation" in the
  appointment notes. Option 3 re-sends the dynamic info; option 4 hands off to
  a human without booking. `NO` returns to the menu without creating anything.
* Every prompt is a template in `MESSAGE_TEMPLATES` (`bot_menu`, `bot_info`,
  `bot_doctors`, `bot_date`, `bot_slots`, `bot_name`, `bot_phone`,
  `bot_confirm`, `bot_booked`, `bot_cancelled`, `bot_handoff`, `bot_unknown`,
  `bot_error`), so wording can be changed without touching code.
* One reply is queued per inbound message: it advances the flow by exactly one
  step. Duplicate webhook deliveries are ignored by the unique WAHA message id
  in `waha_message_log`, so the bot never loops or repeats a prompt. Unclear
  answers re-ask the current question instead of inventing data.
* A new patient is created at the phone-number step, gets the one-time welcome
  text, and the whole WAHA chat is backfilled into their back-office
  `Conversation` so staff see every turn in real time.
* The booking uses the same `BookingService` as the dashboard, so slot
  locking, overlap protection and idempotency are identical. The idempotency
  key includes the flow id and the chosen slot.

### Which clinic does this WhatsApp number serve?

`resolve_clinic()` checks, in order:

1. an existing active patient with the sender's phone (their own clinic);
2. `WAHA_CLINIC_SLUG` from `.env` — the explicit mapping for this session
   (an onboarding clinic may be mapped while it is being set up);
3. the sole active clinic, if there is exactly one.

If none match, the message is logged, no flow is created, and the sender gets
a generic error prompt rather than another clinic's data.

## Welcome message on new patients

Creating a patient — from the staff **Add Patient** form or the WhatsApp
assistant — queues a one-time welcome WhatsApp text. The key is `welcome:<patient id>`,
so a returning patient never gets a second welcome. Delivery failures are logged
on the notification row and never block the patient or appointment write.

## Appointment confirmations and patient replies

The booking service now sends a WhatsApp text to the patient after a
**book**, **reschedule** or **cancel**. The flow is:

```
POST /api/v1/patients/ + POST /api/v1/appointments/   (or the WhatsApp assistant)
    -> BookingService.book()          (or reschedule / cancel)
    -> transaction.on_commit -> appointment_messages.send_appointment_message()
    -> NotificationService.send()     (consent + opt-out checks, NotificationLog QUEUED)
    -> Celery dispatch_notification -> get_messaging_provider() -> WahaAdapter
    -> POST /api/sendText -> ConversationMessage (outbound) + live WebSocket event
```

* Delivery is asynchronous: the request only writes a `QUEUED` row and returns,
  so a slow WAHA/Meta API can never make the dashboard hang. Provider calls are
  retried by Celery and failures are marked `FAILED` on the row.
* Texts are rendered from `MESSAGE_TEMPLATES` in `config/settings.py` (legacy
  `WAHA_APPOINTMENT_MESSAGES` overrides still work) with the clinic's timezone,
  doctor, reference and date/time.
* A clinic with its own Meta WhatsApp Cloud credentials keeps using them;
  otherwise the self-hosted WAHA session is the WhatsApp provider.
* Messaging failures are logged and **never** fail the appointment write.
* Patients who opted out of WhatsApp (`opt_out_whatsapp`) receive nothing.
* Idempotency is enforced by `NotificationLog.idempotency_key`, so a retried
  callback cannot double-send a confirmation.

Inbound replies still arrive at `/api/v1/webhooks/waha/`. Alongside the
`waha_message_log` row and the assistant reply, the sender number is matched to
a patient (tenant-by-tenant) and the message is added to a WhatsApp
`Conversation` linked to that patient. The dashboard's **Conversations** page
shows the patient, the thread, and a reply box that posts through the existing
authenticated `/api/v1/integrations/waha/messages/` endpoint.

Tests: `backend/tests/test_appointment_messages.py` and
`backend/tests/test_whatsapp_bot.py` (WAHA HTTP is always mocked).

## No public booking page

There is no patient-facing website. `/book` and the anonymous
`/api/v1/public/*` endpoints were removed: this project is a back office, and
patients book only by messaging the WhatsApp number. Appointments created by
the assistant appear in **Appointments** and **Conversations** exactly like
staff-created ones.

## Live conversations and dashboard

The dashboard and Conversations pages subscribe to a single authenticated
WebSocket per clinic: `ws://localhost:8000/ws/clinic/<clinic-id>/?token=<JWT>`.
Django Channels (daphne + Redis) broadcasts `dashboard.changed` and
`conversation.message` events whenever an appointment, patient or message
changes. The browser reconnects with backoff and replays thread subscriptions,
so messages and counters update without polling or a page refresh.

## Database

* `WahaMessageLog` (`waha_message_log` table), migration
  `apps/integrations/migrations/0002_wahamessagelog.py`. Stores message id
  (unique → idempotency), session, sender id/phone, text, direction, status,
  timestamp, reply id and error. A duplicate webhook is acknowledged with 200
  but never processed twice.
* `WhatsAppFlow` (`waha_flows` table), migration
  `apps/integrations/migrations/0004_whatsappflow.py`. One row per clinic+chat,
  holding the current state and the answers collected so far. Tenant-isolated
  with row level security, like the other clinic-owned tables.

## Tests

The backend suite covers the REST client (request shape, API key header,
timeouts, HTTP/JSON errors, invalid recipients), webhook auth, parsing and
filtering, duplicate suppression, the full multi-step assistant flow (dynamic
clinic data, invalid answers, cancel, handoff, restart, online consultation),
booking into the back office, welcome templates, endpoint permissions,
doctor creation/visibility, and realtime WebSocket auth + event delivery. WAHA
HTTP calls are always mocked.

Run the focused suites with:

```bash
cd ~/projects/Clinic
docker compose exec -T backend python -m pytest \
  tests/test_waha.py \
  tests/test_appointment_messages.py \
  tests/test_public_booking.py \
  tests/test_doctor_creation.py \
  tests/test_realtime.py -q
```

Run the full suite with `docker compose exec -T backend python -m pytest -q`.
The only expected failures in a local dev database are the four `test_rls.py`
/tenant-scope tests, because the local `clinic_app` role is a superuser with
`rolbypassrls=t` and therefore bypasses the row-level security policies those
tests exist to verify. On a production role without those privileges they pass.

## Live end-to-end verification (not performed here)

A real WhatsApp message was **not** sent — it needs a chosen recipient and
your explicit go-ahead. To do it yourself:

1. Start everything (see commands below) and wait for WAHA session
   `session_01` to be `WORKING`:

   ```bash
   docker compose logs -f waha   # in ~/projects/waha
   # or: curl -H "X-Api-Key: $WAHA_API_KEY" http://localhost:3000/api/sessions/session_01
   ```

2. From a **different** WhatsApp account, send the exact text:

   ```
   Hi
   ```

3. Check the log row and the reply:

   ```bash
   docker compose exec backend python manage.py shell -c \
     "from apps.integrations.models import WahaMessageLog; print(list(WahaMessageLog.objects.values()))"
   docker compose logs -f backend
   ```

You can also send directly to a recipient (JWT required):

```bash
curl -X POST http://localhost:8000/api/v1/integrations/waha/messages/ \
  -H "Authorization: Bearer <JWT>" \
  -H "X-Clinic-Id: <clinic-uuid>" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"<conversation-uuid>","text":"Hello from the clinic."}'
```

The endpoint returns `202` immediately; the reply is delivered by the Celery
worker and appears in the thread via the live WebSocket event. Supply either
`conversation_id` (preferred, links the reply to the patient thread) or a raw
`chat_id` for an unlinked WhatsApp chat.

## Running Clinic + WAHA together

From the repository root use the unified runner:

```bash
./start-all.sh start    # start Clinic (3001/8000) and WAHA (3000)
./start-all.sh status   # health of both projects
./start-all.sh logs     # tail combined logs
./start-all.sh stop     # stop both
```

Clinic UI: `http://localhost:3001` · API docs: `http://localhost:8000/api/docs/`
· WAHA UI: `http://localhost:3000/dashboard`.

## Pause / resume automation

`AUTOMATED_MESSAGING_ENABLED` in `.env` is a hard stop for every outbound
WhatsApp/Meta message — the assistant, reminders, confirmations, welcome texts
and staff replies. Set it to `false` and no message is sent or queued (inbound
messages are still logged); set it back to `true` and restart the services to
resume. The Celery task also checks the flag, so a restart cannot flush an old
backlog.
