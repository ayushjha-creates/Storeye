# EdgeRetail-IQ Database Schema

SQLite is the edge source of truth. Every syncable entity uses:

- UUID4 primary key (generated at the edge)
- UTC timestamps (`created_at_utc`, `updated_at_utc`)
- `store_id` (enables cloud RLS isolation)
- `sync_status` (`PENDING` / `SYNCED` / `FAILED`)

## Tables

| Table | Purpose | Key relations |
|-------|---------|---------------|
| `store` | Retail location (operational isolation unit) | root |
| `camera` | Camera devices per store | → store |
| `zone` | ROI zones (shelf/entrance/queue/billing/general) | → store, → camera |
| `product` | SKUs | → store |
| `planogram` | Expected facings of product in a zone | → store, → zone, → product |
| `inventoryledger` | Shelf/backroom stock | → store, → product, → zone |
| `visualevent` | Camera observations (shelf_gap, person, queue) | → store, → camera, → zone, → product |
| `queuemetric` | Queue count, wait, service time | → store, → zone, → camera |
| `replenishmenttask` | Human tasks with priority/revenue scores | → store, → product, → zone |
| `recommendation` | Structured decisions + confidence + signals | → store, source_event_ids |
| `user` | Store staff + role (ASSOCIATE/MANAGER/REGIONAL_ADMIN) | → store |

## Indexes

Indexed on: `store_id`, `zone_id`, `product_id`, `camera_id`, `event_type`,
`sync_status`, and `created_at_utc` (via app settings).

## Sync Model

- Edge writes locally → marks `PENDING`.
- Background worker upserts to Supabase by UUID (idempotent).
- High-frequency raw events remain local; rollups are synced.
- One-way: edge → cloud (no operational write-back in current scope).

## Migration Strategy

The domain model is the single source of truth
(`backend/app/core/models/database.py`). SQLite tables are created from it
via `SQLModel.metadata.create_all`. Future Postgres/Supabase schema will be
generated from the same domain definition to avoid drift.
