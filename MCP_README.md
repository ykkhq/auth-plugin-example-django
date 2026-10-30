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

Flow diagrams, one page per MCP flow with only its components (generated from
`docs/auth-flow-v4.html` by `docs/gen_mcp_flow_pages.py`; re-run it after changing v4):
[apikey](docs/mcp-flow-apikey.html) · [Kong GW OAuth2](docs/mcp-flow-kong-gw-oauth2.html) · [2025-03-26 client](docs/mcp-flow-2025-03-26-client.html) · [AI GW OIDC](docs/mcp-flow-ai-gw-oidc.html)

## OIDC (Auth0 user login)

Besides the shared apikey, MCP users can sign in with their own Auth0 account,
per the MCP authorization spec: the server answers 401 with OAuth 2.0 Protected
Resource Metadata (RFC 9728), the client runs the Auth0 login (OAuth 2.1 +
PKCE) and then sends the user's access token. There are two flows, alongside
the apikey servers, which are unchanged.

**Kong Gateway 3.16: one server, all 50 tools** (`kong/kong-mcp-oauth2.yaml`,
generated, synced together with `kong/kong.yaml` and `kong/kong-mcp-legacy-auth.yaml`):

```
MCP client --Bearer (Auth0 user)--> Kong GW :8443 /gw-mcp/mfg      [ai-mcp-proxy listener + ai-mcp-oauth2 + rate-limiting]
   tool call (internal request) --> Kong GW /gw-mcp/tools/<resource>/...   [ai-mcp-proxy conversion-only + openid-connect + datakit]
           --(Basic auth, X-Authenticated-User = sub)--> Django :3333 /api/<resource>/...
```

- `ai-mcp-oauth2` can't share a route with `conversion-listener`. Each resource
  therefore gets a `conversion-only` plugin on its own tool route (tag
  `mfg-gw-mcp`), and one `listener` on `/gw-mcp/mfg` aggregates them.
- Tool calls re-enter Kong through the tool routes with the client's headers.
  `passthrough_credentials: true` keeps the JWT, and `openid-connect` on each
  tool route validates it again, so a direct call without a token gets 401.
- Rate limit: 60 MCP requests/min per user (`sub`).

**AI Gateway 2.2: one server per resource** (`mfg-oidc-<resource>-mcp` in
`kong/ai-gateway.yaml`; auth strategy `mcp-auth0-oidc` in `kong/ai-gateway-oidc.yaml`):

```
MCP client --Bearer (Auth0 user)--> AI GW :11443 /mcp-oidc/mfg/<resource>   [openid-connect strategy + access.metadata]
           --same Bearer---------> Kong GW :8443 /oidc/mfg/<resource>/...   [openid-connect bearer (-m2m route) + rate-limiting + datakit]
           --Basic auth----------> Django :3333 /api/<resource>/...
```

The user's token is forwarded (`hide_credentials: false`), so Kong GW sees and
logs the real user, and the `/oidc/mfg` per-user rate limit (10/min) applies.

### Audience = resource

Both MCP layers check the token's `aud` against the protected resource, and
there is no separate audience setting. So each resource is also an Auth0 API
identifier:

| Resource (= Auth0 API identifier) | Used by |
|---|---|
| `https://localhost:8443/gw-mcp/mfg` | Kong GW `ai-mcp-oauth2` and the tool routes' `openid-connect` |
| `https://localhost:11443/mcp-oidc/mfg` | all 9 AI GW OIDC servers (a prefix of each server URL, so one login covers them) and Kong GW's `auth0-oidc-mfg-m2m` (`audience_required`) |

A token for the REST API (`DECK_AUTH0_AUDIENCE`) is rejected with
`401 {"message":"Invalid audience in token"}`.

### Auth0 setup (once)

1. **APIs**: create two, with the identifiers above (RS256).
2. **Application**: create a Native app "MCP Client" with Allowed Callback URLs
   `http://localhost:8765/callback`. Leave the token endpoint auth method at None
   (public client, PKCE). Under each API's *Application Access*, allow this app
   for user access. Put its client id in `kong/auth0.env` as `AUTH0_MCP_CLIENT_ID`.
3. **Tenant settings → Advanced**: turn on **Resource Parameter Compatibility
   Profile**. MCP clients send the RFC 8707 `resource` parameter, not Auth0's
   `audience`. The existing flows are unaffected: browser logins send
   `audience`, and client_credentials uses the Default Audience.

