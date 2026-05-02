# Deployment (template)

This template follows the same **containerized app + Quadlet** approach as the main site: build a Podman image from `Containerfile`, run it with a `.container` unit, reverse-proxy with Nginx, optional Cloudflare tunnel.

## Steps

1. Prepare the host (Postgres, Redis, Nginx, Podman network) using your server bootstrap process.
2. Set `WEBSITE_NAME`, `WEBSITE_PORT`, and `WEBSITE_DOMAIN` at the top of `deployment_items/<slug>_setup.sh` (or run `init_new_project.sh` first).
3. Configure `.env` from `.env.example`.
4. Run `./deployment_items/<slug>_setup.sh`.

## Teardown

After `init_new_project.sh`, the generic `teardown_site.sh` is renamed to `./deployment_items/<slug>_teardown.sh`. Run it with `sudo` from the project root when you need to remove this site from the host; see the script header for flags (`--yes`, `--remove-backups`, `--remove-project`).

## App entrypoint

Gunicorn serves `app.app:app` from the project root (see `Containerfile` and Quadlet `Exec=` in the setup script).

## Stripe

Configure `STRIPE_WEBHOOK_SECRET` and point Stripe to `https://<your-domain>/api/stripe/webhook` (or the path your Nginx exposes).
