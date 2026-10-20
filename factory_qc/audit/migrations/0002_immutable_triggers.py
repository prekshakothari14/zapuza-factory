"""
MySQL-level immutability for audit_auditlog.

Creates BEFORE UPDATE and BEFORE DELETE triggers that raise SQLSTATE 45000.
On SQLite (local demos) the operations are no-ops.
Requires the MySQL user to have TRIGGER privilege (see README).
"""
from django.db import migrations


TRIGGER_UPDATE = """
CREATE TRIGGER audit_auditlog_no_update
BEFORE UPDATE ON audit_auditlog
FOR EACH ROW
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit log is immutable';
"""

TRIGGER_DELETE = """
CREATE TRIGGER audit_auditlog_no_delete
BEFORE DELETE ON audit_auditlog
FOR EACH ROW
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit log is immutable';
"""

DROP_UPDATE = "DROP TRIGGER IF EXISTS audit_auditlog_no_update;"
DROP_DELETE = "DROP TRIGGER IF EXISTS audit_auditlog_no_delete;"


def create_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_UPDATE)
        cursor.execute(DROP_DELETE)
        cursor.execute(TRIGGER_UPDATE)
        cursor.execute(TRIGGER_DELETE)


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_UPDATE)
        cursor.execute(DROP_DELETE)


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_triggers, drop_triggers),
    ]
