import logging
from decimal import Decimal, ROUND_HALF_UP

import razorpay
import requests
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import CancellationRequest, Order, Refund


logger = logging.getLogger(__name__)

CANCELLABLE_ORDER_STATUSES = frozenset({
    "placed",
    "confirmed",
    "processing",
    "stock review",
    "restaurant preparing",
    "store preparing",
    "delivery partner assigned",
    "partner reached restaurant",
    "partner reached store",
})


class CancellationWorkflowError(ValueError):
    pass


def _validate_reviewer(reviewer, permission_codename):
    has_permission = getattr(reviewer, "has_perm", None)
    if not (
        getattr(reviewer, "is_authenticated", False)
        and getattr(reviewer, "is_active", False)
        and getattr(reviewer, "is_staff", False)
        and has_permission
        and has_permission(permission_codename)
    ):
        raise CancellationWorkflowError(
            "You do not have permission to review this cancellation or refund request."
        )


def order_can_be_cancelled(order, status=None):
    return (status or order.order_status).strip().casefold() in CANCELLABLE_ORDER_STATUSES


def _order_belongs_to_user(order, user):
    if order.customer_user_id:
        return order.customer_user_id == user.pk
    return bool(
        user.is_authenticated
        and user.email
        and order.customer_email.casefold() == user.email.casefold()
    )


def _send_customer_email(order, subject, body):
    if not order.customer_email:
        logger.warning("Cannot send order notification for order %s without an email address.", order.pk)
        return
    try:
        sent = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [order.customer_email],
            fail_silently=False,
        )
        if sent != 1:
            logger.error("Order notification email was not accepted for order %s.", order.pk)
    except Exception as error:
        logger.error(
            "Order notification email failed for order %s (%s).",
            order.pk,
            type(error).__name__,
        )


def request_order_cancellation(order_id, user, reason, details=""):
    if not getattr(user, "is_authenticated", False):
        raise CancellationWorkflowError("Sign in before requesting an order cancellation.")
    valid_reasons = dict(CancellationRequest.REASON_CHOICES)
    if reason not in valid_reasons:
        raise CancellationWorkflowError("Choose a valid cancellation reason.")
    details = str(details or "").strip()
    if len(details) > 500:
        raise CancellationWorkflowError("Additional details must be 500 characters or fewer.")
    if reason == "other" and not details:
        raise CancellationWorkflowError("Add a short explanation for the selected reason.")

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if not _order_belongs_to_user(order, user):
            raise Order.DoesNotExist
        if not order_can_be_cancelled(order):
            raise CancellationWorkflowError(
                "This order can no longer be cancelled because it has progressed beyond the cancellation window."
            )
        if CancellationRequest.objects.filter(order=order, status="requested").exists():
            raise CancellationWorkflowError("A cancellation request is already awaiting review.")

        cancellation = CancellationRequest.objects.create(
            order=order,
            customer_user=user,
            reason=reason,
            reason_details=details,
            previous_order_status=order.order_status,
        )
        order.order_status = "Cancellation Requested"
        order.save(update_fields=["order_status"])

    _send_customer_email(
        order,
        f"Cancellation request received for order #{order.pk}",
        (
            f"We received your cancellation request for order #{order.pk}.\n\n"
            "The order is temporarily on hold while our team reviews the request. "
            "If approved, an eligible online payment will be refunded to its original payment method."
        ),
    )
    return cancellation


