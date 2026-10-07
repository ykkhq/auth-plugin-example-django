# Securing the Django API with Kong: recommendations

This is a review of the current setup (Kong Gateway 3.16 on Konnect, Auth0 OIDC,
Django + DRF). It lists what to change to reach a production-grade, defense-in-depth
design, most important first. Config snippets are sketches to adapt and validate
(`deck gateway validate`), not drop-in files.

## The target design

The most secure pattern is **zero trust between every hop**. No component trusts a
request just because of *where* it came from.

```
Client ──TLS──▶ Kong: authenticate (OIDC) + authorize (scopes/roles) + limit + validate
       ──mTLS──▶ Django: verify a signed token itself, enforce per-user permissions
```

1. **Kong authenticates and authorizes**: it decides *who* the caller is and *whether*
   they may call this route and method. This happens before any request reaches Django.
2. **The user's real identity reaches Django**, not a shared service account.
3. **Django verifies that identity cryptographically** (a signed JWT) rather than
   trusting a header because "only Kong can reach me".
4. **Kong ↔ Django is mutually authenticated TLS (mTLS)**, so nothing else can talk to
   Django even inside the network.
5. **No secrets in files or plugin configs**: they come from a vault.

## What the current setup already does well

- OIDC with Auth0 (authorization code + PKCE) for browsers, and Bearer /
  client_credentials for apps. Tokens are verified with JWKS, and `aud` is required.
- Encrypted, `Secure`, `HttpOnly`, `SameSite=Lax` session cookie with idle, rolling
  and absolute timeouts, plus RP-initiated logout.
- Per-user rate limiting by the token's `sub` claim.
- Django is not published, only reachable from Kong on `kong-net`.
- Client-sent `X-Authenticated-User` is stripped or overwritten on every route.
- `ssl_verify: true` toward Auth0, and a private CA for the AI Gateway → Kong hop.

## Gaps found in this repo

| # | Finding | Where | Risk |
|---|---|---|---|
| G1 | Every API call reaches Django as the single user `user1`, with its password hardcoded (`awesome user1`) | DataKit plugins in `kong/kong.yaml` | No per-user authorization in Django. The password sits in git and in Konnect. |
| G2 | Django trusts `X-Authenticated-User` based on network placement only | `inventory/gateway.py`, `kong-net` | Anything that gets onto `kong-net` (a compromised container, a published debug port) can impersonate any user |
| G3 | No authorization at the gateway: any valid token can read, write and delete | OIDC plugins | A user or M2M client that only needs to read can delete all items |
| G4 | Guessable static API keys (`test`, `awsome user1`) and a basic-auth credential in `kong.yaml` | `consumers:` | Anyone who guesses `test` gets full API access through `/inventory` |
| G5 | Django runs with `DEBUG = True`, a hardcoded `SECRET_KEY` and `ALLOWED_HOSTS = ['*']` | `settings.py` | Stack traces and settings leak on errors. Session and CSRF signing can be forged if the key leaks. |
| G6 | The Auth0 **Regular Web Application can use the client_credentials grant** (verified: returns 200) | Auth0 dashboard | The browser app's secret also works as a machine credential |
| G7 | Secrets (client secret, session secret) are stored as plain plugin config | `kong.yaml` → Konnect | Anyone with Konnect read access sees them |
| G8 | Kong reveals its exact version (`Server: kong/3.16.0.0-enterprise-edition`), and there are no security headers (HSTS etc.) | Responses | Easier fingerprinting, no HSTS downgrade protection |
| G9 | Self-signed default certificate on `localhost:8443` | Kong | Users learn to click through certificate warnings |
| G10 | Cookie-based sessions can't be revoked on the server | `session_storage: cookie` | A stolen cookie works until it times out (up to 8 h) |
| G11 | A disabled `pre-function` with Lua that makes HTTP calls is still in config, and the DP may run with `untrusted_lua` set to `lax` | `kong.yaml`, DP env | A larger attack surface if someone re-enables it |
| G12 | The MCP path uses a static apikey shared by all MCP clients | `kong/ai-gateway.yaml` | No per-user identity or revocation for AI agents |

## Recommendations

### P1: Do these first

**1. Pass the real user to Django and verify it there (fixes G1, G2)**

Stop replacing the caller's credentials with `Basic user1`. Remove the DataKit plugins
and let `openid-connect` forward the verified access token (its default
`upstream_access_token_header` is `Authorization: Bearer <token>`). Django then
verifies the JWT itself against Auth0's JWKS:

```python
# settings.py: DRF verifies the Auth0 JWT, then maps sub to a user
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
}
SIMPLE_JWT = {
    "ALGORITHM": "RS256",
    "JWK_URL": "https://<tenant>.us.auth0.com/.well-known/jwks.json",
    "AUDIENCE": "https://django-inventory-endpoint.com",
    "ISSUER": "https://<tenant>.us.auth0.com/",
    "USER_ID_CLAIM": "sub",
    "USER_ID_FIELD": "username",
}
```

Do the same for the web UI by verifying the token instead of trusting
`X-Authenticated-User`. Option: use Kong's **`jwt-signer`** plugin to re-sign a short-lived
internal token with a Kong-owned key, `aud=django` and 1–5 min expiry. Django then trusts
only Kong's key, and Auth0 tokens never reach the backend.

**2. Authorize at the gateway with scopes or roles (fixes G3)**

In Auth0, define API permissions (`read:items`, `write:items`) and enable *RBAC* plus
*Add Permissions in the Access Token*. Split routes by method and require the scope:

```yaml
# route django-route-items-oidc-m2m-read (GET only)
- name: openid-connect
  config:
    scopes_claim: [permissions]
    scopes_required: ["read:items"]
# route ...-write (POST/PUT/PATCH/DELETE)
    scopes_required: ["write:items"]
```

