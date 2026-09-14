from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Session auth without CSRF enforcement.

    Kong presents the Django ``sessionid`` cookie on every proxied request
    but never carries a matching CSRF cookie/token — there is no browser
    involved in the Kong<->Django hop, only in the Kong<->client hop, which
    Kong's own OIDC plugin already protects. Enforcing CSRF here would
    reject every state-changing request coming through the gateway.
    """

    def enforce_csrf(self, request):
        return


class CsrfExemptSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "inventory.authentication.CsrfExemptSessionAuthentication"
    name = "sessionAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": "Django session cookie obtained from POST /api/auth/login/.",
        }