def reject_order_cancellation(cancellation_id, reviewer, review_note=""):
    _validate_reviewer(reviewer, "store.change_cancellationrequest")
    review_note = str(review_note or "").strip()
    if not review_note:
        raise CancellationWorkflowError("Add a review remark before rejecting this request.")
    if len(review_note) > 500:
        raise CancellationWorkflowError("Review notes must be 500 characters or fewer.")

    with transaction.atomic():
        order_id = CancellationRequest.objects.only("order_id").get(pk=cancellation_id).order_id
        order = Order.objects.select_for_update().get(pk=order_id)
        cancellation = (
            CancellationRequest.objects.select_for_update()
            .get(pk=cancellation_id)
        )
        if cancellation.status != "requested":
            raise CancellationWorkflowError("Only pending cancellation requests can be rejected.")
        cancellation.status = "rejected"
        cancellation.review_note = review_note
        cancellation.reviewed_by = reviewer
        cancellation.reviewed_at = timezone.now()
        cancellation.save(update_fields=[
            "status",
            "review_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ])
        if order.order_status.casefold() == "cancellation requested":
            order.order_status = cancellation.previous_order_status or "Confirmed"
            order.save(update_fields=["order_status"])

    _send_customer_email(
        cancellation.order,
        f"Cancellation request update for order #{cancellation.order_id}",
        (
            f"Your cancellation request for order #{cancellation.order_id} was not approved."
            + (f"\n\nReview note: {review_note}" if review_note else "")
        ),
    )
    return cancellation


def _payment_provider(order):
    method = (order.payment_method or "unknown").casefold()
    if method == "razorpay" or order.razorpay_order_id:
        return "razorpay"
    if method == "paypal":
        return "paypal"
    return method


def _payment_reference(order, provider):
    if order.payment_capture_id:
        return order.payment_capture_id
    if provider == "razorpay" and order.payment_id and order.payment_id != order.razorpay_order_id:
        return order.payment_id
    return ""


def _refund_amount(order, provider):
    if order.payment_amount and order.payment_amount > 0:
        return order.payment_amount, order.payment_currency or "INR"
    if provider == "paypal":
        amount = (
            order.total_amount * Decimal(str(settings.PAYPAL_INR_TO_USD))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return amount, settings.PAYPAL_CURRENCY
    return order.total_amount, order.payment_currency or "INR"


def create_refund_for_approved_cancellation(order_id):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.payment_status.casefold() != "paid":
            return None
        cancellation = (
            CancellationRequest.objects.select_for_update()
            .filter(order=order, status="approved")
            .order_by("-created_at")
            .first()
        )
        if cancellation is None:
            return None
        provider = _payment_provider(order)
        amount, currency = _refund_amount(order, provider)
        refund, created = Refund.objects.get_or_create(
            cancellation_request=cancellation,
            defaults={
                "payment_method": provider if provider in {"razorpay", "paypal", "offline"} else "unknown",
                "amount": amount,
                "currency": currency,
            },
        )

    if refund.payment_method in {"razorpay", "paypal"} and _payment_reference(order, refund.payment_method):
        refund = process_refund(refund.pk)
    elif created:
        refund.failure_reason = (
            "This payment requires manual refund review by LocalMart support."
        )
        refund.save(update_fields=["failure_reason", "updated_at"])
        transaction.on_commit(lambda: _email_refund_status(refund.pk))
    return refund


def _restore_inventory(order):
    for item in order.items.select_for_update().filter(stock_deducted=True):
        content_type = item.product_content_type
        model = content_type.model_class() if content_type else None
        if model is None or not item.product_object_id:
            logger.error("Could not identify inventory for cancelled order item %s.", item.pk)
            continue
        try:
            model._meta.get_field("stock")
        except FieldDoesNotExist:
            logger.error("No stock field is available for cancelled order item %s.", item.pk)
            continue
        product = model.objects.select_for_update().filter(pk=item.product_object_id).first()
        if product is None or product.stock is None:
            logger.error("Could not restore stock for cancelled order item %s.", item.pk)
            continue
        model.objects.filter(pk=product.pk).update(stock=F("stock") + item.quantity)
        item.stock_deducted = False
        item.save(update_fields=["stock_deducted"])


def _cancel_tracking(order):
    from tracking.models import DeliveryPartner, OrderDelivery, TrackingSession
    from tracking.services import create_partner_notification, publish_tracking_update

    session = (
        TrackingSession.objects.select_for_update()
        .filter(order=order)
        .first()
    )
    if session is None or session.status in {"delivered", "cancelled"}:
        return

    session.status = "cancelled"
    session.save(update_fields=["status", "updated_at"])
    delivery, _ = OrderDelivery.objects.get_or_create(tracking=session)
    delivery.status = "cancelled"
    delivery.save(update_fields=["status"])
    if session.partner_id:
        create_partner_notification(session, session.partner, "cancelled")
        another_active_delivery = (
            TrackingSession.objects.filter(partner_id=session.partner_id)
            .exclude(pk=session.pk)
            .exclude(status__in=["delivered", "cancelled"])
            .exists()
        )
        if not another_active_delivery:
            DeliveryPartner.objects.filter(pk=session.partner_id).update(is_available=True)
    publish_tracking_update(session)


def approve_order_cancellation(cancellation_id, reviewer, review_note=""):
    _validate_reviewer(reviewer, "store.change_cancellationrequest")
    review_note = str(review_note or "").strip()
    if not review_note:
        raise CancellationWorkflowError("Add a review remark before approving this request.")
    if len(review_note) > 500:
        raise CancellationWorkflowError("Review notes must be 500 characters or fewer.")

    refund_id = None
    with transaction.atomic():
        order_id = CancellationRequest.objects.only("order_id").get(pk=cancellation_id).order_id
        order = Order.objects.select_for_update().get(pk=order_id)
        cancellation = (
            CancellationRequest.objects.select_for_update()
            .get(pk=cancellation_id)
        )
        if cancellation.status != "requested":
            if cancellation.status == "approved":
                return getattr(cancellation, "refund", None)
            raise CancellationWorkflowError("Only pending cancellation requests can be approved.")

        effective_status = (
            cancellation.previous_order_status
            if order.order_status.casefold() == "cancellation requested"
            else order.order_status
        )
        if not order_can_be_cancelled(order, effective_status):
            raise CancellationWorkflowError(
                "This order is no longer eligible for cancellation because its status has changed."
            )

        cancellation.status = "approved"
        cancellation.review_note = review_note
        cancellation.reviewed_by = reviewer
        cancellation.reviewed_at = timezone.now()
        cancellation.save(update_fields=[
            "status",
            "review_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ])

        order.order_status = "Cancelled"
        update_fields = ["order_status"]
        if order.payment_status.casefold() != "paid":
            order.payment_status = "Cancelled"
            update_fields.append("payment_status")
        order.save(update_fields=update_fields)
        _restore_inventory(order)
        _cancel_tracking(order)

        if order.payment_status.casefold() == "paid":
            provider = _payment_provider(order)
            amount, currency = _refund_amount(order, provider)
            refund = Refund.objects.create(
                cancellation_request=cancellation,
                payment_method=provider if provider in {"razorpay", "paypal", "offline"} else "unknown",
                amount=amount,
                currency=currency,
            )
            refund_id = refund.pk

    refund = None
    if refund_id is not None:
        refund = Refund.objects.get(pk=refund_id)
        if refund.payment_method in {"razorpay", "paypal"} and _payment_reference(
            refund.cancellation_request.order,
            refund.payment_method,
        ):
            refund = process_refund(refund.pk)
        elif refund.payment_method in {"razorpay", "paypal"}:
            refund.failure_reason = (
                "The payment capture reference is unavailable. Support must review this refund."
            )
            refund.save(update_fields=["failure_reason", "updated_at"])
        else:
            refund.failure_reason = (
                "This payment requires manual refund review by LocalMart support."
            )
            refund.save(update_fields=["failure_reason", "updated_at"])

    order = cancellation.order
    if refund:
        refund.refresh_from_db()
        refund_details = (
            f"Refund status: {refund.get_status_display()}. "
            f"Refund amount: {refund.amount} {refund.currency}."
        )
    else:
        refund_details = "No refund is due because the payment was not captured."
    _send_customer_email(
        order,
        f"Cancellation approved for order #{order.pk}",
        (
            f"Your cancellation for order #{order.pk} has been approved. {refund_details}"
            f"\n\nReview note: {review_note}"
        ),
    )
    return refund


def _provider_refund_status(provider_status):
    normalized = str(provider_status or "").strip().casefold()
    if normalized in {"processed", "completed", "succeeded"}:
        return "completed"
    if normalized in {"failed", "denied", "cancelled", "canceled"}:
        return "failed"
    return "processing"


def _save_refund_result(refund_id, provider_result):
    with transaction.atomic():
        refund = (
            Refund.objects.select_for_update()
            .select_related("cancellation_request__order")
            .get(pk=refund_id)
        )
        previous_status = refund.status
        gateway_refund_id = str(provider_result.get("id") or "").strip()
        if not gateway_refund_id:
            raise ValueError("The payment provider did not return a refund reference.")
        refund.gateway_refund_id = gateway_refund_id
        refund.status = _provider_refund_status(provider_result.get("status"))
        refund.failure_reason = (
            "The payment provider could not complete this refund."
            if refund.status == "failed"
            else ""
        )
        if refund.status == "completed":
            refund.completed_at = timezone.now()
            Order.objects.filter(pk=refund.cancellation_request.order_id).update(
                payment_status="Refunded",
                order_status="Refunded",
            )
        refund.save(update_fields=[
            "gateway_refund_id",
            "status",
            "failure_reason",
            "completed_at",
            "updated_at",
        ])
        if refund.status != previous_status:
            transaction.on_commit(lambda: _email_refund_status(refund.pk))
    return refund


def _email_refund_status(refund_id):
    refund = Refund.objects.select_related("cancellation_request__order").get(pk=refund_id)
    _send_customer_email(
        refund.cancellation_request.order,
        f"Refund update for order #{refund.cancellation_request.order_id}",
        (
            f"Your refund of {refund.amount} {refund.currency} for order "
            f"#{refund.cancellation_request.order_id} is {refund.get_status_display().lower()}."
            + (f"\n\n{refund.failure_reason}" if refund.failure_reason else "")
        ),
    )


def process_refund(refund_id, retry=False):
    with transaction.atomic():
        refund = (
            Refund.objects.select_for_update()
            .select_related("cancellation_request__order")
            .get(pk=refund_id)
        )
        if refund.cancellation_request.status != "approved":
            raise CancellationWorkflowError(
                "A refund cannot be initiated before the cancellation request is approved."
            )
        if refund.status == "completed" or (
            refund.status == "processing" and refund.gateway_refund_id
        ):
            return refund
        if refund.status == "failed" and not retry:
            return refund
        order = refund.cancellation_request.order
        provider = refund.payment_method
        payment_reference = _payment_reference(order, provider)
        if not payment_reference:
            refund.status = "failed"
            refund.failure_reason = (
                "The payment capture reference is unavailable. Support must review this refund."
            )
            refund.save(update_fields=["status", "failure_reason", "updated_at"])
            return refund
        refund.status = "processing"
        refund.failure_reason = ""
        if refund.initiated_at is None:
            refund.initiated_at = timezone.now()
        refund.save(update_fields=["status", "failure_reason", "initiated_at", "updated_at"])

    try:
        if provider == "razorpay":
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            provider_result = client.payment.refund(
                payment_reference,
                {
                    "amount": int(
                        (refund.amount * Decimal("100")).quantize(
                            Decimal("1"),
                            rounding=ROUND_HALF_UP,
                        )
                    ),
                    "notes": {
                        "order_id": str(order.pk),
                        "cancellation_id": str(refund.cancellation_request_id),
                    },
                },
                headers={"X-Razorpay-Idempotency-Key": str(refund.idempotency_key)},
            )
        elif provider == "paypal":
            access_token = _paypal_access_token()
            response = requests.post(
                f"{_paypal_base_url()}/v2/payments/captures/{payment_reference}/refund",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                    "PayPal-Request-Id": str(refund.idempotency_key),
                },
                json={
                    "amount": {
                        "value": f"{refund.amount:.2f}",
                        "currency_code": refund.currency,
                    },
                },
                timeout=20,
            )
            response.raise_for_status()
            provider_result = response.json()
        else:
            raise ValueError("Automatic refunds are not supported for this payment method.")
        refund = _save_refund_result(refund.pk, provider_result)
    except Exception as error:
        logger.error(
            "Refund initiation failed for order %s (%s).",
            order.pk,
            type(error).__name__,
        )
        refund = Refund.objects.get(pk=refund_id)
        refund.status = "failed"
        refund.failure_reason = (
            "We could not confirm the refund with the payment provider. "
            "LocalMart support can safely retry or review it."
        )
        refund.save(update_fields=["status", "failure_reason", "updated_at"])
        transaction.on_commit(lambda: _email_refund_status(refund_id))
    return refund


def complete_manual_refund(refund_id, reviewer):
    _validate_reviewer(reviewer, "store.change_refund")
    with transaction.atomic():
        refund = (
            Refund.objects.select_for_update()
            .select_related("cancellation_request__order")
            .get(pk=refund_id)
        )
        if refund.cancellation_request.status != "approved":
            raise CancellationWorkflowError(
                "A refund cannot be completed before the cancellation request is approved."
            )
        if refund.payment_method not in {"offline", "unknown"}:
            raise CancellationWorkflowError(
                "Only offline or unidentified payments can be completed manually."
            )
        if refund.status == "completed":
            return refund
        if refund.status not in {"pending", "failed"}:
            raise CancellationWorkflowError(
                "Only pending or failed manual refunds can be completed."
            )
        refund.status = "completed"
        refund.failure_reason = ""
        refund.completed_at = timezone.now()
        refund.completed_by = reviewer
        refund.save(update_fields=[
            "status",
            "failure_reason",
            "completed_by",
            "completed_at",
            "updated_at",
        ])
        Order.objects.filter(pk=refund.cancellation_request.order_id).update(
            payment_status="Refunded",
            order_status="Refunded",
        )
        refund_id = refund.pk
        transaction.on_commit(lambda: _email_refund_status(refund_id))
    return refund


def refresh_refund_status(refund_id):
    refund = Refund.objects.select_related("cancellation_request__order").get(pk=refund_id)
    if refund.cancellation_request.status != "approved":
        raise CancellationWorkflowError(
            "Refund status is available after the cancellation request is approved."
        )
    if not refund.gateway_refund_id:
        return refund

    try:
        if refund.payment_method == "razorpay":
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            provider_result = client.refund.fetch(refund.gateway_refund_id)
        elif refund.payment_method == "paypal":
            access_token = _paypal_access_token()
            response = requests.get(
                f"{_paypal_base_url()}/v2/payments/refunds/{refund.gateway_refund_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            response.raise_for_status()
            provider_result = response.json()
        else:
            return refund
        return _save_refund_result(refund.pk, provider_result)
    except Exception as error:
        logger.error(
            "Refund status refresh failed for order %s (%s).",
            refund.cancellation_request.order_id,
            type(error).__name__,
        )
        raise CancellationWorkflowError(
            "The payment provider could not be reached. The refund status was not changed."
        ) from None


def _paypal_access_token():
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise ValueError("PayPal credentials are not configured.")
    response = requests.post(
        f"{_paypal_base_url()}/v1/oauth2/token",
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _paypal_base_url():
    return (
        "https://api-m.paypal.com"
        if settings.PAYPAL_MODE == "live"
        else "https://api-m.sandbox.paypal.com"
    )
