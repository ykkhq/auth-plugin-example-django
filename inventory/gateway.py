from django.contrib.auth.middleware import PersistentRemoteUserMiddleware


class KongRemoteUserMiddleware(PersistentRemoteUserMiddleware):
    """Django's built-in remote-user login, reading the user Kong's
    openid-connect plugin forwards (the OIDC ``sub``) instead of the
    ``REMOTE_USER`` WSGI variable, which gunicorn can't set from a header.

    The header is only trustworthy because Django is reachable solely from
    Kong (private ``kong-net`` Docker network, no published port).
    """

    header = "HTTP_X_AUTHENTICATED_USER"
