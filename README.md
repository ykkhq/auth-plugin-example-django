# Djangoに対して認証をするKong pluginのデモ

### 流れ
Client(curl) --(apikey認証)--> Kong API gateway (dp) --(basic 認証)--> Django

OIDC版 (`/oidc/inventory`):
Browser --(Auth0 OIDCログイン → Kongセッションcookie)--> Kong API gateway (dp) --(basic 認証)--> Django
curl/アプリ --(Auth0 Bearer JWT または client_credentials)--> Kong API gateway (dp) --(basic 認証)--> Django

### 利用Kong Plugin
- Key auth (`/inventory`)
- OpenID Connect (`/oidc/inventory`、Auth0、セッション管理込み)
- Datakit
- pre function (サンプル、利用しない)

OIDCの設定手順（Auth0側の設定、deck sync、ブラウザ/curlでの確認）は下記英文の
「OIDC with Auth0」を参照。

Key Authでapikey認証を行い、Datakitでハードコードされたusername+passwordをbase64でエンコードしてDjangoに対してBasic認証をする。

pre functionの実装は参考として残しておく。
この実装は、ハードコードされたユーザー名とパスワードを利用して、form loginを行いSessionの情報を取得する方法。
このやり方は、通信が別で認証に発生するので遅いのと、管理が煩雑になる（luaのコードにクレデンシャルがハードコードされている）。


###  利用方法

1. Kong KonnectでControl Planeを作る。
2. Konnectの手順に従ってDataplaneをdockerで展開する。
3. Git cloneでこのレポジトリをclone。
4. `docker compose up --build -d` でDjangoを起動。
5. kong/kong.yaml のdeckファイルをdeckコマンドでsyncする。（情報の修正が必要）
6. 動作を確認する。

### 確認方法

Kong data planeと同じホスト内でcurlを実行する場合のコマンド。

```
curl -L -k https://127.0.0.1:8443/inventory/ -H "apikey:test" 
```
inventoryの結果が出力されれば成功。

### 補足
Djangoを直接実行してデータを入力することなどが可能。
```
ブラウザで以下を開く
http://127.0.0.1:3333/api/items
```

### MCP
Kong AI Gateway 2.2 で全エンドポイントを MCP ツールとして公開（upstream は Kong API Gateway）。`MCP_README.md` を参照。

詳しくは、下記の英文説明を参照。（Claude謹製）


# Inventory Management API (Django + DRF)

A small inventory management REST API, meant to sit behind Kong Konnect
(see `kong/README-kong.md`). Users authenticate at the gateway via OIDC;
Django itself only ever sees a single shared **service account** logged in
via a plain username/password session — Kong bridges the two (see
`kong/kong.yaml`).

## Setup (local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo   # creates the "kong_service" account + sample items
python manage.py runserver 3333
```

`seed_demo` creates three things: the `kong_service` account (used only by
Kong, see below), a regular sample user `user1` / `awesome user1` for the
web UI, and a few sample `Item` rows. To manage data through the Django
admin, additionally create a real admin user (`seed_demo` does not create
one):

```bash
python manage.py createsuperuser
```

## Setup (Docker)

```bash
docker compose up --build
```

This builds the image, runs migrations, seeds demo data, collects static
files, and serves the app with **gunicorn** on port `3333`. The API is
then reachable at `http://localhost:3333/api/...`.

Gunicorn (not `manage.py runserver`) is used here specifically because
this container is meant to sit behind Kong: Django's dev server doesn't
reliably support the HTTP/1.1 keep-alive connections a real reverse proxy
uses, and Kong reusing/pooling a connection to it can come back as a
`502 An invalid response was received from the upstream server`. Local,
non-Docker development (`manage.py runserver`, above) is unaffected —
that's fine for testing directly with curl/browser, just not for putting
a proxy in front of it.

`docker-compose.yml` has a commented-out `kong` service for running a
self-hosted Kong Gateway on the same compose network as Django, using
`kong/kong.yaml`. Kong can also run in its own separate
container/project instead (that's what `kong/kong.yaml` is currently set
up for, via `host.docker.internal`) — see `kong/README-kong.md` for both
paths and what Kong needs (a Kong Enterprise license via
`KONG_LICENSE_DATA`, and real OIDC IdP details) before it'll come up.

## Web UI (for end users)

