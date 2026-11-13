import uuid

from django.db import models
from django.db.models.functions import Lower
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from merchants.models import MerchantProfile


class MarketplaceCoupon(models.Model):
    MARKETPLACE_CATEGORIES = (
        ("Food", "Food"),
        ("Grocery", "Grocery"),
        ("Shopping", "Shopping"),
        ("Electronics", "Electronics"),
        ("Home Appliances", "Home Appliances"),
    )
    DISCOUNT_TYPES = [
        ("percentage", "Percentage"),
        ("fixed", "Fixed amount"),
    ]

    code = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=280)
    discount_type = models.CharField(max_length=12, choices=DISCOUNT_TYPES)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)
    minimum_order_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maximum_discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    eligible_categories = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="unique_marketplace_coupon_code_ci",
            ),
        ]

    def __str__(self):
        return self.code


class Order(models.Model):
    PAYMENT_METHOD_CHOICES = (
        ("unknown", "Unknown"),
        ("razorpay", "Razorpay"),
        ("paypal", "PayPal"),
        ("offline", "Offline"),
    )

    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="localmart_orders")
    cart = models.ForeignKey("cart.Cart", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    delivery_address = models.TextField(blank=True)
    customer_latitude = models.FloatField(null=True, blank=True)
    customer_longitude = models.FloatField(null=True, blank=True)
    delivery_latitude = models.FloatField(null=True, blank=True)
    delivery_longitude = models.FloatField(null=True, blank=True)
    delivery_location_confirmed = models.BooleanField(default=False)
    restaurant_name = models.CharField(max_length=180, blank=True)
    merchant_profile = models.ForeignKey(MerchantProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="localmart_orders")
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_taxable = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_cgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_sgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_igst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    coupon_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_state = models.CharField(max_length=80, blank=True, default="")
    supplier_state = models.CharField(max_length=80, blank=True, default="")
    coupon_code = models.CharField(max_length=40, blank=True, default="")
    invoice_number = models.CharField(max_length=40, blank=True, default="")
    supplier_address = models.TextField(blank=True, default="")
    supplier_gstin = models.CharField(max_length=15, blank=True, default="")
    supplier_legal_name = models.CharField(max_length=220, blank=True, default="")
    customer_gstin = models.CharField(max_length=15, blank=True, default="")

    payment_id = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )
    razorpay_order_id = models.CharField(max_length=200, blank=True, null=True, unique=True)
    payment_method = models.CharField(
        max_length=12,
        choices=PAYMENT_METHOD_CHOICES,
        default="unknown",
    )
    payment_currency = models.CharField(max_length=3, default="INR")
    payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_capture_id = models.CharField(max_length=200, blank=True, default="")

    payment_status = models.CharField(
        max_length=50,
        default="Pending"
    )

    order_status = models.CharField(
        max_length=50,
        default="Placed"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Order #{self.id} - {self.customer_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )

    name = models.CharField(max_length=500)

    category = models.CharField(
        max_length=100,
        blank=True
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    quantity = models.PositiveIntegerField(
        default=1
    )

    image = models.URLField(
        max_length=1000,
        blank=True
    )
    product_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    product_object_id = models.PositiveIntegerField(null=True, blank=True)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hsn_code = models.CharField(max_length=16, blank=True, default="")
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_deducted = models.BooleanField(default=False)
    tax_treatment = models.CharField(max_length=20, blank=True, default="")
    taxable_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    supplier_state = models.CharField(max_length=80, blank=True, default="")
    coupon_discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    catalog_source = models.CharField(max_length=30, blank=True, default="")
    cgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    delivery_charge_share = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    original_line_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_includes_gst = models.BooleanField(default=False)
    sgst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    source_product_id = models.CharField(max_length=180, blank=True, default="")
    tax_classification = models.CharField(max_length=120, blank=True, default="")
    tax_effective_from = models.DateField(null=True, blank=True)
    tax_source_reference = models.CharField(max_length=1000, blank=True, default="")
    place_of_supply_rule = models.CharField(max_length=24, blank=True, default="")
    place_of_supply_state = models.CharField(max_length=80, blank=True, default="")
    purchased_product = GenericForeignKey("product_content_type", "product_object_id")

    def __str__(self):
        return self.name


class CancellationRequest(models.Model):
    REASON_CHOICES = (
        ("changed_mind", "Changed my mind"),
        ("ordered_by_mistake", "Ordered by mistake"),
        ("delivery_delay", "Delivery is taking too long"),
        ("duplicate_order", "Duplicate order"),
        ("other", "Other"),
    )
    STATUS_CHOICES = (
        ("requested", "Pending review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="cancellation_requests",
    )
    customer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_cancellation_requests",
    )
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    reason_details = models.CharField(max_length=500, blank=True)
    previous_order_status = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="requested")
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_order_cancellations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status="requested"),
                name="unique_pending_cancellation_per_order",
            ),
        ]

    def __str__(self):
        return f"Cancellation request for order #{self.order_id}"


class Refund(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )

    cancellation_request = models.OneToOneField(
        CancellationRequest,
        on_delete=models.PROTECT,
        related_name="refund",
    )
    payment_method = models.CharField(
        max_length=12,
        choices=Order.PAYMENT_METHOD_CHOICES,
        default="unknown",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    gateway_refund_id = models.CharField(max_length=200, null=True, blank=True, unique=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    failure_reason = models.CharField(max_length=500, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="completed_localmart_refunds",
    )
    initiated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Refund for order #{self.cancellation_request.order_id}"
