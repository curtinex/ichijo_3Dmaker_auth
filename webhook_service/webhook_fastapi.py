import os
import logging
import datetime
from typing import Optional

import stripe
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
import requests
import secrets

app = FastAPI()
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


def upsert_member_by_email(email: Optional[str], payload: dict):
    if not supabase:
        logging.warning("Supabase client not configured; skipping upsert")
        return None
    if not email:
        logging.warning("No email provided for upsert; skipping to prevent NULL email rows")
        return None
    try:
        # Ensure email is present in payload when available so upsert sets it
        if 'email' not in payload:
            payload['email'] = email
        # Explicitly use on_conflict='email' to update the existing row instead of inserting a new one
        resp = supabase.table('members').upsert(payload, on_conflict='email').execute()
        logging.info(f"Upserted member {email}: {resp}")
        return resp
    except Exception:
        logging.exception(f"Failed to upsert member for {email}")
        return None


def handle_checkout_session(session: dict):
    customer_id = session.get('customer')
    subscription_id = session.get('subscription')
    email = None
    if session.get('customer_details'):
        email = session['customer_details'].get('email')
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
            if sub.get('current_period_end'):
                dt = datetime.datetime.utcfromtimestamp(sub['current_period_end'])
                payload['trial_expires'] = dt.isoformat()
        except Exception:
            logging.exception('Failed to retrieve subscription')

    # Ensure Supabase auth user exists (create via admin API if necessary)
    if supabase and email and SUPA_URL and SUPA_SERVICE_ROLE:
        try:
            # Check members table for existing user_id
            try:
                res = supabase.table('members').select('user_id').eq('email', email).limit(1).execute()
                rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
                existing_user_id = rows[0].get('user_id') if rows and len(rows) > 0 else None
            except Exception:
                existing_user_id = None

            if not existing_user_id:
                # Create a Supabase auth user via admin endpoint
                admin_url = SUPA_URL.rstrip('/') + '/auth/v1/admin/users'
                rand_pw = secrets.token_urlsafe(16)
                headers = {
                    'apikey': SUPA_SERVICE_ROLE,
                    'Authorization': f'Bearer {SUPA_SERVICE_ROLE}',
                    'Content-Type': 'application/json'
                }
                body = {'email': email, 'password': rand_pw, 'email_confirm': True}
                try:
                    r = requests.post(admin_url, json=body, headers=headers, timeout=10)
                    if r.status_code in (200, 201):
                        j = r.json()
                        uid = j.get('id') or j.get('user', {}).get('id')
                        if uid:
                            payload['user_id'] = uid
                    else:
                        logging.warning(f"Supabase admin user create returned {r.status_code}: {r.text[:200]}")
                except Exception:
                    logging.exception('Failed to call Supabase admin API')
        except Exception:
            logging.exception('Failed to check or create Supabase auth user')

    upsert_member_by_email(email, payload)


def handle_invoice_paid(invoice: dict):
    subscription_id = invoice.get('subscription')
    customer_id = invoice.get('customer')
    email = invoice.get('customer_email')
    payload = {
        'plan': 'paid',
        'status': 'active',
        'stripe_customer_id': customer_id,
    }
    if subscription_id:
        payload['stripe_subscription_id'] = subscription_id
    # If invoice didn't include customer_email, try to lookup email by stripe_customer_id
    if not email and supabase and customer_id:
        try:
            res = supabase.table('members').select('email').eq('stripe_customer_id', customer_id).limit(1).execute()
            rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
            email = rows[0]['email'] if rows and len(rows) > 0 else None
        except Exception:
            logging.exception('Failed to lookup email by stripe_customer_id for invoice')

    upsert_member_by_email(email, payload)


def handle_subscription_deleted(sub: dict):
    customer_id = sub.get('customer')
    payload = {
        'plan': 'free',
        'status': 'inactive',
        'stripe_subscription_id': None,
    }
    if supabase and customer_id:
        try:
            res = supabase.table('members').select('email').eq('stripe_customer_id', customer_id).limit(1).execute()
            rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
            email = rows[0]['email'] if rows and len(rows) > 0 else None
            upsert_member_by_email(email, payload)
            return
        except Exception:
            logging.exception('Failed to lookup member by stripe_customer_id')


