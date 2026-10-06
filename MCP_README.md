# MCP server for the inventory API (Kong AI Gateway 2.2)

Kong AI Gateway 2.2 exposes every Django item endpoint as an MCP tool via a
`conversion-listener` MCP server (`ai_gateway_mcp_servers` in
`kong/ai-gateway.yaml`, applied with **kongctl**, not decK). Its upstream is the
Kong Gateway 3.16 data plane, not Django, so the apikey -> Basic auth bridge
(key-auth + DataKit in `kong/kong.yaml`) stays in one place.

```
MCP client --(MCP, apikey)--> AI GW 2.2 :11443 /mcp/inventory      [ai-mcp-proxy]
           --(REST, apikey)--> Kong GW 3.16 :8443 /inventory/...   [key-auth + datakit]
           --(Basic auth)----> Django :3333 /api/items/...
```

## Tools

| Tool          | Method | Kong GW path        | Django path          |
|---------------|--------|---------------------|----------------------|
| `list-items`  | GET    | `/inventory/`       | `/api/items/`        |
| `get-item`    | GET    | `/inventory/{id}/`  | `/api/items/{id}/`   |
| `create-item` | POST   | `/inventory/`       | `/api/items/`        |
| `update-item` | PUT    | `/inventory/{id}/`  | `/api/items/{id}/`   |
| `patch-item`  | PATCH  | `/inventory/{id}/`  | `/api/items/{id}/`   |
| `delete-item` | DELETE | `/inventory/{id}/`  | `/api/items/{id}/`   |

`/api/auth/*` and `/api/schema*` are intentionally not exposed: Kong already
injects Basic auth, and the schema endpoints are documentation.

## Setup

Konnect: Gateway control plane `django-apigw`, AI Gateway `django-ai-gw`
(`/v1/ai-gateways`; DP client cert in gitignored `kong/ai-certs/`).

0. Generate the private CA + Kong GW server cert (once): `./kong/gen-tls.sh`
   (writes gitignored `kong/tls/`)
1. Start Django: `docker compose up --build -d`
2. Start the Kong Gateway DP (registered to `django-apigw`) and the AI
   Gateway DP (`./start_ai_dp.sh`, publishes 11000/11443).
3. Apply config:

```bash
export DECK_GW_TLS_CERT="$(awk '{printf "%s\\n",$0}' kong/tls/server.crt)"
export DECK_GW_TLS_KEY="$(awk '{printf "%s\\n",$0}' kong/tls/server.key)"
deck gateway sync kong/kong.yaml --konnect-token-file ~/.kong/kpat \
  --konnect-control-plane-name django-apigw
kongctl apply -f kong/ai-gateway.yaml --pat "$(cat ~/.kong/kpat)"
```

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

```bash
MCP=https://localhost:11443/mcp/inventory

# 1. initialize -> note the mcp-session-id response header
curl -k -i -X POST $MCP \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "apikey: test" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-06-18","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1.0.0"}}}'

SID=<mcp-session-id>
H=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
   -H "apikey: test" -H "mcp-session-id: $SID")

# 2. initialized notification
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3. list tools (expect 6)
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 4. call tools
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"list-items","arguments":{}}}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"create-item","arguments":{"body":{"name":"Widget","sku":"W-001","unit_price":"9.99","quantity":5}}}}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"patch-item","arguments":{"path_id":1,"body":{"quantity":10}}}}'
```

Tool arguments: path parameters are prefixed `path_` (`path_id`), the JSON
request body goes in `body`.

## Use from Claude Code

```bash

NODE_TLS_REJECT_UNAUTHORIZED=0

claude mcp add --transport http inventory https://localhost:11443/mcp/inventory \
  --header "apikey: test"
```

```bash
$ claude

/mcp

get inventory items from MCP server
```

(The DP uses a self-signed cert; set `NODE_TLS_REJECT_UNAUTHORIZED=0` for
local testing or use the plain-http port `http://localhost:11000/mcp/inventory`.)

## Troubleshooting

- 502 `self-signed certificate` in the AI GW log: Kong GW is serving its
  default cert (SNI `host.docker.internal` not synced) or the AI GW DP was
  started without the CA mount — check `kong/kong.yaml` certificates and
  `start_ai_dp.sh`.
- 401 from a tool call: the `apikey` header didn't reach Kong GW.
- 405: the `django-route-items` route in `kong/kong.yaml` must allow
  GET/POST/PUT/PATCH/DELETE.
- 301/500 on POST/PUT: missing trailing slash (DRF router).
