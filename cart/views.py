import json
import re
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import Cart, CartItem, CatalogProduct
from .services import (
    PRODUCT_TYPES,
    add_product_to_cart,
    evaluate_marketplace_coupon,
    get_customer_cart,
    get_inventory_product,
    get_product_stock,
    serialize_cart,
)
from store.models import MarketplaceCoupon
from .static_catalog import StaticCatalogError, resolve_static_catalog_item


def _json_body(request):
    try:
        value = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _cart_response(cart, *, status=200, **extra):
    return JsonResponse({"success": status < 400, **serialize_cart(cart), **extra}, status=status)


@require_http_methods(["GET", "DELETE"])
def cart_api(request):
    cart = get_customer_cart(request)
    if request.method == "DELETE":
        cart.items.all().delete()
        if cart.coupon_code:
            cart.coupon_code = ""
            cart.save(update_fields=["coupon_code", "updated_at"])
    return _cart_response(cart)


@require_http_methods(["GET", "POST", "DELETE"])
def cart_coupon_api(request):
    cart = get_customer_cart(request)
    if request.method == "GET":
        cart_data = serialize_cart(cart)
        subtotal = Decimal(cart_data["subtotal"])
        available_coupons = [
            evaluate_marketplace_coupon(
                coupon,
                subtotal,
                cart_data["coupon_category_subtotals"],
            )
            for coupon in MarketplaceCoupon.objects.filter(active=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .order_by("minimum_order_amount", "-discount_value")
        ]
        return JsonResponse({
            "success": True,
            **cart_data,
            "available_coupons": available_coupons,
        })

    if request.method == "DELETE":
        cart.coupon_code = ""
        cart.save(update_fields=["coupon_code", "updated_at"])
        return _cart_response(cart, message="Coupon removed.")

    data = _json_body(request)
    code = data.get("code") if data else None
    if not isinstance(code, str):
        return JsonResponse({"success": False, "message": "Enter a valid coupon code."}, status=400)
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,39}", code):
        return JsonResponse({
            "success": False,
            "message": "Coupon codes must be 2-40 letters, numbers, hyphens, or underscores.",
        }, status=400)

    coupon = MarketplaceCoupon.objects.filter(code__iexact=code).first()
    if coupon is None:
        return JsonResponse({"success": False, "message": "That coupon code is not available."}, status=400)
    cart_data = serialize_cart(cart)
    subtotal = Decimal(cart_data["subtotal"])
    result = evaluate_marketplace_coupon(
        coupon,
        subtotal,
        cart_data["coupon_category_subtotals"],
    )
    if not result["eligible"]:
        return JsonResponse({"success": False, "message": result["reason"], "coupon": result}, status=400)

    cart.coupon_code = coupon.code
    cart.save(update_fields=["coupon_code", "updated_at"])
    return _cart_response(cart, message=f"Coupon {coupon.code} applied successfully.")


@require_http_methods(["GET"])
@ensure_csrf_cookie
def cart_count_api(request):
    cart = get_customer_cart(request)
    count = sum(cart.items.values_list("quantity", flat=True))
    return JsonResponse({"success": True, "count": count})


@require_http_methods(["POST"])
def cart_items_api(request):
    data = _json_body(request)
    if data is None:
        return JsonResponse({"success": False, "message": "Invalid JSON request."}, status=400)

    source = str(data.get("source", "")).strip()
    if source not in PRODUCT_TYPES:
        return JsonResponse({"success": False, "message": "Unknown product catalog."}, status=400)

    raw_product_id = data.get("product_id")
    if isinstance(raw_product_id, bool):
        return JsonResponse({"success": False, "message": "Invalid product ID."}, status=400)
    if source == "catalog":
        product_id = str(raw_product_id or "").strip()
        if not product_id or len(product_id) > 160:
            return JsonResponse({"success": False, "message": "Invalid catalog key."}, status=400)
    else:
        if not str(raw_product_id or "").isdigit():
            return JsonResponse({"success": False, "message": "Invalid product ID."}, status=400)
        product_id = int(raw_product_id)

    raw_quantity = data.get("quantity", 1)
    if isinstance(raw_quantity, bool):
        return JsonResponse({"success": False, "message": "Invalid quantity."}, status=400)
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "message": "Invalid quantity."}, status=400)
    if quantity < 1:
        return JsonResponse({"success": False, "message": "Quantity must be at least one."}, status=400)
    cart, message, status = add_product_to_cart(request, source, product_id, quantity)
    if cart is None:
        return JsonResponse({"success": False, "message": message}, status=status)

    return _cart_response(cart, message="Product added to cart successfully.")


