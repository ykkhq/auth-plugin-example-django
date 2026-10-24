from urllib.parse import unquote

from django.contrib.auth.middleware import PersistentRemoteUserMiddleware
from django.urls import get_script_prefix, set_script_prefix

API_ROOT = "/api"
DEFAULT_PORTS = {"http": "80", "https": "443"}


class KongForwardedMiddleware:
    """Make Django build URLs as the client sees them through Kong.

    Kong proxies e.g. https://localhost:8443/oidc/mfg/orders to
    http://django:3333/api/orders: it strips the route path and prepends the
    service path (/api). Without this, DRF's API root links, the browsable
    API's breadcrumbs and APPEND_SLASH redirects point at django:3333 or
    /api/..., which have no Kong route.

    Host: Kong's X-Forwarded-Host carries no port, so the port from
    X-Forwarded-Port is added (settings.USE_X_FORWARDED_HOST and
    SECURE_PROXY_SSL_HEADER then do the rest).

    Path: when Kong stripped X-Forwarded-Prefix and prepended exactly /api
    (the django-api service), the request is served with the API urlconf
    mounted at the public prefix, so reverse(), request.path and redirects
    all yield /oidc/mfg/... . Other routes (/items, /inventory) are left as is.

    The X-Forwarded-* headers are only trustworthy because Django is reachable
    solely from Kong, which overwrites any client-sent copies.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        meta = request.META
        host = meta.get("HTTP_X_FORWARDED_HOST")
        port = meta.get("HTTP_X_FORWARDED_PORT")
        proto = meta.get("HTTP_X_FORWARDED_PROTO", "http")
        if host and port and ":" not in host and DEFAULT_PORTS.get(proto) != port:
            meta["HTTP_X_FORWARDED_HOST"] = f"{host}:{port}"

        prefix = meta.get("HTTP_X_FORWARDED_PREFIX", "").rstrip("/")
        original = unquote(meta.get("HTTP_X_FORWARDED_PATH", "").split("?", 1)[0])
        path = request.path_info
        if prefix and original.startswith(prefix) and (path == API_ROOT or path.startswith(API_ROOT + "/")):
            rest = original[len(prefix):]
            if path[len(API_ROOT):] == rest:
                request.path_info = rest or "/"
                request.path = prefix + request.path_info
                request.urlconf = "inventory.urls"
                # The script prefix is per thread; put it back so the next
                # request on this worker starts clean.
                saved = get_script_prefix()
                set_script_prefix(prefix + "/")
                try:
                    return self.get_response(request)
                finally:
                    set_script_prefix(saved)
        return self.get_response(request)


class KongRemoteUserMiddleware(PersistentRemoteUserMiddleware):
    """Django's built-in remote-user login, reading the user Kong's
    openid-connect plugin forwards (the OIDC ``sub``) instead of the
    ``REMOTE_USER`` WSGI variable, which gunicorn can't set from a header.

    The header is only trustworthy because Django is reachable solely from
    Kong (private ``kong-net`` Docker network, no published port).
    """

    header = "HTTP_X_AUTHENTICATED_USER"
