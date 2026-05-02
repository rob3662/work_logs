# Web app template (containerized Flask)

Slim starter for new sites: shared deployment patterns (env, Postgres, Redis, Mailgun/SendGrid/SMTP, reCAPTCHA, Cloudflare, Stripe webhook stub, Quadlet/Podman) with minimal app code so you can add your own product logic.

## Quick start

1. Copy this folder to a new project path.
2. Run `./deployment_items/init_new_project.sh <domain> <port>` from a project folder named for your slug (or edit and run `deployment_items/website_setup.sh` as-is).
3. Copy `.env.example` → `.env` and fill secrets.
4. Run `./deployment_items/<slug>_setup.sh` on the server (after host bootstrap, if you use split scripts), or `./deployment_items/website_setup.sh` if you did not run the initializer.

See `TEMPLATE_USAGE.md` for details.

## License

This project is proprietary. All rights reserved.  
See the LICENSE file for full terms of use.
