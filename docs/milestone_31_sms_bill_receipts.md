# M31 — SMS Bill Receipts (MSG91)

Status: **code + tests complete (backend 568 / frontend 160); live gateway
sending pending a human (dev API-key check) at the store.**

M31 adds a real, honest "the customer got their receipt" path on top of manual
billing. When a shopkeeper saves a bill for a customer who has a mobile number,
Storeye treats a picture of that bill's **text receipt** and sends it through
MSG91. Sent is only ever recorded after the provider ack'd; failures keep the
row so a shopkeeper can resend. Nothing is fabricated: no fake "SMS sent", no
pretend delivery.

## Decisions (confirmed with the user)

1. **Gateway = MSG91.** `msg91` is the only provider this milestone implements;
   `SMS_PROVIDER` is validated to `{"msg91"}` and the gateway factory is the
   single seam a second provider would slot into.
2. **Auto-send at bill creation.** Saving a bill for a customer with a phone
   number queues a receipt SMS immediately. No extra button, no opt-in —
   but billing is **never blocked** by SMS.
3. **Queue + background send (offline-first).** Delivery goes through a
   local PostgreSQL outbox (`sms_messages`) drained by a small daemon thread
   in the API process. This is the honest design: today's network blips don't
   lose a receipt — the row waits in YOUR store's queue (state visible in
   Billing), the worker retries with backoff, and the shopkeeper can resend
   only genuinely failed ones.

## What M31 changes

### Backend

1. **Outbox model.** `sms_messages` rows: `store_id`, `bill_id` (**SET NULL** —
   SMS history survives the demo reset; it never cascades), `customer_id`,
   `mobile` + `message` **snapshotted at enqueue** (a later edit to the
   customer/bill can't rewrite what we sent), `status` `QUEUED|SENDING|SENT|
   FAILED`, `attempts`, `last_error`, `next_attempt_at`, `sent_at`, `provider`
   (stamped `msg91`). Composite index
   `ix_sms_messages_store_status_due` for the claim query.
   Migration `e7a3c5f1b2d8`, `down_revision = d5e8b0c2e4f6`; `alembic check` clean.
2. **Settings.** `SMS_ENABLED` (gate), `SMS_PROVIDER = msg91`, `MSG91_AUTH_KEY`,
   `MSG91_SENDER_ID` (optional sender ID, validated `^[A-Za-z0-9]{5,6}$` when
   set), `MSG91_ROUTE` (default 4, validated `4|1`), `MSG91_COUNTRY_CODE` (`91`),
   `MSG91_BASE_URL` (`https://api.msg91.com/api`), worker timers (`SMS_POLL_SECONDS`
   5, `SMS_MAX_ATTEMPTS` 5, `SMS_RETRY_BACKOFF_SECONDS` 60 (doubles per attempt,
   capped 3600s), `SMS_STALE_CLAIM_SECONDS` 120, `SMS_TIMEOUT_SECONDS` 10).
3. **MSG91 gateway** (`services/sms/gateway.py`). Sends to the legacy
   `sendhttp.php` over httpx with the exact param contract (authkey, mobiles,
   message, sender?, route, country). Provider ack = response body contains
   `type:success`. Errors are typed: `SmsGatewayNotConfigured` (missing auth
   key → fail immediately, terminal) vs `SmsGatewayError` (transport/HTTP/
   provider refusal → retryable). httpx pinned `>=0.27,<1.0` in requirements.txt.
4. **Receipt builder** (`services/sms/receipt.py`). Deterministic plain-text
   receipt: store name, bill no., date, up to **6 item lines**
   (`2 × Amul Milk 1L = ₹124.00`), `+N more items` overflow line, tax + **total
   in ₹**, thank-you. Numbers always come from the bill row + its lines — never
   from frontend input. Keep it under MSG91's practical character budget.
5. **Outbox service** (`services/sms/outbox.py`). `enqueue_for_bill` (called
   **after** the bill commit, in its own transaction, swallows failures → never
   raises outward), `claim_due` (batch `for_update SKIP LOCKED` claim of due
   rows → SENDING), `process_pending` (send → SENT w/ `sent_at`; on retryable
   error: back to QUEUED w/ exponential `next_attempt_at`, bump `attempts`; on
   terminal: FAILED with `last_error`), `resend` (FAILED only — anything else
   raises `ValueError` → HTTP 409), `list_messages` (status/bill filter, newest
   first, store-scoped), `status` (canonical **lowercase** aggregate payload
   `{total, queued, sending, sent, failed}` — tuned to the pydantic schema).
   Stale rows stuck in SENDING (`> SMS_STALE_CLAIM_SECONDS` with no heartbeat
   refresh) are claimed back to QUEUED.
6. **Worker thread** (`services/sms/manager.py`). One daemon `SmsWorker` per
   API process, started/stopped by FastAPI lifespan; polls `claim_due` →
   `process_pending` every `SMS_POLL_SECONDS`; survives per-message errors;
   `get_sms_worker()` is the "is SMS running" check bills.py uses.
