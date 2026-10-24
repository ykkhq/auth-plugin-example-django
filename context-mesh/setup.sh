#!/bin/zsh
# Kong Context Mesh with a Code Mode MCP server for the manufacturing API.
# Run after ./start.sh (needs the Docker Kong Gateway on :8443 and kong/tls/ca.crt).
# Safe to re-run: existing cluster, Konnect objects and port-forward are reused.
#
#   1. minikube profile "context-mesh" (your current kubectl context is kept)
#   2. Kong Operator 2.3 (feature gate mcp-server) + Konnect control plane
#      "django-context-mesh" + 1 Kong 3.16 data plane      (context-mesh/k8s.yaml)
#   3. mfg-gateway: in-cluster TLS bridge to https://host.minikube.internal:8443/mfg
#      (context-mesh/mfg-gateway.yaml)
#   4. Context Mesh: source "manufacturing-api" (kong/openapi/manufacturing-api.yaml),
#      MCP server "manufacturing", deployed to django-context-mesh (basic mode)
#   5. port-forward: http://localhost:18080/mcp/manufacturing
#   6. benchmark data: seed_benchmark (300 sales orders)
#
#   context-mesh/setup.sh       then   python3 context-mesh/compare_tokens.py
set -e
cd "${0:A:h}/.."

PROFILE=context-mesh
CP_NAME=django-context-mesh
SOURCE_NAME=manufacturing-api
MCP_NAME=manufacturing
UPSTREAM=http://mfg-gateway.default.svc/mfg
LOCAL_PORT=18080
KONNECT_API=https://us.api.konghq.com
PAT=$(tr -d '[:space:]' < ${KONNECT_PAT_FILE:-$HOME/.kong/kpat})

step() { print -P "\n%B==> $*%b"; }
die() { echo "ERROR: $*" >&2; exit 1; }
k() { kubectl --context $PROFILE -n default "$@"; }
retry() {  # retry CMD...: up to 2 minutes, for calls the operator's webhook may still refuse
  for i in {1..24}; do "$@" && return 0; echo "  retrying in 5s ($i/24)" >&2; sleep 5; done
  "$@"
}
konnect() {  # konnect METHOD PATH [curl args...]
  local method=$1 url_path=$2; shift 2
  curl -sS --fail-with-body -X $method -H "Authorization: Bearer $PAT" "$@" "$KONNECT_API$url_path"
}

for cmd in minikube kubectl helm jq curl docker; do
  command -v $cmd >/dev/null || die "missing command: $cmd"
done
[[ -f kong/tls/ca.crt ]] || die "kong/tls/ca.crt missing: run ./start.sh first"
[[ -x .venv/bin/python ]] || die ".venv missing (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"

# --- 1. cluster ---------------------------------------------------------------
step "minikube profile $PROFILE"
prev_ctx=$(kubectl config current-context 2>/dev/null || true)
if ! minikube status -p $PROFILE >/dev/null 2>&1; then
  minikube start -p $PROFILE --driver=docker --cpus=2 --memory=4096
  # minikube switches the current context; give the user theirs back
  [[ -n $prev_ctx && $prev_ctx != $PROFILE ]] && kubectl config use-context $prev_ctx >/dev/null
fi

# --- 2. Kong Operator, control plane, data plane ------------------------------
step "Kong Operator 2.3 + control plane $CP_NAME + data plane"
helm repo add kong https://charts.konghq.com >/dev/null 2>&1 || true
helm repo update kong >/dev/null
helm --kube-context $PROFILE upgrade --install kong-operator kong/kong-operator -n kong --create-namespace \
  --set image.tag=2.3 --set env.ENABLE_CONTROLLER_KONNECT=true --set env.FEATURE_GATES=mcp-server >/dev/null
kubectl --context $PROFILE -n kong wait --for=condition=Available=true --timeout=300s \
  deployment/kong-operator-kong-operator-controller-manager
# The Deployment turns Available a few seconds before its admission webhook
# (:5443) accepts connections, and every Secret/CR create goes through that
# webhook ("connection refused" on a fresh cluster), so retry the applies.
konnect_secret() {  # Kong Operator only reads Secrets labelled konghq.com/secret; no newline in the token
  k create secret generic konnect-pat --from-literal=token="$PAT" --dry-run=client -o yaml |
    kubectl --context $PROFILE label --local -f - konghq.com/credential=konnect konghq.com/secret=true -o yaml
}
retry eval 'konnect_secret | k apply -f - >/dev/null' ||
  die "Kong Operator webhook not reachable (kubectl --context $PROFILE -n kong logs deploy/kong-operator-kong-operator-controller-manager)"
retry k apply -f context-mesh/k8s.yaml
k wait --timeout=5m dataplane dataplane --for=condition=Ready

