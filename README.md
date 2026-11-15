# ASTRA HEALTH

**Your Health. Your Baseline. Beyond Earth.**

ASTRA HEALTH is an offline-first educational prototype for monitoring synthetic astronaut health readings against the person's own activity-specific Earth patterns. It combines a premium space-health public site with a light mission-control dashboard, an authenticated REST API, and a persistent database.

> Research and classroom prototype only. It is not a medical device, has no clinical validation, does not diagnose or prescribe, and does not replace professional medical judgment. Roles in this application do not verify real-world credentials. Use synthetic data only.

## Included

- Responsive public landing page and product dashboard, one FastAPI origin.
- FastAPI, SQLAlchemy, Pydantic, SQLite default; optional MySQL via SQLAlchemy and PyMySQL.
- One-time first administrator setup, signed-in accounts, PBKDF2 password hashes, expiring HttpOnly session cookies, and role checks for restricted actions.
- Roles: Administrator, Medical Officer, Researcher, Astronaut.
- Astronaut and mission management, health data entry and filters, demo setup/reset.
- Earth baseline statistics and preserved versions, five-valid-reading minimum, explicit review and approval workflow.
- Same-activity personal-baseline assessment, explanation, alert review, and audit events.
- Database-backed dashboard and analytics, CSV export, printable report (browser print can save as PDF).
- Service-worker shell cache, IndexedDB API read cache, and an offline reading queue with server-side idempotency keys.
- Chart.js 4.5.1 when the CDN is available; a local SVG chart fallback continues to display without it.

## Architecture

```mermaid
flowchart LR
  Browser[HTML CSS JavaScript] -->|same-origin REST and HttpOnly session| API[FastAPI]
  Browser --> IDB[(IndexedDB cached reads and pending writes)]
  Browser --> SW[Service worker application cache]
  API --> ORM[SQLAlchemy]
  ORM --> DB[(SQLite by default or configured MySQL)]
  API --> Baseline[Baseline and comparison services]
  API --> Review[Role-controlled review and audit]
  Baseline --> DB
  Review --> DB
```

## Windows startup

1. Extract the ZIP to a writable folder.
2. Install Python 3.10+ and ensure `py` or `python` is on PATH.
3. Double-click `run.bat`. It creates `.venv`, installs pinned packages, chooses the next free local port beginning at 8000, waits for the API health check, then opens the correct URL. Keep the command window open.
4. On the first launch, create the initial Administrator account at the sign-in page. There is no default password or backdoor account. Choose a unique password of at least 12 characters.
5. In Settings & access, create a Medical Officer account for the reviewer workflow. Use separate accounts for each role as needed.

The first launch needs internet access for Python packages and the optional Chart.js CDN. When the CDN is unavailable, the local SVG charts still render. The app itself is served locally from FastAPI; there is no separate frontend server. The URL and `/docs` URL are printed by `run.bat`; if port 8000 is occupied, the launcher selects the next free port.

## Database configuration

SQLite is the zero-configuration default at `data/astra_health.db`. Tables are created at startup, and existing rows are retained. To use MySQL, copy `.env.example` to `.env`, install requirements, and set `DATABASE_URL` to:

```text
mysql+pymysql://USERNAME:PASSWORD@127.0.0.1:3306/astra_health
```

Create the `astra_health` database in MySQL first. Keep real credentials in the local `.env`; never put them in frontend files or the ZIP. The app loads `.env` at startup.

## Roles and authentication

The first account is created once through `/api/auth/bootstrap`; subsequent account creation is Administrator-only. Passwords use PBKDF2-HMAC-SHA256 with a random salt. The application stores only a hash of the session token in SQLite/MySQL; the browser receives the raw token only as a short-lived HttpOnly, SameSite=Strict cookie. Sign out revokes the server session and clears cached API reads.

- Administrator: account administration, demo reset, reviews, audit access, and all research operations.
- Medical Officer: baseline approval/rejection and alert review.
- Researcher: missions, astronaut profiles, baseline generation, demo setup, and data review access.
- Astronaut: read access and reading entry.