7. **Billing hook** (`routers/bills.py`). `create_bill` (and `update` re-queue
   when mobile arrives later) calls `_maybe_queue_receipt` **after** commit:
   skips when `SMS_ENABLED` false, worker not running, customer missing, or
   customer mobile empty/malformed. Bill creation is never slowed or broken by
   SMS.
8. **API** (`routers/sms.py`, STAFF+). `GET /api/sms/messages` (store-scoped,
   optional `status`/`bill_id`, newest first), `GET /api/sms/status` (enabled /
   provider / configured / counts), `POST /api/sms/messages/{id}/resend`
   (FAILED-only, else 409; re-enqueues and it becomes SENDING→QUEUED per
   retry rules). All rows scoped through `effective_store_id`/`scoped_get`.

### Frontend

1. **`lib/api/sms.ts`** — `smsApi.list/status/resend`; `types.ts` adds
   `SmsMessage`, `SmsStatus`, `SmsStatusCounts`, `SmsStatusRead`.
2. **Billing** gets a **Receipt SMS column** per bill: Walk-in / no-receipt →
   muted; status badge `Sent` (green) / `Queued` (blue) / `Sending` (amber) /
   `Failed` (red) from the *latest* message for that bill; a **Resend** action on
   FAILED rows. A slim banner above the table shows truthful aggregate state
   when SMS is on: `sent 2, queued 1, failed 0`, or "Receipt SMS is on but not
   configured — set MSG91_AUTH_KEY …" (receipts stay QUEUED until then). SMS
   state loads **best-effort** (independent try/catch) — an SMS outage can never
   blank the Sales page.
3. No shenanigans: we never draw a SENT badge for QUEUED/FAILED; a disabled
   `SMS_ENABLED` hides the banner entirely (no guilt-trip UI).

## Honest model limits / operational behavior

- **Configured ≠ delivered.** `configured: true` only means the auth key is set.
- **Failure is visible.** Messages that exhaust retries stay `FAILED` in the
  Billing table and in `/api/sms/status` until resend succeeds.
- **This milestone cannot prove the customer READ the SMS** — `SENT` = provider
  ack accepted our send, nothing more.
- **First real send is a human task:** set `SMS_ENABLED=true` + `MSG91_AUTH_KEY`
  in `backend/.env`, send a one-₹ receipt to a real phone, and confirm the row
  flips SENT with the actual delivery on the handset. No fabricated delivery
  numbers were recorded here.

## Tests (+30)

- Backend `tests/test_sms.py` (28 new): no-DB settings validation + receipt
  builder + MSG91 gateway against a **monkeypatched httpx.post** (success ack,
  provider error retry, not-configured terminal); pg outbox lifecycle
  (enqueue/claim/process → SENT; exponential backoff; FAILED at max attempts;
  stale-SENDING reclaim; resend FAILED→QUEUED and 409 on SENT; status counts
  casing; API list/status/resend + store scoping/authz; bills auto-enqueue
  after commit, skip on SMS-disabled). Plus `test_migrations.py` +
  `test_startup_and_system.py` updated for head `e7a3c5f1b2d8`.
- Frontend `Billing.test.tsx` (+3): SMS banner + per-bill delivered badge,
  resend POSTs `/api/sms/messages/{id}/resend`, disabled SMS hides the banner.

## Gates (all green)

- Backend: `TEST_DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye_test" .venv/bin/pytest -q` → **568 passed** (540 prior + 28 new).
- `alembic check` → clean (single `e7a3c5f1b2d8` migration; dev DB `storeye` upgraded to head).
- Frontend: `npx tsc -b`, `npx vitest run` (**160 passed**), `npm run build` green.
- No fabricated delivery/perf numbers; offline-first; local PostgreSQL authoritative; SMS never blocks billing.

## Not yet verified (human at the store)

- A real MSG91 send acked end-to-end on a physical phone.
- Retry/backoff behaviour against a genuinely flaky mobile network at the store.

## Files touched

- `backend/app/models/sms_message.py` (new), `alembic/versions/e7a3c5f1b2d8_add_sms_messages_outbox.py` (new).
- `backend/app/services/sms/{__init__,gateway,receipt,outbox,manager}.py` (new) — MSG91 gateway, receipt builder, outbox service, daemon worker.
- `backend/app/api/routers/sms.py` (new), `backend/app/schemas/sms.py` (new) + `schemas/__init__.py` exports.
- `backend/app/api/routers/bills.py` — `_maybe_queue_receipt` after commit; `backend/app/main.py` — router + worker lifespan.
- `backend/app/core/config.py` — SMS settings + validators; `backend/requirements.txt` — httpx; `.env.example` — SMS section.
- `backend/tests/test_sms.py` (new), `test_migrations.py`, `test_startup_and_system.py`.
- Frontend: `lib/api/sms.ts` (new), `lib/api/types.ts` (SMS types), `pages/Billing.tsx` (SMS banner + column + resend), `pages/Billing.test.tsx` (+3).