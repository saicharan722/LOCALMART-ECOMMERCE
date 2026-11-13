from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shopping_cart",
    )
    session_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
    coupon_code = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user or self.session_key}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    product = GenericForeignKey("content_type", "object_id")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "content_type", "object_id"],
                name="unique_cart_product",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="cart_item_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.product} x {self.quantity}"


class CatalogProduct(models.Model):
    """Database-backed inventory record for catalogs currently stored in frontend data."""

    catalog_key = models.CharField(max_length=160, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=120)
    merchant_name = models.CharField(max_length=180, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    stock_tracked = models.BooleanField(default=True)
    image = models.URLField(max_length=1000, blank=True)
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
