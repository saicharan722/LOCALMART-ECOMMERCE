from django.db import models


# =========================================================
# CATEGORY MODEL
# =========================================================

class Category(models.Model):

    name = models.CharField(
        max_length=150,
        unique=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


# =========================================================
# PRODUCT MODEL
# =========================================================

class Product(models.Model):

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="products"
    )

    name = models.CharField(
        max_length=255
    )

    brand = models.CharField(
        max_length=150,
        blank=True,
        default=""
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    rating = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=0
    )

    discount = models.PositiveIntegerField(
        default=0
    )

    stock = models.PositiveIntegerField(
        default=0
    )

    image = models.URLField(
        max_length=1000,
        blank=True,
        default=""
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Product"
        verbose_name_plural = "Products"

    def __str__(self):
        return self.name