This is basic prototype access control, not a security-certified deployment. Run it on localhost with synthetic records.

## Demonstration flow

1. Sign in as Administrator or Researcher and choose **Load demo data** on the dashboard. This creates one synthetic mission, one astronaut, five valid RESTING readings, and five valid WALKING readings.
2. Choose **Generate baseline** or visit Personal baselines to generate the RESTING baseline. Fewer than five VALID Earth readings are rejected.
3. Sign in as Administrator or Medical Officer and approve the pending baseline in Medical review.
4. Return to the dashboard and choose **Simulate space reading**. The system compares only the matching RESTING baseline and explains each illustrative deviation.
5. Review the alert, inspect Analytics and Health history, and export or print a report.
6. **Reset demo data** asks for confirmation and removes the demo mission and astronaut's dependent readings, baselines, comparisons, and alerts. User accounts and audit records are retained.

The demo action is idempotent: repeating **Load demo data** does not generate a new random dataset.

## Personal baseline and assessment

For one astronaut and activity, the baseline service includes only `EARTH` + `VALID` records and requires at least five. Missing parameters remain missing and are excluded from that parameter's calculation; they are never replaced with zero. For each available measurement the system stores mean, median, sample standard deviation, minimum, maximum, and count. A generated version is `PENDING`; approval is a separate, permission-checked action. Previous versions remain available.

For space readings, the latest approved baseline matching both astronaut and activity is used. With nonzero SD, `z = (observed - mean) / SD`. A configurable `DEVIATION_THRESHOLD` defaults to 2.0. Zero-SD differences are flagged as differences without inventing an infinite z-score. Invalid and questionable readings do not become confirmed health events. A missing baseline is shown as unavailable. Alert levels are illustrative review prompts, not emergency classifications.

## Offline behavior

The service worker caches the application shell and IndexedDB caches successful API read responses for this synthetic-data prototype. If a reading POST fails because the server cannot be reached, the browser adds it to a local IndexedDB queue and labels it **Waiting to synchronize**. When the server returns, the app sends queued readings; a unique client request ID prevents duplicates, and the item is removed only after a successful server response. Other write actions require the server. Signing out clears the API read cache; pending readings remain queued so they are not silently discarded.

Only synthetic information should be used. This educational queue is not encrypted or appropriate for real health information or shared public computers.

## API

- Public: `GET /api/health`, `GET /api/auth/setup-status`, `POST /api/auth/bootstrap`, `POST /api/auth/login`.
- Session: `GET /api/auth/me`, `POST /api/auth/logout`.
- Users: `GET|POST /api/users` (Administrator only).
- Missions and astronauts: `/api/missions`, `/api/astronauts` plus item routes.
- Readings: `GET|POST /api/readings`; filters include astronaut, activity, environment, phase, from date, and to date. Legacy field names `systolic_bp`, `diastolic_bp`, `mission_phase`, `quality_status`, and `recorded_at` are accepted and included in reading responses.
- Baselines: `GET /api/baselines`, `POST /api/baselines/generate`, `POST /api/baselines/{id}/review`.
- Reviews and analytics: `/api/alerts`, `/api/assessments`, `/api/analytics`, `/api/audit-logs`, `/api/dashboard`, `/api/history`.
- Exports and demo: `GET /api/reports/readings.csv`, `POST /api/demo/setup`, `/api/demo/simulate-space`, `/api/demo/reset`.

FastAPI documentation is available at `/docs` after startup. Authenticated endpoints require a signed-in application session.

## Tests

From the extracted project folder:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

The tests exercise page and health routes, first-run setup/login and role access, demo idempotency/reset, baseline minimum and approval, activity matching, data quality exclusion, alerts, and CSV export.

## Limitations

No real sensor hardware, clinical protocols, emergency classifications, remote multi-device sync, or verified clinician credentials are integrated. Offline reading entry and duplicate-safe sync are designed for the local synthetic demonstration only. Analytics report stored measurements and do not establish medical findings.
