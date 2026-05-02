# Project Plan: work_logs

## 1. Purpose

A **work session tracking** web app that:

- Tracks **work sessions**, **tasks**, **hours**, **income**, and **expenses** per tenant.
- Uses a **multi-tenant** model: a **tenant owner** registers the organization; they may **invite users** (e.g. employees) who share that tenant’s data.
- **Separation of “personal” vs “self-employment”** is **not** a field on each session. The same person may use **separate accounts** (e.g. personal email vs business email), each with its **own tenant and data**—no single-login “workspace switcher.”
- Provides a **web UI** for viewing, adding, and editing sessions.
- Stores data in **PostgreSQL** (same stack as production on `logs.brakesystems.ca`).
- **Authentication required** for all log functionality.

**Deployment:** Production site remains **https://logs.brakesystems.ca** (already live). Product name in docs and code: **work_logs**.

**Data start:** **Fresh database**—no import from legacy JSON or bash scripts.

---

## 2. Database model (conceptual)

Align with the existing template: **`tenants`**, **`users`** (`tenant_id`, roles), then tenant-scoped work tables.

**Tenancy & users**

- **`tenants`** — one row per organization (or per “solo” account).
- **`users`** — belong to a `tenant_id`; tenant owner is typically `is_admin` (or equivalent); invited members are regular users. Invitations are **per tenant** (invite flow TBD in implementation).

**Work tables (all include `tenant_id` and standard timestamps)**

- **`work_sessions`** (name may match code conventions) — `tenant_id`, `user_id` (who created/owns the row or logged it), `project`, `date`, `start_time`, `end_time`, `hours_worked`, `notes`, optional `income`, optional `expenses` aggregate.
- **`work_tasks`** — `tenant_id`, `session_id`, task text (and optional fields as needed).
- **`work_expense_items`** (optional detail) — `tenant_id`, `session_id`, `amount`, `description`.

**No “work type”** (no Personal/Business flag on sessions). EI-oriented views apply to **whatever data exists in that tenant** (e.g. the self-employment tenant is implicitly “all business” for that account).

---

## 3. Authentication & authorization

- **Flask-Login** (already in template) for sessions; passwords hashed (template pattern, e.g. Werkzeug).
- Login with **email/username + password**; logout and secure cookies.
- **Roles:** tenant admin/owner vs members—**owner** can manage tenant and **invites**; members work within tenant rules (edit own vs all—define in implementation).
- **Invited users** join **one tenant**; no cross-tenant data visibility.

---

## 4. Backend functionality

- **Sessions:** start, stop, edit, delete (with validation and `tenant_id` scoping).
- **Tasks:** CRUD linked to sessions.
- **Expenses:** per session; optional line items table.
- **Reports:**
  - **Generic:** hours, income, expenses, net; filters by date range, project; CSV export.
  - **EI-oriented:** additional views/labels/export tailored for self-employment / EI documentation (same underlying rows—no separate “type” column required if the tenant is dedicated to that use).
- **Security:** rate limits, CSRF on mutations, server-side validation (template patterns).

Optional CLI/API later is **not** in scope for v1 unless added explicitly.

---

## 5. Web interface

- **Login / register / password reset** (template-aligned).
- **Dashboard** — summary hours, income, expenses; filters (date range, project); quick start/stop where applicable.
- **Sessions list** — table: date, project, hours, income, expenses (no work-type column).
- **Session detail** — notes, tasks, expenses; edit/delete with confirmations.
- **Reports** — charts where useful; CSV; **generic** and **EI-oriented** entry points or tabs.
- **Tenant admin** — invite/manage users under the tenant (implementation detail in TODO).

---

## 6. Technical stack

- **Backend:** Python Flask (factory in `app/app.py`, routes in `routes.py`, `auth.py`, `database.py`, `setup_database.py`).
- **Database:** PostgreSQL + **psycopg**; schema and upgrades via **`init_db()`** in `setup_database.py` (idempotent), not a one-shot `database_schema.sql` only.
- **Frontend:** Bootstrap 5 + existing theme (`theme.js`).
- **Host:** dev PC + container/server; production URL **logs.brakesystems.ca**.

---

## 7. Migration / legacy data

**None.** Do not build JSON import for old work logs; start with an empty app-specific schema alongside existing template tables.

---

## 8. Repository layout (this project)

Use the **existing** containerized template layout (not a separate `backend/` tree):

```
work_logs/   (repo root)
├── app/
│   ├── app.py
│   ├── static/
│   └── templates/
├── routes.py
├── auth.py
├── database.py
├── security.py
├── email_service.py
├── setup_database.py
├── requirements.txt
├── deployment_items/
├── project_plan.md
├── TODO.md
└── ...
```

---

## 9. Cursor / implementation note

Build **work_logs** features on top of the current Flask + PostgreSQL template: new **tenant-scoped** tables for sessions, tasks, and expense items; **no** Personal/Business session type; **invite-based** extra users per tenant; **generic and EI-oriented** reporting; **fresh DB** only.