Keep a second layer of checks in Django (DRF permissions based on the same claims),
so a gateway misconfiguration doesn't open the API.

**3. Mutual TLS between Kong and Django (fixes G2)**

Even on a private network, make Django accept only Kong's client certificate:

```yaml
# kong.yaml
services:
- name: django-api-items
  protocol: https
  host: django
  port: 3443
  tls_verify: true
  ca_certificates: [<django-ca-id>]
  client_certificate: { id: <kong-client-cert-id> }
```

```bash
# Django container: gunicorn requires a client cert signed by the internal CA
gunicorn ... --certfile server.crt --keyfile server.key \
  --ca-certs kong-client-ca.crt --cert-reqs 2
```

`kong/gen-tls.sh` already builds a private CA, so reuse it for these certificates.

**4. Remove static credentials and fix the Django basics (fixes G4, G5, G11)**

- Delete the `test` and `awsome user1` API keys and the basic-auth credential.
  If apikey access must stay, generate long random keys per consumer and store them
  in a vault.
- Django: `DEBUG = False`, `SECRET_KEY` from an environment variable or vault, and
  `ALLOWED_HOSTS = ["django"]` (the only host Kong uses).
  Also set `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE` and
  `CSRF_COOKIE_SECURE = True`.
- Delete the disabled `pre-function`, and run the DP with
  `KONG_UNTRUSTED_LUA=sandbox` (or `off` if no Lua plugins are needed).

**5. Lock down the Auth0 applications (fixes G6)**

- Regular Web Application: disable the *Client Credentials* grant. It only needs
  *Authorization Code* (and *Refresh Token*).
- M2M application: grant it only the scopes it needs.
- Tenant: enable MFA, brute-force protection and breached-password detection; keep
  access tokens short-lived (5–15 min); use refresh token rotation.

### P2: Strongly recommended

**6. Keep secrets out of config (fixes G7):** use Kong Vault references, such as the
Konnect Config Store or AWS, GCP, Azure and HashiCorp vaults. The plugin config then
holds only a pointer:

```yaml
client_secret: ["{vault://konnect/auth0-web-client-secret}"]
session_secret: "{vault://konnect/oidc-session-secret}"
```

**7. Server-side sessions with revocation (fixes G10):** set
`session_storage: redis` (plus `session_redis_*` settings) so logout and admin
revocation take effect immediately. Also consider:
- `logout_revoke: true`, which revokes tokens at Auth0 on logout;
- a shorter `session_absolute_timeout`, for example 1–2 h;
- `SameSite=Strict` on the API route.

**8. TLS and response hardening (fixes G8, G9):**
- Use a real certificate (ACME plugin or a managed cert) for the public hostname.
  Allow only TLS 1.2+ (`KONG_SSL_PROTOCOLS="TLSv1.2 TLSv1.3"`).
- Hide version headers with `KONG_HEADERS=off`, or `latency_tokens` only.
- Add security headers with `response-transformer` on the browser routes:
  ```yaml
  add:
    headers:
    - "Strict-Transport-Security: max-age=63072000; includeSubDomains"
    - "X-Content-Type-Options: nosniff"
    - "Referrer-Policy: strict-origin-when-cross-origin"
    - "Content-Security-Policy: default-src 'self'"
  ```
- Close the plain-HTTP listener (`:8000`), or redirect it to HTTPS.

**9. Validate requests before they reach Django:**
- `request-size-limiting` (for example 1 MB) on all routes.
- `oas-validation`, using the OpenAPI schema Django already generates
  (`/api/schema/`), to reject unknown paths, bad bodies and wrong types at the gateway.
- `cors` with an explicit origin list, if any browser app calls the API cross-origin.
- Only expose what is needed. Keep `/admin/` and `/api/schema*` unrouted, or behind
  a separate admin-only OIDC route that requires a role.

**10. Harden rate limiting:**
- `policy: redis`, so limits hold across several DP nodes.
- An IP-based limit in front of authentication (for example `rate-limiting-advanced`
  at service level). This blunts credential stuffing on the client_credentials route,
  where each new id/secret pair makes Kong call Auth0.
- Optional: `bot-detection` on the browser routes.

### P3: Operations

**11. Logging, monitoring and alerts:** send Kong logs to a SIEM (`http-log` / `tcp-log`)
without tokens or cookies in them. Use Konnect Analytics, and alert on 401, 403 and 429
spikes and on unusual per-user volume.

**12. Secure MCP access (fixes G12):** replace the shared apikey on the AI Gateway MCP
server with OAuth (an Auth0 token per agent or user), so agent calls get the same
per-user identity, scopes and rate limits as everything else.

**13. Keep everything current:**
- Patch Kong, Django and Auth0 SDK versions.
- Rotate the DP cluster certificate and the session secret on a schedule.
- Run the DP as non-root (the distroless image already does), with a read-only filesystem.

## Suggested order of work

| Step | Change | Effort |
|---|---|---|
| 1 | Remove static API keys, set Django `DEBUG=False`, `SECRET_KEY` from env, `ALLOWED_HOSTS` (G4, G5) | Small |
| 2 | Auth0: disable client_credentials on the web app; enable MFA and RBAC (G6) | Small |
| 3 | Gateway scopes: read/write routes with `scopes_required` (G3) | Medium |
| 4 | Forward the token and verify the JWT in Django; drop DataKit `user1` (G1, G2) | Medium |
| 5 | Kong ↔ Django mTLS (G2) | Medium |
| 6 | Vault references for all secrets (G7) | Small–Medium |
| 7 | Redis sessions and rate limits, security headers, real TLS cert (G8–G10) | Medium |
| 8 | OAuth for MCP; logging and alerting (G12) | Medium |
