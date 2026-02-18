#!/usr/bin/env python3
"""
Simple Flask server to receive Stripe webhooks and mark paid users in Supabase.

Requirements:
- Set STRIPE_SECRET and STRIPE_WEBHOOK_SECRET in environment or Streamlit secrets.
- Set SUPA_URL and SUPA_SERVICE_ROLE (service role key) in env/secrets so server can upsert the members table.
- Create a Supabase table `members` with columns: email (text, unique), status (text), updated_at (timestamp).

Run:
    pip install -r requirements.txt
    python webhook_server.py

This example upserts a row into `members` with status='active' when checkout.session.completed is received.
"""
import os
import json
import stripe
from flask import Flask, request, jsonify
from datetime import datetime

try:
    from supabase import create_client
except Exception:
    create_client = None

app = Flask(__name__)


def get_config():
    stripe_secret = os.environ.get("STRIPE_SECRET")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    supa_url = os.environ.get("SUPA_URL")
    supa_service = os.environ.get("SUPA_SERVICE_ROLE")
    return stripe_secret, webhook_secret, supa_url, supa_service


@app.route("/", methods=["GET"])
def index():
    return "Stripe webhook receiver"


@app.route("/webhook", methods=["POST"])
def webhook():
    stripe_secret, webhook_secret, supa_url, supa_service = get_config()
    if not webhook_secret:
        return "Webhook secret not configured", 500

    payload = request.get_data(as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        app.logger.error(f"Webhook signature verification failed: {e}")
        return jsonify({'error': 'invalid signature'}), 400

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = None
        cust = session.get('customer_details')
        if cust:
            customer_email = cust.get('email')
        if not customer_email:
            customer_email = session.get('metadata', {}).get('email')

        if customer_email:
            # Upsert into Supabase `members` table using service role key
            if create_client is None:
                app.logger.error('supabase package not available')
            elif not supa_url or not supa_service:
                app.logger.error('Supabase config missing; SUPA_URL and SUPA_SERVICE_ROLE required')
            else:
                try:
                    sb = create_client(supa_url, supa_service)
                    now = datetime.utcnow().isoformat()
                    # Upsert by email
                    data = {"email": customer_email, "status": "active", "updated_at": now}
                    resp = sb.table('members').upsert(data).execute()
                    app.logger.info(f"Supabase upsert response: {resp}")
                except Exception as e:
                    app.logger.error(f"Supabase upsert failed: {e}")

    # Return a 200 to acknowledge receipt of the event
    return jsonify({'status': 'received'})


if __name__ == '__main__':
    # Optional: set stripe api key if needed for further API calls
    stripe_secret, _, _, _ = get_config()
    if stripe_secret:
        stripe.api_key = stripe_secret
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 4242)))