A small server-rendered UI at `/` lets a regular, non-admin user log in and
manage inventory items in a browser — distinct from the JSON API (`/api/`)
and from the Django admin (`/admin/`, which needs its own superuser).

| Path                      | Description                          |
|---------------------------|---------------------------------------|
| `/` or `/items/`          | List items (login required)          |
| `/items/add/`             | Add an item                          |
| `/items/{id}/edit/`       | Edit an item                         |
| `/items/{id}/delete/`     | Delete an item (confirmation page)   |
| `/login/` / `/logout/`    | Session login/logout for the UI      |

Sample login: **`user1`** / **`awesome user1`** (created by `seed_demo`,
a plain user — not staff, so it cannot access `/admin/`).

## API

All endpoints are under `/api/`. Every endpoint below `IsAuthenticated`
requires either the `sessionid` cookie obtained from `/api/auth/login/`, or
an HTTP Basic Auth `Authorization` header with a valid Django username and
password.

| Method | Path                | Description                     |
|--------|---------------------|----------------------------------|
| POST   | `/api/auth/login/`  | Log in, sets `sessionid` cookie |
| POST   | `/api/auth/logout/` | Log out                         |
| GET    | `/api/items/`       | List items                      |
| POST   | `/api/items/`       | Create an item                  |
| GET    | `/api/items/{id}/`  | Retrieve an item                |
| PUT/PATCH | `/api/items/{id}/` | Update an item                |
| DELETE | `/api/items/{id}/`  | Delete an item                  |

### Example

```bash
# Login (saves the session cookie to cookies.txt)
curl -c cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{"username":"kong_service","password":"kong-service-demo-pw"}' \
  http://localhost:3333/api/auth/login/

# Authenticated request
curl -b cookies.txt http://localhost:3333/api/items/

# Authenticated request using HTTP Basic Auth instead of a session cookie
curl -u kong_service:kong-service-demo-pw http://localhost:3333/api/items/
```

### OpenAPI spec

The API's OpenAPI 3 schema is generated by `drf-spectacular`:

| Path                        | Description                        |
|-----------------------------|--------------------------------------|
| `/api/schema/`              | Raw OpenAPI schema (YAML/JSON)     |
| `/api/schema/swagger-ui/`   | Interactive Swagger UI             |
| `/api/schema/redoc/`        | ReDoc reference page               |

Regenerate a static copy with:

```bash
python manage.py spectacular --file schema.yaml
```

Requests without a valid session are rejected with `403`.

## Why session auth allows POST/PUT/DELETE without a CSRF token

`inventory/authentication.py` defines `CsrfExemptSessionAuthentication`, a
`SessionAuthentication` subclass that skips CSRF enforcement. Kong forwards
the `sessionid` cookie to Django on every proxied request but never holds a
matching CSRF cookie/token — there's no browser between Kong and Django, so
CSRF protection (which exists to stop browsers from being tricked into
sending cookies) doesn't apply on that hop; the browser-facing hop is
already protected by Kong's own OIDC login.

This exemption only applies to `/api/`. The web UI's own forms (`/login/`,
`/items/...`) are plain Django views with normal CSRF protection, since a
real browser is involved there.

## Gateway (Kong Konnect)

`kong/kong.yaml` (decK, control plane `django-apigw`) exposes the items API
on two routes of the same service. Both inject Django Basic auth with DataKit.

| Route                     | Client auth                                        |
|---------------------------|----------------------------------------------------|
| `/inventory/...`          | `apikey` header (key-auth); also used by the MCP server |
| `/oidc/inventory/...`     | Auth0 OIDC: browser session cookie, Bearer JWT, or client_credentials |
| `/static/...`             | None. Django/DRF CSS, JS, and images (whitenoise), needed by the browsable API pages |

See `kong/README-kong.md` for topology notes.

## OIDC with Auth0 (browser session + OAuth2 clients)

A single `openid-connect` plugin on `/oidc/inventory` covers both kinds of client:

```
Browser --(no cookie)--> Kong --302--> Auth0 login --callback--> Kong
        <--Set-Cookie: inventory_session (encrypted, Kong-side session)--
        --(cookie)--> Kong --(Basic, X-Authenticated-User/Email)--> Django

curl/app --(Authorization: Bearer <Auth0 JWT>)------------> Kong --> Django
curl/app --(Authorization: Basic <m2m client id:secret>)--> Kong --(client_credentials)--> Auth0
                                                               --> Django
```

