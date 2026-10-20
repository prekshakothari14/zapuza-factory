"""Request-scoped audit context via contextvars (not process globals)."""
from contextvars import ContextVar
from typing import Optional

_audit_user: ContextVar[Optional[object]] = ContextVar("audit_user", default=None)
_audit_ip: ContextVar[Optional[str]] = ContextVar("audit_ip", default=None)


def set_audit_context(user=None, ip_address=None):
    _audit_user.set(user)
    _audit_ip.set(ip_address)


def clear_audit_context():
    _audit_user.set(None)
    _audit_ip.set(None)


def get_audit_user():
    return _audit_user.get()


def get_audit_ip():
    return _audit_ip.get()
