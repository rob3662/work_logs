# SendGrid (optional)

1. Create an API key in SendGrid.
2. Set `SENDGRID_API_KEY` in `.env`.
3. Set `NO_REPLY` to a verified sender (e.g. `noreply@logs.brakesystems.ca`).

Mail order in this template: **Mailgun → SendGrid → SMTP**.