| `auth_methods`        | Who uses it | What Kong does |
|-----------------------|-------------|----------------|
| `authorization_code`  | Browser     | Redirects to Auth0 and handles the callback |
| `session`             | Browser     | Validates the `inventory_session` cookie on each request |
| `bearer`              | curl / apps | Verifies the Auth0 JWT (signature via JWKS, issuer, expiry, `aud`) |
| `client_credentials`  | curl / apps | Exchanges the client id/secret for a token at Auth0 and caches it |

Session management is the OIDC plugin's built-in session (an encrypted cookie;
nothing stored server-side):

| Setting                      | Value        | Meaning |
|------------------------------|--------------|---------|
| `session_cookie_name`        | `inventory_session` | |
| `session_cookie_secure` / `_http_only` / `_same_site` | `true` / `true` / `Lax` | |
| `session_idling_timeout`     | 900 s        | Logged out after 15 min with no requests |
| `session_rolling_timeout`    | 3600 s       | Cookie is re-issued at least once an hour |
| `session_absolute_timeout`   | 28800 s      | Re-login required after 8 h, whatever the activity |
| `logout_uri_suffix`          | `/logout`    | `GET/POST /oidc/inventory/logout` clears the session and logs out of Auth0 |

### 1. Auth0 setup

In the Auth0 dashboard (https://manage.auth0.com):

1. **Create the API** (Applications > APIs > Create API)
   - Name: `Inventory API`
   - Identifier: `https://inventory-api`. This is the **audience**; it can't be changed later.
   - Signing algorithm: `RS256`

   Auth0 only issues JWT access tokens when an audience is requested.
   Without one, it returns opaque tokens that Kong can't verify.

2. **Create the browser app** (Applications > Applications > Create Application >
   *Regular Web Applications*), then under **Settings**:
   - Allowed Callback URLs: `https://localhost:8443/oidc/inventory/`
   - Allowed Logout URLs: `https://localhost:8443/oidc/inventory/`
   - Allowed Web Origins: `https://localhost:8443`
   - Save. Note the **Client ID** and **Client Secret**.
   - Advanced Settings > Grant Types: *Authorization Code* and *Refresh Token* are enabled.
   - **Allow this app to request tokens for the API on behalf of users.**
     Go to Applications > APIs > *Inventory API* > **Application Access**,
     edit this app and set **User Access** to *Authorized*. Alternatively,
     set the API's default User Access policy to *Allow*. Without this, the
     login callback fails with
     `error=invalid_request ... Client "<id>" is not authorized to access resource server "<audience>"`.

3. **Create the machine-to-machine app** (Create Application >
   *Machine to Machine Applications*), authorize it for **Inventory API**
   and save. Note its **Client ID** and **Client Secret**.

4. **Enable RP-initiated logout** (Settings > Advanced >
   *RP-Initiated Logout End Session Endpoint Discovery* = on). This adds
   `end_session_endpoint` to the discovery document, which Kong's
   `/logout` uses to also end the Auth0 session.

5. **Create a test user** (User Management > Users > Create User,
   *Username-Password-Authentication* connection), or log in with a social connection.

If you use a host other than `localhost:8443`, change `redirect_uri` and
`logout_redirect_uri` in `kong/kong.yaml` and the URLs above to match.

### 2. Configure and sync Kong

```bash
cp kong/auth0.env.example kong/auth0.env      # gitignored
# edit kong/auth0.env: tenant domain, both apps' client id/secret, audience, and
#   DECK_OIDC_SESSION_SECRET    -> openssl rand -hex 32
#   DECK_OIDC_CACHE_TOKENS_SALT -> openssl rand -hex 16
# Keep both values fixed: changing them invalidates every existing session.
source kong/auth0.env

export DECK_GW_TLS_CERT="$(awk '{printf "%s\\n",$0}' kong/tls/server.crt)"
export DECK_GW_TLS_KEY="$(awk '{printf "%s\\n",$0}' kong/tls/server.key)"

deck file validate kong/kong.yaml
deck gateway diff kong/kong.yaml --konnect-token-file ~/.kong/kpat \
  --konnect-control-plane-name django-apigw
deck gateway sync kong/kong.yaml --konnect-token-file ~/.kong/kpat \
  --konnect-control-plane-name django-apigw
```

The data plane must be able to reach `https://<tenant>.auth0.com` for
discovery, JWKS, and token calls. `KONG_LUA_SSL_TRUSTED_CERTIFICATE=system`
covers this.

### 3. Test from a browser

1. Open `https://localhost:8443/oidc/inventory/` and accept the self-signed
   certificate warning (Kong's default cert for `localhost`).
2. You're redirected to the Auth0 Universal Login. Sign in.
3. Auth0 sends you back to `/oidc/inventory/` and you see the DRF browsable API item list.
   DevTools > Application > Cookies shows `inventory_session`
   (Secure, HttpOnly, SameSite=Lax).
4. Reload, or open `/oidc/inventory/1/`. No new login is needed because the session cookie is used.
5. Open `https://localhost:8443/oidc/inventory/logout`. The Kong session is
   cleared, Auth0 logs you out and redirects back, and the next visit asks you to log in again.
6. Leave the tab idle for more than 15 minutes, then reload. You're asked to log in again.

### 4. Test from curl / applications

**a) Bearer token**: the app gets a token from Auth0 itself.

```bash
source kong/auth0.env

TOKEN=$(curl -s https://$AUTH0_DOMAIN/oauth/token \
  -H 'Content-Type: application/json' \
  -d "{\"grant_type\":\"client_credentials\",
       \"client_id\":\"$AUTH0_M2M_CLIENT_ID\",
       \"client_secret\":\"$AUTH0_M2M_CLIENT_SECRET\",
       \"audience\":\"$DECK_AUTH0_AUDIENCE\"}" | jq -r .access_token)

curl -k https://localhost:8443/oidc/inventory/ -H "Authorization: Bearer $TOKEN"

curl -k -X POST https://localhost:8443/oidc/inventory/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Widget","sku":"W-OIDC-1","unit_price":"9.99","quantity":5}'
```

**b) client_credentials through Kong**: the app sends its client id/secret
to Kong as HTTP Basic. Kong gets the token from Auth0, adding the audience,
and caches it.

