#!/bin/zsh
# Sets up and starts the whole demo, local and Konnect (the reverse of
# ./cleanup.sh). Safe to re-run: existing certs and Konnect resources are
# reused, and the data-plane containers are recreated.
#   1. certs: private CA + Kong GW server cert (kong/tls/), DP client certs
#      (kong/gw-certs/, kong/ai-certs/)
#   2. Django (docker compose; also creates the kong-net network)
#   3. Konnect: control plane "django-apigw" + AI Gateway "django-ai-gw"
#      (kong/konnect.yaml), Kong GW config (kong/kong.yaml, decK)
#   4. Kong Gateway DP "django-apigw-dp" (:8000/:8443, on kong-net as kong-dp)
#   5. API Catalog + Dev Portal (kong/portal.yaml): API spec, portal with
#      developer sign-up, pages
#   6. MCP users + metering policy (kong/ai-gateway-billing.yaml), MCP servers
#      (kong/ai-gateway.yaml), billing catalog (kong/mcp_billing.py), AI Gateway DP (:11000/:11443)
#   7. monitoring stack (Grafana :3000), unless --no-monitoring
#   8. Catalog MCP servers (kong/catalog_mcp.py), once the AI Gateway answers
#
#   ./start.sh [--no-monitoring]
#
# Needs kong/auth0.env (copy kong/auth0.env.example and fill it in) and a
# Konnect PAT in ~/.kong/kpat (or $KONNECT_PAT_FILE).
set -e
cd "${0:A:h}"

CP_NAME=django-apigw
AI_GW_NAME=django-ai-gw
GW_DP_NAME=django-apigw-dp
GW_IMAGE=kong/kong-gateway:3.16
KONNECT_API=https://us.api.konghq.com
PAT_FILE=${KONNECT_PAT_FILE:-$HOME/.kong/kpat}
APIKEY=test   # key-auth credential of consumer user1 in kong/kong.yaml

monitoring=1
[[ $1 == --no-monitoring ]] && monitoring=0

