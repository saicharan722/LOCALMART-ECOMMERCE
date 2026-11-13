import django.contrib.contenttypes.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Cart",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, max_length=40, null=True, unique=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="shopping_cart", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="CatalogProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("catalog_key", models.CharField(max_length=160, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("category", models.CharField(max_length=120)),
                ("merchant_name", models.CharField(blank=True, max_length=180)),
                ("price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("stock", models.PositiveIntegerField(default=0)),
                ("image", models.URLField(blank=True, max_length=1000)),
                ("is_active", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="CartItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveIntegerField()),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("cart", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="cart.cart")),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype")),
            ],
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(fields=("cart", "content_type", "object_id"), name="unique_cart_product"),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.CheckConstraint(condition=models.Q(("quantity__gte", 1)), name="cart_item_quantity_positive"),
        ),
    ]
