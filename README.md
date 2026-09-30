# Thinklee - CliniOps

A multi-tenant, natural-language business intelligence platform. Connect your data, point an
AI agent at it, then ask questions in plain language and get back explained answers, charts
and dashboards.

CliniOps is the clinical-operations branding of the Thinklee platform; the application code is
domain-neutral and works for any tabular or document-based dataset.

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Core concepts](#core-concepts)
- [Data sources](#data-sources)
- [The query pipeline](#the-query-pipeline)
- [Onboarding](#onboarding)
- [Database and migrations](#database-and-migrations)
- [API reference](#api-reference)
- [Deployment notes](#deployment-notes)
- [Known issues](#known-issues)

---

## What it does

The product is built around a four-step journey, which the in-app tour and the Help & Setup
checklist both follow:

1. **Connect your data** - link a database, or upload CSV/Excel files and documents.
2. **Create an AI agent** - bind an agent to specific tables or documents and tune the prompts
   that shape how it answers.
3. **Ask questions** - Co-Pilot turns natural language into SQL (or a document retrieval), runs
   it, and explains the result. Graph Query does the same but returns a chart.
4. **Build dashboards** - save useful questions as widgets and arrange them into a dashboard.

Supporting features: per-agent business glossaries, thumbs-up/down feedback that feeds back
into future answers as few-shot examples, a query log analyser, organization user management
with invitations, and a super-admin console.

---

## Architecture

A Flask monolith with server-rendered Jinja templates and a JSON API. There is no build step
and no frontend framework - pages are Jinja + Tailwind (via CDN) + vanilla JS calling the API
with a JWT.

```
run.py
  └── app/__init__.py          create_app() - registers blueprints, mail, extensions
        ├── routes/            blueprints; routes map to controller functions
        ├── controllers/       request handling, validation, persistence
        ├── services/          LLM pipelines (SQL generation, RAG, synthesis, routing)
        ├── models/            SQLAlchemy models
        ├── utils/             shared helpers (connections, embeddings, ingestion)
        └── templates/         Jinja pages; base.html includes the sidebar and tour
```

**Request flow for a question:**

```
Browser ──JWT──> /api/query/copilot/<agent_id>
                      │
                      ├── is_agent_queryable()      can this agent be queried, and how?
                      ├── get_similar_feedback()    FAISS over past rated answers
                      ├── glossary lookup
                      │
                      ├── structured ──> query_sql_agent   NL → SQL → execute
                      │                  └── synthesize_result()   rows → prose
                      │
                      └── unstructured ─> query_analyzer_agent     routes the question
                                          ├── analytical  (SQL over event_fact)
                                          ├── hybrid      (facts + explanation)
                                          └── semantic    (MMR retrieval over chunks)
                      │
                      └── QueryLog written with embeddings, follow-ups generated
```

**Two auth tracks run side by side.** `flask_jwt_extended` guards every `/api/*` endpoint via
`@jwt_required()`; page routes authenticate off the JWT stashed in the Flask session at login,
using the guards in `app/utils/auth_guards.py`. The `/admin/*` console has its own session
check. Logging in populates all of them.

Page guards:

| Guard | Behaviour |
|---|---|
| `login_required` | Signed in **and** past onboarding. Otherwise redirects to `/auth?next=<path>`, `/reset-password` or `/org-setup`. |
| `login_required_no_setup` | Signed in, organization setup still allowed to be pending - used by `/org-setup` itself. |
| `redirect_if_authenticated` | Sends signed-in visitors off `/` and `/auth` to wherever they belong. |

The only pages reachable without signing in are `/`, `/auth`, `/reset-password` and `/logout`.
Onboarding cannot be skipped by typing a later URL: the cascade
(reset password → create organization → app) is enforced on every guarded page.

**Embeddings are local** (`sentence-transformers`, `intfloat/multilingual-e5-large`);
**generation is OpenAI** (`gpt-4`, `gpt-4o-mini`). Azure and Claude branches exist in the
services but are commented out.

---

## Quick start

### Prerequisites

- **Python 3.12+** (developed against 3.14)
- An **OpenAI API key**
- ~3 GB free disk - the embedding model is downloaded on first run
- Optional, only for SQL Server / Azure SQL / RDS-for-SQL-Server:
  [**ODBC Driver 18 for SQL Server**](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
  (`msodbcsql18`)

### Install

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

> On Linux/macOS use `source .venv/bin/activate`.

### Configure

Create a `.env` file in the project root - see [Configuration](#configuration) for the full list:

```bash
cp .env.example .env
```

At minimum set `OPENAI_API_KEY`, `SECRET_KEY` and `JWT_SECRET_KEY`.

### Initialise the database

```bash
python -m flask --app run:app db upgrade
```

### Run

```bash
python run.py
```

The app serves on `http://localhost:5000`. Sign up at `/auth`, verify the emailed OTP,
complete organization setup, and the product tour starts automatically on first login.

> **First start is slow.** The `intfloat/multilingual-e5-large` embedding model (~2.2 GB) is
> downloaded and loaded into memory before the app becomes responsive. Subsequent starts load
> it from the local Hugging Face cache.

### Create a super admin

```bash
python create_super_admin.py
```

Interactive; prompts for username, email, password and token quota. The resulting account can
sign in at `/admin/login`.

---

## Configuration

All configuration is read from environment variables (via `.env`, loaded by `python-dotenv`).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | - | SQL generation, RAG synthesis, prompt generation |
| `SECRET_KEY` | **Yes** | `supersecret` | Flask session signing |
| `JWT_SECRET_KEY` | **Yes** | `jwtsecret` | API token signing |
| `MAIL_SERVER` | for email | `smtpout.secureserver.net` | OTP and invitation delivery |
| `MAIL_PORT` | for email | `587` | |
| `MAIL_USE_TLS` | for email | `True` | |
| `MAIL_USERNAME` | for email | - | |
| `MAIL_PASSWORD` | for email | - | |
| `MAIL_DEFAULT_SENDER_NAME` | no | `Thinklee` | |
| `MAIL_DEFAULT_SENDER_EMAIL` | no | - | |

> The defaults for `SECRET_KEY` and `JWT_SECRET_KEY` are hardcoded fallbacks in
> `app/config.py`. **Set both explicitly before deploying** - leaving them at the defaults
> lets anyone forge a session or an API token.

> `EMBEDDING_MODEL` appears in `.env` but is **not currently read** - the model name is
> hardcoded in `app/utils/embeding_utils.py`. Change it there if you need a different one.

The database URI is also hardcoded in `app/config.py` (`sqlite:///thinkly.db`, resolved
relative to `instance/`). Point it at Postgres or MySQL there for a real deployment.

---

## Project structure

```
Thinklee-CliniOps/
├── run.py                       entrypoint; creates the app and serves it
├── create_super_admin.py        interactive super-admin bootstrap
├── requirements.txt
├── instance/thinkly.db          SQLite database (default)
├── migrations/                  Alembic migrations (28 revisions)
└── app/
    ├── __init__.py              create_app(), blueprint registration
    ├── config.py                secrets, database URI
    ├── extensions.py            db, jwt, bcrypt, migrate, mail
    ├── models/
    │   ├── user.py              User, Role, EmailOTP
    │   ├── organization.py      Organization, OrganizationMember
    │   ├── data_connection.py   DataSourceConnection
    │   ├── agent.py             Agent, AgentTableMap, AgentFileMap, BusinessGlossary
    │   ├── table_metadata.py    schema of an uploaded/imported table
    │   ├── file_metadata.py     an uploaded document
    │   ├── chunks.py            document chunks + embeddings
    │   ├── event_fact.py        extracted timestamped events
    │   ├── dashboard.py         Dashboard, DashboardWidget
    │   └── query_log.py         questions, answers, feedback, embeddings
    ├── routes/
    │   ├── page_routes.py       server-rendered pages
    │   ├── auth_routes.py       /api/auth/*
    │   ├── api_routes.py        /api/data, /agent, /query, /dashboard, /profile, /org
    │   ├── admin_api_routes.py  /api/admin/* (super admin)
    │   └── admin_frontend_routes.py  /admin/* console
    ├── controllers/             one per domain area
    ├── services/
    │   ├── query_sql_agent.py       NL → SQL for structured agents
    │   ├── query_rag_agent.py       document retrieval + answering
    │   ├── query_analyzer_agent.py  routes a question: analytical / hybrid / semantic
    │   ├── analytical_engine.py     guarded SQL over event_fact
    │   ├── hybrid_engine.py         SQL facts + LLM explanation
    │   ├── graph_query_agent.py     NL → chart-shaped SQL
    │   ├── data_synthesizer_agent.py rows → natural language
    │   ├── synthesizer.py           conversational response shaping
    │   └── followup_query_ageny.py  suggested follow-up questions
    ├── utils/
    │   ├── db_connections.py    URL building + connection probing for every source type
    │   ├── s3_utils.py          S3 listing and object fetch
    │   ├── embeding_utils.py    embeddings + FAISS feedback retrieval
    │   ├── unstructured_ingest.py  text extraction and chunking
    │   ├── agent_utils.py       is_agent_queryable()
    │   ├── prompt_generation.py LLM-assisted prompt authoring
    │   └── decorators.py        role guards
    ├── templates/               Jinja pages
    │   ├── base.html            layout; includes sidebar + product tour
    │   ├── sidebar.html         navigation
    │   ├── product_tour.html    first-login guided walkthrough
    │   └── …                    one per page
    └── static/                  logo, CSV/XLSX templates
```

> Templates ending in `_old`, `_new` or `_working` are earlier iterations that are no longer
> routed to. Only the un-suffixed versions are live.

---

## Core concepts

### Organizations, users and roles

`Organization` → `OrganizationMember` (`org_admin` / `org_user`) → `User`. `organization_id`
is denormalised onto nearly every table, and controllers scope queries by it - this is the
tenancy boundary.

A separate `Role` table carries the global `superadmin` role used by the `/admin` console.

**Sign-up flow:** register → email OTP → organization setup → home. Invited users receive a
temporary password and are forced through a reset before they reach the app.

### Connections

A `DataSourceConnection` is a saved connection owned by an organization. Credentials are
base64-encoded at rest (see [Known issues](#known-issues)). The supported types are listed
under [Data sources](#data-sources).

### Agents

An `Agent` bundles LLM settings with three editable prompt triples - `sql_*`, `rag_*` and
`synthesizer_*` (each a system prompt, a task and an instruction) - plus a data binding.
`agent_type` is:

- **`structured`** - bound either to a `DataSourceConnection` (queries the live database) or
  to a set of uploaded tables (queries the app's own database).
- **`unstructured`** - bound to a set of uploaded documents; answered by retrieval.

Each agent can carry a **business glossary** of terms and definitions, injected into every
prompt so the model uses your organization's vocabulary.

---

## Data sources

| Type | `source_type` | How it is queried |
|---|---|---|
| PostgreSQL | `postgresql` | direct SQL |
| MySQL / MariaDB | `mysql` | direct SQL |
| Microsoft SQL Server | `mssql` | direct SQL (needs ODBC driver) |
| SQLite | `sqlite` | direct SQL |
| Snowflake | `snowflake` | direct SQL |
| **AWS RDS** | `rds` | direct SQL; `rds_engine` selects PostgreSQL / MySQL / MariaDB / SQL Server |
| **Azure SQL Database** | `azure_sql` | direct SQL, encryption enforced |
| **Amazon S3** | `s3` | **not queried directly** - browse and import (below) |
| CSV / Excel upload | - | landed into `org_<id>_<table>` tables |
| PDF / DOCX / PPTX / TXT / HTML / MD | - | chunked and embedded for retrieval |

URL construction and connection probing for every SQL type live in
`app/utils/db_connections.py`, shared by the connection tester and both query agents.

### Uploading files

Under **Data Management → Upload Data**:

- **Structured** (CSV, XLSX) - a new table needs a *metadata file* describing its schema
  (`column_name`, `data_type`, `description`); download the template from the upload dialog.
  Uploading into an existing table validates the columns match. ZIP archives are expanded
  server-side.
- **Unstructured** (PDF, DOCX, PPTX, TXT, MD, HTML, CSV) - text is extracted, split into
  ~1000-character chunks with 100 characters of overlap, embedded, and stored for retrieval.

### Working with S3

S3 holds files, not tables, so it cannot back a SQL agent. Instead:

1. Save an S3 connection (access key, secret, region, bucket, optional prefix).
2. Click **Browse** on the connection row to list CSV / Excel / JSON objects.
3. Select files and import them into an existing table - they go through the same ingestion
   path as a manual upload.
4. Point an agent at the resulting table.

Objects above 200 MB and non-tabular formats are listed but not importable. If no explicit
keys are supplied, boto3 falls back to the instance role, which is the right way to run this
on EC2.

---

## The query pipeline

### Structured agents

`generate_sql_and_query()` reflects the schema, builds a prompt from the agent's `sql_*`
prompts plus the glossary, chat history and similar past feedback, asks the model for JSON
`{"sql": "..."}`, verifies it is a `SELECT`, executes it, and hands the rows to
`synthesize_result()` for a natural-language answer.

The dialect named in the prompt is the *underlying* engine - an agent on RDS PostgreSQL is
told to write PostgreSQL, not "RDS".

### Unstructured agents

`analyze_query()` first classifies the question into JSON carrying `routing`,
`operation_type`, extracted entities and the user's language, then dispatches:

| Routing | Behaviour |
|---|---|
| `analytical` | LLM writes SQL against the `event_fact` table. Validated against a table/column allowlist, forced to `SELECT`, stripped of comments/unions/multiple statements, and scoped to the agent's own files before execution. |
| `hybrid` | Computes facts with SQL, then has the model explain them without recomputing any numbers. |
| `semantic` | MMR retrieval over document chunks (relevance balanced against redundancy), context budgeted to ~1800 tokens, then answered. |

### Feedback loop

Every question and answer is written to `query_logs` with embeddings. Rating an answer stores
the comment and its embedding; subsequent questions retrieve the most similar past feedback
via FAISS and inject it as few-shot guidance.

---

## Onboarding

New users get a **guided product tour** on their first visit to `/home`. It spotlights the
real navigation and walks through the four-step journey. Whether it has been seen is stored
per user in `User.tour_completed_at`, so it does not reappear in a different browser.

- Skipping and finishing both count as seen.
- **Help & Setup** (`/steps`) shows a live checklist of the four steps with real counts from
  your organization, and a **Replay tour** button.
- Steps whose target is absent on the current page are skipped automatically, so the tour can
  be replayed from anywhere.

To re-trigger the tour for a user: `POST /api/profile/tour/reset`.

---

## Database and migrations

Managed with Flask-Migrate (Alembic). 18 tables:

```
user, role, user_roles, email_otps
organizations, organization_members
data_source_connections
table_of_uploadedfiles_metadata, file_metadata, file_chunks, event_fact
agents, agent_table_map, agent_file_map, business_glossary
dashboard, dashboard_widget
query_logs
```

Plus one `org_<organization_id>_<table_name>` table per uploaded dataset, created dynamically
by `pandas.to_sql`.

```bash
python -m flask --app run:app db upgrade
```

```bash
python -m flask --app run:app db migrate -m "describe the change"
```

> **Caution:** `run.py` calls `db.create_all()` at import time, which creates tables directly
> from the models and bypasses Alembic. On a fresh database this leaves `alembic_version`
> empty, so the next `db upgrade` tries to replay the initial migration against tables that
> already exist and fails. If that happens, `db stamp head` once to reconcile. Removing the
> `create_all()` call is the real fix.

---

## API reference

All `/api/*` endpoints require `Authorization: Bearer <jwt>` unless noted. The token comes
from `POST /api/auth/login` and is stored in `localStorage` under `token`.

### Auth - `/api/auth`

| Method | Path | Purpose |
|---|---|---|
| POST | `/register` | Create an account (requires a valid OTP) |
| POST | `/send-otp` | Email a signup OTP |
| POST | `/verify-otp` | Verify a login OTP |
| POST | `/verify-temp-password` | Validate an invited user's temporary password |
| POST | `/reset-password` | Set a new password |
| POST | `/login` | Returns a JWT and a redirect target |
| POST | `/logout` | Clear the session |
| GET | `/me` | Current identity |

### Data - `/api/data`

| Method | Path | Purpose |
|---|---|---|
| POST | `/save-connection` | Create a data source |
| PUT | `/update-connection/<id>` | Edit one |
| DELETE | `/delete-connection/<id>` | Soft-delete one |
| GET | `/get-data-sources` | List them |
| GET | `/get-data-source/<id>` | Fetch one |
| POST | `/test-connection` | Probe unsaved credentials |
| POST | `/test-saved-connection/<id>` | Probe a stored connection, persist the status |
| POST | `/upload-file` | Upload structured or unstructured files |
| GET | `/get-uploaded-files` | List uploaded files |
| GET | `/get-existing-tables` | List tables available to this org |
| DELETE | `/delete-file/<id>` | Soft-delete a file and its chunks |
| GET | `/s3/<id>/objects` | List bucket contents |
| POST | `/s3/<id>/import` | Import selected objects into a table |

### Agents - `/api/agent`

`POST /create`, `GET /get-agents`, `GET /get/<id>`, `PUT /update/<id>`, `DELETE /delete/<id>`,
`POST /generate-prompts`, `GET /stats`, `GET /files`, and the glossary endpoints
(`POST /glossary/create`, `GET /glossary/list`, `GET /glossary/<id>`,
`POST /glossary/bulk-upload`, `DELETE /glossary/delete/<id>`).

### Query - `/api/query`

| Method | Path | Purpose |
|---|---|---|
| POST | `/copilot/<agent_id>` | Ask a question; returns answer, SQL, follow-ups, `query_id` |
| POST | `/graph/<agent_id>` | Ask for a chart |
| POST | `/graph/sqltograph/<agent_id>` | Render a chart from supplied SQL |
| POST | `/graph/drilldown` | Drill into a chart segment |
| POST | `/feedback/submit` | Rate an answer |
| GET | `/logs` | Query history |

### Dashboards - `/api/dashboard`

`POST /create`, `GET /list`, `GET /<id>`, `PUT /update/<id>`, `PUT /edit/<id>`,
`DELETE /delete/<id>`, `POST /<id>/widget`, `POST /<id>/widgets/bulk-save`,
`GET /<id>/widgets`, `DELETE /<id>/widget/<widget_id>`, `PUT /<id>/layout`.

### Profile and organization

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/profile/me` | Current user and organization |
| PUT | `/api/profile/user` | Update the profile |
| GET | `/api/profile/setup-progress` | Onboarding checklist with real counts |
| POST | `/api/profile/tour/complete` | Mark the tour seen |
| POST | `/api/profile/tour/reset` | Replay the tour |
| POST | `/api/org/setup` | Create the organization |
| GET | `/api/org/users` | List members |
| POST | `/api/org/users/invite` | Invite a member |
| PUT/DELETE | `/api/org/users/<id>` | Update or remove a member |
| POST | `/api/org/users/bulk-*` | Bulk role change, removal, resend invites |

### Super admin - `/api/admin`

`GET /stats`, `GET /roles`, `GET /users`, `POST /users`, `GET|PUT|DELETE /users/<id>`,
`GET /users/search`. All require the `superadmin` role.

---

## Deployment notes

- `run.py` starts the dev server with `debug=True` on `0.0.0.0:5000`. **Do not use it in
  production** - serve `run:app` behind gunicorn or waitress with a reverse proxy.
- Set `SECRET_KEY` and `JWT_SECRET_KEY` to real random values.
- Move off SQLite: change `SQLALCHEMY_DATABASE_URI` in `app/config.py`.
- For SQL Server, Azure SQL or RDS-for-SQL-Server, install `msodbcsql18` on the host. The
  application auto-detects the newest installed driver and reports a clear error if none is
  present.
- The embedding model needs roughly 2–3 GB of RAM resident. Size instances accordingly.
- Uploads are written to temporary files during ingestion; only extracted text, chunks and
  embeddings are persisted.

---

## Known issues

Rough edges worth knowing about before building on this.

**Security**

- Database and S3 credentials are **base64-encoded, not encrypted**, in
  `data_source_connections`. Anyone with database access can trivially recover them. Real
  encryption (the `cryptography` dependency is already present) is the obvious next step.
- `SECRET_KEY` / `JWT_SECRET_KEY` fall back to hardcoded values if unset.
- The `tables` query path executes LLM-generated SQL against the application's own database
  with only a `SELECT` prefix check - it lacks the allowlist validation the `event_fact` path
  has.
- Dashboards are scoped by `user_id`, not `organization_id`, so they are private to their
  creator rather than shared with the organization. That is what the code does today; if
  org-level sharing is intended, the scoping in `dashboard_controller` and the page guards in
  `page_routes` both need to change together.

**Correctness**

- `hybrid_engine.run_hybrid_engine()` calls `run_analytical_engine()` without its required
  `glossary` argument and then reads `["facts"]` and `["chunks"]`, neither of which that
  function returns. The `hybrid` routing path will raise.
- `query_controller.fetch_query_logs()` filters on `QueryLog.agent.is_deleted`, which is not
  valid on a relationship.
- `dashboard_controller.create_dashboard()` never sets `organization_id`, though the column
  is `NOT NULL` - dashboard creation fails.
- `query_controller.submit_feedback()` assigns `query_log.issues = json.dumps(issues),` - the
  trailing comma stores a tuple.
- `auth.html` calls `/api/auth/forgot-password`, which is not registered.
- `home.html` links to `/agents` and `/analytics`; neither route exists.

**Housekeeping**

- `run.py`'s `db.create_all()` conflicts with Alembic (see
  [Database and migrations](#database-and-migrations)).
- `app/models/uploaded_files.py` defines an unused `UploadedFile` model.
- Ten `*_old.html` / `*_working.html` / `*_new.html` templates are dead weight (~7,000 lines).
- There is no automated test suite.
