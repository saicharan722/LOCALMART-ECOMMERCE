from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="catalogproduct",
            name="stock_tracked",
            field=models.BooleanField(default=True),
        ),
    ]
