"""Stripe: per-seat subscriptions for an organisation.

Optional. With no STRIPE_SECRET_KEY the app runs on the free plan (a handful
of seats, every feature) and the billing endpoints say so. With keys set, an
admin buys seats through Stripe Checkout; the webhook is the source of truth
for the org's plan and seat count -- the browser never tells us what was paid.

Environment:
  STRIPE_SECRET_KEY       sk_live_... / sk_test_...
  STRIPE_WEBHOOK_SECRET   whsec_...
  STRIPE_PRICE_SEAT       price_... for the per-seat monthly price
  APP_URL                 public origin, for redirects
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from server import db

FREE_SEATS = 5


def configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PRICE_SEAT"))


def _stripe():
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def plan_info(org: dict) -> dict:
    members = db.org_member_count(org["id"])
    return {
        "plan": org["plan"],
        "seats": org["seats"],
        "members": members,
        "seats_left": max(0, org["seats"] - members),
        "billing_available": configured(),
        "free_seats": FREE_SEATS,
    }


def seats_available(org: dict) -> bool:
    return db.org_member_count(org["id"]) < org["seats"]


def checkout_url(org: dict, user: dict, seats: int) -> str:
    if not configured():
        raise HTTPException(400, "Billing is not configured on this server.")
    seats = max(1, min(int(seats), 5000))
    stripe = _stripe()
    app_url = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
    customer_id = org.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(name=org["name"], email=user["email"],
                                          metadata={"org_id": org["id"]})
        customer_id = customer["id"]
        db.run("UPDATE orgs SET stripe_customer_id=? WHERE id=?", (customer_id, org["id"]))
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": os.environ["STRIPE_PRICE_SEAT"], "quantity": seats}],
        success_url=app_url + "/app/admin?billing=success",
        cancel_url=app_url + "/app/admin?billing=cancelled",
        client_reference_id=org["id"],
        metadata={"org_id": org["id"], "seats": str(seats)},
        allow_promotion_codes=True,
    )
    return session["url"]


def portal_url(org: dict) -> str:
    if not configured() or not org.get("stripe_customer_id"):
        raise HTTPException(400, "No billing account yet.")
    stripe = _stripe()
    app_url = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
    session = stripe.billing_portal.Session.create(customer=org["stripe_customer_id"],
                                                   return_url=app_url + "/app/admin")
    return session["url"]


def handle_webhook(payload: bytes, signature: str) -> dict:
    """Verify and apply. Returns what changed, for the log."""
    if not os.environ.get("STRIPE_WEBHOOK_SECRET"):
        raise HTTPException(400, "Webhook secret not configured.")
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, signature, os.environ["STRIPE_WEBHOOK_SECRET"])
    except Exception:
        raise HTTPException(400, "Invalid signature.")

    kind = event["type"]
    obj = event["data"]["object"]
    changed = {"event": kind}

    if kind in ("checkout.session.completed",):
        org_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("org_id")
        sub_id = obj.get("subscription")
        if org_id and sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
            seats = _seats_of(sub)
            db.run("UPDATE orgs SET plan='pro', seats=?, stripe_subscription_id=?, stripe_customer_id=? WHERE id=?",
                   (seats, sub_id, obj.get("customer"), org_id))
            changed.update({"org_id": org_id, "seats": seats})
    elif kind in ("customer.subscription.updated", "customer.subscription.created"):
        row = db.one("SELECT id FROM orgs WHERE stripe_customer_id=?", (obj.get("customer"),))
        if row:
            active = obj.get("status") in ("active", "trialing", "past_due")
            seats = _seats_of(obj) if active else FREE_SEATS
            db.run("UPDATE orgs SET plan=?, seats=?, stripe_subscription_id=? WHERE id=?",
                   ("pro" if active else "free", seats, obj.get("id"), row["id"]))
            changed.update({"org_id": row["id"], "seats": seats, "active": active})
    elif kind == "customer.subscription.deleted":
        row = db.one("SELECT id FROM orgs WHERE stripe_customer_id=?", (obj.get("customer"),))
        if row:
            db.run("UPDATE orgs SET plan='free', seats=?, stripe_subscription_id=NULL WHERE id=?",
                   (FREE_SEATS, row["id"]))
            changed.update({"org_id": row["id"], "seats": FREE_SEATS, "active": False})

    db.audit("billing." + kind, org_id=changed.get("org_id"), detail=changed)
    return changed


def _seats_of(subscription) -> int:
    try:
        items = subscription["items"]["data"]
        return int(sum(int(i.get("quantity") or 0) for i in items)) or FREE_SEATS
    except (KeyError, TypeError, ValueError):
        return FREE_SEATS

