#!/bin/zsh
# Tears down the whole demo, local and Konnect:
#   - Kong GW / AI GW data-plane containers attached to the CPs below
#   - Konnect AI Gateway "django-ai-gw" (with its MCP servers, consumers,
#     auth strategy, policies, config store and vault) and Gateway control
#     plane "django-apigw"
#   - MCP billing catalog: customers mcp-alice/bob/carol (subscriptions
#     canceled), plan mfg_mcp_pay_per_request, feature mfg_mcp_requests
#     (kong/mcp_billing.py --delete; the shared meter api_requests_total stays)
#   - Analytics dashboard "MCP Cost Analytics (django-ai-gw)"
#   - Context Mesh (context-mesh/cleanup.sh), if context-mesh/setup.sh ran
#   - Dev Portal "manufacturing-portal" (with its developers), Catalog API
#     "manufacturing-api" and the Catalog MCP servers mfg-*-mcp
#   - monitoring + Django compose stacks (volumes, built image, kong-net)
#   - kong/tls/, kong/gw-certs/ and kong/ai-certs/ (private CA, server + DP client certs)
# Safe to re-run: anything already gone is skipped.
#   ./cleanup.sh [-y]     -y: don't ask for confirmation
cd "${0:A:h}"

CP_NAME=django-apigw
AI_GW_NAME=django-ai-gw
KONNECT_API=https://us.api.konghq.com
PAT_FILE=${KONNECT_PAT_FILE:-$HOME/.kong/kpat}

for cmd in curl jq docker; do
  command -v $cmd >/dev/null || { echo "missing: $cmd" >&2; exit 1; }
done
[[ -r $PAT_FILE ]] || { echo "Konnect PAT not readable: $PAT_FILE" >&2; exit 1; }
PAT=$(<$PAT_FILE)

konnect() {  # konnect METHOD PATH [curl args...]
  local method=$1 url_path=$2; shift 2
  curl -sS -X $method -H "Authorization: Bearer $PAT" "$@" "$KONNECT_API$url_path"
}

# --- 1. look up Konnect resources ------------------------------------------
cp_json=$(konnect GET /v2/control-planes -G --data-urlencode "filter[name][eq]=$CP_NAME" |
  jq -c '.data[0] // empty')
