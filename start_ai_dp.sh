#!/bin/zsh
# Kong AI Gateway 2.2 data plane for the Konnect AI Gateway "django-ai-gw".
# Client cert/key live in kong/ai-certs/ (gitignored, registered in Konnect).
# Trusts the private CA from kong/gen-tls.sh so the https call to the Kong
# Gateway (host.docker.internal:8443) passes upstream TLS verification.
# Endpoints are looked up in Konnect (they change every time the AI Gateway
# is recreated); set CP_HOST / TP_HOST to skip the lookup.
set -e
cd "${0:A:h}"

AI_GW_NAME=django-ai-gw
KONNECT_API=https://us.api.konghq.com
PAT_FILE=${KONNECT_PAT_FILE:-$HOME/.kong/kpat}

if [[ -z $CP_HOST ]]; then
  ai_json=$(curl -sSf -H "Authorization: Bearer $(<$PAT_FILE)" "$KONNECT_API/v1/ai-gateways" |
    jq -c --arg n "$AI_GW_NAME" '.data[]? | select(.name == $n)')
  CP_HOST=$(jq -r '.endpoints.configuration // empty' <<<"$ai_json")
  CP_HOST=${CP_HOST#https://}
  [[ -n $CP_HOST ]] || { echo "AI Gateway $AI_GW_NAME not found in Konnect (run ./start.sh)" >&2; exit 1; }
  TP_HOST=$(jq -r '.endpoints.telemetry // empty' <<<"$ai_json")
  TP_HOST=${TP_HOST#https://}
fi
# if Konnect doesn't report it: the configuration host with .cp. -> .tp.
TP_HOST=${TP_HOST:-${CP_HOST/.cp./.tp.}}

# distroless image runs as non-root; it must be able to read the key
chmod 644 kong/ai-certs/tls.key

docker rm -f django-ai-gw >/dev/null 2>&1 || true

docker run -d --name django-ai-gw \
--add-host host.docker.internal:host-gateway \
-v "$PWD/kong/ai-certs:/etc/kong/certs:ro" \
-v "$PWD/kong/tls/ca.crt:/etc/kong/ca/ca.crt:ro" \
-e "KONG_ROLE=data_plane" \
-e "KONG_DATABASE=off" \
-e "KONG_VITALS=off" \
-e "KONG_CLUSTER_MTLS=pki" \
-e "KONG_CLUSTER_CONTROL_PLANE=$CP_HOST:443" \
-e "KONG_CLUSTER_SERVER_NAME=$CP_HOST" \
-e "KONG_CLUSTER_TELEMETRY_ENDPOINT=$TP_HOST:443" \
-e "KONG_CLUSTER_TELEMETRY_SERVER_NAME=$TP_HOST" \
-e "KONG_CLUSTER_CERT=/etc/kong/certs/tls.crt" \
-e "KONG_CLUSTER_CERT_KEY=/etc/kong/certs/tls.key" \
-e "KONG_LUA_SSL_TRUSTED_CERTIFICATE=system,/etc/kong/ca/ca.crt" \
-e "KONG_KONNECT_MODE=on" \
-p 11000:8000 \
-p 11443:8443 \
kong/kong-ai-gateway:2.2.0-distroless >/dev/null
echo "started $AI_GW_NAME -> $CP_HOST"
