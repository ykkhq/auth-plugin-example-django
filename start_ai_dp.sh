#!/bin/zsh
# Kong AI Gateway 2.2 data plane for the Konnect AI Gateway "django-ai-gw".
# Client cert/key live in kong/ai-certs/ (gitignored, registered in Konnect).
# Trusts the private CA from kong/gen-tls.sh so the https call to the Kong
# Gateway (host.docker.internal:8443) passes upstream TLS verification.
cd "${0:A:h}"

CP_HOST=7a29d2c629.us.cp.konghq.com
TP_HOST=7a29d2c629.us.tp.konghq.com

# distroless image runs as non-root; it must be able to read the key
chmod 644 kong/ai-certs/tls.key

docker rm -f django-ai-gw >/dev/null 2>&1

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
kong/kong-ai-gateway:2.2.0-distroless
