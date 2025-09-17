# SDT Repricer Platform

An event-driven Amazon SP-API repricer engineered for Amazon Europe marketplaces (DE, FR, NL, BE, IT).
The platform optimizes Buy Box wins while respecting per-SKU floor prices, supports business pricing,
and ships with an operational dashboard, alerting, and Dockerized deployment for local reliability.

## Features

- **SP-API Integration** – Async HTTP client with automatic token refresh, exponential back-off, and
  adaptive rate-limit handling for pricing, feeds, and notifications.
- **Dynamic Repricing Engine** – Marketplace-aware logic that undercuts competitors responsibly,
  ramps prices while holding the Buy Box, and enforces configurable daily change ceilings.
- **Floor Price Governance** – Hourly CSV ingestion with freshness validation and automatic alerting
  when feeds are stale or missing.
- **Operational Dashboard** – FastAPI + vanilla JS UI showing Buy Box metrics, health telemetry,
  alerts, manual controls, and settings management with live refresh.
- **Monitoring & Alerting** – Persistent alert log, SMTP-ready notifications hook, and automated
  warnings for critical failure scenarios (FTP, API errors, pricing skips).
- **Scalable Scheduling** – Event-driven scheduler reacting to SP-API notifications with scheduled
  fallbacks covering ~30k SKUs per marketplace.
- **Extensible Architecture** – Modular services with clear boundaries, async database access, and
  easily swappable pricing strategies or marketplace coverage.
- **Test & Simulation Mode** – Sandbox-friendly flows for loading sample catalog data, rehearsing
  repricing profiles, and reviewing run telemetry without touching production listings.

## Architecture Overview

The codebase is organized under `sdtrepricer/app`:

| Module | Description |
| --- | --- |
| `core/` | Configuration, logging, and database factories. |
| `services/` | SP-API client, repricing engine, scheduler, FTP ingestion, and alert helpers. |
| `api/` | FastAPI routers for dashboard metrics, settings, and manual actions. |
| `templates` & `static/` | Internal dashboard UI assets. |
| `tests/` | Pytest-based unit tests for pricing logic, repricer orchestration, and API responses. |

A detailed component diagram is available in [`docs/architecture.md`](docs/architecture.md).

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional but recommended)
- Access to Amazon SP-API credentials (LWA + role ARN) and hourly FTP feeds per marketplace

### Local Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
# Edit .env with database credentials, SP-API keys, and FTP paths
alembic upgrade head  # optional: use built-in init on app startup otherwise
uvicorn sdtrepricer.app:app --reload
```

The application automatically creates database tables and seeds the marketplace catalog on startup.
FastAPI serves the dashboard at `http://localhost:8000/`.

### Docker Compose

```bash
docker-compose up --build
```

This launches Postgres 15 and the repricer application with auto-reload. Configure your FTP feed
mount into the `app` container at `/app/ftp_feeds` or update `FTP_ROOT`.

### Running Tests & Quality Checks

```bash
make pytest
make lint
```

### Configuration

Environment variables follow the `.env.example` template and map directly to `Settings` fields. Key
options include:

- `DATABASE_URL`: Async SQLAlchemy DSN (defaults to Postgres).
- `FTP_ROOT`: Directory containing hourly floor price CSVs named `<country>_floor_prices.csv`.
- `MAX_PRICE_CHANGE_PERCENT`: Daily price-change guardrail enforced by the repricing strategy.
- `SP_API_*`: LWA + AWS role credentials used by the SP-API client.

## FTP Floor Files

Each marketplace expects a CSV named `{marketplace}_floor_prices.csv` with columns:

```
SKU,ASIN,MIN_PRICE,MIN_BUSINESS_PRICE
ABCD123,ASIN0001,19.99,18.50
```

Feeds older than the configurable threshold (default 90 minutes) trigger alerts and block repricing
runs until refreshed.

## Test Mode & Simulation

Use the local/sandbox "test mode" to validate pricing logic end-to-end without publishing real
updates to Amazon. The workflow consists of populating sample data, selecting a repricing profile,
triggering a simulation, and reviewing the resulting telemetry.

### Upload Sample Data

1. **Seed sample SKUs** – The startup hook inserts marketplace rows, so you can associate SKUs by
   code instead of hard-coding IDs:

   ```sql
   -- Populate a defensive and an aggressive SKU in the Germany marketplace
   INSERT INTO skus (sku, asin, marketplace_id, min_price, min_business_price, hold_buy_box)
   SELECT 'SKU-DE-TEST-1', 'ASINDE001', id, 19.99, 18.50, TRUE FROM marketplaces WHERE code = 'DE';
   INSERT INTO skus (sku, asin, marketplace_id, min_price, min_business_price, hold_buy_box)
   SELECT 'SKU-DE-TEST-2', 'ASINDE002', id, 17.49, 16.00, FALSE FROM marketplaces WHERE code = 'DE';
   ```

