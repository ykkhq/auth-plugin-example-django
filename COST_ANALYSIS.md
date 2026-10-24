# MCP cost analysis in the Konnect UI

How to set up cost analysis for MCP requests on the AI Gateway `django-ai-gw`
using the Konnect UI, and how to read the results.

Cost analysis in Konnect has two parts:

| Part | Where in Konnect | Shows |
|---|---|---|
| Feature unit cost | Metering & Billing > Features | Cost in money: requests x unit cost, grouped by user or MCP server |
| Analytics dashboard | Analytics > Dashboards | Request volume by user, MCP server, tool and method, plus error rate |

The same setup is automated in this repo: `kong/mcp_billing.py` (unit cost)
and `kong/konnect.yaml` (dashboard), both run by `./start.sh`. Use this guide
to do it by hand, or to understand what those files create.

> Konnect UI labels change between releases. The field names below match the
> Konnect API (`unit_cost`, `agentic_usage`, `control_plane`...), so if a
> label in the UI looks different, match it by meaning.

## Values used in this demo

| Item | Value |
|---|---|
| Konnect org / region | `Kong` / `us` |
| AI Gateway | `django-ai-gw` (id `c5f30a63-8656-4a38-ab30-684c2c937aac`) |
| Meter | `api_requests_total` (event type `kong.api_request`, aggregation `count`) |
| Feature | `mfg_mcp_requests` (meter filtered to `control_plane_id` = AI Gateway id) |
| Unit cost | 0.3 per request (yen, see [Currency](#currency)) |
| Unit price | 1 JPY per request (plan `mfg_mcp_pay_per_request`) |

## Prerequisites

Cost analysis works on usage that is already being metered. Before you start:

1. The AI Gateway has the `metering-and-billing` policy (`mcp-metering`,
   global) and MCP users authenticate with their own API keys
   (`kong/ai-gateway-billing.yaml`). Without a consumer, every request is
   metered as one anonymous subject and you cannot split cost by user.
2. The billing feature `mfg_mcp_requests` exists (`kong/mcp_billing.py`).
3. The AI Gateway data plane is connected. In **AI Gateways > django-ai-gw >
   Data plane nodes**, a node must be listed. If the list is empty while the
   container is running, the data plane lost its control-plane connection and
   is serving old config: restart it with `./start_ai_dp.sh`.

### Check that MCP usage is reaching Konnect

1. Send some MCP traffic with a user key (see `MCP_README.md`).
2. Open **Metering & Billing > Meters > api_requests_total**.
3. Query the last hour and group by **subject**. You should see rows such as
   `consumer:054cca41-...`, one per AI Gateway consumer.

The subject is always `consumer:<consumer id>`, not the consumer's name. To
map an id to a user, open **AI Gateways > django-ai-gw > Consumers**.

## Step 1: Set the unit cost on the feature

The unit cost is what serving one request costs you (infrastructure,
upstream calls). It is separate from the price you charge customers.

1. Open **Metering & Billing > Features**.
2. Open the feature **mfg_mcp_requests** ("MCP requests (django-ai-gw)").
3. Edit the feature and set the unit cost:
   - **Type**: Manual
   - **Amount**: `0.3`
4. Save.

Only the unit cost can be changed on an existing feature. The key and the
meter filter are fixed when the feature is created.

## Step 2: View cost by user and by MCP server

1. On the **mfg_mcp_requests** feature page, open its cost view.
2. Choose the time range, for example the current month.
3. Group by:
   - **subject** for cost per user (`consumer:<id>`)
   - **route_name** for cost per MCP server (`mfg-items-mcp-route`, ...)
4. Each row shows the usage (requests) and the cost (requests x 0.3).

API equivalent, useful for checking the UI's numbers:

```bash
curl -s -X POST https://us.api.konghq.com/v3/openmeter/features/<feature id>/cost/query \
  -H "Authorization: Bearer $(cat ~/.kong/kpat)" -H "Content-Type: application/json" \
  -d '{"from":"2026-10-01T00:00:00Z","group_by_dimensions":["subject"]}'
```

Or let the script do it and add revenue and margin:

```bash
.venv/bin/python kong/mcp_billing.py --cost             # since the start of this month
.venv/bin/python kong/mcp_billing.py --cost 2026-10-15  # since a given date
```

## Step 3: Create the analytics dashboard

The dashboard shows request volume over time. It cannot multiply by a price,
so read cost as requests x 0.3.

1. Open **Analytics > Dashboards** and create a new dashboard named
   **MCP Cost Analytics (django-ai-gw)**.
2. Add a dashboard filter so that every tile shows only this AI Gateway:
   - **Field**: Control plane (`control_plane`)
   - **Operator**: in
   - **Value**: `django-ai-gw`
3. Add the tiles below. For every tile, set the data source to
   **Agentic usage** (`agentic_usage`) and the metric to **Request count**
   (`request_count`), unless the table says otherwise.

| Tile title | Chart | Group by | Filter |
|---|---|---|---|
| MCP requests (x 0.3 JPY = cost) | Single value | none | MCP method is not empty |
| Error rate (billed but failed) | Single value, metric **Error rate** | none | MCP method is not empty |
| Requests by user (cost share) | Donut | Consumer | Consumer is not empty |
| Requests over time by user | Time series bar, stacked | Consumer, Time | Consumer is not empty |
| Requests by JSON-RPC method | Horizontal bar | MCP method | MCP method is not empty |
| Requests by MCP server | Horizontal bar | Gateway service | MCP method is not empty |
| Top tools by calls | Top N, limit 10 | MCP tool name | MCP tool name is not empty |
| Tool calls by user and tool | Horizontal bar, stacked | Consumer, MCP tool name | MCP tool name is not empty |

4. Save the dashboard.

The "is not empty" filters keep non-MCP traffic out of the tiles. Each
**Gateway service** is one MCP server (`mfg-items-mcp`, ...).

## Step 4: Check the results

1. Send a known amount of traffic, for example 5 tool calls as one user.
   One MCP session sends `initialize` and `notifications/initialized` before
   the tool calls, so 5 tool calls = 7 metered requests.
2. Wait about a minute, then check:
   - **Feature cost view**: that user's usage went up by 7 and cost by 2.1.
   - **Dashboard**: the user's count went up by 7, and **Top tools by calls**
     shows the tool you called.
   - `kong/mcp_billing.py --cost` agrees with both.
3. A request without a key, or with a wrong key, is rejected by the AI Gateway
   (401) and must not add usage.

## How to read the numbers

### Cost, revenue and margin

| | Formula | Demo value per request |
|---|---|---|
| Cost | requests x unit cost | 0.3 |
| Revenue | billed requests x unit price | 1 |
| Margin | (revenue - cost) / revenue | 70% |

- Every MCP request is metered, including `initialize` and notifications, so
  each session adds 2 requests to both cost and revenue.
- Traffic with the demo key `test` (consumer `user1`) has cost but no
  revenue: `user1` has no billing customer. This lowers the overall margin.
- Requests sent before a customer's subscription started are counted in cost
  but not invoiced. The `--cost` report's revenue is a list-price figure; for
  what will actually be invoiced use `kong/mcp_billing.py --usage` or the
  customer's charges in **Metering & Billing > Customers**.

### Currency

Konnect stores a manual unit cost as a plain amount with no currency, and its
cost views label the result USD. In this demo the amount is yen (0.3 JPY
against the 1 JPY price), so read the "USD" label as JPY. The `--cost` report
prints JPY.

### Live estimates vs invoices

Cost and dashboard figures are live. Customer charges show usage 0 until the
billing period closes and the invoice is created (2026-11-19 for the current
period). That is expected, not a missing-data problem.

## Changing the unit cost

1. Edit the feature's unit cost in the UI (Step 1).
2. Also update `UNIT_COST` in `kong/mcp_billing.py`. Otherwise the next
   `./start.sh` sets the feature back to the value in the script.
3. Update the "x 0.3 JPY" in the first tile's title (UI, and
   `kong/konnect.yaml`).

The new cost applies to every cost query, including past periods: Konnect
applies the current unit cost to usage at query time.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "feature mfg_mcp_requests has no unit cost configured" | Step 1 was not done (or not saved). |
| No rows in the meter or cost view | No traffic yet, or the AI Gateway data plane is disconnected (see Prerequisites, step 3). |
| All usage under one subject | MCP users are not authenticating with their own keys, so no consumer is identified. |
| Dashboard tiles are empty but the cost view has data | The dashboard filter is not set to `django-ai-gw`, or analytics data for the period is not available yet. Widen the time range and check the control plane filter. |
| Numbers in the dashboard are higher than in the cost view | The dashboard counts all agentic traffic on the gateway; the feature only counts metered `kong.api_request` events. Check the "is not empty" filters on each tile. |
