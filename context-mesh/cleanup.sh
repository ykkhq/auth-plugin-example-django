#!/bin/zsh
# Removes everything context-mesh/setup.sh created: the Context Mesh MCP server
# and source in Konnect, the Konnect control plane "django-context-mesh" (via
# Kong Operator), the port-forward and the minikube profile "context-mesh".
# Benchmark orders (BENCH-*) stay in Django until ./cleanup.sh rebuilds it.
# Safe to re-run.
cd "${0:A:h}/.."

PROFILE=context-mesh
SOURCE_NAME=manufacturing-api
MCP_NAME=manufacturing
KONNECT_API=https://us.api.konghq.com
PAT=$(tr -d '[:space:]' < ${KONNECT_PAT_FILE:-$HOME/.kong/kpat})

konnect() {  # konnect METHOD PATH [curl args...]
  local method=$1 url_path=$2; shift 2
  curl -sS -X $method -H "Authorization: Bearer $PAT" "$@" "$KONNECT_API$url_path"
}
delete() {  # delete LABEL PATH
  local code=$(konnect DELETE $2 -o /dev/null -w '%{http_code}')
  [[ $code == 2* ]] && echo "deleted $1" || echo "WARN: delete $1 -> HTTP $code" >&2
}

pkill -f "port-forward.*18080:80" 2>/dev/null && echo "stopped port-forward"

# Konnect objects in reverse order: control-plane mappings, MCP server, source
mcp_id=$(konnect GET /v1/context-interfaces | jq -r --arg n $MCP_NAME '.data[]? | select(.name == $n) | .id')
if [[ -n $mcp_id ]]; then
  for m in $(konnect GET /v1/context-interfaces/$mcp_id/control-plane-mappings | jq -r '.data[]?.id'); do
    delete "control-plane mapping $m" /v1/context-interfaces/$mcp_id/control-plane-mappings/$m
  done
  delete "Context Mesh MCP server $MCP_NAME" /v1/context-interfaces/$mcp_id
fi
source_id=$(konnect GET /v1/context-sources | jq -r --arg n $SOURCE_NAME '.data[]? | select(.name == $n) | .id')
[[ -n $source_id ]] && delete "Context Mesh source $SOURCE_NAME" /v1/context-sources/$source_id

if minikube status -p $PROFILE >/dev/null 2>&1; then
  # deleting the KonnectGatewayControlPlane removes django-context-mesh in Konnect
  kubectl --context $PROFILE -n default delete -f context-mesh/mfg-gateway.yaml --ignore-not-found >/dev/null
  kubectl --context $PROFILE -n default delete -f context-mesh/k8s.yaml --ignore-not-found --wait=true --timeout=3m
  minikube delete -p $PROFILE
fi
echo "Context Mesh removed."
