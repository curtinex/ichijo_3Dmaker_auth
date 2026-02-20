# webhook_service (Render) — FastAPI Stripe webhook

This folder contains a minimal FastAPI webhook service for Stripe events and Supabase upserts.

Files
- `webhook_fastapi.py`: FastAPI app that verifies Stripe webhook signatures and updates `members` table in Supabase using `SUPA_SERVICE_ROLE`.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: Dockerfile to build the service image.
- `Procfile`: command for platforms that use Procfile (Heroku/Render).

Environment variables (required)
- `STRIPE_SECRET` — Stripe secret key (test or live). e.g. `sk_test_...`
- `STRIPE_WEBHOOK_SECRET` — Stripe webhook signing secret (from `stripe listen` or Dashboard)
- `SUPA_URL` — Your Supabase project URL (https://xxxx.supabase.co)
- `SUPA_SERVICE_ROLE` — Supabase service_role key (keep this secret)
- `PORT` — optional (default 5000)

Deploy to Render (quick)
1. Push this repository to GitHub (already done).
2. Go to https://dashboard.render.com and create a new **Web Service**.
   - Connect your GitHub repo and select the `main` branch.
   - Choose **Docker** as the environment (the repo contains `webhook_service/Dockerfile`).
3. In the Environment settings, set the required environment variables listed above.
4. Create and deploy. Render will build the Docker image and run the service.

Local testing
1. Install dependencies locally (recommended in virtualenv):
```bash
python -m pip install -r webhook_service/requirements.txt
```
2. Start the service locally:
```bash
cd webhook_service
uvicorn webhook_fastapi:app --reload --port 5000
```
3. Use Stripe CLI to forward events to your local server (in another terminal):
```bash
stripe listen --forward-to localhost:5000/webhook
# copy displayed 'Webhook signing secret' and set STRIPE_WEBHOOK_SECRET accordingly
```
4. Trigger test events:
```bash
stripe trigger checkout.session.completed
stripe trigger invoice.payment_succeeded
```

Security notes
- Never commit `SUPA_SERVICE_ROLE` or `STRIPE_SECRET` to the repo. Use Render's Environment settings or a secrets manager.
- In production, use the live Stripe secret (`sk_live_...`) and register the Render public webhook URL in Stripe Dashboard → Webhooks.

Troubleshooting
- If Supabase upserts fail, verify `SUPA_SERVICE_ROLE` has correct privileges and the `members` table exists.
- If Stripe events are not received, ensure the webhook URL is registered or `stripe listen` is forwarding correctly.
