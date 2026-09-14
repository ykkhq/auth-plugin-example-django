# Djangoに対して認証をするKong pluginのデモ

### 流れ
Client(curl) --(apikey認証)--> Kong API gateway (dp) --(basic 認証)--> Django

### 利用Kong Plugin
- Key auth
- Datakit
- pre function (サンプル、利用しない)

Key Authでapikey認証を行い、Datakitでハードコードされたusername+passwordをbase64でエンコードしてDjangoに対してBasic認証をする。

pre functionの実装は参考として残しておく。
この実装は、ハードコードされたユーザー名とパスワードを利用して、form loginを行いSessionの情報を取得する方法。
このやり方は、通信が別で認証に発生するので遅いのと、管理が煩雑になる（luaのコードにクレデンシャルがハードコードされている）。


###  利用方法

1. Kong KonnectでControl Planeを作る。
2. Konnectの手順に従ってDataplaneをdockerで展開する。
3. Git cloneでこのレポジトリをclone。
4. `docker compose --build up -d` でDjangoを起動。
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

See `kong/kong.yaml` and `kong/README-kong.md` for the decK state file that
puts Kong Konnect in front of this API with OIDC login for end users.
