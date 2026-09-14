# Kong Konnect setup for the Inventory API

`kong.yaml` is a decK declarative state file that puts a Konnect-managed
Kong gateway in front of the Django inventory API from this repo.

## Auth model

```
Browser --(OIDC login)--> Kong --(shared service-account session)--> Django
```

- **Browser <-> Kong**: the `openid-connect` plugin on `inventory-route`
  redirects users to your real IdP (Okta, Auth0, Keycloak, Azure AD, ...)
  and manages a Kong-side session cookie after that.
- **Kong <-> Django**: a `pre-function` plugin logs into Django's
  `/api/auth/login/` as one fixed **shared service account**
  (`kong_service`, created by `python manage.py seed_demo` in the Django
  project) and forwards the resulting `sessionid` cookie upstream. Django
  never sees or needs to know about the individual OIDC identity.

This is intentionally the simplest possible bridge for a demo. It is *not*
production-hardened — see the "Before using this for real" section below.

## Running Kong and Django as separate containers/projects

`kong.yaml`'s `services[].url` and the `pre-function` plugin's
`django_login_url` currently point at `http://host.docker.internal:3333`
— this is for when **Kong runs in its own container or compose project**,
separate from this repo's `docker-compose.yml` (i.e. a different Docker
network than the `django` service). `host.docker.internal` lets Kong's
container reach Django's host-published port (`3333:3333` in
`docker-compose.yml`).

- Works out of the box on Docker Desktop (macOS/Windows).
- On Linux Docker Engine, `host.docker.internal` isn't automatic — add to
  wherever Kong's container is defined:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```
- Make sure Django is actually running and reachable first (`docker
  compose up --build` in this repo) — Kong logging in on every request
  means a "connection refused" from the `pre-function` plugin usually
  just means Django isn't up yet at that address.
- Run Django via the Docker container (gunicorn), not `manage.py
  runserver`, when anything proxies to it. Django's dev server doesn't
  reliably support the persistent/keep-alive connections Kong uses to its
  upstream, which surfaces as `502 An invalid response was received from
  the upstream server` — not a `pre-function` error at all, since by that
  point the plugin already succeeded and Kong is proxying the real
  request straight through.

### Alternative: one shared docker-compose stack

This repo's `docker-compose.yml` also has a commented-out `kong` service
that runs Kong on the *same* compose network as `django` — if you use
that instead (uncomment it), switch `kong.yaml` back to
`http://django:3333` (the compose service name) instead of
`host.docker.internal`, since containers on the same compose network
resolve each other by service name directly. That path needs:

```bash
export KONG_LICENSE_DATA="$(cat /path/to/your/license.json)"
docker compose up --build
```

- The `openid-connect` plugin is **Kong Enterprise only** — it isn't in
  the plain OSS `kong` image, which is why that service uses
  `kong/kong-gateway` and requires `KONG_LICENSE_DATA` (a Konnect
  free/dev/trial license works).
- Kong's proxy would be published on `localhost:8000` (what a browser
  should hit — not Django's `3333` directly) and its Admin API on
  `localhost:8001`.

Either way, you still need to replace the OIDC placeholders below before
login actually works end-to-end against a real IdP.

## Prerequisite: allow `resty.http` in the Lua sandbox

By default, Kong Gateway runs `pre-function`/`post-function` Lua in a
sandbox that blocks `require(...)` for anything not explicitly
allow-listed — this is a security feature, not a bug. Without it, the
`pre-function` plugin above fails with:

```
<source>:1: require("resty.http") not allowed within sandbox
```

This is a **node-level Kong Gateway setting**, not something `kong.yaml`
or decK can configure — it has to be set on the data plane itself, then
the node restarted. `docker-compose.yml` already does this for the local
`kong` service via:

```bash
KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES=resty.http,cjson.safe
```

If you're running Kong elsewhere (not via this repo's compose file), set
the same thing there — as that env var, or in `kong.conf`:

```
untrusted_lua_sandbox_requires = resty.http,cjson.safe
```

This only works if you control the Kong Gateway node's configuration
(a self-hosted data plane, whether local or connected to Konnect). If
you're using a **Konnect-hosted/managed data plane** where you can't set
node-level config, `pre-function` cannot make outbound HTTP calls at all
— the sandbox restriction can't be lifted from the plugin config side. In
that case, the OIDC<->Django bridge has to move to a real custom plugin
installed on infrastructure you control, not `pre-function`.

## Before you sync this file

Replace every `REPLACE_WITH_...` placeholder in `kong.yaml`:

- `services[].url` and the `pre-function` plugin's `django_login_url` —
  both default to `http://host.docker.internal:3333` (Kong in its own
  container reaching Django's host-published port). Change this if your
  topology differs — e.g. `http://django:3333` if Kong and Django share
  one compose network instead (see above).
- `openid-connect` plugin config: `issuer`, `client_id`, `client_secret`,
  `redirect_uri` — from your real IdP's application registration.
- `session_secret` and `cache_tokens_salt` — random per-environment values
  (`openssl rand -hex 32` / `openssl rand -hex 16`).
- The `pre-function` plugin's `django_login_url`, `service_username`, and
  `service_password` Lua locals — match whatever you seeded in Django.

## Sync

Against Konnect:

```bash
deck gateway sync -s kong.yaml \
  --konnect-control-plane-name <your-control-plane-name>
```

Against a local Kong instance (for testing without Konnect):

```bash
deck gateway sync -s kong.yaml
```

Offline structural check before syncing anywhere:

```bash
deck file validate kong.yaml
```

## Before using this for real

The `pre-function` plugin in `kong.yaml` is written for clarity, not
production use:

- It calls Django's login endpoint on **every** proxied request. A real
  deployment should cache the `sessionid` per Kong worker (`kong.cache` or
  an `ngx.shared.DICT`) with a TTL kept below Django's
  `SESSION_COOKIE_AGE`, only re-logging in on a cache miss or once Django
  returns `401`/`403` for the cached session.
- The service-account password is inlined as plain Lua for readability.
  Use a Kong Vault reference (e.g. `{vault://env/DJANGO_SERVICE_PASSWORD}`)
  instead of a literal value.
- Consider moving the bridge logic into a small custom Kong plugin instead
  of `pre-function` once it needs caching/retry logic — easier to test and
  version than an inline Lua string.
