from flask import Flask, request, jsonify
import os
import stripe
import datetime
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

STRIPE_SECRET = os.environ.get("STRIPE_SECRET")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPA_URL = os.environ.get("SUPA_URL")
SUPA_SERVICE_ROLE = os.environ.get("SUPA_SERVICE_ROLE")

if STRIPE_SECRET:
    stripe.api_key = STRIPE_SECRET

supabase = None
if SUPA_URL and SUPA_SERVICE_ROLE:
    try:
        from supabase import create_client
        supabase = create_client(SUPA_URL, SUPA_SERVICE_ROLE)
    except Exception as e:
        logging.error(f"Failed to init Supabase client: {e}")


def upsert_member_by_email(email, payload):
    if not supabase:
        logging.warning("Supabase client not configured; skipping upsert")
        return None
    try:
        resp = supabase.table('members').upsert(payload).execute()
        logging.info(f"Upserted member {email}: {resp}")
        return resp
    except Exception as e:
        logging.exception(f"Failed to upsert member: {e}")
        return None


def handle_checkout_session(session):
    # session is the Stripe Checkout Session object
    customer_id = session.get('customer')
    subscription_id = session.get('subscription')
    email = None
    # Try customer_details first (newer sessions)
    if session.get('customer_details'):
        email = session['customer_details'].get('email')
    # Fallback to metadata
    if not email and session.get('metadata'):
        email = session['metadata'].get('email')

    payload = {
        'email': email,
        'plan': 'paid',
        'status': 'active',
        'stripe_customer_id': customer_id,
    }

    if subscription_id:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            payload['stripe_subscription_id'] = subscription_id
            # Set trial_expires to subscription current_period_end (UTC)
            if sub.get('current_period_end'):
                dt = datetime.datetime.utcfromtimestamp(sub['current_period_end'])
                payload['trial_expires'] = dt.isoformat()
        except Exception:
            logging.exception('Failed to retrieve subscription')

    upsert_member_by_email(email, payload)


def handle_invoice_paid(invoice):
    # When an invoice is paid, ensure subscription/customer are marked active
    subscription_id = invoice.get('subscription')
    customer_id = invoice.get('customer')
    # Try to get customer email from invoice
    email = None
    if invoice.get('customer_email'):
        email = invoice['customer_email']
    # Upsert status active
    payload = {
        'plan': 'paid',
        'status': 'active',
        'stripe_customer_id': customer_id,
    }
    if subscription_id:
        payload['stripe_subscription_id'] = subscription_id
    upsert_member_by_email(email, payload)


def handle_subscription_deleted(sub):
    # mark member as inactive
    customer_id = sub.get('customer')
    subscription_id = sub.get('id')
    payload = {
        'plan': 'free',
        'status': 'inactive',
        'stripe_subscription_id': None,
    }
    # Try to find by stripe_customer_id
    if supabase and customer_id:
        try:
            res = supabase.table('members').select('email').eq('stripe_customer_id', customer_id).limit(1).execute()
            rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
            email = rows[0]['email'] if rows and len(rows) > 0 else None
            upsert_member_by_email(email, payload)
            return
        except Exception:
            logging.exception('Failed to lookup member by stripe_customer_id')
    # fallback: no-op


@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            logging.exception('⚠️ Webhook signature verification failed')
            return jsonify({'error': str(e)}), 400
    else:
        # If no webhook secret, attempt to parse JSON (unsafe for production)
        try:
            event = request.get_json(force=True)
        except Exception as e:
            logging.exception('Failed to parse event')
            return jsonify({'error': str(e)}), 400

    event_type = event.get('type')
    logging.info(f'Received event: {event_type}')

    try:
        if event_type == 'checkout.session.completed':
            session = event['data']['object']
            handle_checkout_session(session)
        elif event_type in ('invoice.payment_succeeded', 'invoice.paid'):
            invoice = event['data']['object']
            handle_invoice_paid(invoice)
        elif event_type in ('customer.subscription.deleted', 'customer.subscription.updated'):
            sub = event['data']['object']
            # if deleted, mark inactive; if updated, refresh dates/status
            if event_type == 'customer.subscription.deleted':
                handle_subscription_deleted(sub)
            else:
                # for updates, set status according to subscription
                try:
                    status = sub.get('status')
                    customer_id = sub.get('customer')
                    payload = {'status': status}
                    if sub.get('current_period_end'):
                        dt = datetime.datetime.utcfromtimestamp(sub['current_period_end'])
                        payload['trial_expires'] = dt.isoformat()
                    # upsert by stripe_customer_id
                    if supabase and customer_id:
                        res = supabase.table('members').select('email').eq('stripe_customer_id', customer_id).limit(1).execute()
                        rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
                        email = rows[0]['email'] if rows and len(rows) > 0 else None
                        upsert_member_by_email(email, payload)
                except Exception:
                    logging.exception('Failed to handle subscription.updated')

    except Exception as e:
        logging.exception(f'Error handling event: {e}')
        return jsonify({'error': str(e)}), 500

    return jsonify({'status': 'ok'}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
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
