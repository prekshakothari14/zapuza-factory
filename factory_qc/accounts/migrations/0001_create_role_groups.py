from django.db import migrations

# Role groups. Superusers act as the "Plant Manager" and need no group.
ROLE_GROUPS = ["Quality Engineer", "Inspector", "Supervisor"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_GROUPS:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLE_GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(create_groups, remove_groups)]
