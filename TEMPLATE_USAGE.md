# Project template usage

This folder is a **slim, reusable Flask starter** with the same deployment and environment conventions as your production stack (Postgres, Redis, Mailgun/SendGrid/SMTP, reCAPTCHA, Cloudflare, Stripe webhook stub, Quadlet/Podman, asset versioning, DB init on app startup). It does **not** ship domain-specific business logic—add your own routes and models.

When you keep it inside the `webserver_setup` checkout, the path is `webserver_setup/project_template_containerized/` (copy or `git subtree` this directory into a new repo when you start a site).

**Development Python:** `deployment_items/website_setup.sh` expects **`python3.13`** at **`3.13.12`** when `FLASK_ENV` is not production (same line as `FROM python:3.13-slim` in `Containerfile`). Adjust `DEV_PYTHON_BIN` / `DEV_PYTHON_VERSION_EXPECTED` at the top of the script if your distro uses another path; `.python-version` helps **pyenv** (and similar) pick the same patch on your dev PC.

## What is included

- `app/app.py` — app factory, security, DB init lock + `setup_database.init_db()`
- `routes.py` — auth, home, dashboard, legal stubs, admin summary, health + Stripe webhook stub
- `auth.py` / `database.py` / `security.py` / `email_service.py` — generic patterns
- `setup_database.py` — `tenants`, `users` (with `tenant_id`), `blocked_registration_prefixes`, `security_events`; seeds default tenant + admin from `.env`
- `deployment_items/website_setup.sh` — generic setup script; `init_new_project.sh` renames it to `<slug>_setup.sh` and rewrites placeholders (`<slug>` = project directory name)
- `Containerfile` + trimmed `requirements.txt`
- Minimal templates under `app/templates/`

### Guides (`Guides/`)

- `CLOUDFLARE_SETUP.md`, `REDIS_SETUP.md`, email (SendGrid / Brevo), Stripe  
- **`GLOBAL_CURSOR_RULES.md`** — short rules to paste into Cursor **global** settings  
- **`SEO_GOOGLE_SEARCH_CONSOLE_CHECKLIST.md`** — robots.txt, sitemaps, canonicals, redirects, GSC audits  

## Start a new project

```bash
# From a folder named for your site (that name becomes the project slug, e.g. my_new_site):
./deployment_items/init_new_project.sh mynewsite.com 5060
cp .env.example .env
# edit .env (secrets, APP_NAME, Stripe, Mailgun, Cloudflare, etc.)
./deployment_items/my_new_site_setup.sh
```

`init_new_project.sh` takes **domain** and **port** only; the slug is **`basename` of the project directory**. It replaces placeholders (`work_logs`, `logs.brakesystems.ca`, default port) and renames `website_setup.sh` → `<slug>_setup.sh`.

If you prefer not to run the initializer, edit `WEBSITE_NAME` / `WEBSITE_PORT` / `WEBSITE_DOMAIN` at the top of `deployment_items/website_setup.sh` and run that file directly (it stays named `website_setup.sh` until you rename it yourself).

## Optional registration cap

Set `MAX_REGISTERED_USERS` in `.env` to limit self-service signups (see `auth.py` if you need different rules).
