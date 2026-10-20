"""
Allow UPDATE on audit_auditlog only when the sole change is user_id -> NULL
(Django SET_NULL on user deletion). Every other UPDATE still raises SQLSTATE 45000.
"""
from django.db import migrations


TRIGGER_UPDATE = """
CREATE TRIGGER audit_auditlog_no_update
BEFORE UPDATE ON audit_auditlog
FOR EACH ROW
BEGIN
  IF NOT (
    OLD.user_id IS NOT NULL
    AND NEW.user_id IS NULL
    AND OLD.username <=> NEW.username
    AND OLD.timestamp <=> NEW.timestamp
    AND OLD.action <=> NEW.action
    AND OLD.model_name <=> NEW.model_name
    AND OLD.object_id <=> NEW.object_id
    AND OLD.object_repr <=> NEW.object_repr
    AND OLD.old_values <=> NEW.old_values
    AND OLD.new_values <=> NEW.new_values
    AND OLD.changed_fields <=> NEW.changed_fields
    AND OLD.ip_address <=> NEW.ip_address
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit log is immutable';
  END IF;
END
"""

DROP_UPDATE = "DROP TRIGGER IF EXISTS audit_auditlog_no_update;"


def create_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_UPDATE)
        cursor.execute(TRIGGER_UPDATE)


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    # Restore the strict trigger from 0002 on reverse
    strict = """
CREATE TRIGGER audit_auditlog_no_update
BEFORE UPDATE ON audit_auditlog
FOR EACH ROW
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit log is immutable';
"""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_UPDATE)
        cursor.execute(strict)


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0002_immutable_triggers"),
    ]

    operations = [
        migrations.RunPython(create_triggers, drop_triggers),
    ]
