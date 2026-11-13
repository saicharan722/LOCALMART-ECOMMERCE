from django.db import models
from django.utils.text import slugify


class ElectronicsCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    image = models.URLField(max_length=1000, blank=True, null=True)

    class Meta:
        verbose_name_plural = "Electronics Categories"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ElectronicsProduct(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    category = models.ForeignKey(
        ElectronicsCategory,
        on_delete=models.CASCADE,
        related_name="products"
    )

    brand = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    image = models.URLField(max_length=1000, blank=True, null=True)

    price = models.DecimalField(max_digits=12, decimal_places=2)

    discount_percentage = models.PositiveIntegerField(default=0)

    rating = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=0
    )

    reviews = models.PositiveIntegerField(default=0)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



    
    class Meta:
        ordering = ["-created_at"]

    @property
    def discounted_price(self):
        discount = (
            self.price *
            self.discount_percentage /
            100
        )

        return self.price - discount

    @property
    def in_stock(self):
        return self.stock > 0

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name