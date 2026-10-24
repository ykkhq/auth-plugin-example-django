#!/usr/bin/env python
"""Konnect billing catalog for per-user MCP usage on the AI Gateway "django-ai-gw".

The AI Gateway's metering-and-billing policy (kong/ai-gateway-billing.yaml)
sends one kong.api_request event per MCP request, with subject
"consumer:<AI Gateway consumer id>". This script builds the billing side
(OpenMeter state, which kongctl does not model), safe to re-run:

  meter     api_requests_total (existing, kong.api_request, count)
  feature   mfg_mcp_requests: that meter filtered to control_plane_id = django-ai-gw,
            unit cost 0.3 yen per request (what serving one costs: cost analytics)
  plan      mfg_mcp_pay_per_request: JPY, monthly, 1 yen per MCP request
  customers mcp-alice / mcp-bob / mcp-carol, subject key consumer:<id>
  subscriptions  each customer on the plan

    .venv/bin/python kong/mcp_billing.py          # create what is missing
    .venv/bin/python kong/mcp_billing.py --usage  # per-user requests this billing period
    .venv/bin/python kong/mcp_billing.py --cost   # cost, revenue, margin per user and MCP server
    .venv/bin/python kong/mcp_billing.py --delete # remove all of the above (./cleanup.sh)

Invoices and charges per customer: Konnect UI > Metering & Billing > Customers.
Request volume by user, MCP server and tool: Konnect Analytics dashboard
"MCP Cost Analytics (django-ai-gw)" (kong/konnect.yaml).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

KONNECT = "https://us.api.konghq.com"
OPENMETER = f"{KONNECT}/v3/openmeter"
PAT_FILE = Path(os.environ.get("KONNECT_PAT_FILE", Path.home() / ".kong" / "kpat"))
AI_GW_NAME = "django-ai-gw"
METER = "api_requests_total"
FEATURE = "mfg_mcp_requests"
PLAN = "mfg_mcp_pay_per_request"
UNIT_PRICE = "1"
# Konnect stores a manual unit cost without a currency (cost queries label it USD);
# it is entered and reported here in CURRENCY.
UNIT_COST = "0.3"
CURRENCY = "JPY"
USERS = {"mcp-alice": "Alice", "mcp-bob": "Bob", "mcp-carol": "Carol"}  # AI GW consumer -> display name


def api(method, url, body=None, fail=True):
    """JSON response; on an HTTP error exit, or with fail=False return (None, message)."""
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {PAT_FILE.read_text().strip()}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as exc:
        msg = f"{method} {url} -> {exc.code}: {exc.read().decode()[:500]}"
        if fail:
            sys.exit(msg)
        return None, msg
    data = json.loads(text) if text else None
    return data if fail else (data, None)


def find(collection, key):
    for row in api("GET", f"{OPENMETER}/{collection}?page_size=100")["data"]:
        if row.get("key") == key:
            return row
    return None


def ai_gateway():
    return next((g for g in api("GET", f"{KONNECT}/v1/ai-gateways")["data"] if g["name"] == AI_GW_NAME), None)


def consumer_ids(gw_id):
    rows = api("GET", f"{KONNECT}/v1/ai-gateways/{gw_id}/consumers")["data"]
    return {c["name"]: c["id"] for c in rows}


def ensure_feature(meter_id, gw_id):
    feature = find("features", FEATURE)
    if not feature:
        feature = api("POST", f"{OPENMETER}/features", {
            "key": FEATURE,
            "name": "MCP requests (django-ai-gw)",
            "meter": {"id": meter_id, "filters": {"control_plane_id": {"eq": gw_id}}},
            "unit_cost": {"type": "manual", "amount": UNIT_COST},
        })
        print(f"created feature {FEATURE}")
    elif feature.get("unit_cost") != {"type": "manual", "amount": UNIT_COST}:
        feature = api("PATCH", f"{OPENMETER}/features/{feature['id']}",
                      {"unit_cost": {"type": "manual", "amount": UNIT_COST}})
        print(f"set unit cost of {FEATURE} to {UNIT_COST} {CURRENCY}")
    return feature


def ensure_plan(feature_id):
    plan = find("plans", PLAN)
    if not plan:
        plan = api("POST", f"{OPENMETER}/plans", {
            "key": PLAN,
            "name": "MCP Pay-Per-Request",
            "currency": CURRENCY,
            "billing_cadence": "P1M",
            "phases": [{
                "key": "default",
                "name": "Default",
                "rate_cards": [{
                    "type": "usage_based",
                    "key": FEATURE,  # must equal the feature key
                    "name": "MCP request usage",
                    "feature": {"id": feature_id},
                    "billing_cadence": "P1M",
                    "price": {"type": "unit", "amount": UNIT_PRICE},
                }],
            }],
        })
        print(f"created plan {PLAN}")
    if plan["status"] == "draft":
        plan = api("POST", f"{OPENMETER}/plans/{plan['id']}/publish")
        print(f"published plan {PLAN}")
    return plan


def ensure_customer(name, display, consumer_id):
    subject = f"consumer:{consumer_id}"
    customer = find("customers", name)
    if not customer:
        customer = api("POST", f"{OPENMETER}/customers", {
            "key": name,
            "name": f"{display} (MCP)",
            "currency": CURRENCY,
            "usage_attribution": {"subject_keys": [subject]},
        })
        print(f"created customer {name} -> {subject}")
    elif customer["usage_attribution"]["subject_keys"] != [subject]:
        # the AI Gateway (and so its consumer ids) was recreated, e.g. after ./cleanup.sh
        customer = api("PUT", f"{OPENMETER}/customers/{customer['id']}", {
            "key": name,
            "name": customer["name"],
            "currency": customer.get("currency", CURRENCY),
            "usage_attribution": {"subject_keys": [subject]},
        })
        print(f"relinked customer {name} -> {subject}")
    return customer


def ensure_subscription(customer, plan):
    subs = api("GET", f"{OPENMETER}/subscriptions?filter%5Bcustomer_id%5D={customer['id']}&page_size=100")["data"]
    if any(s["customer_id"] == customer["id"] and s["status"] == "active"
           and s.get("plan", {}).get("key") == PLAN for s in subs):
        return
    api("POST", f"{OPENMETER}/subscriptions", {
        "customer": {"id": customer["id"]},
        "plan": {"key": PLAN, "version": plan["version"]},
    })
    print(f"subscribed {customer['key']} to {PLAN}")


def requests_by_subject(meter_id, gw_id, start):
    q = api("POST", f"{OPENMETER}/meters/{meter_id}/query", {
        "from": start,
        "group_by_dimensions": ["subject"],
        "filters": {"dimensions": {"control_plane_id": {"eq": gw_id}}},
    })
    return {r["dimensions"]["subject"]: int(r["value"]) for r in q["data"]}


def usage(meter_id, gw_id):
    """Per-user MCP requests in the current billing period, priced like the plan.

    A live estimate: Konnect books usage charges when the period closes
    (invoice_at), so the charge itself shows usage 0 until then."""
    ids = consumer_ids(gw_id)
    print(f"{'customer':<12} {'billing period':<25} {'requests':>8} {'amount':>9}  invoice at")
    for name in USERS:
        customer = find("customers", name)
        charge = next((c for c in api("GET", f"{OPENMETER}/customers/{customer['id']}/charges")["data"]
                       if c["name"] == "MCP request usage"), None) if customer else None
        if not charge:
            print(f"{name:<12} not subscribed (run without --usage)")
            continue
        period = charge["billing_period"]
        count = requests_by_subject(meter_id, gw_id, period["from"]).get(f"consumer:{ids[name]}", 0)
        amount = count * int(charge["price"]["amount"])
        print(f"{name:<12} {period['from'][:10]} -> {period['to'][:10]}  {count:>8} {amount:>5} {charge['currency']}"
              f"  {charge['invoice_at'][:10]}")
    month = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00Z")
    billed = {f"consumer:{ids[n]}" for n in USERS if n in ids}
    names = {f"consumer:{cid}": n for n, cid in ids.items()}
    for subject, count in requests_by_subject(meter_id, gw_id, month).items():
        if subject not in billed:
            print(f"{names.get(subject, subject):<12} not billed: {count} requests this month")


def cost(feature_id, gw_id, start):
    """Cost (unit cost x requests) next to revenue (unit price x requests), per user and per MCP server."""
    names = {f"consumer:{cid}": n for n, cid in consumer_ids(gw_id).items()}
    billed = set(USERS)

    def rows(dimension):
        q = api("POST", f"{OPENMETER}/features/{feature_id}/cost/query",
                {"from": start, "group_by_dimensions": [dimension]})
        out = {}
        for r in q["data"]:
            key = r["dimensions"][dimension]
            used, spent = out.get(key, (0, 0.0))
            out[key] = (used + int(float(r["usage"])), spent + float(r["cost"]))
        return out

    def table(title, data, label, revenue_of):
        print(f"\n{title}")
        print(f"  {label:<26} {'requests':>8} {'cost':>8} {'revenue':>8} {'margin':>8}")
        total = [0, 0.0, 0]
        for key, (used, spent) in sorted(data.items(), key=lambda kv: -kv[1][0]):
            revenue = revenue_of(key, used)
            margin = f"{(revenue - spent) / revenue:.0%}" if revenue else "-"
            print(f"  {key:<26} {used:>8} {spent:>8.1f} {revenue:>8} {margin:>8}")
            total = [total[0] + used, total[1] + spent, total[2] + revenue]
        margin = f"{(total[2] - total[1]) / total[2]:.0%}" if total[2] else "-"
        print(f"  {'total':<26} {total[0]:>8} {total[1]:>8.1f} {total[2]:>8} {margin:>8}")

    print(f"MCP cost analytics since {start[:10]} ({CURRENCY}; cost {UNIT_COST}/request, price {UNIT_PRICE}/request)")
    by_user = {names.get(k, k): v for k, v in rows("subject").items()}
    table("By user (unsubscribed users cost money but bring no revenue)", by_user, "user",
          lambda user, used: used * int(UNIT_PRICE) if user in billed else 0)
    # revenue per server assumes every request came from a billed user
    by_server = {k.removesuffix("-route"): v for k, v in rows("route_name").items()}
    table("By MCP server (revenue if all requests were billed)", by_server, "MCP server",
          lambda _, used: used * int(UNIT_PRICE))


def delete():
    """Remove the catalog in reverse order; warn and go on when Konnect refuses a step
    (e.g. a customer with an invoice that is not final yet cannot be deleted)."""
    def step(label, method, path, body=None):
        _, err = api(method, f"{OPENMETER}{path}", body, fail=False)
        print(f"WARN: {label}: {err}" if err else label, file=sys.stderr if err else sys.stdout)

    for name in USERS:
        customer = find("customers", name)
        if not customer:
            continue
        subs = api("GET", f"{OPENMETER}/subscriptions?filter%5Bcustomer_id%5D={customer['id']}&page_size=100")["data"]
        for sub in subs:
            if sub["customer_id"] == customer["id"] and sub["status"] == "active":
                step(f"canceled subscription of {name}", "POST", f"/subscriptions/{sub['id']}/cancel",
                     {"timing": "immediate"})
        step(f"deleted customer {name}", "DELETE", f"/customers/{customer['id']}")
    plan = find("plans", PLAN)
    if plan:
        if plan["status"] == "active":
            step(f"archived plan {PLAN}", "POST", f"/plans/{plan['id']}/archive")
        step(f"deleted plan {PLAN}", "DELETE", f"/plans/{plan['id']}")
    feature = find("features", FEATURE)
    if feature:
        step(f"deleted feature {FEATURE}", "DELETE", f"/features/{feature['id']}")
    print(f"billing catalog removed (meter {METER} is shared and kept)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--usage", action="store_true", help="print per-user usage instead of provisioning")
    ap.add_argument("--cost", nargs="?", const="month", metavar="FROM",
                    help="print cost analytics since FROM (ISO date, default: start of this month)")
    ap.add_argument("--delete", action="store_true", help="remove the billing catalog (customers, plan, feature)")
    args = ap.parse_args()
    if args.delete:
        return delete()
    gw = ai_gateway() or sys.exit(f"AI Gateway {AI_GW_NAME} not found: run ./start.sh")
    gw_id = gw["id"]
    meter = find("meters", METER) or sys.exit(f"meter {METER} not found")
    if args.usage:
        return usage(meter["id"], gw_id)
    if args.cost:
        start = datetime.now(timezone.utc).strftime("%Y-%m-01") if args.cost == "month" else args.cost
        feature = find("features", FEATURE) or sys.exit(f"feature {FEATURE} not found: run without --cost")
        return cost(feature["id"], gw_id, f"{start}T00:00:00Z" if len(start) == 10 else start)
    feature = ensure_feature(meter["id"], gw_id)
    plan = ensure_plan(feature["id"])
    ids = consumer_ids(gw_id)
    for name, display in USERS.items():
        if name not in ids:
            sys.exit(f"AI Gateway consumer {name} not found: apply kong/ai-gateway-billing.yaml first")
        ensure_subscription(ensure_customer(name, display, ids[name]), plan)
    print("billing catalog ready")


if __name__ == "__main__":
    main()