@require_http_methods(["PATCH", "DELETE"])
def cart_item_api(request, item_id):
    cart = get_customer_cart(request)
    item = CartItem.objects.filter(cart=cart, pk=item_id).first()
    if item is None:
        return JsonResponse({"success": False, "message": "Cart item not found."}, status=404)

    if request.method == "DELETE":
        item.delete()
        return _cart_response(cart, message="Product removed from cart.")

    data = _json_body(request)
    if data is None:
        return JsonResponse({"success": False, "message": "Invalid JSON request."}, status=400)
    raw_quantity = data.get("quantity")
    if isinstance(raw_quantity, bool):
        return JsonResponse({"success": False, "message": "Invalid quantity."}, status=400)
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "message": "Invalid quantity."}, status=400)
    if quantity < 1:
        return JsonResponse({"success": False, "message": "Quantity cannot be less than one."}, status=400)
    with transaction.atomic():
        Cart.objects.select_for_update().get(pk=cart.pk)
        item = CartItem.objects.select_for_update().filter(cart=cart, pk=item_id).first()
        if item is None:
            return JsonResponse({"success": False, "message": "Cart item not found."}, status=404)
        source = next(
            (key for key, model in PRODUCT_TYPES.items() if model._meta.model_name == item.content_type.model),
            None,
        )
        product = get_inventory_product(source, item.object_id, lock=True) if source else None
        if product is None:
            return JsonResponse({"success": False, "message": "Product is no longer available."}, status=409)
        stock = get_product_stock(product)
        if stock is None and quantity > 99:
            return JsonResponse({"success": False, "message": "Quantity cannot exceed 99."}, status=400)
        if stock is not None and quantity > stock:
            return JsonResponse({
                "success": False,
                "message": f"Only {stock} item(s) are available.",
                "available_stock": stock,
            }, status=409)
        item.quantity = quantity
        item.save(update_fields=["quantity"])

    return _cart_response(cart)


@require_http_methods(["POST"])
def cart_import_local_api(request):
    data = _json_body(request)
    if data is None or not isinstance(data.get("items"), list):
        return JsonResponse({"success": False, "message": "Invalid local cart request."}, status=400)

    raw_items = data["items"]
    if not raw_items or len(raw_items) > 100:
        return JsonResponse({"success": False, "message": "The cart must contain between 1 and 100 products."}, status=400)

    resolved_items = {}
    try:
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                return JsonResponse({"success": False, "message": "Invalid product in cart."}, status=400)

            name = str(raw_item.get("name") or "").strip()
            product = resolve_static_catalog_item(raw_item)
            if product is None:
                display_name = name or "A product"
                return JsonResponse({
                    "success": False,
                    "message": f"{display_name} could not be verified against the current catalog.",
                }, status=409)

            raw_quantity = raw_item.get("quantity", 1)
            if isinstance(raw_quantity, bool):
                return JsonResponse({"success": False, "message": "Invalid product quantity."}, status=400)
            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                return JsonResponse({"success": False, "message": "Invalid product quantity."}, status=400)
            if quantity < 1 or quantity > 99:
                return JsonResponse({"success": False, "message": "Product quantity must be between 1 and 99."}, status=400)

            entry = resolved_items.setdefault(
                product["catalog_key"],
                {"product": product, "quantity": 0},
            )
            entry["quantity"] += quantity
            if entry["quantity"] > 99:
                return JsonResponse({"success": False, "message": "Product quantity must be between 1 and 99."}, status=400)
    except StaticCatalogError as error:
        return JsonResponse({"success": False, "message": str(error)}, status=503)

    class ImportConflict(Exception):
        pass

    try:
        with transaction.atomic():
            cart = get_customer_cart(request)
            Cart.objects.select_for_update().get(pk=cart.pk)
            imports = []

            for entry in resolved_items.values():
                catalog_item = entry["product"]
                product, _ = CatalogProduct.objects.get_or_create(
                    catalog_key=catalog_item["catalog_key"],
                    defaults={
                        "name": catalog_item["name"],
                        "category": catalog_item["category"],
                        "price": catalog_item["price"],
                        "stock": catalog_item["stock"],
                        "stock_tracked": catalog_item["stock_tracked"],
                        "image": catalog_item["image"],
                        "is_active": True,
                    },
                )
                if not product.is_active:
                    raise ImportConflict(f"{product.name} is no longer available.")

                content_type = ContentType.objects.get_for_model(product)
                item = CartItem.objects.select_for_update().filter(
                    cart=cart,
                    content_type=content_type,
                    object_id=product.pk,
                ).first()
                quantity = max(item.quantity if item else 0, entry["quantity"])
                stock = get_product_stock(product)
                if stock is None and quantity > 99:
                    raise ImportConflict("A product quantity cannot exceed 99.")
                if stock is not None and quantity > stock:
                    raise ImportConflict(f"Only {stock} {product.name}(s) are available.")
                imports.append((product, content_type, item, quantity))

            for product, content_type, item, quantity in imports:
                if item:
                    if item.quantity != quantity:
                        item.quantity = quantity
                        item.save(update_fields=["quantity"])
                else:
                    CartItem.objects.create(
                        cart=cart,
                        content_type=content_type,
                        object_id=product.pk,
                        quantity=quantity,
                    )
    except ImportConflict as error:
        return JsonResponse({"success": False, "message": str(error)}, status=409)

    return _cart_response(cart, message="Products verified and added to your cart.")


@ensure_csrf_cookie
def cart_page(request):
    return render(request, "cart.html")
