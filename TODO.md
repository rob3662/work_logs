# TODO: work_logs (Flask + PostgreSQL)

## Overview

Greenfield **work_logs** product on the existing **containerized Flask template**: PostgreSQL, multi-tenant (`tenants` / `users`), **invited users per tenant**, session/task/expense tracking, **generic and EI-oriented** reporting, **no** per-session work-type field, **no** JSON or legacy import—**fresh database**.

Production URL: **https://logs.brakesystems.ca** (already deployed). Implement incrementally; test as you go.

### Recently shipped (for context)

- Per-tenant registration (new `tenants` row per signup), global email/username uniqueness, **`is_site_admin`** vs tenant **`is_admin`**, `/admin` only for site admins.
- **`work_sessions`**, **`work_tasks`**, **`work_expense_items`** (+ `user_id` on sessions for starter, **`ended_by_user_id`** when stopped, **`user_id`** on tasks for who added each task).
- **`/work`** session list, start, detail, stop, edit; tasks add with attribution; dashboard recent sessions + **Started by** column.
- **`tenant_invites`**: `/work/team` (invite/revoke), **`/auth/accept-invite/<token>`**, email template; optional **`TENANT_INVITE_EXPIRES_DAYS`** (default 7).

---

## Phase 1: Foundation (template + schema)

### 1.1 Baseline

- [x] Confirm `.env` / PostgreSQL connectivity for local and server (template already in use).
- [ ] Document work_logs-specific env vars in one place (e.g. `TENANT_INVITE_EXPIRES_DAYS`, `APP_NAME`, Mailgun/SMTP as used by this app).

### 1.2 Database — work log tables

- [x] Idempotent `CREATE TABLE` / `_ensure_column` in `setup_database.py` for `work_sessions`, `work_tasks`, `work_expense_items`, `tenant_invites`.
- [x] Tenant-scoped tables with `tenant_id`, timestamps, FKs; sessions and tasks linked to `users` where needed.
- [x] Smoke-test path: `init_db()` on app boot (file lock); re-run safe on upgrades.

### 1.3 Auth / tenancy (extend template)

- [x] Tenant owner vs invited member: owner **`is_admin`** on tenant; invitees created without admin; **`is_site_admin`** only for global `/admin`.
- [x] Invite flow: token (hashed at rest), email link, accept → **`create_user_in_existing_tenant`** on correct `tenant_id`.
- [x] New self-serve registrations create a **new tenant**; invites attach to **existing** tenant.
- [x] Rate limits + **`security_events`** on invite create/accept/revoke and related auth events.

---

## Phase 2: Core backend (routes + data)

### 2.1 Application wiring

- [x] Work blueprint (`work_logs_routes.py`) registered from `app/app.py`.
- [x] Login required + **`tenant_id`** scoping on work log queries.

### 2.2 Session CRUD

- [x] Start / stop / edit sessions (CSRF, validation, rate limits).
- [ ] **Delete** session (with confirmation and permission rules).
- [x] Income / expense totals on session row.
- [ ] **`work_expense_items`** UI (table exists; no add/list/edit in app yet).

### 2.3 Task CRUD

- [x] Add tasks linked to `session_id` + `tenant_id`; store **`user_id`** (who added).
- [ ] Edit / delete tasks (and permission rules).

### 2.4 Reporting

- [ ] **Generic:** aggregates by date range and project; hours, income, expenses, net; CSV export.
- [ ] **EI-oriented:** dedicated report(s) and/or export labels for self-employment / EI documentation (same tenant rows).
- [ ] Optional: simple charts for hours and money over time.

---

## Phase 3: Web UI

### 3.1 Auth pages

- [x] Login, register, forgot/reset (template); **accept team invite** page.
- [ ] Optional branding/copy pass for **work_logs** specifically.

### 3.2 Dashboard

- [x] Recent sessions table + quick links (start session, work log).
- [ ] Summary cards: hours / income / expenses for a chosen period; filters (date range, project).

### 3.3 Sessions UI

- [x] List and detail views; edit; **Started by** / **Stopped by** on detail; list + dashboard show starter.
- [ ] List **filters** (date range, project).
- [ ] **Delete** session with confirmation.

### 3.4 Tasks UI

- [x] Add tasks on session detail; show **who added** each task.
- [ ] Edit / delete task actions.

### 3.5 Reports UI

- [ ] Reports page: **Generic** and **EI-oriented** sections (or tabs).
- [ ] CSV download; print-friendly optional.

### 3.6 Tenant admin / invites

- [x] Invite by email, list invites (with status), revoke pending.
- [ ] Optional: **team roster** (list users in tenant, roles) without over-exposing emails.

---

## Phase 4: ~~Migration~~ — not applicable

- **Skipped:** No JSON import, no legacy bash workflow migration, fresh data only.

---

## Phase 5: Polish & extras (after core works)

- [ ] Monthly/yearly summaries; trends (optional).
- [ ] Mobile-friendly passes on session forms and lists.
- [ ] Backup/restore notes in `deployment_items` if not already covered.

---

## Phase 6: Deployment & ops

- [ ] Align `deployment_items` scripts and docs with **work_logs** naming where they still say template defaults (if any).
- [ ] Production DB backups for new tables.
- [ ] Confirm **logs.brakesystems.ca** SSL and app health after releases.

---

## Phase 7: Testing

- [ ] Unit/integration tests for session/task endpoints and `tenant_id` isolation.
- [x] Manual smoke: invites + sessions (keep repeating after major changes).
- [ ] Verify generic and EI report numbers once reporting exists.

---

## Key considerations

- **Tenant isolation:** every query includes `tenant_id`; invites never leak other tenants’ data.
- **Two “worlds” for one person:** two registrations → two tenants; no app-level merge.
- **EI reports:** logical layer on top of tenant data, not a `type` column on sessions.
- **Stack:** PostgreSQL, parameterized queries, template security (CSRF, rate limits, logging).

---

## Success criteria

- [x] Tenant owner can run core session + task workflow; invitees can join and use the same tenant data.
- [ ] Full expense line items + reporting + CSV.
- [ ] Generic and EI-oriented reporting and export available.
- [x] No work-type field; separation only by account/tenant.
- [x] Deployed at **logs.brakesystems.ca** with schema upgrades via **`init_db()`** (ongoing: add new guarded DDL as features land).
