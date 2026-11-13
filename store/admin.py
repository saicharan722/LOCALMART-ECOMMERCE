from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm

from .models import CancellationRequest, Order, OrderItem, Refund
from .refunds import (
    CancellationWorkflowError,
    approve_order_cancellation,
    complete_manual_refund,
    process_refund,
    refresh_refund_status,
    reject_order_cancellation,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class CancellationReviewActionForm(ActionForm):
    review_note = forms.CharField(
        label="Admin review remarks",
        help_text="Required for approval or rejection; visible to the customer.",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "cols": 48}),
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_name", "restaurant_name", "merchant_profile", "payment_status", "order_status", "created_at")
    list_filter = ("payment_status", "order_status")
    search_fields = ("customer_name", "customer_email", "restaurant_name", "id")
    readonly_fields = (
        "created_at",
        "total_amount",
        "payment_status",
        "order_status",
        "payment_id",
        "razorpay_order_id",
        "payment_method",
        "payment_currency",
        "payment_amount",
        "payment_capture_id",
    )
    inlines = (OrderItemInline,)


@admin.action(
    description="Approve cancellation requests and process refunds",
    permissions=["change"],
)
def approve_cancellations(modeladmin, request, queryset):
    approved = 0
    errors = []
    review_note = request.POST.get("review_note", "")
    for cancellation in queryset.order_by("pk"):
        try:
            approve_order_cancellation(cancellation.pk, request.user, review_note)
            approved += 1
        except CancellationWorkflowError as error:
            errors.append(f"Order #{cancellation.order_id}: {error}")
    if approved:
        modeladmin.message_user(
            request,
            f"{approved} cancellation request(s) approved.",
            level=messages.SUCCESS,
        )
    if errors:
        modeladmin.message_user(
            request,
            " ".join(errors),
            level=messages.WARNING,
        )


@admin.action(
    description="Reject selected cancellation requests",
    permissions=["change"],
)
def reject_cancellations(modeladmin, request, queryset):
    rejected = 0
    errors = []
    review_note = request.POST.get("review_note", "")
    for cancellation in queryset.order_by("pk"):
        try:
            reject_order_cancellation(cancellation.pk, request.user, review_note)
            rejected += 1
        except CancellationWorkflowError as error:
            errors.append(f"Order #{cancellation.order_id}: {error}")
    if rejected:
        modeladmin.message_user(
            request,
            f"{rejected} cancellation request(s) rejected.",
            level=messages.SUCCESS,
        )
    if errors:
        modeladmin.message_user(
            request,
            " ".join(errors),
            level=messages.WARNING,
        )


@admin.register(CancellationRequest)
class CancellationRequestAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer_user", "reason", "status", "created_at", "reviewed_at")
    list_filter = ("status", "reason", "created_at")
    search_fields = ("order__id", "order__customer_name", "order__customer_email")
    readonly_fields = (
        "order",
        "customer_user",
        "reason",
        "reason_details",
        "status",
        "review_note",
        "reviewed_by",
        "reviewed_at",
        "created_at",
        "updated_at",
    )
    actions = (approve_cancellations, reject_cancellations)
    action_form = CancellationReviewActionForm

    @admin.display(description="Order", ordering="order_id")
    def order_number(self, cancellation):
        return f"ORD-{cancellation.order_id}"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.action(description="Retry failed online refunds", permissions=["change"])
def retry_failed_refunds(modeladmin, request, queryset):
    processed = 0
    errors = []
    for refund in queryset.filter(status="failed", payment_method__in=["razorpay", "paypal"]):
        result = process_refund(refund.pk, retry=True)
        if result.status == "failed":
            errors.append(f"Refund #{refund.pk}: {result.failure_reason}")
        else:
            processed += 1
    if processed:
        modeladmin.message_user(
            request,
            f"Retry started for {processed} online refund(s).",
            level=messages.SUCCESS,
        )
    if errors:
        modeladmin.message_user(request, " ".join(errors), level=messages.WARNING)


@admin.action(
    description="Refresh refund status from payment provider",
    permissions=["change"],
)
def refresh_refunds(modeladmin, request, queryset):
    refreshed = 0
    errors = []
    for refund in queryset.filter(payment_method__in=["razorpay", "paypal"]):
        try:
            refresh_refund_status(refund.pk)
            refreshed += 1
        except CancellationWorkflowError as error:
            errors.append(f"Refund #{refund.pk}: {error}")
    if refreshed:
        modeladmin.message_user(
            request,
            f"Refreshed {refreshed} refund status(es).",
            level=messages.SUCCESS,
        )
    if errors:
        modeladmin.message_user(request, " ".join(errors), level=messages.WARNING)


@admin.action(
    description="Mark completed manual refunds as completed",
    permissions=["change"],
)
def complete_manual_refunds(modeladmin, request, queryset):
    completed = 0
    errors = []
    for refund in queryset.filter(payment_method__in=["offline", "unknown"]):
        try:
            complete_manual_refund(refund.pk, request.user)
            completed += 1
        except CancellationWorkflowError as error:
            errors.append(f"Refund #{refund.pk}: {error}")
    if completed:
        modeladmin.message_user(
            request,
            f"Marked {completed} manual refund(s) completed.",
            level=messages.SUCCESS,
        )
    if errors:
        modeladmin.message_user(request, " ".join(errors), level=messages.WARNING)


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("order_number", "payment_method", "amount", "currency", "status", "gateway_refund_id", "created_at")
    list_filter = ("status", "payment_method", "created_at")
    search_fields = ("cancellation_request__order__id", "gateway_refund_id")
    readonly_fields = (
        "cancellation_request",
        "payment_method",
        "amount",
        "currency",
        "status",
        "gateway_refund_id",
        "idempotency_key",
        "failure_reason",
        "completed_by",
        "initiated_at",
        "completed_at",
        "created_at",
        "updated_at",
    )
    actions = (retry_failed_refunds, refresh_refunds, complete_manual_refunds)

    @admin.display(description="Order")
    def order_number(self, refund):
        return f"ORD-{refund.cancellation_request.order_id}"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
