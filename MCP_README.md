# MCP servers for the manufacturing API (Kong AI Gateway 2.2)

Kong AI Gateway 2.2 exposes every Django REST endpoint as an MCP tool. There
is one `conversion-listener` MCP server per resource, at
`/mcp/mfg/<resource>` (`ai_gateway_mcp_servers` in `kong/ai-gateway.yaml`,
applied with **kongctl**, not decK). Each server's upstream is the matching
Kong Gateway 3.16 path `/mfg/<resource>`, not Django, so the apikey -> Basic
auth bridge (key-auth + DataKit in `kong/kong.yaml`) stays in one place.

```
MCP client --(MCP, apikey)--> AI GW 2.2 :11443 /mcp/mfg/<resource>     [ai-mcp-proxy]
           --(REST, apikey)--> Kong GW 3.16 :8443 /mfg/<resource>/...   [key-auth + datakit]
           --(Basic auth)----> Django :3333 /api/<resource>/...
```

## MCP servers (9) and tools (50)

`kong/ai-gateway.yaml` is **generated** from the drf-spectacular OpenAPI
schema. Don't edit it by hand. After changing any view or serializer:

```bash
.venv/bin/python kong/gen_mcp_tools.py          # rewrite kong/ai-gateway.yaml
.venv/bin/python kong/gen_mcp_tools.py --check  # CI: fail if it is stale
```

Tool descriptions come from the `extend_schema` summaries in
`inventory/views.py`. Filters become optional query parameters, and request
bodies come from the serializers (read-only fields left out). A new API
resource gets its own MCP server automatically.

| MCP server (`https://localhost:11443` + path) | Tools |
|---|---|
| `/mcp/mfg/items` | `list-items`, `create-item`, `get-item`, `update-item`, `patch-item`, `delete-item`, `build-item` |
| `/mcp/mfg/item-components` (BOM) | `list-item-components`, `create-item-component`, `get-item-component`, `update-item-component`, `patch-item-component`, `delete-item-component` |
| `/mcp/mfg/suppliers` | `list-suppliers`, `create-supplier`, `get-supplier`, `update-supplier`, `patch-supplier`, `delete-supplier` |
| `/mcp/mfg/customers` | `list-customers`, `create-customer`, `get-customer`, `update-customer`, `patch-customer`, `delete-customer` |
| `/mcp/mfg/purchase-orders` | `list-purchase-orders`, `create-purchase-order`, `get-purchase-order`, `update-purchase-order`, `patch-purchase-order`, `delete-purchase-order`, `receive-purchase-order` |
| `/mcp/mfg/orders` | `list-orders`, `create-order`, `get-order`, `update-order`, `patch-order`, `delete-order`, `confirm-order`, `cancel-order` |
| `/mcp/mfg/shipments` | `list-shipments`, `create-shipment`, `get-shipment`, `update-shipment`, `patch-shipment`, `delete-shipment` |
| `/mcp/mfg/shipping-statuses` | `list-shipping-statuses`, `create-shipping-status`, `get-shipping-status` |
| `/mcp/mfg/shipping-schedule` | `get-shipping-schedule` |

The former single server `/mcp/inventory` is gone. `/api/auth/*` and
`/api/schema*` are intentionally not exposed: Kong already injects Basic
auth, and the schema endpoints are documentation.

Removing a server: `kongctl apply` only creates and updates, so a server
dropped from `kong/ai-gateway.yaml` stays in Konnect until you delete it
(Konnect UI, or `DELETE /v1/ai-gateways/{id}/mcp-servers/{server-id}`).

## Setup

`./start.sh` does everything below. Run it again at any time; it reuses
the certs and Konnect resources and recreates the DP containers.
It needs `kong/auth0.env` and a Konnect PAT in `~/.kong/kpat`.

Konnect: Gateway control plane `django-apigw` and AI Gateway `django-ai-gw`,
both declared in `kong/konnect.yaml` (kongctl) with their DP client certs
(gitignored `kong/gw-certs/`, `kong/ai-certs/`).

To do it by hand:

0. Generate the private CA + Kong GW server cert (once): `./kong/gen-tls.sh`
   (writes gitignored `kong/tls/`), and a self-signed DP client cert in
   each of `kong/gw-certs/` and `kong/ai-certs/` (`tls.crt`, `tls.key`).
1. Start Django: `docker compose up --build -d`
2. Create the Konnect resources:
   `kongctl apply -f kong/konnect.yaml --pat "$(cat ~/.kong/kpat)"`
3. Start the Kong Gateway DP (on `kong-net`, alias `kong-dp`, see
   `start.sh`) and the AI Gateway DP (`./start_ai_dp.sh`, publishes
   11000/11443; it looks up its Konnect endpoints).
4. Apply config:

```bash
export DECK_GW_TLS_CERT="$(awk '{printf "%s\\n",$0}' kong/tls/server.crt)"
export DECK_GW_TLS_KEY="$(awk '{printf "%s\\n",$0}' kong/tls/server.key)"
deck gateway sync kong/kong.yaml --konnect-token-file ~/.kong/kpat \
  --konnect-control-plane-name django-apigw
kongctl apply -f kong/ai-gateway.yaml --pat "$(cat ~/.kong/kpat)"
```

To tear everything down (DP containers, Konnect CP `django-apigw` and AI
Gateway `django-ai-gw`, compose stacks and volumes, `kong/tls/`,
`kong/gw-certs/`, `kong/ai-certs/`): `./cleanup.sh` (`-y` skips the confirmation).

