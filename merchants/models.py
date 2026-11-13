from django.conf import settings
from django.db import models
from django.utils.text import slugify


class MerchantProfile(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="merchant_profile"
    )

    shop_name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_confirmed = models.BooleanField(default=False)
    logo = models.URLField(max_length=1000, blank=True)

    currency = models.CharField(
        max_length=3,
        default="INR"
    )

    payout_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    # Merchant approval workflow
    is_approved = models.BooleanField(
        default=False
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.shop_name)[:200] or "store"
            candidate = base_slug
            suffix = 2
            while MerchantProfile.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base_slug[:210]}-{suffix}"
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.shop_name


class MerchantCategory(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="categories"
    )

    name = models.CharField(
        max_length=120
    )

    class Meta:
        unique_together = ("merchant", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class MerchantProduct(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="products"
    )

    category = models.ForeignKey(
        MerchantCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products"
    )

    name = models.CharField(
        max_length=220
    )

    sku = models.CharField(
        max_length=80
    )

    description = models.TextField(
        blank=True
    )

    image = models.URLField(
        max_length=1000,
        blank=True
    )

    hsn_code = models.CharField(
        max_length=16,
        blank=True,
        default=""
    )

    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )

    tax_treatment = models.CharField(
        max_length=20,
        default="unclassified"
    )

    gst_verified = models.BooleanField(
        default=False
    )

    price_includes_gst = models.BooleanField(
        default=False
    )

    tax_classification = models.CharField(
        max_length=120,
        default="unclassified"
    )

    tax_effective_from = models.DateField(
        null=True,
        blank=True
    )

    tax_source_reference = models.CharField(
        max_length=1000,
        blank=True,
        default=""
    )

    place_of_supply_rule = models.CharField(
        max_length=24,
        default="unclassified"
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    compare_at_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    stock = models.PositiveIntegerField(
        default=0
    )

    low_stock_threshold = models.PositiveIntegerField(
        default=5
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "sku"],
                name="unique_merchant_product_sku"
            )
        ]

        ordering = ["-created_at"]

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    def __str__(self):
        return self.name


class MerchantProductVariant(models.Model):
    product = models.ForeignKey(
        MerchantProduct,
        on_delete=models.CASCADE,
        related_name="variants"
    )

    name = models.CharField(
        max_length=120
    )

    value = models.CharField(
        max_length=120
    )

    price_delta = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    stock = models.PositiveIntegerField(
        default=0
    )


class MerchantOrder(models.Model):
    STATUS_CHOICES = [
        (value, value.title())
        for value in (
            "pending",
            "processing",
            "shipped",
            "delivered",
            "cancelled",
            "refunded"
        )
    ]

    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="orders"
    )

    order_number = models.CharField(
        max_length=40
    )

    customer_name = models.CharField(
        max_length=180
    )

    customer_email = models.EmailField()

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    payment_status = models.CharField(
        max_length=30,
        default="pending"
    )

    shipping_tracking = models.CharField(
        max_length=120,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["-created_at"]


class MerchantOrderItem(models.Model):
    order = models.ForeignKey(
        MerchantOrder,
        on_delete=models.CASCADE,
        related_name="items"
    )

    product = models.ForeignKey(
        MerchantProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    name = models.CharField(
        max_length=220
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    quantity = models.PositiveIntegerField(
        default=1
    )


class MerchantCoupon(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="coupons"
    )

    code = models.CharField(
        max_length=40
    )

    percentage = models.PositiveIntegerField(
        default=0
    )

    fixed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    active = models.BooleanField(
        default=True
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        unique_together = ("merchant", "code")


class MerchantPayout(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="payouts"
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    reference = models.CharField(
        max_length=120,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )


class MerchantReview(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="reviews"
    )

    product = models.ForeignKey(
        MerchantProduct,
        on_delete=models.CASCADE,
        related_name="reviews"
    )

    customer_name = models.CharField(
        max_length=180
    )

    rating = models.PositiveSmallIntegerField(
        default=5
    )

    comment = models.TextField(
        blank=True
    )

    reply = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )


class MerchantSupportTicket(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("pending", "Pending"),
        ("closed", "Closed"),
    ]

    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="tickets"
    )

    subject = models.CharField(
        max_length=220
    )

    description = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="open"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )


class MerchantNotification(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="notifications"
    )

    title = models.CharField(
        max_length=180
    )

    message = models.TextField()

    is_read = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )


class MerchantActivity(models.Model):
    merchant = models.ForeignKey(
        MerchantProfile,
        on_delete=models.CASCADE,
        related_name="activities"
    )

    message = models.CharField(
        max_length=240
    )

    kind = models.CharField(
        max_length=40,
        default="general"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )
