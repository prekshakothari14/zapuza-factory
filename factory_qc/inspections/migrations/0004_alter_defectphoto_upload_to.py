from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inspections", "0003_alter_checklist_status_add_statuses"),
    ]

    operations = [
        migrations.AlterField(
            model_name="defectphoto",
            name="image",
            field=models.ImageField(upload_to="defects/%Y/%m/"),
        ),
    ]
