from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from electronics.models import ElectronicsProduct
from merchants.models import MerchantProduct
from products.models import Product

from store.models import MarketplaceCoupon

from .models import Cart, CartItem, CatalogProduct


PRODUCT_TYPES = {
    "product": Product,
    "electronics": ElectronicsProduct,
    "merchant": MerchantProduct,
    "catalog": CatalogProduct,
}
SOURCE_BY_MODEL = {
    model._meta.model_name: source
    for source, model in PRODUCT_TYPES.items()
}
HOME_APPLIANCE_CATEGORIES = {
    "refrigerators",
    "washing machines",
    "air conditioners",
    "televisions",
    "microwave ovens",
    "mixer grinders",
    "air fryers",
    "fans",
    "vacuum cleaners",
    "water purifiers",
    "geysers",
    "dishwashers",
    "induction cooktops",
    "kitchen chimneys",
}
FOOD_CATEGORIES = {"burgers", "coffee", "juices", "pizza", "south indian", "tea"}


def get_customer_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart

    if not request.session.session_key:
        request.session.create()
    cart, _ = Cart.objects.get_or_create(session_key=request.session.session_key)
    return cart


def get_inventory_product(source, product_id, *, lock=False):
    model = PRODUCT_TYPES.get(source)
    if model is None:
        return None

    queryset = model.objects.all()
    if lock:
        queryset = queryset.select_for_update()

    if source == "electronics":
        queryset = queryset.filter(is_active=True)
    elif source == "merchant":
        queryset = queryset.filter(is_active=True, merchant__is_approved=True)
    elif source == "catalog":
        queryset = queryset.filter(is_active=True)

    try:
        if source == "catalog":
            product = queryset.filter(catalog_key=str(product_id)).first()
            if product is not None:
                return product
            if str(product_id).isdigit():
                return queryset.filter(pk=int(product_id)).first()
            return None
        return queryset.get(pk=product_id)
    except (model.DoesNotExist, ValueError, TypeError):
        return None


def get_product_stock(product):
    if isinstance(product, CatalogProduct) and not product.stock_tracked:
        return None
    return int(getattr(product, "stock", 0))


def get_product_price(product):
    if isinstance(product, ElectronicsProduct):
        return product.discounted_price
    return product.price


def get_product_category(product):
    category = getattr(product, "category", "")
    if category is None:
        return ""
    if hasattr(category, "name"):
        return category.name
    return str(category)


def get_product_merchant(product):
    merchant = getattr(product, "merchant", None)
    if merchant:
        return merchant.shop_name
    return str(getattr(product, "merchant_name", "") or "")


def get_product_image(product):
    image = getattr(product, "image", None)
    if not image:
        return ""
    return getattr(image, "url", str(image))


def marketplace_category_group(category, *, source=None, catalog_key=""):
    if source == "merchant":
        return "Food"
    if source == "electronics":
        return "Electronics"

    category = str(category or "").strip()
    normalized = category.casefold()
    prefix = normalized.split("/", 1)[0].strip()
    category_groups = {
        "food": "Food",
        "grocery": "Grocery",
        "shopping": "Shopping",
        "fashion": "Shopping",
        "electronics": "Electronics",
        "home appliances": "Home Appliances",
    }
    if prefix in category_groups:
        return category_groups[prefix]
    if normalized in HOME_APPLIANCE_CATEGORIES:
        return "Home Appliances"
    if normalized in FOOD_CATEGORIES:
        return "Food"
    if str(catalog_key).casefold().startswith("fashion:"):
        return "Shopping"
    return "Marketplace"


def get_product_marketplace_category(product, source):
    return marketplace_category_group(
        get_product_category(product),
        source=source,
        catalog_key=getattr(product, "catalog_key", ""),
    )


