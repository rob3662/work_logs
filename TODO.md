# TODO: work_logs (Flask + PostgreSQL)

## Overview

Greenfield **work_logs** product on the existing **containerized Flask template**: PostgreSQL, multi-tenant (`tenants` / `users`), **invited users per tenant**, session/task/expense tracking, **generic and EI-oriented** reporting, **no** per-session work-type field, **no** JSON or legacy import—**fresh database**.

Production URL: **https://logs.brakesystems.ca** (already deployed). Implement incrementally; test as you go.

---

## Phase 1: Foundation (template + schema)

### 1.1 Baseline

- [ ] Confirm `.env` / PostgreSQL connectivity for local and server (template already in use).
- [ ] Document any work_logs-specific env vars as they are added.

### 1.2 Database — work log tables

- [ ] Add idempotent `CREATE TABLE` / `_ensure_column` steps in `setup_database.py` for tenant-scoped tables (e.g. `work_sessions`, `work_tasks`, `work_expense_items`—final names to match code).
- [ ] Every new table: `id`, `tenant_id` → `tenants(id)`, `created_at`, `updated_at`, FKs with sensible `ON DELETE`.
- [ ] Link sessions to `users` as needed (e.g. `user_id` for creator or logger); always filter by `tenant_id`.
- [ ] Smoke-test `init_db()` on empty DB and on existing production-shaped DB.

### 1.3 Auth / tenancy (extend template)

- [ ] Clarify and implement **tenant owner** vs **invited member** (roles, permissions).
- [ ] **Invite flow:** create invite token or email link, accept invite → user attached to correct `tenant_id`.
- [ ] Ensure new registrations create a **new tenant** (solo owner) unless accepting an invite.
- [ ] Rate-limit and log security-sensitive actions (`security_events` where appropriate).

---

## Phase 2: Core backend (routes + data)

### 2.1 Application wiring

- [ ] Register blueprints or routes for work log URLs; keep patterns consistent with `routes.py` / `auth.py`.
- [ ] Enforce login + `tenant_id` on all work log queries.

### 2.2 Session CRUD

- [ ] Start / stop / edit / delete work sessions (validation, CSRF).
- [ ] Income and optional expense totals on session; optional expense line items.
- [ ] Project field and date/time or duration rules.

### 2.3 Task CRUD

- [ ] Tasks linked to `session_id` + `tenant_id`; edit/delete rules.

### 2.4 Reporting

- [ ] **Generic:** aggregates by date range and project; hours, income, expenses, net; CSV export.
- [ ] **EI-oriented:** dedicated report(s) and/or export labels aimed at self-employment / EI documentation (data is still “all rows in this tenant”).
- [ ] Optional: simple charts for hours and money over time.

---

## Phase 3: Web UI

### 3.1 Auth pages

- [ ] Reuse/adjust template login, register, forgot/reset password for work_logs copy/branding if needed.

### 3.2 Dashboard

- [ ] Summary cards or tables: hours, income, expenses; filters (date range, project).
- [ ] Quick links: start session / active session (if applicable).

### 3.3 Sessions UI

- [ ] List view with filters; detail view; edit/delete with confirmation.
- [ ] No work-type column or filter.

### 3.4 Tasks UI

- [ ] Per-session tasks: add, edit, delete (inline or on detail page).

### 3.5 Reports UI

- [ ] Reports page: **Generic** section and **EI-oriented** section (or tabs).
- [ ] CSV download; print-friendly optional.

### 3.6 Tenant admin / invites

- [ ] UI for owner: list pending invites, invite by email, revoke; list users in tenant (within privacy constraints).

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

- [ ] Unit/integration tests for session/task/report endpoints and `tenant_id` isolation.
- [ ] Manual UAT: owner + invited user on same tenant; two separate tenants (simulate personal vs business accounts).
- [ ] Verify generic and EI report numbers match underlying rows.

---

## Key considerations

- **Tenant isolation:** every query includes `tenant_id`; invites never leak other tenants’ data.
- **Two “worlds” for one person:** two registrations → two tenants; no app-level merge.
- **EI reports:** logical layer on top of tenant data, not a `type` column on sessions.
- **Stack:** PostgreSQL, parameterized queries, template security (CSRF, rate limits, logging).

---

## Success criteria

- [ ] Tenant owner can run full session/task/expense workflow.
- [ ] Invited users can participate per defined permissions.
- [ ] Generic and EI-oriented reporting and export available.
- [ ] No work-type field; separation only by account/tenant.
- [ ] Deployed and usable at **logs.brakesystems.ca** with stable PostgreSQL schema upgrades via `init_db()`.