# --- 3. TLS bridge ------------------------------------------------------------
step "mfg-gateway (in-cluster TLS bridge to the Docker Kong Gateway)"
k create configmap mfg-gateway-ca --from-file=ca.crt=kong/tls/ca.crt --dry-run=client -o yaml | k apply -f - >/dev/null
k apply -f context-mesh/mfg-gateway.yaml
k rollout status deploy/mfg-gateway --timeout=180s

# --- 4. Context Mesh ----------------------------------------------------------
step "Context Mesh source $SOURCE_NAME + MCP server $MCP_NAME"
spec=$(.venv/bin/python -c "import yaml,json; print(json.dumps(yaml.safe_load(open('kong/openapi/manufacturing-api.yaml'))))")
source_body=$(jq -n --arg n $SOURCE_NAME --arg spec "$spec" --arg url $UPSTREAM '{
  name: $n, display_name: "Manufacturing Management API",
  description: "Manufacturing REST API through Kong Gateway /mfg (in-cluster TLS bridge)",
  labels: {}, type: "api",
  source: {type: "raw", config: {spec: $spec, base_url: $url}}}')
source_id=$(konnect GET /v1/context-sources | jq -r --arg n $SOURCE_NAME '.data[] | select(.name == $n) | .id')
if [[ -n $source_id ]]; then
  konnect PUT /v1/context-sources/$source_id --json "$source_body" >/dev/null  # keep the spec current
else
  source_id=$(konnect POST /v1/context-sources --json "$source_body" | jq -r .id)
fi

mcp_id=$(konnect GET /v1/context-interfaces | jq -r --arg n $MCP_NAME '.data[] | select(.name == $n) | .id')
[[ -n $mcp_id ]] || mcp_id=$(konnect POST /v1/context-interfaces --json "$(jq -n --arg n $MCP_NAME '{
  name: $n, display_name: "Manufacturing (Code Mode)",
  description: "Code Mode MCP server for the whole manufacturing API", labels: {}}')" | jq -r .id)

konnect GET /v1/context-interfaces/$mcp_id/context-source-mappings |
  jq -e --arg s $source_id '.data[] | select(.context_source_id == $s)' >/dev/null ||
  konnect POST /v1/context-interfaces/$mcp_id/context-source-mappings --json "{\"context_source_id\":\"$source_id\"}" >/dev/null

cp_id=$(konnect GET "/v2/control-planes?filter%5Bname%5D%5Beq%5D=$CP_NAME" | jq -r '.data[0].id')
konnect GET /v1/context-interfaces/$mcp_id/control-plane-mappings |
  jq -e --arg c $cp_id '.data[] | select(.control_plane_id == $c)' >/dev/null ||
  konnect POST /v1/context-interfaces/$mcp_id/control-plane-mappings --json "{\"control_plane_id\":\"$cp_id\",\"mode\":\"basic\"}" >/dev/null

echo "waiting for the mcpserver-* pod"
for i in {1..60}; do k get pods -o name | grep -q '^pod/mcpserver-' && break; sleep 5; done
k wait --for=condition=Ready --timeout=5m $(k get pods -o name | grep '^pod/mcpserver-')

# --- 5. port-forward ----------------------------------------------------------
step "port-forward localhost:$LOCAL_PORT -> data plane"
pkill -f "port-forward.*$LOCAL_PORT:80" 2>/dev/null || true
svc=$(k get svc -o name | grep '^service/dataplane-ingress-')
nohup kubectl --context $PROFILE -n default port-forward $svc $LOCAL_PORT:80 >/dev/null 2>&1 &
mcp_init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"setup.sh","version":"1"}}}'
for i in {1..30}; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:$LOCAL_PORT/mcp/$MCP_NAME \
    -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
    -H "X-Upstream-Api-Key: test" -d $mcp_init) || true
  [[ $code == 200 ]] && break
  sleep 3
done
[[ $code == 200 ]] || die "Code Mode MCP server not answering on localhost:$LOCAL_PORT (HTTP $code)"

# --- 6. benchmark data --------------------------------------------------------
step "benchmark data (seed_benchmark)"
docker compose exec -T django python manage.py seed_benchmark

cat <<EOF

Context Mesh is up.
  Code Mode MCP  http://localhost:$LOCAL_PORT/mcp/$MCP_NAME   (header X-Upstream-Api-Key: test)
                 tools: list_tools, search, get_schema, execute
  Claude Code    claude mcp add --transport http mfg-codemode http://localhost:$LOCAL_PORT/mcp/$MCP_NAME --header "X-Upstream-Api-Key: test"
  Compare        python3 context-mesh/compare_tokens.py
  Tear down      context-mesh/cleanup.sh
EOF