step() { print -P "\n%B==> $*%b"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# --- 0. prerequisites ---------------------------------------------------------
for cmd in curl jq docker openssl deck kongctl; do
  command -v $cmd >/dev/null || die "missing command: $cmd"
done
docker info >/dev/null 2>&1 || die "docker daemon is not running"
[[ -r $PAT_FILE ]] || die "Konnect PAT not readable: $PAT_FILE"
PAT=$(<$PAT_FILE)
[[ -r kong/auth0.env ]] ||
  die "kong/auth0.env missing: cp kong/auth0.env.example kong/auth0.env and fill it in (README \"OIDC with Auth0\")"
source kong/auth0.env
grep -q REPLACE_WITH kong/auth0.env && die "kong/auth0.env still has REPLACE_WITH_... placeholders"

konnect() {  # konnect METHOD PATH [curl args...]
  local method=$1 url_path=$2; shift 2
  curl -sSf -X $method -H "Authorization: Bearer $PAT" "$@" "$KONNECT_API$url_path"
}

# --- 1. certificates ----------------------------------------------------------
step "Certificates"
if [[ -f kong/tls/server.crt ]]; then
  echo "reuse kong/tls/ (private CA + Kong GW server cert)"
else
  ./kong/gen-tls.sh
fi

dp_cert() {  # dp_cert DIR CN: pinned client cert for a Konnect data plane
  if [[ -f $1/tls.crt ]]; then
    echo "reuse $1/tls.crt"
    return
  fi
  mkdir -p $1
  openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout $1/tls.key -out $1/tls.crt -days 3650 -subj "/CN=$2" 2>/dev/null
  echo "generated $1/tls.crt"
}
dp_cert kong/gw-certs $GW_DP_NAME
dp_cert kong/ai-certs $AI_GW_NAME
# both DP images run as non-root and bind-mount these dirs
chmod 644 kong/gw-certs/tls.key kong/ai-certs/tls.key

# --- 2. Django ----------------------------------------------------------------
step "Django (docker compose)"
docker compose up --build -d

# --- 3. Konnect ---------------------------------------------------------------
step "Konnect: control plane $CP_NAME + AI Gateway $AI_GW_NAME"
kongctl apply -f kong/konnect.yaml --pat "$PAT" --auto-approve ||
  die "kongctl apply failed. If $CP_NAME / $AI_GW_NAME already exist but weren't created by kongctl, run ./cleanup.sh first."

step "Kong Gateway config (decK sync kong/kong.yaml)"
export DECK_GW_TLS_CERT="$(awk '{printf "%s\\n",$0}' kong/tls/server.crt)"
export DECK_GW_TLS_KEY="$(awk '{printf "%s\\n",$0}' kong/tls/server.key)"
deck gateway sync kong/kong.yaml --konnect-token-file $PAT_FILE \
  --konnect-control-plane-name $CP_NAME

if [[ -x .venv/bin/python ]]; then
  .venv/bin/python kong/gen_mcp_tools.py --check ||
    echo "WARN: generated files are stale; run .venv/bin/python kong/gen_mcp_tools.py" >&2
fi
step "API Catalog + Dev Portal (kongctl apply kong/portal.yaml)"
# after decK: the API implementation links to the django-api Gateway Service
kongctl apply -f kong/portal.yaml --pat "$PAT" --auto-approve

# --- 4. Kong Gateway data plane -----------------------------------------------
step "Kong Gateway data plane ($GW_DP_NAME)"
cp_json=$(konnect GET /v2/control-planes -G --data-urlencode "filter[name][eq]=$CP_NAME" | jq -c '.data[0]')
cp_host=$(jq -r '.config.control_plane_endpoint' <<<"$cp_json"); cp_host=${cp_host#https://}
tp_host=$(jq -r '.config.telemetry_endpoint' <<<"$cp_json"); tp_host=${tp_host#https://}
[[ -n $cp_host && $cp_host != null ]] || die "control plane $CP_NAME has no endpoint"

docker rm -f $GW_DP_NAME >/dev/null 2>&1 || true
# On kong-net so it reaches http://django:3333; alias kong-dp is what
# Prometheus scrapes (monitoring/prometheus/prometheus.yml).
docker run -d --name $GW_DP_NAME \
  --network kong-net --network-alias kong-dp \
  -v "$PWD/kong/gw-certs:/etc/kong/certs:ro" \
  -e "KONG_ROLE=data_plane" \
  -e "KONG_DATABASE=off" \
  -e "KONG_VITALS=off" \
  -e "KONG_ROUTER_FLAVOR=expressions" \
  -e "KONG_KONNECT_MODE=on" \
  -e "KONG_CLUSTER_MTLS=pki" \
  -e "KONG_CLUSTER_CONTROL_PLANE=$cp_host:443" \
  -e "KONG_CLUSTER_SERVER_NAME=$cp_host" \
  -e "KONG_CLUSTER_TELEMETRY_ENDPOINT=$tp_host:443" \
  -e "KONG_CLUSTER_TELEMETRY_SERVER_NAME=$tp_host" \
  -e "KONG_CLUSTER_CERT=/etc/kong/certs/tls.crt" \
  -e "KONG_CLUSTER_CERT_KEY=/etc/kong/certs/tls.key" \
  -e "KONG_LUA_SSL_TRUSTED_CERTIFICATE=system" \
  -p 8000:8000 \
  -p 8443:8443 \
  $GW_IMAGE >/dev/null
echo "started $GW_DP_NAME ($GW_IMAGE) -> $cp_host"

# --- 5. MCP server + AI Gateway data plane --------------------------------------
# MCP user keys + metering policy first: the MCP servers name its auth strategy
step "MCP users and metering policy (kongctl apply kong/ai-gateway-billing.yaml)"
[[ -f kong/mcp-users.env ]] || for u in ALICE BOB CAROL; do
  echo "MCP_KEY_$u=mcp-${u:l}-$(openssl rand -hex 12)"
done > kong/mcp-users.env && grep -q '^MCP_KEY_USER1=' kong/mcp-users.env || echo "MCP_KEY_USER1=$APIKEY" >> kong/mcp-users.env
(set -a; source kong/mcp-users.env; METERING_API_TOKEN=$PAT \
  kongctl apply -f kong/ai-gateway-billing.yaml --pat "$PAT" --auto-approve)

step "MCP servers (kongctl apply kong/ai-gateway.yaml)"
kongctl apply -f kong/ai-gateway.yaml --pat "$PAT" --auto-approve

step "MCP billing catalog (kong/mcp_billing.py)"
.venv/bin/python kong/mcp_billing.py

step "AI Gateway data plane ($AI_GW_NAME)"
./start_ai_dp.sh

# --- 6. monitoring --------------------------------------------------------------
if (( monitoring )); then
  step "Monitoring (Prometheus, Loki, Alloy, Grafana)"
  docker compose -f monitoring/docker-compose.yml up -d
fi

# --- 7. wait until traffic flows end to end -------------------------------------
wait_for() {  # wait_for LABEL CMD...: retry for up to 2 minutes until CMD prints 200
  local code
  for i in {1..40}; do
    code=$("${@:2}" 2>/dev/null) || true
    [[ $code == 200 ]] && { echo "ok   $1"; return 0; }
    sleep 3
  done
  echo "FAIL $1 (last HTTP status: ${code:-none})" >&2
  return 1
}
step "Waiting for config to reach the data planes"
ok=1
wait_for "Kong GW  https://localhost:8443/mfg/items/" \
  curl -sk -o /dev/null -w '%{http_code}' -H "apikey: $APIKEY" https://localhost:8443/mfg/items/ || ok=0
wait_for "AI GW    https://localhost:11443/mcp/mfg/items (MCP initialize)" \
  curl -sk -o /dev/null -w '%{http_code}' -X POST https://localhost:11443/mcp/mfg/items \
    -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
    -H "apikey: $APIKEY" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"start.sh","version":"1.0.0"}}}' || ok=0

# --- 8. Catalog MCP servers (reads each server's live tools/list) -------------
if [[ -x .venv/bin/python ]] && (( ok )); then
  step "Catalog MCP servers (kong/catalog_mcp.py)"
  .venv/bin/python kong/catalog_mcp.py || ok=0
else
  echo "WARN: skipped kong/catalog_mcp.py (needs .venv and a running AI Gateway)" >&2
fi
portal_host=$(konnect GET /v3/portals | jq -r '.data[] | select(.name == "manufacturing-portal") | .default_domain')

cat <<EOF

$( (( ok )) && echo "Demo is up." || echo "Started, but a check failed: see docker logs $GW_DP_NAME / $AI_GW_NAME." )
  REST (apikey)   curl -k https://localhost:8443/mfg/items/ -H "apikey: $APIKEY"
  REST (OIDC)     https://localhost:8443/oidc/mfg/   (browser, Auth0 login)
  Web UI          https://localhost:8443/items/
  MCP             https://localhost:11443/mcp/mfg/<resource>  (header apikey: $APIKEY)
                  resources: items item-components suppliers customers purchase-orders
                             orders shipments shipping-statuses shipping-schedule
  Dev Portal      https://$portal_host   (sign up at /register)
EOF
(( monitoring )) && echo "  Grafana         http://localhost:3000"
echo "Tear down with ./cleanup.sh"
