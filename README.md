# DeltaWatch — Website Change Intelligence

DeltaWatch monitors **public web pages**, captures rendered snapshots with Playwright, filters configured noise, compares text and screenshots, and records meaningful changes in a searchable dashboard. This repository contains the React/Vite frontend, FastAPI backend, SQLite persistence layer, scheduler/worker pool, notification integrations, and automated backend tests.

## Product flow

1. Add a public page and choose a check interval (15 minutes to 24 hours).
2. DeltaWatch renders it in Chromium, captures visible text and a viewport screenshot, and stores the first capture as a baseline.
3. Later checks compare the current text with the latest snapshot. You can tune a CSS region, ignore selectors, exact volatile phrases, and the minimum change percentage. Changing the watched URL/region/noise rules automatically takes a fresh baseline instead of alerting on the configuration change itself.
4. Meaningful differences create an event with added/removed text, before/after snapshots and an amplified pixel-difference image.
5. Configure a Discord webhook, a Telegram `sendMessage` URL, or an email recipient (SMTP settings are required for email). Repeat identical captures do not send duplicate alerts.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer and npm
- Chromium dependencies required by Playwright (on Linux, use Playwright's `--with-deps` installer if packages are missing)

## Run locally on macOS/Linux

Open two terminal tabs from the project directory.

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
# Start the API and scheduler
uvicorn app.main:app --reload --port 8000
```

The API docs are available at `http://localhost:8000/docs`. Data and artifacts are written to `backend/data/` by default.

On Linux servers that do not have browser system libraries installed, use `python -m playwright install --with-deps chromium` before starting the service. Running the application as a normal non-root user is recommended so Chromium's sandbox remains enabled.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend expects the API at `http://localhost:8000` by default. For another API URL, create `frontend/.env` with:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Restart Vite after changing environment variables. Make sure the backend's `DELTAWATCH_CORS_ORIGINS` includes the exact frontend origin.

## Run the automated tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

The automated suite uses temporary SQLite databases and mocks external browser/SMTP work; it does not send traffic to real websites or deliver email. It covers API CRUD, response redaction, URL safety rules, text normalization, diff generation, monitoring state transitions and email notification behavior.

## Configuration

The backend reads environment variables directly. Copy `backend/.env.example` to `backend/.env` as a reference, then export the values in the shell that starts Uvicorn. The example file is documentation only; it is not auto-loaded by Python.

| Variable | Default | Purpose |
|---|---|---|
| `DELTAWATCH_DATA_DIR` | `backend/data` | SQLite DB and screenshot artifact root |
| `DELTAWATCH_DB_PATH` | derived from data dir | Optional explicit SQLite file path |
| `DELTAWATCH_ARTIFACTS_DIR` | `backend/data/artifacts` | Screenshot and diff image root |
| `DELTAWATCH_CORS_ORIGINS` | localhost Vite origins | Comma-separated allowed browser origins |
| `DELTAWATCH_CHECK_TIMEOUT_SECONDS` | `25` | Navigation timeout for a page capture |
| `DELTAWATCH_WORKERS` | `3` | Maximum concurrent monitor checks |
| `DELTAWATCH_ENABLE_SCHEDULER` | `true` | Enable the automatic due-check scheduler |
| `DELTAWATCH_PUBLIC_APP_URL` | `http://localhost:5173` | Base URL embedded in alert links; set this to the deployed frontend URL in production |
| `DELTAWATCH_CHROMIUM_EXECUTABLE` | Playwright-managed Chromium | Optional path to an installed Chromium binary |
| `DELTAWATCH_CHROMIUM_NO_SANDBOX` | `false` | Explicitly disables Chromium sandbox; avoid unless required by a container environment |
| `DELTAWATCH_SMTP_HOST` | blank | SMTP host; required for email alerts |
| `DELTAWATCH_SMTP_PORT` | `587` | SMTP port |
| `DELTAWATCH_SMTP_USERNAME` | blank | SMTP username, if required |
| `DELTAWATCH_SMTP_PASSWORD` | blank | SMTP password or app password, if required |
| `DELTAWATCH_SMTP_FROM` | username or blank | Sender address for email alerts |
| `DELTAWATCH_SMTP_USE_TLS` | `true` | Use STARTTLS for SMTP |

Example shell setup for a deployment (do not commit real credentials):

```bash
export DELTAWATCH_SMTP_HOST="smtp.example.com"
export DELTAWATCH_SMTP_PORT="587"
export DELTAWATCH_SMTP_USERNAME="alerts@example.com"
export DELTAWATCH_SMTP_PASSWORD="your-app-password"
export DELTAWATCH_SMTP_FROM="alerts@example.com"
export DELTAWATCH_PUBLIC_APP_URL="https://your-frontend.example"
```

Email configuration is optional. Without SMTP settings, the UI will not allow an email recipient to be saved; Discord and configured Telegram endpoints work independently.

## Safety and operating notes

- The service rejects local/internal hostnames, private/loopback/link-local/reserved IPs, URL-embedded credentials, and non-HTTP(S) page URLs. It resolves hostnames before navigation and validates browser requests/redirects as defense in depth. Do not expose the app to untrusted users as a multi-tenant public service without additional process/network isolation and authentication.
- Only public pages should be monitored. Respect the target site's terms, robots guidance, and rate limits; do not attempt to bypass logins, CAPTCHAs or access controls.
- Browser captures have a bounded timeout, fixed viewport and limited worker concurrency. A CAPTCHA/403/429, missing page, server outage or absent selector is reported as blocked/error rather than a confirmed content change. WebSocket connections are disabled during capture to reduce SSRF paths; highly dynamic pages that depend on WebSockets may therefore display less data.
- Text differences determine whether an event is meaningful. Screenshot differences are supporting visual evidence and can contain layout/animation noise.
- SQLite and screenshots are stored locally. Deleting a monitor removes its snapshots and events from SQLite; artifact files may remain on disk and can be periodically cleaned from `backend/data/artifacts/` when no longer needed.
- The default app has no user authentication. Keep it bound to a trusted environment; add authentication and isolated browser workers before deployment to a shared/public environment.

## Architecture

```text
React + Vite dashboard
        │ REST / JSON
        ▼
FastAPI API ─── SQLite (monitors, snapshots, events)
        │
        ├── scheduler (poll due checks)
        └── bounded worker pool
                │
                ├── Playwright / Chromium capture
                ├── selector + ignore-text normalization
                ├── text hash + add/remove diff
                ├── Pillow screenshot diff
                └── Discord / Telegram / SMTP alerts
```

## Project layout

```text
DeltaWatch/
├── README.md
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI routes and schema validation
│   │   ├── db.py              # SQLite persistence and migrations
│   │   ├── service.py         # Scheduler, concurrency and state transitions
│   │   ├── check_engine.py    # Playwright capture, text and image diffs
│   │   ├── security.py        # URL/SSRF and webhook validation
│   │   ├── notifications.py   # Discord, Telegram and SMTP delivery
│   │   └── config.py
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html
    ├── package.json
    └── src/
        ├── App.jsx
        ├── api.js
        ├── main.jsx
        └── styles.css
```