`./start.sh` checks both endpoints (metadata 200, MCP call without a token →
401 with `WWW-Authenticate`). `DECK_AUTH0_ISSUER_URL` (`https://<tenant>/`,
advertised as the authorization server) is derived from `AUTH0_DOMAIN` when unset.

### Use from Claude Code

```bash
source kong/auth0.env
NODE_TLS_REJECT_UNAUTHORIZED=0

# Kong GW: one server with every tool
claude mcp add --transport http mfg-gw-oidc https://localhost:8443/gw-mcp/mfg \
  --client-id "$AUTH0_MCP_CLIENT_ID" --callback-port 8765

# AI GW: per resource
claude mcp add --transport http mfg-oidc-orders https://localhost:11443/mcp-oidc/mfg/orders \
  --client-id "$AUTH0_MCP_CLIENT_ID" --callback-port 8765
```

In `claude`, run `/mcp`, pick the server and choose **Authenticate**. The browser
opens the Auth0 login; after the callback the tools are listed.

### Test with curl

```bash
# public metadata, and the 401 that points to it
curl -sk https://localhost:8443/gw-mcp/mfg/.well-known/oauth-protected-resource
curl -sk -i -X POST https://localhost:8443/gw-mcp/mfg -d '{}' | grep -i www-authenticate
curl -sk https://localhost:11443/mcp-oidc/mfg/items/.well-known/oauth-protected-resource

# with a user token ($TOKEN from the Auth0 login, aud = the resource), reuse the
# mcp() helper above with -H "Authorization: Bearer $TOKEN" instead of the apikey
# and MCP=https://localhost:8443/gw-mcp/mfg: tools/list returns all 50 tools
```

### Tools by role (Auth0)

Each Auth0 user has one of three roles, and sees and can call only that role's
tools on both OIDC flows. `tools/list` returns only the allowed tools, and calling
any other tool gets HTTP 403. The apikey servers (`/mcp/mfg/*`) aren't filtered.

| Role | Tools | Count |
|---|---|---|
| `sales` | customers and orders (everything but delete, incl. `confirm-order`, `cancel-order`); `list-`/`get-` for items, shipments, shipping statuses; `get-shipping-schedule`. No suppliers, purchase orders or BOM. | 19 |
| `manager` | every tool except `delete-*` | 43 |
| `admin` | all tools | 50 |

```
Auth0 Post-Login Action --> access token claim  "mfg_roles": ["sales"]
Kong GW  ai-mcp-oauth2 (listener) + openid-connect (tool routes): consumer_groups_claim mfg_roles
         -> consumer group "sales" (no consumer needed) -> ai-mcp-proxy tools[].acl.allow
AI GW    auth strategy mcp-auth0-oidc: consumer_groups_claim mfg_roles
         -> AI consumer group "sales" -> tools[].access.acls.allow
```

The rule is `tool_roles()` in `kong/gen_mcp_tools.py`. Change it there and
regenerate. The consumer groups are `consumer_groups` in the generated
`kong/kong-mcp-oauth2.yaml` (Kong GW) and `ai_gateway_consumer_groups` in
`kong/ai-gateway-oidc.yaml` (AI GW). A token without a known role is rejected
(`consumer_groups_optional: false`).

**Auth0 setup (once, in addition to "Auth0 setup" above):**

1. **Roles** (User Management → Roles → Create Role): `sales`, `manager`, `admin`.
   The names must match exactly, because they become the Kong consumer group names.
2. **Users** (User Management → Users → Create User, connection
   `Username-Password-Authentication`): e.g. `sales@mfg.demo`, `manager@mfg.demo`,
   `admin@mfg.demo`. On each user's **Roles** tab, assign one role.
3. **Action** (Actions → Library → Create Action → Build from scratch, trigger
   *Login / Post Login*), named "MCP roles claim". Paste this code, then **Deploy**:

   ```js
   exports.onExecutePostLogin = async (event, api) => {
     api.accessToken.setCustomClaim('mfg_roles', event.authorization?.roles ?? []);
   };
   ```

4. **Trigger** (Actions → Triggers → post-login): drag "MCP roles claim" into the
   flow and click **Apply**.

You don't need RBAC on the APIs: `event.authorization.roles` holds the user's roles
either way. Users who are already signed in must sign in again to get a token with
the claim (in Claude Code: `/mcp` → the server → **Clear authentication**, then
**Authenticate**).

Check it: decode the access token (e.g. jwt.io). It must contain
`"mfg_roles": ["sales"]`. Then compare `tools/list` on `/gw-mcp/mfg` for each user
(19 / 43 / 50 tools). On the AI GW, `/mcp-oidc/mfg/suppliers` lists no tools for
`sales`.

