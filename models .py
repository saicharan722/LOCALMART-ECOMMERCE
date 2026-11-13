from django.db import models


class Order(models.Model):
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_id = models.CharField(max_length=200, blank=True, null=True)
    payment_status = models.CharField(max_length=50, default="Pending")
    order_status = models.CharField(max_length=50, default="Placed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order #{self.id} - {self.customer_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    image = models.URLField(blank=True)

    def __str__(self):
        return self.name