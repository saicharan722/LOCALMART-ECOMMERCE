import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cart", "0001_initial"),
        ("store", "0006_orderitem_product_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="cart",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="orders",
                to="cart.cart",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="razorpay_order_id",
            field=models.CharField(blank=True, max_length=200, null=True, unique=True),
        ),
    ]
