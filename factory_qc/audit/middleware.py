from .context import clear_audit_context, set_audit_context


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditContextMiddleware:
    """
    Stores the current request user and IP in contextvars so signal handlers
    can attribute audit log rows without using a process-wide global.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and not getattr(user, "is_authenticated", False):
            user = None
        set_audit_context(user=user, ip_address=_client_ip(request))
        try:
            return self.get_response(request)
        finally:
            clear_audit_context()
