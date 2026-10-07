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

セッションの保存場所：Kong側には保存しない。ログイン後のセッション情報（トークン等）は
`session_secret` で暗号化され、ブラウザの `inventory_session` クッキー自体に入る
（`session_storage: cookie`、デフォルト）。サーバー側で即時に無効化したい場合は
`session_storage: redis` に変更する（クッキーにはセッションIDのみ入り、本体はRedisに保存される）。
詳細と切り替え手順は下記英文の「Where sessions are stored」「Switching to Redis」を参照。

Django側の変更：OIDC認証はKong側で完結し、Djangoはトークンを一切扱わない。Web UI（`/items`）用に、
Kongが転送する `X-Authenticated-User`（Auth0の `sub`）でログインさせる `RemoteUserBackend` と
`inventory/gateway.py` のミドルウェアを追加、`CSRF_TRUSTED_ORIGINS` を設定、ログアウトをKongの
`/items/logout` に変更、Djangoのポートを非公開にした（Kong以外からヘッダーを偽装させないため）。
API（`/oidc/inventory`）側のDjangoは変更なし（従来通り `kong_service` のBasic認証）。
詳細は下記英文の「What changed on the Django side」を参照。

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
DjangoのWeb UIはKong経由で開く（Auth0でログイン）。
```
ブラウザで以下を開く
https://localhost:8443/items/
```
Djangoのポート3333は公開していない（Kongが渡すユーザーヘッダーを信頼するため、Kong以外から直接アクセスさせない）。
デバッグ時のみ `docker-compose.yml` の `127.0.0.1:3333` を有効化する。

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
files, and serves the app with **gunicorn** on port `3333`. The container
joins the private `kong-net` network and **doesn't publish the port**,
because Django trusts the user header Kong sends (see "Web UI through Kong"
below). Reach it through Kong, or for local debugging uncomment the
`127.0.0.1:3333` port in `docker-compose.yml`. With the port published, anyone
on the host could fake a user.

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
| `/items/...`              | Auth0 OIDC browser login (shared session). Django web UI logged in as the Auth0 user |
| `/static/...`             | None. Django/DRF CSS, JS, and images (whitenoise), needed by the browsable API pages |

See `kong/README-kong.md` for topology notes.

## OIDC with Auth0 (browser session + OAuth2 clients)

`/oidc/inventory` serves both kinds of client. It is two Kong routes on the same path,
each with its own `openid-connect` plugin (same Auth0 config):

- `django-route-items-oidc-m2m` matches requests that carry an `Authorization: Bearer …`
  or `Authorization: Basic …` header. It allows `bearer` and `client_credentials`, and
  sends **no scopes**. Auth0 rejects a client_credentials request that asks for
  `openid profile email` (`403 Client has not been granted scopes`), and the plugin
  sends its `scopes` on every token request.
- `django-route-items-oidc` handles everything else (browsers). It allows
  `authorization_code` and `session`, with scopes `openid profile email`.


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

### Where sessions are stored

**Kong keeps no session state.** `session_storage` is left at its default, `cookie`:

- After the Auth0 login, Kong puts the session data (ID token, access token, any
  refresh token, expiry and timeouts) **into the `inventory_session` cookie itself**,
  encrypted with `session_secret` (`DECK_OIDC_SESSION_SECRET`). The browser holds the
  cookie but can't read or change it.
- On every request, Kong decrypts and checks the cookie. There is no server-side
  lookup, so any Kong node, and both `/oidc/inventory` and `/items`, accept the same
  cookie.
- Tokens are large, so Kong may split the cookie into several parts
  (`inventory_session`, `inventory_session_2`, …).

Kong's per-node **memory cache** holds Auth0's discovery document, its signing keys
(JWKS), tokens obtained through client_credentials, and the rate-limit counters
(`policy: local`). It holds no user sessions, and it is lost when the container restarts.