def evaluate_marketplace_coupon(coupon, subtotal, category_subtotals=None):
    discount_value = coupon.discount_value
    eligible_categories = coupon.eligible_categories or []
    eligible_subtotal = (
        sum(
            (Decimal(str((category_subtotals or {}).get(category, "0.00"))) for category in eligible_categories),
            Decimal("0.00"),
        )
        if eligible_categories
        else subtotal
    )
    result = {
        "code": coupon.code,
        "description": coupon.description,
        "discount_type": coupon.discount_type,
        "discount_value": str(discount_value),
        "eligible_categories": eligible_categories,
        "eligible_subtotal": str(eligible_subtotal),
        "minimum_order_amount": str(coupon.minimum_order_amount),
        "maximum_discount_amount": (
            str(coupon.maximum_discount_amount)
            if coupon.maximum_discount_amount is not None
            else None
        ),
        "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
        "eligible": False,
        "discount_amount": "0.00",
        "reason": "",
    }

    if not coupon.active:
        result["reason"] = "This coupon is no longer active."
    elif coupon.expires_at and coupon.expires_at <= timezone.now():
        result["reason"] = "This coupon has expired."
    elif eligible_subtotal <= 0 and eligible_categories:
        result["reason"] = (
            f"This coupon applies only to {', '.join(eligible_categories)} products."
        )
    elif eligible_subtotal <= 0:
        result["reason"] = "Add products to your cart to use this coupon."
    elif eligible_subtotal < coupon.minimum_order_amount:
        target = (
            f"eligible {', '.join(eligible_categories)} items"
            if eligible_categories
            else "your order"
        )
        result["reason"] = (
            f"Add {coupon.minimum_order_amount - eligible_subtotal:.2f} more to {target} "
            "to use this coupon."
        )
    elif coupon.discount_type == "percentage":
        if discount_value <= 0 or discount_value > 100:
            result["reason"] = "This coupon has an invalid discount."
        else:
            discount = (eligible_subtotal * discount_value / Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if coupon.maximum_discount_amount is not None:
                discount = min(discount, coupon.maximum_discount_amount)
            discount = min(discount, eligible_subtotal)
            result["eligible"] = True
            result["discount_amount"] = str(discount)
    elif coupon.discount_type == "fixed":
        if discount_value <= 0:
            result["reason"] = "This coupon has an invalid discount."
        else:
            discount = min(discount_value, eligible_subtotal)
            if coupon.maximum_discount_amount is not None:
                discount = min(discount, coupon.maximum_discount_amount)
            result["eligible"] = discount > 0
            result["discount_amount"] = str(discount)
            if not result["eligible"]:
                result["reason"] = "This coupon has an invalid discount."
    else:
        result["reason"] = "This coupon has an invalid discount type."
    return result


def get_cart_category_subtotals(cart):
    category_subtotals = {}
    for item in cart.items.select_related("content_type"):
        product = item.product
        if product is None:
            continue
        source = SOURCE_BY_MODEL.get(item.content_type.model)
        if source is None:
            continue
        category = get_product_marketplace_category(product, source)
        category_subtotals[category] = (
            category_subtotals.get(category, Decimal("0.00"))
            + get_product_price(product) * item.quantity
        )
    return {category: str(amount) for category, amount in category_subtotals.items()}


def get_applied_marketplace_coupon(cart, subtotal, category_subtotals=None):
    code = cart.coupon_code.strip()
    if not code:
        return None
    coupon = MarketplaceCoupon.objects.filter(code__iexact=code).first()
    if coupon is None:
        return {
            "code": code,
            "eligible": False,
            "discount_amount": "0.00",
            "reason": "This coupon is no longer available.",
        }
    if category_subtotals is None:
        category_subtotals = get_cart_category_subtotals(cart)
    return evaluate_marketplace_coupon(coupon, subtotal, category_subtotals)


def add_product_to_cart(request, source, product_id, quantity=1):
    with transaction.atomic():
        product = get_inventory_product(source, product_id, lock=True)
        if product is None:
            return None, "Product is not available in the verified catalog.", 404

        cart = get_customer_cart(request)
        Cart.objects.select_for_update().get(pk=cart.pk)
        content_type = ContentType.objects.get_for_model(product)
        item = CartItem.objects.select_for_update().filter(
            cart=cart,
            content_type=content_type,
            object_id=product.pk,
        ).first()
        existing_quantity = item.quantity if item else 0
        stock = get_product_stock(product)
        if stock is not None and stock < 1:
            return None, "Product is out of stock.", 409
        if stock is None and existing_quantity + quantity > 99:
            return None, "A product quantity cannot exceed 99.", 409
        if stock is not None and existing_quantity + quantity > stock:
            return None, f"Only {stock} item(s) are available.", 409

        if item:
            item.quantity += quantity
            item.save(update_fields=["quantity"])
        else:
            CartItem.objects.create(
                cart=cart,
                content_type=content_type,
                object_id=product.pk,
                quantity=quantity,
            )

    return cart, "", 200


def serialize_cart(cart):
    items = []
    count = 0
    subtotal = Decimal("0.00")
    category_subtotals = {}

    for item in cart.items.select_related("content_type").order_by("id"):
        product = item.product
        if product is None:
            continue

        price = get_product_price(product)
        line_total = price * item.quantity
        count += item.quantity
        subtotal += line_total
        source = SOURCE_BY_MODEL.get(item.content_type.model, item.content_type.model)
        marketplace_category = get_product_marketplace_category(product, source)
        category_subtotals[marketplace_category] = (
            category_subtotals.get(marketplace_category, Decimal("0.00"))
            + line_total
        )
        serialized_item = {
            "item_id": item.pk,
            "source": source,
            "product_id": item.object_id,
            "name": product.name,
            "category": get_product_category(product),
            "marketplace_category": marketplace_category,
            "merchant_name": get_product_merchant(product),
            "price": str(price),
            "quantity": item.quantity,
            "stock": get_product_stock(product),
            "subtotal": str(line_total),
            "image": get_product_image(product),
        }
        if isinstance(product, MerchantProduct):
            serialized_item.update({
                "merchant_id": product.merchant_id,
                "merchant_product_id": product.pk,
                "restaurant_name": product.merchant.shop_name,
            })
        items.append(serialized_item)

    serialized_category_subtotals = {
        category: str(amount)
        for category, amount in category_subtotals.items()
    }
    coupon = get_applied_marketplace_coupon(
        cart,
        subtotal,
        serialized_category_subtotals,
    )
    coupon_discount = (
        Decimal(coupon["discount_amount"])
        if coupon and coupon["eligible"]
        else Decimal("0.00")
    )
    taxable_subtotal = subtotal - coupon_discount
    tax = (taxable_subtotal * Decimal("0.05")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return {
        "items": items,
        "item_count": count,
        "line_count": len(items),
        "subtotal": str(subtotal),
        "coupon_category_subtotals": serialized_category_subtotals,
        "coupon": coupon,
        "coupon_discount": str(coupon_discount),
        "tax": str(tax),
        "total": str(taxable_subtotal + tax),
    }


def merge_guest_cart(user, session_key):
    if not session_key:
        return

    guest_cart = Cart.objects.filter(session_key=session_key).first()
    if guest_cart is None:
        return

    customer_cart, _ = Cart.objects.get_or_create(user=user)
    with transaction.atomic():
        Cart.objects.select_for_update().get(pk=customer_cart.pk)
        for guest_item in guest_cart.items.select_related("content_type").all():
            product = guest_item.product
            if product is None:
                continue

            stock = get_product_stock(product)
            if stock is not None and stock < 1:
                continue

            customer_item = CartItem.objects.filter(
                cart=customer_cart,
                content_type=guest_item.content_type,
                object_id=guest_item.object_id,
            ).first()
            if customer_item is None:
                CartItem.objects.create(
                    cart=customer_cart,
                    content_type=guest_item.content_type,
                    object_id=guest_item.object_id,
                    quantity=min(stock, guest_item.quantity) if stock is not None else guest_item.quantity,
                )
            else:
                customer_item.quantity = (
                    min(stock, guest_item.quantity + customer_item.quantity)
                    if stock is not None
                    else min(99, guest_item.quantity + customer_item.quantity)
                )
                customer_item.save(update_fields=["quantity"])

        guest_cart.orders.update(cart=customer_cart)
        if not customer_cart.coupon_code and guest_cart.coupon_code:
            customer_cart.coupon_code = guest_cart.coupon_code
            customer_cart.save(update_fields=["coupon_code", "updated_at"])
        guest_cart.delete()