The AI GW reaches Kong GW over verified https at
`https://host.docker.internal:8443`:

- Kong GW serves `kong/tls/server.crt` (SAN `host.docker.internal`, signed by
  the private CA) via the `certificates`/`snis` entities in `kong/kong.yaml`.
- The AI GW DP trusts that CA via
  `KONG_LUA_SSL_TRUSTED_CERTIFICATE=system,/etc/kong/ca/ca.crt`
  (`start_ai_dp.sh`), keeping the system CAs for public upstreams.

The MCP client's `apikey` header is forwarded upstream
(`server.forward_client_headers: true`). To avoid giving MCP clients a Kong
GW key, add a request-transformer AI Gateway policy that sets `apikey`.

## Test with curl

Each MCP server has its own session. This zsh/bash helper opens one:
`mcp <resource>` runs `initialize` + `notifications/initialized` and sets
`$MCP` and `$H` (headers including `mcp-session-id`) for the calls after it.

```bash
mcp() {
  MCP=https://localhost:11443/mcp/mfg/$1
  local base=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "apikey: test")
  local sid=$(curl -sk -D - -o /dev/null -X POST $MCP "${base[@]}" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0.0"}}}' |
    awk 'tolower($1)=="mcp-session-id:"{print $2}' | tr -d '\r')
  H=("${base[@]}" -H "mcp-session-id: $sid")
  curl -sk -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
}

# items server: list tools (expect 7), then call some
mcp items
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"list-items","arguments":{}}}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"create-item","arguments":{"body":{"name":"Widget","sku":"W-001","unit_price":"9.99","quantity":5}}}}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"patch-item","arguments":{"path_id":1,"body":{"quantity":10}}}}'

# manufacturing flow (ids from the seed_demo data; check them with list-* first)
# build 2 "Desk Workstation Bundle" (FG-2001) from its BOM
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":6,"method":"tools/call",
  "params":{"name":"build-item","arguments":{"path_id":6,"body":{"quantity":2}}}}'

# receive everything outstanding on purchase order 1
mcp purchase-orders
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":7,"method":"tools/call",
  "params":{"name":"receive-purchase-order","arguments":{"path_id":1,"body":{}}}}'

# sales order with lines for a dealer, then ship it
mcp orders
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":8,"method":"tools/call",
  "params":{"name":"create-order","arguments":{"body":{"order_number":"SO-0100","customer":1,
  "order_date":"2026-10-15","lines":[{"item":6,"quantity":1}]}}}}'

mcp shipping-statuses
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":9,"method":"tools/call",
  "params":{"name":"create-shipping-status","arguments":{"body":{"shipment":1,"status":"in_transit"}}}}'

mcp shipping-schedule
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":10,"method":"tools/call",
  "params":{"name":"get-shipping-schedule","arguments":{}}}'
```

Tool arguments: path parameters are prefixed `path_` (`path_id`), the JSON
request body goes in `body`. Query parameters (list filters) are optional.
`tools/list` shows their exact argument names.

## Konnect Catalog and Dev Portal

The 9 MCP servers are also registered in the Konnect Catalog (MCP servers)
by `kong/catalog_mcp.py`. Each entry gets the server's live tool list, its
remote URL and a link to the AI Gateway MCP server. The Dev Portal
(`kong/portal.yaml`) lists them on its MCP servers page,
`kong/portal/mcp-servers.md`, which `kong/gen_mcp_tools.py` generates. See
README "API Catalog and Dev Portal (Konnect)".

## Use from Claude Code

```bash

NODE_TLS_REJECT_UNAUTHORIZED=0

# one Claude Code MCP server per resource
for r in items item-components suppliers customers purchase-orders orders \
         shipments shipping-statuses shipping-schedule; do
  claude mcp add --transport http mfg-$r https://localhost:11443/mcp/mfg/$r \
    --header "apikey: test"
done
```

Add only the servers a client needs (e.g. just `mfg-orders` and
`mfg-shipments` for an order-tracking agent) to keep its tool list small.

```bash
$ claude

/mcp

list the bill of materials for FG-2001 and build 2 of them
```

(The DP uses a self-signed cert; set `NODE_TLS_REJECT_UNAUTHORIZED=0` for
local testing or use the plain-http port `http://localhost:11000/mcp/mfg/<resource>`.)

## Troubleshooting

- 502 `self-signed certificate` in the AI GW log: Kong GW is serving its
  default cert (SNI `host.docker.internal` not synced) or the AI GW DP was
  started without the CA mount — check `kong/kong.yaml` certificates and
  `start_ai_dp.sh`.
- 401 from a tool call: the `apikey` header didn't reach Kong GW.
- 405: the `django-route-mfg` route in `kong/kong.yaml` must allow
  GET/POST/PUT/PATCH/DELETE.
- 404 from the MCP endpoint itself: the path must be
  `/mcp/mfg/<resource>` (`/mcp/inventory` no longer exists).
- 404 from every tool of one server: its `config.url` must be
  `https://host.docker.internal:8443/mfg/<resource>` (the `django-api`
  service maps `/mfg` to Django `/api`).
- 409 from `build-item`, `receive-purchase-order` or
  `create-shipping-status`: not enough stock, or the order/PO isn't in a
  state that allows it. The `detail` message names the short items.
- 413 on large orders: raise `max_request_body_size` in `kong/gen_mcp_tools.py`.
- 301/500 on POST/PUT: missing trailing slash (DRF router).