```bash
curl -k -u "$AUTH0_M2M_CLIENT_ID:$AUTH0_M2M_CLIENT_SECRET" \
  https://localhost:8443/oidc/inventory/
```

**Negative checks**

```bash
curl -k -i https://localhost:8443/oidc/inventory/                       # 302 -> Auth0 /authorize
curl -k -i https://localhost:8443/oidc/inventory/ -H "Authorization: Bearer bad"  # 401
```

### Troubleshooting

- **The browser lands on `/oidc/inventory/?error=invalid_request&error_description=Client "..." is not authorized to access resource server "..."`**:
  the Regular Web Application has no *User Access* to the API. See step 1.2.
  If the error names the M2M client instead, its *Client Access* is
  missing; see step 1.3.
- **`no Route matched with those values` after a successful sync**: the DP
  rejected the new config and kept running the old one. Check
  `docker logs <dp> 2>&1 | grep 'bad config'`. On Kong 3.16+ the
  `openid-connect` plugin needs `ssl_verify: true`, because global
  `tls_certificate_verify` is on. `kong/kong.yaml` already sets it.
- **Unauthenticated curl gets `302` instead of `401`**: this is expected.
  `authorization_code` is enabled on the route, so any request without
  credentials is sent to the login page.
- **`Callback URL mismatch`** on the Auth0 page: the Allowed Callback URLs
  don't exactly match `redirect_uri`, including the trailing `/`.
- **`401` with a valid-looking token**: `aud` doesn't contain
  `DECK_AUTH0_AUDIENCE`, or the token is opaque because no audience was
  requested. Decode it at https://jwt.io to check.
- **`client_credentials` returns `401`**: the M2M app isn't authorized for
  the API (step 1.3), or *Client Credentials* isn't one of its grant types.
- **Logout doesn't end the Auth0 session**: RP-initiated logout discovery
  (step 1.4) is off, or the logout URL isn't in *Allowed Logout URLs*.
- **Everyone is logged out after a sync**: `DECK_OIDC_SESSION_SECRET`
  changed.
- The apikey route (`/inventory`) and the MCP server don't change.
  `curl -k https://localhost:8443/inventory/ -H "apikey:test"` still works.

## MCP server (Kong AI Gateway 2.2)

`kong/ai-gateway.yaml` exposes every item endpoint as an MCP tool at
`/mcp/inventory` on a Kong AI Gateway 2.2 data plane, which uses this
Kong Gateway as its upstream. See `MCP_README.md`.
