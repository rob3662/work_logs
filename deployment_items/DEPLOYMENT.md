# Deployment (template)

This template follows the same **containerized app + Quadlet** approach as the main site: build a Podman image from `Containerfile`, run it with a `.container` unit, reverse-proxy with Nginx, optional Cloudflare tunnel.

## Cloudflare tunnel and DNS

A healthy tunnel in Zero Trust does **not** imply public DNS is correct. For each public hostname you must add DNS in the **apex** zone (see `Guides/CLOUDFLARE_SETUP.md`). A dedicated tunnel needs its own CNAME (or Tunnel record) to `<CLOUDFLARE_TUNNEL_ID>.cfargotunnel.com`, not the hostname target used by other apps on the same domain.

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
