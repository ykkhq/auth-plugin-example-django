#!/bin/zsh
# Private CA + Kong Gateway server cert, so the AI Gateway can call the
# Kong Gateway over verified https (AI GW -> https://host.docker.internal:8443).
#   kong/tls/ca.crt       trusted by the AI GW DP (start_ai_dp.sh)
#   kong/tls/server.crt   served by Kong GW for SNI host.docker.internal
#   kong/tls/server.key   (kong/kong.yaml via DECK_GW_TLS_CERT/DECK_GW_TLS_KEY)
# Output dir is gitignored. Re-run only to rotate.
set -e
cd "${0:A:h}"
mkdir -p tls && cd tls

openssl req -x509 -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
  -keyout ca.key -out ca.crt -days 3650 -subj "/CN=django-demo-local-ca" \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"

openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
  -keyout server.key -out server.csr -subj "/CN=host.docker.internal"

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 825 -extfile <(printf '%s\n' \
    "subjectAltName=DNS:host.docker.internal,DNS:localhost,IP:127.0.0.1" \
    "basicConstraints=CA:FALSE" "keyUsage=digitalSignature" "extendedKeyUsage=serverAuth")

rm -f server.csr ca.srl
# distroless AI GW image runs as non-root and bind-mounts this dir
chmod 644 ca.crt server.crt
echo "generated: $(pwd)/{ca.crt,server.crt,server.key}"
