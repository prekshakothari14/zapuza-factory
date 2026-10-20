"""Signal handlers that write immutable AuditLog rows for tracked models."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.db.models.fields.files import FieldFile
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .context import get_audit_ip, get_audit_user


def _tracked_model_labels():
    try:
        cfg = apps.get_app_config("audit")
        return set(cfg.TRACKED_MODELS)
    except LookupError:
        return set()


def _model_label(instance):
    return f"{instance._meta.app_label}.{instance._meta.object_name}"


def _is_tracked(instance):
    label = _model_label(instance)
    # Never log AuditLog itself
    if label == "audit.AuditLog":
        return False
    return label in _tracked_model_labels()


def _json_safe(value):
    """Convert field values to JSON-serialisable types."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, FieldFile):
        return value.name if value else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    # FK / related objects → primary key
    if hasattr(value, "pk") and not isinstance(value, (str, int, float, bool)):
        return value.pk
    try:
        # Ensure the value is JSON-serialisable by attempting a no-op
        import json
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _instance_dict(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name == "id" and field.primary_key:
            continue
        # Use attname for FKs (stores the raw id)
        name = field.attname
        raw = getattr(instance, name, None)
        data[field.name] = _json_safe(raw)
    return data


def _actor():
    user = get_audit_user()
    ip = get_audit_ip()
    if user is not None and getattr(user, "is_authenticated", False):
        return user, user.get_username(), ip
    return None, "system", ip


@receiver(pre_save)
def audit_pre_save(sender, instance, **kwargs):
    if not _is_tracked(instance):
        return
    if instance.pk:
        try:
            old = sender.objects.filter(pk=instance.pk).first()
        except Exception:
            old = None
        if old is not None:
            instance._audit_old_values = _instance_dict(old)
        else:
            instance._audit_old_values = None
    else:
        instance._audit_old_values = None


@receiver(post_save)
def audit_post_save(sender, instance, created, **kwargs):
    if not _is_tracked(instance):
        return

    from .models import AuditLog  # local import to avoid circularity

    new_values = _instance_dict(instance)
    user, username, ip = _actor()

    if created:
        AuditLog(
            user=user,
            username=username or "system",
            action=AuditLog.Action.CREATE,
            model_name=_model_label(instance),
            object_id=str(instance.pk),
            object_repr=str(instance)[:255],
            old_values=None,
            new_values=new_values,
            changed_fields=list(new_values.keys()),
            ip_address=ip,
        ).save()
        return

    old_values = getattr(instance, "_audit_old_values", None) or {}
    changed = {}
    old_changed = {}
    for key, new_val in new_values.items():
        old_val = old_values.get(key)
        if old_val != new_val:
            changed[key] = new_val
            old_changed[key] = old_val

    if not changed:
        return  # nothing changed — skip

    AuditLog(
        user=user,
        username=username or "system",
        action=AuditLog.Action.UPDATE,
        model_name=_model_label(instance),
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        old_values=old_changed,
        new_values=changed,
        changed_fields=list(changed.keys()),
        ip_address=ip,
    ).save()


@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    if not _is_tracked(instance):
        return

    from .models import AuditLog

    user, username, ip = _actor()
    old_values = _instance_dict(instance)
    AuditLog(
        user=user,
        username=username or "system",
        action=AuditLog.Action.DELETE,
        model_name=_model_label(instance),
        object_id=str(getattr(instance, "pk", "") or ""),
        object_repr=str(instance)[:255],
        old_values=old_values,
        new_values=None,
        changed_fields=list(old_values.keys()),
        ip_address=ip,
    ).save()
