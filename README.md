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