cp_id=$(jq -r '.id // empty' <<<"$cp_json")
cp_host=$(jq -r '.config.control_plane_endpoint // empty' <<<"$cp_json")
cp_host=${cp_host#https://}

ai_json=$(konnect GET /v1/ai-gateways | jq -c --arg n "$AI_GW_NAME" '.data[]? | select(.name == $n)')
ai_id=$(jq -r '.id // empty' <<<"$ai_json")
ai_host=$(jq -r '.endpoints.configuration // empty' <<<"$ai_json")
ai_host=${ai_host#https://}

portal_id=$(konnect GET /v3/portals | jq -r '.data[]? | select(.name == "manufacturing-portal") | .id')
api_id=$(konnect GET /v3/apis | jq -r '.data[]? | select(.slug == "manufacturing-api") | .id')
mcp_ids=($(konnect GET "/v1/mcp-servers?page%5Bsize%5D=100" |
  jq -r '.data[]? | select(.name | test("^mfg-.*-mcp$")) | .id'))
DASHBOARD_NAME="MCP Cost Analytics (django-ai-gw)"
dashboard_id=$(konnect GET "/v2/dashboards?page%5Bsize%5D=100" |
  jq -r --arg n "$DASHBOARD_NAME" '.data[]? | select(.name == $n) | .id')
billing=($(konnect GET "/v3/openmeter/customers?page_size=100" |
  jq -r '.data[]? | select(.key | test("^mcp-(alice|bob|carol)$")) | .key'))

# --- 2. find local DPs connected to those CPs --------------------------------
# DPs started by hand get random names, so match on KONG_CLUSTER_CONTROL_PLANE
# (Kong containers of other demos point at other CPs and are left alone).
dps=()
for c in $(docker ps -aq); do
  env_cp=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' $c |
    sed -n 's/^KONG_CLUSTER_CONTROL_PLANE=//p')
  env_cp=${env_cp%:*}
  [[ -n $env_cp && ( $env_cp == $cp_host || $env_cp == $ai_host ) ]] &&
    dps+=$(docker inspect -f '{{.Name}}' $c | tr -d /)
done
docker inspect django-ai-gw >/dev/null 2>&1 && (( ! ${dps[(Ie)django-ai-gw]} )) && dps+=django-ai-gw

echo "Will remove:"
echo "  Konnect Dev Portal : ${${portal_id:+manufacturing-portal ($portal_id)}:-<not found>}"
echo "  Konnect Catalog    : ${${api_id:+API manufacturing-api}:-<no API>}, ${#mcp_ids} MCP server(s) mfg-*-mcp"
echo "  Konnect AI Gateway : ${${ai_id:+$AI_GW_NAME ($ai_id)}:-<not found>}"
echo "  Konnect CP         : ${${cp_id:+$CP_NAME ($cp_id)}:-<not found>}"
echo "  Konnect billing    : customers ${billing:-<none>}, plan mfg_mcp_pay_per_request, feature mfg_mcp_requests"
echo "  Konnect dashboard  : ${${dashboard_id:+$DASHBOARD_NAME}:-<not found>}"
echo "  DP containers      : ${dps:-<none>}"
echo "  compose stacks     : monitoring/ and ./ (with volumes, built image, kong-net)"
echo "  local files        : kong/tls/ kong/gw-certs/ kong/ai-certs/"
if [[ $1 != -y ]]; then
  read -q "?Proceed? [y/N] " || { echo; exit 1; }
  echo
fi

# --- 3. Context Mesh (context-mesh/setup.sh) depends on everything below -------
if command -v minikube >/dev/null && minikube status -p context-mesh >/dev/null 2>&1; then
  context-mesh/cleanup.sh
fi

# --- 3b. stop DPs first so they stop reconnecting -----------------------------
(( $#dps )) && docker rm -f $dps >/dev/null && echo "removed DPs: $dps"

# --- 4. Konnect ---------------------------------------------------------------
delete() {  # delete LABEL PATH
  local code=$(konnect DELETE $2 -o /dev/null -w '%{http_code}')
  [[ $code == 2* ]] && echo "deleted $1" || echo "WARN: delete $1 -> HTTP $code" >&2
}
# portal first (force: it may have registered developers), then the API it publishes
[[ -n $portal_id ]] && delete "Dev Portal manufacturing-portal" "/v3/portals/$portal_id?force=true" || echo "skip: Dev Portal not found"
[[ -n $api_id ]] && delete "Catalog API manufacturing-api" /v3/apis/$api_id || echo "skip: Catalog API not found"
for id in $mcp_ids; do delete "Catalog MCP server $id" /v1/mcp-servers/$id; done
[[ -n $ai_id ]] && delete "AI Gateway $AI_GW_NAME" /v1/ai-gateways/$ai_id || echo "skip: AI Gateway $AI_GW_NAME not found"
[[ -n $cp_id ]] && delete "control plane $CP_NAME" /v2/control-planes/$cp_id || echo "skip: control plane $CP_NAME not found"
[[ -n $dashboard_id ]] && delete "dashboard $DASHBOARD_NAME" /v2/dashboards/$dashboard_id || echo "skip: dashboard not found"
# billing catalog: subscriptions, customers, plan, feature (stdlib python only)
py=.venv/bin/python; [[ -x $py ]] || py=python3
KONNECT_PAT_FILE=$PAT_FILE $py kong/mcp_billing.py --delete

# --- 5. compose stacks --------------------------------------------------------
docker compose -f monitoring/docker-compose.yml down -v
docker compose down -v --rmi local
docker network rm kong-net >/dev/null 2>&1 && echo "removed network kong-net"

# --- 6. local certs -----------------------------------------------------------
rm -rf kong/tls kong/gw-certs kong/ai-certs && echo "removed kong/tls kong/gw-certs kong/ai-certs"

cat <<'EOF'

Done. To set everything up again: ./start.sh
EOF