### Clients on the 2025-03-26 MCP spec (Kong GW only)

Older MCP clients (for example MCP TypeScript SDK ≤ 1.12) predate protected
resource metadata. They ignore `WWW-Authenticate`, drop the path of the MCP URL,
and treat that origin as the authorization server. They also expect dynamic client
registration, and never send the `resource` parameter. `kong/kong-mcp-legacy-auth.yaml`
answers them on `https://localhost:8443` with DataKit `exit` nodes, in front of
the same `/gw-mcp/mfg` server:

```
old client --POST /gw-mcp/mfg----------------------------> 401 (header ignored)
           --GET  /.well-known/oauth-authorization-server -> Kong: issuer = this origin,
                                                              authorize/register = Kong, token = Auth0
           --POST /register ------------------------------> Kong: 201 with the pre-registered public
                                                              client (AUTH0_MCP_CLIENT_ID), no Auth0 DCR
           --GET  /authorize?…&code_challenge=… ----------> Kong: 302 to Auth0 /authorize, same params
                                                              + audience=https://localhost:8443/gw-mcp/mfg
           --browser login, POST Auth0 /oauth/token ------> token with aud = the resource
           --POST /gw-mcp/mfg  Bearer <token> ------------> same as a current-spec client
```

- **No Auth0 open registration:** every old client gets the same public Native
  app. It has no secret, PKCE protects the code, and Auth0 still checks the
  `redirect_uri` against the app's Allowed Callback URLs. So add each old client's
  callback there (MCP TS SDK clients use whatever `redirectUrl` they are configured with).
- **The audience is forced at `/authorize`:** there's no `resource` parameter to
  rely on, so Kong sets `audience`. It also drops any `resource` a client sends,
  so the compatibility profile can't pick a different API.
- **Kong GW only:** the AI Gateway serves MCP servers, not arbitrary routes, so
  `:11443` has no origin-level `/.well-known/oauth-authorization-server`. Old
  clients use `https://localhost:8443/gw-mcp/mfg` (or `npx mcp-remote`, or the apikey servers).
- **Refresh tokens:** `offline_access` is advertised. Auth0 issues refresh tokens
  only if the API has *Allow Offline Access* turned on.

Check it with the SDK version before protected resource metadata (1.11.0); it
stops at the browser redirect:

```bash
curl -sk https://localhost:8443/.well-known/oauth-authorization-server
curl -sk -X POST https://localhost:8443/register -H 'Content-Type: application/json' \
  -d '{"client_name":"old","redirect_uris":["http://localhost:8765/callback"]}'
curl -sk -o /dev/null -w '%{http_code} %header{location}\n' \
  'https://localhost:8443/authorize?response_type=code&client_id=x&code_challenge=abc&code_challenge_method=S256&redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback'
# -> 302 https://<tenant>.auth0.com/authorize?…&audience=https%3A%2F%2Flocalhost%3A8443%2Fgw-mcp%2Fmfg
```

### Troubleshooting (OIDC)

- 401 `Invalid audience in token`: the token was issued for another API. Check
  that the compatibility profile is on and that the API identifier equals the resource exactly.
- Auth0 `access_denied` / `Service not found`: the API doesn't exist, or the MCP
  Client app isn't allowed to access it.
- Auth0 callback mismatch: the `--callback-port` and the Allowed Callback URL
  (`http://localhost:8765/callback`) must match.
- 404 on the AI GW metadata URL: it must sit under the server's route
  (`access.metadata.endpoint`, generated). A `resource_metadata` URL with port
  8443 on the AI GW means the DP was started with the old port mapping: rerun `./start_ai_dp.sh`.
- Old-spec client: `client_id` = `AUTH0_MCP_CLIENT_ID-not-set` in the `/register`
  answer means `AUTH0_MCP_CLIENT_ID` was missing from `kong/auth0.env` at sync time.
  Auth0 `Callback URL mismatch` means the client's redirect_uri isn't an Allowed
  Callback URL of the Native app.
- 401 from a tool call on `/gw-mcp/mfg` while `tools/list` works: the tool route's
  `openid-connect` didn't get the token. Check `passthrough_credentials: true`.
- Every MCP request is rejected after login, or `tools/list` is empty: the token has
  no `mfg_roles` claim (Action not deployed, not in the post-login flow, or an old
  token), or the role name isn't exactly `sales` / `manager` / `admin`.
- 403 on a tool call: the user's role doesn't allow that tool (see "Tools by role").

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