@app.post('/webhook')
async def webhook(request: Request, stripe_signature: Optional[str] = Header(None, alias='Stripe-Signature')):
    body = await request.body()
    event = None
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(body, stripe_signature, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            logging.exception('⚠️ Webhook signature verification failed')
            # Log signature header and a safe preview of the raw body to help debugging
            try:
                sig_preview = stripe_signature if stripe_signature else '<missing>'
                body_preview = ''
                try:
                    # body may be bytes
                    if isinstance(body, (bytes, bytearray)):
                        body_preview = body.decode('utf-8', errors='replace')[:1000]
                    else:
                        body_preview = str(body)[:1000]
                except Exception:
                    body_preview = '<unprintable body>'
                logging.info(f"Stripe-Signature header: {sig_preview}")
                logging.info(f"Raw body preview (first 1000 chars): {body_preview}")
            except Exception:
                logging.exception('Failed to log webhook debug info')
            # Return a generic 400 to Stripe (don't leak internal exception text)
            raise HTTPException(status_code=400, detail="Webhook signature verification failed")
    else:
        try:
            event = await request.json()
        except Exception as e:
            logging.exception('Failed to parse event')
            raise HTTPException(status_code=400, detail=str(e))

    event_type = event.get('type')
    logging.info(f'Received event: {event_type}')

    try:
        if event_type == 'checkout.session.completed':
            session = event['data']['object']
            handle_checkout_session(session)
        elif event_type == 'customer.subscription.created':
            sub = event['data']['object']
            # Try to resolve email from subscription object or supabase via customer id
            email = None
            if sub.get('customer_email'):
                email = sub.get('customer_email')
            if not email and sub.get('metadata'):
                email = sub['metadata'].get('email')
            # Build payload
            payload = {
                'plan': 'paid',
                'status': sub.get('status'),
                'stripe_subscription_id': sub.get('id'),
                'stripe_customer_id': sub.get('customer'),
            }
            # trial end or current_period_end
            if sub.get('trial_end'):
                try:
                    dt = datetime.datetime.utcfromtimestamp(int(sub['trial_end']))
                    payload['trial_expires'] = dt.isoformat()
                except Exception:
                    pass
            elif sub.get('current_period_end'):
                try:
                    dt = datetime.datetime.utcfromtimestamp(int(sub['current_period_end']))
                    payload['trial_expires'] = dt.isoformat()
                except Exception:
                    pass

            # If no email, attempt lookup by customer id in supabase
            if not email and supabase and sub.get('customer'):
                try:
                    res = supabase.table('members').select('email').eq('stripe_customer_id', sub.get('customer')).limit(1).execute()
                    rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
                    email = rows[0]['email'] if rows and len(rows) > 0 else None
                except Exception:
                    logging.exception('Failed to lookup email by stripe_customer_id for subscription.created')

            upsert_member_by_email(email, payload)
        elif event_type in ('invoice.payment_succeeded', 'invoice.paid'):
            invoice = event['data']['object']
            handle_invoice_paid(invoice)
        elif event_type in ('customer.subscription.deleted', 'customer.subscription.updated'):
            sub = event['data']['object']
            if event_type == 'customer.subscription.deleted':
                handle_subscription_deleted(sub)
            else:
                try:
                    status = sub.get('status')
                    customer_id = sub.get('customer')
                    payload = {'status': status}
                    if sub.get('current_period_end'):
                        dt = datetime.datetime.utcfromtimestamp(sub['current_period_end'])
                        payload['trial_expires'] = dt.isoformat()
                    if supabase and customer_id:
                        res = supabase.table('members').select('email').eq('stripe_customer_id', customer_id).limit(1).execute()
                        rows = res.get('data') if isinstance(res, dict) else getattr(res, 'data', None)
                        email = rows[0]['email'] if rows and len(rows) > 0 else None
                        upsert_member_by_email(email, payload)
                except Exception:
                    logging.exception('Failed to handle subscription.updated')
    except Exception as e:
        logging.exception(f'Error handling event: {e}')
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse({'status': 'ok'})
