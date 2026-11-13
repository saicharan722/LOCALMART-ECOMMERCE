import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("store", "0005_alter_orderitem_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="product_content_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="product_object_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