2. **Drop floor prices** – Place a CSV per marketplace under `ftp_feeds/` using the loader naming
   convention. For example `ftp_feeds/de_floor_prices.csv`:

   ```csv
   SKU,ASIN,MIN_PRICE,MIN_BUSINESS_PRICE
   SKU-DE-TEST-1,ASINDE001,18.00,17.00
   SKU-DE-TEST-2,ASINDE002,15.50,14.75
   ```

3. **(Optional) Upload via the UI** – The dashboard ships with a "Bulk price file" form that
   forwards CSV/XML payloads through `/api/actions/bulk-upload`. Point it at the Amazon sandbox (see
   below) to rehearse full feed submission.

### Enable Test Mode

Run the stack with sandbox credentials so the SP-API client talks to Amazon's non-production
endpoint and records responses locally:

```bash
export SP_API_ENDPOINT="https://sandbox.sellingpartnerapi-eu.amazon.com"
export SP_API_CLIENT_ID="<sandbox-client-id>"
export SP_API_CLIENT_SECRET="<sandbox-client-secret>"
export SP_API_REFRESH_TOKEN="<sandbox-refresh-token>"
uvicorn sdtrepricer.app:app --reload
```

Leaving the production endpoint untouched while using sandbox credentials prevents live offers from
changing and keeps the emitted `price_events` tagged with the `repricer` reason for audit review.

### Adjust Dynamic Price-Increase Guardrails

The dashboard exposes a configuration form powered by `/api/settings`. Update test-mode guardrails
directly from the UI or via API calls to rehearse aggressive vs. conservative strategies:

```bash
curl -X POST http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{
        "max_price_change_percent": 15,
        "step_up_percentage": 3.5,
        "step_up_interval_hours": 4
      }'
```

Behind the scenes these values land in the `system_settings` table and are pulled into the
`PricingStrategy` constructor so daily guardrails and Buy Box step-ups respond instantly.

### Define and Apply Repricing Profiles

Treat a "repricing profile" as a named bundle of guardrails. Persist reusable profiles alongside the
live configuration so you can switch strategies between simulations:

```sql
INSERT INTO system_settings (key, value)
VALUES
  ('profile:defensive', '{"max_price_change_percent": 10, "step_up_percentage": 1.5, "step_up_interval_hours": 8}'),
  ('profile:aggressive', '{"max_price_change_percent": 25, "step_up_percentage": 5, "step_up_interval_hours": 2}')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
```

When you're ready to test a profile, fetch its JSON payload and post it to `/api/settings` to make it
the active configuration. The scheduler will pick up the new limits on the next tick without
restarting the service.

### Run a Simulation and Review Outcomes

1. Trigger a run in test mode using the dashboard "Trigger Repricing" form or curl:

   ```bash
   curl -X POST http://localhost:8000/api/actions/manual-reprice \
     -H 'Content-Type: application/json' \
     -d '{"marketplace_code": "DE", "skus": []}'
   ```

2. Open the dashboard to monitor progress. The **System Health** panel exposes `scheduler.stats`,
   while **Alerts** surface stale feeds or missing floors detected during the run.

3. Inspect the relational telemetry:

   ```sql
   SELECT * FROM repricing_runs ORDER BY started_at DESC LIMIT 5;
   SELECT sku, new_price, context ->> 'target_competitor'
   FROM price_events
   ORDER BY created_at DESC LIMIT 5;
   ```

Combine the dashboard snapshot with the SQL queries to interpret simulation results—processed SKU
counts, price deltas, and competitor context—before promoting a profile to production.

## Extensibility Roadmap

- Plug additional marketplaces by extending `Settings.marketplace_ids` or seeding extra records.
- Support multi-account SP-API credentials by namespacing marketplace definitions per account.
- Swap pricing strategies by injecting a new `PricingStrategy` implementation (e.g., category-based).
- Integrate notification delivery (SMTP, Slack, PagerDuty) via the alert service.

## Reliability Notes

- Scheduler processes SP-API notifications and scheduled fallbacks to keep coverage high without
  exceeding rate limits.
- All price updates are logged in `price_events` with contextual metadata for audits.
- Error paths emit alerts and persist diagnostic data, ensuring operators have actionable insights.

## License

Internal use only. Adapt and extend per your organizational policies.