The **web UI (`/items`) also has a Django session**: when `RemoteUserBackend` logs the
Auth0 user in, Django sets its own `sessionid` cookie and stores the session in its
database (the `django_session` table in the container's SQLite). It only remembers which
Django user the browser is. Kong re-sends the verified user on every request anyway.

| | Cookie storage (current) | Server-side: `session_storage: redis` / `memcached` |
|---|---|---|
| Session data | In the browser, encrypted | In Redis or Memcached; the cookie only holds a session ID |
| Extra infrastructure | None | A Redis or Memcached server |
| Logout | Clears that browser's cookie. A copied cookie stays valid until the idle (15 min) or absolute (8 h) timeout. | Deletes the session on the server, so every copy stops working at once |
| Cookie size | Large (tokens inside) | Small |
| Several Kong nodes | Works as is | All nodes must share the same Redis |

Cookie storage is fine for this demo. Switch to `session_storage: redis` (plus the
plugin's `session_redis_*` settings) if logout must end a session everywhere
immediately, or if cookie size becomes a problem.

#### Switching to Redis (not applied in this demo)

1. Add Redis to `docker-compose.yml` on `kong-net`, so the Kong DP reaches it as
   `redis:6379`. Don't publish its port, for the same reason Django's isn't:

   ```yaml
     redis:
       image: redis:7-alpine
       command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}"]
       networks: [kong-net]
   ```

2. In the `openid-connect` plugin in `kong/kong.yaml`, next to the other `session_*`
   settings:

   ```yaml
   session_storage: redis
   session_redis_host: redis
   session_redis_port: 6379
   session_redis_password: "${{ env "DECK_REDIS_PASSWORD" }}"
   # session_redis_ssl: true    # for a TLS Redis
   ```

   Keep `session_secret`, because Kong still uses it to protect the cookie. Check the
   field names against your Kong version with `deck file validate` or
   `deck gateway diff` before syncing.

3. To verify, log in at https://localhost:8443/items/ and run
   `docker exec <redis-container> redis-cli -a "$REDIS_PASSWORD" --scan`. The session
   key should be listed, and `inventory_session` should be a single small cookie.

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

5. **Set the Default Audience** (Settings > General > API Authorization Settings >
   *Default Audience* = `https://inventory-api`, your API identifier). When an app
   sends its client id/secret to Kong (client_credentials), Kong's token request to
   Auth0 can't include `audience`, and Auth0 answers `403 access_denied: No audience
   parameter was provided`. The default audience fills that in.

6. **Create a test user** (User Management > Users > Create User,
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

### Per-user rate limit

Both `/oidc/inventory` routes have Kong's `rate-limiting` plugin: **10 requests/minute and
200/hour per user**. `openid-connect` turns each token's `sub` claim into a virtual
credential (`credential_claim`, default `sub`), and `rate-limiting` counts by it
(`limit_by: credential`). So every Auth0 user and every M2M client has its own counter,
with no Kong consumers to manage. Counting uses the verified token, not a
client-supplied header, so it can't be bypassed by spoofing.

```bash
for i in $(seq 1 12); do
  curl -sk -o /dev/null -w '%{http_code} ' -u "$AUTH0_M2M_CLIENT_ID:$AUTH0_M2M_CLIENT_SECRET" \
    https://localhost:8443/oidc/inventory/
done
# 200 200 200 200 200 200 200 200 200 200 429 429
```

Responses include `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` and
`X-RateLimit-Remaining-Minute/-Hour`. A `429` also has `Retry-After`.
Change the limits in `kong/kong.yaml` (`&per_user_rate_limit`). `policy: local` keeps
counters on each data plane node; with several nodes, use `policy: redis` so they share
one counter. The apikey route (`/inventory`) and the web UI (`/items`) are not limited.

### 5. Web UI (`/items/`) through Kong

The server-rendered UI is also behind Auth0. It uses the same Auth0 app and the same
`inventory_session` cookie, so one login covers both `/items/` and `/oidc/inventory/`.
Django's side is its built-in remote-user support. No extra package is needed.

```
Browser --(Auth0 login / inventory_session)--> Kong /items  [openid-connect]
        --(X-Authenticated-User = Auth0 "sub")--> django:3333/items/   (kong-net only)
```

- Kong's `openid-connect` plugin sets `X-Authenticated-User` to the verified `sub`
  claim on every request. This replaces any value the client sent.
- Django logs that user in with `RemoteUserBackend`, creating the Django user on the
  first visit. `inventory/gateway.py` is the 2-line `PersistentRemoteUserMiddleware`
  subclass that reads that header; this is the pattern Django's docs recommend.
- **Django trusts the header because only Kong can reach it.** Django runs on the
  private `kong-net` Docker network with no published port, and Kong calls it at
  `http://django:3333`. The `/inventory` (apikey) and `/static` routes have no OIDC
  plugin to overwrite the header, so a `request-transformer` strips any
  client-sent copy there.
- The add, edit and delete forms keep Django's CSRF protection.
  `CSRF_TRUSTED_ORIGINS=https://localhost:8443` makes Django accept form posts
  that come through Kong.
- **Log out** goes to `/items/logout`. Kong ends the Kong session and the Auth0 session.
- The UI shows the Django username, which is the Auth0 `sub`
  (e.g. `auth0|66ab…`). To show emails instead, add an Auth0 Action that puts
  `email` into the access token, and forward that claim as the user header.

Setup:

1. Auth0 → your Regular Web Application → add `https://localhost:8443/items/` to
   **Allowed Callback URLs** and **Allowed Logout URLs**.
2. Start Django on `kong-net`, and attach the Kong data plane to the same network:
   ```bash
   docker compose up --build -d                      # creates kong-net
   docker network connect kong-net <kong-dp-container>
   docker restart <kong-dp-container>                # Kong reads DNS at startup
   ```
   Or add `--network kong-net` to the data plane's `docker run` command.
3. Sync Kong:
   ```bash
   source kong/auth0.env
   deck gateway sync kong/kong.yaml --konnect-token-file ~/.kong/kpat \
     --konnect-control-plane-name django-apigw
   ```
4. Open `https://localhost:8443/items/`, sign in at Auth0, and you land on the item list.

#### What changed on the Django side

Kong does all of the OIDC work: the Auth0 login, token checks and the session. Django
never sees a token. The only Django changes let it accept the user Kong forwards:

| File | Change |
|------|--------|
| `inventory/gateway.py` | New `KongRemoteUserMiddleware` (`PersistentRemoteUserMiddleware` with `header = "HTTP_X_AUTHENTICATED_USER"`). It reads the header because gunicorn can't set `REMOTE_USER` from one. Being "Persistent", it doesn't log the user out on a request without the header. |
| `inventory_management/settings.py` | `MIDDLEWARE`: the middleware above, after `AuthenticationMiddleware`. `AUTHENTICATION_BACKENDS`: `RemoteUserBackend` (creates and logs in the user), then `ModelBackend` (keeps password login for `/login/` and `kong_service`). `CSRF_TRUSTED_ORIGINS` from the environment, default `https://localhost:8443`. |
| `inventory/templates/inventory/base.html` | When `X-Authenticated-User` is present, **Log out** links to Kong's `/items/logout` instead of posting to Django's logout. |
| `docker-compose.yml` | Port 3333 no longer published. Django is reachable only on `kong-net`, which is what makes trusting the header safe. |

The JSON API is unchanged. On `/oidc/inventory`, Kong checks the OIDC token and then
calls Django with Basic auth as the shared `kong_service` account, just like the apikey
route. So the API sees one service account, and only the web UI (`/items`) sees
individual Auth0 users.

### Troubleshooting

- **`503` and `DNS resolution failed ... django` in the data plane log**: the Kong
  container isn't on `kong-net`, or it was attached without a restart afterwards.
- **`403 CSRF verification failed`** on a form: `CSRF_TRUSTED_ORIGINS` doesn't
  include the URL in the browser's address bar.
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
- **`client_credentials` through Kong returns `401`**: the tenant's Default Audience
  isn't set (step 1.5), the M2M app isn't authorized for the API (step 1.3), or
  *Client Credentials* isn't one of its grant types.
- **Logout doesn't end the Auth0 session**: RP-initiated logout discovery
  (step 1.4) is off, or the logout URL isn't in *Allowed Logout URLs*.
- **Everyone is logged out after a sync**: `DECK_OIDC_SESSION_SECRET`
  changed.
- The apikey route (`/inventory`) and the MCP server don't change.
  `curl -k https://localhost:8443/inventory/ -H "apikey:test"` still works.

## Monitoring with Grafana (route and user activity)

`monitoring/` runs Prometheus, Loki, Grafana Alloy and Grafana on `kong-net`, with two
provisioned dashboards in the **Kong** folder:

| Dashboard | Source | Shows |
|---|---|---|
| **Kong · Route activity** | Prometheus (Kong `prometheus` plugin) | Requests/s by route, success rate, status classes, p95 latency (total, Kong vs Django), 401/403/429 by route, bandwidth |
| **Kong · User activity** | Loki (Kong `file-log` JSON) | Active users, requests per user, top users, p95 latency per user, top rate-limited users, 401s by client IP, per-user/route/status table, recent requests |

```
Kong DP ──prometheus plugin──▶ /kong-metrics (kong-net only) ◀── Prometheus ─┐
        ──file-log JSON → stdout──▶ Alloy (Docker logs) ──▶ Loki ────────────┼──▶ Grafana :3000
```

How the user is identified: the `file-log` plugin adds a `user` field set to the
`openid-connect` virtual credential, which is the token's `sub` (an Auth0 user
`auth0|…`, or an M2M client `<client-id>@clients`). On the apikey route it is the
key-auth credential id. Request and response headers are removed from the log, so
cookies and tokens are never stored. `user` is not a Loki label (that would mean too
many label values); queries parse it with `| json`.

Kong config (in `kong/kong.yaml`): global `prometheus` and `file-log` plugins, plus a
`kong-metrics` service and route. The route loops back to the DP's own status API
(`127.0.0.1:8007/metrics`), and `ip-restriction` allows only `kong-net`
(`172.18.0.0/16`). From the host it returns 403.

Setup:

```bash
# 1. Kong DP on kong-net with the alias Prometheus scrapes
docker network connect --alias kong-dp kong-net <kong-dp-container>
# 2. Sync kong/kong.yaml (adds the plugins and the metrics route)
# 3. Start the stack
cd monitoring && GRAFANA_ADMIN_PASSWORD='<choose one>' docker compose up -d
```

Open http://localhost:3000 (user `admin`; the password defaults to `admin` if unset).
Grafana and Prometheus (`:9090`) are published on `127.0.0.1` only.
To change a dashboard, edit `monitoring/grafana/generate_dashboards.py` and rerun it.
Grafana reloads the JSON within about 10 seconds.

Notes:
- Prometheus `increase()` needs two samples, so the first occurrence of a new status
  code on a route isn't counted in "Rate-limited (429) in range". The Loki-based user
  dashboard counts every request.
- Alloy reads all container logs through the Docker socket, but keeps only Kong
  access-log lines and drops Prometheus's own scrapes.

## MCP server (Kong AI Gateway 2.2)

`kong/ai-gateway.yaml` exposes every item endpoint as an MCP tool at
`/mcp/inventory` on a Kong AI Gateway 2.2 data plane, which uses this
Kong Gateway as its upstream. See `MCP_README.md`.
