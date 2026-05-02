# Stripe (template)

1. Create Products/Prices in the Stripe Dashboard.
2. Set `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, and price IDs in `.env`.
3. Set `STRIPE_WEBHOOK_SECRET` and register endpoint `/api/stripe/webhook`.
4. Implement checkout and customer portal routes for your product (stub page: `/subscription/plans`).
